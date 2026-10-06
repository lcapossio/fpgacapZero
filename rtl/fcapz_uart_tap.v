// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// UART physical layer for the fpgacapZero virtual JTAG TAP.
//
// This module is only the PHY: an 8N1 transmitter and receiver wrapped around
// fcapz_tap_bridge, which owns the wire protocol and drives the TAP.  Swap
// this for an SPI (or USB-FIFO, or anything else that moves bytes) PHY and the
// protocol, the host transport, and every core behind the TAP stay the same.
//
// Use it on any board whose fabric has no usable JTAG but does have two free
// pins.  Those pins need not be a dedicated UART header: on boards configured
// by a companion MCU they are often the configuration pins themselves, which
// go idle once configuration finishes (see examples/forgix/ for one such
// board).  Nothing here is board- or vendor-specific.
//
// Parameters
//   CLK_HZ      - fabric clock frequency in Hz
//   BAUD_RATE   - UART baud rate; CLK_HZ/BAUD_RATE must be >= 4
//   NUM_CHAINS  - number of user chains exposed via sel[]
//   MAX_DR_BITS - largest DR width accepted (256 covers the burst chain)
//   RX_TIMEOUT_US - how long, in microseconds, a partly received command may
//                 wait for its next byte before the bridge drops it and
//                 hunts for SOF again (see fcapz_tap_bridge.v); 0 waits
//                 forever.  The host sends a command in one write, so its
//                 bytes arrive back to back; 10 ms is far above any gap a
//                 USB-serial bridge leaves inside one, and far below the
//                 host transport's reply timeout.  Rounded up to whole clocks
//                 and clamped at 2^31-2 of them (~10 s at 200 MHz).

