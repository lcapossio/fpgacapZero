// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Wrapper port-width bench.
//
// With PROBE_MUX_W set, fcapz_ela's probe_in is the full mux input
// (PROBE_MUX_W bits), not SAMPLE_W*NUM_CHANNELS.  A wrapper that declares its
// own probe_in at the narrow width still elaborates -- the tools only warn and
// pad -- but every mux slice above the first then captures zeros.  This bench
// drives a distinct pattern on every bit and checks that it reaches the core
// unchanged through each wrapper.

module fcapz_ela_wrapper_ports_tb;

    localparam int SAMPLE_W    = 8;
    localparam int PROBE_MUX_W = 16;

    logic clk = 1'b0;
    logic rst = 1'b1;
    always #10 clk = ~clk;

    logic [PROBE_MUX_W-1:0] probe = 16'hA55A;

    int pass_count = 0;
    int fail_count = 0;

    task automatic check(input string name, input bit cond);
        if (cond) begin
            pass_count++;
            $display("  PASS: %s", name);
        end else begin
            fail_count++;
            $display("  FAIL: %s", name);
        end
    endtask

    fcapz_ela_uart #(
        .CLK_HZ(50_000_000), .BAUD_RATE(1_000_000),
        .SAMPLE_W(SAMPLE_W), .DEPTH(16), .PROBE_MUX_W(PROBE_MUX_W)
    ) u_uart (
        .sample_clk(clk), .sample_rst(rst),
        .probe_in(probe),
        .trigger_in(1'b0), .trigger_out(), .armed_out(),
        .uart_rxd(1'b1), .uart_txd()
    );

    fcapz_ela_efinix #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(16), .PROBE_MUX_W(PROBE_MUX_W)
    ) u_efinix (
        .sample_clk(clk), .sample_rst(rst),
        .probe_in(probe),
        .trigger_in(1'b0), .trigger_out(), .armed_out(),
        .jtag1_tck(1'b0), .jtag1_drck(1'b0), .jtag1_tdi(1'b0), .jtag1_tdo(),
        .jtag1_capture(1'b0), .jtag1_shift(1'b0), .jtag1_update(1'b0),
        .jtag1_sel(1'b0),
        .jtag2_tck(1'b0), .jtag2_drck(1'b0), .jtag2_tdi(1'b0), .jtag2_tdo(),
        .jtag2_capture(1'b0), .jtag2_shift(1'b0), .jtag2_update(1'b0),
        .jtag2_sel(1'b0)
    );

    fcapz_ela_intel #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(16), .PROBE_MUX_W(PROBE_MUX_W)
    ) u_intel (
        .sample_clk(clk), .sample_rst(rst),
        .probe_in(probe),
        .trigger_in(1'b0), .trigger_out(), .armed_out()
    );

    initial begin
        #100 rst = 1'b0;
        #100;
        $display("\n=== probe_in reaches the core at full mux width ===");
        check("fcapz_ela_uart",   u_uart.u_ela.probe_in   === probe);
        check("fcapz_ela_efinix", u_efinix.u_ela.probe_in === probe);
        check("fcapz_ela_intel",  u_intel.u_ela.probe_in  === probe);

        $display("\n=== Summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count > 0)
            $fatal(1, "wrapper port bench: failures detected");
        $finish;
    end

endmodule
