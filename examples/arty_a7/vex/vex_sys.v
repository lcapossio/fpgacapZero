// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// VexRiscv shared-bus subsystem for the Arty A7 fpgacapZero reference design.
//
// Drop-in analogue of mb_sys_wrapper: it presents the same Clk/reset plus an
// M_EJTAG AXI4 slave port (the EJTAG-AXI bridge master feeds it) and an M_BUS
// AXI4 master port (drives the shared test slave + AXI-monitor tap). Internally
// it wires the VexRiscv CPU (vex_cpu) and the EJTAG bridge onto the vendor-
// neutral fcapz_axi_interconnect (axiZero-generated 2x1 full-AXI4 crossbar)
// that merges both masters onto M_BUS -- the same shared-bus merge the
// MicroBlaze subsystem gets from a SmartConnect, but as portable RTL so the
// DE25-Nano can reuse the identical interconnect.
//
//   vex_cpu (s0) ─┐
//                 ├─ fcapz_axi_interconnect ─ M_BUS (m0) ─► test slave + monitor
//   EJTAG bridge ─┘   (s0=CPU, s1=M_EJTAG, m0=M_BUS)
//     (M_EJTAG, s1)
//
// The interconnect uses a single global slave map covering the whole 4 GiB, so
// (unlike the SmartConnect per-master remap) the CPU's 0x4000_0000 traffic and
// the host's addresses reach the test slave unmodified; axi4_test_slave aliases
// by address-modulo, so both land on the same register words as before.

