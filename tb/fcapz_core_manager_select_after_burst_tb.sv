// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// A slot switch right after a single-chain burst.
//
// The core manager ignores an MGR_ACTIVE write while the pipe is filling its
// burst staging register (burst_rd_active).  Until a command scan ends burst
// mode, every capture on the chain starts another fill, including the
// capture of the select scan itself, and a fill takes 256 / SAMPLE_W TCKs.
// On a lane of 4 bits or fewer that outlasts the 49-bit select scan, so the
// select is dropped and the next access reaches the previous slot.
//
// The host (XilinxHwServerTransport._read_block_burst) therefore ends every
// single-chain burst with an uncaptured VERSION read and
// BURST_DRAIN_IDLE_CYCLES idle TCKs.  Each case runs a burst on slot 0, then
// selects slot 1 with the host's register-write framing:
//   DRAIN=0  select straight after the last burst scan (the old host);
//   DRAIN=1  the host's drain first.
// With the drain the select must land for every lane width.  Without it the
// select must be dropped on a 1-bit lane, which shows the case reaches the
// hazard the drain is for.

module select_after_burst_case #(
    parameter SAMPLE_W = 4,
    parameter DRAIN = 1,
    parameter DRAIN_IDLE = 258
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

    fcapz_core_manager #(
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
        .burst_start(bstart), .burst_timestamp(bts), .burst_ptr_in(bptr)
    );

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
        active = mgr.active_idx;
        done = 1'b1;
    end
endmodule

module fcapz_core_manager_select_after_burst_tb;
    localparam N = 6;
    wire [N-1:0] done_drain, done_naive;
    wire [N*8-1:0] active_drain, active_naive;

    // Lane widths 1, 2, 4, 8, 16, 32.
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : g_case
            select_after_burst_case #(.SAMPLE_W(1 << g), .DRAIN(1)) drain (
                .done(done_drain[g]), .active(active_drain[g*8 +: 8])
            );
            select_after_burst_case #(.SAMPLE_W(1 << g), .DRAIN(0)) naive (
                .done(done_naive[g]), .active(active_naive[g*8 +: 8])
            );
        end
    endgenerate

    integer i;
    integer fails;
    initial begin
        wait (&done_drain && &done_naive);
        fails = 0;
        for (i = 0; i < N; i = i + 1) begin
            $display("SAMPLE_W=%0d: with drain slot %0d, without slot %0d",
                     1 << i, active_drain[i*8 +: 8], active_naive[i*8 +: 8]);
            if (active_drain[i*8 +: 8] !== 8'd1) begin
                fails = fails + 1;
                $display("FAIL: SAMPLE_W=%0d: select after the drained burst was dropped", 1 << i);
            end
        end
        if (active_naive[7:0] !== 8'd0) begin
            fails = fails + 1;
            $display("FAIL: SAMPLE_W=1 without the drain: select landed, so this case no longer reaches the hazard");
        end
        $display("\n=== fcapz_core_manager select after burst summary: %0d failed ===", fails);
        if (fails != 0)
            $fatal(1);
        $finish;
    end
endmodule
