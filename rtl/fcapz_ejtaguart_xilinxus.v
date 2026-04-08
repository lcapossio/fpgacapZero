// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero JTAG-to-UART bridge wrapper for Xilinx UltraScale /
// UltraScale+.
//
// Thin shim over fcapz_ejtaguart_xilinx7 -- BSCANE2 is the same
// primitive on 7-series, UltraScale, and UltraScale+, so there is no
// point in duplicating the wrapper internals.  See jtag_tap_xilinxus.v
// for the list of confirmed device families.
//
// Usage:
//   fcapz_ejtaguart_xilinxus #(.CLK_HZ(100_000_000)) u_uart (
//       .uart_clk(clk), .uart_rst(rst),
//       .uart_txd(txd), .uart_rxd(rxd)
//   );

module fcapz_ejtaguart_xilinxus #(
    parameter JTAG_CHAIN     = 4,
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

    fcapz_ejtaguart_xilinx7 #(
        .JTAG_CHAIN(JTAG_CHAIN), .CLK_HZ(CLK_HZ),
        .BAUD_RATE(BAUD_RATE),
        .TX_FIFO_DEPTH(TX_FIFO_DEPTH), .RX_FIFO_DEPTH(RX_FIFO_DEPTH),
        .PARITY(PARITY)
    ) u_inner (
        .uart_clk(uart_clk), .uart_rst(uart_rst),
        .uart_txd(uart_txd), .uart_rxd(uart_rxd)
    );

endmodule
