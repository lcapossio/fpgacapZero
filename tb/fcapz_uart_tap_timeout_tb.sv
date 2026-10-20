// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// RX_TIMEOUT_US -> clock cycles, checked at elaboration.
//
// The conversion must neither round the clock down to whole MHz (a 1.5 MHz
// clock would lose a third of the timeout) nor wrap: a cycle count past 31
// bits used to go negative, and the bridge then dropped the timeout without a
// word.  Each instance below is idle; only its parameters are inspected.

module fcapz_uart_tap_timeout_tb;

    logic clk = 1'b0;
    logic rst = 1'b1;

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

    // 1.5 MHz, 1 ms: 1,500 clocks, not the 1,000 a whole-MHz clock gives.
    fcapz_uart_tap #(
        .CLK_HZ(1_500_000), .BAUD_RATE(115_200), .NUM_CHAINS(1),
        .MAX_DR_BITS(32), .RX_TIMEOUT_US(1_000)
    ) u_slow (
        .clk(clk), .arst(rst), .uart_rxd(1'b1), .uart_txd(),
        .tck(), .tdi(), .tdo(1'b0), .capture(), .shift(), .update(), .sel()
    );

    // 33.333333 MHz, 10 ms: 333,334 clocks (rounded up), not 330,000.
    fcapz_uart_tap #(
        .CLK_HZ(33_333_333), .BAUD_RATE(1_000_000), .NUM_CHAINS(1),
        .MAX_DR_BITS(32), .RX_TIMEOUT_US(10_000)
    ) u_frac (
        .clk(clk), .arst(rst), .uart_rxd(1'b1), .uart_txd(),
        .tck(), .tdi(), .tdo(1'b0), .capture(), .shift(), .update(), .sel()
    );

    // 200 MHz, 20 s: 4e12 clocks, clamped.  Unclamped it wrapped negative.
    fcapz_uart_tap #(
        .CLK_HZ(200_000_000), .BAUD_RATE(1_000_000), .NUM_CHAINS(1),
        .MAX_DR_BITS(32), .RX_TIMEOUT_US(20_000_000)
    ) u_long (
        .clk(clk), .arst(rst), .uart_rxd(1'b1), .uart_txd(),
        .tck(), .tdi(), .tdo(1'b0), .capture(), .shift(), .update(), .sel()
    );

    // 50 MHz, 10 ms: the ordinary case is exact.
    fcapz_uart_tap #(
        .CLK_HZ(50_000_000), .BAUD_RATE(1_000_000), .NUM_CHAINS(1),
        .MAX_DR_BITS(32), .RX_TIMEOUT_US(10_000)
    ) u_norm (
        .clk(clk), .arst(rst), .uart_rxd(1'b1), .uart_txd(),
        .tck(), .tdi(), .tdo(1'b0), .capture(), .shift(), .update(), .sel()
    );

    initial begin
        $display("\n=== RX_TIMEOUT_US conversion ===");
        check("1.5 MHz keeps its fraction",
              u_slow.u_bridge.RX_TIMEOUT == 1_500);
        check("33.333333 MHz rounds up",
              u_frac.u_bridge.RX_TIMEOUT == 333_334);
        check("a 31-bit overflow is clamped",
              u_long.u_bridge.RX_TIMEOUT == 32'h7FFF_FFFE);
        check("a clamped timeout is still on",
              u_long.u_bridge.HAS_RX_TIMEOUT);
        check("50 MHz is exact",
              u_norm.u_bridge.RX_TIMEOUT == 500_000);

        $display("\n=== Summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count > 0)
            $fatal(1, "uart tap timeout bench: failures detected");
        $finish;
    end

endmodule
