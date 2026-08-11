// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Tiny self-stimulating AXI4-Lite master for the DE25-Nano AXI-monitor demo.
//
// Periodically issues a single-beat write followed by a single-beat read to a
// small address window, so the AXI monitor tapping this bus always has live
// traffic to trigger on (aw_hs / w_hs / b_hs / ar_hs / r_hs) even when no host
// is driving the EJTAG-AXI bridge. It only ever produces *clean* (OKAY)
// transactions -- it never touches an error/hang address -- so it cannot forge
// an any_err event; error triggering stays a deliberate, host-driven stimulus.
//
// AXI4 burst fields are tied off for single-beat transfers (awlen=0, size=word,
// INCR) so it can talk to the AXI4 axi4_test_slave. Single outstanding: one
// transaction fully completes before the next is launched.

module axi4_traffic_gen #(
    parameter ADDR_W   = 32,
    parameter DATA_W   = 32,
    parameter PERIOD   = 4096,          // idle cycles between transactions
    parameter BASE_ADDR = 32'h0000_0020 // clean target window (never ERROR/HANG)
) (
    input  wire              clk,
    input  wire              rst,       // active-high

    output reg  [ADDR_W-1:0] m_axi_awaddr,
    output wire [7:0]        m_axi_awlen,
    output wire [2:0]        m_axi_awsize,
    output wire [1:0]        m_axi_awburst,
    output wire [2:0]        m_axi_awprot,
    output reg               m_axi_awvalid,
    input  wire              m_axi_awready,
    output reg  [DATA_W-1:0] m_axi_wdata,
    output wire [DATA_W/8-1:0] m_axi_wstrb,
    output wire              m_axi_wlast,
    output reg               m_axi_wvalid,
    input  wire              m_axi_wready,
    input  wire [1:0]        m_axi_bresp,
    input  wire              m_axi_bvalid,
    output reg               m_axi_bready,

    output reg  [ADDR_W-1:0] m_axi_araddr,
    output wire [7:0]        m_axi_arlen,
    output wire [2:0]        m_axi_arsize,
    output wire [1:0]        m_axi_arburst,
    output wire [2:0]        m_axi_arprot,
    output reg               m_axi_arvalid,
    input  wire              m_axi_arready,
    input  wire [DATA_W-1:0] m_axi_rdata,
    input  wire [1:0]        m_axi_rresp,
    input  wire              m_axi_rvalid,
    output reg               m_axi_rready
);

    // Single-beat AXI4 framing.
    assign m_axi_awlen   = 8'd0;
    assign m_axi_arlen   = 8'd0;
    assign m_axi_awsize  = 3'd2;   // 4 bytes
    assign m_axi_arsize  = 3'd2;
    assign m_axi_awburst = 2'b01;  // INCR
    assign m_axi_arburst = 2'b01;
    assign m_axi_awprot  = 3'b000;
    assign m_axi_arprot  = 3'b000;
    assign m_axi_wstrb   = {(DATA_W/8){1'b1}};
    assign m_axi_wlast   = 1'b1;

    localparam [2:0] S_IDLE  = 3'd0,
                     S_WADDR = 3'd1,  // drive AW+W, wait both accepted
                     S_WRESP = 3'd2,  // wait B
                     S_RADDR = 3'd3,  // drive AR, wait accepted
                     S_RDATA = 3'd4;  // wait R

    reg [2:0]  state;
    reg [31:0] wait_cnt;
    reg [DATA_W-1:0] pattern;
    reg aw_done, w_done;

    always @(posedge clk) begin
        if (rst) begin
            state         <= S_IDLE;
            wait_cnt      <= 32'd0;
            pattern       <= 32'h1000_0001;
            m_axi_awaddr  <= BASE_ADDR;
            m_axi_araddr  <= BASE_ADDR;
            m_axi_awvalid <= 1'b0;
            m_axi_wvalid  <= 1'b0;
            m_axi_wdata   <= 32'd0;
            m_axi_bready  <= 1'b0;
            m_axi_arvalid <= 1'b0;
            m_axi_rready  <= 1'b0;
            aw_done       <= 1'b0;
            w_done        <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (wait_cnt >= PERIOD) begin
                        wait_cnt      <= 32'd0;
                        m_axi_awaddr  <= BASE_ADDR;
                        m_axi_wdata   <= pattern;
                        m_axi_awvalid <= 1'b1;
                        m_axi_wvalid  <= 1'b1;
                        aw_done       <= 1'b0;
                        w_done        <= 1'b0;
                        state         <= S_WADDR;
                    end else begin
                        wait_cnt <= wait_cnt + 1'b1;
                    end
                end
                S_WADDR: begin
                    if (m_axi_awvalid && m_axi_awready) begin
                        m_axi_awvalid <= 1'b0;
                        aw_done       <= 1'b1;
                    end
                    if (m_axi_wvalid && m_axi_wready) begin
                        m_axi_wvalid <= 1'b0;
                        w_done       <= 1'b1;
                    end
                    if ((aw_done || (m_axi_awvalid && m_axi_awready)) &&
                        (w_done  || (m_axi_wvalid  && m_axi_wready))) begin
                        m_axi_bready <= 1'b1;
                        state        <= S_WRESP;
                    end
                end
                S_WRESP: begin
                    if (m_axi_bvalid && m_axi_bready) begin
                        m_axi_bready  <= 1'b0;
                        m_axi_araddr  <= BASE_ADDR;
                        m_axi_arvalid <= 1'b1;
                        state         <= S_RADDR;
                    end
                end
                S_RADDR: begin
                    if (m_axi_arvalid && m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        m_axi_rready  <= 1'b1;
                        state         <= S_RDATA;
                    end
                end
                S_RDATA: begin
                    if (m_axi_rvalid && m_axi_rready) begin
                        m_axi_rready <= 1'b0;
                        pattern      <= pattern + 32'h0000_0011;
                        state        <= S_IDLE;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
