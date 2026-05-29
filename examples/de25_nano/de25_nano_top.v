// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// DE25-Nano hardware-validation top-level for fpgacapZero Intel/Altera
// USB-Blaster transport.
//
// The design is self-stimulating:
// - ELA on sld_virtual_jtag instance 1 captures an 8-bit 50 MHz counter.
// - ELA burst readout uses sld_virtual_jtag instance 2.
// - EIO on sld_virtual_jtag instance 3 exposes switches/buttons/counter bits,
//   drives the eight active-low user LEDs, and feeds the ELA external trigger.
// - EJTAG-AXI on sld_virtual_jtag instance 4 connects to axi4_test_slave.

module de25_nano_top (
    input  wire       CLOCK1_50,
    input  wire [1:0] KEY,
    input  wire [3:0] SW,
    output wire [7:0] LEDR
);

    localparam SAMPLE_W = 8;
    localparam DEPTH = 1024;

    reg [7:0] por_count = 8'hFF;
    wire por_rst = |por_count;
    reg [SAMPLE_W-1:0] counter = {SAMPLE_W{1'b0}};
    reg [25:0] heartbeat_div = 26'd0;
    reg heartbeat = 1'b0;
    wire [7:0] eio_probe_in;
    wire [7:0] eio_probe_out;
    wire trigger_out_unused;
    wire ela_armed;
    reg [7:0] eio_out_sync1 = 8'h00;
    reg [7:0] eio_out_sync2 = 8'h00;
    reg ela_armed_d = 1'b0;
    reg [3:0] armed_test_count = 4'd0;
    reg armed_test_active = 1'b0;
    reg armed_test_pulse = 1'b0;
    reg armed_test_gate = 1'b0;
    wire ela_fresh_arm_w;
    wire trigger_in_w;

    wire [31:0] bridge_awaddr;
    wire [31:0] bridge_wdata;
    wire [31:0] bridge_araddr;
    wire [31:0] bridge_rdata;
    wire [7:0]  bridge_awlen;
    wire [7:0]  bridge_arlen;
    wire [2:0]  bridge_awsize;
    wire [2:0]  bridge_arsize;
    wire [2:0]  bridge_awprot;
    wire [2:0]  bridge_arprot;
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

    always @(posedge CLOCK1_50) begin
        if (por_rst) begin
            por_count <= por_count - 1'b1;
            counter <= {SAMPLE_W{1'b0}};
            heartbeat_div <= 26'd0;
            heartbeat <= 1'b0;
            eio_out_sync1 <= 8'h00;
            eio_out_sync2 <= 8'h00;
            ela_armed_d <= 1'b0;
            armed_test_count <= 4'd0;
            armed_test_active <= 1'b0;
            armed_test_pulse <= 1'b0;
            armed_test_gate <= 1'b0;
        end else begin
            counter <= counter + 1'b1;
            eio_out_sync1 <= eio_probe_out;
            eio_out_sync2 <= eio_out_sync1;
            ela_armed_d <= ela_armed;
            armed_test_pulse <= 1'b0;

            if (ela_fresh_arm_w) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= eio_out_sync2[6];
                if (eio_out_sync2[5])
                    armed_test_pulse <= 1'b1;
                armed_test_gate <= 1'b0;
            end else if (!ela_armed) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= 1'b0;
                armed_test_gate   <= 1'b0;
            end else if (armed_test_active) begin
                armed_test_count <= armed_test_count + 1'b1;
                if (eio_out_sync2[6] && (armed_test_count == 4'd7))
                    armed_test_gate <= 1'b1;
                if (armed_test_count == 4'd7)
                    armed_test_active <= 1'b0;
            end

            if (heartbeat_div == 26'd24_999_999) begin
                heartbeat_div <= 26'd0;
                heartbeat <= ~heartbeat;
            end else begin
                heartbeat_div <= heartbeat_div + 1'b1;
            end
        end
    end

    assign eio_probe_in = {SW, ~KEY, counter[1:0]};
    assign ela_fresh_arm_w = ela_armed && !ela_armed_d;
    assign trigger_in_w = eio_out_sync2[4] | armed_test_pulse | armed_test_gate;

    fcapz_ela_intel #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .CTRL_CHAIN(1),
        .DATA_CHAIN(2),
        .INPUT_PIPE(1),
        .DECIM_EN(1),
        .EXT_TRIG_EN(1),
        .TIMESTAMP_W(32),
        .NUM_SEGMENTS(4),
        .STARTUP_ARM(1),
        .DEFAULT_TRIG_EXT(2)
    ) u_ela (
        .sample_clk(CLOCK1_50),
        .sample_rst(por_rst),
        .probe_in(counter),
        .trigger_in(trigger_in_w),
        .trigger_out(trigger_out_unused),
        .armed_out(ela_armed)
    );

    fcapz_eio_intel #(
        .IN_W(8),
        .OUT_W(8),
        .CHAIN(3)
    ) u_eio (
        .probe_in(eio_probe_in),
        .probe_out(eio_probe_out)
    );

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
        .m_axi_awprot(bridge_awprot),
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
        .m_axi_arprot(bridge_arprot),
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

    axi4_test_slave #(.NUM_WORDS(16), .ERROR_ADDR(32'hFFFF_FFFC)) u_axi_slave (
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

    // DE25-Nano user LEDs are active-low. LEDR[0] shows heartbeat unless
    // overridden by EIO bit 0; other LEDs are direct EIO outputs.
    assign LEDR = ~({eio_out_sync2[7:1], eio_out_sync2[0] | heartbeat});

endmodule
