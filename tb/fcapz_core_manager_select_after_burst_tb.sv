// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// A slot switch right after a single-chain burst.
//
// The core manager ignores an MGR_ACTIVE write while the pipe is filling its
// burst staging register (burst_rd_active).  On bitstreams from before the
// reset epochs (MGR_CAPS bit 3; the frozen models in tb/legacy/), until a
// command scan ends burst mode every capture on the chain starts another
// fill, including the capture of the select scan itself, and a fill takes
// 256 / SAMPLE_W TCKs.  On a lane of 4 bits or fewer that outlasts the 49-bit
// select scan, so the select is dropped and the next access reaches the
// previous slot.  The current pipe ends that fill on the command itself.
//
// The host (XilinxHwServerTransport) therefore ends every burst on the
// control chain with an uncaptured VERSION read and BURST_DRAIN_IDLE_CYCLES
// idle TCKs, and puts the same drain ahead of a per-access select on a
// manager without epochs.  Each case runs a burst on slot 0, then selects
// slot 1 with the host's register-write framing:
//   DRAIN=0  select straight after the last burst scan;
//   DRAIN=1  the host's drain first.
// Three builds: current manager and pipe; the current manager on the legacy
// pipe (a bitstream with MGR_CAPS bit 3 from before the pipe fix, which the
// host does not drain for: the manager takes the write once a burst owner is
// bound); legacy manager and pipe.  With the drain the select must land on
// every build at every lane width.  Without it the first two must still take
// it, and the legacy build must drop it on a 1-bit lane, which shows the case
// reaches the hazard the drain is for.

