// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Gowin JTAG TAP wrapper.
// Presents the standard fpgacapZero TAP interface.
//
// Gowin devices expose user logic through one GW_JTAG primitive per design.
// That primitive provides two user DR chains (ER1/ER2, selected by IR
// 0x42/0x43 on the devices checked so far).

module jtag_tap_gowin #(
) (
    output reg          tck,
    output reg          tdi,
    input  reg  [1:0]   tdo,
    output reg  [1:0]   capture,
    output reg  [1:0]   shift,
    output reg  [1:0]   update,
    output reg  [1:0]   sel,

    input  wire         tms_pad_i,
    input  wire         tck_pad_i,
    input  wire         tdi_pad_i,
    output wire         tdo_pad_o
);

    wire jtck;
    wire jtdi;
    wire jshift_capture;
    wire jupdate;
    wire jce1;
    wire jce2;

    reg jupdate_d1;
    reg jtdi_l;
    reg sreg;
    reg jhold;

    GW_JTAG u_jtag (
        .tck_pad_i              (tck_pad_i),
        .tms_pad_i              (tms_pad_i),
        .tdi_pad_i              (tdi_pad_i),
        .tdo_pad_o              (tdo_pad_o),
        .tck_o                  (jtck),
        .tdi_o                  (jtdi),
        .test_logic_reset_o     (),
        .run_test_idle_er1_o    (),
        .run_test_idle_er2_o    (),
        .shift_dr_capture_dr_o  (jshift_capture),
        .pause_dr_o             (),
        .update_dr_o            (jupdate),
        .enable_er1_o           (jce1),
        .enable_er2_o           (jce2),
        .tdo_er1_i              (tdo[0]),
        .tdo_er2_i              (tdo[1])
    );

    always_comb begin
        tck = jtck;

        if (jshift_capture == 1'b1) begin
            tdi = jtdi;
        end else begin
            tdi = jtdi_l;
        end
    end

    always @(posedge jtck) begin
        if (jshift_capture == 1'b1) begin
            jtdi_l <= jtdi;
        end
    end

    always @(posedge jtck) begin
        // defaults
        jupdate_d1 <= jupdate;

        if (jshift_capture == 1'b1) begin
            jhold <= 1'b1;
        end else if ((jupdate == 1'b0) && (jupdate_d1 == 1'b1)) begin
            jhold <= 1'b0;
        end
    end

    always_comb begin
        capture[0]  = jce1 & (~jshift_capture) & (~jhold);
        capture[1]  = jce2 & (~jshift_capture) & (~jhold);

        shift[0]    = jce1 & jshift_capture;
        shift[1]    = jce2 & jshift_capture;
    end

    always @(posedge jtck) begin
        if (jshift_capture == 1'b1) begin
            if (jce1 == 1'b1) begin
                sreg <= 1'b0;
            end
            if (jce2 == 1'b1) begin
                sreg <= 1'b1;
            end
        end
    end

    always_comb begin
        update[0]   = jupdate & ~sreg;
        update[1]   = jupdate & sreg;

        sel[0]      = jce1;
        sel[1]      = jce2;
    end

endmodule