module vex_sys (
    input  wire        Clk,
    input  wire        reset,             // active-high

    // ---- M_EJTAG: AXI4 slave (EJTAG-AXI bridge master drives this) -----
    input  wire [31:0] M_EJTAG_awaddr,
    input  wire [7:0]  M_EJTAG_awlen,
    input  wire [2:0]  M_EJTAG_awsize,
    input  wire [1:0]  M_EJTAG_awburst,
    input  wire [2:0]  M_EJTAG_awprot,
    input  wire        M_EJTAG_awvalid,
    output wire        M_EJTAG_awready,
    input  wire [3:0]  M_EJTAG_awcache,
    input  wire        M_EJTAG_awlock,
    input  wire [3:0]  M_EJTAG_awqos,
    input  wire [31:0] M_EJTAG_wdata,
    input  wire [3:0]  M_EJTAG_wstrb,
    input  wire        M_EJTAG_wlast,
    input  wire        M_EJTAG_wvalid,
    output wire        M_EJTAG_wready,
    output wire [1:0]  M_EJTAG_bresp,
    output wire        M_EJTAG_bvalid,
    input  wire        M_EJTAG_bready,
    input  wire [31:0] M_EJTAG_araddr,
    input  wire [7:0]  M_EJTAG_arlen,
    input  wire [2:0]  M_EJTAG_arsize,
    input  wire [1:0]  M_EJTAG_arburst,
    input  wire [2:0]  M_EJTAG_arprot,
    input  wire        M_EJTAG_arvalid,
    output wire        M_EJTAG_arready,
    input  wire [3:0]  M_EJTAG_arcache,
    input  wire        M_EJTAG_arlock,
    input  wire [3:0]  M_EJTAG_arqos,
    output wire [31:0] M_EJTAG_rdata,
    output wire [1:0]  M_EJTAG_rresp,
    output wire        M_EJTAG_rlast,
    output wire        M_EJTAG_rvalid,
    input  wire        M_EJTAG_rready,

    // ---- M_BUS: AXI4 master (test slave + AXI-monitor tap) -------------
    output wire [31:0] M_BUS_awaddr,
    output wire [7:0]  M_BUS_awlen,
    output wire [2:0]  M_BUS_awsize,
    output wire [1:0]  M_BUS_awburst,
    output wire [2:0]  M_BUS_awprot,
    output wire        M_BUS_awvalid,
    input  wire        M_BUS_awready,
    output wire [31:0] M_BUS_wdata,
    output wire [3:0]  M_BUS_wstrb,
    output wire        M_BUS_wlast,
    output wire        M_BUS_wvalid,
    input  wire        M_BUS_wready,
    input  wire [1:0]  M_BUS_bresp,
    input  wire        M_BUS_bvalid,
    output wire        M_BUS_bready,
    output wire [31:0] M_BUS_araddr,
    output wire [7:0]  M_BUS_arlen,
    output wire [2:0]  M_BUS_arsize,
    output wire [1:0]  M_BUS_arburst,
    output wire [2:0]  M_BUS_arprot,
    output wire        M_BUS_arvalid,
    input  wire        M_BUS_arready,
    input  wire [31:0] M_BUS_rdata,
    input  wire [1:0]  M_BUS_rresp,
    input  wire        M_BUS_rlast,
    input  wire        M_BUS_rvalid,
    output wire        M_BUS_rready
);

    // ---- CPU AXI4 master (single-beat) -> SmartConnect S00 (M_CPU) -----
    wire [31:0] cpu_awaddr, cpu_wdata, cpu_araddr, cpu_rdata;
    wire [7:0]  cpu_awlen, cpu_arlen;
    wire [2:0]  cpu_awsize, cpu_arsize, cpu_awprot, cpu_arprot;
    wire [1:0]  cpu_awburst, cpu_arburst, cpu_bresp, cpu_rresp;
    wire [3:0]  cpu_wstrb;
    wire        cpu_awvalid, cpu_awready, cpu_wvalid, cpu_wready, cpu_wlast;
    wire        cpu_bvalid, cpu_bready;
    wire        cpu_arvalid, cpu_arready, cpu_rvalid, cpu_rready, cpu_rlast;

    vex_cpu u_cpu (
        .clk          (Clk),
        .rst          (reset),
        .m_axi_awaddr (cpu_awaddr), .m_axi_awlen  (cpu_awlen),
        .m_axi_awsize (cpu_awsize), .m_axi_awburst(cpu_awburst),
        .m_axi_awprot (cpu_awprot), .m_axi_awvalid(cpu_awvalid),
        .m_axi_awready(cpu_awready),
        .m_axi_wdata  (cpu_wdata), .m_axi_wstrb (cpu_wstrb),
        .m_axi_wlast  (cpu_wlast), .m_axi_wvalid(cpu_wvalid),
        .m_axi_wready (cpu_wready),
        .m_axi_bresp  (cpu_bresp), .m_axi_bvalid(cpu_bvalid),
        .m_axi_bready (cpu_bready),
        .m_axi_araddr (cpu_araddr), .m_axi_arlen  (cpu_arlen),
        .m_axi_arsize (cpu_arsize), .m_axi_arburst(cpu_arburst),
        .m_axi_arprot (cpu_arprot), .m_axi_arvalid(cpu_arvalid),
        .m_axi_arready(cpu_arready),
        .m_axi_rdata  (cpu_rdata), .m_axi_rresp (cpu_rresp),
        .m_axi_rlast  (cpu_rlast), .m_axi_rvalid(cpu_rvalid),
        .m_axi_rready (cpu_rready)
    );

    // ---- Vendor-neutral AXI4 interconnect ------------------------------
    // s0 = VexRiscv CPU, s1 = EJTAG-AXI bridge (M_EJTAG), m0 = shared M_BUS.
    // aresetn is active-low. The masters do not drive awid/arid/awregion/
    // arregion (single-ID masters) so those are tied off; the CPU's AXI4
    // qualifier inputs (awcache/awlock/awqos) get the same sane defaults the
    // SmartConnect build used, while the bridge forwards its own. m0's ID and
    // qualifier outputs are unused downstream (the test slave/monitor ignore
    // them) and left open; bid/rid inputs are tied off because response routing
    // is by internal grant tracking (maxOutstanding=1 blocking), not slave IDs.
    fcapz_axi_interconnect u_bus (
        .aclk    (Clk),
        .aresetn (~reset),

        // ---- s0: VexRiscv CPU master ----
        .s0_axi_awvalid(cpu_awvalid), .s0_axi_awready(cpu_awready),
        .s0_axi_awaddr (cpu_awaddr), .s0_axi_awid(4'd0), .s0_axi_awregion(4'd0),
        .s0_axi_awlen  (cpu_awlen), .s0_axi_awsize(cpu_awsize), .s0_axi_awburst(cpu_awburst),
        .s0_axi_awlock (1'b0), .s0_axi_awcache(4'b0011), .s0_axi_awqos(4'b0000),
        .s0_axi_awprot (cpu_awprot),
        .s0_axi_wvalid (cpu_wvalid), .s0_axi_wready(cpu_wready),
        .s0_axi_wdata  (cpu_wdata), .s0_axi_wstrb(cpu_wstrb), .s0_axi_wlast(cpu_wlast),
        .s0_axi_bvalid (cpu_bvalid), .s0_axi_bready(cpu_bready),
        .s0_axi_bid    (), .s0_axi_bresp(cpu_bresp),
        .s0_axi_arvalid(cpu_arvalid), .s0_axi_arready(cpu_arready),
        .s0_axi_araddr (cpu_araddr), .s0_axi_arid(4'd0), .s0_axi_arregion(4'd0),
        .s0_axi_arlen  (cpu_arlen), .s0_axi_arsize(cpu_arsize), .s0_axi_arburst(cpu_arburst),
        .s0_axi_arlock (1'b0), .s0_axi_arcache(4'b0011), .s0_axi_arqos(4'b0000),
        .s0_axi_arprot (cpu_arprot),
        .s0_axi_rvalid (cpu_rvalid), .s0_axi_rready(cpu_rready),
        .s0_axi_rdata  (cpu_rdata), .s0_axi_rid(), .s0_axi_rresp(cpu_rresp), .s0_axi_rlast(cpu_rlast),

        // ---- s1: EJTAG-AXI bridge master (M_EJTAG) ----
        .s1_axi_awvalid(M_EJTAG_awvalid), .s1_axi_awready(M_EJTAG_awready),
        .s1_axi_awaddr (M_EJTAG_awaddr), .s1_axi_awid(4'd0), .s1_axi_awregion(4'd0),
        .s1_axi_awlen  (M_EJTAG_awlen), .s1_axi_awsize(M_EJTAG_awsize), .s1_axi_awburst(M_EJTAG_awburst),
        .s1_axi_awlock (M_EJTAG_awlock), .s1_axi_awcache(M_EJTAG_awcache), .s1_axi_awqos(M_EJTAG_awqos),
        .s1_axi_awprot (M_EJTAG_awprot),
        .s1_axi_wvalid (M_EJTAG_wvalid), .s1_axi_wready(M_EJTAG_wready),
        .s1_axi_wdata  (M_EJTAG_wdata), .s1_axi_wstrb(M_EJTAG_wstrb), .s1_axi_wlast(M_EJTAG_wlast),
        .s1_axi_bvalid (M_EJTAG_bvalid), .s1_axi_bready(M_EJTAG_bready),
        .s1_axi_bid    (), .s1_axi_bresp(M_EJTAG_bresp),
        .s1_axi_arvalid(M_EJTAG_arvalid), .s1_axi_arready(M_EJTAG_arready),
        .s1_axi_araddr (M_EJTAG_araddr), .s1_axi_arid(4'd0), .s1_axi_arregion(4'd0),
        .s1_axi_arlen  (M_EJTAG_arlen), .s1_axi_arsize(M_EJTAG_arsize), .s1_axi_arburst(M_EJTAG_arburst),
        .s1_axi_arlock (M_EJTAG_arlock), .s1_axi_arcache(M_EJTAG_arcache), .s1_axi_arqos(M_EJTAG_arqos),
        .s1_axi_arprot (M_EJTAG_arprot),
        .s1_axi_rvalid (M_EJTAG_rvalid), .s1_axi_rready(M_EJTAG_rready),
        .s1_axi_rdata  (M_EJTAG_rdata), .s1_axi_rid(), .s1_axi_rresp(M_EJTAG_rresp), .s1_axi_rlast(M_EJTAG_rlast),

        // ---- m0: shared bus master (M_BUS) -> test slave + monitor tap ----
        .m0_axi_awvalid(M_BUS_awvalid), .m0_axi_awready(M_BUS_awready),
        .m0_axi_awaddr (M_BUS_awaddr), .m0_axi_awid(), .m0_axi_awregion(),
        .m0_axi_awlen  (M_BUS_awlen), .m0_axi_awsize(M_BUS_awsize), .m0_axi_awburst(M_BUS_awburst),
        .m0_axi_awlock (), .m0_axi_awcache(), .m0_axi_awqos(), .m0_axi_awprot(M_BUS_awprot),
        .m0_axi_wvalid (M_BUS_wvalid), .m0_axi_wready(M_BUS_wready),
        .m0_axi_wdata  (M_BUS_wdata), .m0_axi_wstrb(M_BUS_wstrb), .m0_axi_wlast(M_BUS_wlast),
        .m0_axi_bvalid (M_BUS_bvalid), .m0_axi_bready(M_BUS_bready),
        .m0_axi_bid    (5'd0), .m0_axi_bresp(M_BUS_bresp),
        .m0_axi_arvalid(M_BUS_arvalid), .m0_axi_arready(M_BUS_arready),
        .m0_axi_araddr (M_BUS_araddr), .m0_axi_arid(), .m0_axi_arregion(),
        .m0_axi_arlen  (M_BUS_arlen), .m0_axi_arsize(M_BUS_arsize), .m0_axi_arburst(M_BUS_arburst),
        .m0_axi_arlock (), .m0_axi_arcache(), .m0_axi_arqos(), .m0_axi_arprot(M_BUS_arprot),
        .m0_axi_rvalid (M_BUS_rvalid), .m0_axi_rready(M_BUS_rready),
        .m0_axi_rdata  (M_BUS_rdata), .m0_axi_rid(5'd0), .m0_axi_rresp(M_BUS_rresp), .m0_axi_rlast(M_BUS_rlast)
    );

endmodule
