// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// JTAG-to-AXI4 bridge core (vendor-agnostic).
//
// TAP signals are provided by an external vendor-specific wrapper.
// Uses a 72-bit pipelined streaming DR: each scan shifts in a command
// and shifts out the previous result.  One AXI transaction per scan,
// zero polling.
//
// Parameters:
//   ADDR_W     - AXI address width (default 32)
//   DATA_W     - AXI data width    (default 32)
//   FIFO_DEPTH - async read FIFO depth for burst reads (default 16)
//   TIMEOUT    - AXI ready timeout in axi_clk cycles   (default 4096)
//
// 72-bit DR format (LSB first):
//   Shift-in:  [31:0] addr, [63:32] payload, [67:64] wstrb, [71:68] cmd
//   Shift-out: [31:0] rdata, [63:32] info, [65:64] resp, [67:66] rsvd, [71:68] status

module fcapz_ejtagaxi #(
    parameter ADDR_W     = 32,
    parameter DATA_W     = 32,
    parameter FIFO_DEPTH = 16,
    parameter TIMEOUT    = 4096,
    parameter USE_BEHAV_ASYNC_FIFO    = 1
) (
    // TAP signals (from vendor-specific wrapper)
    input  wire        tck,
    input  wire        tdi,
    output wire        tdo,
    input  wire        capture,
    input  wire        shift_en,
    input  wire        update,
    input  wire        sel,

    // AXI4 master interface
    input  wire                    axi_clk,
    input  wire                    axi_rst,
    // Write address
    output reg  [ADDR_W-1:0]      m_axi_awaddr,
    output reg  [7:0]             m_axi_awlen,
    output reg  [2:0]             m_axi_awsize,
    output reg  [1:0]             m_axi_awburst,
    output reg                    m_axi_awvalid,
    input  wire                   m_axi_awready,
    output wire [2:0]             m_axi_awprot,
    // Write data
    output reg  [DATA_W-1:0]     m_axi_wdata,
    output reg  [DATA_W/8-1:0]   m_axi_wstrb,
    output reg                    m_axi_wvalid,
    input  wire                   m_axi_wready,
    output reg                    m_axi_wlast,
    // Write response
    input  wire [1:0]             m_axi_bresp,
    input  wire                   m_axi_bvalid,
    output reg                    m_axi_bready,
    // Read address
    output reg  [ADDR_W-1:0]     m_axi_araddr,
    output reg  [7:0]            m_axi_arlen,
    output reg  [2:0]            m_axi_arsize,
    output reg  [1:0]            m_axi_arburst,
    output reg                    m_axi_arvalid,
    input  wire                   m_axi_arready,
    output wire [2:0]             m_axi_arprot,
    // Read data
    input  wire [DATA_W-1:0]     m_axi_rdata,
    input  wire [1:0]            m_axi_rresp,
    input  wire                   m_axi_rvalid,
    input  wire                   m_axi_rlast,
    output reg                    m_axi_rready
);

    // ---- Constants -----------------------------------------------------------
    localparam DR_W = 72;

    // Commands
    localparam CMD_NOP         = 4'h0;
    localparam CMD_WRITE       = 4'h1;
    localparam CMD_READ        = 4'h2;
    localparam CMD_WRITE_INC   = 4'h3;
    localparam CMD_READ_INC    = 4'h4;
    localparam CMD_SET_ADDR    = 4'h5;
    localparam CMD_BURST_SETUP = 4'h6;
    localparam CMD_BURST_WDATA = 4'h7;
    localparam CMD_BURST_RDATA = 4'h8;
    localparam CMD_BURST_RSTART= 4'h9;
    localparam CMD_CONFIG      = 4'hE;
    localparam CMD_RESET       = 4'hF;

    // AXI FSM states
    localparam [3:0] ST_IDLE        = 4'd0,
                     ST_AW_W        = 4'd1,
                     ST_WAIT_B      = 4'd2,
                     ST_AR          = 4'd3,
                     ST_WAIT_R      = 4'd4,
                     ST_BURST_AW_W  = 4'd5,
                     ST_BURST_W     = 4'd6,
                     ST_BURST_AR    = 4'd7,
                     ST_BURST_R_FILL= 4'd8,
                     ST_DONE        = 4'd9,
                     ST_TIMEOUT_ERR = 4'd10;

    // Config register addresses
    localparam CFG_BRIDGE_ID = 16'h0000;
    localparam CFG_VERSION   = 16'h0004;
    localparam CFG_FEATURES  = 16'h002C;

    // Unprivileged, non-secure, data access
    assign m_axi_awprot = 3'b000;
    assign m_axi_arprot = 3'b000;

    // ---- Async FIFO pointer width --------------------------------------------
    localparam FIFO_AW = $clog2(FIFO_DEPTH);
    // Encoded into FEATURES[23:16] as (FIFO_DEPTH-1) so 256 fits in 8 bits.
    localparam [7:0] FIFO_DEPTH_ENC = FIFO_DEPTH - 1;

    // ---- Parameter assertions ------------------------------------------------
    // FIFO_DEPTH bounds: must be >=1, <=256 (AXI4 burst max), and power of 2
    // (required by the async FIFO).  Synthesis-safe trap + sim $error.
    generate
        if (FIFO_DEPTH < 1 || FIFO_DEPTH > 256)
            FIFO_DEPTH_must_be_between_1_and_256 _fifo_depth_check_FAILED();
        if (FIFO_DEPTH & (FIFO_DEPTH - 1))
            FIFO_DEPTH_must_be_power_of_2 _fifo_depth_pow2_check_FAILED();
    endgenerate
    initial begin
        if (FIFO_DEPTH < 1 || FIFO_DEPTH > 256)
            $error("fcapz_ejtagaxi: FIFO_DEPTH must be 1..256 (got %0d)", FIFO_DEPTH);
        if (FIFO_DEPTH & (FIFO_DEPTH - 1))
            $error("fcapz_ejtagaxi: FIFO_DEPTH must be a power of 2 (got %0d)", FIFO_DEPTH);
    end

    // ========================================================================
    //  TCK domain registers
    // ========================================================================

    // 72-bit shift register
    reg [DR_W-1:0] sr;
    assign tdo = sr[0];

    // Parsed command fields (active during update)
    wire [31:0] sr_addr    = sr[31:0];
    wire [31:0] sr_payload = sr[63:32];
    wire [3:0]  sr_wstrb   = sr[67:64];
    wire [3:0]  sr_cmd     = sr[71:68];

    // Auto-increment address
    reg [ADDR_W-1:0] auto_inc_addr;

    // Burst config latches
    reg [7:0]        burst_awlen;
    reg [2:0]        burst_awsize;
    reg [1:0]        burst_awburst;
    reg [ADDR_W-1:0] burst_addr;

    // CDC shadow registers (tck -> axi_clk, stable when req_toggle != ack_toggle)
    reg [3:0]           shadow_cmd;
    reg [ADDR_W-1:0]    shadow_addr;
    reg [DATA_W-1:0]    shadow_wdata;
    reg [DATA_W/8-1:0]  shadow_wstrb;
    reg [7:0]           shadow_burst_len;
    reg [2:0]           shadow_burst_size;
    reg [1:0]           shadow_burst_type;

    // Toggle handshake (tck side)
    reg req_toggle;

    // 2-FF sync of ack_toggle into tck domain
    (* ASYNC_REG = "TRUE" *) reg ack_toggle_sync1, ack_toggle_sync2;
    wire cdc_idle = (req_toggle == ack_toggle_sync2);

    // 2-FF sync of response data (axi_clk -> tck)
    (* ASYNC_REG = "TRUE" *) reg [DATA_W-1:0] resp_rdata_sync1, resp_rdata_sync2;
    (* ASYNC_REG = "TRUE" *) reg [1:0]        resp_code_sync1,  resp_code_sync2;

    // Status bits
    reg prev_valid;
    reg busy;
    reg error_sticky;
    reg ack_toggle_prev;

    // Last command tracker (for capture-time data source selection)
    reg [3:0] last_cmd;

    // ---- Async FIFO instance (burst read buffer) -----------------------------
    wire                  fifo_wr_en;
    wire                  fifo_full;
    wire                  fifo_rd_en;
    wire [DATA_W-1:0]     fifo_rdata;
    wire                  fifo_empty;
    wire [FIFO_AW:0]      fifo_rd_count;
    wire                  fifo_notempty = !fifo_empty;
    wire [7:0]            fifo_count   = fifo_rd_count[FIFO_AW:0];

    // FIFO reset: asserted by AXI domain on CMD_RESET
    reg fifo_rst_axi;

    fcapz_async_fifo #(
        .DATA_W  (DATA_W),
        .DEPTH   (FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO (USE_BEHAV_ASYNC_FIFO)
    ) u_burst_fifo (
        .wr_clk   (axi_clk),
        .wr_rst   (axi_rst | fifo_rst_axi),
        .wr_en    (fifo_wr_en),
        .wr_data  (m_axi_rdata),
        .wr_full  (fifo_full),
        .rd_clk   (tck),
        .rd_rst   (1'b0),
        .rd_en    (fifo_rd_en),
        .rd_data  (fifo_rdata),
        .rd_empty (fifo_empty),
        .rd_count (fifo_rd_count),
        .wr_count ()
    );

    // FIFO read: pop on UPDATE when BURST_RDATA and previous scan also read
    assign fifo_rd_en = sel && update && (sr_cmd == CMD_BURST_RDATA) &&
                        fifo_notempty && (last_cmd == CMD_BURST_RDATA);

    // Config read value (latched at update time when cmd=CONFIG)
    reg [31:0] config_rdata;

    // Capture-time data source mux
    wire ack_edge = (ack_toggle_sync2 != ack_toggle_prev);

    wire [31:0] capture_rdata =
        (last_cmd == CMD_CONFIG)                       ? config_rdata      :
        (last_cmd == CMD_BURST_RDATA && fifo_notempty) ? fifo_rdata        :
        ack_edge                                       ? resp_rdata_sync2  :
                                                         {DATA_W{1'b0}};

    wire [1:0] capture_resp =
        ack_edge ? resp_code_sync2 : 2'b00;

    wire capture_prev_valid =
        (last_cmd == CMD_CONFIG)                       ||
        (last_cmd == CMD_BURST_RDATA && fifo_notempty) ||
        ack_edge;

    wire [31:0] info_field   = {8'd0, fifo_count, auto_inc_addr[15:0]};
    wire [3:0]  status_bits  = {fifo_notempty, error_sticky, busy, prev_valid};

    // ---- TCK: 2-FF synchronizers --------------------------------------------
    always @(posedge tck) begin
        // ack_toggle sync (axi_clk -> tck)
        ack_toggle_sync1 <= ack_toggle;
        ack_toggle_sync2 <= ack_toggle_sync1;
        // response data sync (axi_clk -> tck)
        resp_rdata_sync1 <= resp_rdata;
        resp_rdata_sync2 <= resp_rdata_sync1;
        resp_code_sync1  <= resp_code;
        resp_code_sync2  <= resp_code_sync1;
    end

    // ---- TCK: main CAPTURE / SHIFT / UPDATE logic ---------------------------
    always @(posedge tck) begin

        if (sel) begin
            if (capture) begin
                // Consume ack edge only during capture so it stays sticky
                // until the next scan's capture phase reads it
                ack_toggle_prev <= ack_toggle_sync2;

                // Assemble shift-out register from computed mux outputs
                if (capture_prev_valid) begin
                    prev_valid <= 1'b1;
                end
                if (ack_edge) begin
                    busy <= 1'b0;
                end
                // Set error_sticky on error response
                if (ack_edge && resp_code_sync2 != 2'b00) begin
                    error_sticky <= 1'b1;
                end

                // Build status with live values that reflect this capture's updates
                sr <= {{fifo_notempty,
                        error_sticky | (ack_edge & (resp_code_sync2 != 2'b00)),
                        busy & ~ack_edge,
                        capture_prev_valid},
                       2'b00, capture_resp, info_field, capture_rdata};

            end else if (shift_en) begin
                sr <= {tdi, sr[DR_W-1:1]};

            end else if (update) begin
                prev_valid <= 1'b0;

                case (sr_cmd)
                    CMD_NOP: begin
                        // No operation
                    end

                    CMD_SET_ADDR: begin
                        auto_inc_addr <= sr_addr;
                    end

                    CMD_WRITE: begin
                        if (cdc_idle) begin
                            shadow_cmd   <= CMD_WRITE;
                            shadow_addr  <= sr_addr;
                            shadow_wdata <= sr_payload;
                            shadow_wstrb <= sr_wstrb;
                            req_toggle   <= ~req_toggle;
                            busy         <= 1'b1;
                        end
                    end

                    CMD_READ: begin
                        if (cdc_idle) begin
                            shadow_cmd  <= CMD_READ;
                            shadow_addr <= sr_addr;
                            req_toggle  <= ~req_toggle;
                            busy        <= 1'b1;
                        end
                    end

                    CMD_WRITE_INC: begin
                        if (cdc_idle) begin
                            shadow_cmd    <= CMD_WRITE;
                            shadow_addr   <= auto_inc_addr;
                            shadow_wdata  <= sr_payload;
                            shadow_wstrb  <= sr_wstrb;
                            req_toggle    <= ~req_toggle;
                            busy          <= 1'b1;
                            auto_inc_addr <= auto_inc_addr + 4;
                        end
                    end

                    CMD_READ_INC: begin
                        if (cdc_idle) begin
                            shadow_cmd    <= CMD_READ;
                            shadow_addr   <= auto_inc_addr;
                            req_toggle    <= ~req_toggle;
                            busy          <= 1'b1;
                            auto_inc_addr <= auto_inc_addr + 4;
                        end
                    end

                    CMD_BURST_SETUP: begin
                        burst_addr    <= sr_addr;
                        burst_awlen   <= sr_payload[7:0];
                        burst_awsize  <= sr_payload[10:8];
                        burst_awburst <= sr_payload[13:12];
                    end

                    CMD_BURST_WDATA: begin
                        if (cdc_idle) begin
                            shadow_cmd        <= CMD_BURST_WDATA;
                            shadow_addr       <= burst_addr;
                            shadow_wdata      <= sr_payload;
                            shadow_wstrb      <= sr_wstrb;
                            shadow_burst_len  <= burst_awlen;
                            shadow_burst_size <= burst_awsize;
                            shadow_burst_type <= burst_awburst;
                            req_toggle        <= ~req_toggle;
                            busy              <= 1'b1;
                        end
                    end

                    CMD_BURST_RSTART: begin
                        if (cdc_idle) begin
                            shadow_cmd        <= CMD_BURST_RSTART;
                            shadow_addr       <= burst_addr;
                            shadow_burst_len  <= burst_awlen;
                            shadow_burst_size <= burst_awsize;
                            shadow_burst_type <= burst_awburst;
                            req_toggle        <= ~req_toggle;
                            busy              <= 1'b1;
                        end
                    end

                    CMD_BURST_RDATA: begin
                        // FIFO pop is handled by fifo_rd_en (combinational)
                    end

                    CMD_CONFIG: begin
                        // Latch config value now (sr_addr is valid at update)
                        case (sr_addr[15:0])
                            CFG_BRIDGE_ID: config_rdata <= 32'h454A4158;
                            CFG_VERSION:   config_rdata <= {16'd0, 16'd1};
                            // FEATURES: [7:0]=ADDR_W, [15:8]=DATA_W,
                            // [23:16]=(FIFO_DEPTH-1)  (AXI4 awlen convention,
                            // so FIFO_DEPTH=256 fits as 0xFF; host adds 1)
                            CFG_FEATURES:  config_rdata <= {8'd0,
                                                            FIFO_DEPTH_ENC,
                                                            DATA_W[7:0],
                                                            ADDR_W[7:0]};
                            default:       config_rdata <= 32'h0;
                        endcase
                    end

                    CMD_RESET: begin
                        // Clear tck-domain state unconditionally.
                        error_sticky <= 1'b0;
                        prev_valid   <= 1'b0;
                        // Propagate reset to AXI domain via CDC handshake.
                        // The AXI FSM recognizes CMD_RESET and resets its
                        // state, FIFO write pointer, and pending transactions.
                        if (cdc_idle) begin
                            shadow_cmd <= CMD_RESET;
                            req_toggle <= ~req_toggle;
                            busy       <= 1'b1;
                        end
                        // If NOT idle: an AXI transaction is in flight.
                        // We do NOT clear busy — the in-flight op will
                        // complete and toggle ack, which clears busy on
                        // the next capture.  The host must poll (NOP) until
                        // busy=0 then re-issue RESET to propagate to AXI.
                        // This avoids reporting a clean state while stale
                        // AXI activity is still running.
                    end

                    default: begin
                        // Unknown command — treat as NOP
                    end
                endcase

                // Track last command for capture-time data source selection.
                // Only update for commands that actually executed — commands
                // dropped due to busy (cdc_idle=0) must NOT change last_cmd,
                // otherwise the capture-side mux selects the wrong data source
                // for a command that never launched.
                case (sr_cmd)
                    CMD_NOP, CMD_SET_ADDR, CMD_CONFIG, CMD_BURST_SETUP,
                    CMD_BURST_RDATA:
                        // These are always handled (no CDC needed), safe to update
                        last_cmd <= sr_cmd;
                    CMD_RESET:
                        // RESET updates last_cmd only if it launched (cdc_idle)
                        if (cdc_idle) last_cmd <= sr_cmd;
                    default:
                        // AXI commands (WRITE/READ/INC/BURST_WDATA/RSTART):
                        // Only update if the command was actually dispatched
                        if (cdc_idle) last_cmd <= sr_cmd;
                endcase
            end
        end
    end

    // ---- TCK initial values -------------------------------------------------
    initial begin
        sr                = {DR_W{1'b0}};
        auto_inc_addr     = {ADDR_W{1'b0}};
        burst_awlen       = 8'd0;
        burst_awsize      = 3'b010;
        burst_awburst     = 2'b01;
        burst_addr        = {ADDR_W{1'b0}};
        shadow_cmd        = 4'h0;
        shadow_addr       = {ADDR_W{1'b0}};
        shadow_wdata      = {DATA_W{1'b0}};
        shadow_wstrb      = {(DATA_W/8){1'b0}};
        shadow_burst_len  = 8'd0;
        shadow_burst_size = 3'b010;
        shadow_burst_type = 2'b01;
        req_toggle        = 1'b0;
        ack_toggle_sync1  = 1'b0;
        ack_toggle_sync2  = 1'b0;
        ack_toggle_prev   = 1'b0;
        resp_rdata_sync1  = {DATA_W{1'b0}};
        resp_rdata_sync2  = {DATA_W{1'b0}};
        resp_code_sync1   = 2'b00;
        resp_code_sync2   = 2'b00;
        prev_valid        = 1'b0;
        busy              = 1'b0;
        error_sticky      = 1'b0;
        config_rdata      = 32'h0;
        last_cmd          = 4'h0;
    end

    // ========================================================================
    //  AXI_CLK domain
    // ========================================================================

    // -- CDC: req_toggle sync (tck -> axi_clk) --------------------------------
    (* ASYNC_REG = "TRUE" *) reg req_toggle_sync1, req_toggle_sync2;
    reg req_toggle_prev_axi;
    wire req_edge = (req_toggle_sync2 != req_toggle_prev_axi);

    // req_toggle_prev_axi updates every cycle — req_edge is a single-cycle
    // pulse.  This is correct because ST_IDLE always consumes the edge
    // immediately, and ST_BURST_W only needs edges from subsequent beats
    // which arrive well after the previous edge has been consumed.
    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst) begin
            req_toggle_sync1    <= 1'b0;
            req_toggle_sync2    <= 1'b0;
            req_toggle_prev_axi <= 1'b0;
        end else begin
            req_toggle_sync1    <= req_toggle;
            req_toggle_sync2    <= req_toggle_sync1;
            req_toggle_prev_axi <= req_toggle_sync2;
        end
    end

    // -- Launch registers (axi_clk domain) ------------------------------------
    reg [3:0]           launch_cmd;
    reg [ADDR_W-1:0]    launch_addr;
    reg [DATA_W-1:0]    launch_wdata;
    reg [DATA_W/8-1:0]  launch_wstrb;
    reg [7:0]           launch_burst_len;
    reg [2:0]           launch_burst_size;
    reg [1:0]           launch_burst_type;

    // -- Response shadow (axi_clk domain, read by tck via 2-FF sync) ----------
    reg [DATA_W-1:0] resp_rdata;
    reg [1:0]        resp_code;

    // -- Ack toggle (axi_clk domain) ------------------------------------------
    reg ack_toggle;

    // -- AXI FSM state --------------------------------------------------------
    reg [3:0]  axi_state;
    reg [11:0] timeout_cnt;
    reg [7:0]  beat_count;

    // -- AXI_CLK initial values -----------------------------------------------
    initial begin
        req_toggle_sync1    = 1'b0;
        req_toggle_sync2    = 1'b0;
        req_toggle_prev_axi = 1'b0;
        launch_cmd          = 4'h0;
        launch_addr         = {ADDR_W{1'b0}};
        launch_wdata        = {DATA_W{1'b0}};
        launch_wstrb        = {(DATA_W/8){1'b0}};
        launch_burst_len    = 8'd0;
        launch_burst_size   = 3'b010;
        launch_burst_type   = 2'b01;
        resp_rdata          = {DATA_W{1'b0}};
        resp_code           = 2'b00;
        ack_toggle          = 1'b0;
        axi_state           = ST_IDLE;
        timeout_cnt         = 12'd0;
        beat_count          = 8'd0;
        m_axi_awaddr        = {ADDR_W{1'b0}};
        m_axi_awlen         = 8'd0;
        m_axi_awsize        = 3'b010;
        m_axi_awburst       = 2'b01;
        m_axi_awvalid       = 1'b0;
        m_axi_wdata         = {DATA_W{1'b0}};
        m_axi_wstrb         = {(DATA_W/8){1'b0}};
        m_axi_wvalid        = 1'b0;
        m_axi_wlast         = 1'b0;
        m_axi_bready        = 1'b0;
        m_axi_araddr        = {ADDR_W{1'b0}};
        m_axi_arlen         = 8'd0;
        m_axi_arsize        = 3'b010;
        m_axi_arburst       = 2'b01;
        m_axi_arvalid       = 1'b0;
        m_axi_rready        = 1'b0;
        fifo_rst_axi        = 1'b0;
    end

    // ---- AXI master FSM -----------------------------------------------------
    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst) begin
            axi_state         <= ST_IDLE;
            timeout_cnt       <= 12'd0;
            beat_count        <= 8'd0;
            ack_toggle        <= 1'b0;
            resp_rdata        <= {DATA_W{1'b0}};
            resp_code         <= 2'b00;
            launch_cmd        <= 4'h0;
            launch_addr       <= {ADDR_W{1'b0}};
            launch_wdata      <= {DATA_W{1'b0}};
            launch_wstrb      <= {(DATA_W/8){1'b0}};
            launch_burst_len  <= 8'd0;
            launch_burst_size <= 3'b010;
            launch_burst_type <= 2'b01;
            m_axi_awaddr      <= {ADDR_W{1'b0}};
            m_axi_awlen       <= 8'd0;
            m_axi_awsize      <= 3'b010;
            m_axi_awburst     <= 2'b01;
            m_axi_awvalid     <= 1'b0;
            m_axi_wdata       <= {DATA_W{1'b0}};
            m_axi_wstrb       <= {(DATA_W/8){1'b0}};
            m_axi_wvalid      <= 1'b0;
            m_axi_wlast       <= 1'b0;
            m_axi_bready      <= 1'b0;
            m_axi_araddr      <= {ADDR_W{1'b0}};
            m_axi_arlen       <= 8'd0;
            m_axi_arsize      <= 3'b010;
            m_axi_arburst     <= 2'b01;
            m_axi_arvalid     <= 1'b0;
            m_axi_rready      <= 1'b0;
            fifo_rst_axi      <= 1'b0;
        end else begin

            case (axi_state)

                // ---- Idle: wait for request toggle edge ----
                ST_IDLE: begin
                    m_axi_awvalid <= 1'b0;
                    m_axi_wvalid  <= 1'b0;
                    m_axi_wlast   <= 1'b0;
                    m_axi_bready  <= 1'b0;
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b0;
                    timeout_cnt   <= 12'd0;
                    beat_count    <= 8'd0;

                    if (req_edge) begin
                        // Latch shadow -> launch
                        launch_cmd        <= shadow_cmd;
                        launch_addr       <= shadow_addr;
                        launch_wdata      <= shadow_wdata;
                        launch_wstrb      <= shadow_wstrb;
                        launch_burst_len  <= shadow_burst_len;
                        launch_burst_size <= shadow_burst_size;
                        launch_burst_type <= shadow_burst_type;

                        case (shadow_cmd)
                            CMD_WRITE: begin
                                m_axi_awaddr  <= shadow_addr;
                                m_axi_awlen   <= 8'd0;
                                m_axi_awsize  <= 3'b010;
                                m_axi_awburst <= 2'b01;
                                m_axi_awvalid <= 1'b1;
                                m_axi_wdata   <= shadow_wdata;
                                m_axi_wstrb   <= shadow_wstrb;
                                m_axi_wvalid  <= 1'b1;
                                m_axi_wlast   <= 1'b1;
                                axi_state     <= ST_AW_W;
                            end

                            CMD_READ: begin
                                m_axi_araddr  <= shadow_addr;
                                m_axi_arlen   <= 8'd0;
                                m_axi_arsize  <= 3'b010;
                                m_axi_arburst <= 2'b01;
                                m_axi_arvalid <= 1'b1;
                                axi_state     <= ST_AR;
                            end

                            CMD_BURST_WDATA: begin
                                m_axi_awaddr  <= shadow_addr;
                                m_axi_awlen   <= shadow_burst_len;
                                m_axi_awsize  <= shadow_burst_size;
                                m_axi_awburst <= shadow_burst_type;
                                m_axi_awvalid <= 1'b1;
                                m_axi_wdata   <= shadow_wdata;
                                m_axi_wstrb   <= shadow_wstrb;
                                m_axi_wvalid  <= 1'b1;
                                m_axi_wlast   <= (shadow_burst_len == 8'd0);
                                beat_count    <= 8'd0;
                                axi_state     <= ST_BURST_AW_W;
                            end

                            CMD_BURST_RSTART: begin
                                m_axi_araddr  <= shadow_addr;
                                m_axi_arlen   <= shadow_burst_len;
                                m_axi_arsize  <= shadow_burst_size;
                                m_axi_arburst <= shadow_burst_type;
                                m_axi_arvalid <= 1'b1;
                                axi_state     <= ST_BURST_AR;
                            end

                            CMD_RESET: begin
                                // Reset AXI-domain state: pulse FIFO reset
                                // and go straight to DONE (toggles ack).
                                fifo_rst_axi   <= 1'b1;
                                resp_code      <= 2'b00;
                                resp_rdata     <= {DATA_W{1'b0}};
                                axi_state      <= ST_DONE;
                            end

                            default: begin
                                // Unknown AXI command — ack immediately
                                axi_state <= ST_DONE;
                            end
                        endcase
                    end
                end

                // ---- Single write: AW + W phase ----
                ST_AW_W: begin
                    if (m_axi_awready && m_axi_awvalid)
                        m_axi_awvalid <= 1'b0;
                    if (m_axi_wready && m_axi_wvalid) begin
                        m_axi_wvalid <= 1'b0;
                        m_axi_wlast  <= 1'b0;
                    end
                    // Both channels accepted -> wait for B
                    if ((!m_axi_awvalid || m_axi_awready) &&
                        (!m_axi_wvalid  || m_axi_wready)) begin
                        m_axi_awvalid <= 1'b0;
                        m_axi_wvalid  <= 1'b0;
                        m_axi_wlast   <= 1'b0;
                        m_axi_bready  <= 1'b1;
                        axi_state     <= ST_WAIT_B;
                        timeout_cnt   <= 12'd0;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Wait for write response ----
                ST_WAIT_B: begin
                    if (m_axi_bvalid) begin
                        resp_code    <= m_axi_bresp;
                        resp_rdata   <= {DATA_W{1'b0}};
                        m_axi_bready <= 1'b0;
                        axi_state    <= ST_DONE;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Single read: AR phase ----
                ST_AR: begin
                    if (m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        axi_state     <= ST_WAIT_R;
                        timeout_cnt   <= 12'd0;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Wait for read data ----
                ST_WAIT_R: begin
                    if (m_axi_rvalid) begin
                        resp_rdata   <= m_axi_rdata;
                        resp_code    <= m_axi_rresp;
                        m_axi_rready <= 1'b0;
                        axi_state    <= ST_DONE;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Burst write: AW + first W beat ----
                ST_BURST_AW_W: begin
                    if (m_axi_awready && m_axi_awvalid)
                        m_axi_awvalid <= 1'b0;
                    if (m_axi_wready && m_axi_wvalid) begin
                        m_axi_wvalid <= 1'b0;
                        if (m_axi_wlast)
                            m_axi_wlast <= 1'b0;
                    end
                    if ((!m_axi_awvalid || m_axi_awready) &&
                        (!m_axi_wvalid  || m_axi_wready)) begin
                        m_axi_awvalid <= 1'b0;
                        m_axi_wvalid  <= 1'b0;
                        if (launch_burst_len == 8'd0) begin
                            // Single-beat burst
                            m_axi_wlast  <= 1'b0;
                            m_axi_bready <= 1'b1;
                            axi_state    <= ST_WAIT_B;
                        end else begin
                            // Multi-beat burst: ack first beat so host can send next
                            ack_toggle <= ~ack_toggle;
                            beat_count <= 8'd1;
                            axi_state  <= ST_BURST_W;
                        end
                        timeout_cnt <= 12'd0;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Burst write: subsequent beats (fed by host) ----
                ST_BURST_W: begin
                    // Accept W-channel handshake
                    if (m_axi_wvalid && m_axi_wready) begin
                        m_axi_wvalid <= 1'b0;
                        if (m_axi_wlast) begin
                            m_axi_wlast  <= 1'b0;
                            m_axi_bready <= 1'b1;
                            axi_state    <= ST_WAIT_B;
                            timeout_cnt  <= 12'd0;
                        end
                    end
                    // New data from host via toggle edge
                    if (req_edge && !m_axi_wvalid) begin
                        if (shadow_cmd == CMD_BURST_WDATA) begin
                            // Normal: next burst beat
                            launch_wdata <= shadow_wdata;
                            launch_wstrb <= shadow_wstrb;
                            m_axi_wdata  <= shadow_wdata;
                            m_axi_wstrb  <= shadow_wstrb;
                            m_axi_wvalid <= 1'b1;
                            m_axi_wlast  <= (beat_count == launch_burst_len);
                            beat_count   <= beat_count + 1;
                            timeout_cnt  <= 12'd0;
                            // Ack non-last beats so host can queue next
                            if (beat_count != launch_burst_len)
                                ack_toggle <= ~ack_toggle;
                        end else begin
                            // Unexpected command while in burst — abort.
                            // Deassert all AXI signals and go to DONE.
                            // The slave may see an incomplete burst (no wlast)
                            // which violates AXI protocol, but this is a
                            // recovery path — the alternative is hanging.
                            m_axi_wvalid <= 1'b0;
                            m_axi_wlast  <= 1'b0;
                            resp_code    <= 2'b10;  // report SLVERR to host
                            axi_state    <= ST_DONE;
                        end
                    end
                    // No timeout in ST_BURST_W: inter-beat timing is
                    // controlled by the host via JTAG scans (~0.5 ms each),
                    // which is far longer than any AXI-side timeout.
                    // Timeout only applies to AXI handshake waits (wready,
                    // bvalid, arready, rvalid), not to host-paced data flow.
                end

                // ---- Burst read: AR phase ----
                ST_BURST_AR: begin
                    if (m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        axi_state     <= ST_BURST_R_FILL;
                        timeout_cnt   <= 12'd0;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Burst read: fill FIFO from R-channel ----
                ST_BURST_R_FILL: begin
                    // Flow control: deassert rready when FIFO is full
                    m_axi_rready <= !fifo_full;

                    if (m_axi_rvalid && !fifo_full) begin
                        // fifo_wr_en is combinational (assigned below)
                        timeout_cnt    <= 12'd0;
                        if (m_axi_rlast) begin
                            resp_code    <= m_axi_rresp;
                            resp_rdata   <= m_axi_rdata;
                            m_axi_rready <= 1'b0;
                            axi_state    <= ST_DONE;
                        end
                    end else if (!m_axi_rvalid) begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1)
                            axi_state <= ST_TIMEOUT_ERR;
                    end
                end

                // ---- Transaction complete: toggle ack ----
                ST_DONE: begin
                    m_axi_awvalid <= 1'b0;
                    m_axi_wvalid  <= 1'b0;
                    m_axi_wlast   <= 1'b0;
                    m_axi_bready  <= 1'b0;
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b0;
                    ack_toggle    <= ~ack_toggle;
                    axi_state     <= ST_IDLE;
                end

                // ---- Timeout error: signal error and ack ----
                ST_TIMEOUT_ERR: begin
                    m_axi_awvalid <= 1'b0;
                    m_axi_wvalid  <= 1'b0;
                    m_axi_wlast   <= 1'b0;
                    m_axi_bready  <= 1'b0;
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b0;
                    resp_code     <= 2'b10; // SLVERR
                    resp_rdata    <= {DATA_W{1'b0}};
                    ack_toggle    <= ~ack_toggle;
                    axi_state     <= ST_IDLE;
                end

                default: begin
                    axi_state <= ST_IDLE;
                end

            endcase

            // Clear FIFO reset pulse after one cycle
            if (fifo_rst_axi)
                fifo_rst_axi <= 1'b0;
        end
    end

    // FIFO write enable: burst read data from AXI R-channel
    assign fifo_wr_en = (axi_state == ST_BURST_R_FILL) &&
                        m_axi_rvalid && !fifo_full;

endmodule
