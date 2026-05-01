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
//   CMD_FIFO_DEPTH  - async command FIFO depth (default 2*FIFO_DEPTH)
//   RESP_FIFO_DEPTH - async response FIFO depth (default 2*FIFO_DEPTH)
//   TIMEOUT    - AXI ready timeout in axi_clk cycles   (default 4096)
//   *_FIFO_MEMORY_TYPE - XPM storage selectors ("auto", "block", "distributed")
//
// 72-bit DR format (LSB first):
//   Shift-in:  [31:0] addr, [63:32] payload, [67:64] wstrb, [71:68] cmd
//   Shift-out: [31:0] rdata, [63:32] info, [65:64] resp, [67:66] rsvd, [71:68] status

module fcapz_ejtagaxi #(
    parameter ADDR_W     = 32,
    parameter DATA_W     = 32,
    parameter FIFO_DEPTH = 16,
    parameter CMD_FIFO_DEPTH  = FIFO_DEPTH * 2,
    parameter RESP_FIFO_DEPTH = FIFO_DEPTH * 2,
    parameter TIMEOUT    = 4096,
    parameter DEBUG_EN   = 0,
    parameter USE_BEHAV_ASYNC_FIFO    = 1,
    parameter ASYNC_FIFO_IMPL = (USE_BEHAV_ASYNC_FIFO ? 0 : 1),
    parameter CMD_FIFO_MEMORY_TYPE   = "auto",
    parameter RESP_FIFO_MEMORY_TYPE  = "auto",
    parameter BURST_FIFO_MEMORY_TYPE = "auto"
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
    output reg                    m_axi_rready,

    // Optional debug buses for on-chip logic analysis
    output wire [255:0]          debug_tck,
    output wire [255:0]          debug_tck_edge,
    output wire [255:0]          debug_axi,
    output wire [255:0]          debug_axi_edge
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
                     ST_DONE         = 4'd9,
                     ST_TIMEOUT_ERR  = 4'd10,
                     ST_CMD_FETCH    = 4'd11,
                     ST_CMD_DISPATCH = 4'd12,
                     ST_BURST_W_FETCH= 4'd13,
                     ST_BURST_W_LOAD = 4'd14;

    // Config register addresses
    localparam CFG_BRIDGE_ID = 16'h0000;
    localparam CFG_VERSION   = 16'h0004;
    localparam CFG_FEATURES  = 16'h002C;
    localparam CFG_DBG_REC_COUNT      = 16'h0100;
    localparam CFG_DBG_REC0_SR_ADDR   = 16'h0120;
    localparam CFG_DBG_REC0_SR_PAYLOAD= 16'h0124;
    localparam CFG_DBG_REC0_SR_META   = 16'h0128;
    localparam CFG_DBG_REC0_AUTO_ADDR = 16'h012C;
    localparam CFG_DBG_REC0_CMD_ADDR  = 16'h0130;
    localparam CFG_DBG_REC0_CMD_WDATA = 16'h0134;
    localparam CFG_DBG_REC0_CMD_META  = 16'h0138;
    localparam CFG_DBG_REC1_SR_ADDR   = 16'h0140;
    localparam CFG_DBG_REC1_SR_PAYLOAD= 16'h0144;
    localparam CFG_DBG_REC1_SR_META   = 16'h0148;
    localparam CFG_DBG_REC1_AUTO_ADDR = 16'h014C;
    localparam CFG_DBG_REC1_CMD_ADDR  = 16'h0150;
    localparam CFG_DBG_REC1_CMD_WDATA = 16'h0154;
    localparam CFG_DBG_REC1_CMD_META  = 16'h0158;
    localparam CFG_DBG_REC2_SR_ADDR   = 16'h0160;
    localparam CFG_DBG_REC2_SR_PAYLOAD= 16'h0164;
    localparam CFG_DBG_REC2_SR_META   = 16'h0168;
    localparam CFG_DBG_REC2_AUTO_ADDR = 16'h016C;
    localparam CFG_DBG_REC2_CMD_ADDR  = 16'h0170;
    localparam CFG_DBG_REC2_CMD_WDATA = 16'h0174;
    localparam CFG_DBG_REC2_CMD_META  = 16'h0178;
    localparam CFG_DBG_REC3_SR_ADDR   = 16'h0180;
    localparam CFG_DBG_REC3_SR_PAYLOAD= 16'h0184;
    localparam CFG_DBG_REC3_SR_META   = 16'h0188;
    localparam CFG_DBG_REC3_AUTO_ADDR = 16'h018C;
    localparam CFG_DBG_REC3_CMD_ADDR  = 16'h0190;
    localparam CFG_DBG_REC3_CMD_WDATA = 16'h0194;
    localparam CFG_DBG_REC3_CMD_META  = 16'h0198;
    localparam CFG_RESP_WR_REC_COUNT  = 16'h01A0;
    localparam CFG_RESP_WR_REC0_DATA  = 16'h01A4;
    localparam CFG_RESP_WR_REC0_META  = 16'h01A8;
    localparam CFG_RESP_WR_REC1_DATA  = 16'h01AC;
    localparam CFG_RESP_WR_REC1_META  = 16'h01B0;
    localparam CFG_RESP_WR_REC2_DATA  = 16'h01B4;
    localparam CFG_RESP_WR_REC2_META  = 16'h01B8;
    localparam CFG_RESP_WR_REC3_DATA  = 16'h01BC;
    localparam CFG_RESP_WR_REC3_META  = 16'h01C0;
    localparam CFG_RESP_CAP_REC_COUNT = 16'h01C4;
    localparam CFG_RESP_CAP_REC0_DATA = 16'h01C8;
    localparam CFG_RESP_CAP_REC0_META = 16'h01CC;
    localparam CFG_RESP_CAP_REC1_DATA = 16'h01D0;
    localparam CFG_RESP_CAP_REC1_META = 16'h01D4;
    localparam CFG_RESP_CAP_REC2_DATA = 16'h01D8;
    localparam CFG_RESP_CAP_REC2_META = 16'h01DC;
    localparam CFG_RESP_CAP_REC3_DATA = 16'h01E0;
    localparam CFG_RESP_CAP_REC3_META = 16'h01E4;
    localparam CFG_AXI_DEQ_REC_COUNT  = 16'h01E8;
    localparam CFG_AXI_DEQ_REC0_ADDR  = 16'h01EC;
    localparam CFG_AXI_DEQ_REC0_META  = 16'h01F0;
    localparam CFG_AXI_DEQ_REC1_ADDR  = 16'h01F4;
    localparam CFG_AXI_DEQ_REC1_META  = 16'h01F8;
    localparam CFG_AXI_DEQ_REC2_ADDR  = 16'h01FC;
    localparam CFG_AXI_DEQ_REC2_META  = 16'h0200;
    localparam CFG_AXI_DEQ_REC3_ADDR  = 16'h0204;
    localparam CFG_AXI_DEQ_REC3_META  = 16'h0208;

    // Unprivileged, non-secure, data access
    assign m_axi_awprot = 3'b000;
    assign m_axi_arprot = 3'b000;

    // ---- Async FIFO pointer widths -------------------------------------------
    localparam FIFO_AW = $clog2(FIFO_DEPTH);
    localparam CMD_FIFO_AW = $clog2(CMD_FIFO_DEPTH);
    localparam RESP_FIFO_AW = $clog2(RESP_FIFO_DEPTH);
    // Encoded into FEATURES[23:16] as (FIFO_DEPTH-1) so 256 fits in 8 bits.
    localparam [7:0] FIFO_DEPTH_ENC = FIFO_DEPTH - 1;
    localparam CMDQ_W  = 4 + ADDR_W + DATA_W + (DATA_W/8) + 8 + 3 + 2;
    localparam RESPQ_W = DATA_W + 2;

    // ---- Parameter assertions ------------------------------------------------
    // FIFO_DEPTH bounds: must be >=1, <=256 (AXI4 burst max), and power of 2
    // (required by the async FIFO).  Synthesis-safe trap + sim $error.
    generate
        if (FIFO_DEPTH < 1 || FIFO_DEPTH > 256)
            FIFO_DEPTH_must_be_between_1_and_256 _fifo_depth_check_FAILED();
        if (FIFO_DEPTH & (FIFO_DEPTH - 1))
            FIFO_DEPTH_must_be_power_of_2 _fifo_depth_pow2_check_FAILED();
        if (CMD_FIFO_DEPTH < 2 || (CMD_FIFO_DEPTH & (CMD_FIFO_DEPTH - 1)))
            CMD_FIFO_DEPTH_must_be_power_of_2_and_at_least_2 _cmd_depth_check_FAILED();
        if (RESP_FIFO_DEPTH < 2 || (RESP_FIFO_DEPTH & (RESP_FIFO_DEPTH - 1)))
            RESP_FIFO_DEPTH_must_be_power_of_2_and_at_least_2 _resp_depth_check_FAILED();
    endgenerate
    initial begin
        if (FIFO_DEPTH < 1 || FIFO_DEPTH > 256)
            $error("fcapz_ejtagaxi: FIFO_DEPTH must be 1..256 (got %0d)", FIFO_DEPTH);
        if (FIFO_DEPTH & (FIFO_DEPTH - 1))
            $error("fcapz_ejtagaxi: FIFO_DEPTH must be a power of 2 (got %0d)", FIFO_DEPTH);
        if (CMD_FIFO_DEPTH < 2 || (CMD_FIFO_DEPTH & (CMD_FIFO_DEPTH - 1)))
            $error("fcapz_ejtagaxi: CMD_FIFO_DEPTH must be a power of 2 >= 2 (got %0d)", CMD_FIFO_DEPTH);
        if (RESP_FIFO_DEPTH < 2 || (RESP_FIFO_DEPTH & (RESP_FIFO_DEPTH - 1)))
            $error("fcapz_ejtagaxi: RESP_FIFO_DEPTH must be a power of 2 >= 2 (got %0d)", RESP_FIFO_DEPTH);
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
    reg              burst_cfg_valid;
    reg [8:0]        burst_w_beats_left;

    // Status bits
    reg prev_valid;
    reg error_sticky;
    reg [CMD_FIFO_AW:0] pending_count;

    // Last command tracker (for capture-time data source selection)
    reg [3:0] last_cmd;
    reg [2:0] dbg_rec_count;
    reg [31:0] dbg_rec_sr_addr [0:3];
    reg [31:0] dbg_rec_sr_payload [0:3];
    reg [31:0] dbg_rec_sr_meta [0:3];
    reg [31:0] dbg_rec_auto_addr [0:3];
    reg [31:0] dbg_rec_cmd_addr [0:3];
    reg [31:0] dbg_rec_cmd_wdata [0:3];
    reg [31:0] dbg_rec_cmd_meta [0:3];
    reg [2:0] dbg_resp_wr_rec_count;
    reg [31:0] dbg_resp_wr_rec_data [0:3];
    reg [31:0] dbg_resp_wr_rec_meta [0:3];
    reg [2:0] dbg_resp_cap_rec_count;
    reg [31:0] dbg_resp_cap_rec_data [0:3];
    reg [31:0] dbg_resp_cap_rec_meta [0:3];
    reg        resp_pop_pending;
    reg [2:0] dbg_axi_deq_rec_count;
    reg [31:0] dbg_axi_deq_rec_addr [0:3];
    reg [31:0] dbg_axi_deq_rec_meta [0:3];
    reg [DR_W-1:0] dbg_tck_update_sr;
    reg [CMDQ_W-1:0] dbg_tck_update_cmdq;
    reg [ADDR_W-1:0] dbg_tck_update_auto_inc;
    reg [3:0] dbg_tck_update_last_cmd;
    reg dbg_tck_update_fire;
    reg dbg_tck_update_full;
    reg [15:0] dbg_tck_update_count;
    reg [15:0] dbg_tck_enqueue_count;
    reg        reset_req_toggle;
    reg        reset_ack_sync1_tck;
    reg        reset_ack_sync2_tck;
    wire       reset_busy_tck = (reset_req_toggle != reset_ack_sync2_tck);

    // TCK -> AXI command FIFO.  This replaces the old req_toggle/shadow_*
    // mailbox so command payload bits cross domains atomically.
    wire                  cmdq_wr_en;
    wire [CMDQ_W-1:0]     cmdq_wr_data;
    wire                  cmdq_full;
    wire                  cmdq_wr_rst_busy;
    wire                  cmdq_rd_en;
    wire [CMDQ_W-1:0]     cmdq_rd_data;
    wire                  cmdq_empty;
    wire                  cmdq_rd_rst_busy;
    wire [CMD_FIFO_AW:0]  cmdq_rd_count;
    wire [CMD_FIFO_AW:0]  cmdq_wr_count;

    // AXI -> TCK response FIFO.  Completed AXI command responses cross back
    // as coherent words instead of independent synchronized data bits.
    wire                  respq_wr_en;
    wire [RESPQ_W-1:0]    respq_wr_data;
    wire                  respq_full;
    wire                  respq_wr_rst_busy;
    wire                  respq_rd_en;
    wire [RESPQ_W-1:0]    respq_rd_data;
    wire                  respq_empty;
    wire                  respq_rd_rst_busy;
    wire [RESP_FIFO_AW:0] respq_rd_count;
    wire [RESP_FIFO_AW:0] respq_wr_count;
    wire [DATA_W-1:0]     respq_rdata = respq_rd_data[DATA_W-1:0];
    wire [1:0]            respq_code  = respq_rd_data[DATA_W+1:DATA_W];
    integer dbg_i;
    reg                   respq_head_seen;
    reg                   cmdq_stage_valid;
    reg [CMDQ_W-1:0]      cmdq_stage_data;

    wire cmdq_wr_ready        = !cmdq_wr_rst_busy;
    wire cmdq_rd_ready        = !cmdq_rd_rst_busy;
    wire respq_wr_ready       = !respq_wr_rst_busy;
    wire respq_rd_ready       = !respq_rd_rst_busy;
    wire cmdq_stage_ready     = !cmdq_stage_valid;

    assign cmdq_wr_en   = cmdq_stage_valid && cmdq_wr_ready && !cmdq_full;
    assign cmdq_wr_data = cmdq_stage_data;

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
    reg fifo_rst_tck;
    reg cmdq_rst_axi;
    reg cmdq_rst_tck;
    reg respq_rst_axi;
    reg respq_rst_tck;

    fcapz_async_fifo #(
        .DATA_W  (CMDQ_W),
        .DEPTH   (CMD_FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO (USE_BEHAV_ASYNC_FIFO),
        .ASYNC_FIFO_IMPL      (ASYNC_FIFO_IMPL),
        .XPM_FIFO_MEMORY_TYPE (CMD_FIFO_MEMORY_TYPE)
    ) u_cmd_fifo (
        .wr_clk   (tck),
        .wr_rst   (axi_rst | cmdq_rst_tck),
        .wr_en    (cmdq_wr_en),
        .wr_data  (cmdq_wr_data),
        .wr_full  (cmdq_full),
        .wr_rst_busy (cmdq_wr_rst_busy),
        .rd_clk   (axi_clk),
        .rd_rst   (axi_rst | cmdq_rst_axi),
        .rd_en    (cmdq_rd_en),
        .rd_data  (cmdq_rd_data),
        .rd_empty (cmdq_empty),
        .rd_rst_busy (cmdq_rd_rst_busy),
        .rd_count (cmdq_rd_count),
        .wr_count (cmdq_wr_count)
    );

    fcapz_async_fifo #(
        .DATA_W  (RESPQ_W),
        .DEPTH   (RESP_FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO (USE_BEHAV_ASYNC_FIFO),
        .ASYNC_FIFO_IMPL      (ASYNC_FIFO_IMPL),
        .XPM_FIFO_MEMORY_TYPE (RESP_FIFO_MEMORY_TYPE)
    ) u_resp_fifo (
        .wr_clk   (axi_clk),
        .wr_rst   (axi_rst | respq_rst_axi),
        .wr_en    (respq_wr_en),
        .wr_data  (respq_wr_data),
        .wr_full  (respq_full),
        .wr_rst_busy (respq_wr_rst_busy),
        .rd_clk   (tck),
        .rd_rst   (axi_rst | respq_rst_tck),
        .rd_en    (respq_rd_en),
        .rd_data  (respq_rd_data),
        .rd_empty (respq_empty),
        .rd_rst_busy (respq_rd_rst_busy),
        .rd_count (respq_rd_count),
        .wr_count (respq_wr_count)
    );

    fcapz_async_fifo #(
        .DATA_W  (DATA_W),
        .DEPTH   (FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO (USE_BEHAV_ASYNC_FIFO),
        .ASYNC_FIFO_IMPL      (ASYNC_FIFO_IMPL),
        .XPM_FIFO_MEMORY_TYPE (BURST_FIFO_MEMORY_TYPE)
    ) u_burst_fifo (
        .wr_clk   (axi_clk),
        .wr_rst   (axi_rst | fifo_rst_axi),
        .wr_en    (fifo_wr_en),
        .wr_data  (m_axi_rdata),
        .wr_full  (fifo_full),
        .wr_rst_busy (),
        .rd_clk   (tck),
        .rd_rst   (axi_rst | fifo_rst_tck),
        .rd_en    (fifo_rd_en),
        .rd_data  (fifo_rdata),
        .rd_empty (fifo_empty),
        .rd_rst_busy (),
        .rd_count (fifo_rd_count),
        .wr_count ()
    );

    // FIFO read: pop on UPDATE when BURST_RDATA and previous scan also read
    assign fifo_rd_en = sel && update && (sr_cmd == CMD_BURST_RDATA) &&
                        fifo_notempty && (last_cmd == CMD_BURST_RDATA);

    // Config read value (latched at update time when cmd=CONFIG)
    reg [31:0] config_rdata;

    // Capture-time data source mux
    wire capture_burst_data = (last_cmd == CMD_BURST_RDATA) && fifo_notempty;
    wire capture_resp_data  = !capture_burst_data &&
                              respq_head_seen &&
                              respq_rd_ready &&
                              !respq_empty;

    wire [31:0] capture_rdata =
        (last_cmd == CMD_CONFIG)                       ? config_rdata      :
        capture_burst_data                             ? fifo_rdata        :
        capture_resp_data                              ? respq_rdata       :
                                                         {DATA_W{1'b0}};

    wire [1:0] capture_resp =
        capture_resp_data ? respq_code : 2'b00;

    wire capture_prev_valid =
        (last_cmd == CMD_CONFIG)                       ||
        capture_burst_data                             ||
        capture_resp_data;

    wire [31:0] info_field   = {8'd0, fifo_count, auto_inc_addr[15:0]};
    wire        busy_status  = reset_busy_tck ||
                               (pending_count != {(CMD_FIFO_AW+1){1'b0}}) ||
                               cmdq_full || !cmdq_wr_ready || !cmdq_rd_ready;
    wire [3:0]  status_bits  = {fifo_notempty, error_sticky, busy_status, prev_valid};

    assign debug_tck = DEBUG_EN ? {
        sr,
        cmdq_wr_data,
        auto_inc_addr,
        last_cmd,
        sr_cmd,
        cmdq_wr_en,
        cmdq_full,
        respq_rd_en,
        fifo_rd_en,
        capture_resp_data,
        capture_burst_data,
        capture_prev_valid,
        pending_count[4:0],
        cmdq_wr_count[4:0],
        respq_rd_count[4:0],
        cmdq_wr_ready,
        cmdq_wr_rst_busy,
        respq_rd_ready,
        respq_rd_rst_busy,
        status_bits,
        capture_resp,
        prev_valid,
        error_sticky,
        25'd0
    } : 256'd0;

    assign debug_tck_edge = DEBUG_EN ? {
        47'd0,
        dbg_tck_enqueue_count,
        dbg_tck_update_count,
        cmdq_wr_rst_busy,
        cmdq_wr_ready,
        cmdq_full,
        cmdq_wr_en,
        cmdq_wr_data,
        auto_inc_addr,
        sr_cmd,
        sr_wstrb,
        sr_payload,
        sr_addr
    } : 256'd0;

    assign respq_rd_en = sel && update && resp_pop_pending && respq_rd_ready;
    assign cmdq_rd_en = cmdq_rd_ready &&
                        !cmdq_empty &&
                        ((axi_state == ST_CMD_FETCH) ||
                         (axi_state == ST_BURST_W_FETCH));

    wire burst_first_ack_push =
        (axi_state == ST_BURST_AW_W) &&
        ((!m_axi_awvalid || m_axi_awready) && (!m_axi_wvalid || m_axi_wready)) &&
        (launch_burst_len != 8'd0) && respq_wr_ready && !respq_full;

    wire burst_mid_ack_push =
        (axi_state == ST_BURST_W_LOAD) &&
        (launch_cmd == CMD_BURST_WDATA) &&
        (beat_count != launch_burst_len) && respq_wr_ready && !respq_full;

    wire done_resp_push =
        (axi_state == ST_DONE) && respq_wr_ready && !respq_full;

    wire timeout_resp_push =
        (axi_state == ST_TIMEOUT_ERR) && respq_wr_ready && !respq_full;

    assign respq_wr_en = burst_first_ack_push || burst_mid_ack_push ||
                         done_resp_push || timeout_resp_push;

    assign respq_wr_data =
        (burst_first_ack_push || burst_mid_ack_push) ? {2'b00, {DATA_W{1'b0}}} :
        done_resp_push                               ? {resp_code, resp_rdata} :
        timeout_resp_push                            ? {2'b10, {DATA_W{1'b0}}} :
                                                       {RESPQ_W{1'b0}};

    // ---- TCK: main CAPTURE / SHIFT / UPDATE logic ---------------------------
    always @(posedge tck) begin
        reset_ack_sync1_tck <= dut_reset_ack_toggle_axi;
        reset_ack_sync2_tck <= reset_ack_sync1_tck;
        cmdq_rst_tck  <= 1'b0;
        respq_rst_tck <= 1'b0;
        fifo_rst_tck  <= 1'b0;
        if (DEBUG_EN && cmdq_wr_en) begin
            cmdq_stage_valid <= 1'b0;
            dbg_tck_enqueue_count <= dbg_tck_enqueue_count + 1'b1;
        end else if (cmdq_wr_en) begin
            cmdq_stage_valid <= 1'b0;
        end
        if (sel) begin
            respq_head_seen <= respq_rd_ready && !respq_empty;
            if (capture) begin
                resp_pop_pending <= capture_resp_data;
                // Assemble shift-out register from computed mux outputs
                if (capture_prev_valid) begin
                    prev_valid <= 1'b1;
                end
                // Set error_sticky on error response
                if (capture_resp_data && respq_code != 2'b00) begin
                    error_sticky <= 1'b1;
                end
                if (capture_resp_data &&
                    pending_count != {(CMD_FIFO_AW+1){1'b0}}) begin
                    pending_count <= pending_count - 1'b1;
                end
                if (DEBUG_EN && capture_resp_data && dbg_resp_cap_rec_count < 3'd4) begin
                    dbg_resp_cap_rec_data[dbg_resp_cap_rec_count] <= capture_rdata;
                    dbg_resp_cap_rec_meta[dbg_resp_cap_rec_count] <= {
                        9'd0,
                        respq_rd_count[4:0],
                        pending_count[4:0],
                        last_cmd,
                        capture_resp,
                        respq_head_seen,
                        respq_empty,
                        respq_rd_ready
                    };
                    dbg_resp_cap_rec_count <= dbg_resp_cap_rec_count + 1'b1;
                end

                // Build status with live values that reflect this capture's updates
                sr <= {{fifo_notempty,
                        error_sticky | (capture_resp_data & (respq_code != 2'b00)),
                        busy_status & ~capture_resp_data,
                        capture_prev_valid},
                       2'b00, capture_resp, info_field, capture_rdata};

            end else if (shift_en) begin
                sr <= {tdi, sr[DR_W-1:1]};

            end else if (update) begin
                prev_valid <= 1'b0;
                resp_pop_pending <= 1'b0;
                if (DEBUG_EN && dbg_rec_count < 3'd4) begin
                    dbg_rec_sr_addr[dbg_rec_count]    <= sr_addr;
                    dbg_rec_sr_payload[dbg_rec_count] <= sr_payload;
                    dbg_rec_sr_meta[dbg_rec_count]    <= {21'd0, cmdq_stage_valid, cmdq_wr_ready, cmdq_full, sr_cmd, sr_wstrb};
                    dbg_rec_auto_addr[dbg_rec_count]  <= auto_inc_addr;
                    dbg_rec_cmd_addr[dbg_rec_count]   <= {ADDR_W{1'b0}};
                    dbg_rec_cmd_wdata[dbg_rec_count]  <= {DATA_W{1'b0}};
                    dbg_rec_cmd_meta[dbg_rec_count]   <= 32'd0;
                    dbg_rec_count <= dbg_rec_count + 1'b1;
                end
                if (DEBUG_EN) begin
                    dbg_tck_update_sr       <= sr;
                    dbg_tck_update_cmdq     <= cmdq_stage_data;
                    dbg_tck_update_auto_inc <= auto_inc_addr;
                    dbg_tck_update_last_cmd <= last_cmd;
                    dbg_tck_update_fire     <= 1'b0;
                    dbg_tck_update_full     <= cmdq_full;
                    dbg_tck_update_count    <= dbg_tck_update_count + 1'b1;
                end

                case (sr_cmd)
                    CMD_NOP: begin
                        // No operation
                    end

                    CMD_SET_ADDR: begin
                        auto_inc_addr <= sr_addr;
                    end

                    CMD_WRITE: begin
                        if (sr_wstrb == {(DATA_W/8){1'b0}}) begin
                            // Ignore malformed zero-strobe writes so a
                            // garbled poll scan cannot mutate memory.
                        end else if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_WRITE, sr_addr[ADDR_W-1:0],
                                                 sr_payload[DATA_W-1:0],
                                                 sr_wstrb[DATA_W/8-1:0],
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= sr_addr[ADDR_W-1:0];
                                dbg_rec_cmd_wdata[dbg_rec_count] <= sr_payload[DATA_W-1:0];
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_WRITE,
                                    sr_wstrb[DATA_W/8-1:0],
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_WRITE, sr_addr[ADDR_W-1:0],
                                                        sr_payload[DATA_W-1:0],
                                                        sr_wstrb[DATA_W/8-1:0],
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_READ: begin
                        if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_READ, sr_addr[ADDR_W-1:0],
                                                 {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= sr_addr[ADDR_W-1:0];
                                dbg_rec_cmd_wdata[dbg_rec_count] <= {DATA_W{1'b0}};
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_READ,
                                    {(DATA_W/8){1'b0}},
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_READ, sr_addr[ADDR_W-1:0],
                                                        {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_WRITE_INC: begin
                        if (sr_wstrb == {(DATA_W/8){1'b0}}) begin
                            // Ignore malformed zero-strobe writes so a
                            // garbled poll scan cannot mutate memory.
                        end else if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_WRITE, auto_inc_addr,
                                                 sr_payload[DATA_W-1:0],
                                                 sr_wstrb[DATA_W/8-1:0],
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= auto_inc_addr;
                                dbg_rec_cmd_wdata[dbg_rec_count] <= sr_payload[DATA_W-1:0];
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_WRITE,
                                    sr_wstrb[DATA_W/8-1:0],
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_WRITE, auto_inc_addr,
                                                        sr_payload[DATA_W-1:0],
                                                        sr_wstrb[DATA_W/8-1:0],
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                            auto_inc_addr <= auto_inc_addr + 4;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_READ_INC: begin
                        if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_READ, auto_inc_addr,
                                                 {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= auto_inc_addr;
                                dbg_rec_cmd_wdata[dbg_rec_count] <= {DATA_W{1'b0}};
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_READ,
                                    {(DATA_W/8){1'b0}},
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_READ, auto_inc_addr,
                                                        {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                            auto_inc_addr <= auto_inc_addr + 4;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_BURST_SETUP: begin
                        burst_addr    <= sr_addr;
                        burst_awlen   <= sr_payload[7:0];
                        burst_awsize  <= sr_payload[10:8];
                        burst_awburst <= sr_payload[13:12];
                        burst_cfg_valid <= 1'b1;
                        burst_w_beats_left <= {1'b0, sr_payload[7:0]} + 9'd1;
                    end

                    CMD_BURST_WDATA: begin
                        if (!burst_cfg_valid || burst_w_beats_left == 9'd0) begin
                            // Ignore stray burst-data commands unless a
                            // BURST_SETUP armed a real burst transfer.
                        end else if (sr_wstrb == {(DATA_W/8){1'b0}}) begin
                            // Ignore malformed zero-strobe burst writes.
                        end else if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_BURST_WDATA, burst_addr,
                                                 sr_payload[DATA_W-1:0],
                                                 sr_wstrb[DATA_W/8-1:0],
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= burst_addr;
                                dbg_rec_cmd_wdata[dbg_rec_count] <= sr_payload[DATA_W-1:0];
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_BURST_WDATA,
                                    sr_wstrb[DATA_W/8-1:0],
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_BURST_WDATA, burst_addr,
                                                        sr_payload[DATA_W-1:0],
                                                        sr_wstrb[DATA_W/8-1:0],
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                            if (burst_w_beats_left == 9'd1) begin
                                burst_cfg_valid <= 1'b0;
                                burst_w_beats_left <= 9'd0;
                            end else begin
                                burst_w_beats_left <= burst_w_beats_left - 9'd1;
                            end
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_BURST_RSTART: begin
                        if (!burst_cfg_valid) begin
                            // Ignore stray burst-start commands unless a
                            // BURST_SETUP armed a real burst transfer.
                        end else if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_BURST_RSTART, burst_addr,
                                                 {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                            if (DEBUG_EN) begin
                                dbg_rec_cmd_addr[dbg_rec_count]  <= burst_addr;
                                dbg_rec_cmd_wdata[dbg_rec_count] <= {DATA_W{1'b0}};
                                dbg_rec_cmd_meta[dbg_rec_count]  <= {
                                    10'd0,
                                    CMD_BURST_RSTART,
                                    {(DATA_W/8){1'b0}},
                                    burst_awlen,
                                    burst_awsize,
                                    burst_awburst
                                };
                                dbg_tck_update_cmdq <= {CMD_BURST_RSTART, burst_addr,
                                                        {DATA_W{1'b0}}, {(DATA_W/8){1'b0}},
                                                        burst_awlen, burst_awsize, burst_awburst};
                                dbg_tck_update_fire <= 1'b1;
                            end
                        end else begin
                            error_sticky <= 1'b1;
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
                            CFG_DBG_REC_COUNT: config_rdata <= DEBUG_EN ? {29'd0, dbg_rec_count} : 32'd0;
                            CFG_DBG_REC0_SR_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_sr_addr[0] : 32'd0;
                            CFG_DBG_REC0_SR_PAYLOAD: config_rdata <= DEBUG_EN ? dbg_rec_sr_payload[0] : 32'd0;
                            CFG_DBG_REC0_SR_META: config_rdata <= DEBUG_EN ? dbg_rec_sr_meta[0] : 32'd0;
                            CFG_DBG_REC0_AUTO_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_auto_addr[0] : 32'd0;
                            CFG_DBG_REC0_CMD_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_cmd_addr[0] : 32'd0;
                            CFG_DBG_REC0_CMD_WDATA: config_rdata <= DEBUG_EN ? dbg_rec_cmd_wdata[0] : 32'd0;
                            CFG_DBG_REC0_CMD_META: config_rdata <= DEBUG_EN ? dbg_rec_cmd_meta[0] : 32'd0;
                            CFG_DBG_REC1_SR_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_sr_addr[1] : 32'd0;
                            CFG_DBG_REC1_SR_PAYLOAD: config_rdata <= DEBUG_EN ? dbg_rec_sr_payload[1] : 32'd0;
                            CFG_DBG_REC1_SR_META: config_rdata <= DEBUG_EN ? dbg_rec_sr_meta[1] : 32'd0;
                            CFG_DBG_REC1_AUTO_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_auto_addr[1] : 32'd0;
                            CFG_DBG_REC1_CMD_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_cmd_addr[1] : 32'd0;
                            CFG_DBG_REC1_CMD_WDATA: config_rdata <= DEBUG_EN ? dbg_rec_cmd_wdata[1] : 32'd0;
                            CFG_DBG_REC1_CMD_META: config_rdata <= DEBUG_EN ? dbg_rec_cmd_meta[1] : 32'd0;
                            CFG_DBG_REC2_SR_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_sr_addr[2] : 32'd0;
                            CFG_DBG_REC2_SR_PAYLOAD: config_rdata <= DEBUG_EN ? dbg_rec_sr_payload[2] : 32'd0;
                            CFG_DBG_REC2_SR_META: config_rdata <= DEBUG_EN ? dbg_rec_sr_meta[2] : 32'd0;
                            CFG_DBG_REC2_AUTO_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_auto_addr[2] : 32'd0;
                            CFG_DBG_REC2_CMD_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_cmd_addr[2] : 32'd0;
                            CFG_DBG_REC2_CMD_WDATA: config_rdata <= DEBUG_EN ? dbg_rec_cmd_wdata[2] : 32'd0;
                            CFG_DBG_REC2_CMD_META: config_rdata <= DEBUG_EN ? dbg_rec_cmd_meta[2] : 32'd0;
                            CFG_DBG_REC3_SR_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_sr_addr[3] : 32'd0;
                            CFG_DBG_REC3_SR_PAYLOAD: config_rdata <= DEBUG_EN ? dbg_rec_sr_payload[3] : 32'd0;
                            CFG_DBG_REC3_SR_META: config_rdata <= DEBUG_EN ? dbg_rec_sr_meta[3] : 32'd0;
                            CFG_DBG_REC3_AUTO_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_auto_addr[3] : 32'd0;
                            CFG_DBG_REC3_CMD_ADDR: config_rdata <= DEBUG_EN ? dbg_rec_cmd_addr[3] : 32'd0;
                            CFG_DBG_REC3_CMD_WDATA: config_rdata <= DEBUG_EN ? dbg_rec_cmd_wdata[3] : 32'd0;
                            CFG_DBG_REC3_CMD_META: config_rdata <= DEBUG_EN ? dbg_rec_cmd_meta[3] : 32'd0;
                            CFG_RESP_WR_REC_COUNT: config_rdata <= DEBUG_EN ? {29'd0, dbg_resp_wr_rec_count} : 32'd0;
                            CFG_RESP_WR_REC0_DATA: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_data[0] : 32'd0;
                            CFG_RESP_WR_REC0_META: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_meta[0] : 32'd0;
                            CFG_RESP_WR_REC1_DATA: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_data[1] : 32'd0;
                            CFG_RESP_WR_REC1_META: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_meta[1] : 32'd0;
                            CFG_RESP_WR_REC2_DATA: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_data[2] : 32'd0;
                            CFG_RESP_WR_REC2_META: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_meta[2] : 32'd0;
                            CFG_RESP_WR_REC3_DATA: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_data[3] : 32'd0;
                            CFG_RESP_WR_REC3_META: config_rdata <= DEBUG_EN ? dbg_resp_wr_rec_meta[3] : 32'd0;
                            CFG_RESP_CAP_REC_COUNT: config_rdata <= DEBUG_EN ? {29'd0, dbg_resp_cap_rec_count} : 32'd0;
                            CFG_RESP_CAP_REC0_DATA: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_data[0] : 32'd0;
                            CFG_RESP_CAP_REC0_META: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_meta[0] : 32'd0;
                            CFG_RESP_CAP_REC1_DATA: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_data[1] : 32'd0;
                            CFG_RESP_CAP_REC1_META: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_meta[1] : 32'd0;
                            CFG_RESP_CAP_REC2_DATA: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_data[2] : 32'd0;
                            CFG_RESP_CAP_REC2_META: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_meta[2] : 32'd0;
                            CFG_RESP_CAP_REC3_DATA: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_data[3] : 32'd0;
                            CFG_RESP_CAP_REC3_META: config_rdata <= DEBUG_EN ? dbg_resp_cap_rec_meta[3] : 32'd0;
                            CFG_AXI_DEQ_REC_COUNT: config_rdata <= DEBUG_EN ? {29'd0, dbg_axi_deq_rec_count} : 32'd0;
                            CFG_AXI_DEQ_REC0_ADDR: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_addr[0] : 32'd0;
                            CFG_AXI_DEQ_REC0_META: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_meta[0] : 32'd0;
                            CFG_AXI_DEQ_REC1_ADDR: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_addr[1] : 32'd0;
                            CFG_AXI_DEQ_REC1_META: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_meta[1] : 32'd0;
                            CFG_AXI_DEQ_REC2_ADDR: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_addr[2] : 32'd0;
                            CFG_AXI_DEQ_REC2_META: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_meta[2] : 32'd0;
                            CFG_AXI_DEQ_REC3_ADDR: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_addr[3] : 32'd0;
                            CFG_AXI_DEQ_REC3_META: config_rdata <= DEBUG_EN ? dbg_axi_deq_rec_meta[3] : 32'd0;
                            default:       config_rdata <= 32'h0;
                        endcase
                    end

                    CMD_RESET: begin
                        // Clear tck-domain state unconditionally.
                        error_sticky <= 1'b0;
                        prev_valid   <= 1'b0;
                        respq_head_seen <= 1'b0;
                        resp_pop_pending <= 1'b0;
                        pending_count <= {(CMD_FIFO_AW+1){1'b0}};
                        cmdq_rst_tck  <= 1'b1;
                        respq_rst_tck <= 1'b1;
                        fifo_rst_tck  <= 1'b1;
                        cmdq_stage_valid <= 1'b0;
                        cmdq_stage_data <= {CMDQ_W{1'b0}};
                        auto_inc_addr <= {ADDR_W{1'b0}};
                        burst_awlen   <= 8'd0;
                        burst_awsize  <= 3'b010;
                        burst_awburst <= 2'b01;
                        burst_addr    <= {ADDR_W{1'b0}};
                        burst_cfg_valid <= 1'b0;
                        burst_w_beats_left <= 9'd0;
                        config_rdata  <= 32'h0;
                        last_cmd      <= CMD_NOP;
                        dbg_rec_count <= 3'd0;
                        dbg_resp_cap_rec_count <= 3'd0;
                        reset_req_toggle <= ~reset_req_toggle;
                    end

                    default: begin
                        // Unknown command — treat as NOP
                    end
                endcase

                // Track last command for capture-time data source selection.
                // AXI commands update only when successfully enqueued.
                case (sr_cmd)
                    CMD_NOP, CMD_SET_ADDR, CMD_CONFIG, CMD_BURST_SETUP,
                    CMD_BURST_RDATA:
                        // These are always handled (no CDC needed), safe to update
                        last_cmd <= sr_cmd;
                    CMD_RESET:
                        // RESET clears the capture pipeline rather than
                        // becoming the new "last command".
                        last_cmd <= CMD_NOP;
                    default:
                        // AXI commands update only if queued.
                        if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            case (sr_cmd)
                                CMD_WRITE, CMD_WRITE_INC:
                                    if (sr_wstrb != {(DATA_W/8){1'b0}})
                                        last_cmd <= sr_cmd;
                                CMD_BURST_WDATA:
                                    if (burst_cfg_valid &&
                                        burst_w_beats_left != 9'd0 &&
                                        sr_wstrb != {(DATA_W/8){1'b0}})
                                        last_cmd <= sr_cmd;
                                CMD_BURST_RSTART:
                                    if (burst_cfg_valid)
                                        last_cmd <= sr_cmd;
                                default:
                                    last_cmd <= sr_cmd;
                            endcase
                        end
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
        burst_cfg_valid   = 1'b0;
        burst_w_beats_left = 9'd0;
        prev_valid        = 1'b0;
        error_sticky      = 1'b0;
        pending_count     = {(CMD_FIFO_AW+1){1'b0}};
        reset_req_toggle  = 1'b0;
        reset_ack_sync1_tck = 1'b0;
        reset_ack_sync2_tck = 1'b0;
        respq_head_seen   = 1'b0;
        resp_pop_pending  = 1'b0;
        cmdq_stage_valid  = 1'b0;
        cmdq_stage_data   = {CMDQ_W{1'b0}};
        cmdq_rst_tck      = 1'b0;
        respq_rst_tck     = 1'b0;
        fifo_rst_tck      = 1'b0;
        config_rdata      = 32'h0;
        last_cmd          = 4'h0;
        dbg_rec_count     = 3'd0;
        dbg_resp_wr_rec_count = 3'd0;
        dbg_resp_cap_rec_count = 3'd0;
        dbg_axi_deq_rec_count = 3'd0;
        for (dbg_i = 0; dbg_i < 4; dbg_i = dbg_i + 1) begin
            dbg_rec_sr_addr[dbg_i] = 32'd0;
            dbg_rec_sr_payload[dbg_i] = 32'd0;
            dbg_rec_sr_meta[dbg_i] = 32'd0;
            dbg_rec_auto_addr[dbg_i] = 32'd0;
            dbg_rec_cmd_addr[dbg_i] = 32'd0;
            dbg_rec_cmd_wdata[dbg_i] = 32'd0;
            dbg_rec_cmd_meta[dbg_i] = 32'd0;
            dbg_resp_wr_rec_data[dbg_i] = 32'd0;
            dbg_resp_wr_rec_meta[dbg_i] = 32'd0;
            dbg_resp_cap_rec_data[dbg_i] = 32'd0;
            dbg_resp_cap_rec_meta[dbg_i] = 32'd0;
            dbg_axi_deq_rec_addr[dbg_i] = 32'd0;
            dbg_axi_deq_rec_meta[dbg_i] = 32'd0;
        end
        dbg_tck_update_sr = {DR_W{1'b0}};
        dbg_tck_update_cmdq = {CMDQ_W{1'b0}};
        dbg_tck_update_auto_inc = {ADDR_W{1'b0}};
        dbg_tck_update_last_cmd = 4'h0;
        dbg_tck_update_fire = 1'b0;
        dbg_tck_update_full = 1'b0;
        dbg_tck_update_count = 16'd0;
        dbg_tck_enqueue_count = 16'd0;
    end

    // ========================================================================
    //  AXI_CLK domain
    // ========================================================================

    // -- Command FIFO unpack (axi_clk domain) ---------------------------------
    wire [1:0]          cmdq_burst_type = cmdq_rd_data[1:0];
    wire [2:0]          cmdq_burst_size = cmdq_rd_data[4:2];
    wire [7:0]          cmdq_burst_len  = cmdq_rd_data[12:5];
    wire [DATA_W/8-1:0] cmdq_wstrb      = cmdq_rd_data[12 + DATA_W/8:13];
    wire [DATA_W-1:0]   cmdq_wdata      = cmdq_rd_data[12 + DATA_W/8 + DATA_W:
                                                        13 + DATA_W/8];
    wire [ADDR_W-1:0]   cmdq_addr       = cmdq_rd_data[12 + DATA_W/8 + DATA_W + ADDR_W:
                                                        13 + DATA_W/8 + DATA_W];
    wire [3:0]          cmdq_cmd        = cmdq_rd_data[CMDQ_W-1:CMDQ_W-4];

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

    // -- AXI FSM state --------------------------------------------------------
    reg [3:0]  axi_state;
    reg [11:0] timeout_cnt;
    reg [7:0]  beat_count;
    reg        reset_req_sync1_axi;
    reg        reset_req_sync2_axi;
    reg        reset_req_seen_axi;
    reg        dut_reset_ack_toggle_axi;
    reg [CMDQ_W-1:0]    dbg_axi_deq_cmdq;
    reg [3:0]           dbg_axi_deq_cmd;
    reg [ADDR_W-1:0]    dbg_axi_deq_addr;
    reg [DATA_W-1:0]    dbg_axi_deq_wdata;
    reg [DATA_W/8-1:0]  dbg_axi_deq_wstrb;
    reg [3:0]           dbg_axi_deq_state;
    reg                 dbg_axi_deq_fire;
    reg [15:0]          dbg_axi_cycle_count;
    reg [15:0]          dbg_axi_deq_count;

    // -- AXI_CLK initial values -----------------------------------------------
    initial begin
        launch_cmd          = 4'h0;
        launch_addr         = {ADDR_W{1'b0}};
        launch_wdata        = {DATA_W{1'b0}};
        launch_wstrb        = {(DATA_W/8){1'b0}};
        launch_burst_len    = 8'd0;
        launch_burst_size   = 3'b010;
        launch_burst_type   = 2'b01;
        resp_rdata          = {DATA_W{1'b0}};
        resp_code           = 2'b00;
        axi_state           = ST_IDLE;
        timeout_cnt         = 12'd0;
        beat_count          = 8'd0;
        reset_req_sync1_axi = 1'b0;
        reset_req_sync2_axi = 1'b0;
        reset_req_seen_axi  = 1'b0;
        dut_reset_ack_toggle_axi = 1'b0;
        dbg_axi_deq_cmdq    = {CMDQ_W{1'b0}};
        dbg_axi_deq_cmd     = 4'h0;
        dbg_axi_deq_addr    = {ADDR_W{1'b0}};
        dbg_axi_deq_wdata   = {DATA_W{1'b0}};
        dbg_axi_deq_wstrb   = {(DATA_W/8){1'b0}};
        dbg_axi_deq_state   = ST_IDLE;
        dbg_axi_deq_fire    = 1'b0;
        dbg_axi_cycle_count = 16'd0;
        dbg_axi_deq_count   = 16'd0;
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
        cmdq_rst_axi        = 1'b0;
        fifo_rst_axi        = 1'b0;
        respq_rst_axi       = 1'b0;
    end

    // ---- AXI master FSM -----------------------------------------------------
    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst) begin
            axi_state         <= ST_IDLE;
            timeout_cnt       <= 12'd0;
            beat_count        <= 8'd0;
            reset_req_sync1_axi <= 1'b0;
            reset_req_sync2_axi <= 1'b0;
            reset_req_seen_axi  <= 1'b0;
            dut_reset_ack_toggle_axi <= 1'b0;
            dbg_axi_deq_cmdq  <= {CMDQ_W{1'b0}};
            dbg_axi_deq_cmd   <= 4'h0;
            dbg_axi_deq_addr  <= {ADDR_W{1'b0}};
            dbg_axi_deq_wdata <= {DATA_W{1'b0}};
            dbg_axi_deq_wstrb <= {(DATA_W/8){1'b0}};
            dbg_axi_deq_state <= ST_IDLE;
            dbg_axi_deq_fire  <= 1'b0;
            dbg_axi_cycle_count <= 16'd0;
            dbg_axi_deq_count   <= 16'd0;
            dbg_resp_wr_rec_count <= 3'd0;
            dbg_axi_deq_rec_count <= 3'd0;
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
            cmdq_rst_axi      <= 1'b0;
            fifo_rst_axi      <= 1'b0;
            respq_rst_axi     <= 1'b0;
        end else begin
            reset_req_sync1_axi <= reset_req_toggle;
            reset_req_sync2_axi <= reset_req_sync1_axi;
            if (DEBUG_EN) begin
                dbg_axi_deq_fire <= 1'b0;
                dbg_axi_cycle_count <= dbg_axi_cycle_count + 1'b1;
            end
            cmdq_rst_axi <= 1'b0;
            respq_rst_axi <= 1'b0;
            fifo_rst_axi  <= 1'b0;
            if (DEBUG_EN && respq_wr_en && dbg_resp_wr_rec_count < 3'd4) begin
                dbg_resp_wr_rec_data[dbg_resp_wr_rec_count] <= respq_wr_data[DATA_W-1:0];
                dbg_resp_wr_rec_meta[dbg_resp_wr_rec_count] <= {
                    11'd0,
                    respq_wr_count[4:0],
                    launch_cmd,
                    respq_wr_data[DATA_W+1:DATA_W],
                    respq_full,
                    respq_wr_ready,
                    axi_state
                };
                dbg_resp_wr_rec_count <= dbg_resp_wr_rec_count + 1'b1;
            end
            if (DEBUG_EN && cmdq_rd_en) begin
                dbg_axi_deq_cmdq  <= cmdq_rd_data;
                dbg_axi_deq_cmd   <= cmdq_cmd;
                dbg_axi_deq_addr  <= cmdq_addr;
                dbg_axi_deq_wdata <= cmdq_wdata;
                dbg_axi_deq_wstrb <= cmdq_wstrb;
                dbg_axi_deq_state <= axi_state;
                dbg_axi_deq_fire  <= 1'b1;
                dbg_axi_deq_count <= dbg_axi_deq_count + 1'b1;
                if (dbg_axi_deq_rec_count < 3'd4) begin
                    dbg_axi_deq_rec_addr[dbg_axi_deq_rec_count] <= cmdq_addr;
                    dbg_axi_deq_rec_meta[dbg_axi_deq_rec_count] <= {
                        16'd0,
                        cmdq_burst_len,
                        cmdq_cmd,
                        axi_state
                    };
                    dbg_axi_deq_rec_count <= dbg_axi_deq_rec_count + 1'b1;
                end
            end
            if (reset_req_sync2_axi != reset_req_seen_axi) begin
                reset_req_seen_axi     <= reset_req_sync2_axi;
                dut_reset_ack_toggle_axi <= reset_req_sync2_axi;
                axi_state              <= ST_IDLE;
                timeout_cnt            <= 12'd0;
                beat_count             <= 8'd0;
                launch_cmd             <= 4'h0;
                launch_addr            <= {ADDR_W{1'b0}};
                launch_wdata           <= {DATA_W{1'b0}};
                launch_wstrb           <= {(DATA_W/8){1'b0}};
                launch_burst_len       <= 8'd0;
                launch_burst_size      <= 3'b010;
                launch_burst_type      <= 2'b01;
                resp_rdata             <= {DATA_W{1'b0}};
                resp_code              <= 2'b00;
                m_axi_awvalid          <= 1'b0;
                m_axi_wvalid           <= 1'b0;
                m_axi_wlast            <= 1'b0;
                m_axi_bready           <= 1'b0;
                m_axi_arvalid          <= 1'b0;
                m_axi_rready           <= 1'b0;
                cmdq_rst_axi           <= 1'b1;
                respq_rst_axi          <= 1'b1;
                fifo_rst_axi           <= 1'b1;
                if (DEBUG_EN) begin
                    dbg_resp_wr_rec_count  <= 3'd0;
                    dbg_axi_deq_rec_count  <= 3'd0;
                end
            end else case (axi_state)

                // ---- Idle: consume next queued command ----
                ST_IDLE: begin
                    m_axi_awvalid <= 1'b0;
                    m_axi_wvalid  <= 1'b0;
                    m_axi_wlast   <= 1'b0;
                    m_axi_bready  <= 1'b0;
                    m_axi_arvalid <= 1'b0;
                    m_axi_rready  <= 1'b0;
                    timeout_cnt   <= 12'd0;
                    beat_count    <= 8'd0;

                    if (!cmdq_empty) begin
                        // Give FWFT async FIFO one full rd_clk cycle with
                        // empty=0 before sampling/popping the head word.
                        axi_state <= ST_CMD_FETCH;
                    end
                end

                ST_CMD_FETCH: begin
                    launch_cmd        <= cmdq_cmd;
                    launch_addr       <= cmdq_addr;
                    launch_wdata      <= cmdq_wdata;
                    launch_wstrb      <= cmdq_wstrb;
                    launch_burst_len  <= cmdq_burst_len;
                    launch_burst_size <= cmdq_burst_size;
                    launch_burst_type <= cmdq_burst_type;
                    axi_state         <= ST_CMD_DISPATCH;
                end

                ST_CMD_DISPATCH: begin
                    case (launch_cmd)
                        CMD_WRITE: begin
                            m_axi_awaddr  <= launch_addr;
                            m_axi_awlen   <= 8'd0;
                            m_axi_awsize  <= 3'b010;
                            m_axi_awburst <= 2'b01;
                            m_axi_awvalid <= 1'b1;
                            m_axi_wdata   <= launch_wdata;
                            m_axi_wstrb   <= launch_wstrb;
                            m_axi_wvalid  <= 1'b1;
                            m_axi_wlast   <= 1'b1;
                            axi_state     <= ST_AW_W;
                        end

                        CMD_READ: begin
                            m_axi_araddr  <= launch_addr;
                            m_axi_arlen   <= 8'd0;
                            m_axi_arsize  <= 3'b010;
                            m_axi_arburst <= 2'b01;
                            m_axi_arvalid <= 1'b1;
                            axi_state     <= ST_AR;
                        end

                        CMD_BURST_WDATA: begin
                            m_axi_awaddr  <= launch_addr;
                            m_axi_awlen   <= launch_burst_len;
                            m_axi_awsize  <= launch_burst_size;
                            m_axi_awburst <= launch_burst_type;
                            m_axi_awvalid <= 1'b1;
                            m_axi_wdata   <= launch_wdata;
                            m_axi_wstrb   <= launch_wstrb;
                            m_axi_wvalid  <= 1'b1;
                            m_axi_wlast   <= (launch_burst_len == 8'd0);
                            beat_count    <= 8'd0;
                            axi_state     <= ST_BURST_AW_W;
                        end

                        CMD_BURST_RSTART: begin
                            m_axi_araddr  <= launch_addr;
                            m_axi_arlen   <= launch_burst_len;
                            m_axi_arsize  <= launch_burst_size;
                            m_axi_arburst <= launch_burst_type;
                            m_axi_arvalid <= 1'b1;
                            axi_state     <= ST_BURST_AR;
                        end

                        default: begin
                            resp_code  <= 2'b00;
                            resp_rdata <= {DATA_W{1'b0}};
                            axi_state  <= ST_DONE;
                        end
                    endcase
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
                            if (respq_wr_ready && !respq_full) begin
                                beat_count <= 8'd1;
                                axi_state  <= ST_BURST_W;
                            end
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
                    // New data from host via command FIFO
                    if (cmdq_rd_ready && !cmdq_empty && !m_axi_wvalid &&
                        ((beat_count == launch_burst_len) || (respq_wr_ready && !respq_full))) begin
                        axi_state    <= ST_BURST_W_FETCH;
                    end
                    // No timeout in ST_BURST_W: inter-beat timing is
                    // controlled by the host via JTAG scans (~0.5 ms each),
                    // which is far longer than any AXI-side timeout.
                    // Timeout only applies to AXI handshake waits (wready,
                    // bvalid, arready, rvalid), not to host-paced data flow.
                end

                ST_BURST_W_FETCH: begin
                    launch_cmd   <= cmdq_cmd;
                    launch_wdata <= cmdq_wdata;
                    launch_wstrb <= cmdq_wstrb;
                    axi_state    <= ST_BURST_W_LOAD;
                end

                ST_BURST_W_LOAD: begin
                    if (launch_cmd == CMD_BURST_WDATA) begin
                        m_axi_wdata  <= launch_wdata;
                        m_axi_wstrb  <= launch_wstrb;
                        m_axi_wvalid <= 1'b1;
                        m_axi_wlast  <= (beat_count == launch_burst_len);
                        beat_count   <= beat_count + 1;
                        timeout_cnt  <= 12'd0;
                        axi_state <= ST_BURST_W;
                    end else begin
                        m_axi_wvalid <= 1'b0;
                        m_axi_wlast  <= 1'b0;
                        resp_code    <= 2'b10;
                        resp_rdata   <= {DATA_W{1'b0}};
                        axi_state    <= ST_DONE;
                    end
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
                    if (respq_wr_ready && !respq_full) begin
                        axi_state     <= ST_IDLE;
                    end
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
                    if (respq_wr_ready && !respq_full) begin
                        axi_state     <= ST_IDLE;
                    end
                end

                default: begin
                    axi_state <= ST_IDLE;
                end

            endcase
        end
    end

    // FIFO write enable: burst read data from AXI R-channel
    assign fifo_wr_en = (axi_state == ST_BURST_R_FILL) &&
                        m_axi_rvalid && !fifo_full;

    assign debug_axi = DEBUG_EN ? {
        cmdq_rd_data,
        launch_addr,
        launch_wdata,
        launch_wstrb,
        launch_cmd,
        axi_state,
        beat_count,
        launch_burst_len,
        resp_rdata,
        resp_code,
        respq_wr_en,
        respq_full,
        cmdq_rd_en,
        cmdq_empty,
        cmdq_rd_ready,
        cmdq_rd_rst_busy,
        respq_wr_ready,
        respq_wr_rst_busy,
        m_axi_bready,
        m_axi_bvalid,
        m_axi_wlast,
        m_axi_wready,
        m_axi_wvalid,
        m_axi_awready,
        m_axi_awvalid,
        m_axi_rready,
        m_axi_rvalid,
        m_axi_arready,
        m_axi_arvalid,
        m_axi_bresp,
        24'd0
    } : 256'd0;

    assign debug_axi_edge = DEBUG_EN ? {
        48'd0,
        dbg_axi_deq_count,
        dbg_axi_cycle_count,
        respq_wr_rst_busy,
        respq_wr_ready,
        respq_full,
        cmdq_rd_rst_busy,
        cmdq_rd_ready,
        cmdq_empty,
        cmdq_rd_en,
        beat_count,
        axi_state,
        launch_cmd,
        launch_wstrb,
        launch_wdata,
        launch_addr,
        cmdq_rd_data
    } : 256'd0;

endmodule
