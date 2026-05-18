// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// JTAG to parallel register bus bridge (vendor-agnostic).
//
// TAP signals (tck, tdi, tdo, capture, shift, update, sel) are
// provided by an external vendor-specific TAP wrapper.
//
// 49-bit DR protocol (LSB-first on the wire):
//   bits[31:0]  = wdata / rdata
//   bits[47:32] = addr[15:0]
//   bits[48]    = rnw (1 = write, 0 = read)

module jtag_reg_iface (
    input  wire        arst,

    // TAP signals (from vendor-specific wrapper)
    input  wire        tck,
    input  wire        tdi,
    output wire        tdo,
    input  wire        capture,
    input  wire        shift_en,
    input  wire        update,
    input  wire        sel,

    // Register bus
    output wire        reg_clk,
    output wire        reg_rst,
    output reg         reg_wr_en,
    output reg         reg_rd_en,
    output reg  [15:0] reg_addr,
    output reg  [31:0] reg_wdata,
    input  wire [31:0] reg_rdata
);

    reg [48:0] sr;

    assign tdo     = sr[0];
    assign reg_clk = tck;
    assign reg_rst = arst;

    always @(posedge tck) begin
        if (arst == 1'b1) begin
            sr <= 49'h0;
            reg_wr_en <= 1'b0;
            reg_rd_en <= 1'b0;
            reg_addr <= 16'h0;
            reg_wdata <= 32'h0;
        end else begin
            reg_wr_en <= 1'b0;
            reg_rd_en <= 1'b0;

            if (sel) begin
                if (capture) begin
                    sr[31:0] <= reg_rdata;
                end else if (shift_en) begin
                    sr <= {tdi, sr[48:1]};
                end else if (update) begin
                    if (sr[48]) begin
                        reg_addr <= sr[47:32];
                        reg_wdata <= sr[31:0];
                        reg_wr_en <= 1'b1;
                    end else begin
                        reg_addr <= sr[47:32];
                        reg_rd_en <= 1'b1;
                    end
                end
            end
        end
    end

endmodule
