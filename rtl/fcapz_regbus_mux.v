// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Register bus address mux for shared-chain configurations.
//
// Splits a single jtag_reg_iface bus into two ports using addr[15]:
//   addr[15]=0 → port A (ELA)  — addresses 0x0000-0x7FFF
//   addr[15]=1 → port B (EIO)  — addresses 0x0000-0x7FFF (offset stripped)
//
// Used by ECP5 and Gowin wrappers where the number of JTAG user chains
// is too small to give ELA and EIO separate register interfaces.

module fcapz_regbus_mux (
    // Upstream (from jtag_reg_iface)
    input  wire [15:0] addr,
    input  wire        wr_en,
    input  wire        rd_en,
    input  wire [31:0] wdata,
    output wire [31:0] rdata,

    // Port A — ELA (addr[15]=0)
    output wire        a_wr_en,
    output wire        a_rd_en,
    output wire [15:0] a_addr,
    output wire [31:0] a_wdata,
    input  wire [31:0] a_rdata,

    // Port B — EIO (addr[15]=1)
    output wire        b_wr_en,
    output wire        b_rd_en,
    output wire [15:0] b_addr,
    output wire [31:0] b_wdata,
    input  wire [31:0] b_rdata
);

    wire sel_b = addr[15];

    assign a_wr_en = wr_en & ~sel_b;
    assign a_rd_en = rd_en & ~sel_b;
    assign a_addr  = addr;
    assign a_wdata = wdata;

    assign b_wr_en = wr_en &  sel_b;
    assign b_rd_en = rd_en &  sel_b;
    assign b_addr  = {1'b0, addr[14:0]};  // strip bit 15
    assign b_wdata = wdata;

    assign rdata = sel_b ? b_rdata : a_rdata;

endmodule
