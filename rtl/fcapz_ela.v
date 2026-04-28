// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Project-wide version + per-core identity defines.  AUTO-generated from
// the canonical VERSION file at the repo root by tools/sync_version.py.
// CI verifies this header is in sync (`python tools/sync_version.py --check`).
`include "fcapz_version.vh"

// ELA-style capture core with optional advanced features.
//
// Parameters:
//   SAMPLE_W     - probe width (1 to 256+ bits) per channel
//   DEPTH        - sample buffer depth
//   TRIG_STAGES  - trigger sequencer stages (1 = simple, 2-4 = sequencer)
//   STOR_QUAL    - storage qualification (0 = off, 1 = on)
//   NUM_CHANNELS - number of mutually-exclusive probe buses (default 1)
//   INPUT_PIPE   - number of pipeline register stages on probe_in (0 = none)
//   TIMESTAMP_W  - timestamp counter width (0 = disabled, 32 or 48 = enabled)
//   NUM_SEGMENTS - number of capture segments (1 = single capture, >1 = segmented)
//   REL_COMPARE  - 1 enables relational trigger modes (<, >, <=, >=)
//
// When NUM_CHANNELS=1, probe_in width is unchanged (backward compatible).
// All optional features are gated by parameters. The smallest core uses:
//   TRIG_STAGES=1, STOR_QUAL=0, DECIM_EN=0, EXT_TRIG_EN=0,
//   TIMESTAMP_W=0, NUM_SEGMENTS=1
// and all extra logic optimizes away in synthesis.

module fcapz_ela #(
    parameter SAMPLE_W    = 32,
    parameter DEPTH       = 1024,
    parameter TRIG_STAGES = 1,      // 1 = simple, 2-4 = sequencer
    parameter STOR_QUAL   = 0,      // 0 = off, 1 = storage qualification
    parameter NUM_CHANNELS = 1,     // probe mux channels (1 = single bus)
    parameter INPUT_PIPE  = 0,      // input pipeline stages (0 = none)
    parameter DECIM_EN    = 0,      // 0 = no decimation, 1 = enable
    parameter EXT_TRIG_EN = 0,      // 0 = no ext trigger ports, 1 = enable
    parameter TIMESTAMP_W = 0,      // timestamp width (0=off, 32 or 48)
    parameter NUM_SEGMENTS = 1,     // capture segments (1 = normal)
    parameter PROBE_MUX_W = 0,      // 0=disabled, >0=total probe width for runtime mux
    parameter STARTUP_ARM = 0,      // 1 = arm automatically after reset/programming
    parameter DEFAULT_TRIG_EXT = 0, // reset/default external trigger mode
    parameter REL_COMPARE = 0,      // 0=small/faster trigger, 1=enable < > <= >=
    parameter DUAL_COMPARE = 1,     // 0=A-only trigger compare, 1=enable comparator B
    parameter USER1_DATA_EN = 1     // 0=disable slow USER1 DATA window readback
) (
    input  wire                              sample_clk,
    input  wire                              sample_rst,
    input  wire [(PROBE_MUX_W > 0 ? PROBE_MUX_W : NUM_CHANNELS*SAMPLE_W)-1:0] probe_in,

    // External trigger I/O
    input  wire                 trigger_in,
    output wire                 trigger_out,
    output wire                 armed_out,

    input  wire                 jtag_clk,
    input  wire                 jtag_rst,
    input  wire                 jtag_wr_en,
    input  wire                 jtag_rd_en,
    input  wire [15:0]          jtag_addr,
    input  wire [31:0]          jtag_wdata,
    output reg  [31:0]          jtag_rdata,

    // Burst read port (jtag_clk domain, active when done=1)
    input  wire [$clog2(DEPTH)-1:0] burst_rd_addr,
    output wire [SAMPLE_W-1:0]      burst_rd_data,
    output wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data,
    output reg                       burst_start,
    output reg                       burst_timestamp,
    output reg  [$clog2(DEPTH)-1:0]  burst_start_ptr
);

    // ---- Address map -------------------------------------------------------
    localparam ADDR_VERSION     = 16'h0000;
    localparam ADDR_CTRL        = 16'h0004;
    localparam ADDR_STATUS      = 16'h0008;
    localparam ADDR_SAMPLE_W    = 16'h000C;
    localparam ADDR_DEPTH       = 16'h0010;
    localparam ADDR_PRETRIG     = 16'h0014;
    localparam ADDR_POSTTRIG    = 16'h0018;
    localparam ADDR_CAPTURE_LEN = 16'h001C;
    localparam ADDR_TRIG_MODE   = 16'h0020;
    localparam ADDR_TRIG_VALUE  = 16'h0024;
    localparam ADDR_TRIG_MASK   = 16'h0028;
    localparam ADDR_BURST_PTR   = 16'h002C;
    // Storage qualification registers (only used when STOR_QUAL=1)
    localparam ADDR_SQ_MODE     = 16'h0030;
    localparam ADDR_SQ_VALUE    = 16'h0034;
    localparam ADDR_SQ_MASK     = 16'h0038;
    localparam ADDR_FEATURES    = 16'h003C;
    // Sequencer stage registers (only used when TRIG_STAGES > 1)
    // Stage N: CFG       = 0x0040 + N*20
    //          VALUE_A   = 0x0044 + N*20
    //          MASK_A    = 0x0048 + N*20
    //          VALUE_B   = 0x004C + N*20
    //          MASK_B    = 0x0050 + N*20
    localparam ADDR_SEQ_BASE    = 16'h0040;
    localparam SEQ_STRIDE       = 20;  // 5 registers x 4 bytes
    // Channel mux registers
    localparam ADDR_CHAN_SEL    = 16'h00A0;  // RW: active channel (0..NUM_CHANNELS-1)
    localparam ADDR_NUM_CHAN    = 16'h00A4;  // RO: NUM_CHANNELS parameter value
    // Phase 1: decimation
    localparam ADDR_DECIM       = 16'h00B0;  // RW: 24-bit decimation ratio
    // Phase 2: external trigger
    localparam ADDR_TRIG_EXT    = 16'h00B4;  // RW: [1:0] ext trigger mode
    // Phase 4: segmented memory
    localparam ADDR_NUM_SEGMENTS = 16'h00B8; // RO
    localparam ADDR_SEG_STATUS  = 16'h00BC;  // RO
    localparam ADDR_SEG_SEL     = 16'h00C0;  // RW
    localparam ADDR_SEG_START   = 16'h00C8;  // RO: seg_start_ptr[seg_sel] (CDC readback)
    // Phase 3: timestamp
    localparam ADDR_TIMESTAMP_W = 16'h00C4;  // RO
    // Probe mux registers (only used when PROBE_MUX_W > 0)
    localparam ADDR_PROBE_SEL   = 16'h00AC;  // RW: [7:0] slice index
    localparam ADDR_PROBE_MUX_W = 16'h00D0;  // RO: PROBE_MUX_W parameter
    localparam ADDR_TRIG_DELAY  = 16'h00D4;  // RW: [15:0] post-trigger delay
                                             // (sample-clock cycles between
                                             // trigger event and committed
                                             // trigger sample; default 0)
    localparam ADDR_STARTUP_ARM = 16'h00D8;  // RW: [0] auto-arm after reset
    localparam ADDR_TRIG_HOLDOFF = 16'h00DC; // RW: [15:0] ignore triggers for
                                             // sample-clock cycles after arm/re-arm
    localparam ADDR_COMPARE_CAPS = 16'h00E0; // RO: compare modes implemented

    localparam ADDR_DATA_BASE   = 16'h0100;
    localparam [1:0] DEFAULT_TRIG_EXT_MODE = DEFAULT_TRIG_EXT[1:0];

    // ---- Parameter assertions (simulation) ------------------------------------
    initial begin
        if (DEPTH & (DEPTH - 1))
            $error("fcapz_ela: DEPTH must be a power of 2 (got %0d)", DEPTH);
        if (NUM_SEGMENTS > 1 && (DEPTH % NUM_SEGMENTS != 0))
            $error("fcapz_ela: DEPTH must be divisible by NUM_SEGMENTS (%0d)", NUM_SEGMENTS);
        if (TRIG_STAGES < 1 || TRIG_STAGES > 4)
            $error("fcapz_ela: TRIG_STAGES must be 1-4 (got %0d)", TRIG_STAGES);
        if (SAMPLE_W < 1)
            $error("fcapz_ela: SAMPLE_W must be >= 1");
        if (SAMPLE_W > 256)
            $error("fcapz_ela: SAMPLE_W must be <= 256 (got %0d)", SAMPLE_W);
        if (DEFAULT_TRIG_EXT < 0 || DEFAULT_TRIG_EXT > 3)
            $error("fcapz_ela: DEFAULT_TRIG_EXT must be 0-3 (got %0d)", DEFAULT_TRIG_EXT);
    end

    // Synthesis-safe upper-bound trap for SAMPLE_W
    generate
        if (SAMPLE_W > 256)
            SAMPLE_W_must_be_at_most_256 _sample_w_check_FAILED();
    endgenerate

    localparam PTR_W = $clog2(DEPTH);
    localparam WORDS_PER_SAMPLE = (SAMPLE_W + 31) / 32;
    localparam SEQ_STATE_W = (TRIG_STAGES > 1) ? $clog2(TRIG_STAGES) : 1;
    // INPUT_PIPE also registers compare hits so REL_COMPARE comparators stay
    // off the capture-control critical path. This adds one trigger-decision
    // cycle whenever probe input pipelining is enabled.
    localparam COMPARE_PIPE = (INPUT_PIPE >= 1) ? 1 : 0;
    localparam HAS_DUAL_COMPARE = (DUAL_COMPARE != 0);
    localparam HAS_USER1_DATA = (USER1_DATA_EN != 0);
    localparam HAS_SEQUENCER = (TRIG_STAGES > 1);
    localparam HAS_STOR_QUAL = (STOR_QUAL != 0);
    localparam HAS_DECIM = (DECIM_EN != 0);
    localparam HAS_EXT_TRIG = (EXT_TRIG_EN != 0);
    localparam HAS_SEGMENTS = (NUM_SEGMENTS > 1);
    localparam HAS_CHANNEL_MUX = (NUM_CHANNELS > 1);
    localparam HAS_PROBE_MUX = (PROBE_MUX_W > 0);

    // Phase 4: segment derived params
    localparam SEG_DEPTH = DEPTH / NUM_SEGMENTS;
    localparam SEG_PTR_W = $clog2(SEG_DEPTH);
    localparam SEG_IDX_W = (NUM_SEGMENTS > 1) ? $clog2(NUM_SEGMENTS) : 1;

    // Static assert: SEG_DEPTH must be a power-of-two (bitmask wrap arithmetic)
    generate
        if (SEG_DEPTH != 0 && (SEG_DEPTH & (SEG_DEPTH - 1)) != 0) begin : g_bad_seg_depth
            SEG_DEPTH_must_be_power_of_two invalid();
        end
    endgenerate

    // Phase 3: timestamp data base address
    localparam ADDR_TS_DATA_BASE = ADDR_DATA_BASE + DEPTH * WORDS_PER_SAMPLE * 4;
    // Timestamp words per entry
    localparam TS_WORDS = (TIMESTAMP_W > 0) ? ((TIMESTAMP_W + 31) / 32) : 0;

    // Probe mux derived params
    localparam PROBE_MUX_SLICES = (PROBE_MUX_W > 0) ? (PROBE_MUX_W / SAMPLE_W) : 0;

    // Feature flags: [3:0]=TRIG_STAGES, [4]=STOR_QUAL, [5]=HAS_DECIM,
    //                [6]=HAS_EXT_TRIG, [7]=HAS_TIMESTAMP,
    //                [15:8]=NUM_CHANNELS, [23:16]=NUM_SEGMENTS, [31:24]=TIMESTAMP_W
    localparam [31:0] FEATURES = {TIMESTAMP_W[7:0], NUM_SEGMENTS[7:0], NUM_CHANNELS[7:0],
                                  (TIMESTAMP_W > 0) ? 1'b1 : 1'b0,
                                  HAS_EXT_TRIG ? 1'b1 : 1'b0,
                                  HAS_DECIM ? 1'b1 : 1'b0,
                                  STOR_QUAL[0], TRIG_STAGES[3:0]};
    localparam [31:0] COMPARE_MODE_CAPS =
        (REL_COMPARE != 0) ? 32'h0000_01FF : 32'h0000_01C3;
    localparam [31:0] COMPARE_CAPS =
        COMPARE_MODE_CAPS | 32'h0002_0000 |
        (HAS_DUAL_COMPARE ? 32'h0001_0000 : 32'h0000_0000);

    // ---- Compare mode encoding -----------------------------------------------
    // CMP_MODE[3:0]: 0=EQ 1=NEQ 2=LT 3=GT 4=LEQ 5=GEQ 6=RISING 7=FALLING 8=CHANGED
    // COMBINE[1:0]:  0=A_only 1=B_only 2=A_AND_B 3=A_OR_B

    // ---- JTAG-domain registers ---------------------------------------------
    reg [31:0] jtag_ctrl;
    reg [31:0] jtag_pretrig_len;
    reg [31:0] jtag_posttrig_len;
    reg [31:0] jtag_trig_mode;   // legacy: [0]=value_match [1]=edge_detect
    reg [31:0] jtag_trig_value;  // legacy: comparator A value (stage 0)
    reg [31:0] jtag_trig_mask;   // legacy: comparator A mask (stage 0)
    reg        jtag_startup_arm;
    reg [15:0] jtag_trig_holdoff;
    reg [15:0] jtag_trig_delay;  // post-trigger delay (sample clocks)
    // Zero-extended to SAMPLE_W for sync pipeline.
    // SAMPLE_W <= 32: direct truncation (Verilog replication count cannot be 0,
    //   so the ternary trick is avoided — assign from a wider intermediate).
    // SAMPLE_W > 32:  zero-pad upper bits.
    wire [SAMPLE_W-1:0] jtag_trig_value_w;
    wire [SAMPLE_W-1:0] jtag_trig_mask_w;
    generate
        if (SAMPLE_W <= 32) begin : g_trig_narrow
            assign jtag_trig_value_w = jtag_trig_value[SAMPLE_W-1:0];
            assign jtag_trig_mask_w  = jtag_trig_mask[SAMPLE_W-1:0];
        end else begin : g_trig_wide
            assign jtag_trig_value_w = {{(SAMPLE_W-32){1'b0}}, jtag_trig_value};
            assign jtag_trig_mask_w  = {{(SAMPLE_W-32){1'b0}}, jtag_trig_mask};
        end
    endgenerate

    reg [7:0] jtag_chan_sel;   // active channel (jtag_clk domain)

    reg arm_toggle_jtag;
    reg reset_toggle_jtag;

    // Storage qualification JTAG registers
    reg [31:0] jtag_sq_mode;   // [3:0]=cmp_mode
    reg [31:0] jtag_sq_value;
    reg [31:0] jtag_sq_mask;
    wire [SAMPLE_W-1:0] jtag_sq_value_w;
    wire [SAMPLE_W-1:0] jtag_sq_mask_w;
    generate
        if (SAMPLE_W <= 32) begin : g_sq_narrow
            assign jtag_sq_value_w = jtag_sq_value[SAMPLE_W-1:0];
            assign jtag_sq_mask_w  = jtag_sq_mask[SAMPLE_W-1:0];
        end else begin : g_sq_wide
            assign jtag_sq_value_w = {{(SAMPLE_W-32){1'b0}}, jtag_sq_value};
            assign jtag_sq_mask_w  = {{(SAMPLE_W-32){1'b0}}, jtag_sq_mask};
        end
    endgenerate

    // Per-stage sequencer JTAG registers
    reg [31:0] jtag_seq_cfg     [0:TRIG_STAGES-1];
    reg [31:0] jtag_seq_value_a [0:TRIG_STAGES-1];
    reg [31:0] jtag_seq_mask_a  [0:TRIG_STAGES-1];
    reg [31:0] jtag_seq_value_b [0:TRIG_STAGES-1];
    reg [31:0] jtag_seq_mask_b  [0:TRIG_STAGES-1];
    // Zero-extended per-stage wires (same generate pattern as trig/sq above)
    wire [SAMPLE_W-1:0] jtag_seq_value_a_w [0:TRIG_STAGES-1];
    wire [SAMPLE_W-1:0] jtag_seq_mask_a_w  [0:TRIG_STAGES-1];
    wire [SAMPLE_W-1:0] jtag_seq_value_b_w [0:TRIG_STAGES-1];
    wire [SAMPLE_W-1:0] jtag_seq_mask_b_w  [0:TRIG_STAGES-1];
    genvar gi;
    generate
        for (gi = 0; gi < TRIG_STAGES; gi = gi + 1) begin : g_seq_w
            if (SAMPLE_W <= 32) begin : g_narrow
                assign jtag_seq_value_a_w[gi] = jtag_seq_value_a[gi][SAMPLE_W-1:0];
                assign jtag_seq_mask_a_w[gi]  = jtag_seq_mask_a[gi][SAMPLE_W-1:0];
                assign jtag_seq_value_b_w[gi] = jtag_seq_value_b[gi][SAMPLE_W-1:0];
                assign jtag_seq_mask_b_w[gi]  = jtag_seq_mask_b[gi][SAMPLE_W-1:0];
            end else begin : g_wide
                assign jtag_seq_value_a_w[gi] = {{(SAMPLE_W-32){1'b0}}, jtag_seq_value_a[gi]};
                assign jtag_seq_mask_a_w[gi]  = {{(SAMPLE_W-32){1'b0}}, jtag_seq_mask_a[gi]};
                assign jtag_seq_value_b_w[gi] = {{(SAMPLE_W-32){1'b0}}, jtag_seq_value_b[gi]};
                assign jtag_seq_mask_b_w[gi]  = {{(SAMPLE_W-32){1'b0}}, jtag_seq_mask_b[gi]};
            end
        end
    endgenerate

    // Phase 1: decimation register
    reg [23:0] jtag_decim;

    // Phase 2: external trigger mode register
    reg [1:0] jtag_trig_ext;

    // Phase 4: segment select register
    reg [SEG_IDX_W-1:0] jtag_seg_sel;

    // Probe mux: slice select register (jtag_clk domain)
    reg [7:0] jtag_probe_sel;

    // ---- CDC sync registers ------------------------------------------------
    reg arm_toggle_sync1, arm_toggle_sync2;
    reg reset_toggle_sync1, reset_toggle_sync2;

    // Narrowed to the bits actually used on the sample side, reducing FF count.
    reg [PTR_W-1:0]    pretrig_len_sync1,  pretrig_len_sync2;
    reg [PTR_W-1:0]    posttrig_len_sync1, posttrig_len_sync2;
    reg [1:0]          trig_mode_sync1,    trig_mode_sync2;
    reg [SAMPLE_W-1:0] trig_value_sync1,   trig_value_sync2;
    reg [SAMPLE_W-1:0] trig_mask_sync1,    trig_mask_sync2;
    reg [7:0]          chan_sel_sync1,     chan_sel_sync2;
    reg [7:0]          probe_sel_sync1,   probe_sel_sync2;
    reg                startup_arm_sync1, startup_arm_sync2;
    reg [15:0]         trig_holdoff_sync1, trig_holdoff_sync2;
    reg [15:0]         trig_delay_sync1,   trig_delay_sync2;
    reg [3:0]          sq_mode_sync1, sq_mode_sync2;
    reg [SAMPLE_W-1:0] sq_value_sync1, sq_value_sync2;
    reg [SAMPLE_W-1:0] sq_mask_sync1, sq_mask_sync2;
    reg [31:0]         seq_cfg_sync1     [0:TRIG_STAGES-1];
    reg [31:0]         seq_cfg_sync2     [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_value_a_sync1 [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_value_a_sync2 [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_mask_a_sync1  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_mask_a_sync2  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_value_b_sync1 [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_value_b_sync2 [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_mask_b_sync1  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0] seq_mask_b_sync2  [0:TRIG_STAGES-1];

    // ---- Channel mux (sample_clk domain) -----------------------------------
    reg [7:0] chan_sel;   // active channel, latched on arm
    reg [7:0] probe_sel;  // runtime probe mux slice, latched on arm

    // Mux probe_in to the active channel slice or runtime probe mux slice.
    wire [SAMPLE_W-1:0] probe_muxed;
    generate
        if (HAS_PROBE_MUX) begin : g_probe_mux
            assign probe_muxed = probe_in[probe_sel * SAMPLE_W +: SAMPLE_W];
        end else if (HAS_CHANNEL_MUX) begin : g_chan_mux
            assign probe_muxed = probe_in[chan_sel * SAMPLE_W +: SAMPLE_W];
        end else begin : g_no_probe_mux
            assign probe_muxed = probe_in[SAMPLE_W-1:0];
        end
    endgenerate

    // Optional input pipeline
    wire [SAMPLE_W-1:0] active_probe;
    generate
        if (INPUT_PIPE == 0) begin : g_nopipe
            assign active_probe = probe_muxed;
        end else begin : g_pipe
            reg [SAMPLE_W-1:0] pipe [0:INPUT_PIPE-1];
            genvar pi;
            for (pi = 0; pi < INPUT_PIPE; pi = pi + 1) begin : g_stage
                always @(posedge sample_clk or posedge sample_rst) begin
                    if (sample_rst)
                        pipe[pi] <= {SAMPLE_W{1'b0}};
                    else if (pi == 0)
                        pipe[pi] <= probe_muxed;
                    else
                        pipe[pi] <= pipe[pi-1];
                end
            end
            assign active_probe = pipe[INPUT_PIPE-1];
        end
    endgenerate

    // ---- Sample-domain state -----------------------------------------------
    reg armed, triggered, done, overflow;
    reg [PTR_W-1:0]  pretrig_len, posttrig_len;
    reg [3:0] trig_cmp_mode_a, trig_cmp_mode_b;
    reg [1:0] trig_combine;
    reg [SAMPLE_W-1:0] trig_value, trig_mask;
    reg [SAMPLE_W-1:0] trig_value_b, trig_mask_b;
    reg [PTR_W-1:0] wr_ptr, trig_ptr, start_ptr;
    reg [PTR_W-1:0] post_count;
    reg [PTR_W:0]   pre_count;
    reg [PTR_W:0]   capture_len;  // one extra bit: can equal DEPTH (= 2^PTR_W)
    reg [SAMPLE_W-1:0] probe_prev;
    // Trigger delay: when the comparator fires, count down trig_delay
    // sample-clock cycles before committing trig_ptr.  During the
    // countdown the FSM stays in the "armed, not yet triggered" branch,
    // so the circular buffer keeps recording.  trig_delay = 0 reproduces
    // the legacy zero-delay behavior exactly.
    reg [15:0] trig_delay;
    reg [15:0] trig_delay_count;
    reg        trig_delay_pending;
    reg [15:0] trig_holdoff;
    reg [15:0] trig_holdoff_count;
    reg        trig_holdoff_active;
    reg        startup_arm_pending;

    // Xilinx GSR loads flip-flop INIT values at configuration time.  Keep the
    // startup-arm path explicit so a bitstream can come up armed without first
    // relying on a user reset pulse.
    initial begin
        jtag_startup_arm   = (STARTUP_ARM != 0);
        jtag_trig_ext      = DEFAULT_TRIG_EXT_MODE;
        startup_arm_pending = (STARTUP_ARM != 0);
        armed              = 1'b0;
        triggered          = 1'b0;
        done               = 1'b0;
    end

    // Phase 1: decimation state (sample domain)
    // When DECIM_EN=0, decim_tick is tied high and all counter logic optimizes away.
    reg [23:0] decim_ratio;
    reg [23:0] decim_count;
    wire       decim_tick = !HAS_DECIM ? 1'b1 : (decim_count == 0);

    // Phase 2: external trigger sync + state
    // When EXT_TRIG_EN=0, all ext trigger state ties to constant 0
    // and optimizes away in synthesis.
    reg trig_in_sync1, trig_in_sync2;
    reg [1:0] ext_trig_mode;
    reg trigger_out_r;
    assign trigger_out = HAS_EXT_TRIG ? trigger_out_r : 1'b0;
    assign armed_out = armed;

    // Phase 4: segmented memory state
    reg [SEG_IDX_W-1:0] cur_segment;
    reg [SEG_IDX_W-1:0] seg_count;            // number of completed segments
    reg                  all_seg_done;
    reg                  segment_wrapped;
    wire                 segment_auto_rearm_now;
    // Per-segment start_ptr storage
    reg [PTR_W-1:0] seg_start_ptr [0:NUM_SEGMENTS-1];
    reg [PTR_W-1:0] seg_start_ptr_jtag_sync1 [0:NUM_SEGMENTS-1];
    reg [PTR_W-1:0] seg_start_ptr_jtag_sync2 [0:NUM_SEGMENTS-1];

    // ---- Sample buffer (dual-port RAM) -------------------------------------
    localparam TS_DATA_W = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    reg                  mem_we_a_q;
    reg  [PTR_W-1:0]     mem_wr_addr_q;
    reg  [SAMPLE_W-1:0]  mem_wr_data_q;
    reg  [TS_DATA_W-1:0] mem_wr_ts_q;
    reg  [PTR_W-1:0]     mem_addr_a;
    wire [SAMPLE_W-1:0]  mem_dout_a;
    wire [SAMPLE_W-1:0]  mem_dout_b;
    wire                 mem_we_a;
    wire                 mem_we_a_ram;
    wire [SAMPLE_W-1:0]  mem_din_a_ram;
    wire [TS_DATA_W-1:0] mem_ts_din_a_ram;
    wire [TS_DATA_W-1:0] ts_counter_cur;

    assign mem_we_a_ram   = (INPUT_PIPE >= 1) ? mem_we_a_q : mem_we_a;
    assign mem_din_a_ram  = (INPUT_PIPE >= 1) ? mem_wr_data_q : active_probe;
    assign mem_ts_din_a_ram = (INPUT_PIPE >= 1) ? mem_wr_ts_q : ts_counter_cur;

    dpram #(.WIDTH(SAMPLE_W), .DEPTH(DEPTH)) u_samplebuf (
        .clk_a  (sample_clk),
        .we_a   (mem_we_a_ram),
        .addr_a (mem_addr_a),
        .din_a  (mem_din_a_ram),
        .dout_a (mem_dout_a),
        .clk_b  (jtag_clk),
        .addr_b (burst_rd_addr),
        .dout_b (mem_dout_b)
    );

    // ---- Phase 3: Timestamp DPRAM ------------------------------------------
    generate
        if (TIMESTAMP_W > 0) begin : g_ts
            reg [TIMESTAMP_W-1:0] ts_counter;
            wire [TIMESTAMP_W-1:0] ts_dout_a;
            wire [TIMESTAMP_W-1:0] ts_dout_b;
            assign ts_counter_cur = ts_counter;

            // Free-running counter in sample_clk
            always @(posedge sample_clk or posedge sample_rst) begin
                if (sample_rst)
                    ts_counter <= {TIMESTAMP_W{1'b0}};
                else
                    ts_counter <= ts_counter + 1'b1;
            end

            dpram #(.WIDTH(TIMESTAMP_W), .DEPTH(DEPTH)) u_tsbuf (
                .clk_a  (sample_clk),
                .we_a   (mem_we_a_ram),
                .addr_a (mem_addr_a),
                .din_a  (mem_ts_din_a_ram[TIMESTAMP_W-1:0]),
                .dout_a (ts_dout_a),
                .clk_b  (jtag_clk),
                .addr_b (burst_rd_addr),
                .dout_b (ts_dout_b)
            );
            assign burst_rd_ts_data = ts_dout_b;
        end else begin : g_no_ts
            assign ts_counter_cur = {TS_DATA_W{1'b0}};
            assign burst_rd_ts_data = 1'b0;
        end
    endgenerate

    // ---- Sequencer state (sample domain) -----------------------------------
    reg [SEQ_STATE_W-1:0] seq_state;
    reg [15:0] seq_counter;
    reg [3:0]            seq_mode_a   [0:TRIG_STAGES-1];
    reg [3:0]            seq_mode_b   [0:TRIG_STAGES-1];
    reg [1:0]            seq_combine  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0]  seq_value_a  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0]  seq_mask_a   [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0]  seq_value_b  [0:TRIG_STAGES-1];
    reg [SAMPLE_W-1:0]  seq_mask_b   [0:TRIG_STAGES-1];
    reg [15:0]           seq_count_target [0:TRIG_STAGES-1];
    reg [SEQ_STATE_W-1:0] seq_next_state [0:TRIG_STAGES-1];
    reg                  seq_is_final [0:TRIG_STAGES-1];

    // ---- Storage qualification state (sample domain) -----------------------
    reg sq_enable;
    reg [3:0] sq_cmp_mode;
    reg [SAMPLE_W-1:0] sq_value, sq_mask;

    // ---- Burst read port (via dpram port B) --------------------------------
    assign burst_rd_data = mem_dout_b;

    // ---- CDC read path registers -------------------------------------------
    reg rd_req_toggle_jtag, rd_req_sync1, rd_req_sync2, rd_req_sync3;
    reg rd_ack_toggle_sample, rd_ack_sync1, rd_ack_sync2;
    reg [15:0] rd_addr_jtag, rd_addr_sync1, rd_addr_sync2, rd_addr_req;
    reg [SAMPLE_W-1:0] rd_data_sample, rd_data_sync1, rd_data_sync2;
    reg [SAMPLE_W-1:0] rd_data_jtag;
    reg [PTR_W-1:0] idx, rd_start_ptr_req;
    integer word_index, sample_index;

    // Phase 3: timestamp readback CDC registers
    reg [TS_DATA_W-1:0] ts_rd_data_sample, ts_rd_data_sync1, ts_rd_data_sync2;
    reg [TS_DATA_W-1:0] ts_rd_data_jtag;

    // ---- Trigger logic (combinational) -------------------------------------
    wire arm_pulse   = arm_toggle_sync1 ^ arm_toggle_sync2;
    wire startup_arm_pulse = startup_arm_pending;
    wire any_arm_pulse = arm_pulse | startup_arm_pulse;
    wire reset_pulse = reset_toggle_sync1 ^ reset_toggle_sync2;

    // Simple trigger: uses stage-0 comparators (backward compatible)
    wire simple_hit_a_raw, simple_hit_b_raw;
    trig_compare #(.W(SAMPLE_W), .REL_COMPARE(REL_COMPARE)) u_simple_a (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(trig_value), .mask(trig_mask),
        .mode(trig_cmp_mode_a), .hit(simple_hit_a_raw)
    );
    generate
        if (HAS_DUAL_COMPARE) begin : g_simple_b_cmp
            trig_compare #(.W(SAMPLE_W), .REL_COMPARE(REL_COMPARE)) u_simple_b (
                .probe(active_probe), .probe_prev(probe_prev),
                .value(trig_value_b), .mask(trig_mask_b),
                .mode(trig_cmp_mode_b), .hit(simple_hit_b_raw)
            );
        end else begin : g_no_simple_b_cmp
            assign simple_hit_b_raw = 1'b0;
        end
    endgenerate
    reg simple_hit_a_q, simple_hit_b_q;
    wire simple_hit_a = (COMPARE_PIPE != 0) ? simple_hit_a_q : simple_hit_a_raw;
    wire simple_hit_b = (COMPARE_PIPE != 0) ? simple_hit_b_q : simple_hit_b_raw;
    reg simple_trigger_hit;
    always @(*) begin
        if (!HAS_DUAL_COMPARE) begin
            simple_trigger_hit = simple_hit_a;
        end else begin
            case (trig_combine)
                2'd0: simple_trigger_hit = simple_hit_a;
                2'd1: simple_trigger_hit = simple_hit_b;
                2'd2: simple_trigger_hit = simple_hit_a & simple_hit_b;
                2'd3: simple_trigger_hit = simple_hit_a | simple_hit_b;
            endcase
        end
    end

    // Sequencer trigger: current stage comparators A and B
    wire seq_hit_a_raw, seq_hit_b_raw;
    trig_compare #(.W(SAMPLE_W), .REL_COMPARE(REL_COMPARE)) u_seq_a (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(seq_value_a[seq_state]), .mask(seq_mask_a[seq_state]),
        .mode(seq_mode_a[seq_state]), .hit(seq_hit_a_raw)
    );
    generate
        if (HAS_DUAL_COMPARE) begin : g_seq_b_cmp
            trig_compare #(.W(SAMPLE_W), .REL_COMPARE(REL_COMPARE)) u_seq_b (
                .probe(active_probe), .probe_prev(probe_prev),
                .value(seq_value_b[seq_state]), .mask(seq_mask_b[seq_state]),
                .mode(seq_mode_b[seq_state]), .hit(seq_hit_b_raw)
            );
        end else begin : g_no_seq_b_cmp
            assign seq_hit_b_raw = 1'b0;
        end
    endgenerate
    reg seq_hit_a_q, seq_hit_b_q;
    wire seq_hit_a = (COMPARE_PIPE != 0) ? seq_hit_a_q : seq_hit_a_raw;
    wire seq_hit_b = (COMPARE_PIPE != 0) ? seq_hit_b_q : seq_hit_b_raw;
    wire [1:0] seq_combine_cur = seq_combine[seq_state];
    reg seq_stage_hit;
    always @(*) begin
        if (!HAS_DUAL_COMPARE) begin
            seq_stage_hit = seq_hit_a;
        end else begin
            case (seq_combine_cur)
                2'd0: seq_stage_hit = seq_hit_a;
                2'd1: seq_stage_hit = seq_hit_b;
                2'd2: seq_stage_hit = seq_hit_a & seq_hit_b;
                2'd3: seq_stage_hit = seq_hit_a | seq_hit_b;
            endcase
        end
    end

    wire seq_count_reached = (seq_count_target[seq_state] == 16'h0) ||
                             ((seq_counter + 16'h1) >= seq_count_target[seq_state]);
    wire pretrigger_ready = pre_count >= {1'b0, pretrig_len};
    wire trigger_holdoff_done = !trig_holdoff_active;

    // Internal trigger signal (before ext trigger combination)
    wire internal_trigger_hit = (TRIG_STAGES == 1) ? simple_trigger_hit :
                       (seq_stage_hit && seq_is_final[seq_state] && seq_count_reached);

    wire seq_advance = (TRIG_STAGES > 1) && seq_stage_hit &&
                       !seq_is_final[seq_state] && seq_count_reached;

    // Phase 2: combine with external trigger
    reg trigger_hit;
    always @(*) begin
        case (ext_trig_mode)
            2'd0: trigger_hit = internal_trigger_hit;                          // disabled
            2'd1: trigger_hit = internal_trigger_hit | trig_in_sync2;          // OR
            2'd2: trigger_hit = internal_trigger_hit & trig_in_sync2;          // AND
            default: trigger_hit = internal_trigger_hit;
        endcase
    end

    // Storage qualification comparator (only instantiated when STOR_QUAL=1)
    wire sq_hit_raw;
    generate
        if (STOR_QUAL != 0) begin : g_sq_cmp
            trig_compare #(.W(SAMPLE_W), .REL_COMPARE(REL_COMPARE)) u_sq_cmp (
                .probe(active_probe), .probe_prev(probe_prev),
                .value(sq_value), .mask(sq_mask),
                .mode(sq_cmp_mode), .hit(sq_hit_raw)
            );
        end else begin : g_no_sq_cmp
            assign sq_hit_raw = 1'b1;  // STOR_QUAL=0: always store
        end
    endgenerate
    reg sq_hit_q;
    wire sq_hit_w = (COMPARE_PIPE != 0) ? sq_hit_q : sq_hit_raw;
    wire store_sample = (STOR_QUAL == 0) || !sq_enable || sq_hit_w;

    // Register compare hits when the input path is already pipelined.  This
    // keeps wide relational comparators off the capture-control critical path.
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            simple_hit_a_q <= 1'b0;
            simple_hit_b_q <= 1'b0;
            seq_hit_a_q    <= 1'b0;
            seq_hit_b_q    <= 1'b0;
            sq_hit_q       <= 1'b0;
        end else if (reset_pulse || any_arm_pulse || segment_auto_rearm_now) begin
            simple_hit_a_q <= 1'b0;
            simple_hit_b_q <= 1'b0;
            seq_hit_a_q    <= 1'b0;
            seq_hit_b_q    <= 1'b0;
            sq_hit_q       <= 1'b0;
        end else begin
            simple_hit_a_q <= simple_hit_a_raw;
            simple_hit_b_q <= simple_hit_b_raw;
            seq_hit_a_q    <= seq_hit_a_raw;
            seq_hit_b_q    <= seq_hit_b_raw;
            sq_hit_q       <= sq_hit_raw;
        end
    end

    // Phase 1: combined store enable (storage qualification AND decimation)
    wire store_enable = store_sample & decim_tick;

    // ---- JTAG-domain register writes ---------------------------------------
    wire jtag_rd_data_window = HAS_USER1_DATA && (
        (jtag_addr >= ADDR_DATA_BASE) ||
        (TIMESTAMP_W > 0 && jtag_addr >= ADDR_TS_DATA_BASE[15:0]));
    wire rd_addr_data_window = HAS_USER1_DATA && (
        (rd_addr_jtag >= ADDR_DATA_BASE) ||
        (TIMESTAMP_W > 0 && rd_addr_jtag >= ADDR_TS_DATA_BASE[15:0]));

    integer s;
    reg [31:0] jtag_rdata_mux;

    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            jtag_ctrl          <= 32'h0;
            jtag_pretrig_len   <= 32'h0;
            jtag_posttrig_len  <= 32'h0;
            jtag_trig_mode     <= 32'h1;
            jtag_trig_value    <= 32'h0;
            jtag_trig_mask     <= 32'hFFFF_FFFF;
            jtag_sq_mode       <= 32'h0;
            jtag_sq_value      <= 32'h0;
            jtag_sq_mask       <= 32'h0;
            jtag_chan_sel      <= 8'h0;
            jtag_decim         <= 24'h0;
            jtag_trig_ext      <= DEFAULT_TRIG_EXT_MODE;
            jtag_seg_sel       <= {SEG_IDX_W{1'b0}};
            jtag_probe_sel     <= 8'h0;
            jtag_startup_arm   <= (STARTUP_ARM != 0);
            jtag_trig_holdoff  <= 16'h0;
            jtag_trig_delay    <= 16'h0;
            arm_toggle_jtag    <= 1'b0;
            reset_toggle_jtag  <= 1'b0;
            rd_req_toggle_jtag <= 1'b0;
            rd_addr_jtag       <= 16'h0;
            burst_start        <= 1'b0;
            burst_timestamp    <= 1'b0;
            burst_start_ptr    <= {PTR_W{1'b0}};
            for (s = 0; s < NUM_SEGMENTS; s = s + 1) begin
                seg_start_ptr_jtag_sync1[s] <= {PTR_W{1'b0}};
                seg_start_ptr_jtag_sync2[s] <= {PTR_W{1'b0}};
            end
            for (s = 0; s < TRIG_STAGES; s = s + 1) begin
                jtag_seq_cfg[s]     <= (s == 0) ? 32'h0000_1000 : 32'h0;
                jtag_seq_value_a[s] <= 32'h0;
                jtag_seq_mask_a[s]  <= 32'hFFFF_FFFF;
                jtag_seq_value_b[s] <= 32'h0;
                jtag_seq_mask_b[s]  <= 32'hFFFF_FFFF;
            end
        end else begin
            for (s = 0; s < NUM_SEGMENTS; s = s + 1) begin
                seg_start_ptr_jtag_sync1[s] <= seg_start_ptr[s];
                seg_start_ptr_jtag_sync2[s] <= seg_start_ptr_jtag_sync1[s];
            end

            if (jtag_wr_en) begin
                case (jtag_addr)
                    ADDR_CTRL: begin
                        jtag_ctrl <= jtag_wdata;
                        if (jtag_wdata[0]) arm_toggle_jtag <= ~arm_toggle_jtag;
                        if (jtag_wdata[1]) reset_toggle_jtag <= ~reset_toggle_jtag;
                    end
                    ADDR_PRETRIG:    jtag_pretrig_len  <= jtag_wdata;
                    ADDR_POSTTRIG:   jtag_posttrig_len <= jtag_wdata;
                    ADDR_TRIG_MODE:  jtag_trig_mode    <= jtag_wdata;
                    ADDR_TRIG_VALUE: jtag_trig_value   <= jtag_wdata;
                    ADDR_TRIG_MASK:  jtag_trig_mask    <= jtag_wdata;
                    ADDR_SQ_MODE:    if (HAS_STOR_QUAL) jtag_sq_mode <= jtag_wdata;
                    ADDR_SQ_VALUE:   if (HAS_STOR_QUAL) jtag_sq_value <= jtag_wdata;
                    ADDR_SQ_MASK:    if (HAS_STOR_QUAL) jtag_sq_mask <= jtag_wdata;
                    ADDR_CHAN_SEL:   if (HAS_CHANNEL_MUX) jtag_chan_sel <= jtag_wdata[7:0];
                    ADDR_DECIM:      if (HAS_DECIM) jtag_decim <= jtag_wdata[23:0];
                    ADDR_TRIG_EXT:   if (HAS_EXT_TRIG) jtag_trig_ext <= jtag_wdata[1:0];
                    ADDR_PROBE_SEL:  if (HAS_PROBE_MUX) jtag_probe_sel <= jtag_wdata[7:0];
                    ADDR_STARTUP_ARM: jtag_startup_arm <= jtag_wdata[0];
                    ADDR_TRIG_HOLDOFF: jtag_trig_holdoff <= jtag_wdata[15:0];
                    ADDR_TRIG_DELAY: jtag_trig_delay   <= jtag_wdata[15:0];
                    ADDR_SEG_SEL:    if (HAS_SEGMENTS) jtag_seg_sel <= jtag_wdata[SEG_IDX_W-1:0];
                    ADDR_BURST_PTR: begin
                        // Use the JTAG-domain copy; seg_start_ptr is written
                        // in sample_clk and must not feed USER2 directly.
                        burst_start_ptr <= HAS_SEGMENTS
                            ? seg_start_ptr_jtag_sync2[jtag_seg_sel]
                            : start_ptr;
                        burst_timestamp <= jtag_wdata[31];
                        burst_start     <= ~burst_start;
                    end
                    default: begin
                        // Sequencer stage registers (5 regs x 4 bytes per stage)
                        if (HAS_SEQUENCER &&
                            jtag_addr >= ADDR_SEQ_BASE &&
                            jtag_addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE) begin
                            s = (jtag_addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                            case ((jtag_addr - ADDR_SEQ_BASE) % SEQ_STRIDE)
                                0:  jtag_seq_cfg[s]     <= HAS_DUAL_COMPARE
                                                           ? jtag_wdata
                                                           : (jtag_wdata & ~32'h0000_03F0);
                                4:  jtag_seq_value_a[s] <= jtag_wdata;
                                8:  jtag_seq_mask_a[s]  <= jtag_wdata;
                                12: if (HAS_DUAL_COMPARE) jtag_seq_value_b[s] <= jtag_wdata;
                                16: if (HAS_DUAL_COMPARE) jtag_seq_mask_b[s]  <= jtag_wdata;
                                default: ;
                            endcase
                        end
                    end
                endcase
            end

            if (jtag_rd_en) begin
                rd_addr_jtag <= jtag_addr;
                if (jtag_rd_data_window)
                    rd_req_toggle_jtag <= ~rd_req_toggle_jtag;
            end
        end
    end

    // ---- CDC: arm/reset toggles --------------------------------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            arm_toggle_sync1   <= 1'b0; arm_toggle_sync2   <= 1'b0;
            reset_toggle_sync1 <= 1'b0; reset_toggle_sync2 <= 1'b0;
            startup_arm_pending <= (STARTUP_ARM != 0);
        end else begin
            arm_toggle_sync1   <= arm_toggle_jtag;
            arm_toggle_sync2   <= arm_toggle_sync1;
            reset_toggle_sync1 <= reset_toggle_jtag;
            reset_toggle_sync2 <= reset_toggle_sync1;
            if (reset_pulse)
                startup_arm_pending <= startup_arm_sync2;
            else if (startup_arm_pulse)
                startup_arm_pending <= 1'b0;
        end
    end

    // ---- CDC: config registers ---------------------------------------------
    integer si;
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            pretrig_len_sync1  <= 0; pretrig_len_sync2  <= 0;
            posttrig_len_sync1 <= 0; posttrig_len_sync2 <= 0;
            trig_mode_sync1    <= 0; trig_mode_sync2    <= 0;
            trig_value_sync1   <= 0; trig_value_sync2   <= 0;
            trig_mask_sync1    <= 0; trig_mask_sync2    <= 0;
            chan_sel_sync1     <= 0; chan_sel_sync2     <= 0;
            probe_sel_sync1   <= 0; probe_sel_sync2   <= 0;
            startup_arm_sync1 <= (STARTUP_ARM != 0); startup_arm_sync2 <= (STARTUP_ARM != 0);
            trig_holdoff_sync1 <= 0; trig_holdoff_sync2 <= 0;
            trig_delay_sync1  <= 0; trig_delay_sync2  <= 0;
            sq_mode_sync1     <= 0; sq_mode_sync2     <= 0;
            sq_value_sync1    <= 0; sq_value_sync2    <= 0;
            sq_mask_sync1     <= 0; sq_mask_sync2     <= 0;
            for (si = 0; si < TRIG_STAGES; si = si + 1) begin
                seq_cfg_sync1[si]     <= 32'h0;
                seq_cfg_sync2[si]     <= 32'h0;
                seq_value_a_sync1[si] <= {SAMPLE_W{1'b0}};
                seq_value_a_sync2[si] <= {SAMPLE_W{1'b0}};
                seq_mask_a_sync1[si]  <= {SAMPLE_W{1'b0}};
                seq_mask_a_sync2[si]  <= {SAMPLE_W{1'b0}};
                seq_value_b_sync1[si] <= {SAMPLE_W{1'b0}};
                seq_value_b_sync2[si] <= {SAMPLE_W{1'b0}};
                seq_mask_b_sync1[si]  <= {SAMPLE_W{1'b0}};
                seq_mask_b_sync2[si]  <= {SAMPLE_W{1'b0}};
            end
        end else begin
            pretrig_len_sync1  <= jtag_pretrig_len[PTR_W-1:0];
            pretrig_len_sync2  <= pretrig_len_sync1;
            posttrig_len_sync1 <= jtag_posttrig_len[PTR_W-1:0];
            posttrig_len_sync2 <= posttrig_len_sync1;
            trig_mode_sync1    <= jtag_trig_mode[1:0];
            trig_mode_sync2    <= trig_mode_sync1;
            trig_value_sync1   <= jtag_trig_value_w;
            trig_value_sync2   <= trig_value_sync1;
            trig_mask_sync1    <= jtag_trig_mask_w;
            trig_mask_sync2    <= trig_mask_sync1;
            chan_sel_sync1     <= HAS_CHANNEL_MUX ? jtag_chan_sel : 8'h0;
            chan_sel_sync2     <= HAS_CHANNEL_MUX ? chan_sel_sync1 : 8'h0;
            probe_sel_sync1   <= HAS_PROBE_MUX ? jtag_probe_sel : 8'h0;
            probe_sel_sync2   <= HAS_PROBE_MUX ? probe_sel_sync1 : 8'h0;
            startup_arm_sync1 <= jtag_startup_arm;
            startup_arm_sync2 <= startup_arm_sync1;
            trig_holdoff_sync1 <= jtag_trig_holdoff;
            trig_holdoff_sync2 <= trig_holdoff_sync1;
            trig_delay_sync1  <= jtag_trig_delay;
            trig_delay_sync2  <= trig_delay_sync1;
            sq_mode_sync1     <= HAS_STOR_QUAL ? jtag_sq_mode[3:0] : 4'h0;
            sq_mode_sync2     <= HAS_STOR_QUAL ? sq_mode_sync1 : 4'h0;
            sq_value_sync1    <= HAS_STOR_QUAL ? jtag_sq_value_w : {SAMPLE_W{1'b0}};
            sq_value_sync2    <= HAS_STOR_QUAL ? sq_value_sync1 : {SAMPLE_W{1'b0}};
            sq_mask_sync1     <= HAS_STOR_QUAL ? jtag_sq_mask_w : {SAMPLE_W{1'b0}};
            sq_mask_sync2     <= HAS_STOR_QUAL ? sq_mask_sync1 : {SAMPLE_W{1'b0}};
            for (si = 0; si < TRIG_STAGES; si = si + 1) begin
                if (HAS_SEQUENCER) begin
                    seq_cfg_sync1[si]     <= jtag_seq_cfg[si];
                    seq_cfg_sync2[si]     <= seq_cfg_sync1[si];
                    seq_value_a_sync1[si] <= jtag_seq_value_a_w[si];
                    seq_value_a_sync2[si] <= seq_value_a_sync1[si];
                    seq_mask_a_sync1[si]  <= jtag_seq_mask_a_w[si];
                    seq_mask_a_sync2[si]  <= seq_mask_a_sync1[si];
                end else begin
                    seq_cfg_sync1[si]     <= 32'h0;
                    seq_cfg_sync2[si]     <= 32'h0;
                    seq_value_a_sync1[si] <= {SAMPLE_W{1'b0}};
                    seq_value_a_sync2[si] <= {SAMPLE_W{1'b0}};
                    seq_mask_a_sync1[si]  <= {SAMPLE_W{1'b1}};
                    seq_mask_a_sync2[si]  <= {SAMPLE_W{1'b1}};
                end
                if (HAS_SEQUENCER && HAS_DUAL_COMPARE) begin
                    seq_value_b_sync1[si] <= jtag_seq_value_b_w[si];
                    seq_value_b_sync2[si] <= seq_value_b_sync1[si];
                    seq_mask_b_sync1[si]  <= jtag_seq_mask_b_w[si];
                    seq_mask_b_sync2[si]  <= seq_mask_b_sync1[si];
                end else begin
                    seq_value_b_sync1[si] <= {SAMPLE_W{1'b0}};
                    seq_value_b_sync2[si] <= {SAMPLE_W{1'b0}};
                    seq_mask_b_sync1[si]  <= {SAMPLE_W{1'b1}};
                    seq_mask_b_sync2[si]  <= {SAMPLE_W{1'b1}};
                end
            end
        end
    end

    // Phase 2: external trigger_in synchronizer
    generate
        if (HAS_EXT_TRIG) begin : g_ext_trig_sync
            always @(posedge sample_clk or posedge sample_rst) begin
                if (sample_rst) begin
                    trig_in_sync1 <= 1'b0;
                    trig_in_sync2 <= 1'b0;
                end else begin
                    trig_in_sync1 <= trigger_in;
                    trig_in_sync2 <= trig_in_sync1;
                end
            end
        end else begin : g_no_ext_trig_sync
            always @(posedge sample_clk) begin
                trig_in_sync1 = 1'b0;
                trig_in_sync2 = 1'b0;
            end
        end
    endgenerate

    // ---- Latch config on arm -----------------------------------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            pretrig_len      <= 0;
            posttrig_len     <= 0;
            trig_cmp_mode_a  <= 4'd0;  // EQ
            trig_cmp_mode_b  <= 4'd0;
            trig_combine     <= 2'd0;  // A only
            trig_value       <= {SAMPLE_W{1'b0}};
            trig_mask        <= {SAMPLE_W{1'b1}};
            trig_value_b     <= {SAMPLE_W{1'b0}};
            trig_mask_b      <= {SAMPLE_W{1'b1}};
            sq_enable        <= 1'b0;
            sq_cmp_mode      <= 4'd0;
            sq_value         <= {SAMPLE_W{1'b0}};
            sq_mask          <= {SAMPLE_W{1'b0}};
            chan_sel         <= 8'h0;
            probe_sel        <= 8'h0;
            decim_ratio      <= 24'h0;
            ext_trig_mode    <= DEFAULT_TRIG_EXT_MODE;
            trig_delay       <= 16'h0;
            for (si = 0; si < TRIG_STAGES; si = si + 1) begin
                seq_mode_a[si]       <= 4'd0;
                seq_mode_b[si]       <= 4'd0;
                seq_combine[si]      <= 2'd0;
                seq_value_a[si]      <= {SAMPLE_W{1'b0}};
                seq_mask_a[si]       <= {SAMPLE_W{1'b1}};
                seq_value_b[si]      <= {SAMPLE_W{1'b0}};
                seq_mask_b[si]       <= {SAMPLE_W{1'b1}};
                seq_count_target[si] <= 16'h0;
                seq_next_state[si]   <= {SEQ_STATE_W{1'b0}};
                seq_is_final[si]     <= 1'b0;
            end
        end else if (any_arm_pulse) begin
            pretrig_len      <= pretrig_len_sync2;
            posttrig_len     <= posttrig_len_sync2;
            trig_value       <= trig_value_sync2;
            trig_mask        <= trig_mask_sync2;
            // Stage-0 compare modes
            if (HAS_SEQUENCER && seq_cfg_sync2[0][9:0] != 10'd0) begin
                trig_cmp_mode_a <= seq_cfg_sync2[0][3:0];
                trig_cmp_mode_b <= HAS_DUAL_COMPARE ? seq_cfg_sync2[0][7:4] : 4'd0;
                trig_combine    <= HAS_DUAL_COMPARE ? seq_cfg_sync2[0][9:8] : 2'd0;
            end else begin
                trig_cmp_mode_a <= trig_mode_sync2[1] ? 4'd8 : 4'd0;
                trig_cmp_mode_b <= (HAS_DUAL_COMPARE && trig_mode_sync2 == 2'b11) ? 4'd8 : 4'd0;
                trig_combine    <= (HAS_DUAL_COMPARE && trig_mode_sync2 == 2'b11) ? 2'd3 : 2'd0;
            end
            trig_value_b     <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                 ? seq_value_b_sync2[0] : {SAMPLE_W{1'b0}};
            trig_mask_b      <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                 ? seq_mask_b_sync2[0] : {SAMPLE_W{1'b1}};
            // Channel select (clamped to valid range)
            chan_sel         <= (HAS_CHANNEL_MUX && chan_sel_sync2 < NUM_CHANNELS)
                                ? chan_sel_sync2 : 8'h0;
            // Probe mux select (clamped when enabled)
            if (HAS_PROBE_MUX)
                probe_sel   <= (probe_sel_sync2 < PROBE_MUX_SLICES) ? probe_sel_sync2 : 8'h0;
            else
                probe_sel   <= 8'h0;
            // Storage qualification
            sq_enable        <= HAS_STOR_QUAL && (sq_mode_sync2 != 0);
            sq_cmp_mode      <= HAS_STOR_QUAL ? sq_mode_sync2 : 4'h0;
            sq_value         <= HAS_STOR_QUAL ? sq_value_sync2 : {SAMPLE_W{1'b0}};
            sq_mask          <= HAS_STOR_QUAL ? sq_mask_sync2 : {SAMPLE_W{1'b0}};
            // Phase 1: decimation
            decim_ratio      <= HAS_DECIM ? jtag_decim : 24'h0;
            // Phase 2: external trigger
            ext_trig_mode    <= HAS_EXT_TRIG ? jtag_trig_ext : 2'd0;
            trig_holdoff     <= trig_holdoff_sync2;
            // Trigger delay (sample clocks) — latched on arm
            trig_delay       <= trig_delay_sync2;
            // Sequencer stages
            for (si = 0; si < TRIG_STAGES; si = si + 1) begin
                seq_mode_a[si]       <= HAS_SEQUENCER ? seq_cfg_sync2[si][3:0] : 4'd0;
                seq_mode_b[si]       <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                         ? seq_cfg_sync2[si][7:4] : 4'd0;
                seq_combine[si]      <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                         ? seq_cfg_sync2[si][9:8] : 2'd0;
                seq_next_state[si]   <= HAS_SEQUENCER
                                         ? seq_cfg_sync2[si][10 +: SEQ_STATE_W]
                                         : {SEQ_STATE_W{1'b0}};
                seq_is_final[si]     <= HAS_SEQUENCER ? seq_cfg_sync2[si][12] : 1'b0;
                seq_count_target[si] <= HAS_SEQUENCER ? seq_cfg_sync2[si][31:16] : 16'h0;
                seq_value_a[si]      <= HAS_SEQUENCER ? seq_value_a_sync2[si] : {SAMPLE_W{1'b0}};
                seq_mask_a[si]       <= HAS_SEQUENCER ? seq_mask_a_sync2[si] : {SAMPLE_W{1'b1}};
                seq_value_b[si]      <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                         ? seq_value_b_sync2[si] : {SAMPLE_W{1'b0}};
                seq_mask_b[si]       <= (HAS_SEQUENCER && HAS_DUAL_COMPARE)
                                         ? seq_mask_b_sync2[si] : {SAMPLE_W{1'b1}};
            end
        end
    end

    // ---- Previous sample register ------------------------------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) probe_prev <= {SAMPLE_W{1'b0}};
        else            probe_prev <= active_probe;
    end

    // ---- Phase 1: Decimation counter (sample_clk domain) -------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            decim_count <= 24'h0;
        end else begin
            if (!HAS_DECIM) begin
                decim_count <= 24'h0;
            end else if (any_arm_pulse) begin
                decim_count <= 24'h0;
            end else if (armed && !done) begin
                if (decim_count >= decim_ratio)
                    decim_count <= 24'h0;
                else
                    decim_count <= decim_count + 1'b1;
            end
        end
    end

    // ---- Capture state machine ---------------------------------------------
    reg mem_rd_pending;
    wire [PTR_W-1:0] post_store_limit = posttrig_len;
    assign segment_auto_rearm_now = HAS_SEGMENTS && armed && !done && triggered &&
        (cur_segment != NUM_SEGMENTS - 1) &&
        ((post_count >= post_store_limit) ||
         (store_enable && (post_count + 1'b1 >= post_store_limit)));
    wire trigger_commit_now = armed && !done && !triggered && pretrigger_ready &&
        trigger_holdoff_done &&
        ((trig_delay_pending && (trig_delay_count == 16'h0)) ||
         (!trig_delay_pending && trigger_hit && (trig_delay == 16'h0)));
    wire post_store_now = armed && !done && triggered && store_enable &&
                          (post_count < post_store_limit);
    wire pre_store_now = armed && !done && !triggered &&
                         (store_enable || trigger_commit_now);
    assign mem_we_a = pre_store_now || post_store_now;
    always @(*) begin
        if ((INPUT_PIPE >= 1) && mem_we_a_q)
            mem_addr_a = mem_wr_addr_q;
        else if (HAS_USER1_DATA && mem_rd_pending)
            mem_addr_a = idx;
        else
            mem_addr_a = wr_ptr;
    end

    // Register the RAM write command so address, data, and enable stay
    // aligned and the trigger/WEA path does not have to reach the BRAM in
    // the same cycle as trigger evaluation.
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            mem_we_a_q     <= 1'b0;
            mem_wr_addr_q  <= {PTR_W{1'b0}};
            mem_wr_data_q  <= {SAMPLE_W{1'b0}};
            mem_wr_ts_q    <= {TS_DATA_W{1'b0}};
        end else begin
            mem_we_a_q <= mem_we_a;
            if (mem_we_a) begin
                mem_wr_addr_q <= wr_ptr;
                mem_wr_data_q <= active_probe;
                mem_wr_ts_q   <= ts_counter_cur;
            end
        end
    end

    // Phase 2: trigger_out pulse
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst)
            trigger_out_r <= 1'b0;
        else
            trigger_out_r <= (armed && !triggered && pretrigger_ready &&
                              trigger_holdoff_done && trigger_hit) ? 1'b1 : 1'b0;
    end

    // Phase 4: segment base address
    wire [PTR_W-1:0] seg_base =
        HAS_SEGMENTS ? (cur_segment * SEG_DEPTH[PTR_W-1:0]) : {PTR_W{1'b0}};
    wire [PTR_W-1:0] wr_seg_off = wr_ptr - seg_base;
    wire [PTR_W-1:0] trig_seg_off = trig_ptr - seg_base;
    wire [PTR_W-1:0] capture_start_ptr =
        (HAS_SEGMENTS && !segment_wrapped && trig_seg_off < pretrig_len)
            ? seg_base
            : seg_base + ((trig_ptr - seg_base + SEG_DEPTH - pretrig_len) & (SEG_DEPTH - 1));

    integer seg_i;
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            armed       <= 1'b0;
            triggered   <= 1'b0;
            done        <= 1'b0;
            overflow    <= 1'b0;
            wr_ptr      <= {PTR_W{1'b0}};
            trig_ptr    <= {PTR_W{1'b0}};
            start_ptr   <= {PTR_W{1'b0}};
            post_count  <= {PTR_W{1'b0}};
            pre_count   <= {PTR_W+1{1'b0}};
            capture_len <= {PTR_W+1{1'b0}};
            seq_state   <= {SEQ_STATE_W{1'b0}};
            seq_counter <= 16'h0;
            trig_holdoff       <= 16'h0;
            trig_holdoff_active <= 1'b0;
            trig_holdoff_count  <= 16'h0;
            trig_delay_pending <= 1'b0;
            trig_delay_count   <= 16'h0;
            cur_segment <= {SEG_IDX_W{1'b0}};
            seg_count   <= {SEG_IDX_W{1'b0}};
            all_seg_done <= 1'b0;
            segment_wrapped <= 1'b0;
            for (seg_i = 0; seg_i < NUM_SEGMENTS; seg_i = seg_i + 1)
                seg_start_ptr[seg_i] <= {PTR_W{1'b0}};
        end else begin
            if (reset_pulse) begin
                armed       <= 1'b0;
                triggered   <= 1'b0;
                done        <= 1'b0;
                overflow    <= 1'b0;
                wr_ptr      <= {PTR_W{1'b0}};
                post_count  <= {PTR_W{1'b0}};
                pre_count   <= {PTR_W+1{1'b0}};
                capture_len <= {PTR_W+1{1'b0}};
                trig_holdoff_active <= 1'b0;
                trig_holdoff_count  <= 16'h0;
                trig_delay_pending <= 1'b0;
                trig_delay_count   <= 16'h0;
                cur_segment <= {SEG_IDX_W{1'b0}};
                seg_count   <= {SEG_IDX_W{1'b0}};
                all_seg_done <= 1'b0;
                segment_wrapped <= 1'b0;
                for (seg_i = 0; seg_i < NUM_SEGMENTS; seg_i = seg_i + 1)
                    seg_start_ptr[seg_i] <= {PTR_W{1'b0}};
            end

            if (any_arm_pulse) begin
                armed       <= 1'b1;
                triggered   <= 1'b0;
                done        <= 1'b0;
                wr_ptr      <= {PTR_W{1'b0}};
                post_count  <= {PTR_W{1'b0}};
                pre_count   <= {PTR_W+1{1'b0}};
                seq_state   <= {SEQ_STATE_W{1'b0}};
                seq_counter <= 16'h0;
                trig_holdoff_active <= (trig_holdoff_sync2 != 16'h0);
                trig_holdoff_count  <= (trig_holdoff_sync2 != 16'h0)
                    ? (trig_holdoff_sync2 - 16'h1) : 16'h0;
                trig_delay_pending <= 1'b0;
                trig_delay_count   <= 16'h0;
                cur_segment <= {SEG_IDX_W{1'b0}};
                seg_count   <= {SEG_IDX_W{1'b0}};
                all_seg_done <= 1'b0;
                segment_wrapped <= 1'b0;
                // Overflow check: use SEG_DEPTH for segmented mode
                if (NUM_SEGMENTS > 1)
                    overflow <= (pretrig_len_sync2 + posttrig_len_sync2 + 1 > SEG_DEPTH);
                else
                    overflow <= (pretrig_len_sync2 + posttrig_len_sync2 + 1 > DEPTH);
            end

            if (armed && !done) begin
                if (trig_holdoff_active) begin
                    if (trig_holdoff_count == 16'h0)
                        trig_holdoff_active <= 1'b0;
                    else
                        trig_holdoff_count <= trig_holdoff_count - 16'h1;
                end
                // Store sample (qualified + decimated).  A trigger commit
                // force-stores the anchor sample so samples[pretrig] remains
                // the committed trigger sample even when decimation or storage
                // qualification would otherwise skip that cycle.
                if (mem_we_a) begin
                    wr_ptr <= wr_ptr + 1'b1;
                    // Phase 4: segment-aware wrap
                    if (NUM_SEGMENTS > 1) begin
                        if (wr_seg_off + 1'b1 >= SEG_DEPTH[PTR_W-1:0]) begin
                            wr_ptr <= seg_base;
                            segment_wrapped <= 1'b1;
                        end else begin
                            wr_ptr <= wr_ptr + 1'b1;
                        end
                    end
                end
                if (!triggered && !trigger_commit_now && store_enable && !pretrigger_ready)
                    pre_count <= pre_count + 1'b1;

                // Trigger / sequencer evaluation (runs every cycle, NOT gated by decimation)
                if (!triggered) begin
                    if (trig_holdoff_active) begin
                        // Ignore trigger / sequencer activity until the
                        // post-arm holdoff window expires.
                    end else if (trig_delay_pending) begin
                        // Counting down sample-clock cycles between the
                        // trigger event and the committed trigger sample.
                        // Buffer continues to record (gated by store_enable
                        // above).  At terminal count, commit trig_ptr from
                        // the *current* wr_ptr — this is now `trig_delay`
                        // store events later than the original cause.
                        if (trig_delay_count == 16'h0) begin
                            triggered          <= 1'b1;
                            trig_ptr           <= wr_ptr;
                            post_count         <= {PTR_W{1'b0}};
                            capture_len        <= pretrig_len + posttrig_len + 1'b1;
                            trig_delay_pending <= 1'b0;
                        end else begin
                            trig_delay_count <= trig_delay_count - 1'b1;
                        end
                    end else if (pretrigger_ready && trigger_hit) begin
                        if (trig_delay == 16'h0) begin
                            // Zero delay: legacy behavior, commit immediately.
                            triggered   <= 1'b1;
                            trig_ptr    <= wr_ptr;
                            post_count  <= {PTR_W{1'b0}};
                            capture_len <= pretrig_len + posttrig_len + 1'b1;
                        end else begin
                            // Enter delay countdown.  trig_delay_count is
                            // the number of *additional* cycles after this
                            // one before commit, so subtract 1.
                            trig_delay_pending <= 1'b1;
                            trig_delay_count   <= trig_delay - 16'h1;
                        end
                    end else if (pretrigger_ready && seq_advance) begin
                        seq_state   <= seq_next_state[seq_state];
                        seq_counter <= 16'h0;
                    end else if (pretrigger_ready && TRIG_STAGES > 1 && seq_stage_hit) begin
                        seq_counter <= seq_counter + 1'b1;
                    end
                end else begin
                    // Post-trigger countdown (counts stored samples only)
                    if (post_count >= post_store_limit) begin
                        // Segment complete
                        if (NUM_SEGMENTS > 1) begin
                            // Ring start within this segment. Before the
                            // segment has wrapped, don't point pretrigger
                            // history into unwritten tail addresses.
                            seg_start_ptr[cur_segment] <= capture_start_ptr;
                            if (cur_segment == NUM_SEGMENTS - 1) begin
                                // All segments done
                                done      <= 1'b1;
                                armed     <= 1'b0;
                                start_ptr <= seg_start_ptr[0];
                                all_seg_done <= 1'b1;
                                seg_count    <= seg_count + 1'b1;
                            end else begin
                                // Auto-rearm for next segment
                                cur_segment <= cur_segment + 1'b1;
                                seg_count   <= seg_count + 1'b1;
                                triggered   <= 1'b0;
                                post_count  <= {PTR_W{1'b0}};
                                pre_count   <= {PTR_W+1{1'b0}};
                                seq_state   <= {SEQ_STATE_W{1'b0}};
                                seq_counter <= 16'h0;
                                trig_holdoff_active <= (trig_holdoff != 16'h0);
                                trig_holdoff_count  <= (trig_holdoff != 16'h0)
                                    ? (trig_holdoff - 16'h1) : 16'h0;
                                trig_delay_pending <= 1'b0;
                                trig_delay_count   <= 16'h0;
                                // Set wr_ptr to next segment base
                                wr_ptr      <= (cur_segment + 1) * SEG_DEPTH[PTR_W-1:0];
                                segment_wrapped <= 1'b0;
                            end
                        end else begin
                            done      <= 1'b1;
                            armed     <= 1'b0;
                            start_ptr <= capture_start_ptr;
                        end
                    end else if (store_enable) begin
                        if (post_count + 1'b1 >= post_store_limit) begin
                            // Segment complete
                            if (NUM_SEGMENTS > 1) begin
                                // Ring start within this segment. Before the
                                // segment has wrapped, don't point pretrigger
                                // history into unwritten tail addresses.
                                seg_start_ptr[cur_segment] <= capture_start_ptr;
                                if (cur_segment == NUM_SEGMENTS - 1) begin
                                    // All segments done
                                    done      <= 1'b1;
                                    armed     <= 1'b0;
                                    start_ptr <= seg_start_ptr[0];
                                    all_seg_done <= 1'b1;
                                    seg_count    <= seg_count + 1'b1;
                                end else begin
                                    // Auto-rearm for next segment
                                    cur_segment <= cur_segment + 1'b1;
                                    seg_count   <= seg_count + 1'b1;
                                    triggered   <= 1'b0;
                                    post_count  <= {PTR_W{1'b0}};
                                    pre_count   <= {PTR_W+1{1'b0}};
                                    seq_state   <= {SEQ_STATE_W{1'b0}};
                                    seq_counter <= 16'h0;
                                    trig_holdoff_active <= (trig_holdoff != 16'h0);
                                    trig_holdoff_count  <= (trig_holdoff != 16'h0)
                                        ? (trig_holdoff - 16'h1) : 16'h0;
                                    trig_delay_pending <= 1'b0;
                                    trig_delay_count   <= 16'h0;
                                    // Set wr_ptr to next segment base
                                    wr_ptr      <= (cur_segment + 1) * SEG_DEPTH[PTR_W-1:0];
                                    segment_wrapped <= 1'b0;
                                end
                            end else begin
                                done      <= 1'b1;
                                armed     <= 1'b0;
                                start_ptr <= capture_start_ptr;
                            end
                        end else begin
                            post_count <= post_count + 1'b1;
                        end
                    end
                end
            end
        end
    end

    // ---- CDC: segment select sync (jtag -> sample_clk) ----------------------
    reg [SEG_IDX_W-1:0] seg_sel_sync1, seg_sel_sync2;
    // Registered lookup of seg_start_ptr to avoid combinational CDC path
    reg [PTR_W-1:0] seg_start_ptr_rd;
    wire [PTR_W-1:0] seg_rd_base_req;
    generate
        if (NUM_SEGMENTS > 1) begin : g_seg_rd_base
            assign seg_rd_base_req = {rd_start_ptr_req[PTR_W-1:SEG_PTR_W], {SEG_PTR_W{1'b0}}};
        end else begin : g_no_seg_rd_base
            assign seg_rd_base_req = {PTR_W{1'b0}};
        end
    endgenerate

    // ---- CDC: data readback (via dpram port A read) -------------------------
    localparam [2:0] RD_IDLE      = 3'd0;
    localparam [2:0] RD_DECODE    = 3'd1;
    localparam [2:0] RD_WAIT_ADDR = 3'd2;
    localparam [2:0] RD_WAIT_DATA = 3'd3;
    localparam [2:0] RD_CAPTURE   = 3'd4;
    localparam [2:0] RD_ACK       = 3'd5;
    reg [2:0] rd_phase;
    // Track whether current read targets timestamp vs sample memory
    reg rd_is_ts;
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            rd_req_sync1         <= 1'b0;
            rd_req_sync2         <= 1'b0;
            rd_req_sync3         <= 1'b0;
            rd_addr_sync1        <= 16'h0;
            rd_addr_sync2        <= 16'h0;
            rd_addr_req          <= 16'h0;
            seg_sel_sync1        <= {SEG_IDX_W{1'b0}};
            seg_sel_sync2        <= {SEG_IDX_W{1'b0}};
            seg_start_ptr_rd     <= {PTR_W{1'b0}};
            rd_data_sample       <= {SAMPLE_W{1'b0}};
            ts_rd_data_sample    <= 32'h0;
            rd_ack_toggle_sample <= 1'b0;
            mem_rd_pending       <= 1'b0;
            rd_phase             <= RD_IDLE;
            idx                  <= {PTR_W{1'b0}};
            rd_start_ptr_req     <= {PTR_W{1'b0}};
            rd_is_ts             <= 1'b0;
        end else begin
            rd_req_sync1  <= rd_req_toggle_jtag;
            rd_req_sync2  <= rd_req_sync1;
            rd_req_sync3  <= rd_req_sync2;
            rd_addr_sync1 <= rd_addr_jtag;
            rd_addr_sync2 <= rd_addr_sync1;
            seg_sel_sync1 <= jtag_seg_sel;
            seg_sel_sync2 <= seg_sel_sync1;
            seg_start_ptr_rd <= seg_start_ptr[seg_sel_sync2];

            if (rd_phase == RD_CAPTURE) begin
                rd_data_sample <= mem_dout_a;
                if (TIMESTAMP_W > 0 && rd_is_ts)
                    ts_rd_data_sample <= g_ts.ts_dout_a;
                mem_rd_pending <= 1'b0;
                rd_phase <= RD_ACK;
            end else if (rd_phase == RD_ACK) begin
                rd_ack_toggle_sample <= ~rd_ack_toggle_sample;
                rd_phase <= RD_IDLE;
                rd_is_ts <= 1'b0;
            end else if (rd_phase == RD_WAIT_DATA) begin
                rd_phase <= RD_CAPTURE;
            end else if (rd_phase == RD_WAIT_ADDR) begin
                rd_phase <= RD_WAIT_DATA;
            end else if (rd_phase == RD_DECODE) begin
                // Decode from payload latched on request edge, not from live sync buses.
                if (TIMESTAMP_W > 0 && rd_addr_req >= ADDR_TS_DATA_BASE[15:0]) begin
                    word_index   = (rd_addr_req - ADDR_TS_DATA_BASE[15:0]) >> 2;
                    sample_index = word_index / TS_WORDS;
                    if (sample_index < capture_len) begin
                        idx <= seg_rd_base_req
                            + ((rd_start_ptr_req - seg_rd_base_req + sample_index) & (SEG_DEPTH - 1));
                        mem_rd_pending <= 1'b1;
                        rd_phase <= RD_WAIT_ADDR;
                        rd_is_ts <= 1'b1;
                    end else begin
                        ts_rd_data_sample <= 32'h0;
                        rd_phase <= RD_ACK;
                    end
                end else if (rd_addr_req >= ADDR_DATA_BASE) begin
                    word_index   = (rd_addr_req - ADDR_DATA_BASE) >> 2;
                    sample_index = word_index / WORDS_PER_SAMPLE;
                    if (sample_index < capture_len) begin
                        idx <= seg_rd_base_req
                            + ((rd_start_ptr_req - seg_rd_base_req + sample_index) & (SEG_DEPTH - 1));
                        mem_rd_pending <= 1'b1;
                        rd_phase <= RD_WAIT_ADDR;
                        rd_is_ts <= 1'b0;
                    end else begin
                        rd_data_sample <= {SAMPLE_W{1'b0}};
                        rd_phase <= RD_ACK;
                    end
                end else begin
                    rd_data_sample <= {SAMPLE_W{1'b0}};
                    rd_phase <= RD_ACK;
                end
            end else if (rd_req_sync2 ^ rd_req_sync3) begin
                // Request edge delayed to sync2^sync3 so rd_addr_sync2 is fully settled.
                rd_addr_req      <= rd_addr_sync2;
                rd_start_ptr_req <= (NUM_SEGMENTS > 1) ? seg_start_ptr_rd : start_ptr;
                rd_phase         <= RD_DECODE;
            end
        end
    end

    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            rd_ack_sync1  <= 1'b0;
            rd_ack_sync2  <= 1'b0;
            rd_data_sync1 <= {SAMPLE_W{1'b0}};
            rd_data_sync2 <= {SAMPLE_W{1'b0}};
            rd_data_jtag  <= {SAMPLE_W{1'b0}};
            ts_rd_data_sync1 <= 32'h0;
            ts_rd_data_sync2 <= 32'h0;
            ts_rd_data_jtag  <= 32'h0;
            jtag_rdata       <= 32'h0;
        end else begin
            rd_ack_sync1  <= rd_ack_toggle_sample;
            rd_ack_sync2  <= rd_ack_sync1;
            rd_data_sync1 <= rd_data_sample;
            rd_data_sync2 <= rd_data_sync1;
            ts_rd_data_sync1 <= ts_rd_data_sample;
            ts_rd_data_sync2 <= ts_rd_data_sync1;
            if (jtag_rd_en && !jtag_rd_data_window)
                jtag_rdata <= jtag_rdata_mux;
            if (rd_ack_sync1 ^ rd_ack_sync2) begin
                rd_data_jtag <= rd_data_sync1;
                ts_rd_data_jtag <= ts_rd_data_sync1;
                if (rd_addr_data_window) begin
                    if (TIMESTAMP_W > 0 && rd_addr_jtag >= ADDR_TS_DATA_BASE[15:0]) begin
                        jtag_rdata <= ts_rd_data_sync1 >> (
                            ((rd_addr_jtag - ADDR_TS_DATA_BASE[15:0]) >> 2) % TS_WORDS
                        ) * 32;
                    end else if (WORDS_PER_SAMPLE == 1) begin
                        jtag_rdata <= {{(32-SAMPLE_W){1'b0}}, rd_data_sync1};
                    end else begin
                        jtag_rdata <= sample_chunk_word(
                            rd_data_sync1,
                            ((rd_addr_jtag - ADDR_DATA_BASE) >> 2) % WORDS_PER_SAMPLE
                        );
                    end
                end
            end
        end
    end

    // ---- Register read mux -------------------------------------------------
    integer seq_rd_stage, seq_rd_off;

    wire [SEG_IDX_W-1:0] jtag_seg_sel_clamped =
        (HAS_SEGMENTS && jtag_seg_sel < NUM_SEGMENTS) ? jtag_seg_sel : {SEG_IDX_W{1'b0}};
    wire [PTR_W-1:0] jtag_seg_start_ptr = seg_start_ptr_jtag_sync2[jtag_seg_sel_clamped];

    wire seq_addr_hit = HAS_SEQUENCER && (jtag_addr >= ADDR_SEQ_BASE) &&
                        (jtag_addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE);
    wire [15:0] seq_addr_delta = jtag_addr - ADDR_SEQ_BASE;
    wire [31:0] seq_rd_stage_w = seq_addr_hit ? (seq_addr_delta / SEQ_STRIDE) : 32'h0;
    wire [31:0] seq_rd_off_w   = seq_addr_hit ? (seq_addr_delta % SEQ_STRIDE) : 32'h0;
    wire [31:0] seq_cfg_r      = jtag_seq_cfg[seq_rd_stage_w];
    wire [31:0] seq_value_a_r  = jtag_seq_value_a[seq_rd_stage_w];
    wire [31:0] seq_mask_a_r   = jtag_seq_mask_a[seq_rd_stage_w];
    wire [31:0] seq_value_b_r  = jtag_seq_value_b[seq_rd_stage_w];
    wire [31:0] seq_mask_b_r   = jtag_seq_mask_b[seq_rd_stage_w];

    function [31:0] sample_chunk_word;
        input [SAMPLE_W-1:0] sample;
        input integer chunk;
        integer bit_i;
        integer bit_base;
        begin
            sample_chunk_word = 32'h0;
            bit_base = chunk * 32;
            for (bit_i = 0; bit_i < 32; bit_i = bit_i + 1) begin
                if (bit_base + bit_i < SAMPLE_W)
                    sample_chunk_word[bit_i] = sample[bit_base + bit_i];
            end
        end
    endfunction

    always @(*) begin
        jtag_rdata_mux = 32'h0;
        case (jtag_addr)
            // VERSION layout (defined in rtl/fcapz_version.vh, generated
            // from the repo-root VERSION file by tools/sync_version.py):
            //   [31:24] = `FCAPZ_VERSION_MAJOR (8-bit)
            //   [23:16] = `FCAPZ_VERSION_MINOR (8-bit)
            //   [15:0]  = `FCAPZ_ELA_CORE_ID  = ASCII "LA" = 0x4C41
            // Hosts must verify VERSION[15:0] equals the LA magic before
            // trusting any other ELA register on this chain.
            ADDR_VERSION:     jtag_rdata_mux = `FCAPZ_ELA_VERSION_REG;
            ADDR_CTRL:        jtag_rdata_mux = jtag_ctrl;
            ADDR_STATUS:      jtag_rdata_mux = {28'h0, overflow, done, triggered, armed};
            ADDR_SAMPLE_W:    jtag_rdata_mux = SAMPLE_W;
            ADDR_DEPTH:       jtag_rdata_mux = DEPTH;
            ADDR_PRETRIG:     jtag_rdata_mux = jtag_pretrig_len;
            ADDR_POSTTRIG:    jtag_rdata_mux = jtag_posttrig_len;
            ADDR_CAPTURE_LEN: jtag_rdata_mux = capture_len;
            ADDR_TRIG_MODE:   jtag_rdata_mux = jtag_trig_mode;
            ADDR_TRIG_VALUE:  jtag_rdata_mux = jtag_trig_value;
            ADDR_TRIG_MASK:   jtag_rdata_mux = jtag_trig_mask;
            ADDR_SQ_MODE:     jtag_rdata_mux = HAS_STOR_QUAL ? jtag_sq_mode : 32'h0;
            ADDR_SQ_VALUE:    jtag_rdata_mux = HAS_STOR_QUAL ? jtag_sq_value : 32'h0;
            ADDR_SQ_MASK:     jtag_rdata_mux = HAS_STOR_QUAL ? jtag_sq_mask : 32'h0;
            ADDR_FEATURES:    jtag_rdata_mux = FEATURES;
            ADDR_CHAN_SEL:    jtag_rdata_mux = HAS_CHANNEL_MUX ? {24'h0, jtag_chan_sel} : 32'h0;
            ADDR_NUM_CHAN:    jtag_rdata_mux = NUM_CHANNELS;
            ADDR_DECIM:       jtag_rdata_mux = HAS_DECIM ? {8'h0, jtag_decim} : 32'h0;
            ADDR_TRIG_EXT:    jtag_rdata_mux = HAS_EXT_TRIG ? {30'h0, jtag_trig_ext} : 32'h0;
            ADDR_NUM_SEGMENTS: jtag_rdata_mux = NUM_SEGMENTS;
            ADDR_SEG_STATUS:  jtag_rdata_mux = HAS_SEGMENTS
                                               ? {all_seg_done, {(31-SEG_IDX_W){1'b0}}, seg_count}
                                               : 32'h8000_0000;
            ADDR_SEG_SEL:     jtag_rdata_mux = HAS_SEGMENTS
                                               ? {{(32-SEG_IDX_W){1'b0}}, jtag_seg_sel}
                                               : 32'h0;
            // seg_start_ptr is stable after all_seg_done (same CDC pattern
            // as all_seg_done/seg_count on ADDR_SEG_STATUS above)
            ADDR_SEG_START:   jtag_rdata_mux = HAS_SEGMENTS
                                ? {{(32-PTR_W){1'b0}}, jtag_seg_start_ptr}
                                : {{(32-PTR_W){1'b0}}, start_ptr};
            ADDR_PROBE_SEL:   jtag_rdata_mux = HAS_PROBE_MUX ? {24'h0, jtag_probe_sel} : 32'h0;
            ADDR_PROBE_MUX_W: jtag_rdata_mux = PROBE_MUX_W;
            ADDR_STARTUP_ARM: jtag_rdata_mux = {31'h0, jtag_startup_arm};
            ADDR_TRIG_HOLDOFF: jtag_rdata_mux = {16'h0, jtag_trig_holdoff};
            ADDR_TRIG_DELAY:  jtag_rdata_mux = {16'h0, jtag_trig_delay};
            ADDR_TIMESTAMP_W: jtag_rdata_mux = TIMESTAMP_W;
            ADDR_COMPARE_CAPS: jtag_rdata_mux = COMPARE_CAPS;
            default: begin
                if (seq_addr_hit) begin
                    seq_rd_stage = seq_rd_stage_w;
                    seq_rd_off   = seq_rd_off_w;
                    case (seq_rd_off)
                        0:  jtag_rdata_mux = seq_cfg_r;
                        4:  jtag_rdata_mux = seq_value_a_r;
                        8:  jtag_rdata_mux = seq_mask_a_r;
                        12: jtag_rdata_mux = HAS_DUAL_COMPARE ? seq_value_b_r : 32'h0;
                        16: jtag_rdata_mux = HAS_DUAL_COMPARE ? seq_mask_b_r : 32'hFFFF_FFFF;
                        default: jtag_rdata_mux = 32'h0;
                    endcase
                end
            end
        endcase
    end

endmodule
