// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps
`include "fcapz_version.vh"

// fcapz_ejtagaxi: a read burst the slave accepted but has not finished must
// be drained, never left on the R channel for the next read to take.
//
// Stream 1 (0x200) gets its first burst stuck: the slave stalls its first R
// burst for STALL_CYCLES.  The host sees empty slots and aborts with a RESET
// scan (TDI ones), then streams 0x400.  Every word of stream 2 must come
// from 0x400 and the stream must end with an OKAY response.
//   STALL_CYCLES > TIMEOUT: the bridge's R timeout fires first (drain set
//                           at the timeout).
//   STALL_CYCLES < TIMEOUT: the abort lands with the burst still in flight
//                           (drain set by the RESET).

module fcapz_ejtagaxi_drain_tb;
    parameter FIFO_DEPTH   = 16;
    parameter TIMEOUT      = 4096;
    parameter STALL_CYCLES = 4300;
    parameter PRE_SCANS    = 6;
    parameter PRE_SLOTS    = 40;
    localparam NUM_WORDS = 2048;
    localparam SLOT_W    = 33;
    localparam MAX_BITS  = 4000;
    localparam WORDS     = 64;

    logic tck = 0, axi_clk = 0, axi_rst = 1;
    always #50 tck = ~tck;          // 10 MHz
    always #15 axi_clk = ~axi_clk;  // ~33 MHz

    logic tdi = 0; wire tdo;
    logic capture = 0, shift_en = 0, update = 0, sel = 0;

    wire [31:0] m_axi_awaddr; wire [7:0] m_axi_awlen; wire [2:0] m_axi_awsize;
    wire [1:0]  m_axi_awburst; wire m_axi_awvalid, m_axi_awready; wire [2:0] m_axi_awprot;
    wire [31:0] m_axi_wdata; wire [3:0] m_axi_wstrb; wire m_axi_wvalid, m_axi_wready, m_axi_wlast;
    wire [1:0]  m_axi_bresp; wire m_axi_bvalid, m_axi_bready;
    wire [31:0] m_axi_araddr; wire [7:0] m_axi_arlen; wire [2:0] m_axi_arsize;
    wire [1:0]  m_axi_arburst; wire m_axi_arvalid, m_axi_arready; wire [2:0] m_axi_arprot;
    wire [31:0] m_axi_rdata; wire [1:0] m_axi_rresp; wire m_axi_rvalid, m_axi_rlast, m_axi_rready;

    fcapz_ejtagaxi #(.ADDR_W(32), .DATA_W(32), .FIFO_DEPTH(FIFO_DEPTH), .TIMEOUT(TIMEOUT),
                     .STREAM_EN(1),
                     .USE_BEHAV_ASYNC_FIFO(1)) dut (
        .tck(tck), .tdi(tdi), .tdo(tdo), .capture(capture), .shift_en(shift_en),
        .update(update), .sel(sel), .axi_clk(axi_clk), .axi_rst(axi_rst),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_awlen(m_axi_awlen), .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst), .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_awprot(m_axi_awprot), .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready), .m_axi_wlast(m_axi_wlast),
        .m_axi_bresp(m_axi_bresp), .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .m_axi_araddr(m_axi_araddr), .m_axi_arlen(m_axi_arlen), .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst), .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_arprot(m_axi_arprot), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rvalid(m_axi_rvalid), .m_axi_rlast(m_axi_rlast), .m_axi_rready(m_axi_rready),
        .debug_tck(), .debug_tck_edge(), .debug_axi(), .debug_axi_edge());

    axi4_test_slave #(.ADDR_W(32), .DATA_W(32), .NUM_WORDS(NUM_WORDS),
                      .STALL_CYCLES(STALL_CYCLES), .STALL_FIRST_R(1), .HANG_EN(0)) slave (
        .clk(axi_clk), .rst(axi_rst),
        .s_axi_awaddr(m_axi_awaddr), .s_axi_awlen(m_axi_awlen), .s_axi_awsize(m_axi_awsize),
        .s_axi_awburst(m_axi_awburst), .s_axi_awvalid(m_axi_awvalid), .s_axi_awready(m_axi_awready),
        .s_axi_wdata(m_axi_wdata), .s_axi_wstrb(m_axi_wstrb), .s_axi_wlast(m_axi_wlast),
        .s_axi_wvalid(m_axi_wvalid), .s_axi_wready(m_axi_wready),
        .s_axi_bresp(m_axi_bresp), .s_axi_bvalid(m_axi_bvalid), .s_axi_bready(m_axi_bready),
        .s_axi_araddr(m_axi_araddr), .s_axi_arlen(m_axi_arlen), .s_axi_arsize(m_axi_arsize),
        .s_axi_arburst(m_axi_arburst), .s_axi_arvalid(m_axi_arvalid), .s_axi_arready(m_axi_arready),
        .s_axi_rdata(m_axi_rdata), .s_axi_rresp(m_axi_rresp), .s_axi_rlast(m_axi_rlast),
        .s_axi_rvalid(m_axi_rvalid), .s_axi_rready(m_axi_rready));

    localparam [3:0] CMD_NOP = 4'h0, CMD_STREAM_RSTART = 4'hA, CMD_RESET = 4'hF;
    function [71:0] make_cmd(input [3:0] cmd, input [31:0] addr, input [31:0] payload);
        make_cmd = {cmd, 4'h0, payload, addr};
    endfunction

    integer fail_count = 0;
    task automatic check(input string name, input bit ok);
        if (!ok) begin
            $display("FAIL: %s", name);
            fail_count++;
        end
    endtask

    // SEL stays high: BSCANE2 holds it while USER4 is in the IR.
    logic [MAX_BITS-1:0] tdi_bits, tdo_bits;
    task automatic dr_scan(input integer nbits);
        integer i;
        @(posedge tck); sel <= 1; capture <= 1;
        @(posedge tck); capture <= 0; shift_en <= 1;
        for (i = 0; i < nbits; i++) begin
            tdi <= tdi_bits[i]; @(negedge tck); tdo_bits[i] = tdo; @(posedge tck);
        end
        shift_en <= 0; tdi <= 0;
        @(posedge tck); update <= 1; @(posedge tck); update <= 0; @(negedge tck);
    endtask
    task automatic scan72(input [71:0] din, output [71:0] dout);
        tdi_bits = '0; tdi_bits[71:0] = din; dr_scan(72); dout = tdo_bits[71:0];
    endtask
    task automatic idle(input integer n); repeat (n) @(posedge tck); endtask
    task automatic poll_resp(output [71:0] dout);
        integer n;
        n = 0;
        do begin
            idle(20);
            scan72(make_cmd(CMD_NOP, 0, 0), dout);
            n++;
        end while (dout[68] == 1'b0 && n < 50);
    endtask

    logic [31:0] got [0:255]; integer got_n;
    task automatic stream_scan(input integer nslots);
        integer k;
        tdi_bits = '0; dr_scan(nslots * SLOT_W);
        for (k = 1; k < nslots; k++)
            if (tdo_bits[k * SLOT_W]) begin
                got[got_n] = tdo_bits[k*SLOT_W+1 +: 32];
                got_n++;
            end
    endtask

    function [31:0] mem_at(input [31:0] addr);
        mem_at = slave.mem[(addr >> 2) % NUM_WORDS];
    endfunction

    initial begin
        logic [71:0] dout; integer i, s, bad;
        for (i = 0; i < NUM_WORDS; i++) slave.mem[i] = (i * 32'h9E3779B1) ^ 32'hA5A5_0000 ^ i;
        repeat (4) @(posedge axi_clk); axi_rst <= 0; idle(20);

        // Stream 1: the first burst gets stuck; the host gives up and aborts.
        scan72(make_cmd(CMD_RESET, 0, 0), dout); idle(20);
        scan72(make_cmd(CMD_STREAM_RSTART, 32'h200, WORDS), dout);
        got_n = 0;
        for (s = 0; s < PRE_SCANS; s++) stream_scan(PRE_SLOTS);
        check("stream 1 stalled (no words yet)", got_n == 0);
        scan72(make_cmd(CMD_RESET, 0, 0), dout);   // TDI ones: abort
        idle(400);
        check("not in stream mode after the abort", dut.stream_mode == 1'b0);

        // Stream 2 must carry 0x400's words only.
        scan72(make_cmd(CMD_STREAM_RSTART, 32'h400, WORDS), dout);
        got_n = 0;
        for (s = 0; s < 40 && got_n < WORDS; s++) stream_scan(20);
        stream_scan(1);                              // header 0: last scan
        check($sformatf("stream 2: %0d/%0d words", got_n, WORDS), got_n == WORDS);
        bad = 0;
        for (i = 0; i < got_n; i++)
            if (got[i] !== mem_at(32'h400 + 4 * i)) begin
                if (bad < 4)
                    $display("  word %0d got %08x want %08x (stale 0x200: %08x)", i, got[i],
                             mem_at(32'h400 + 4 * i), mem_at(32'h200 + 4 * i));
                bad++;
            end
        check($sformatf("stream 2: %0d wrong words", bad), bad == 0);
        check("stream 2 ended", dut.stream_mode == 1'b0);
        poll_resp(dout);
        check("stream 2 response prev_valid", dout[68] == 1'b1);
        check($sformatf("stream 2 response resp=%0d want OKAY", dout[65:64]), dout[65:64] == 2'b00);

        if (fail_count > 0) $fatal(1, "TESTS FAILED");
        $display("PASS: drain (STALL_CYCLES=%0d TIMEOUT=%0d)", STALL_CYCLES, TIMEOUT);
        $finish;
    end
endmodule
