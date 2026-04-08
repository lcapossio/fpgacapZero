// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero JTAG-to-AXI4 bridge wrapper for Xilinx UltraScale /
// UltraScale+.
//
// Thin shim over fcapz_ejtagaxi_xilinx7 -- BSCANE2 is the same
// primitive on 7-series, UltraScale, and UltraScale+, so there is no
// point in duplicating the wrapper internals.  See jtag_tap_xilinxus.v
// for the list of confirmed device families.
//
// Usage:
//   fcapz_ejtagaxi_xilinxus #(.ADDR_W(32), .DATA_W(32)) u_axi (
//       .axi_clk(clk), .axi_rst(rst),
//       .m_axi_awaddr(awaddr), /* ... remaining AXI signals ... */
//   );

module fcapz_ejtagaxi_xilinxus #(
    parameter ADDR_W     = 32,
    parameter DATA_W     = 32,
    parameter FIFO_DEPTH = 16,
    parameter TIMEOUT    = 4096,
    parameter CHAIN      = 4
) (
    // AXI4 master interface
    input  wire                    axi_clk,
    input  wire                    axi_rst,
    // Write address
    output wire [ADDR_W-1:0]      m_axi_awaddr,
    output wire [7:0]             m_axi_awlen,
    output wire [2:0]             m_axi_awsize,
    output wire [1:0]             m_axi_awburst,
    output wire                   m_axi_awvalid,
    input  wire                   m_axi_awready,
    output wire [2:0]             m_axi_awprot,
    // Write data
    output wire [DATA_W-1:0]     m_axi_wdata,
    output wire [DATA_W/8-1:0]   m_axi_wstrb,
    output wire                   m_axi_wvalid,
    input  wire                   m_axi_wready,
    output wire                   m_axi_wlast,
    // Write response
    input  wire [1:0]             m_axi_bresp,
    input  wire                   m_axi_bvalid,
    output wire                   m_axi_bready,
    // Read address
    output wire [ADDR_W-1:0]     m_axi_araddr,
    output wire [7:0]            m_axi_arlen,
    output wire [2:0]            m_axi_arsize,
    output wire [1:0]            m_axi_arburst,
    output wire                   m_axi_arvalid,
    input  wire                   m_axi_arready,
    output wire [2:0]             m_axi_arprot,
    // Read data
    input  wire [DATA_W-1:0]     m_axi_rdata,
    input  wire [1:0]            m_axi_rresp,
    input  wire                   m_axi_rvalid,
    input  wire                   m_axi_rlast,
    output wire                   m_axi_rready
);

    fcapz_ejtagaxi_xilinx7 #(
        .ADDR_W(ADDR_W), .DATA_W(DATA_W),
        .FIFO_DEPTH(FIFO_DEPTH), .TIMEOUT(TIMEOUT),
        .CHAIN(CHAIN)
    ) u_inner (
        .axi_clk(axi_clk), .axi_rst(axi_rst),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize), .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_bresp(m_axi_bresp), .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_araddr(m_axi_araddr), .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize), .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rvalid(m_axi_rvalid), .m_axi_rlast(m_axi_rlast),
        .m_axi_rready(m_axi_rready)
    );

endmodule
