// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// DE25-Nano core-manager variant of the fpgacapZero Intel/Altera example.
//
// One fcapz_debug_multi_intel hub on sld_virtual_jtag instance 1 serves four
// managed slots through a single virtual JTAG node:
//   slot 0  ELA0: free-running up counter (counter_a)
//   slot 1  ELA1: second up counter, XORed with 8'hA5 (counter_b ^ 8'hA5)
//   slot 2  EIO0: in = {SW, slow_counter}, out drives LEDR
//   slot 3  EIO1: in = {counter_b[3:0], 2'b00, ~KEY}, out is readback only
// Both ELAs carry timestamps and four segments, so their bursts go through the
// hub's single-chain readback. The EJTAG-AXI bridge on instance 4 sits beside
// the hub on its own node and drives an axi4_test_slave directly, so the host
// sees a manager and an ordinary core on the same cable.
//
// This mirrors the Arty A7 USER1 hub (fcapz_debug_multi_xilinx7): the same
// vendor-free fcapz_debug_multi layers, with only the TAP shell swapped.
// Unlike the Arty, the hub sets TLR_RESET_EN: quartus_stp keeps the TAP out
// of Test-Logic-Reset during a session, so a Test-Logic-Reset here means a
// new session, and it cancels any burst the last one left open.