module fcapz_uart_tap #(
    parameter CLK_HZ        = 50_000_000,
    parameter BAUD_RATE     = 1_000_000,
    parameter NUM_CHAINS    = 4,
    parameter MAX_DR_BITS   = 256,
    parameter RX_TIMEOUT_US = 10_000
) (
    input  wire                   clk,
    input  wire                   arst,

    // UART pins
    input  wire                   uart_rxd,
    output wire                   uart_txd,

    // fpgacapZero TAP interface
    output wire                   tck,
    output wire                   tdi,
    input  wire [NUM_CHAINS-1:0]  tdo,
    output wire                   capture,
    output wire                   shift,
    output wire                   update,
    output wire [NUM_CHAINS-1:0]  sel
);

    localparam BAUD_DIV = CLK_HZ / BAUD_RATE;
    // ceil(CLK_HZ * RX_TIMEOUT_US / 1e6), in 64 bits: the product overflows
    // 32-bit parameter maths at ordinary clock rates, and dividing first
    // rounds CLK_HZ down to whole MHz (a 1.5 MHz clock would lose a third of
    // the timeout).  Rounding up keeps it at least as long as asked.
    localparam [63:0] RX_TIMEOUT_CYC64 =
        (64'd1 * CLK_HZ * RX_TIMEOUT_US + 64'd999_999) / 64'd1_000_000;
    // Clamped to what the bridge's 32-bit parameter maths takes, about 10 s
    // at 200 MHz.  Unclamped, a longer one wraps negative and the bridge
    // silently drops the timeout altogether.
    localparam [63:0] RX_TIMEOUT_MAX = 64'h7FFF_FFFE;
    localparam integer RX_TIMEOUT_CYC =
        (RX_TIMEOUT_CYC64 > RX_TIMEOUT_MAX) ? RX_TIMEOUT_MAX[31:0]
                                             : RX_TIMEOUT_CYC64[31:0];

    // synthesis translate_off
    initial begin
        if (CLK_HZ / BAUD_RATE < 4)
            $error("BAUD_RATE too high for CLK_HZ: divider must be >= 4");
        if (RX_TIMEOUT_US > 0 && RX_TIMEOUT_CYC < 20 * BAUD_DIV)
            $error("RX_TIMEOUT_US must cover at least two bytes on the wire");
    end
    // synthesis translate_on

    // ------------------------------------------------------------------
    //  Receiver -- 8N1, sampled at the bit midpoint
    // ------------------------------------------------------------------
    localparam BAUD_CNT_W = $clog2(BAUD_DIV);

    // Two-stage synchroniser: uart_rxd is asynchronous to clk.
    (* ASYNC_REG = "TRUE" *) reg rxd_meta, rxd_sync;
    always @(posedge clk or posedge arst) begin
        if (arst) begin
            rxd_meta <= 1'b1;
            rxd_sync <= 1'b1;
        end else begin
            rxd_meta <= uart_rxd;
            rxd_sync <= rxd_meta;
        end
    end

    reg                   rx_busy;
    reg [BAUD_CNT_W:0]    rx_cnt;
    reg [3:0]             rx_bit;
    reg [7:0]             rx_sr;
    reg [7:0]             rx_data;
    reg                   rx_valid;   // one-clk strobe

    always @(posedge clk or posedge arst) begin
        if (arst) begin
            rx_busy  <= 1'b0;
            rx_cnt   <= 0;
            rx_bit   <= 4'd0;
            rx_sr    <= 8'h0;
            rx_data  <= 8'h0;
            rx_valid <= 1'b0;
        end else begin
            rx_valid <= 1'b0;
            if (!rx_busy) begin
                // Idle: wait for the falling edge that starts a frame, then
                // aim at the middle of the start bit.
                if (!rxd_sync) begin
                    rx_busy <= 1'b1;
                    rx_cnt  <= BAUD_DIV / 2;
                    rx_bit  <= 4'd0;
                end
            end else if (rx_cnt != 0) begin
                rx_cnt <= rx_cnt - 1'b1;
            end else begin
                rx_cnt <= BAUD_DIV - 1;
                if (rx_bit == 4'd0) begin
                    // Midpoint of the start bit.  A high here is noise, not a
                    // frame -- abandon it rather than shifting in garbage.
                    if (rxd_sync) rx_busy <= 1'b0;
                    else          rx_bit  <= 4'd1;
                end else if (rx_bit <= 4'd8) begin
                    rx_sr  <= {rxd_sync, rx_sr[7:1]};   // LSB first
                    rx_bit <= rx_bit + 1'b1;
                end else begin
                    // Stop bit.  Accept the byte even if the stop bit is low
                    // (framing error); the command parser resynchronises on
                    // SOF, which recovers faster than dropping bytes here.
                    rx_data  <= rx_sr;
                    rx_valid <= 1'b1;
                    rx_busy  <= 1'b0;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    //  Transmitter -- 8N1
    // ------------------------------------------------------------------
    wire [7:0] tx_data;
    wire       tx_start;

    reg                tx_busy;
    reg [BAUD_CNT_W:0] tx_cnt;
    reg [3:0]          tx_bit;
    reg [9:0]          tx_sr;      // {stop, data[7:0], start}

    assign uart_txd = tx_busy ? tx_sr[0] : 1'b1;

    always @(posedge clk or posedge arst) begin
        if (arst) begin
            tx_busy <= 1'b0;
            tx_cnt  <= 0;
            tx_bit  <= 4'd0;
            tx_sr   <= 10'h3FF;
        end else if (!tx_busy) begin
            if (tx_start) begin
                tx_sr   <= {1'b1, tx_data, 1'b0};
                tx_busy <= 1'b1;
                tx_cnt  <= BAUD_DIV - 1;
                tx_bit  <= 4'd0;
            end
        end else if (tx_cnt != 0) begin
            tx_cnt <= tx_cnt - 1'b1;
        end else begin
            tx_cnt <= BAUD_DIV - 1;
            tx_sr  <= {1'b1, tx_sr[9:1]};
            tx_bit <= tx_bit + 1'b1;
            if (tx_bit == 4'd9) tx_busy <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    //  Protocol engine + TAP
    // ------------------------------------------------------------------
    fcapz_tap_bridge #(
        .NUM_CHAINS(NUM_CHAINS),
        .MAX_DR_BITS(MAX_DR_BITS),
        .PROTO_EXTRA(0),
        .RX_TIMEOUT(RX_TIMEOUT_CYC)
    ) u_bridge (
        .clk(clk), .arst(arst),
        .rx_data(rx_data), .rx_valid(rx_valid),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .tck(tck), .tdi(tdi), .tdo(tdo),
        .capture(capture), .shift(shift), .update(update), .sel(sel)
    );

endmodule
