// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero core-manager variant for the Microchip PolarFire SoC Discovery
// Kit (MPFS-DISCO-KIT, MPFS095T-1FCSG325E).  Fabric only; the MSS is not used.
//
// One fcapz_debug_multi_polarfire hub on UJTAG USER1 (IR 0x20) carries four
// slots, read through the hub's single-chain burst:
//   slot 0  ELA  : 8-bit x 1024, 32-bit timestamps, 4 segments;
//                  probe = free-running counter on the 50 MHz reference clock
//   slot 1  ELA  : same shape; probe = that counter XOR 0xA5
//   slot 2  EIO  : in  = {SWITCH2, SWITCH1 pressed, 2'b00, slow counter[3:0]}
//                  out = {2'b00 unused, LED6..LED1}
//   slot 3  EIO  : in  = its own outputs (loopback); out = not connected
//   LED7 : heartbeat, ~1.5 Hz.
//
// SWITCH1 held = sample-domain reset.  TCK/TMS/TDI/TRSTB/TDO are the
// device's dedicated JTAG pins; Libero binds them, the PDC does not.

module mpfs_disco_kit_manager_top (
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

    wire [15:0] eio_out;
    wire [7:0]  eio0_in = {sw2_sync[1], sw1_sync[1], 2'b00, heartbeat[24:21]};

    fcapz_debug_multi_polarfire #(
        .NUM_ELAS     (2),
        .NUM_EIOS     (2),
        .SAMPLE_W     (8),
        .DEPTH        (1024),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (4),
        .EIO_IN_W     (8),
        .EIO_OUT_W    (8)
    ) u_debug (
        .ela_sample_clk  ({clk, clk}),
        .ela_sample_rst  ({rst, rst}),
        .ela_probe_in    ({counter ^ 8'hA5, counter}),
        .ela_trigger_in  (2'b00),
        .ela_trigger_out (),
        .ela_armed_out   (),
        .eio_probe_in    ({eio_out[15:8], eio0_in}),
        .eio_probe_out   (eio_out),
        .tck_pad_i       (TCK),
        .tms_pad_i       (TMS),
        .tdi_pad_i       (TDI),
        .trstb_pad_i     (TRSTB),
        .tdo_pad_o       (TDO)
    );

    assign {LED6, LED5, LED4, LED3, LED2, LED1} = eio_out[5:0];
    assign LED7 = heartbeat[24];

endmodule
