// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Regression: a stale staged command must not reach the AXI bus after reset.
//
// On devices that drop register initial values (PolarFire), the TCK-side
// command staging register can power up, or survive a reprogram, holding a
// valid command. The bench seeds one (a write of 0xDEADBEEF to 0x08), holds
// axi_rst with TCK stopped, as when no host is clocking JTAG during power-up,
// then releases axi_rst and clocks TCK with the chain deselected. The bridge
// must issue no AXI transaction: axi_rst, synchronized to TCK, has to clear
// the staged command before it can be enqueued.

module fcapz_ejtagaxi_stale_stage_tb;

    logic tck     = 1'b0;
    logic tck_en  = 1'b0;
    logic axi_clk = 1'b0;
    logic axi_rst = 1'b1;

    always #50 if (tck_en) tck = ~tck;
    always #15 axi_clk = ~axi_clk;

    wire        tdo;
    wire [31:0] m_axi_awaddr;
    wire [7:0]  m_axi_awlen;
    wire [2:0]  m_axi_awsize;
    wire [1:0]  m_axi_awburst;
    wire        m_axi_awvalid;
    wire        m_axi_awready;
    wire [2:0]  m_axi_awprot;
    wire [31:0] m_axi_wdata;
    wire [3:0]  m_axi_wstrb;
    wire        m_axi_wvalid;
    wire        m_axi_wready;
    wire        m_axi_wlast;
    wire [1:0]  m_axi_bresp;
    wire        m_axi_bvalid;
    wire        m_axi_bready;
    wire [31:0] m_axi_araddr;
    wire [7:0]  m_axi_arlen;
    wire [2:0]  m_axi_arsize;
    wire [1:0]  m_axi_arburst;
    wire        m_axi_arvalid;
    wire        m_axi_arready;
    wire [2:0]  m_axi_arprot;
    wire [31:0] m_axi_rdata;
    wire [1:0]  m_axi_rresp;
    wire        m_axi_rvalid;
    wire        m_axi_rlast;
    wire        m_axi_rready;

    localparam [3:0] CMD_WRITE = 4'h1;

    fcapz_ejtagaxi #(
        .ADDR_W     (32),
        .DATA_W     (32),
        .FIFO_DEPTH (16),
        .TIMEOUT    (4096),
        .DEBUG_EN   (0),
        .USE_BEHAV_ASYNC_FIFO (1),
        .ASYNC_FIFO_IMPL      (0)
    ) dut (
        .tck           (tck),
        .tdi           (1'b0),
        .tdo           (tdo),
        .capture       (1'b0),
        .shift_en      (1'b0),
        .update        (1'b0),
        .sel           (1'b0),
        .axi_clk       (axi_clk),
        .axi_rst       (axi_rst),
        .m_axi_awaddr  (m_axi_awaddr),
        .m_axi_awlen   (m_axi_awlen),
        .m_axi_awsize  (m_axi_awsize),
        .m_axi_awburst (m_axi_awburst),
        .m_axi_awvalid (m_axi_awvalid),
        .m_axi_awready (m_axi_awready),
        .m_axi_awprot  (m_axi_awprot),
        .m_axi_wdata   (m_axi_wdata),
        .m_axi_wstrb   (m_axi_wstrb),
        .m_axi_wvalid  (m_axi_wvalid),
        .m_axi_wready  (m_axi_wready),
        .m_axi_wlast   (m_axi_wlast),
        .m_axi_bresp   (m_axi_bresp),
        .m_axi_bvalid  (m_axi_bvalid),
        .m_axi_bready  (m_axi_bready),
        .m_axi_araddr  (m_axi_araddr),
        .m_axi_arlen   (m_axi_arlen),
        .m_axi_arsize  (m_axi_arsize),
        .m_axi_arburst (m_axi_arburst),
        .m_axi_arvalid (m_axi_arvalid),
        .m_axi_arready (m_axi_arready),
        .m_axi_arprot  (m_axi_arprot),
        .m_axi_rdata   (m_axi_rdata),
        .m_axi_rresp   (m_axi_rresp),
        .m_axi_rvalid  (m_axi_rvalid),
        .m_axi_rlast   (m_axi_rlast),
        .m_axi_rready  (m_axi_rready),
        .debug_tck     (),
        .debug_tck_edge(),
        .debug_axi     (),
        .debug_axi_edge()
    );

    axi4_test_slave #(
        .ADDR_W    (32),
        .DATA_W    (32),
        .NUM_WORDS (16)
    ) slave (
        .clk           (axi_clk),
        .rst           (axi_rst),
        .s_axi_awaddr  (m_axi_awaddr),
        .s_axi_awlen   (m_axi_awlen),
        .s_axi_awsize  (m_axi_awsize),
        .s_axi_awburst (m_axi_awburst),
        .s_axi_awvalid (m_axi_awvalid),
        .s_axi_awready (m_axi_awready),
        .s_axi_wdata   (m_axi_wdata),
        .s_axi_wstrb   (m_axi_wstrb),
        .s_axi_wlast   (m_axi_wlast),
        .s_axi_wvalid  (m_axi_wvalid),
        .s_axi_wready  (m_axi_wready),
        .s_axi_bresp   (m_axi_bresp),
        .s_axi_bvalid  (m_axi_bvalid),
        .s_axi_bready  (m_axi_bready),
        .s_axi_araddr  (m_axi_araddr),
        .s_axi_arlen   (m_axi_arlen),
        .s_axi_arsize  (m_axi_arsize),
        .s_axi_arburst (m_axi_arburst),
        .s_axi_arvalid (m_axi_arvalid),
        .s_axi_arready (m_axi_arready),
        .s_axi_rdata   (m_axi_rdata),
        .s_axi_rresp   (m_axi_rresp),
        .s_axi_rlast   (m_axi_rlast),
        .s_axi_rvalid  (m_axi_rvalid),
        .s_axi_rready  (m_axi_rready)
    );

    integer aw_count = 0;
    integer ar_count = 0;
    always @(posedge axi_clk) begin
        if (m_axi_awvalid && m_axi_awready) aw_count = aw_count + 1;
        if (m_axi_arvalid && m_axi_arready) ar_count = ar_count + 1;
    end

    initial begin
        // After the DUT's own initial blocks: model the power-up contents.
        #1;
        dut.cmdq_stage_valid = 1'b1;
        dut.cmdq_stage_data  = {CMD_WRITE, 32'h0000_0008, 32'hDEADBEEF,
                                4'hF, 8'd0, 3'b010, 2'b01};
        #300;
        axi_rst = 1'b0;             // reset ends while TCK is still stopped
        #1000;
        tck_en = 1'b1;              // the host starts clocking TCK, sel low
        #4000;
        tck_en = 1'b0;
        #2000;
        if (aw_count == 0 && ar_count == 0 && !dut.cmdq_stage_valid) begin
            $display("PASS: stale staged command dropped by reset");
        end else begin
            $display("FAIL: stale staged command reached AXI (aw=%0d ar=%0d stage_valid=%0d)",
                     aw_count, ar_count, dut.cmdq_stage_valid);
        end
        $finish;
    end

endmodule
