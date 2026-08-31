// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// VexRiscv shared-bus subsystem for the Arty A7 fpgacapZero reference design.
//
// Drop-in analogue of mb_sys_wrapper: it presents the same Clk/reset plus an
// M_EJTAG AXI4 slave port (the EJTAG-AXI bridge master feeds it) and an M_BUS
// AXI4 master port (drives the shared test slave + AXI-monitor tap). Internally
// it wires the VexRiscv CPU (vex_cpu) and the EJTAG bridge onto a block-design
// SmartConnect (vex_bus) that merges both masters onto M_BUS -- exactly how the
// MicroBlaze subsystem merges microblaze_0's M_AXI_DP with the bridge, minus
// the proprietary CPU/LMB/MDM.
//
//   vex_cpu (M_CPU) ─┐
//                    ├─ SmartConnect (vex_bus) ─ M_BUS ─► test slave + monitor
//   EJTAG bridge  ───┘   (S00=M_CPU, S01=M_EJTAG, M00=M_BUS)
//        (M_EJTAG)

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

    // ---- SmartConnect block-design wrapper -----------------------------
    // aresetn is active-low; the CPU's AXI4 qualifier inputs the bridge does
    // not drive (awcache/awlock/awqos) are tied to sane defaults, mirroring how
    // arty_a7_top ties them on the M_EJTAG port.
    vex_bus_wrapper u_bus (
        .aclk         (Clk),
        .aresetn      (~reset),

        .M_CPU_awaddr (cpu_awaddr), .M_CPU_awlen  (cpu_awlen),
        .M_CPU_awsize (cpu_awsize), .M_CPU_awburst(cpu_awburst),
        .M_CPU_awprot (cpu_awprot), .M_CPU_awvalid(cpu_awvalid),
        .M_CPU_awready(cpu_awready),
        .M_CPU_awcache(4'b0011), .M_CPU_awlock(1'b0), .M_CPU_awqos(4'b0000),
        .M_CPU_wdata  (cpu_wdata), .M_CPU_wstrb (cpu_wstrb),
        .M_CPU_wlast  (cpu_wlast), .M_CPU_wvalid(cpu_wvalid),
        .M_CPU_wready (cpu_wready),
        .M_CPU_bresp  (cpu_bresp), .M_CPU_bvalid(cpu_bvalid),
        .M_CPU_bready (cpu_bready),
        .M_CPU_araddr (cpu_araddr), .M_CPU_arlen  (cpu_arlen),
        .M_CPU_arsize (cpu_arsize), .M_CPU_arburst(cpu_arburst),
        .M_CPU_arprot (cpu_arprot), .M_CPU_arvalid(cpu_arvalid),
        .M_CPU_arready(cpu_arready),
        .M_CPU_arcache(4'b0011), .M_CPU_arlock(1'b0), .M_CPU_arqos(4'b0000),
        .M_CPU_rdata  (cpu_rdata), .M_CPU_rresp (cpu_rresp),
        .M_CPU_rlast  (cpu_rlast), .M_CPU_rvalid(cpu_rvalid),
        .M_CPU_rready (cpu_rready),

        .M_EJTAG_awaddr (M_EJTAG_awaddr), .M_EJTAG_awlen  (M_EJTAG_awlen),
        .M_EJTAG_awsize (M_EJTAG_awsize), .M_EJTAG_awburst(M_EJTAG_awburst),
        .M_EJTAG_awprot (M_EJTAG_awprot), .M_EJTAG_awvalid(M_EJTAG_awvalid),
        .M_EJTAG_awready(M_EJTAG_awready),
        .M_EJTAG_awcache(M_EJTAG_awcache), .M_EJTAG_awlock(M_EJTAG_awlock),
        .M_EJTAG_awqos  (M_EJTAG_awqos),
        .M_EJTAG_wdata  (M_EJTAG_wdata), .M_EJTAG_wstrb (M_EJTAG_wstrb),
        .M_EJTAG_wlast  (M_EJTAG_wlast), .M_EJTAG_wvalid(M_EJTAG_wvalid),
        .M_EJTAG_wready (M_EJTAG_wready),
        .M_EJTAG_bresp  (M_EJTAG_bresp), .M_EJTAG_bvalid(M_EJTAG_bvalid),
        .M_EJTAG_bready (M_EJTAG_bready),
        .M_EJTAG_araddr (M_EJTAG_araddr), .M_EJTAG_arlen  (M_EJTAG_arlen),
        .M_EJTAG_arsize (M_EJTAG_arsize), .M_EJTAG_arburst(M_EJTAG_arburst),
        .M_EJTAG_arprot (M_EJTAG_arprot), .M_EJTAG_arvalid(M_EJTAG_arvalid),
        .M_EJTAG_arready(M_EJTAG_arready),
        .M_EJTAG_arcache(M_EJTAG_arcache), .M_EJTAG_arlock(M_EJTAG_arlock),
        .M_EJTAG_arqos  (M_EJTAG_arqos),
        .M_EJTAG_rdata  (M_EJTAG_rdata), .M_EJTAG_rresp (M_EJTAG_rresp),
        .M_EJTAG_rlast  (M_EJTAG_rlast), .M_EJTAG_rvalid(M_EJTAG_rvalid),
        .M_EJTAG_rready (M_EJTAG_rready),

        .M_BUS_awaddr (M_BUS_awaddr), .M_BUS_awlen  (M_BUS_awlen),
        .M_BUS_awsize (M_BUS_awsize), .M_BUS_awburst(M_BUS_awburst),
        .M_BUS_awprot (M_BUS_awprot), .M_BUS_awvalid(M_BUS_awvalid),
        .M_BUS_awready(M_BUS_awready),
        // Master-side AXI4 qualifier outputs are unused downstream (the test
        // slave and monitor ignore them), left open as arty_a7_top does.
        .M_BUS_awcache(), .M_BUS_awlock(), .M_BUS_awqos(),
        .M_BUS_wdata  (M_BUS_wdata), .M_BUS_wstrb (M_BUS_wstrb),
        .M_BUS_wlast  (M_BUS_wlast), .M_BUS_wvalid(M_BUS_wvalid),
        .M_BUS_wready (M_BUS_wready),
        .M_BUS_bresp  (M_BUS_bresp), .M_BUS_bvalid(M_BUS_bvalid),
        .M_BUS_bready (M_BUS_bready),
        .M_BUS_araddr (M_BUS_araddr), .M_BUS_arlen  (M_BUS_arlen),
        .M_BUS_arsize (M_BUS_arsize), .M_BUS_arburst(M_BUS_arburst),
        .M_BUS_arprot (M_BUS_arprot), .M_BUS_arvalid(M_BUS_arvalid),
        .M_BUS_arready(M_BUS_arready),
        .M_BUS_arcache(), .M_BUS_arlock(), .M_BUS_arqos(),
        .M_BUS_rdata  (M_BUS_rdata), .M_BUS_rresp (M_BUS_rresp),
        .M_BUS_rlast  (M_BUS_rlast), .M_BUS_rvalid(M_BUS_rvalid),
        .M_BUS_rready (M_BUS_rready)
    );

endmodule
