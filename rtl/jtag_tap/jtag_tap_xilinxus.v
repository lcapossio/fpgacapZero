// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Xilinx UltraScale / UltraScale+ JTAG TAP wrapper.
//
// UltraScale and UltraScale+ both expose the same BSCANE2 primitive
// from the unisim library that 7-series uses.  The body of this module
// is therefore a thin shim over jtag_tap_xilinx7 -- there is one
// definition of the BSCANE2 instantiation in the project, used by both
// the 7-series and UltraScale entry points.  If AMD ever ships an
// UltraScale-only revision of the primitive, only this file needs to
// change; the wrappers in fcapz_*_xilinxus.v stay untouched.
//
// Confirmed device families (Vivado 2022.2 and later):
//   UltraScale          - Kintex UltraScale  (KU040, KU060, KU115, ...)
//                       - Virtex UltraScale  (VU065, VU125, VU190, ...)
//   UltraScale+         - Artix UltraScale+  (AU7P, AU10P, ...)
//                       - Kintex UltraScale+ (KU3P, KU5P, KU9P, KU11P,
//                                             KU15P, KU19P)
//                       - Virtex UltraScale+ (VU3P/5P/7P/9P/11P/13P/...)
//                       - Zynq UltraScale+   (ZU2/3/4/5/6/7/9/11/15/17/19/...)
//
// USER chain → IR encoding, from the parts' BSDL files:
//   single-die parts (6-bit IR, e.g. KU035): the 7-series codes,
//     USER1..USER4 = 0x02, 0x03, 0x22, 0x23
//   multi-die parts (KU085/KU115: 12-bit IR, USER1 = 0x0A4) and Zynq
//     UltraScale+ (12-bit IR, USER1 = 0x902) have longer codes
//
// The IR-to-USER mapping is handled inside BSCANE2 and is transparent
// to this wrapper.  The host's hw_server backend uses xsdb's register-IR
// mode on UltraScale(+) parts, which looks the instruction up per device;
// raw-opcode backends (OpenOCD, FTDI) need the part's codes in ir_table.
//
// Versal devices (XCVM, XCVC, XCVP, XCVE, XCVH) use a different TAP
// primitive (BSCANE2_INST or via the CIPS BlockRAM); they are NOT
// covered by this wrapper.

module jtag_tap_xilinxus #(
    parameter CHAIN = 1
) (
    output wire tck,
    output wire tdi,
    input  wire tdo,
    output wire capture,
    output wire shift,
    output wire update,
    output wire sel,
    // TAP in Test-Logic-Reset (level, TCK domain)
    output wire tlr
);

    // Direct shim — see file header for the rationale.  No code changes
    // here are appropriate unless AMD breaks BSCANE2 compatibility for a
    // future UltraScale revision.
    jtag_tap_xilinx7 #(.CHAIN(CHAIN)) u_tap (
        .tck(tck), .tdi(tdi), .tdo(tdo),
        .capture(capture), .shift(shift),
        .update(update), .sel(sel),
        .tlr(tlr)
    );

endmodule
