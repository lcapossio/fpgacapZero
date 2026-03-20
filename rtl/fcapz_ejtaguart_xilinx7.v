// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero JTAG-to-UART bridge wrapper for Xilinx 7-series / UltraScale.
//
// Single-instantiation wrapper: bundles the JTAG-to-UART core with a
// BSCANE2 TAP primitive on USER4 (CHAIN=4).  USER1-3 are typically
// reserved for ELA and EIO.
//
// Usage:
//   fcapz_ejtaguart_xilinx7 #(.CLK_HZ(100_000_000)) u_uart (
//       .uart_clk(clk), .uart_rst(rst),
//       .uart_txd(txd), .uart_rxd(rxd)
//   );

module fcapz_ejtaguart_xilinx7 #(
    parameter JTAG_CHAIN     = 4,    // USER1-4; default 4
    parameter CLK_HZ         = 100_000_000,
    parameter BAUD_RATE      = 115200,
    parameter TX_FIFO_DEPTH  = 256,
    parameter RX_FIFO_DEPTH  = 256,
    parameter PARITY         = 0
) (
    input  wire uart_clk,
    input  wire uart_rst,
    output wire uart_txd,
    input  wire uart_rxd
);

    // TAP signals
    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;

    // ---- TAP wrapper ----
    jtag_tap_xilinx7 #(.CHAIN(JTAG_CHAIN)) u_tap (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

    // ---- JTAG-to-UART core ----
    fcapz_ejtaguart #(
        .CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD_RATE),
        .TX_FIFO_DEPTH(TX_FIFO_DEPTH), .RX_FIFO_DEPTH(RX_FIFO_DEPTH),
        .PARITY(PARITY),
        .USE_BEHAV_ASYNC_FIFO(0)
    ) u_ejtaguart (
        .uart_clk(uart_clk), .uart_rst(uart_rst),
        .uart_txd(uart_txd), .uart_rxd(uart_rxd),
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel)
    );

endmodule
