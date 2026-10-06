// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero reference design for the Microchip PolarFire SoC Discovery Kit
// (MPFS-DISCO-KIT, MPFS095T-1FCSG325E).  Fabric only; the MSS is not used.
//
//   ELA  : 8-bit samples, 1024 deep, probe = free-running counter on the
//          50 MHz reference clock.  USER1 (IR 0x20) control, USER2 (IR 0x21)
//          burst readout.
//   EIO  : shares USER1 at register offset 0x8000 (one UJTAG per device).
//          probe_in  = {SWITCH2, SWITCH1} pressed (active-high)
//          probe_out = LED1..LED6
//   LED7 : heartbeat, ~1.5 Hz, shows the fabric is configured and clocked.
//
// SWITCH1 held = sample-domain reset.  TCK/TMS/TDI/TRSTB/TDO are the
// device's dedicated JTAG pins; Libero binds them, the PDC does not.

module mpfs_disco_kit_top (
    input  wire REF_CLK_50MHz,
    input  wire SWITCH1,        // active-low push button
    input  wire SWITCH2,        // active-low push button
    output wire LED1,
    output wire LED2,
    output wire LED3,
    output wire LED4,
    output wire LED5,
    output wire LED6,
    output wire LED7,
    // Dedicated JTAG pins (UJTAG)
    input  wire TCK,
    input  wire TMS,
    input  wire TDI,
    input  wire TRSTB,
    output wire TDO
);

    wire clk = REF_CLK_50MHz;

    // Power-on reset: fabric registers come up at zero after programming,
    // so hold reset for 16 cycles, then follow SWITCH1.
    reg [4:0] por_cnt = 5'd0;
    reg [1:0] sw1_sync = 2'b00;
    reg [1:0] sw2_sync = 2'b00;
    reg       rst = 1'b1;

    always @(posedge clk) begin
        if (!por_cnt[4])
            por_cnt <= por_cnt + 5'd1;
        sw1_sync <= {sw1_sync[0], ~SWITCH1};
        sw2_sync <= {sw2_sync[0], ~SWITCH2};
        rst      <= ~por_cnt[4] | sw1_sync[1];
    end

    reg [7:0] counter;
    always @(posedge clk) begin
        if (rst)
            counter <= 8'd0;
        else
            counter <= counter + 8'd1;
    end

    reg [24:0] heartbeat;
    always @(posedge clk) begin
        if (rst)
            heartbeat <= 25'd0;
        else
            heartbeat <= heartbeat + 25'd1;
    end

    wire [5:0] eio_leds;

    fcapz_ela_polarfire #(
        .SAMPLE_W  (8),
        .DEPTH     (1024),
        .EIO_EN    (1),
        .EIO_IN_W  (2),
        .EIO_OUT_W (6)
    ) u_ela (
        .sample_clk    (clk),
        .sample_rst    (rst),
        .probe_in      (counter),
        .eio_probe_in  ({sw2_sync[1], sw1_sync[1]}),
        .eio_probe_out (eio_leds),
        .tck_pad_i     (TCK),
        .tms_pad_i     (TMS),
        .tdi_pad_i     (TDI),
        .trstb_pad_i   (TRSTB),
        .tdo_pad_o     (TDO)
    );

    assign {LED6, LED5, LED4, LED3, LED2, LED1} = eio_leds;
    assign LED7 = heartbeat[24];

endmodule
