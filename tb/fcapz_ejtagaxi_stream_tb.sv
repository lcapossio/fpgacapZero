// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps
`include "fcapz_version.vh"

// EJTAG-AXI bridge streaming-read testbench (CMD_STREAM_RSTART).
// Raw TAP signals drive fcapz_ejtagaxi; scans of any length are shifted the
// way a JTAG cable does (sample TDO, then the shift edge).  Checks: data and
// order across 4 KB boundaries, scans cut inside a slot, slots the FIFO could
// not fill, the per-scan header, the stream response, abort with a burst in
// flight, AXI errors, a zero-length stream and every burst's 4 KB / length.

module fcapz_ejtagaxi_stream_tb;

    parameter FIFO_DEPTH           = 16;
    parameter USE_BEHAV_ASYNC_FIFO = 1;
    parameter ASYNC_FIFO_IMPL      = (USE_BEHAV_ASYNC_FIFO ? 0 : 1);
    parameter STALL_CYCLES         = 0;
    parameter TCK_HALF_NS          = 50;     // 10 MHz

    localparam NUM_WORDS    = 2048;          // 8 KB, wraps
    localparam STREAM_BURST = (FIFO_DEPTH >= 4) ? FIFO_DEPTH / 4 : 1;
    localparam SLOT_W       = 33;
    localparam MAX_BITS     = 40000;

    // ---- Clocks and resets ---------------------------------------------------

    logic tck     = 1'b0;
    logic axi_clk = 1'b0;
    logic axi_rst = 1'b1;

    always #(TCK_HALF_NS) tck = ~tck;
    always #15 axi_clk = ~axi_clk;           // ~33 MHz

    // ---- TAP signals ---------------------------------------------------------

    logic tdi      = 1'b0;
    wire  tdo;
    logic capture  = 1'b0;
    logic shift_en = 1'b0;
    logic update   = 1'b0;
    logic sel      = 1'b0;

    // ---- AXI4 wires ----------------------------------------------------------

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

    // ---- DUT -----------------------------------------------------------------

    fcapz_ejtagaxi #(
        .ADDR_W               (32),
        .DATA_W               (32),
        .FIFO_DEPTH           (FIFO_DEPTH),
        .TIMEOUT              (4096),
        .STREAM_EN            (1),
        .USE_BEHAV_ASYNC_FIFO (USE_BEHAV_ASYNC_FIFO),
        .ASYNC_FIFO_IMPL      (ASYNC_FIFO_IMPL)
    ) dut (
        .tck (tck), .tdi (tdi), .tdo (tdo),
        .capture (capture), .shift_en (shift_en), .update (update), .sel (sel),
        .axi_clk (axi_clk), .axi_rst (axi_rst),
        .m_axi_awaddr (m_axi_awaddr), .m_axi_awlen (m_axi_awlen),
        .m_axi_awsize (m_axi_awsize), .m_axi_awburst (m_axi_awburst),
        .m_axi_awvalid (m_axi_awvalid), .m_axi_awready (m_axi_awready),
        .m_axi_awprot (m_axi_awprot),
        .m_axi_wdata (m_axi_wdata), .m_axi_wstrb (m_axi_wstrb),
        .m_axi_wvalid (m_axi_wvalid), .m_axi_wready (m_axi_wready),
        .m_axi_wlast (m_axi_wlast),
        .m_axi_bresp (m_axi_bresp), .m_axi_bvalid (m_axi_bvalid),
        .m_axi_bready (m_axi_bready),
        .m_axi_araddr (m_axi_araddr), .m_axi_arlen (m_axi_arlen),
        .m_axi_arsize (m_axi_arsize), .m_axi_arburst (m_axi_arburst),
        .m_axi_arvalid (m_axi_arvalid), .m_axi_arready (m_axi_arready),
        .m_axi_arprot (m_axi_arprot),
        .m_axi_rdata (m_axi_rdata), .m_axi_rresp (m_axi_rresp),
        .m_axi_rvalid (m_axi_rvalid), .m_axi_rlast (m_axi_rlast),
        .m_axi_rready (m_axi_rready),
        .debug_tck (), .debug_tck_edge (), .debug_axi (), .debug_axi_edge ()
    );

    axi4_test_slave #(
        .ADDR_W       (32),
        .DATA_W       (32),
        .NUM_WORDS    (NUM_WORDS),
        .STALL_CYCLES (STALL_CYCLES),
        .HANG_EN      (0)
    ) slave (
        .clk (axi_clk), .rst (axi_rst),
        .s_axi_awaddr (m_axi_awaddr), .s_axi_awlen (m_axi_awlen),
        .s_axi_awsize (m_axi_awsize), .s_axi_awburst (m_axi_awburst),
        .s_axi_awvalid (m_axi_awvalid), .s_axi_awready (m_axi_awready),
        .s_axi_wdata (m_axi_wdata), .s_axi_wstrb (m_axi_wstrb),
        .s_axi_wlast (m_axi_wlast), .s_axi_wvalid (m_axi_wvalid),
        .s_axi_wready (m_axi_wready),
        .s_axi_bresp (m_axi_bresp), .s_axi_bvalid (m_axi_bvalid),
        .s_axi_bready (m_axi_bready),
        .s_axi_araddr (m_axi_araddr), .s_axi_arlen (m_axi_arlen),
        .s_axi_arsize (m_axi_arsize), .s_axi_arburst (m_axi_arburst),
        .s_axi_arvalid (m_axi_arvalid), .s_axi_arready (m_axi_arready),
        .s_axi_rdata (m_axi_rdata), .s_axi_rresp (m_axi_rresp),
        .s_axi_rlast (m_axi_rlast), .s_axi_rvalid (m_axi_rvalid),
        .s_axi_rready (m_axi_rready)
    );

    // ---- Checks --------------------------------------------------------------

    integer pass_count = 0;
    integer fail_count = 0;

    task automatic check(input string name, input logic cond);
        if (cond) pass_count++;
        else begin
            fail_count++;
            $display("FAIL: %s", name);
        end
    endtask

    // Every read burst: within 4 KB, at most STREAM_BURST beats while a
    // stream runs, and the slave never sees a beat the bridge refuses.
    integer ar_count = 0;
    always @(posedge axi_clk) begin
        if (m_axi_arvalid && m_axi_arready) begin
            ar_count = ar_count + 1;
            if (((m_axi_araddr & 32'hFFF) + (m_axi_arlen + 1) * 4) > 32'h1000) begin
                fail_count++;
                $display("FAIL: burst at 0x%08x len %0d crosses 4 KB",
                         m_axi_araddr, m_axi_arlen + 1);
            end
            if (dut.strm_active && (m_axi_arlen + 1) > STREAM_BURST) begin
                fail_count++;
                $display("FAIL: stream burst of %0d beats > %0d",
                         m_axi_arlen + 1, STREAM_BURST);
            end
        end
        if (dut.strm_active && dut.axi_state == 4'd8 && m_axi_rvalid && !m_axi_rready) begin
            fail_count++;
            $display("FAIL: stream back-pressured the slave (burst FIFO full)");
        end
    end

    // ---- Commands ------------------------------------------------------------

    localparam [3:0] CMD_NOP           = 4'h0;
    localparam [3:0] CMD_READ          = 4'h2;
    localparam [3:0] CMD_STREAM_RSTART = 4'hA;
    localparam [3:0] CMD_CONFIG        = 4'hE;
    localparam [3:0] CMD_RESET         = 4'hF;

    function [71:0] make_cmd(input [3:0] cmd, input [31:0] addr, input [31:0] payload);
        make_cmd = {cmd, 4'h0, payload, addr};
    endfunction

    // One DR scan of nbits: TDO sampled before each shift edge, as on a cable.
    logic [MAX_BITS-1:0] tdi_bits;
    logic [MAX_BITS-1:0] tdo_bits;

    task automatic dr_scan(input integer nbits);
        integer i;
        begin
            @(posedge tck);
            sel     <= 1'b1;
            capture <= 1'b1;
            @(posedge tck);
            capture  <= 1'b0;
            shift_en <= 1'b1;
            for (i = 0; i < nbits; i = i + 1) begin
                tdi <= tdi_bits[i];
                @(negedge tck);
                tdo_bits[i] = tdo;
                @(posedge tck);
            end
            shift_en <= 1'b0;
            tdi      <= 1'b0;
            @(posedge tck);
            update <= 1'b1;
            @(posedge tck);
            update <= 1'b0;
            // SEL stays high: BSCANE2 holds it while USER4 is in the IR.
            @(negedge tck);   // let the UPDATE edge's assignments land
        end
    endtask

    task automatic scan72(input [71:0] din, output [71:0] dout);
        begin
            tdi_bits = '0;
            tdi_bits[71:0] = din;
            dr_scan(72);
            dout = tdo_bits[71:0];
        end
    endtask

    task automatic idle(input integer n);
        repeat (n) @(posedge tck);
    endtask

    // NOP scans until a response is captured (prev_valid), as the host polls.
    task automatic poll_resp(output [71:0] dout);
        integer n;
        begin
            n = 0;
            do begin
                idle(20);
                scan72(make_cmd(CMD_NOP, 0, 0), dout);
                n = n + 1;
            end while (dout[68] == 1'b0 && n < 50);
        end
    endtask

    // Expected memory word at a byte address (slave wraps at NUM_WORDS; its
    // ERROR_ADDR beat returns SLVERR with zero data).
    function [31:0] mem_at(input [31:0] addr);
        mem_at = (addr == 32'hFFFF_FFFC) ? 32'h0 : slave.mem[(addr >> 2) % NUM_WORDS];
    endfunction

    // One stream scan of nslots slots plus extra_bits: collects valid words
    // into got[] and checks the header against the words still to come.
    logic [31:0] got [0:NUM_WORDS*2];
    integer      got_n;

    task automatic stream_scan(input integer nslots, input integer extra_bits,
                               input integer total, input string tag);
        integer nbits, k;
        logic [31:0] hdr, word;
        begin
            nbits = nslots * SLOT_W + extra_bits;
            tdi_bits = '0;
            dr_scan(nbits);
            hdr = tdo_bits[1 +: 32];
            check($sformatf("%s: header valid=0", tag), tdo_bits[0] == 1'b0);
            check($sformatf("%s: header left %0d == %0d", tag, hdr, total - got_n),
                  hdr == total - got_n);
            for (k = 1; (k + 1) * SLOT_W <= nbits; k = k + 1) begin
                if (tdo_bits[k * SLOT_W]) begin
                    word = tdo_bits[k * SLOT_W + 1 +: 32];
                    got[got_n] = word;
                    got_n = got_n + 1;
                end
            end
        end
    endtask

    // Stream `total` words from `addr` with a pattern of scan lengths, check
    // every word, then the stream response on a normal NOP scan.
    task automatic run_stream(input [31:0] addr, input integer total,
                              input [1:0] want_resp, input string tag);
        logic [71:0] dout;
        integer scans, i, bad;
        integer pat_slots [0:5];
        integer pat_extra [0:5];
        begin
            pat_slots[0] = 1;   pat_extra[0] = 0;    // header only
            pat_slots[1] = 40;  pat_extra[1] = 0;
            pat_slots[2] = 17;  pat_extra[2] = 20;   // cut inside a slot
            pat_slots[3] = 300; pat_extra[3] = 0;
            pat_slots[4] = 3;   pat_extra[4] = 32;   // cut before the last bit
            pat_slots[5] = 90;  pat_extra[5] = 1;
            got_n = 0;
            scan72(make_cmd(CMD_RESET, 0, 0), dout);
            idle(20);
            scan72(make_cmd(CMD_STREAM_RSTART, addr, total), dout);
            scans = 0;
            while (got_n < total && scans < 4000) begin
                stream_scan(pat_slots[scans % 6], pat_extra[scans % 6], total,
                            $sformatf("%s scan %0d", tag, scans));
                scans = scans + 1;
            end
            check($sformatf("%s: got %0d of %0d words", tag, got_n, total), got_n == total);
            // Stream mode stays until a header reads 0: the host's closing
            // header-only scan confirms the count of the last words.
            check($sformatf("%s: still in stream mode before the final scan", tag),
                  dut.stream_mode == 1'b1);
            stream_scan(1, 0, total, $sformatf("%s final", tag));
            bad = 0;
            for (i = 0; i < got_n && i < total; i = i + 1)
                if (got[i] !== mem_at(addr + 4 * i)) begin
                    if (bad < 5)
                        $display("  %s word %0d: got 0x%08x want 0x%08x",
                                 tag, i, got[i], mem_at(addr + 4 * i));
                    bad = bad + 1;
                end
            check($sformatf("%s: %0d words wrong", tag, bad), bad == 0);
            check($sformatf("%s: stream mode left", tag), dut.stream_mode == 1'b0);
            poll_resp(dout);
            check($sformatf("%s: response prev_valid", tag), dout[68] == 1'b1);
            check($sformatf("%s: response resp=%0d want %0d", tag, dout[65:64], want_resp),
                  dout[65:64] == want_resp);
            idle(20);
            scan72(make_cmd(CMD_NOP, 0, 0), dout);
            check($sformatf("%s: idle after", tag), dout[69] == 1'b0);
        end
    endtask

    // ---- Scenarios -----------------------------------------------------------

    initial begin
        logic [71:0] dout;
        integer i;

        for (i = 0; i < NUM_WORDS; i = i + 1)
            slave.mem[i] = (i * 32'h9E3779B1) ^ 32'hA5A5_0000 ^ i;

        repeat (4) @(posedge axi_clk);
        axi_rst <= 1'b0;
        idle(20);

        $display("\n=== S1: FEATURES streaming bit ===");
        scan72(make_cmd(CMD_CONFIG, 32'h2C, 0), dout);
        idle(4);
        scan72(make_cmd(CMD_NOP, 0, 0), dout);
        check("S1: FEATURES[24]=1", dout[24] == 1'b1);

        $display("\n=== S2: stream across 4 KB boundaries ===");
        run_stream(32'h0000_0F84, 1500, 2'b00, "S2");

        $display("\n=== S3: short stream, word-unaligned address ===");
        run_stream(32'h0000_0103, 5, 2'b00, "S3");

        $display("\n=== S4: single word ===");
        run_stream(32'h0000_0040, 1, 2'b00, "S4");

        $display("\n=== S5: AXI error inside the range ===");
        // The slave flags SLVERR for a burst that starts at 0xFFFF_FFFC; the
        // 4 KB cut ends that burst there, then the range wraps to 0.
        run_stream(32'hFFFF_FFFC, 6, 2'b10, "S5");

        $display("\n=== S6: zero-length stream is a NOP ===");
        scan72(make_cmd(CMD_RESET, 0, 0), dout);
        idle(20);
        scan72(make_cmd(CMD_STREAM_RSTART, 32'h100, 0), dout);
        check("S6: not in stream mode", dut.stream_mode == 1'b0);
        poll_resp(dout);
        check("S6: response prev_valid", dout[68] == 1'b1);

        $display("\n=== S7: abort with a burst in flight, then a single read ===");
        scan72(make_cmd(CMD_RESET, 0, 0), dout);
        idle(20);
        got_n = 0;
        scan72(make_cmd(CMD_STREAM_RSTART, 32'h200, 1000), dout);
        stream_scan(25, 0, 1000, "S7 scan");
        tdi_bits = '0;
        tdi_bits[3] = 1'b1;
        dr_scan(8);
        check("S7: abort left stream mode", dut.stream_mode == 1'b0);
        idle(400);
        check("S7: no read left in flight", dut.r_drain == 1'b0);
        scan72(make_cmd(CMD_READ, 32'h0000_0010, 0), dout);
        poll_resp(dout);
        check("S7: read after abort prev_valid", dout[68] == 1'b1);
        check($sformatf("S7: read after abort 0x%08x", dout[31:0]),
              dout[31:0] == mem_at(32'h10));
        run_stream(32'h0000_0400, 64, 2'b00, "S7 restart");

        $display("\n=== S8: long stream through the wrap ===");
        run_stream(32'h0000_1F00, 3000, 2'b00, "S8");

        check("bursts were issued", ar_count > 0);
        $display("=== EJTAGAXI STREAM TB (FIFO_DEPTH=%0d, STALL=%0d): %0d passed, %0d failed ===",
                 FIFO_DEPTH, STALL_CYCLES, pass_count, fail_count);
        if (fail_count > 0) $fatal(1, "TESTS FAILED");
        $display("PASS: stream");
        $finish;
    end

endmodule
