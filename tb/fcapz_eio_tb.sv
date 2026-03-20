// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// EIO core simulation testbench.
// Exercises read-input / write-output paths, CDC sync, and register map.

module fcapz_eio_tb;

    localparam int IN_W  = 16;
    localparam int OUT_W = 12;

    logic jtag_clk  = 1'b0;
    logic jtag_rst  = 1'b1;
    logic fabric_clk = 1'b0;  // simulates probe_in source clock

    // DUT ports
    logic [IN_W-1:0]  probe_in  = '0;
    wire  [OUT_W-1:0] probe_out;

    logic        jtag_wr_en = 1'b0;
    logic [15:0] jtag_addr  = '0;
    logic [31:0] jtag_wdata = '0;
    logic [31:0] jtag_rdata;

    fcapz_eio #(
        .IN_W (IN_W),
        .OUT_W(OUT_W)
    ) dut (
        .probe_in  (probe_in),
        .probe_out (probe_out),
        .jtag_clk  (jtag_clk),
        .jtag_rst  (jtag_rst),
        .jtag_wr_en(jtag_wr_en),
        .jtag_addr (jtag_addr),
        .jtag_wdata(jtag_wdata),
        .jtag_rdata(jtag_rdata)
    );

    // Clocks
    always #7  jtag_clk   = ~jtag_clk;    // ~71 MHz  (JTAG TCK)
    always #5  fabric_clk = ~fabric_clk;  // 100 MHz  (fabric domain)

    // ---- Helpers ------------------------------------------------------------

    task automatic vio_write(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr  <= addr;
        jtag_wdata <= data;
        jtag_wr_en <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en <= 1'b0;
    endtask

    task automatic vio_read(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr <= addr;
        @(posedge jtag_clk);
        data = jtag_rdata;
    endtask

    // ---- Test infrastructure ------------------------------------------------

    int pass_count = 0;
    int fail_count = 0;

    task automatic check(input string label, input logic cond);
        if (cond) begin
            $display("  PASS: %s", label);
            pass_count++;
        end else begin
            $display("  FAIL: %s", label);
            fail_count++;
        end
    endtask

    // ---- Tests --------------------------------------------------------------

    initial begin
        logic [31:0] rdata;
        logic [31:0] expected;

        // Release reset
        repeat (3) @(posedge jtag_clk);
        jtag_rst <= 1'b0;
        repeat (2) @(posedge jtag_clk);

        // ---- Test 1: Identity registers ------------------------------------
        $display("\n=== Test 1: Identity registers ===");

        vio_read(16'h0000, rdata);
        check("EIO_ID = 0x56494F01", rdata == 32'h5649_4F01);

        vio_read(16'h0004, rdata);
        check($sformatf("EIO_IN_W = %0d", rdata), rdata == IN_W);

        vio_read(16'h0008, rdata);
        check($sformatf("EIO_OUT_W = %0d", rdata), rdata == OUT_W);

        // ---- Test 2: Output register write/readback ------------------------
        $display("\n=== Test 2: Output write/readback ===");

        vio_write(16'h0100, 32'hABC);   // OUT[0] = 0xABC (12-bit output)
        #1;  // allow NBA to settle before reading wire
        vio_read(16'h0100, rdata);
        check("OUT[0] readback = 0xABC", rdata == 32'hABC);
        check("probe_out = 12'hABC", probe_out == 12'hABC);

        vio_write(16'h0100, 32'h000);
        #1;
        vio_read(16'h0100, rdata);
        check("OUT[0] cleared", rdata == 32'h000);
        check("probe_out cleared", probe_out == 12'h000);

        vio_write(16'h0100, 32'hFFF);   // all 12 bits set
        #1;
        check("probe_out all ones", probe_out == 12'hFFF);

        // ---- Test 3: Output reset clears registers -------------------------
        $display("\n=== Test 3: Reset clears outputs ===");
        vio_write(16'h0100, 32'h555);
        jtag_rst <= 1'b1;
        repeat (2) @(posedge jtag_clk);
        jtag_rst <= 1'b0;
        repeat (2) @(posedge jtag_clk);

        #1;
        vio_read(16'h0100, rdata);
        check("OUT[0] = 0 after reset", rdata == 32'h0);
        check("probe_out = 0 after reset", probe_out == 12'h0);

        // ---- Test 4: Input probe CDC (synchronised read) -------------------
        $display("\n=== Test 4: Input probe read (after CDC) ===");

        // Drive probe_in in jtag_clk domain (simplification: same clock here)
        probe_in <= 16'hCAFE;
        repeat (4) @(posedge jtag_clk);   // allow 2-FF sync to settle

        vio_read(16'h0010, rdata);         // IN[0] = bits[15:0]
        check("IN[0] = 0xCAFE", rdata == 32'hCAFE);

        probe_in <= 16'h1234;
        repeat (4) @(posedge jtag_clk);

        vio_read(16'h0010, rdata);
        check("IN[0] = 0x1234 after change", rdata == 32'h1234);

        // ---- Test 5: Multi-word output (IN_W=16 fits in one word) ----------
        $display("\n=== Test 5: Wide probe (IN_W=16, one word) ===");
        probe_in <= 16'hFFFF;
        repeat (4) @(posedge jtag_clk);
        vio_read(16'h0010, rdata);
        check("IN[0] = 0xFFFF (all bits)", rdata == 32'hFFFF);

        probe_in <= 16'h0001;
        repeat (4) @(posedge jtag_clk);
        vio_read(16'h0010, rdata);
        check("IN[0] = 0x0001 (LSB only)", rdata == 32'h0001);

        // ---- Test 6: Out-of-range address returns 0 ------------------------
        $display("\n=== Test 6: Unknown address returns 0 ===");
        vio_read(16'h0200, rdata);
        check("Unknown addr reads 0", rdata == 32'h0);

        // ---- Test 7: Bit-manipulation via write ----------------------------
        $display("\n=== Test 7: Bit-level output control ===");
        vio_write(16'h0100, 32'h000);
        vio_read(16'h0100, rdata);
        // set bit 3
        vio_write(16'h0100, rdata | 32'h8);
        vio_read(16'h0100, rdata);
        check("Bit 3 set", rdata[3] == 1'b1);
        check("Other bits unchanged", (rdata & 32'hFFFFFFF7) == 32'h0);
        // clear bit 3
        vio_write(16'h0100, rdata & ~32'h8);
        vio_read(16'h0100, rdata);
        check("Bit 3 cleared", rdata[3] == 1'b0);

        // ---- Summary -------------------------------------------------------
        $display("\n=== Summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count > 0)
            $fatal(1, "EIO testbench: failures detected");
        $finish;
    end

endmodule
