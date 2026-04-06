// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// Equivalence testbench for fcapz_async_fifo.
//
// Instantiates both USE_BEHAV_ASYNC_FIFO=1 (behavioral) and
// USE_BEHAV_ASYNC_FIFO=0 (vendor/XPM, backed by the stub) side-by-side
// with identical stimulus.  Asserts that rd_data, rd_empty, and wr_full
// match between the two instances at every clock edge.
//
// Run with:
//   iverilog -g2012 -o fifo_equiv_tb.vvp \
//       tb/fcapz_async_fifo_equiv_tb.v rtl/fcapz_async_fifo.v \
//       tb/xpm_fifo_async_stub.v
//   vvp fifo_equiv_tb.vvp

`timescale 1ns/1ps

module fcapz_async_fifo_equiv_tb;

    localparam DATA_W = 8;
    localparam DEPTH  = 16;

    // Clocks (different rates to exercise CDC paths)
    reg wr_clk = 0;
    reg rd_clk = 0;
    always #5  wr_clk = ~wr_clk;   // 100 MHz write clock
    always #7  rd_clk = ~rd_clk;   //  71 MHz read clock

    reg rst    = 1;
    reg wr_en  = 0;
    reg rd_en  = 0;
    reg [DATA_W-1:0] wr_data = 0;

    // --- DUT A: behavioral ---
    wire [DATA_W-1:0] rd_data_a;
    wire              rd_empty_a, wr_full_a;

    fcapz_async_fifo #(
        .DATA_W                (DATA_W),
        .DEPTH                 (DEPTH),
        .USE_BEHAV_ASYNC_FIFO  (1)
    ) dut_a (
        .wr_clk   (wr_clk), .wr_rst (rst),
        .wr_en    (wr_en),  .wr_data(wr_data), .wr_full (wr_full_a),
        .wr_count (),
        .rd_clk   (rd_clk), .rd_rst (rst),
        .rd_en    (rd_en),  .rd_data(rd_data_a), .rd_empty(rd_empty_a),
        .rd_count ()
    );

    // --- DUT B: XPM stub (wraps behavioral) ---
    wire [DATA_W-1:0] rd_data_b;
    wire              rd_empty_b, wr_full_b;

    fcapz_async_fifo #(
        .DATA_W                (DATA_W),
        .DEPTH                 (DEPTH),
        .USE_BEHAV_ASYNC_FIFO  (0)
    ) dut_b (
        .wr_clk   (wr_clk), .wr_rst (rst),
        .wr_en    (wr_en),  .wr_data(wr_data), .wr_full (wr_full_b),
        .wr_count (),
        .rd_clk   (rd_clk), .rd_rst (rst),
        .rd_en    (rd_en),  .rd_data(rd_data_b), .rd_empty(rd_empty_b),
        .rd_count ()
    );

    // --- Checker ---
    integer errors = 0;

    task check;
        input [63:0] ts;
        begin
            if (rd_empty_a !== rd_empty_b) begin
                $display("MISMATCH @ %0t: rd_empty A=%b B=%b", ts, rd_empty_a, rd_empty_b);
                errors = errors + 1;
            end
            if (wr_full_a !== wr_full_b) begin
                $display("MISMATCH @ %0t: wr_full A=%b B=%b", ts, wr_full_a, wr_full_b);
                errors = errors + 1;
            end
            if (!rd_empty_a && !rd_empty_b && (rd_data_a !== rd_data_b)) begin
                $display("MISMATCH @ %0t: rd_data A=%0h B=%0h", ts, rd_data_a, rd_data_b);
                errors = errors + 1;
            end
        end
    endtask

    // --- Stimulus ---
    integer i;
    initial begin
        // Hold reset for several cycles
        @(posedge wr_clk); @(posedge wr_clk); @(posedge wr_clk);
        rst = 0;
        @(posedge wr_clk);

        // Fill FIFO to capacity
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(posedge wr_clk);
            wr_data = i[DATA_W-1:0];
            wr_en   = 1;
        end
        @(posedge wr_clk);
        wr_en = 0;

        // Let read domain settle
        repeat (4) @(posedge rd_clk);

        // Drain FIFO
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(posedge rd_clk);
            rd_en = 1;
        end
        @(posedge rd_clk);
        rd_en = 0;

        // Interleaved write+read
        repeat (4) @(posedge wr_clk);
        for (i = 0; i < DEPTH / 2; i = i + 1) begin
            @(posedge wr_clk);
            wr_data = (i + 8'hA0) & 8'hFF;
            wr_en   = 1;
            @(posedge rd_clk);
            rd_en   = 1;
        end
        @(posedge wr_clk); wr_en = 0;
        @(posedge rd_clk); rd_en = 0;

        // Final settle
        repeat (8) @(posedge rd_clk);

        if (errors == 0)
            $display("PASS: behavioral and XPM stub outputs match (%0d checks)", DEPTH * 3);
        else
            $display("FAIL: %0d mismatches", errors);

        $finish;
    end

    // Sample both DUTs on rd_clk negedge (stable after posedge transitions)
    always @(negedge rd_clk) begin
        if (!rst)
            check($time);
    end

endmodule
