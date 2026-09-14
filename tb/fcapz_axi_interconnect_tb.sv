// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Testbench for fcapz_axi_interconnect (axiZero-generated 2x1 full-AXI4
// crossbar). Two masters (s0 = CPU-like, s1 = EJTAG-bridge-like) are merged
// onto one shared axi4_test_slave (m0). Proves:
//   * each master can write then read back its own data,
//   * B/R responses route back to the originating master (no crossing),
//   * the full 4 GiB decode reaches the slave for a high address, so a write
//     to ERROR_ADDR (0xFFFF_FFFC) returns the slave's SLVERR (2'b10), not the
//     interconnect's DECERR (2'b11),
//   * concurrent writes from both masters both complete and land correctly.

module fcapz_axi_interconnect_tb;

    localparam ERROR_ADDR = 32'hFFFF_FFFC;

    reg aclk = 1'b0;
    reg aresetn = 1'b0;
    always #5 aclk = ~aclk;   // 100 MHz

    integer errors = 0;

    // ---- s0 (master 0) driver/monitor ------------------------------------
    reg          s0_awvalid; wire s0_awready;
    reg  [31:0]  s0_awaddr;
    reg          s0_wvalid;  wire s0_wready;
    reg  [31:0]  s0_wdata;
    wire         s0_bvalid;  reg  s0_bready;  wire [1:0] s0_bresp;
    reg          s0_arvalid; wire s0_arready;
    reg  [31:0]  s0_araddr;
    wire         s0_rvalid;  reg  s0_rready;  wire [31:0] s0_rdata; wire [1:0] s0_rresp;

    // ---- s1 (master 1) driver/monitor ------------------------------------
    reg          s1_awvalid; wire s1_awready;
    reg  [31:0]  s1_awaddr;
    reg          s1_wvalid;  wire s1_wready;
    reg  [31:0]  s1_wdata;
    wire         s1_bvalid;  reg  s1_bready;  wire [1:0] s1_bresp;
    reg          s1_arvalid; wire s1_arready;
    reg  [31:0]  s1_araddr;
    wire         s1_rvalid;  reg  s1_rready;  wire [31:0] s1_rdata; wire [1:0] s1_rresp;

    // ---- m0 (shared slave) wires -----------------------------------------
    wire         m0_awvalid, m0_awready;
    wire [31:0]  m0_awaddr;
    wire [7:0]   m0_awlen;   wire [2:0] m0_awsize; wire [1:0] m0_awburst;
    wire         m0_wvalid,  m0_wready;
    wire [31:0]  m0_wdata;   wire [3:0] m0_wstrb;  wire m0_wlast;
    wire         m0_bvalid,  m0_bready; wire [1:0] m0_bresp;
    wire         m0_arvalid, m0_arready;
    wire [31:0]  m0_araddr;
    wire [7:0]   m0_arlen;   wire [2:0] m0_arsize; wire [1:0] m0_arburst;
    wire         m0_rvalid,  m0_rready; wire [31:0] m0_rdata; wire [1:0] m0_rresp; wire m0_rlast;

    // ---- DUT --------------------------------------------------------------
    fcapz_axi_interconnect u_dut (
        // master 0 (s0)
        .s0_axi_awvalid(s0_awvalid), .s0_axi_awready(s0_awready),
        .s0_axi_awaddr(s0_awaddr), .s0_axi_awid(4'd0), .s0_axi_awregion(4'd0),
        .s0_axi_awlen(8'd0), .s0_axi_awsize(3'd2), .s0_axi_awburst(2'b01),
        .s0_axi_awlock(1'b0), .s0_axi_awcache(4'd0), .s0_axi_awqos(4'd0), .s0_axi_awprot(3'd0),
        .s0_axi_wvalid(s0_wvalid), .s0_axi_wready(s0_wready),
        .s0_axi_wdata(s0_wdata), .s0_axi_wstrb(4'hF), .s0_axi_wlast(1'b1),
        .s0_axi_bvalid(s0_bvalid), .s0_axi_bready(s0_bready), .s0_axi_bid(), .s0_axi_bresp(s0_bresp),
        .s0_axi_arvalid(s0_arvalid), .s0_axi_arready(s0_arready),
        .s0_axi_araddr(s0_araddr), .s0_axi_arid(4'd0), .s0_axi_arregion(4'd0),
        .s0_axi_arlen(8'd0), .s0_axi_arsize(3'd2), .s0_axi_arburst(2'b01),
        .s0_axi_arlock(1'b0), .s0_axi_arcache(4'd0), .s0_axi_arqos(4'd0), .s0_axi_arprot(3'd0),
        .s0_axi_rvalid(s0_rvalid), .s0_axi_rready(s0_rready),
        .s0_axi_rdata(s0_rdata), .s0_axi_rid(), .s0_axi_rresp(s0_rresp), .s0_axi_rlast(),
        // master 1 (s1)
        .s1_axi_awvalid(s1_awvalid), .s1_axi_awready(s1_awready),
        .s1_axi_awaddr(s1_awaddr), .s1_axi_awid(4'd0), .s1_axi_awregion(4'd0),
        .s1_axi_awlen(8'd0), .s1_axi_awsize(3'd2), .s1_axi_awburst(2'b01),
        .s1_axi_awlock(1'b0), .s1_axi_awcache(4'd0), .s1_axi_awqos(4'd0), .s1_axi_awprot(3'd0),
        .s1_axi_wvalid(s1_wvalid), .s1_axi_wready(s1_wready),
        .s1_axi_wdata(s1_wdata), .s1_axi_wstrb(4'hF), .s1_axi_wlast(1'b1),
        .s1_axi_bvalid(s1_bvalid), .s1_axi_bready(s1_bready), .s1_axi_bid(), .s1_axi_bresp(s1_bresp),
        .s1_axi_arvalid(s1_arvalid), .s1_axi_arready(s1_arready),
        .s1_axi_araddr(s1_araddr), .s1_axi_arid(4'd0), .s1_axi_arregion(4'd0),
        .s1_axi_arlen(8'd0), .s1_axi_arsize(3'd2), .s1_axi_arburst(2'b01),
        .s1_axi_arlock(1'b0), .s1_axi_arcache(4'd0), .s1_axi_arqos(4'd0), .s1_axi_arprot(3'd0),
        .s1_axi_rvalid(s1_rvalid), .s1_axi_rready(s1_rready),
        .s1_axi_rdata(s1_rdata), .s1_axi_rid(), .s1_axi_rresp(s1_rresp), .s1_axi_rlast(),
        // shared slave (m0)
        .m0_axi_awvalid(m0_awvalid), .m0_axi_awready(m0_awready),
        .m0_axi_awaddr(m0_awaddr), .m0_axi_awid(), .m0_axi_awregion(),
        .m0_axi_awlen(m0_awlen), .m0_axi_awsize(m0_awsize), .m0_axi_awburst(m0_awburst),
        .m0_axi_awlock(), .m0_axi_awcache(), .m0_axi_awqos(), .m0_axi_awprot(),
        .m0_axi_wvalid(m0_wvalid), .m0_axi_wready(m0_wready),
        .m0_axi_wdata(m0_wdata), .m0_axi_wstrb(m0_wstrb), .m0_axi_wlast(m0_wlast),
        .m0_axi_bvalid(m0_bvalid), .m0_axi_bready(m0_bready), .m0_axi_bid(5'd0), .m0_axi_bresp(m0_bresp),
        .m0_axi_arvalid(m0_arvalid), .m0_axi_arready(m0_arready),
        .m0_axi_araddr(m0_araddr), .m0_axi_arid(), .m0_axi_arregion(),
        .m0_axi_arlen(m0_arlen), .m0_axi_arsize(m0_arsize), .m0_axi_arburst(m0_arburst),
        .m0_axi_arlock(), .m0_axi_arcache(), .m0_axi_arqos(), .m0_axi_arprot(),
        .m0_axi_rvalid(m0_rvalid), .m0_axi_rready(m0_rready),
        .m0_axi_rdata(m0_rdata), .m0_axi_rid(5'd0), .m0_axi_rresp(m0_rresp), .m0_axi_rlast(m0_rlast),
        .aclk(aclk), .aresetn(aresetn)
    );

    // ---- shared slave -----------------------------------------------------
    axi4_test_slave #(.NUM_WORDS(16), .ERROR_ADDR(ERROR_ADDR)) u_slave (
        .clk(aclk), .rst(~aresetn),
        .s_axi_awaddr(m0_awaddr), .s_axi_awlen(m0_awlen), .s_axi_awsize(m0_awsize),
        .s_axi_awburst(m0_awburst), .s_axi_awvalid(m0_awvalid), .s_axi_awready(m0_awready),
        .s_axi_wdata(m0_wdata), .s_axi_wstrb(m0_wstrb), .s_axi_wlast(m0_wlast),
        .s_axi_wvalid(m0_wvalid), .s_axi_wready(m0_wready),
        .s_axi_bresp(m0_bresp), .s_axi_bvalid(m0_bvalid), .s_axi_bready(m0_bready),
        .s_axi_araddr(m0_araddr), .s_axi_arlen(m0_arlen), .s_axi_arsize(m0_arsize),
        .s_axi_arburst(m0_arburst), .s_axi_arvalid(m0_arvalid), .s_axi_arready(m0_arready),
        .s_axi_rdata(m0_rdata), .s_axi_rresp(m0_rresp), .s_axi_rlast(m0_rlast),
        .s_axi_rvalid(m0_rvalid), .s_axi_rready(m0_rready)
    );

    // ---- master-0 access tasks -------------------------------------------
    task m0_write(input [31:0] addr, input [31:0] data, output [1:0] resp);
        begin
            @(posedge aclk);
            s0_awaddr <= addr; s0_awvalid <= 1'b1;
            s0_wdata  <= data; s0_wvalid  <= 1'b1;
            fork
                begin : aw0
                    @(posedge aclk); while (!s0_awready) @(posedge aclk);
                    s0_awvalid <= 1'b0;
                end
                begin : w0
                    @(posedge aclk); while (!s0_wready) @(posedge aclk);
                    s0_wvalid <= 1'b0;
                end
            join
            s0_bready <= 1'b1;
            @(posedge aclk); while (!s0_bvalid) @(posedge aclk);
            resp = s0_bresp;
            s0_bready <= 1'b0;
        end
    endtask

    task m0_read(input [31:0] addr, output [31:0] data, output [1:0] resp);
        begin
            @(posedge aclk);
            s0_araddr <= addr; s0_arvalid <= 1'b1;
            @(posedge aclk); while (!s0_arready) @(posedge aclk);
            s0_arvalid <= 1'b0;
            s0_rready  <= 1'b1;
            @(posedge aclk); while (!s0_rvalid) @(posedge aclk);
            data = s0_rdata; resp = s0_rresp;
            s0_rready <= 1'b0;
        end
    endtask

    // ---- master-1 access tasks -------------------------------------------
    task m1_write(input [31:0] addr, input [31:0] data, output [1:0] resp);
        begin
            @(posedge aclk);
            s1_awaddr <= addr; s1_awvalid <= 1'b1;
            s1_wdata  <= data; s1_wvalid  <= 1'b1;
            fork
                begin : aw1
                    @(posedge aclk); while (!s1_awready) @(posedge aclk);
                    s1_awvalid <= 1'b0;
                end
                begin : w1
                    @(posedge aclk); while (!s1_wready) @(posedge aclk);
                    s1_wvalid <= 1'b0;
                end
            join
            s1_bready <= 1'b1;
            @(posedge aclk); while (!s1_bvalid) @(posedge aclk);
            resp = s1_bresp;
            s1_bready <= 1'b0;
        end
    endtask

    task m1_read(input [31:0] addr, output [31:0] data, output [1:0] resp);
        begin
            @(posedge aclk);
            s1_araddr <= addr; s1_arvalid <= 1'b1;
            @(posedge aclk); while (!s1_arready) @(posedge aclk);
            s1_arvalid <= 1'b0;
            s1_rready  <= 1'b1;
            @(posedge aclk); while (!s1_rvalid) @(posedge aclk);
            data = s1_rdata; resp = s1_rresp;
            s1_rready <= 1'b0;
        end
    endtask

    task check32(input [255:0] name, input [31:0] got, input [31:0] exp);
        begin
            if (got !== exp) begin
                $display("  FAIL %0s: got 0x%08x exp 0x%08x", name, got, exp);
                errors = errors + 1;
            end else
                $display("  ok   %0s = 0x%08x", name, got);
        end
    endtask

    task check2(input [255:0] name, input [1:0] got, input [1:0] exp);
        begin
            if (got !== exp) begin
                $display("  FAIL %0s: got %b exp %b", name, got, exp);
                errors = errors + 1;
            end else
                $display("  ok   %0s = %b", name, got);
        end
    endtask

    reg [31:0] rd0, rd1;
    reg [1:0]  rp0, rp1;

    initial begin
        s0_awvalid=0; s0_wvalid=0; s0_bready=0; s0_arvalid=0; s0_rready=0;
        s1_awvalid=0; s1_wvalid=0; s1_bready=0; s1_arvalid=0; s1_rready=0;
        s0_awaddr=0; s0_wdata=0; s0_araddr=0;
        s1_awaddr=0; s1_wdata=0; s1_araddr=0;
        repeat (5) @(posedge aclk);
        aresetn = 1'b1;
        repeat (3) @(posedge aclk);

        $display("[T1] master0 write+read 0x40000000");
        m0_write(32'h4000_0000, 32'hCAFE_F00D, rp0); check2("m0 bresp", rp0, 2'b00);
        m0_read (32'h4000_0000, rd0, rp0);           check32("m0 rdata", rd0, 32'hCAFE_F00D);
                                                     check2 ("m0 rresp", rp0, 2'b00);

        $display("[T2] master1 write+read 0x00000004 (different word)");
        m1_write(32'h0000_0004, 32'h1234_ABCD, rp1); check2("m1 bresp", rp1, 2'b00);
        m1_read (32'h0000_0004, rd1, rp1);           check32("m1 rdata", rd1, 32'h1234_ABCD);
                                                     check2 ("m1 rresp", rp1, 2'b00);

        $display("[T3] master0 still reads its own word (no crossing)");
        m0_read (32'h4000_0000, rd0, rp0);           check32("m0 reread", rd0, 32'hCAFE_F00D);

        $display("[T4] full-4GiB decode: bridge writes ERROR_ADDR 0xFFFFFFFC");
        m1_write(ERROR_ADDR, 32'hDEAD_BEEF, rp1);
        // SLVERR (2'b10) proves the write reached the real slave; DECERR
        // (2'b11) would mean the interconnect black-holed the high address.
        check2("error-addr bresp==SLVERR", rp1, 2'b10);

        $display("[T5] concurrent writes from both masters to distinct words");
        fork
            m0_write(32'h4000_0008, 32'hA5A5_0001, rp0); // word 2
            m1_write(32'h4000_000C, 32'h5A5A_0002, rp1); // word 3
        join
        check2("concurrent m0 bresp", rp0, 2'b00);
        check2("concurrent m1 bresp", rp1, 2'b00);
        m0_read (32'h4000_0008, rd0, rp0); check32("concurrent m0 word", rd0, 32'hA5A5_0001);
        m1_read (32'h4000_000C, rd1, rp1); check32("concurrent m1 word", rd1, 32'h5A5A_0002);

        repeat (5) @(posedge aclk);
        if (errors == 0)
            $display("\nRESULT: PASS (all checks ok)");
        else
            $display("\nRESULT: FAIL (%0d error(s))", errors);
        $finish;
    end

    // watchdog
    initial begin
        #200000;
        $display("\nRESULT: FAIL (timeout)");
        $finish;
    end

endmodule
