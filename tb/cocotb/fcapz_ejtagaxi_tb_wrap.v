// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module fcapz_ejtagaxi_tb_wrap #(
    parameter DEBUG_EN = 0,
    parameter FIFO_DEPTH = 16,
    parameter CMD_FIFO_DEPTH = FIFO_DEPTH * 2,
    parameter RESP_FIFO_DEPTH = FIFO_DEPTH * 2,
    parameter USE_BEHAV_ASYNC_FIFO = 1,
    parameter ASYNC_FIFO_IMPL = (USE_BEHAV_ASYNC_FIFO ? 0 : 1),
    parameter CMD_FIFO_MEMORY_TYPE = "auto",
    parameter RESP_FIFO_MEMORY_TYPE = "auto",
    parameter BURST_FIFO_MEMORY_TYPE = "auto"
) (
    input  wire        tck,
    input  wire        tdi,
    output wire        tdo,
    input  wire        capture,
    input  wire        shift_en,
    input  wire        update,
    input  wire        sel,
    input  wire        axi_clk,
    input  wire        axi_rst,
    output wire [31:0] mem0,
    output wire [31:0] mem1,
    output wire [31:0] mem4,
    output wire [31:0] mem5,
    output wire [31:0] mem6,
    output wire [31:0] mem7,
    output wire [31:0] mem8,
    output wire [31:0] mem9,
    output wire [31:0] mem10,
    output wire [31:0] mem11,
    output wire [7:0]  pending_count_probe,
    output wire [3:0]  last_cmd_probe,
    output wire [255:0] debug_tck,
    output wire [255:0] debug_tck_edge,
    output wire [255:0] debug_axi,
    output wire [255:0] debug_axi_edge
);

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

    fcapz_ejtagaxi #(
        .ADDR_W(32),
        .DATA_W(32),
        .FIFO_DEPTH(FIFO_DEPTH),
        .CMD_FIFO_DEPTH(CMD_FIFO_DEPTH),
        .RESP_FIFO_DEPTH(RESP_FIFO_DEPTH),
        .TIMEOUT(4096),
        .DEBUG_EN(DEBUG_EN),
        .USE_BEHAV_ASYNC_FIFO(USE_BEHAV_ASYNC_FIFO),
        .ASYNC_FIFO_IMPL(ASYNC_FIFO_IMPL),
        .CMD_FIFO_MEMORY_TYPE(CMD_FIFO_MEMORY_TYPE),
        .RESP_FIFO_MEMORY_TYPE(RESP_FIFO_MEMORY_TYPE),
        .BURST_FIFO_MEMORY_TYPE(BURST_FIFO_MEMORY_TYPE)
    ) dut (
        .tck(tck),
        .tdi(tdi),
        .tdo(tdo),
        .capture(capture),
        .shift_en(shift_en),
        .update(update),
        .sel(sel),
        .axi_clk(axi_clk),
        .axi_rst(axi_rst),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rready(m_axi_rready),
        .debug_tck(debug_tck),
        .debug_tck_edge(debug_tck_edge),
        .debug_axi(debug_axi),
        .debug_axi_edge(debug_axi_edge)
    );

    axi4_test_slave #(
        .ADDR_W(32),
        .DATA_W(32),
        .NUM_WORDS(16)
    ) slave (
        .clk(axi_clk),
        .rst(axi_rst),
        .s_axi_awaddr(m_axi_awaddr),
        .s_axi_awlen(m_axi_awlen),
        .s_axi_awsize(m_axi_awsize),
        .s_axi_awburst(m_axi_awburst),
        .s_axi_awvalid(m_axi_awvalid),
        .s_axi_awready(m_axi_awready),
        .s_axi_wdata(m_axi_wdata),
        .s_axi_wstrb(m_axi_wstrb),
        .s_axi_wlast(m_axi_wlast),
        .s_axi_wvalid(m_axi_wvalid),
        .s_axi_wready(m_axi_wready),
        .s_axi_bresp(m_axi_bresp),
        .s_axi_bvalid(m_axi_bvalid),
        .s_axi_bready(m_axi_bready),
        .s_axi_araddr(m_axi_araddr),
        .s_axi_arlen(m_axi_arlen),
        .s_axi_arsize(m_axi_arsize),
        .s_axi_arburst(m_axi_arburst),
        .s_axi_arvalid(m_axi_arvalid),
        .s_axi_arready(m_axi_arready),
        .s_axi_rdata(m_axi_rdata),
        .s_axi_rresp(m_axi_rresp),
        .s_axi_rlast(m_axi_rlast),
        .s_axi_rvalid(m_axi_rvalid),
        .s_axi_rready(m_axi_rready)
    );

    assign mem0 = slave.mem[0];
    assign mem1 = slave.mem[1];
    assign mem4 = slave.mem[4];
    assign mem5 = slave.mem[5];
    assign mem6 = slave.mem[6];
    assign mem7 = slave.mem[7];
    assign mem8 = slave.mem[8];
    assign mem9 = slave.mem[9];
    assign mem10 = slave.mem[10];
    assign mem11 = slave.mem[11];
    assign pending_count_probe = dut.pending_count;
    assign last_cmd_probe = dut.last_cmd;

endmodule