module select_after_burst_case #(
    parameter SAMPLE_W = 4,
    parameter DRAIN = 1,
    parameter DRAIN_IDLE = 258,
    parameter LEGACY_MGR = 0,
    parameter LEGACY_PIPE = 0
) (
    output reg       done,
    output reg [7:0] active
);
    localparam NUM_SLOTS = 2;
    localparam DEPTH = 1024;
    localparam PTR_W = 10;
    localparam BURST_W = 256;
    localparam WRITE_IDLE = 20;      // XilinxHwServerTransport.READ_IDLE_CYCLES
    localparam PREFILL_IDLE = 160;   // BURST_PREFILL_IDLE_CYCLES
    localparam DATA_SCANS = 2;

    reg tck = 1'b0;
    always #5 tck = ~tck;

    reg arst = 1'b1;
    reg tdi = 1'b0;
    reg capture = 1'b0;
    reg shift_en = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;
    wire tdo;

    wire pipe_wr_en, pipe_rd_en;
    wire [15:0] pipe_addr;
    wire [31:0] pipe_wdata, mgr_rdata;
    wire [PTR_W-1:0] rd_addr;
    wire rd_active;
    wire [SAMPLE_W-1:0] rd_data;
    wire rd_ts;
    wire bstart, bts;
    wire [PTR_W-1:0] bptr;

    wire [NUM_SLOTS-1:0] slot_wr_en, slot_rd_en;
    wire [NUM_SLOTS*16-1:0] slot_addr;
    wire [NUM_SLOTS*32-1:0] slot_wdata;
    wire [NUM_SLOTS*PTR_W-1:0] slot_rd_addr;
    wire [NUM_SLOTS-1:0] slot_rd_active;
    reg [NUM_SLOTS-1:0] slot_flag = {NUM_SLOTS{1'b0}};
    reg [NUM_SLOTS*PTR_W-1:0] slot_ptr = {NUM_SLOTS*PTR_W{1'b0}};

    // Burst slot stubs: a BURST_PTR write latches the pointer and toggles the
    // slot's start flag, as the ELA does.
    integer si;
    always @(posedge tck) begin
        for (si = 0; si < NUM_SLOTS; si = si + 1) begin
            if (slot_wr_en[si] && slot_addr[si*16 +: 16] == 16'h002C) begin
                slot_ptr[si*PTR_W +: PTR_W] <= slot_wdata[si*32 +: PTR_W];
                slot_flag[si] <= ~slot_flag[si];
            end
        end
    end

    generate
        if (LEGACY_MGR) begin : g_mgr
            fcapz_core_manager_pre_burst_start #(
                .NUM_SLOTS(NUM_SLOTS), .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0),
                .DEPTH(DEPTH), .SLOT_CORE_IDS({16'h4C41, 16'h4C41}),
                .SLOT_HAS_BURST(2'b11)
            ) mgr (
                .jtag_clk(tck), .jtag_rst(arst),
                .jtag_wr_en(pipe_wr_en), .jtag_rd_en(pipe_rd_en),
                .jtag_addr(pipe_addr), .jtag_wdata(pipe_wdata), .jtag_rdata(mgr_rdata),
                .slot_wr_en(slot_wr_en), .slot_rd_en(slot_rd_en),
                .slot_addr(slot_addr), .slot_wdata(slot_wdata),
                .slot_rdata({NUM_SLOTS*32{1'b0}}),
                .burst_rd_addr(rd_addr), .burst_rd_active(rd_active),
                .slot_burst_rd_addr(slot_rd_addr), .slot_burst_rd_active(slot_rd_active),
                .slot_burst_rd_data({NUM_SLOTS*SAMPLE_W{1'b0}}),
                .slot_burst_rd_ts_data({NUM_SLOTS{1'b0}}),
                .slot_burst_start(slot_flag),
                .slot_burst_timestamp({NUM_SLOTS{1'b0}}),
                .slot_burst_start_ptr(slot_ptr),
                .burst_rd_data(rd_data), .burst_rd_ts_data(rd_ts),
                .burst_start(bstart), .burst_timestamp(bts), .burst_start_ptr(bptr)
            );
        end else begin : g_mgr
            fcapz_core_manager #(
                .NUM_SLOTS(NUM_SLOTS), .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0),
                .DEPTH(DEPTH), .SLOT_CORE_IDS({16'h4C41, 16'h4C41}),
                .SLOT_HAS_BURST(2'b11)
            ) mgr (
                .jtag_clk(tck), .jtag_rst(arst), .proto_rst(arst), .tlr(1'b0),
                .jtag_wr_en(pipe_wr_en), .jtag_rd_en(pipe_rd_en),
                .jtag_addr(pipe_addr), .jtag_wdata(pipe_wdata), .jtag_rdata(mgr_rdata),
                .slot_wr_en(slot_wr_en), .slot_rd_en(slot_rd_en),
                .slot_addr(slot_addr), .slot_wdata(slot_wdata),
                .slot_rdata({NUM_SLOTS*32{1'b0}}),
                .slot_rst({NUM_SLOTS{arst}}), .slot_rst_req(),
                .burst_rd_addr(rd_addr), .burst_rd_active(rd_active),
                .slot_burst_rd_addr(slot_rd_addr), .slot_burst_rd_active(slot_rd_active),
                .slot_burst_rd_data({NUM_SLOTS*SAMPLE_W{1'b0}}),
                .slot_burst_rd_ts_data({NUM_SLOTS{1'b0}}),
                .slot_burst_start(slot_flag),
                .slot_burst_timestamp({NUM_SLOTS{1'b0}}),
                .slot_burst_start_ptr(slot_ptr),
                .burst_rd_data(rd_data), .burst_rd_ts_data(rd_ts),
                .burst_start(bstart), .burst_timestamp(bts), .burst_start_ptr(bptr),
                .burst_header()
            );
        end
    endgenerate

    generate
        if (LEGACY_PIPE) begin : g_pipe
            jtag_pipe_iface_pre_cmd_preload_end #(
                .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0), .DEPTH(DEPTH),
                .BURST_W(BURST_W), .SEG_DEPTH(DEPTH)
            ) pipe (
                .arst(arst), .tck(tck), .tdi(tdi), .tdo(tdo),
                .capture(capture), .shift_en(shift_en), .update(update), .sel(sel),
                .reg_clk(), .reg_rst(),
                .reg_wr_en(pipe_wr_en), .reg_rd_en(pipe_rd_en),
                .reg_addr(pipe_addr), .reg_wdata(pipe_wdata), .reg_rdata(mgr_rdata),
                .mem_addr(rd_addr), .mem_active(rd_active),
                .sample_data(rd_data), .timestamp_data(1'b0),
                .burst_start(bstart), .burst_timestamp(bts), .burst_ptr_in(bptr)
            );
        end else begin : g_pipe
            jtag_pipe_iface #(
                .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0), .DEPTH(DEPTH),
                .BURST_W(BURST_W), .SEG_DEPTH(DEPTH)
            ) pipe (
                .arst(arst), .tck(tck), .tdi(tdi), .tdo(tdo),
                .capture(capture), .shift_en(shift_en), .update(update), .sel(sel),
                .reg_clk(), .reg_rst(),
                .reg_wr_en(pipe_wr_en), .reg_rd_en(pipe_rd_en),
                .reg_addr(pipe_addr), .reg_wdata(pipe_wdata), .reg_rdata(mgr_rdata),
                .mem_addr(rd_addr), .mem_active(rd_active),
                .sample_data(rd_data), .timestamp_data(1'b0),
                .burst_start(bstart), .burst_timestamp(bts), .burst_ptr_in(bptr),
                .burst_header({BURST_W{1'b0}})
            );
        end
    endgenerate

    task tick;
        begin
            @(posedge tck);
            #1;
        end
    endtask

    task idle(input integer n);
        integer i;
        begin
            for (i = 0; i < n; i = i + 1)
                tick();
        end
    endtask

    // One DR scan: Capture-DR, nbits of Shift-DR, Update-DR, then the two
    // TCKs back to the next Capture-DR.  No IR scans are modelled between
    // DR scans; they only add TCKs, which can only help the select land.
    task scan(input integer nbits, input [BURST_W-1:0] din);
        integer i;
        begin
            sel = 1'b1;
            capture = 1'b1;
            tick();
            capture = 1'b0;
            shift_en = 1'b1;
            for (i = 0; i < nbits; i = i + 1) begin
                tdi = din[i];
                tick();
            end
            shift_en = 1'b0;
            tdi = 1'b0;
            update = 1'b1;
            tick();
            update = 1'b0;
            sel = 1'b0;
            idle(2);
        end
    endtask

    task command(input bit write, input [15:0] addr, input [31:0] data);
        begin
            scan(49, {{(BURST_W-49){1'b0}}, write, addr, data});
        end
    endtask

    integer j;
    initial begin
        done = 1'b0;
        idle(4);
        arst = 1'b0;
        idle(4);
        command(1'b1, 16'hF008, 32'd0);
        idle(WRITE_IDLE);
        // The host's burst: BURST_PTR write, prefill idle, prime + data scans.
        command(1'b1, 16'h002C, 32'h10);
        idle(PREFILL_IDLE);
        for (j = 0; j < 1 + DATA_SCANS; j = j + 1)
            scan(BURST_W, {BURST_W{1'b0}});
        if (DRAIN) begin
            command(1'b0, 16'h0000, 32'h0);  // uncaptured VERSION read
            idle(DRAIN_IDLE);
        end
        command(1'b1, 16'hF008, 32'd1);
        idle(WRITE_IDLE);
        active = g_mgr.mgr.active_idx;
        done = 1'b1;
    end
endmodule

module fcapz_core_manager_select_after_burst_tb;
    localparam N = 6;
    // Kind k = build * 2 + DRAIN; build 0 current, 1 current manager on the
    // legacy pipe, 2 legacy.  One case per lane width in each.
    localparam K = 6;
    wire [K*N-1:0] done_c;
    wire [N*8-1:0] active_c [0:K-1];

    // Lane widths 1, 2, 4, 8, 16, 32.
    genvar g, k;
    generate
        for (k = 0; k < K; k = k + 1) begin : g_kind
            for (g = 0; g < N; g = g + 1) begin : g_case
                select_after_burst_case #(
                    .SAMPLE_W(1 << g), .DRAIN(k % 2),
                    .LEGACY_MGR(k / 2 == 2), .LEGACY_PIPE(k / 2 >= 1)
                ) c (
                    .done(done_c[k*N + g]), .active(active_c[k][g*8 +: 8])
                );
            end
        end
    endgenerate

    integer i, b;
    integer fails;
    initial begin
        wait (&done_c);
        fails = 0;
        for (i = 0; i < N; i = i + 1) begin
            $display("SAMPLE_W=%0d: current %0d/%0d, bit-3 manager on legacy pipe %0d/%0d, legacy %0d/%0d (with/without drain)",
                     1 << i, active_c[1][i*8 +: 8], active_c[0][i*8 +: 8],
                     active_c[3][i*8 +: 8], active_c[2][i*8 +: 8],
                     active_c[5][i*8 +: 8], active_c[4][i*8 +: 8]);
            for (b = 0; b < 3; b = b + 1) begin
                if (active_c[b*2 + 1][i*8 +: 8] !== 8'd1) begin
                    fails = fails + 1;
                    $display("FAIL: SAMPLE_W=%0d build %0d: select after the drained burst was dropped",
                             1 << i, b);
                end
            end
            for (b = 0; b < 2; b = b + 1) begin
                if (active_c[b*2][i*8 +: 8] !== 8'd1) begin
                    fails = fails + 1;
                    $display("FAIL: SAMPLE_W=%0d build %0d: an undrained select was dropped",
                             1 << i, b);
                end
            end
        end
        if (active_c[4][7:0] !== 8'd0) begin
            fails = fails + 1;
            $display("FAIL: SAMPLE_W=1 on the legacy build without the drain: select landed, so this case no longer reaches the hazard");
        end
        $display("\n=== fcapz_core_manager select after burst summary: %0d failed ===", fails);
        if (fails != 0)
            $fatal(1);
        $finish;
    end
endmodule
