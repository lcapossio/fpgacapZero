// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Arty A7-100T top-level for fpgacapZero reference design.
// Probes a free-running 8-bit counter via the ELA wrapper.
//
// Single wrapper instantiation — all JTAG TAPs, register interface,
// and burst read engine are bundled inside fcapz_ela_xilinx7.

module arty_a7_top (
    input  wire       clk,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    localparam SAMPLE_W     = 8;
    localparam DEPTH        = 1024;
    localparam NUM_SEGMENTS = 4;

    reg [3:0] rst_pipe;
    wire rst;

    reg [SAMPLE_W-1:0] counter;

    // ---- Reset ----
    always @(posedge clk) begin
        rst_pipe <= {rst_pipe[2:0], btn[0]};
    end
    assign rst = rst_pipe[3];

    // ---- Counter (probe target) ----
    always @(posedge clk) begin
        if (rst)
            counter <= {SAMPLE_W{1'b0}};
        else
            counter <= counter + 1'b1;
    end
    wire trigger_out_w;
    assign led = {trigger_out_w, counter[2:0]};

    // ---- ELA (all features enabled for HW validation) ----
    fcapz_ela_xilinx7 #(
        .SAMPLE_W     (SAMPLE_W),
        .DEPTH        (DEPTH),
        .DECIM_EN     (1),
        .EXT_TRIG_EN  (1),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (NUM_SEGMENTS)
    ) u_ela (
        .sample_clk (clk),
        .sample_rst (rst),
        .probe_in   (counter),
        .trigger_in (btn[1]),         // btn[1] as external trigger
        .trigger_out(trigger_out_w)   // led[3] pulses on trigger
    );

    // ---- EJTAGAXI: JTAG-to-AXI4 bridge (USER4) ----
    // Bridges JTAG to AXI4 master, connected to a test slave for validation.

    wire [31:0] bridge_awaddr, bridge_wdata, bridge_araddr, bridge_rdata;
    wire [7:0]  bridge_awlen, bridge_arlen;
    wire [2:0]  bridge_awsize, bridge_arsize, bridge_awprot, bridge_arprot;
    wire [1:0]  bridge_awburst, bridge_arburst, bridge_bresp, bridge_rresp;
    wire [3:0]  bridge_wstrb;
    wire        bridge_awvalid, bridge_awready, bridge_wvalid, bridge_wready;
    wire        bridge_wlast, bridge_bvalid, bridge_bready;
    wire        bridge_arvalid, bridge_arready, bridge_rvalid, bridge_rready, bridge_rlast;

    fcapz_ejtagaxi_xilinx7 #(
        .ADDR_W(32), .DATA_W(32), .FIFO_DEPTH(16), .TIMEOUT(4096)
    ) u_ejtagaxi (
        .axi_clk(clk),
        .axi_rst(rst),
        .m_axi_awaddr(bridge_awaddr), .m_axi_awlen(bridge_awlen),
        .m_axi_awsize(bridge_awsize), .m_axi_awburst(bridge_awburst),
        .m_axi_awvalid(bridge_awvalid), .m_axi_awready(bridge_awready),
        .m_axi_awprot(bridge_awprot),
        .m_axi_wdata(bridge_wdata), .m_axi_wstrb(bridge_wstrb),
        .m_axi_wvalid(bridge_wvalid), .m_axi_wready(bridge_wready),
        .m_axi_wlast(bridge_wlast),
        .m_axi_bresp(bridge_bresp), .m_axi_bvalid(bridge_bvalid),
        .m_axi_bready(bridge_bready),
        .m_axi_araddr(bridge_araddr), .m_axi_arlen(bridge_arlen),
        .m_axi_arsize(bridge_arsize), .m_axi_arburst(bridge_arburst),
        .m_axi_arvalid(bridge_arvalid), .m_axi_arready(bridge_arready),
        .m_axi_arprot(bridge_arprot),
        .m_axi_rdata(bridge_rdata), .m_axi_rresp(bridge_rresp),
        .m_axi_rvalid(bridge_rvalid), .m_axi_rready(bridge_rready),
        .m_axi_rlast(bridge_rlast)
    );

    axi4_test_slave #(.NUM_WORDS(16), .ERROR_ADDR(32'hFFFF_FFFC)) u_axi_slave (
        .clk(clk), .rst(rst),
        .s_axi_awaddr(bridge_awaddr), .s_axi_awlen(bridge_awlen),
        .s_axi_awsize(bridge_awsize), .s_axi_awburst(bridge_awburst),
        .s_axi_awvalid(bridge_awvalid), .s_axi_awready(bridge_awready),
        .s_axi_wdata(bridge_wdata), .s_axi_wstrb(bridge_wstrb),
        .s_axi_wvalid(bridge_wvalid), .s_axi_wready(bridge_wready),
        .s_axi_wlast(bridge_wlast),
        .s_axi_bresp(bridge_bresp), .s_axi_bvalid(bridge_bvalid),
        .s_axi_bready(bridge_bready),
        .s_axi_araddr(bridge_araddr), .s_axi_arlen(bridge_arlen),
        .s_axi_arsize(bridge_arsize), .s_axi_arburst(bridge_arburst),
        .s_axi_arvalid(bridge_arvalid), .s_axi_arready(bridge_arready),
        .s_axi_rdata(bridge_rdata), .s_axi_rresp(bridge_rresp),
        .s_axi_rvalid(bridge_rvalid), .s_axi_rready(bridge_rready),
        .s_axi_rlast(bridge_rlast)
    );

    // ---- EIO: Embedded I/O (USER3) ----
    // Reads the counter as probe_in, drives 4 LEDs via probe_out.
    // EIO probe_out directly replaces the counter-driven LEDs when
    // written via JTAG, giving the host read/write access to fabric
    // signals for HW validation.

    wire [7:0] eio_probe_out;

    fcapz_eio_xilinx7 #(
        .IN_W  (8),     // 8-bit counter input
        .OUT_W (8),     // 8-bit output (directly visible)
        .CHAIN (3)
    ) u_eio (
        .probe_in  (counter),
        .probe_out (eio_probe_out)
    );

endmodule
