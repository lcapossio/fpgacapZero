// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

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
    parameter PROBE_MUX_W = 0       // 0=disabled, >0=total probe width for runtime mux
) (
    input  wire                              sample_clk,
    input  wire                              sample_rst,
    input  wire [(PROBE_MUX_W > 0 ? PROBE_MUX_W : NUM_CHANNELS*SAMPLE_W)-1:0] probe_in,

    // External trigger I/O
    input  wire                 trigger_in,
    output wire                 trigger_out,

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
    output reg                       burst_start,
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

    localparam ADDR_DATA_BASE   = 16'h0100;

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
    end

    localparam PTR_W = $clog2(DEPTH);
    localparam WORDS_PER_SAMPLE = (SAMPLE_W + 31) / 32;
    localparam SEQ_STATE_W = (TRIG_STAGES > 1) ? $clog2(TRIG_STAGES) : 1;

    // Phase 4: segment derived params
    localparam SEG_DEPTH = DEPTH / NUM_SEGMENTS;
    localparam SEG_PTR_W = $clog2(SEG_DEPTH);
    localparam SEG_IDX_W = (NUM_SEGMENTS > 1) ? $clog2(NUM_SEGMENTS) : 1;

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
                                  (EXT_TRIG_EN != 0) ? 1'b1 : 1'b0,
                                  (DECIM_EN != 0) ? 1'b1 : 1'b0,
                                  STOR_QUAL[0], TRIG_STAGES[3:0]};

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

    // ---- Channel mux (sample_clk domain) -----------------------------------
    reg [7:0] chan_sel;   // active channel, latched on arm
    reg [7:0] probe_sel;  // runtime probe mux slice, latched on arm

    // Mux probe_in to the active channel slice or runtime probe mux slice.
    wire [SAMPLE_W-1:0] probe_muxed;
    generate
        if (PROBE_MUX_W > 0) begin : g_probe_mux
            assign probe_muxed = probe_in[probe_sel * SAMPLE_W +: SAMPLE_W];
        end else begin : g_no_probe_mux
            assign probe_muxed = probe_in[chan_sel * SAMPLE_W +: SAMPLE_W];
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
    reg [PTR_W:0]   capture_len;  // one extra bit: can equal DEPTH (= 2^PTR_W)
    reg [SAMPLE_W-1:0] probe_prev;

    // Phase 1: decimation state (sample domain)
    // When DECIM_EN=0, decim_tick is tied high and all counter logic optimizes away.
    reg [23:0] decim_ratio;
    reg [23:0] decim_count;
    wire       decim_tick = (DECIM_EN == 0) ? 1'b1 : (decim_count == 0);

    // Phase 2: external trigger sync + state
    // When EXT_TRIG_EN=0, all ext trigger state ties to constant 0
    // and optimizes away in synthesis.
    reg trig_in_sync1, trig_in_sync2;
    reg [1:0] ext_trig_mode;
    reg trigger_out_r;
    assign trigger_out = (EXT_TRIG_EN != 0) ? trigger_out_r : 1'b0;

    // Phase 4: segmented memory state
    reg [SEG_IDX_W-1:0] cur_segment;
    reg [SEG_IDX_W-1:0] seg_count;            // number of completed segments
    reg                  all_seg_done;
    // Per-segment start_ptr storage
    reg [PTR_W-1:0] seg_start_ptr [0:NUM_SEGMENTS-1];

    // ---- Sample buffer (dual-port RAM) -------------------------------------
    wire                 mem_we_a;
    reg  [PTR_W-1:0]    mem_addr_a;
    wire [SAMPLE_W-1:0] mem_dout_a;
    wire [SAMPLE_W-1:0] mem_dout_b;

    dpram #(.WIDTH(SAMPLE_W), .DEPTH(DEPTH)) u_samplebuf (
        .clk_a  (sample_clk),
        .we_a   (mem_we_a),
        .addr_a (mem_addr_a),
        .din_a  (active_probe),
        .dout_a (mem_dout_a),
        .clk_b  (jtag_clk),
        .addr_b (burst_rd_addr),
        .dout_b (mem_dout_b)
    );

    // ---- Phase 3: Timestamp DPRAM ------------------------------------------
    generate
        if (TIMESTAMP_W > 0) begin : g_ts
            reg [TIMESTAMP_W-1:0] ts_counter;
            reg [PTR_W-1:0]      ts_addr_a;
            wire [TIMESTAMP_W-1:0] ts_dout_a;
            wire [TIMESTAMP_W-1:0] ts_dout_b;

            // Free-running counter in sample_clk
            always @(posedge sample_clk or posedge sample_rst) begin
                if (sample_rst)
                    ts_counter <= {TIMESTAMP_W{1'b0}};
                else
                    ts_counter <= ts_counter + 1'b1;
            end

            dpram #(.WIDTH(TIMESTAMP_W), .DEPTH(DEPTH)) u_tsbuf (
                .clk_a  (sample_clk),
                .we_a   (mem_we_a),
                .addr_a (mem_addr_a),
                .din_a  (ts_counter),
                .dout_a (ts_dout_a),
                .clk_b  (jtag_clk),
                .addr_b (burst_rd_addr),
                .dout_b (ts_dout_b)
            );
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
    reg rd_req_toggle_jtag, rd_req_sync1, rd_req_sync2;
    reg rd_ack_toggle_sample, rd_ack_sync1, rd_ack_sync2;
    reg [15:0] rd_addr_jtag, rd_addr_sync1, rd_addr_sync2;
    reg [SAMPLE_W-1:0] rd_data_sample, rd_data_sync1, rd_data_sync2;
    reg [PTR_W-1:0] idx;
    integer word_index, sample_index;

    // Phase 3: timestamp readback CDC registers
    reg [31:0] ts_rd_data_sample, ts_rd_data_sync1, ts_rd_data_sync2;

    // ---- Trigger logic (combinational) -------------------------------------
    wire arm_pulse   = arm_toggle_sync1 ^ arm_toggle_sync2;
    wire reset_pulse = reset_toggle_sync1 ^ reset_toggle_sync2;

    // Simple trigger: uses stage-0 comparators (backward compatible)
    wire simple_hit_a, simple_hit_b;
    trig_compare #(.W(SAMPLE_W)) u_simple_a (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(trig_value), .mask(trig_mask),
        .mode(trig_cmp_mode_a), .hit(simple_hit_a)
    );
    trig_compare #(.W(SAMPLE_W)) u_simple_b (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(trig_value_b), .mask(trig_mask_b),
        .mode(trig_cmp_mode_b), .hit(simple_hit_b)
    );
    reg simple_trigger_hit;
    always @(*) begin
        case (trig_combine)
            2'd0: simple_trigger_hit = simple_hit_a;
            2'd1: simple_trigger_hit = simple_hit_b;
            2'd2: simple_trigger_hit = simple_hit_a & simple_hit_b;
            2'd3: simple_trigger_hit = simple_hit_a | simple_hit_b;
        endcase
    end

    // Sequencer trigger: current stage comparators A and B
    wire seq_hit_a, seq_hit_b;
    trig_compare #(.W(SAMPLE_W)) u_seq_a (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(seq_value_a[seq_state]), .mask(seq_mask_a[seq_state]),
        .mode(seq_mode_a[seq_state]), .hit(seq_hit_a)
    );
    trig_compare #(.W(SAMPLE_W)) u_seq_b (
        .probe(active_probe), .probe_prev(probe_prev),
        .value(seq_value_b[seq_state]), .mask(seq_mask_b[seq_state]),
        .mode(seq_mode_b[seq_state]), .hit(seq_hit_b)
    );
    reg seq_stage_hit;
    always @(*) begin
        case (seq_combine[seq_state])
            2'd0: seq_stage_hit = seq_hit_a;
            2'd1: seq_stage_hit = seq_hit_b;
            2'd2: seq_stage_hit = seq_hit_a & seq_hit_b;
            2'd3: seq_stage_hit = seq_hit_a | seq_hit_b;
        endcase
    end

    // Internal trigger signal (before ext trigger combination)
    wire internal_trigger_hit = (TRIG_STAGES == 1) ? simple_trigger_hit :
                       (seq_stage_hit && seq_is_final[seq_state] &&
                        seq_counter >= seq_count_target[seq_state]);

    wire seq_advance = (TRIG_STAGES > 1) && seq_stage_hit &&
                       !seq_is_final[seq_state] &&
                       (seq_counter >= seq_count_target[seq_state]);

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
    wire sq_hit_w;
    generate
        if (STOR_QUAL != 0) begin : g_sq_cmp
            trig_compare #(.W(SAMPLE_W)) u_sq_cmp (
                .probe(active_probe), .probe_prev(probe_prev),
                .value(sq_value), .mask(sq_mask),
                .mode(sq_cmp_mode), .hit(sq_hit_w)
            );
        end else begin : g_no_sq_cmp
            assign sq_hit_w = 1'b1;  // STOR_QUAL=0: always store
        end
    endgenerate
    wire store_sample = (STOR_QUAL == 0) || !sq_enable || sq_hit_w;

    // Phase 1: combined store enable (storage qualification AND decimation)
    wire store_enable = store_sample & decim_tick;

    // ---- JTAG-domain register writes ---------------------------------------
    integer s;
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
            jtag_trig_ext      <= 2'h0;
            jtag_seg_sel       <= {SEG_IDX_W{1'b0}};
            jtag_probe_sel     <= 8'h0;
            arm_toggle_jtag    <= 1'b0;
            reset_toggle_jtag  <= 1'b0;
            rd_req_toggle_jtag <= 1'b0;
            rd_addr_jtag       <= 16'h0;
            burst_start        <= 1'b0;
            burst_start_ptr    <= {PTR_W{1'b0}};
            for (s = 0; s < TRIG_STAGES; s = s + 1) begin
                jtag_seq_cfg[s]     <= (s == 0) ? 32'h0000_1000 : 32'h0;
                jtag_seq_value_a[s] <= 32'h0;
                jtag_seq_mask_a[s]  <= 32'hFFFF_FFFF;
                jtag_seq_value_b[s] <= 32'h0;
                jtag_seq_mask_b[s]  <= 32'hFFFF_FFFF;
            end
        end else begin
            burst_start <= 1'b0;

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
                    ADDR_SQ_MODE:    jtag_sq_mode      <= jtag_wdata;
                    ADDR_SQ_VALUE:   jtag_sq_value     <= jtag_wdata;
                    ADDR_SQ_MASK:    jtag_sq_mask      <= jtag_wdata;
                    ADDR_CHAN_SEL:   jtag_chan_sel     <= jtag_wdata[7:0];
                    ADDR_DECIM:      jtag_decim        <= jtag_wdata[23:0];
                    ADDR_TRIG_EXT:   jtag_trig_ext     <= jtag_wdata[1:0];
                    ADDR_PROBE_SEL:  jtag_probe_sel    <= jtag_wdata[7:0];
                    ADDR_SEG_SEL:    jtag_seg_sel      <= jtag_wdata[SEG_IDX_W-1:0];
                    ADDR_BURST_PTR: begin
                        // Direct read of seg_start_ptr (stable after
                        // all_seg_done, same CDC safety as STATUS reads)
                        burst_start_ptr <= (NUM_SEGMENTS > 1)
                            ? seg_start_ptr[jtag_seg_sel]
                            : start_ptr;
                        burst_start     <= 1'b1;
                    end
                    default: begin
                        // Sequencer stage registers (5 regs x 4 bytes per stage)
                        if (jtag_addr >= ADDR_SEQ_BASE &&
                            jtag_addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE) begin
                            s = (jtag_addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                            case ((jtag_addr - ADDR_SEQ_BASE) % SEQ_STRIDE)
                                0:  jtag_seq_cfg[s]     <= jtag_wdata;
                                4:  jtag_seq_value_a[s] <= jtag_wdata;
                                8:  jtag_seq_mask_a[s]  <= jtag_wdata;
                                12: jtag_seq_value_b[s] <= jtag_wdata;
                                16: jtag_seq_mask_b[s]  <= jtag_wdata;
                                default: ;
                            endcase
                        end
                    end
                endcase
            end

            if (jtag_rd_en) begin
                rd_addr_jtag <= jtag_addr;
                rd_req_toggle_jtag <= ~rd_req_toggle_jtag;
            end
        end
    end

    // ---- CDC: arm/reset toggles --------------------------------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            arm_toggle_sync1   <= 1'b0; arm_toggle_sync2   <= 1'b0;
            reset_toggle_sync1 <= 1'b0; reset_toggle_sync2 <= 1'b0;
        end else begin
            arm_toggle_sync1   <= arm_toggle_jtag;
            arm_toggle_sync2   <= arm_toggle_sync1;
            reset_toggle_sync1 <= reset_toggle_jtag;
            reset_toggle_sync2 <= reset_toggle_sync1;
        end
    end

    // ---- CDC: config registers ---------------------------------------------
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            pretrig_len_sync1  <= 0; pretrig_len_sync2  <= 0;
            posttrig_len_sync1 <= 0; posttrig_len_sync2 <= 0;
            trig_mode_sync1    <= 0; trig_mode_sync2    <= 0;
            trig_value_sync1   <= 0; trig_value_sync2   <= 0;
            trig_mask_sync1    <= 0; trig_mask_sync2    <= 0;
            chan_sel_sync1     <= 0; chan_sel_sync2     <= 0;
            probe_sel_sync1   <= 0; probe_sel_sync2   <= 0;
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
            chan_sel_sync1     <= jtag_chan_sel;
            chan_sel_sync2     <= chan_sel_sync1;
            probe_sel_sync1   <= jtag_probe_sel;
            probe_sel_sync2   <= probe_sel_sync1;
        end
    end

    // Phase 2: external trigger_in synchronizer
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            trig_in_sync1 <= 1'b0;
            trig_in_sync2 <= 1'b0;
        end else begin
            trig_in_sync1 <= trigger_in;
            trig_in_sync2 <= trig_in_sync1;
        end
    end

    // ---- Latch config on arm -----------------------------------------------
    integer si;
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
            ext_trig_mode    <= 2'h0;
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
        end else if (arm_pulse) begin
            pretrig_len      <= pretrig_len_sync2;
            posttrig_len     <= posttrig_len_sync2;
            trig_value       <= trig_value_sync2;
            trig_mask        <= trig_mask_sync2;
            // Stage-0 compare modes
            if (jtag_seq_cfg[0][9:0] != 10'd0) begin
                trig_cmp_mode_a <= jtag_seq_cfg[0][3:0];
                trig_cmp_mode_b <= jtag_seq_cfg[0][7:4];
                trig_combine    <= jtag_seq_cfg[0][9:8];
            end else begin
                trig_cmp_mode_a <= trig_mode_sync2[1] ? 4'd8 : 4'd0;
                trig_cmp_mode_b <= (trig_mode_sync2 == 2'b11) ? 4'd8 : 4'd0;
                trig_combine    <= (trig_mode_sync2 == 2'b11) ? 2'd3 : 2'd0;
            end
            trig_value_b     <= jtag_seq_value_b_w[0];
            trig_mask_b      <= jtag_seq_mask_b_w[0];
            // Channel select (clamped to valid range)
            chan_sel         <= (chan_sel_sync2 < NUM_CHANNELS) ? chan_sel_sync2 : 8'h0;
            // Probe mux select (clamped when enabled)
            if (PROBE_MUX_W > 0)
                probe_sel   <= (probe_sel_sync2 < PROBE_MUX_SLICES) ? probe_sel_sync2 : 8'h0;
            else
                probe_sel   <= 8'h0;
            // Storage qualification
            sq_enable        <= (STOR_QUAL != 0) && (jtag_sq_mode[3:0] != 0);
            sq_cmp_mode      <= jtag_sq_mode[3:0];
            sq_value         <= jtag_sq_value_w;
            sq_mask          <= jtag_sq_mask_w;
            // Phase 1: decimation
            decim_ratio      <= jtag_decim;
            // Phase 2: external trigger
            ext_trig_mode    <= jtag_trig_ext;
            // Sequencer stages
            for (si = 0; si < TRIG_STAGES; si = si + 1) begin
                seq_mode_a[si]       <= jtag_seq_cfg[si][3:0];
                seq_mode_b[si]       <= jtag_seq_cfg[si][7:4];
                seq_combine[si]      <= jtag_seq_cfg[si][9:8];
                seq_next_state[si]   <= jtag_seq_cfg[si][10 +: SEQ_STATE_W];
                seq_is_final[si]     <= jtag_seq_cfg[si][12];
                seq_count_target[si] <= jtag_seq_cfg[si][31:16];
                seq_value_a[si]      <= jtag_seq_value_a_w[si];
                seq_mask_a[si]       <= jtag_seq_mask_a_w[si];
                seq_value_b[si]      <= jtag_seq_value_b_w[si];
                seq_mask_b[si]       <= jtag_seq_mask_b_w[si];
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
            if (arm_pulse) begin
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
    // Phase 1: mem_we_a now gated by store_enable (= store_sample & decim_tick)
    assign mem_we_a = armed && !done && store_enable;
    always @(*) begin
        if (mem_rd_pending)
            mem_addr_a = idx;
        else
            mem_addr_a = wr_ptr;
    end

    // Phase 2: trigger_out pulse
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst)
            trigger_out_r <= 1'b0;
        else
            trigger_out_r <= (armed && !triggered && trigger_hit) ? 1'b1 : 1'b0;
    end

    // Phase 4: segment base address
    wire [PTR_W-1:0] seg_base = (NUM_SEGMENTS > 1) ? (cur_segment * SEG_DEPTH[PTR_W-1:0]) : {PTR_W{1'b0}};
    wire [PTR_W-1:0] seg_limit = seg_base + SEG_DEPTH[PTR_W-1:0];

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
            capture_len <= {PTR_W+1{1'b0}};
            seq_state   <= {SEQ_STATE_W{1'b0}};
            seq_counter <= 16'h0;
            cur_segment <= {SEG_IDX_W{1'b0}};
            seg_count   <= {SEG_IDX_W{1'b0}};
            all_seg_done <= 1'b0;
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
                capture_len <= {PTR_W+1{1'b0}};
                cur_segment <= {SEG_IDX_W{1'b0}};
                seg_count   <= {SEG_IDX_W{1'b0}};
                all_seg_done <= 1'b0;
                for (seg_i = 0; seg_i < NUM_SEGMENTS; seg_i = seg_i + 1)
                    seg_start_ptr[seg_i] <= {PTR_W{1'b0}};
            end

            if (arm_pulse) begin
                armed       <= 1'b1;
                triggered   <= 1'b0;
                done        <= 1'b0;
                wr_ptr      <= (NUM_SEGMENTS > 1) ? ({PTR_W{1'b0}}) : {PTR_W{1'b0}};
                post_count  <= {PTR_W{1'b0}};
                seq_state   <= {SEQ_STATE_W{1'b0}};
                seq_counter <= 16'h0;
                cur_segment <= {SEG_IDX_W{1'b0}};
                seg_count   <= {SEG_IDX_W{1'b0}};
                all_seg_done <= 1'b0;
                // Overflow check: use SEG_DEPTH for segmented mode
                if (NUM_SEGMENTS > 1)
                    overflow <= (pretrig_len_sync2 + posttrig_len_sync2 + 1 > SEG_DEPTH);
                else
                    overflow <= (pretrig_len_sync2 + posttrig_len_sync2 + 1 > DEPTH);
            end

            if (armed && !done) begin
                // Store sample (qualified + decimated)
                if (store_enable) begin
                    wr_ptr <= wr_ptr + 1'b1;
                    // Phase 4: segment-aware wrap
                    if (NUM_SEGMENTS > 1) begin
                        if (wr_ptr + 1'b1 >= seg_limit)
                            wr_ptr <= seg_base;
                        else
                            wr_ptr <= wr_ptr + 1'b1;
                    end
                end

                // Trigger / sequencer evaluation (runs every cycle, NOT gated by decimation)
                if (!triggered) begin
                    if (trigger_hit) begin
                        triggered   <= 1'b1;
                        trig_ptr    <= wr_ptr;
                        post_count  <= {PTR_W{1'b0}};
                        capture_len <= pretrig_len + posttrig_len + 1'b1;
                    end else if (seq_advance) begin
                        seq_state   <= seq_next_state[seq_state];
                        seq_counter <= 16'h0;
                    end else if (TRIG_STAGES > 1 && seq_stage_hit) begin
                        seq_counter <= seq_counter + 1'b1;
                    end
                end else begin
                    // Post-trigger countdown (counts stored samples only)
                    if (store_enable) begin
                        if (post_count >= posttrig_len) begin
                            // Segment complete
                            if (NUM_SEGMENTS > 1) begin
                                seg_start_ptr[cur_segment] <= trig_ptr - pretrig_len;
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
                                    seq_state   <= {SEQ_STATE_W{1'b0}};
                                    seq_counter <= 16'h0;
                                    // Set wr_ptr to next segment base
                                    wr_ptr      <= (cur_segment + 1) * SEG_DEPTH[PTR_W-1:0];
                                end
                            end else begin
                                done      <= 1'b1;
                                armed     <= 1'b0;
                                start_ptr <= trig_ptr - pretrig_len;
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
    wire [PTR_W-1:0] rd_start_ptr = (NUM_SEGMENTS > 1) ? seg_start_ptr_rd : start_ptr;

    // ---- CDC: data readback (via dpram port A read) -------------------------
    reg [1:0] rd_phase;
    // Track whether current read targets timestamp vs sample memory
    reg rd_is_ts;
    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst) begin
            rd_req_sync1         <= 1'b0;
            rd_req_sync2         <= 1'b0;
            rd_addr_sync1        <= 16'h0;
            rd_addr_sync2        <= 16'h0;
            seg_sel_sync1        <= {SEG_IDX_W{1'b0}};
            seg_sel_sync2        <= {SEG_IDX_W{1'b0}};
            seg_start_ptr_rd     <= {PTR_W{1'b0}};
            rd_data_sample       <= {SAMPLE_W{1'b0}};
            ts_rd_data_sample    <= 32'h0;
            rd_ack_toggle_sample <= 1'b0;
            mem_rd_pending       <= 1'b0;
            rd_phase             <= 2'b00;
            idx                  <= {PTR_W{1'b0}};
            rd_is_ts             <= 1'b0;
        end else begin
            rd_req_sync1  <= rd_req_toggle_jtag;
            rd_req_sync2  <= rd_req_sync1;
            rd_addr_sync1 <= rd_addr_jtag;
            rd_addr_sync2 <= rd_addr_sync1;
            seg_sel_sync1 <= jtag_seg_sel;
            seg_sel_sync2 <= seg_sel_sync1;
            seg_start_ptr_rd <= seg_start_ptr[seg_sel_sync2];

            if (rd_phase == 2'b10) begin
                rd_data_sample <= mem_dout_a;
                if (TIMESTAMP_W > 0 && rd_is_ts)
                    ts_rd_data_sample <= g_ts.ts_dout_a;
                rd_ack_toggle_sample <= ~rd_ack_toggle_sample;
                mem_rd_pending <= 1'b0;
                rd_phase <= 2'b00;
                rd_is_ts <= 1'b0;
            end else if (rd_phase == 2'b01) begin
                rd_phase <= 2'b10;
            end else if (rd_req_sync1 ^ rd_req_sync2) begin
                if (TIMESTAMP_W > 0 && rd_addr_sync1 >= ADDR_TS_DATA_BASE[15:0]) begin
                    // Timestamp readback
                    word_index   = (rd_addr_sync1 - ADDR_TS_DATA_BASE[15:0]) >> 2;
                    sample_index = word_index / TS_WORDS;
                    if (sample_index < capture_len) begin
                        idx <= rd_start_ptr + sample_index[PTR_W-1:0];
                        mem_rd_pending <= 1'b1;
                        rd_phase <= 2'b01;
                        rd_is_ts <= 1'b1;
                    end else begin
                        ts_rd_data_sample <= 32'h0;
                        rd_ack_toggle_sample <= ~rd_ack_toggle_sample;
                    end
                end else if (rd_addr_sync1 >= ADDR_DATA_BASE) begin
                    word_index   = (rd_addr_sync1 - ADDR_DATA_BASE) >> 2;
                    sample_index = word_index / WORDS_PER_SAMPLE;
                    if (sample_index < capture_len) begin
                        idx <= rd_start_ptr + sample_index[PTR_W-1:0];
                        mem_rd_pending <= 1'b1;
                        rd_phase <= 2'b01;
                        rd_is_ts <= 1'b0;
                    end else begin
                        rd_data_sample <= {SAMPLE_W{1'b0}};
                        rd_ack_toggle_sample <= ~rd_ack_toggle_sample;
                    end
                end else begin
                    rd_data_sample <= {SAMPLE_W{1'b0}};
                    rd_ack_toggle_sample <= ~rd_ack_toggle_sample;
                end
            end
        end
    end

    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            rd_ack_sync1  <= 1'b0;
            rd_ack_sync2  <= 1'b0;
            rd_data_sync1 <= {SAMPLE_W{1'b0}};
            rd_data_sync2 <= {SAMPLE_W{1'b0}};
            ts_rd_data_sync1 <= 32'h0;
            ts_rd_data_sync2 <= 32'h0;
        end else begin
            rd_ack_sync1  <= rd_ack_toggle_sample;
            rd_ack_sync2  <= rd_ack_sync1;
            rd_data_sync1 <= rd_data_sample;
            rd_data_sync2 <= rd_data_sync1;
            ts_rd_data_sync1 <= ts_rd_data_sample;
            ts_rd_data_sync2 <= ts_rd_data_sync1;
        end
    end

    // ---- Register read mux -------------------------------------------------
    integer data_word_idx, data_chunk, seq_rd_stage, seq_rd_off;
    integer ts_word_idx, ts_chunk;

    always @(*) begin
        jtag_rdata = 32'h0;
        case (jtag_addr)
            ADDR_VERSION:     jtag_rdata = 32'h0001_0001;
            ADDR_CTRL:        jtag_rdata = jtag_ctrl;
            ADDR_STATUS:      jtag_rdata = {28'h0, overflow, done, triggered, armed};
            ADDR_SAMPLE_W:    jtag_rdata = SAMPLE_W;
            ADDR_DEPTH:       jtag_rdata = DEPTH;
            ADDR_PRETRIG:     jtag_rdata = jtag_pretrig_len;
            ADDR_POSTTRIG:    jtag_rdata = jtag_posttrig_len;
            ADDR_CAPTURE_LEN: jtag_rdata = capture_len;
            ADDR_TRIG_MODE:   jtag_rdata = jtag_trig_mode;
            ADDR_TRIG_VALUE:  jtag_rdata = jtag_trig_value;
            ADDR_TRIG_MASK:   jtag_rdata = jtag_trig_mask;
            ADDR_SQ_MODE:     jtag_rdata = jtag_sq_mode;
            ADDR_SQ_VALUE:    jtag_rdata = jtag_sq_value;
            ADDR_SQ_MASK:     jtag_rdata = jtag_sq_mask;
            ADDR_FEATURES:    jtag_rdata = FEATURES;
            ADDR_CHAN_SEL:    jtag_rdata = {24'h0, jtag_chan_sel};
            ADDR_NUM_CHAN:    jtag_rdata = NUM_CHANNELS;
            ADDR_DECIM:       jtag_rdata = {8'h0, jtag_decim};
            ADDR_TRIG_EXT:    jtag_rdata = {30'h0, jtag_trig_ext};
            ADDR_NUM_SEGMENTS: jtag_rdata = NUM_SEGMENTS;
            ADDR_SEG_STATUS:  jtag_rdata = {all_seg_done, {(31-SEG_IDX_W){1'b0}}, seg_count};
            ADDR_SEG_SEL:     jtag_rdata = {{(32-SEG_IDX_W){1'b0}}, jtag_seg_sel};
            // seg_start_ptr is stable after all_seg_done (same CDC pattern
            // as all_seg_done/seg_count on ADDR_SEG_STATUS above)
            ADDR_SEG_START:   jtag_rdata = (NUM_SEGMENTS > 1)
                                ? {{(32-PTR_W){1'b0}}, seg_start_ptr[jtag_seg_sel]}
                                : {{(32-PTR_W){1'b0}}, start_ptr};
            ADDR_PROBE_SEL:   jtag_rdata = {24'h0, jtag_probe_sel};
            ADDR_PROBE_MUX_W: jtag_rdata = PROBE_MUX_W;
            ADDR_TIMESTAMP_W: jtag_rdata = TIMESTAMP_W;
            default: begin
                if (TIMESTAMP_W > 0 && jtag_addr >= ADDR_TS_DATA_BASE[15:0]) begin
                    ts_word_idx = (jtag_addr - ADDR_TS_DATA_BASE[15:0]) >> 2;
                    ts_chunk = ts_word_idx % TS_WORDS;
                    jtag_rdata = ts_rd_data_sync2 >> (ts_chunk * 32);
                end else if (jtag_addr >= ADDR_DATA_BASE) begin
                    if (WORDS_PER_SAMPLE == 1) begin
                        jtag_rdata = {{(32-SAMPLE_W){1'b0}}, rd_data_sync2};
                    end else begin
                        data_word_idx = (jtag_addr - ADDR_DATA_BASE) >> 2;
                        data_chunk = data_word_idx % WORDS_PER_SAMPLE;
                        jtag_rdata = rd_data_sync2[data_chunk * 32 +: 32];
                    end
                end else if (jtag_addr >= ADDR_SEQ_BASE &&
                             jtag_addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE) begin
                    seq_rd_stage = (jtag_addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                    seq_rd_off   = (jtag_addr - ADDR_SEQ_BASE) % SEQ_STRIDE;
                    case (seq_rd_off)
                        0:  jtag_rdata = jtag_seq_cfg[seq_rd_stage];
                        4:  jtag_rdata = jtag_seq_value_a[seq_rd_stage];
                        8:  jtag_rdata = jtag_seq_mask_a[seq_rd_stage];
                        12: jtag_rdata = jtag_seq_value_b[seq_rd_stage];
                        16: jtag_rdata = jtag_seq_mask_b[seq_rd_stage];
                        default: jtag_rdata = 32'h0;
                    endcase
                end
            end
        endcase
    end

endmodule
