// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Gowin JTAG TAP wrapper.
// Presents the standard fpgacapZero TAP interface.
//
// Gowin devices expose user logic through one GW_JTAG primitive per design.
// That primitive provides two user DR chains (ER1/ER2, selected by IR
// 0x42/0x43 on the devices checked so far).  CHAIN selects which ER this
// wrapper instance routes, but do not instantiate multiple standalone Gowin
// fcapz wrappers in the same design unless you refactor them to share one
// GW_JTAG instance.

module jtag_tap_gowin #(
    parameter CHAIN = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel
);

    wire jtck, jtdi;
    wire jreset;
    wire jrti1, jrti2;
    wire jshift_capture, jupdate;
    wire jpause;
    wire jce1, jce2;

    generate
        if (CHAIN < 1 || CHAIN > 2) begin : g_invalid_chain
`ifndef VERILATOR
            __FCAPZ_GOWIN_CHAIN_MUST_BE_1_OR_2__ u_invalid_chain();
`endif
            initial begin
                $error("jtag_tap_gowin CHAIN must be 1 (ER1) or 2 (ER2)");
                $finish;
            end
        end
    endgenerate

    GW_JTAG u_jtag (
        .tck_o                (jtck),
        .tdi_o                (jtdi),
        .test_logic_reset_o   (jreset),
        .run_test_idle_er1_o  (jrti1),
        .run_test_idle_er2_o  (jrti2),
        .shift_dr_capture_dr_o(jshift_capture),
        .pause_dr_o           (jpause),
        .update_dr_o          (jupdate),
        .enable_er1_o         (jce1),
        .enable_er2_o         (jce2),
        .tdo_er1_i            ((CHAIN == 1) ? tdo : 1'b0),
        .tdo_er2_i            ((CHAIN == 2) ? tdo : 1'b0)
    );

    assign tck     = jtck;
    assign tdi     = jtdi;
    assign shift   = jshift_capture & ~jpause;
    assign update  = jupdate;
    assign sel     = (CHAIN == 1) ? jce1 : jce2;

    // GW_JTAG combines CAPTURE-DR and SHIFT-DR into one pulse/level, so
    // derive the one-cycle capture strobe from the selected chain enable
    // rising edge.  Gate PAUSE-DR out so a pause/resume sequence cannot
    // look like a fresh CAPTURE-DR to the register interface.
    reg sel_prev;
    always @(posedge jtck) sel_prev <= sel;
    assign capture = sel & ~sel_prev & jshift_capture & ~jpause;

endmodule
