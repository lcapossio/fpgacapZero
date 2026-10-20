// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Microchip PolarFire / PolarFire SoC JTAG TAP wrapper.  SmartFusion2 and
// IGLOO2 have the same UJTAG port list (not validated on hardware there).
//
// PolarFire exposes one user JTAG primitive (UJTAG) per device.  It
// carries the current instruction register on UIREG[7:0] and gives the
// fabric a single user TDR path; IR values 16..127 are left to the user.
// This wrapper decodes two of them, USER1 and USER2, gates
// UDRCAP/UDRSH/UDRUPD per chain and muxes UTDO from the selected chain.
// UDRCK is the TAP's TCK; UDRCAP/UDRSH/UDRUPD are high in the
// Capture-DR/Shift-DR/Update-DR states, as with Xilinx BSCANE2.
//
// Because UJTAG is a single primitive per device, this TAP wrapper
// presents BOTH chains' interfaces on its ports (chN_*) instead of
// being instantiated twice with a CHAIN parameter.  The ELA wrapper
// uses both chains; the EIO wrapper uses ch1 only and ties off ch2.
//
// UJTAG's TCK/TMS/TDI/TRSTB/TDO pins must reach top-level ports of the
// design, which Libero binds to the dedicated JTAG pins.  They are
// passed through on the *_pad_* ports.
//
// USER opcodes default to 0x20/0x21.  0x10/0x11 are in the user range
// on paper, but on PolarFire SoC the MSS RISC-V debug module answers
// there (dtmcs/dmi), so they never reach the fabric.

module jtag_tap_polarfire #(
    parameter [7:0] IR_USER1 = 8'h20,
    parameter [7:0] IR_USER2 = 8'h21
) (
    // JTAG pads (connect straight to top-level ports)
    input  wire tck_pad_i,
    input  wire tms_pad_i,
    input  wire tdi_pad_i,
    input  wire trstb_pad_i,
    output wire tdo_pad_o,
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
    wire       utdi, udrck, udrcap, udrsh, udrupd;
    wire       urstb_unused;

    wire is_user1 = (uireg == IR_USER1);
    wire is_user2 = (uireg == IR_USER2);

    // Mux per-chain TDO into UJTAG.UTDO.  If neither chain is
    // selected, drive zero so we never feed X back to the TAP.
    wire utdo = is_user1 ? ch1_tdo
              : is_user2 ? ch2_tdo
              : 1'b0;

    UJTAG u_ujtag (
        .TCK    (tck_pad_i),
        .TMS    (tms_pad_i),
        .TDI    (tdi_pad_i),
        .TRSTB  (trstb_pad_i),
        .TDO    (tdo_pad_o),
        .UIREG  (uireg),
        .UTDI   (utdi),
        .UDRCK  (udrck),
        .UDRCAP (udrcap),
        .UDRSH  (udrsh),
        .UDRUPD (udrupd),
        .URSTB  (urstb_unused),
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
