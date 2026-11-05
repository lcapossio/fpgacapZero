// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// fcapz_async_fifo with the XPM implementation: the primitive has one rst,
// which must be synchronous to wr_clk. A short rd_rst pulse from the read
// clock domain, landing between wr_clk edges, must reach the primitive as a
// reset that rises and falls on wr_clk edges and lasts at least two wr_clk
// cycles, and no write may reach the primitive while it is in reset.
// An rd_rst with wr_clk stopped (TCK between scans) and a word queued must
// stop reads at once and keep them stopped until the primitive has been
// reset, so the stale word is never read.
// Run against tb/xpm_fifo_async_stub.v.

`timescale 1ns/1ps

module fcapz_async_fifo_xpm_rst_tb #(
    parameter real RD_HALF = 18.5
);

    reg        wr_clk = 1'b0;
    reg        rd_clk = 1'b0;
    reg        wr_rst = 1'b0;
    reg        rd_rst = 1'b0;
    reg        wr_en  = 1'b0;
    reg  [7:0] wr_data = 8'h00;
    reg        rd_en  = 1'b0;
    wire       wr_full, rd_empty, wr_rst_busy, rd_rst_busy;
    wire [7:0] rd_data;
    wire [4:0] rd_count, wr_count;

    reg        wr_run = 1'b1;
    always #5    wr_clk = wr_run ? ~wr_clk : 1'b0;
    always #(RD_HALF) rd_clk = ~rd_clk;

    fcapz_async_fifo #(
        .DATA_W(8),
        .DEPTH(16),
        .ASYNC_FIFO_IMPL(1)
    ) dut (
        .wr_clk(wr_clk), .wr_rst(wr_rst), .wr_en(wr_en), .wr_data(wr_data),
        .wr_full(wr_full), .wr_rst_busy(wr_rst_busy),
        .rd_clk(rd_clk), .rd_rst(rd_rst), .rd_en(rd_en), .rd_data(rd_data),
        .rd_empty(rd_empty), .rd_rst_busy(rd_rst_busy),
        .rd_count(rd_count), .wr_count(wr_count)
    );

    wire prim_rst = dut.gen_xpm.u_xpm_fifo.rst;
    wire prim_wr_en = dut.gen_xpm.u_xpm_fifo.wr_en;
    wire prim_rd_en = dut.gen_xpm.u_xpm_fifo.rd_en;

    integer errors = 0;
    integer rst_cycles = 0;
    time last_wr_edge = 0;

    always @(posedge wr_clk) last_wr_edge = $time;

    // The primitive's rst may only change just after a wr_clk edge.
    always @(prim_rst) begin
        if ($time > 0 && $time != last_wr_edge) begin
            $display("FAIL: XPM rst changed to %b at %0t, not on a wr_clk edge", prim_rst, $time);
            errors = errors + 1;
        end
    end

    // XPM ignores a reset that starts while it is busy with the last one.
    reg prim_rst_q = 1'b1;
    always @(posedge wr_clk) begin
        if (prim_rst && !prim_rst_q && dut.gen_xpm.xpm_wr_rst_busy) begin
            $display("FAIL: XPM rst rose while XPM was busy at %0t", $time);
            errors = errors + 1;
        end
        prim_rst_q = prim_rst;
    end

    always @(posedge wr_clk) begin
        if (prim_rst)
            rst_cycles = rst_cycles + 1;
        if (dut.gen_xpm.xpm_req && prim_wr_en) begin
            $display("FAIL: write reached XPM with a reset pending at %0t", $time);
            errors = errors + 1;
        end
        if (prim_rst && prim_wr_en) begin
            $display("FAIL: write reached XPM during reset at %0t", $time);
            errors = errors + 1;
        end
    end

    // The read side may only reopen once the primitive's own read reset is
    // over: its rd_rst_busy must never rise after ours has fallen.
    reg rd_busy_q = 1'b1;
    always @(posedge rd_clk) begin
        if (!rd_busy_q && dut.gen_xpm.xpm_rd_rst_busy) begin
            $display("FAIL: read side reopened before the XPM read reset at %0t", $time);
            errors = errors + 1;
        end
        rd_busy_q = rd_rst_busy;
    end

    initial begin
        // Power-up reset releases on its own.
        repeat (6) @(posedge wr_clk);
        if (prim_rst) begin
            $display("FAIL: power-up reset never released");
            errors = errors + 1;
        end
        while (wr_rst_busy || rd_rst_busy) @(posedge wr_clk);

        // Write continuously, then pulse rd_rst for 2 ns between wr_clk edges.
        @(posedge wr_clk);
        #1 wr_en = 1'b1;
        repeat (3) @(posedge wr_clk);
        rst_cycles = 0;
        #2 rd_rst = 1'b1;
        #2 rd_rst = 1'b0;
        repeat (8) @(posedge wr_clk);
        #1 wr_en = 1'b0;
        if (rst_cycles < 2) begin
            $display("FAIL: rd_rst pulse held XPM in reset for %0d wr_clk cycles", rst_cycles);
            errors = errors + 1;
        end

        // Drain, then queue one word and wait until the read side sees it.
        rd_en = 1'b1;
        while (wr_rst_busy || rd_rst_busy || !rd_empty) @(posedge rd_clk);
        @(posedge rd_clk);
        #1 rd_en = 1'b0;
        @(posedge wr_clk);
        #1 wr_data = 8'h5A; wr_en = 1'b1;
        @(posedge wr_clk);
        #1 wr_en = 1'b0;
        while (rd_empty) @(posedge rd_clk);

        // Stop wr_clk, then reset from the read side and try to read.
        @(negedge wr_clk);
        wr_run = 1'b0;
        @(posedge rd_clk);
        #1 rd_rst = 1'b1;
        @(posedge rd_clk);
        #1 rd_rst = 1'b0; rd_en = 1'b1;
        repeat (10) begin
            @(posedge rd_clk);
            if (!rd_empty || !rd_rst_busy || prim_rd_en) begin
                $display("FAIL: read side open with wr_clk stopped after rd_rst at %0t (empty=%b busy=%b rd_en=%b)",
                         $time, rd_empty, rd_rst_busy, prim_rd_en);
                errors = errors + 1;
            end
        end

        // Restart wr_clk: the reset runs, and the stale word is gone.
        wr_run = 1'b1;
        while (rd_rst_busy) @(posedge rd_clk);
        repeat (4) @(posedge rd_clk);
        if (!rd_empty) begin
            $display("FAIL: stale word %h still readable after reset", rd_data);
            errors = errors + 1;
        end
        #1 rd_en = 1'b0;

        // A second reset while XPM is still busy with the first must wait
        // for it and then run, not be dropped; writes stay blocked between.
        @(posedge rd_clk);
        #1 rd_rst = 1'b1;
        @(posedge rd_clk);
        #1 rd_rst = 1'b0;
        while (!prim_rst) @(posedge wr_clk);
        while (prim_rst) @(posedge wr_clk);
        #1 wr_en = 1'b1;
        @(posedge rd_clk);
        #1 rd_rst = 1'b1;
        @(posedge rd_clk);
        #1 rd_rst = 1'b0;
        rst_cycles = 0;
        while (wr_rst_busy || rd_rst_busy) @(posedge wr_clk);
        #1 wr_en = 1'b0;
        if (rst_cycles < 2) begin
            $display("FAIL: reset requested during XPM busy was dropped");
            errors = errors + 1;
        end

        if (errors == 0)
            $display("PASS: XPM reset is synchronous to wr_clk");
        $finish;
    end

endmodule
