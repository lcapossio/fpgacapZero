// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero reference design for the Forgix board
// (Efinix Trion T8F49 + Raspberry Pi RP2354).
//
// The Forgix board has no JTAG path to the FPGA fabric at all -- the T8 is
// configured by the RP2354 over a write-only passive SPI link and its JTAG
// pins are not bonded out to a header, a test point, or the Tag-Connect
// footprint (which is ARM SWD for the RP2354).  So this design reaches the
// host through fcapz_ela_uart / fcapz_uart_tap instead, over the two
// configuration SPI pins, which are free once configuration finishes.
//
// See README.md in this folder for the pin reuse, the RP2354 firmware patch,
// and how to connect from the host.
//
// The probe source here is a free-running counter, so the design is useful on
// its own as a bring-up check: arm a capture, and you should read back a ramp.

module forgix_top #(
    // Frequency of the board oscillator feeding clk_in.
    //
    // 32 MHz on the Forgix boards seen so far: the vendor's own reference
    // design (Example_Designs/plasm_led in the forgix_public repository) names
    // the signal `clk_32m` and assigns it to ball B4, which is the pin this
    // design uses.  The oscillator part (ECS-2520MV) is a stocked family
    // rather than a single frequency, so check your board if the link comes up
    // garbled -- the baud divider is derived from this, and a wrong value
    // shows up as noise on the wire rather than as a build error.
    //
    // 32 MHz / 1 Mbaud is an exact divide, so there is no baud error at all.
    parameter CLK_HZ    = 32_000_000,
    parameter BAUD_RATE = 1_000_000,
    parameter SAMPLE_W  = 8,
    parameter DEPTH     = 1024
) (
    input  wire clk_in,

    // No board wiring needed -- these ride the configuration SPI pins, which
    // sit idle once DONE is high:
    //   uart_rxd  = the FPGA's CCK pin  (ball F3)  <- RP2354 GPIO2 (UART0 TX)
    //   uart_txd  = the FPGA's CDI0 pin (ball F2)  -> RP2354 GPIO3 (UART0 RX)
    // CCK and CDI are dual-purpose pins, usable as general I/O in user mode
    // (Efinix AN006, Table 3).  The vendor's own reference design puts the
    // board LEDs on CDI1/CDI5/CDI7, which is independent confirmation that
    // these pins are free once configuration is done.
    input  wire uart_rxd,
    output wire uart_txd,

    // Board LED, active low.
    output wire led_armed_n
);

    // ---- Power-on reset ----
    //
    // There is no user reset pin to bring in.  The board's only reset is
    // CRESET_N, a dedicated configuration pin driven by the RP2354, and the
    // T8's JTAG pins are not bonded out either -- so nothing external can
    // reach the fabric.  Hold reset for a short window after configuration
    // instead; the FPGA enters user mode with its registers already in the
    // state the bitstream set, so this only has to cover the first cycles.
    reg [3:0] por = 4'd0;
    always @(posedge clk_in) begin
        if (!por[3]) por <= por + 1'b1;
    end
    wire rst = ~por[3];

    wire armed;
    assign led_armed_n = ~armed;   // board LED is active low

    // ---- Probe source: a free-running counter ----
    reg [SAMPLE_W-1:0] counter;
    always @(posedge clk_in or posedge rst) begin
        if (rst) counter <= {SAMPLE_W{1'b0}};
        else     counter <= counter + 1'b1;
    end

    fcapz_ela_uart #(
        .CLK_HZ(CLK_HZ),
        .BAUD_RATE(BAUD_RATE),
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        // Keep the footprint modest: the T8F49 has 7,384 LEs, and a
        // dual-comparator build costs roughly half of them.  Turn
        // DUAL_COMPARE back on if you need the richer trigger shapes and can
        // spare the logic.
        .DUAL_COMPARE(0),
        .TRIG_STAGES(1),
        .BURST_W(64)
    ) u_fcapz (
        .sample_clk(clk_in),
        .sample_rst(rst),
        .probe_in(counter),
        .trigger_in(1'b0),
        .trigger_out(),
        .armed_out(armed),
        .uart_rxd(uart_rxd),
        .uart_txd(uart_txd)
    );

endmodule
