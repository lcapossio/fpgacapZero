// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Project-wide version + per-core identity defines.  AUTO-generated from
// the canonical VERSION file at the repo root by tools/sync_version.py.
`include "fcapz_version.vh"

// Embedded I/O core — JTAG-accessible input/output probes.
//
// Parameters:
//   IN_W   - input probe width  (fabric → host, read-only from host)
//   OUT_W  - output probe width (host  → fabric, writable from host)
//
// Uses USER3 (CHAIN=3) so it coexists with the ELA core that uses
// USER1 (registers) and USER2 (burst read).
//
// Clock domains:
//   probe_in  lives in the fabric clock domain.  It is synchronised into
//             jtag_clk via 2-FF sync before the host reads it.
//   probe_out lives in jtag_clk.  For use in fast fabric logic, add a
//             synchroniser stage after instantiation.
//
// Register map (49-bit DR, same protocol as jtag_reg_iface):
//   0x0000  VERSION   (R)  {major[7:0], minor[7:0], core_id[15:0]="IO"=0x494F}
//                          Hosts must verify VERSION[15:0] == 0x494F before
//                          touching any other EIO register on this chain.
//   0x0004  EIO_IN_W  (R)  IN_W
//   0x0008  EIO_OUT_W (R)  OUT_W
//   0x0010  IN[0]     (R)  probe_in[31:0]   (synced to jtag_clk)
//   0x0014  IN[1]     (R)  probe_in[63:32]
//   ...     (IN_WORDS * 4 bytes)
//   0x0100  OUT[0]    (RW) probe_out[31:0]
//   0x0104  OUT[1]    (RW) probe_out[63:32]
//   ...     (OUT_WORDS * 4 bytes)

module fcapz_eio #(
    parameter IN_W  = 32,
    parameter OUT_W = 32
) (
    // Fabric-side probes
    input  wire [IN_W-1:0]  probe_in,    // signals to observe (any clock domain)
    output wire [OUT_W-1:0] probe_out,   // signals to drive   (jtag_clk domain)

    // JTAG register bus (jtag_clk domain, from jtag_reg_iface)
    input  wire        jtag_clk,
    input  wire        jtag_rst,
    input  wire        jtag_wr_en,
    input  wire [15:0] jtag_addr,
    input  wire [31:0] jtag_wdata,
    output reg  [31:0] jtag_rdata
);

    localparam IN_WORDS  = (IN_W  + 31) / 32;
    localparam OUT_WORDS = (OUT_W + 31) / 32;

    // Pad probe_in to a multiple of 32 bits for clean word extraction
    localparam IN_PAD  = IN_WORDS  * 32;
    localparam OUT_PAD = OUT_WORDS * 32;

    localparam ADDR_VERSION  = 16'h0000;
    localparam ADDR_IN_W     = 16'h0004;
    localparam ADDR_OUT_W    = 16'h0008;
    localparam ADDR_IN_BASE  = 16'h0010;
    localparam ADDR_OUT_BASE = 16'h0100;

    // ---- Output registers (jtag_clk) ----------------------------------------
    reg [OUT_PAD-1:0] out_regs;

    assign probe_out = out_regs[OUT_W-1:0];

    always @(posedge jtag_clk or posedge jtag_rst) begin : p_out_regs
        integer i;
        if (jtag_rst) begin
            out_regs <= {OUT_PAD{1'b0}};
        end else if (jtag_wr_en &&
                     jtag_addr >= ADDR_OUT_BASE &&
                     jtag_addr <  ADDR_OUT_BASE + OUT_WORDS * 4) begin
            i = (jtag_addr - ADDR_OUT_BASE) >> 2;
            out_regs[i*32 +: 32] <= jtag_wdata;
        end
    end

    // ---- Input CDC (2-stage synchroniser into jtag_clk) --------------------
    // Whole-bus sync — for a debug tool this is acceptable.
    (* ASYNC_REG = "TRUE" *) reg [IN_PAD-1:0] in_sync1;
    (* ASYNC_REG = "TRUE" *) reg [IN_PAD-1:0] in_sync2;

    wire [IN_PAD-1:0] probe_in_pad = {{(IN_PAD-IN_W){1'b0}}, probe_in};

    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            in_sync1 <= {IN_PAD{1'b0}};
            in_sync2 <= {IN_PAD{1'b0}};
        end else begin
            in_sync1 <= probe_in_pad;
            in_sync2 <= in_sync1;
        end
    end

    // ---- Register read mux --------------------------------------------------
    always @(*) begin : p_rdata
        integer i;
        jtag_rdata = 32'h0;
        if (jtag_addr == ADDR_VERSION) begin
            // {major[7:0], minor[7:0], core_id[15:0]="IO"=0x494F}, generated
            // from rtl/fcapz_version.vh by tools/sync_version.py
            jtag_rdata = `FCAPZ_EIO_VERSION_REG;
        end else if (jtag_addr == ADDR_IN_W) begin
            jtag_rdata = IN_W;
        end else if (jtag_addr == ADDR_OUT_W) begin
            jtag_rdata = OUT_W;
        end else if (jtag_addr >= ADDR_IN_BASE &&
                     jtag_addr <  ADDR_IN_BASE + IN_WORDS * 4) begin
            i = (jtag_addr - ADDR_IN_BASE) >> 2;
            jtag_rdata = in_sync2[i*32 +: 32];
        end else if (jtag_addr >= ADDR_OUT_BASE &&
                     jtag_addr <  ADDR_OUT_BASE + OUT_WORDS * 4) begin
            i = (jtag_addr - ADDR_OUT_BASE) >> 2;
            jtag_rdata = out_regs[i*32 +: 32];
        end
    end

endmodule