module de25_nano_manager_top (
    input  wire       CLOCK1_50,
    input  wire [1:0] KEY,
    input  wire [3:0] SW,
    output wire [7:0] LEDR
);

    localparam SAMPLE_W = 8;
    localparam DEPTH = 1024;

    reg [7:0] por_count = 8'hFF;
    wire por_rst = |por_count;
    reg [SAMPLE_W-1:0] counter_a = {SAMPLE_W{1'b0}};
    reg [SAMPLE_W-1:0] counter_b = 8'h5A;
    reg [25:0] slow_div = 26'd0;
    reg [3:0] slow_counter = 4'd0;

    wire [7:0] eio0_probe_in;
    wire [7:0] eio0_probe_out;
    wire [7:0] eio1_probe_in;
    wire [7:0] eio1_probe_out;
    wire [1:0] ela_trigger_out_unused;
    wire [1:0] ela_armed_unused;

    always @(posedge CLOCK1_50) begin
        if (por_count != 8'h00)
            por_count <= por_count - 1'b1;

        if (por_rst) begin
            counter_a <= {SAMPLE_W{1'b0}};
            counter_b <= 8'h5A;
            slow_div <= 26'd0;
            slow_counter <= 4'd0;
        end else begin
            counter_a <= counter_a + 1'b1;
            counter_b <= counter_b + 1'b1;
            // 1 Hz nibble so the host can watch an EIO input advance.
            if (slow_div == 26'd49_999_999) begin
                slow_div <= 26'd0;
                slow_counter <= slow_counter + 1'b1;
            end else begin
                slow_div <= slow_div + 1'b1;
            end
        end
    end

    assign eio0_probe_in = {SW, slow_counter};
    assign eio1_probe_in = {counter_b[3:0], 2'b00, ~KEY};
    assign LEDR = eio0_probe_out;

    fcapz_debug_multi_intel #(
        .NUM_ELAS     (2),
        .EIO_EN       (1),
        .NUM_EIOS     (2),
        .SAMPLE_W     (SAMPLE_W),
        .DEPTH        (DEPTH),
        .INPUT_PIPE   (1),
        .DECIM_EN     (1),
        .EXT_TRIG_EN  (1),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (4),
        .STARTUP_ARM  (1),
        .DEFAULT_TRIG_EXT(2),
        .CTRL_CHAIN   (1),
        .EIO_IN_W     (8),
        .EIO_OUT_W    (8),
        .TLR_RESET_EN (1)
    ) u_debug (
        .ela_sample_clk ({CLOCK1_50, CLOCK1_50}),
        .ela_sample_rst ({por_rst, por_rst}),
        .ela_probe_in   ({counter_b ^ 8'hA5, counter_a}),
        .ela_trigger_in (2'b00),
        .ela_trigger_out(ela_trigger_out_unused),
        .ela_armed_out  (ela_armed_unused),
        .eio_probe_in   ({eio1_probe_in, eio0_probe_in}),
        .eio_probe_out  ({eio1_probe_out, eio0_probe_out})
    );

    wire [31:0] bridge_awaddr;
    wire [31:0] bridge_wdata;
    wire [31:0] bridge_araddr;
    wire [31:0] bridge_rdata;
    wire [7:0]  bridge_awlen;
    wire [7:0]  bridge_arlen;
    wire [2:0]  bridge_awsize;
    wire [2:0]  bridge_arsize;
    wire [2:0]  bridge_awprot_unused;
    wire [2:0]  bridge_arprot_unused;
    wire [1:0]  bridge_awburst;
    wire [1:0]  bridge_arburst;
    wire [1:0]  bridge_bresp;
    wire [1:0]  bridge_rresp;
    wire [3:0]  bridge_wstrb;
    wire        bridge_awvalid;
    wire        bridge_awready;
    wire        bridge_wvalid;
    wire        bridge_wready;
    wire        bridge_wlast;
    wire        bridge_bvalid;
    wire        bridge_bready;
    wire        bridge_arvalid;
    wire        bridge_arready;
    wire        bridge_rvalid;
    wire        bridge_rready;
    wire        bridge_rlast;
    wire [255:0] debug_tck_unused;
    wire [255:0] debug_tck_edge_unused;
    wire [255:0] debug_axi_unused;
    wire [255:0] debug_axi_edge_unused;

    fcapz_ejtagaxi_intel #(
        .ADDR_W(32),
        .DATA_W(32),
        .FIFO_DEPTH(16),
        .CMD_FIFO_DEPTH(16),
        .RESP_FIFO_DEPTH(16),
        .CMD_FIFO_MEMORY_TYPE("distributed"),
        .TIMEOUT(4096),
        .DEBUG_EN(0),
        .ASYNC_FIFO_IMPL(0),
        .CHAIN(4)
    ) u_ejtagaxi (
        .axi_clk(CLOCK1_50),
        .axi_rst(por_rst),
        .m_axi_awaddr(bridge_awaddr),
        .m_axi_awlen(bridge_awlen),
        .m_axi_awsize(bridge_awsize),
        .m_axi_awburst(bridge_awburst),
        .m_axi_awvalid(bridge_awvalid),
        .m_axi_awready(bridge_awready),
        .m_axi_awprot(bridge_awprot_unused),
        .m_axi_wdata(bridge_wdata),
        .m_axi_wstrb(bridge_wstrb),
        .m_axi_wvalid(bridge_wvalid),
        .m_axi_wready(bridge_wready),
        .m_axi_wlast(bridge_wlast),
        .m_axi_bresp(bridge_bresp),
        .m_axi_bvalid(bridge_bvalid),
        .m_axi_bready(bridge_bready),
        .m_axi_araddr(bridge_araddr),
        .m_axi_arlen(bridge_arlen),
        .m_axi_arsize(bridge_arsize),
        .m_axi_arburst(bridge_arburst),
        .m_axi_arvalid(bridge_arvalid),
        .m_axi_arready(bridge_arready),
        .m_axi_arprot(bridge_arprot_unused),
        .m_axi_rdata(bridge_rdata),
        .m_axi_rresp(bridge_rresp),
        .m_axi_rvalid(bridge_rvalid),
        .m_axi_rlast(bridge_rlast),
        .m_axi_rready(bridge_rready),
        .debug_tck(debug_tck_unused),
        .debug_tck_edge(debug_tck_edge_unused),
        .debug_axi(debug_axi_unused),
        .debug_axi_edge(debug_axi_edge_unused)
    );

    axi4_test_slave #(.NUM_WORDS(16), .ERROR_ADDR(32'hFFFF_FFFC), .HANG_EN(0)) u_axi_slave (
        .clk(CLOCK1_50),
        .rst(por_rst),
        .s_axi_awaddr(bridge_awaddr),
        .s_axi_awlen(bridge_awlen),
        .s_axi_awsize(bridge_awsize),
        .s_axi_awburst(bridge_awburst),
        .s_axi_awvalid(bridge_awvalid),
        .s_axi_awready(bridge_awready),
        .s_axi_wdata(bridge_wdata),
        .s_axi_wstrb(bridge_wstrb),
        .s_axi_wlast(bridge_wlast),
        .s_axi_wvalid(bridge_wvalid),
        .s_axi_wready(bridge_wready),
        .s_axi_bresp(bridge_bresp),
        .s_axi_bvalid(bridge_bvalid),
        .s_axi_bready(bridge_bready),
        .s_axi_araddr(bridge_araddr),
        .s_axi_arlen(bridge_arlen),
        .s_axi_arsize(bridge_arsize),
        .s_axi_arburst(bridge_arburst),
        .s_axi_arvalid(bridge_arvalid),
        .s_axi_arready(bridge_arready),
        .s_axi_rdata(bridge_rdata),
        .s_axi_rresp(bridge_rresp),
        .s_axi_rlast(bridge_rlast),
        .s_axi_rvalid(bridge_rvalid),
        .s_axi_rready(bridge_rready)
    );

endmodule
