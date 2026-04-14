// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Microchip / Microsemi PolarFire (and SmartFusion2 / IGLOO2) JTAG TAP wrapper.
//
// PolarFire exposes a single user JTAG primitive (UJTAG) with two
// user instructions, USER1 and USER2, sharing one TDR path.  The
// active user IR is exposed on UIREG[7:0]; the wrapper decodes it
// to gate UDRSEL/UDRCAP/UDRSH/UDRUPD per chain and to mux UTDO from
// the chain currently selected.
//
// Because UJTAG is a single primitive per device, this TAP wrapper
// presents BOTH chains' interfaces on its ports (chN_*) instead of
// being instantiated twice with a CHAIN parameter.  The ELA wrapper
// uses both chains; the EIO wrapper uses ch1 only and ties off ch2.
//
// USER opcodes default to the documented PolarFire values
// (USER1=0x10, USER2=0x11) and can be overridden if your device's
// BSDL uses different codes.

module jtag_tap_polarfire #(
    parameter [7:0] IR_USER1 = 8'h10,
    parameter [7:0] IR_USER2 = 8'h11
) (
    // Chain 1 (USER1) — register interface
    output wire ch1_tck,
    output wire ch1_tdi,
    input  wire ch1_tdo,
    output wire ch1_capture,
    output wire ch1_shift,
    output wire ch1_update,
    output wire ch1_sel,
    // Chain 2 (USER2) — burst data
    output wire ch2_tck,
    output wire ch2_tdi,
    input  wire ch2_tdo,
    output wire ch2_capture,
    output wire ch2_shift,
    output wire ch2_update,
    output wire ch2_sel
);

    wire [7:0] uireg;
    wire       utdi, udrck, udrcap, udrsh, udrupd, urstb;

    wire is_user1 = (uireg == IR_USER1);
    wire is_user2 = (uireg == IR_USER2);

    // Mux per-chain TDO into UJTAG.UTDO.  If neither chain is
    // selected, drive zero so we never feed X back to the TAP.
    wire utdo = is_user1 ? ch1_tdo
              : is_user2 ? ch2_tdo
              : 1'b0;

    UJTAG u_ujtag (
        .UIREG0 (uireg[0]),
        .UIREG1 (uireg[1]),
        .UIREG2 (uireg[2]),
        .UIREG3 (uireg[3]),
        .UIREG4 (uireg[4]),
        .UIREG5 (uireg[5]),
        .UIREG6 (uireg[6]),
        .UIREG7 (uireg[7]),
        .UTDI   (utdi),
        .UDRCK  (udrck),
        .UDRCAP (udrcap),
        .UDRSH  (udrsh),
        .UDRUPD (udrupd),
        .URSTB  (urstb),
        .UTDO   (utdo)
    );

    // Gate per-chain capture/shift/update with the IR decode so each
    // chain's logic only ticks while its USER instruction is active.
    assign ch1_tck     = udrck;
    assign ch1_tdi     = utdi;
    assign ch1_capture = udrcap & is_user1;
    assign ch1_shift   = udrsh  & is_user1;
    assign ch1_update  = udrupd & is_user1;
    assign ch1_sel     = is_user1;

    assign ch2_tck     = udrck;
    assign ch2_tdi     = utdi;
    assign ch2_capture = udrcap & is_user2;
    assign ch2_shift   = udrsh  & is_user2;
    assign ch2_update  = udrupd & is_user2;
    assign ch2_sel     = is_user2;

endmodule
