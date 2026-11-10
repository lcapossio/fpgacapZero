// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Project-wide version + per-core identity defines.  AUTO-generated from
// the canonical VERSION file at the repo root by tools/sync_version.py.
`include "fcapz_version.vh"

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
//   STREAM_EN  - streaming read mode (default 0; needs DATA_W = 32)
//   *_FIFO_MEMORY_TYPE - XPM storage selectors ("auto", "block", "distributed")
//
// 72-bit DR format (LSB first):
//   Shift-in:  [31:0] addr, [63:32] payload, [67:64] wstrb, [71:68] cmd
//   Shift-out: [31:0] rdata, [63:32] info, [65:64] resp, [67:66] rsvd, [71:68] status
//
// Streaming read (STREAM_EN, FEATURES[24]):
//   CMD_STREAM_RSTART (addr = start, payload = word count) puts the DR in
//   stream mode.  The AXI side reads the range in INCR bursts that never
//   cross 4 KB and only start when the burst FIFO has room for the whole
//   burst, so the slave is never back-pressured.  Every DR scan in stream
//   mode, of any length, shifts out 33-bit slots (LSB first):
//     slot = {data[31:0], valid}
//   Slot 0 of every scan is a header, valid = 0, data = words not yet
//   delivered (lets the host detect a scan it did not issue).  A word
//   slot has valid = 1; valid = 0 means the FIFO was empty and nothing
//   was consumed.  A word counts as delivered only once all 33 bits have
//   been shifted out; a scan that ends inside a slot re-sends that word
//   in the next scan.  TDI must be 0: a scan that shifts in any 1 aborts
//   the stream exactly like CMD_RESET.  Stream mode ends at the UPDATE of
//   the first scan whose header reads 0, so the host confirms the count
//   of the last words it took with one more (header-only, 33-bit) scan;
//   the next normal scan returns the stream's AXI response (first non-OKAY
//   resp of the range) with prev_valid.

module fcapz_ejtagaxi #(
    parameter ADDR_W     = 32,
    parameter DATA_W     = 32,
    parameter FIFO_DEPTH = 16,
    parameter CMD_FIFO_DEPTH  = FIFO_DEPTH * 2,
    parameter RESP_FIFO_DEPTH = FIFO_DEPTH * 2,
    parameter TIMEOUT    = 4096,
    parameter DEBUG_EN   = 0,
    parameter STREAM_EN  = 0,
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
    output wire                   m_axi_rready,

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
    localparam CMD_STREAM_RSTART = 4'hA;
    // Internal only: the TCK side queues the first BURST_WDATA after a
    // BURST_SETUP under this code, so the AXI side can tell a new burst from
    // continuation data.  The DR never accepts 4'hB (it decodes as a NOP).
    localparam CMD_BURST_WFIRST = 4'hB;
    localparam CMD_CONFIG      = 4'hE;
    localparam CMD_RESET       = 4'hF;

    // AXI FSM states
    // (Codes 2, 5, 6, 13 and 14 belonged to the old per-beat write states.)
    localparam [3:0] ST_IDLE        = 4'd0,
                     ST_W_WAIT      = 4'd1,
                     ST_AR          = 4'd3,
                     ST_WAIT_R      = 4'd4,
                     ST_BURST_AR    = 4'd7,
                     ST_BURST_R_FILL= 4'd8,
                     ST_DONE         = 4'd9,
                     ST_TIMEOUT_ERR  = 4'd10,
                     ST_CMD_FETCH    = 4'd11,
                     ST_CMD_DISPATCH = 4'd12,
                     ST_STREAM_ISSUE = 4'd15;

    // Config register addresses
    localparam CFG_VERSION   = 16'h0000;
    localparam CFG_VERSION_ALIAS = 16'h0004;
    localparam CFG_FEATURES  = 16'h002C;
    localparam CFG_AXI_STATUS = 16'h0030;
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
    // Write buffer index width (FIFO_DEPTH = 1 still needs one bit).
    localparam WB_AW = (FIFO_AW > 0) ? FIFO_AW : 1;
    localparam WB_W  = DATA_W + DATA_W/8;
    // Wide enough to count to TIMEOUT - 1 (12 bits at the default 4096).
    localparam TO_W = (TIMEOUT > 1) ? $clog2(TIMEOUT) : 1;
    localparam CMD_FIFO_AW = $clog2(CMD_FIFO_DEPTH);
    localparam RESP_FIFO_AW = $clog2(RESP_FIFO_DEPTH);
    // Encoded into FEATURES[23:16] as (FIFO_DEPTH-1) so 256 fits in 8 bits.
    localparam [7:0] FIFO_DEPTH_ENC = FIFO_DEPTH - 1;
    localparam CMDQ_W  = 4 + ADDR_W + DATA_W + (DATA_W/8) + 8 + 3 + 2;
    localparam RESPQ_W = DATA_W + 2;

    // Streaming read: one 33-bit slot per word; bursts of a quarter of the
    // burst FIFO, started only while the FIFO has room for all of them plus
    // a small margin for the FIFO's own count latency.
    localparam [0:0] STREAM_ON = (STREAM_EN != 0) && (DATA_W == 32);
    localparam SLOT_W        = 33;
    localparam STREAM_BURST  = (FIFO_DEPTH >= 4) ? FIFO_DEPTH / 4 : 1;
    localparam STREAM_MARGIN = (FIFO_DEPTH >= 16) ? 4 : 0;
    localparam STREAM_LIMIT  = FIFO_DEPTH - STREAM_BURST - STREAM_MARGIN;

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
        if (ADDR_W < 12)
            ADDR_W_must_be_at_least_12 _addr_w_check_FAILED();
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
        if (ADDR_W < 12)
            $error("fcapz_ejtagaxi: ADDR_W must be >= 12 (got %0d)", ADDR_W);
    end

    // ========================================================================
    //  AXI_CLK domain registers
    // ========================================================================
    // Declared ahead of the TCK logic, which reads several of them; Verilog
    // requires a declaration before use, and newer Icarus releases enforce it.

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
    reg        rready_q;   // R-channel ready for single reads
    reg        r_drain;    // discard the rest of a read cut off by RESET or an R timeout
    reg            ar_orphan;  // ARVALID left up by a timeout or RESET, held to AR handshake
    reg [TO_W-1:0] drain_cnt;  // cycles without progress while a channel is owed (saturates)
    reg [TO_W-1:0] timeout_cnt;
    reg [7:0]  beat_count;
    (* ASYNC_REG = "TRUE" *) reg reset_req_sync1_axi;
    (* ASYNC_REG = "TRUE" *) reg reset_req_sync2_axi;
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

    // -- Streaming read (axi_clk domain) --------------------------------------
    reg                 strm_active;   // ST_BURST_AR/R_FILL serve the stream
    reg [ADDR_W-1:0]    strm_addr;     // next burst address
    reg [31:0]          strm_left;     // words not yet requested
    reg [7:0]           strm_len;      // beats of the next burst
    reg                 strm_len_ok;   // strm_len computed for strm_addr/left
    reg [1:0]           strm_err;      // first non-OKAY rresp of the stream

    // -- Write path (axi_clk domain) ------------------------------------------
    // A write reaches the bus only once all its beats are in wbuf: a burst is
    // collected beat by beat (each beat acknowledged as it arrives) and an
    // incomplete one is discarded without any bus activity.  The write engine
    // then owns AW/W/B until the slave's B, whatever the host or CMD_RESET do
    // meanwhile (we_detached: finish, but report nothing).
    reg [WB_W-1:0]      wbuf [0:FIFO_DEPTH-1];
    reg [WB_W-1:0]      wbuf_q;        // registered read of wbuf[we_w_idx]
    reg                 wb_collecting; // burst beats still to come
    reg                 wb_bad;        // burst refused: its beats answer SLVERR
    reg [8:0]           wb_cnt;        // beats of the burst received so far
    reg [ADDR_W-1:0]    wb_addr;       // descriptor of the burst being collected
    reg [7:0]           wb_len;
    reg [2:0]           wb_size;
    reg [1:0]           wb_type;
    reg                 we_start;      // host FSM -> engine: start we_d_*
    reg                 we_detach;     // host FSM -> engine: report nothing
    reg [ADDR_W-1:0]    we_d_addr;
    reg [7:0]           we_d_len;
    reg [2:0]           we_d_size;
    reg [1:0]           we_d_type;
    reg                 we_busy;       // engine owns AW/W/B
    reg                 we_detached;
    reg                 we_aw_done;
    reg [8:0]           we_w_idx;      // next beat to present
    reg [8:0]           we_w_done;     // W handshakes so far
    reg [7:0]           we_len;
    reg                 we_rd_ok;      // wbuf_q holds beat we_w_idx
    reg                 we_done;       // pulse: an attached write finished
    reg [1:0]           we_bresp;
    reg                 we_progress;   // pulse: an AW, W or B handshake

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
    (* ASYNC_REG = "TRUE" *) reg reset_ack_sync1_tck;
    (* ASYNC_REG = "TRUE" *) reg reset_ack_sync2_tck;
    reg        axi_owed;  // registered chan_busy (CFG_AXI_STATUS[5])
    (* ASYNC_REG = "TRUE" *) reg [5:0] axi_status_sync1_tck;
    (* ASYNC_REG = "TRUE" *) reg [5:0] axi_status_sync2_tck;

    // Streaming read (tck domain)
    reg              stream_mode;
    reg [31:0]       stream_left;      // words not yet delivered
    reg              stream_hold_full; // word in the slot, or re-sent next scan
    reg [31:0]       stream_hold;
    reg              stream_nxt_valid; // look-ahead word popped from the FIFO
    reg [31:0]       stream_nxt;
    reg              stream_slot_valid;
    reg [5:0]        stream_bitpos;    // shift edges into the current slot
    reg              stream_tdi_one;   // any TDI 1 this scan: abort
    reg              stream_hdr_zero;  // this scan's header read 0: last scan
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

    // TCK-domain reset: axi_rst asserts it at once, and it releases on the
    // second TCK edge after axi_rst ends. It resets the TCK sides of the async
    // FIFOs (so their release is synchronous to TCK) and the TCK command state,
    // so no staged command outlives a reset. That includes power-up on devices
    // that drop register initial values (PolarFire), where axi_rst comes from
    // the device power-on reset.
    (* ASYNC_REG = "TRUE" *) reg [1:0] tck_rst_sync;
    initial tck_rst_sync = 2'b11;
    always @(posedge tck or posedge axi_rst) begin
        if (axi_rst)
            tck_rst_sync <= 2'b11;
        else
            tck_rst_sync <= {tck_rst_sync[0], 1'b0};
    end
    wire tck_rst = tck_rst_sync[1];

    wire cmdq_wr_ready        = !cmdq_wr_rst_busy;
    wire cmdq_rd_ready        = !cmdq_rd_rst_busy;
    wire respq_wr_ready       = !respq_wr_rst_busy;
    wire respq_rd_ready       = !respq_rd_rst_busy;
    wire cmdq_stage_ready     = !cmdq_stage_valid;

    assign cmdq_wr_en   = !tck_rst && cmdq_stage_valid && cmdq_wr_ready && !cmdq_full;
    assign cmdq_wr_data = cmdq_stage_data;

    // ---- Async FIFO instance (burst read buffer) -----------------------------
    wire                  fifo_wr_en;
    wire                  fifo_full;
    wire                  fifo_rd_en;
    wire [DATA_W-1:0]     fifo_rdata;
    wire                  fifo_empty;
    wire [FIFO_AW:0]      fifo_rd_count;
    wire [FIFO_AW:0]      fifo_wr_count;
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
        .wr_rst   (tck_rst | cmdq_rst_tck),
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
        .rd_rst   (tck_rst | respq_rst_tck),
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
        .rd_rst   (tck_rst | fifo_rst_tck),
        .rd_en    (fifo_rd_en),
        .rd_data  (fifo_rdata),
        .rd_empty (fifo_empty),
        .rd_rst_busy (),
        .rd_count (fifo_rd_count),
        .wr_count (fifo_wr_count)
    );

    // In stream mode the DR holds slot data, not a command: UPDATE decodes
    // nothing, except that a scan with a TDI 1 in it acts as CMD_RESET.
    wire       stream_on_now = STREAM_ON && stream_mode;
    wire [3:0] upd_cmd       = stream_on_now ? CMD_RESET : sr_cmd;

    // Stream look-ahead: pop the FIFO head into stream_nxt whenever it is free
    // (any TCK edge; the slot logic consumes it at a slot boundary).
    wire stream_pop = stream_on_now && !stream_nxt_valid && fifo_notempty;

    // FIFO read: pop on UPDATE when BURST_RDATA and previous scan also read
    assign fifo_rd_en = (sel && update && !stream_on_now &&
                         (sr_cmd == CMD_BURST_RDATA) &&
                         fifo_notempty && (last_cmd == CMD_BURST_RDATA)) ||
                        stream_pop;

    // Next slot at a slot boundary.  A valid slot is always stream_hold; once
    // its last bit is out it is delivered and stream_hold frees up.
    wire        stream_hold_busy = stream_hold_full && !stream_slot_valid;
    wire [31:0] stream_left_after = stream_left - {31'd0, stream_slot_valid};
    wire        stream_take_nxt  = !stream_hold_busy && stream_nxt_valid &&
                                   (stream_left_after != 32'd0);

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
    assign cmdq_rd_en = cmdq_rd_ready && !cmdq_empty && (axi_state == ST_CMD_FETCH);

    // One response per queued command, each pushed by ST_DONE or
    // ST_TIMEOUT_ERR (both wait for room).  An intermediate burst beat is
    // answered OKAY when it is stored; the last one with the write's B.
    wire done_resp_push =
        (axi_state == ST_DONE) && respq_wr_ready && !respq_full;

    wire timeout_resp_push =
        (axi_state == ST_TIMEOUT_ERR) && respq_wr_ready && !respq_full;

    assign respq_wr_en = done_resp_push || timeout_resp_push;

    assign respq_wr_data =
        done_resp_push    ? {resp_code, resp_rdata} :
        timeout_resp_push ? {2'b10, {DATA_W{1'b0}}} :
                            {RESPQ_W{1'b0}};

    // First BURST_WDATA after a BURST_SETUP: queued as CMD_BURST_WFIRST.
    wire       burst_w_first = (burst_w_beats_left == {1'b0, burst_awlen} + 9'd1);
    wire [3:0] burst_w_cmd   = burst_w_first ? CMD_BURST_WFIRST : CMD_BURST_WDATA;

    // AXI-side bus state for CFG_AXI_STATUS: flags, each a flop output,
    // synchronized per bit.  Bits can pass the synchronizers a TCK apart (an
    // AR handed from ar_orphan to r_drain may show neither for a moment), so
    // "anything owed" is its own flop, axi_owed, which stays high across such
    // hand-overs; hosts test that one bit for idle.
    wire [5:0] axi_status_axi = {axi_owed, wb_collecting, r_drain, ar_orphan,
                                 we_detached, we_busy};

    // ---- TCK: main CAPTURE / SHIFT / UPDATE logic ---------------------------
    always @(posedge tck) begin
        reset_ack_sync1_tck <= dut_reset_ack_toggle_axi;
        reset_ack_sync2_tck <= reset_ack_sync1_tck;
        axi_status_sync1_tck <= axi_status_axi;
        axi_status_sync2_tck <= axi_status_sync1_tck;
        cmdq_rst_tck  <= 1'b0;
        respq_rst_tck <= 1'b0;
        fifo_rst_tck  <= 1'b0;
        if (DEBUG_EN && cmdq_wr_en) begin
            cmdq_stage_valid <= 1'b0;
            dbg_tck_enqueue_count <= dbg_tck_enqueue_count + 1'b1;
        end else if (cmdq_wr_en) begin
            cmdq_stage_valid <= 1'b0;
        end
        if (stream_pop) begin
            stream_nxt       <= fifo_rdata;
            stream_nxt_valid <= 1'b1;
        end
        if (sel) begin
            respq_head_seen <= respq_rd_ready && !respq_empty;
            if (capture && stream_on_now) begin
                // Header slot: words still to deliver.  Leaves the response
                // queue alone; the stream's response is read after it ends.
                sr <= {{(DR_W-SLOT_W){1'b0}}, stream_left, 1'b0};
                stream_slot_valid <= 1'b0;
                stream_bitpos     <= 6'd0;
                stream_tdi_one    <= 1'b0;
                stream_hdr_zero   <= (stream_left == 32'd0);

            end else if (shift_en && stream_on_now) begin
                stream_tdi_one <= stream_tdi_one | tdi;
                if (stream_bitpos == SLOT_W - 1) begin
                    // Last bit of the slot is out: deliver it, load the next.
                    stream_bitpos <= 6'd0;
                    stream_left   <= stream_left_after;
                    if (stream_hold_busy) begin
                        // Re-send the word a previous scan cut short.
                        sr <= {{(DR_W-SLOT_W){1'b0}}, stream_hold, 1'b1};
                        stream_slot_valid <= 1'b1;
                    end else if (stream_take_nxt) begin
                        sr <= {{(DR_W-SLOT_W){1'b0}}, stream_nxt, 1'b1};
                        stream_hold       <= stream_nxt;
                        stream_hold_full  <= 1'b1;
                        stream_nxt_valid  <= 1'b0;
                        stream_slot_valid <= 1'b1;
                    end else begin
                        sr <= {DR_W{1'b0}};
                        stream_hold_full  <= 1'b0;
                        stream_slot_valid <= 1'b0;
                    end
                end else begin
                    sr <= {tdi, sr[DR_W-1:1]};
                    stream_bitpos <= stream_bitpos + 6'd1;
                end

            end else if (update && stream_on_now && !stream_tdi_one) begin
                // A word cut short stays in stream_hold for the next scan.
                prev_valid       <= 1'b0;
                resp_pop_pending <= 1'b0;
                if (stream_hdr_zero)
                    stream_mode <= 1'b0;

            end else if (capture) begin
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

                case (upd_cmd)
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
                            cmdq_stage_data  <= {burst_w_cmd, burst_addr,
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
                                dbg_tck_update_cmdq <= {burst_w_cmd, burst_addr,
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

                    CMD_STREAM_RSTART: begin
                        if (!STREAM_ON) begin
                            // Streaming not built in: NOP.
                        end else if (cmdq_wr_ready && !cmdq_full && cmdq_stage_ready) begin
                            cmdq_stage_valid <= 1'b1;
                            cmdq_stage_data  <= {CMD_STREAM_RSTART, sr_addr[ADDR_W-1:0],
                                                 sr_payload[DATA_W-1:0],
                                                 {(DATA_W/8){1'b0}},
                                                 burst_awlen, burst_awsize, burst_awburst};
                            pending_count <= pending_count + 1'b1;
                            burst_cfg_valid <= 1'b0;
                            burst_w_beats_left <= 9'd0;
                            // The burst FIFO must be empty here (host sends
                            // CMD_RESET first); every word it then receives
                            // belongs to this stream.
                            stream_mode       <= (sr_payload != 32'd0);
                            stream_left       <= sr_payload;
                            stream_hold_full  <= 1'b0;
                            stream_nxt_valid  <= 1'b0;
                            stream_slot_valid <= 1'b0;
                            stream_bitpos     <= 6'd0;
                            stream_tdi_one    <= 1'b0;
                            stream_hdr_zero   <= 1'b0;
                        end else begin
                            error_sticky <= 1'b1;
                        end
                    end

                    CMD_CONFIG: begin
                        // Latch config value now (sr_addr is valid at update)
                        case (sr_addr[15:0])
                            CFG_VERSION:   config_rdata <= `FCAPZ_EJTAGAXI_VERSION_REG;
                            CFG_VERSION_ALIAS: config_rdata <= `FCAPZ_EJTAGAXI_VERSION_REG;
                            // FEATURES: [7:0]=ADDR_W, [15:8]=DATA_W,
                            // [23:16]=(FIFO_DEPTH-1)  (AXI4 awlen convention,
                            // so FIFO_DEPTH=256 fits as 0xFF; host adds 1),
                            // [24]=streaming read, [25]=bus-safe writes
                            // (buffered bursts, held VALIDs, owned B, burst
                            // checks, CFG_AXI_STATUS)
                            CFG_FEATURES:  config_rdata <= {6'd0,
                                                            1'b1,
                                                            STREAM_ON,
                                                            FIFO_DEPTH_ENC,
                                                            DATA_W[7:0],
                                                            ADDR_W[7:0]};
                            // AXI_STATUS: [0] write engine busy, [1] it
                            // finishes a write nobody waits for, [2] AR held
                            // after a timeout/RESET, [3] read beats being
                            // drained, [4] burst write being collected,
                            // [5] anything owed to the slave ([0]|[2]|[3]).
                            CFG_AXI_STATUS: config_rdata <= {26'd0, axi_status_sync2_tck};
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
                        stream_mode       <= 1'b0;
                        stream_left       <= 32'd0;
                        stream_hold_full  <= 1'b0;
                        stream_nxt_valid  <= 1'b0;
                        stream_slot_valid <= 1'b0;
                        stream_bitpos     <= 6'd0;
                        stream_tdi_one    <= 1'b0;
                        stream_hdr_zero   <= 1'b0;
                        reset_req_toggle <= ~reset_req_toggle;
                    end

                    default: begin
                        // Unknown command — treat as NOP
                    end
                endcase

                // Track last command for capture-time data source selection.
                // AXI commands update only when successfully enqueued.
                case (upd_cmd)
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
                            case (upd_cmd)
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

        // tck_rst (axi_rst, synchronized to TCK) clears the same TCK state as
        // CMD_RESET. Last in the block, so it overrides every assignment above.
        // The FIFOs' TCK sides are held by tck_rst directly. The CMD_RESET
        // request toggle is left alone: this block only runs on TCK edges, so
        // clearing it here could flip it after the AXI side is out of reset
        // and request a second reset; the AXI side rejoins the handshake
        // from its own axi_rst.
        if (tck_rst) begin
            error_sticky       <= 1'b0;
            prev_valid         <= 1'b0;
            respq_head_seen    <= 1'b0;
            resp_pop_pending   <= 1'b0;
            pending_count      <= {(CMD_FIFO_AW+1){1'b0}};
            cmdq_stage_valid   <= 1'b0;
            cmdq_stage_data    <= {CMDQ_W{1'b0}};
            auto_inc_addr      <= {ADDR_W{1'b0}};
            burst_awlen        <= 8'd0;
            burst_awsize       <= 3'b010;
            burst_awburst      <= 2'b01;
            burst_addr         <= {ADDR_W{1'b0}};
            burst_cfg_valid    <= 1'b0;
            burst_w_beats_left <= 9'd0;
            config_rdata       <= 32'h0;
            last_cmd           <= CMD_NOP;
            dbg_rec_count      <= 3'd0;
            dbg_resp_cap_rec_count <= 3'd0;
            stream_mode        <= 1'b0;
            stream_left        <= 32'd0;
            stream_hold_full   <= 1'b0;
            stream_nxt_valid   <= 1'b0;
            stream_slot_valid  <= 1'b0;
            stream_bitpos      <= 6'd0;
            stream_tdi_one     <= 1'b0;
            stream_hdr_zero    <= 1'b0;
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
        axi_status_sync1_tck = 6'd0;
        axi_status_sync2_tck = 6'd0;
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
        stream_mode       = 1'b0;
        stream_left       = 32'd0;
        stream_hold_full  = 1'b0;
        stream_hold       = 32'd0;
        stream_nxt_valid  = 1'b0;
        stream_nxt        = 32'd0;
        stream_slot_valid = 1'b0;
        stream_bitpos     = 6'd0;
        stream_tdi_one    = 1'b0;
        stream_hdr_zero   = 1'b0;
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
        strm_active         = 1'b0;
        strm_addr           = {ADDR_W{1'b0}};
        strm_left           = 32'd0;
        strm_len            = 8'd0;
        strm_len_ok         = 1'b0;
        strm_err            = 2'b00;
        timeout_cnt         = {TO_W{1'b0}};
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
        rready_q            = 1'b0;
        r_drain             = 1'b0;
        ar_orphan           = 1'b0;
        drain_cnt           = {TO_W{1'b0}};
        cmdq_rst_axi        = 1'b0;
        fifo_rst_axi        = 1'b0;
        respq_rst_axi       = 1'b0;
        wbuf_q              = {WB_W{1'b0}};
        wb_collecting       = 1'b0;
        wb_bad              = 1'b0;
        wb_cnt              = 9'd0;
        wb_addr             = {ADDR_W{1'b0}};
        wb_len              = 8'd0;
        wb_size             = 3'b010;
        wb_type             = 2'b01;
        we_start            = 1'b0;
        we_detach           = 1'b0;
        we_d_addr           = {ADDR_W{1'b0}};
        we_d_len            = 8'd0;
        we_d_size           = 3'b010;
        we_d_type           = 2'b01;
        we_busy             = 1'b0;
        we_detached         = 1'b0;
        we_aw_done          = 1'b0;
        we_w_idx            = 9'd0;
        we_w_done           = 9'd0;
        we_len              = 8'd0;
        we_rd_ok            = 1'b0;
        we_done             = 1'b0;
        we_bresp            = 2'b00;
        we_progress         = 1'b0;
    end

    // Burst descriptor check, before any VALID goes up: transfer size within
    // the bus, burst type not reserved, FIXED at most 16 beats, WRAP of 2, 4,
    // 8 or 16 beats from a size-aligned address, INCR inside one 4 KB page
    // counted from the size-aligned start.  A FIXED or aligned WRAP burst
    // never crosses 4 KB (its window is at most 2 KB and aligned).
    function burst_ok;
        input [ADDR_W-1:0] addr;
        input [7:0]        len;
        input [2:0]        size;
        input [1:0]        btype;
        reg   [11:0]       a0;
        reg   [16:0]       span;
        begin
            a0   = addr[11:0] & ~((12'd1 << size) - 12'd1);
            span = {5'd0, a0} + (({9'd0, len} + 17'd1) << size);
            if ((9'd1 << size) > (DATA_W / 8))
                burst_ok = 1'b0;
            else case (btype)
                2'b00:   burst_ok = (len <= 8'd15);
                2'b01:   burst_ok = (span <= 17'd4096);
                2'b10:   burst_ok = ((len == 8'd1) || (len == 8'd3) ||
                                     (len == 8'd7) || (len == 8'd15)) &&
                                    ((addr[6:0] & ((7'd1 << size) - 7'd1)) == 7'd0);
                default: burst_ok = 1'b0;
            endcase
        end
    endfunction

    // Read channel owes something: beats of an accepted read, or an AR held
    // up after a timeout/RESET.  Write channel owes something: we_busy.
    wire rd_busy   = r_drain || ar_orphan;
    wire chan_busy = rd_busy || we_busy;
    wire ar_hs     = m_axi_arvalid && m_axi_arready;

    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst)
            axi_owed <= 1'b0;
        else
            axi_owed <= chan_busy;
    end

    // A read the slave has accepted and not finished (see r_drain).
    wire r_inflight = (axi_state == ST_WAIT_R) || (axi_state == ST_BURST_R_FILL) || ar_hs;

    // Stream bursts: STREAM_BURST beats, cut at the stream end and at 4 KB.
    wire [10:0] strm_to_4k   = 11'd1024 - {1'b0, strm_addr[11:2]};
    wire [10:0] strm_len_a   = (strm_left < STREAM_BURST) ? strm_left[10:0]
                                                          : STREAM_BURST[10:0];
    wire [10:0] strm_len_nxt = (strm_to_4k < strm_len_a) ? strm_to_4k : strm_len_a;
    wire        strm_room    = ({1'b0, fifo_wr_count} <= STREAM_LIMIT);

    // First-beat check: refused bursts never reach the bus.
    wire wfirst_bad = we_busy ||
                      ({1'b0, launch_burst_len} >= FIFO_DEPTH) ||
                      !burst_ok(launch_addr, launch_burst_len,
                                launch_burst_size, launch_burst_type);

    // ---- Write buffer -------------------------------------------------------
    // Written in ST_CMD_DISPATCH (single write at 0, burst beat at its index),
    // never while the engine may still read it.  wbuf_q is a registered read,
    // so the buffer can map to block or distributed RAM.
    wire wb_store =
        (axi_state == ST_CMD_DISPATCH) && !we_busy &&
        ((launch_cmd == CMD_WRITE) ||
         ((launch_cmd == CMD_BURST_WFIRST) && ({1'b0, launch_burst_len} < FIFO_DEPTH)) ||
         ((launch_cmd == CMD_BURST_WDATA) && wb_collecting && !wb_bad));
    wire [8:0] wb_store_idx = (launch_cmd == CMD_BURST_WDATA) ? wb_cnt : 9'd0;

    always @(posedge axi_clk) begin
        if (wb_store)
            wbuf[wb_store_idx[WB_AW-1:0]] <= {launch_wstrb, launch_wdata};
        wbuf_q <= wbuf[we_w_idx[WB_AW-1:0]];
    end

    // ---- Write engine -------------------------------------------------------
    // Owns AW, W and B for one write at a time.  AW and W are independent (W
    // may complete first); each VALID and its payload stay unchanged until its
    // handshake; exactly we_len + 1 beats go out, WLAST on the last; the B is
    // always taken.  Only axi_rst stops it.  A detached write (host timeout or
    // CMD_RESET) completes the same way and reports nothing.
    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst) begin
            m_axi_awaddr  <= {ADDR_W{1'b0}};
            m_axi_awlen   <= 8'd0;
            m_axi_awsize  <= 3'b010;
            m_axi_awburst <= 2'b01;
            m_axi_awvalid <= 1'b0;
            m_axi_wdata   <= {DATA_W{1'b0}};
            m_axi_wstrb   <= {(DATA_W/8){1'b0}};
            m_axi_wvalid  <= 1'b0;
            m_axi_wlast   <= 1'b0;
            m_axi_bready  <= 1'b0;
            we_busy       <= 1'b0;
            we_detached   <= 1'b0;
            we_aw_done    <= 1'b0;
            we_w_idx      <= 9'd0;
            we_w_done     <= 9'd0;
            we_len        <= 8'd0;
            we_rd_ok      <= 1'b0;
            we_done       <= 1'b0;
            we_bresp      <= 2'b00;
            we_progress   <= 1'b0;
        end else begin
            we_done     <= 1'b0;
            we_progress <= 1'b0;
            we_rd_ok    <= 1'b1;  // we_w_idx held a cycle: wbuf_q is its beat
            if (!we_busy) begin
                if (we_start) begin
                    m_axi_awaddr  <= we_d_addr;
                    m_axi_awlen   <= we_d_len;
                    m_axi_awsize  <= we_d_size;
                    m_axi_awburst <= we_d_type;
                    m_axi_awvalid <= 1'b1;
                    we_busy       <= 1'b1;
                    we_detached   <= 1'b0;
                    we_aw_done    <= 1'b0;
                    we_w_idx      <= 9'd0;
                    we_w_done     <= 9'd0;
                    we_len        <= we_d_len;
                    we_rd_ok      <= 1'b0;
                end
            end else begin
                if (we_detach)
                    we_detached <= 1'b1;
                if (m_axi_awvalid && m_axi_awready) begin
                    m_axi_awvalid <= 1'b0;
                    we_aw_done    <= 1'b1;
                    we_progress   <= 1'b1;
                end
                if (m_axi_wvalid && m_axi_wready) begin
                    m_axi_wvalid <= 1'b0;
                    m_axi_wlast  <= 1'b0;
                    we_w_done    <= we_w_done + 9'd1;
                    we_progress  <= 1'b1;
                end else if (!m_axi_wvalid && (we_w_idx <= {1'b0, we_len}) && we_rd_ok) begin
                    m_axi_wdata  <= wbuf_q[DATA_W-1:0];
                    m_axi_wstrb  <= wbuf_q[WB_W-1:DATA_W];
                    m_axi_wvalid <= 1'b1;
                    m_axi_wlast  <= (we_w_idx == {1'b0, we_len});
                    we_w_idx     <= we_w_idx + 9'd1;
                    we_rd_ok     <= 1'b0;
                end
                // B once AW and every beat are through.
                if (we_aw_done && (we_w_done == {1'b0, we_len} + 9'd1))
                    m_axi_bready <= 1'b1;
                if (m_axi_bready && m_axi_bvalid) begin
                    m_axi_bready <= 1'b0;
                    we_busy      <= 1'b0;
                    we_detached  <= 1'b0;
                    we_progress  <= 1'b1;
                    if (!we_detached && !we_detach) begin
                        we_done  <= 1'b1;
                        we_bresp <= m_axi_bresp;
                    end
                end
            end
        end
    end

    // ---- AXI master FSM -----------------------------------------------------
    always @(posedge axi_clk or posedge axi_rst) begin
        if (axi_rst) begin
            axi_state         <= ST_IDLE;
            timeout_cnt       <= {TO_W{1'b0}};
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
            m_axi_araddr      <= {ADDR_W{1'b0}};
            m_axi_arlen       <= 8'd0;
            m_axi_arsize      <= 3'b010;
            m_axi_arburst     <= 2'b01;
            m_axi_arvalid     <= 1'b0;
            rready_q          <= 1'b0;
            r_drain           <= 1'b0;
            ar_orphan         <= 1'b0;
            drain_cnt         <= {TO_W{1'b0}};
            cmdq_rst_axi      <= 1'b0;
            fifo_rst_axi      <= 1'b0;
            respq_rst_axi     <= 1'b0;
            strm_active       <= 1'b0;
            strm_addr         <= {ADDR_W{1'b0}};
            strm_left         <= 32'd0;
            strm_len          <= 8'd0;
            strm_len_ok       <= 1'b0;
            strm_err          <= 2'b00;
            wb_collecting     <= 1'b0;
            wb_bad            <= 1'b0;
            wb_cnt            <= 9'd0;
            wb_addr           <= {ADDR_W{1'b0}};
            wb_len            <= 8'd0;
            wb_size           <= 3'b010;
            wb_type           <= 2'b01;
            we_start          <= 1'b0;
            we_detach         <= 1'b0;
            we_d_addr         <= {ADDR_W{1'b0}};
            we_d_len          <= 8'd0;
            we_d_size         <= 3'b010;
            we_d_type         <= 2'b01;
        end else begin
            reset_req_sync1_axi <= reset_req_toggle;
            we_start  <= 1'b0;
            we_detach <= 1'b0;
            // The drain only ends at RLAST: a beat that arrives however late
            // is still discarded.  While a channel is owed (drain, held AR,
            // busy write engine) commands wait for it at most TIMEOUT cycles
            // without progress (drain_cnt); after that they run, but a read
            // answers SLVERR without an AR while the read channel is owed and
            // a write answers SLVERR without an AW while the engine is busy
            // (ST_CMD_DISPATCH), so a slave that never answers cannot wedge
            // the bridge, and nothing owed to the slave is ever withdrawn.
            if (r_drain && m_axi_rvalid && m_axi_rlast)
                r_drain <= 1'b0;
            if (!chan_busy || (r_drain && m_axi_rvalid) || ar_hs || we_progress)
                drain_cnt <= {TO_W{1'b0}};
            else if (drain_cnt < TIMEOUT - 1)
                drain_cnt <= drain_cnt + 1;
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
                // CMD_RESET clears the host side only.  Whatever the slave
                // is owed stays owed: a write in the engine is detached and
                // finishes, an AR not yet accepted stays up (ar_orphan) and a
                // read already accepted is drained (r_drain).
                reset_req_seen_axi     <= reset_req_sync2_axi;
                dut_reset_ack_toggle_axi <= reset_req_sync2_axi;
                axi_state              <= ST_IDLE;
                timeout_cnt            <= {TO_W{1'b0}};
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
                rready_q               <= 1'b0;
                cmdq_rst_axi           <= 1'b1;
                respq_rst_axi          <= 1'b1;
                fifo_rst_axi           <= 1'b1;
                strm_active            <= 1'b0;
                strm_len_ok            <= 1'b0;
                wb_collecting          <= 1'b0;
                wb_bad                 <= 1'b0;
                we_detach              <= 1'b1;
                // An AR the slave takes in this very cycle is done (its read
                // is drained below); one it has not taken stays up.
                if (ar_hs)
                    m_axi_arvalid <= 1'b0;
                else if (m_axi_arvalid)
                    ar_orphan <= 1'b1;
                // A read already accepted by the slave is drained, so its
                // beats cannot land in the next command (an aborted stream
                // usually has a burst in flight).
                if (r_inflight && !(m_axi_rvalid && m_axi_rready && m_axi_rlast))
                    r_drain <= 1'b1;
                if (DEBUG_EN) begin
                    dbg_resp_wr_rec_count  <= 3'd0;
                    dbg_axi_deq_rec_count  <= 3'd0;
                end
            end else case (axi_state)

                // ---- Idle: consume next queued command ----
                ST_IDLE: begin
                    rready_q      <= 1'b0;
                    timeout_cnt   <= {TO_W{1'b0}};
                    beat_count    <= 8'd0;

                    if (!cmdq_empty && (!chan_busy || drain_cnt >= TIMEOUT - 1)) begin
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
                    // Any command but continuation data ends a burst being
                    // collected; its beats never reach the bus.
                    wb_collecting <= 1'b0;
                    timeout_cnt   <= {TO_W{1'b0}};
                    case (launch_cmd)
                        CMD_WRITE: begin
                            if (we_busy) begin
                                resp_code  <= 2'b10;
                                resp_rdata <= {DATA_W{1'b0}};
                                axi_state  <= ST_DONE;
                            end else begin
                                // wbuf[0] is written this cycle (wb_store).
                                we_d_addr <= launch_addr;
                                we_d_len  <= 8'd0;
                                we_d_size <= 3'b010;
                                we_d_type <= 2'b01;
                                we_start  <= 1'b1;
                                axi_state <= ST_W_WAIT;
                            end
                        end

                        CMD_READ: begin
                            if (rd_busy) begin
                                // Read channel still owed: no AR.
                                axi_state     <= ST_TIMEOUT_ERR;
                            end else begin
                                m_axi_araddr  <= launch_addr;
                                m_axi_arlen   <= 8'd0;
                                m_axi_arsize  <= 3'b010;
                                m_axi_arburst <= 2'b01;
                                m_axi_arvalid <= 1'b1;
                                axi_state     <= ST_AR;
                            end
                        end

                        CMD_BURST_WFIRST: begin
                            // First beat of a burst: latch its descriptor.
                            // A refused burst (bad descriptor, longer than
                            // the buffer, engine busy) answers SLVERR for
                            // every beat and never reaches the bus.
                            wb_addr <= launch_addr;
                            wb_len  <= launch_burst_len;
                            wb_size <= launch_burst_size;
                            wb_type <= launch_burst_type;
                            wb_cnt  <= 9'd1;
                            wb_bad  <= wfirst_bad;
                            if (wfirst_bad) begin
                                wb_collecting <= (launch_burst_len != 8'd0);
                                resp_code     <= 2'b10;
                                resp_rdata    <= {DATA_W{1'b0}};
                                axi_state     <= ST_DONE;
                            end else if (launch_burst_len == 8'd0) begin
                                we_d_addr <= launch_addr;
                                we_d_len  <= launch_burst_len;
                                we_d_size <= launch_burst_size;
                                we_d_type <= launch_burst_type;
                                we_start  <= 1'b1;
                                axi_state <= ST_W_WAIT;
                            end else begin
                                wb_collecting <= 1'b1;
                                resp_code     <= 2'b00;
                                resp_rdata    <= {DATA_W{1'b0}};
                                axi_state     <= ST_DONE;
                            end
                        end

                        CMD_BURST_WDATA: begin
                            if (!wb_collecting) begin
                                // Continuation data with no burst open.
                                resp_code  <= 2'b10;
                                resp_rdata <= {DATA_W{1'b0}};
                                axi_state  <= ST_DONE;
                            end else if (wb_cnt == {1'b0, wb_len}) begin
                                // Last beat: the whole burst is buffered.
                                if (wb_bad) begin
                                    resp_code  <= 2'b10;
                                    resp_rdata <= {DATA_W{1'b0}};
                                    axi_state  <= ST_DONE;
                                end else begin
                                    we_d_addr <= wb_addr;
                                    we_d_len  <= wb_len;
                                    we_d_size <= wb_size;
                                    we_d_type <= wb_type;
                                    we_start  <= 1'b1;
                                    axi_state <= ST_W_WAIT;
                                end
                            end else begin
                                wb_collecting <= 1'b1;
                                wb_cnt        <= wb_cnt + 9'd1;
                                resp_code     <= wb_bad ? 2'b10 : 2'b00;
                                resp_rdata    <= {DATA_W{1'b0}};
                                axi_state     <= ST_DONE;
                            end
                        end

                        CMD_BURST_RSTART: begin
                            if (rd_busy) begin
                                axi_state     <= ST_TIMEOUT_ERR;
                            end else if (!burst_ok(launch_addr, launch_burst_len,
                                                   launch_burst_size, launch_burst_type)) begin
                                resp_code     <= 2'b10;
                                resp_rdata    <= {DATA_W{1'b0}};
                                axi_state     <= ST_DONE;
                            end else begin
                                m_axi_araddr  <= launch_addr;
                                m_axi_arlen   <= launch_burst_len;
                                m_axi_arsize  <= launch_burst_size;
                                m_axi_arburst <= launch_burst_type;
                                m_axi_arvalid <= 1'b1;
                                axi_state     <= ST_BURST_AR;
                            end
                        end

                        CMD_STREAM_RSTART: begin
                            if (STREAM_ON) begin
                                strm_addr   <= {launch_addr[ADDR_W-1:2], 2'b00};
                                strm_left   <= launch_wdata;
                                strm_err    <= 2'b00;
                                strm_len_ok <= 1'b0;
                                strm_active <= 1'b1;
                                axi_state   <= ST_STREAM_ISSUE;
                            end else begin
                                resp_code  <= 2'b00;
                                resp_rdata <= {DATA_W{1'b0}};
                                axi_state  <= ST_DONE;
                            end
                        end

                        default: begin
                            resp_code  <= 2'b00;
                            resp_rdata <= {DATA_W{1'b0}};
                            axi_state  <= ST_DONE;
                        end
                    endcase
                end

                // ---- Write: wait for the engine's B ----
                ST_W_WAIT: begin
                    if (we_done) begin
                        resp_code   <= we_bresp;
                        resp_rdata  <= {DATA_W{1'b0}};
                        axi_state   <= ST_DONE;
                    end else if (we_progress) begin
                        timeout_cnt <= {TO_W{1'b0}};
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1) begin
                            // No handshake for TIMEOUT cycles: answer SLVERR.
                            // The engine keeps every VALID up and takes the
                            // B whenever it comes, reporting nothing.
                            we_detach <= 1'b1;
                            axi_state <= ST_TIMEOUT_ERR;
                        end
                    end
                end

                // ---- Single read: AR phase ----
                ST_AR: begin
                    if (m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        rready_q      <= 1'b1;
                        axi_state     <= ST_WAIT_R;
                        timeout_cnt   <= {TO_W{1'b0}};
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1) begin
                            // ARVALID stays up until the slave takes it.
                            ar_orphan <= 1'b1;
                            axi_state <= ST_TIMEOUT_ERR;
                        end
                    end
                end

                // ---- Wait for read data ----
                ST_WAIT_R: begin
                    if (m_axi_rvalid) begin
                        resp_rdata   <= m_axi_rdata;
                        resp_code    <= m_axi_rresp;
                        rready_q     <= 1'b0;
                        axi_state    <= ST_DONE;
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1) begin
                            // The slave accepted the AR: drain the late
                            // beat so it cannot land in a later read.
                            r_drain   <= 1'b1;
                            axi_state <= ST_TIMEOUT_ERR;
                        end
                    end
                end

                // ---- Burst read: AR phase ----
                ST_BURST_AR: begin
                    if (m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        axi_state     <= ST_BURST_R_FILL;
                        timeout_cnt   <= {TO_W{1'b0}};
                    end else begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1) begin
                            ar_orphan <= 1'b1;
                            axi_state <= ST_TIMEOUT_ERR;
                        end
                    end
                end

                // ---- Burst read: fill FIFO from R-channel ----
                ST_BURST_R_FILL: begin
                    // m_axi_rready is !fifo_full here (assigned below), so
                    // a beat is accepted exactly when fifo_wr_en writes it.
                    if (m_axi_rvalid && !fifo_full) begin
                        timeout_cnt    <= {TO_W{1'b0}};
                        if (strm_active && m_axi_rresp != 2'b00 && strm_err == 2'b00)
                            strm_err <= m_axi_rresp;
                        if (m_axi_rlast && strm_active) begin
                            strm_addr <= strm_addr + {{(ADDR_W-10){1'b0}}, strm_len, 2'b00};
                            strm_left <= strm_left - {24'd0, strm_len};
                            axi_state <= ST_STREAM_ISSUE;
                        end else if (m_axi_rlast) begin
                            resp_code    <= m_axi_rresp;
                            resp_rdata   <= m_axi_rdata;
                            axi_state    <= ST_DONE;
                        end
                    end else if (!m_axi_rvalid) begin
                        timeout_cnt <= timeout_cnt + 1;
                        if (timeout_cnt >= TIMEOUT - 1) begin
                            // Drain the rest of the burst: left on the R
                            // channel it would become the first beats of
                            // the next read (or stream) with resp OKAY.
                            r_drain   <= 1'b1;
                            axi_state <= ST_TIMEOUT_ERR;
                        end
                    end
                end

                // ---- Stream: next burst, or the stream's one response ----
                ST_STREAM_ISSUE: begin
                    if (strm_left == 32'd0) begin
                        resp_code   <= strm_err;
                        resp_rdata  <= {DATA_W{1'b0}};
                        strm_active <= 1'b0;
                        axi_state   <= ST_DONE;
                    end else if (!strm_len_ok) begin
                        strm_len    <= strm_len_nxt[7:0];
                        strm_len_ok <= 1'b1;
                    end else if (strm_room && !rd_busy) begin
                        // While earlier beats are still owed the stream
                        // stalls; the host sees no words and aborts.
                        m_axi_araddr  <= strm_addr;
                        m_axi_arlen   <= strm_len - 8'd1;
                        m_axi_arsize  <= 3'b010;
                        m_axi_arburst <= 2'b01;
                        m_axi_arvalid <= 1'b1;
                        strm_len_ok   <= 1'b0;
                        timeout_cnt   <= {TO_W{1'b0}};
                        axi_state     <= ST_BURST_AR;
                    end
                    // No timeout while waiting for room: the host drains the
                    // FIFO at JTAG pace.
                end

                // ---- Transaction complete: push the response ----
                ST_DONE: begin
                    rready_q      <= 1'b0;
                    if (respq_wr_ready && !respq_full) begin
                        axi_state     <= ST_IDLE;
                    end
                end

                // ---- Timeout error: push SLVERR ----
                ST_TIMEOUT_ERR: begin
                    strm_active   <= 1'b0;
                    rready_q      <= 1'b0;
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

            // An AR left up by a timeout or RESET: drop it at its handshake,
            // whatever the FSM is doing, and drain the read it started.
            if (ar_orphan && ar_hs) begin
                m_axi_arvalid <= 1'b0;
                ar_orphan     <= 1'b0;
                r_drain       <= 1'b1;
            end
        end
    end

    // FIFO write enable: burst read data from AXI R-channel
    assign fifo_wr_en = (axi_state == ST_BURST_R_FILL) &&
                        m_axi_rvalid && !fifo_full;

    // Burst fill: ready is the FIFO's own !full, not a registered copy.  A
    // registered copy stayed high in the cycle the FIFO filled, so the slave
    // handed over a beat that fifo_wr_en did not write.
    assign m_axi_rready = r_drain                        ? 1'b1       :
                          (axi_state == ST_BURST_R_FILL) ? !fifo_full : rready_q;

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
