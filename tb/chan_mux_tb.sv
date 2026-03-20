// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Channel mux testbench — verifies NUM_CHANNELS > 1 behavior.
// Instantiates fcapz_ela with NUM_CHANNELS=3, SAMPLE_W=8, DEPTH=16.
// Each channel carries a distinct fixed pattern; the test selects each
// channel in turn, arms, triggers, and verifies the captured values.

module chan_mux_tb;
    localparam int SAMPLE_W    = 8;
    localparam int DEPTH       = 16;
    localparam int NUM_CHANNELS = 3;

    // Channel patterns (distinct per channel)
    localparam [SAMPLE_W-1:0] CH0_VAL = 8'hAA;
    localparam [SAMPLE_W-1:0] CH1_VAL = 8'hBB;
    localparam [SAMPLE_W-1:0] CH2_VAL = 8'hCC;

    logic sample_clk = 1'b0;
    logic jtag_clk   = 1'b0;
    logic sample_rst = 1'b1;
    logic jtag_rst   = 1'b1;

    // Wide probe: channel 2 | channel 1 | channel 0  (ch0 at LSB)
    logic [NUM_CHANNELS*SAMPLE_W-1:0] probe_in;

    logic        jtag_wr_en = 1'b0;
    logic        jtag_rd_en = 1'b0;
    logic [15:0] jtag_addr  = '0;
    logic [31:0] jtag_wdata = '0;
    logic [31:0] jtag_rdata;

    logic [$clog2(DEPTH)-1:0] burst_rd_addr = '0;
    wire  [SAMPLE_W-1:0]      burst_rd_data;
    wire                       burst_start;
    wire  [$clog2(DEPTH)-1:0]  burst_start_ptr;

    fcapz_ela #(
        .SAMPLE_W    (SAMPLE_W),
        .DEPTH       (DEPTH),
        .NUM_CHANNELS(NUM_CHANNELS)
    ) dut (
        .sample_clk      (sample_clk),
        .sample_rst      (sample_rst),
        .probe_in        (probe_in),
        .trigger_in      (1'b0),
        .trigger_out     (),
        .jtag_clk        (jtag_clk),
        .jtag_rst        (jtag_rst),
        .jtag_wr_en      (jtag_wr_en),
        .jtag_rd_en      (jtag_rd_en),
        .jtag_addr       (jtag_addr),
        .jtag_wdata      (jtag_wdata),
        .jtag_rdata      (jtag_rdata),
        .burst_rd_addr   (burst_rd_addr),
        .burst_rd_data   (burst_rd_data),
        .burst_start     (burst_start),
        .burst_start_ptr (burst_start_ptr)
    );

    always #5  sample_clk = ~sample_clk;
    always #7  jtag_clk   = ~jtag_clk;

    // Drive fixed patterns on all channels simultaneously
    assign probe_in = {CH2_VAL, CH1_VAL, CH0_VAL};

    // ---- Helpers ------------------------------------------------------------

    task automatic jtag_write(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr  <= addr; jtag_wdata <= data; jtag_wr_en <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en <= 1'b0;
    endtask

    task automatic jtag_read(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr <= addr; jtag_rd_en <= 1'b1;
        @(posedge jtag_clk);
        jtag_rd_en <= 1'b0;
        repeat (8) @(posedge jtag_clk);
        data = jtag_rdata;
    endtask

    // Arm, wait for done, read back the first captured sample
    task automatic capture_and_read(output [31:0] sample);
        int cycles;
        logic [31:0] status;
        // Trigger on any value (mask=0 means always match)
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'h0);    // TRIG_VALUE
        jtag_write(16'h0028, 32'h0);    // TRIG_MASK = 0 → always trigger
        jtag_write(16'h0014, 32'd0);    // PRETRIG_LEN = 0
        jtag_write(16'h0018, 32'd2);    // POSTTRIG_LEN = 2
        jtag_write(16'h0004, 32'h1);    // ARM
        // Wait for done
        cycles = 0;
        while (cycles < 100) begin @(posedge sample_clk); cycles++; end
        // Read first sample
        jtag_read(16'h0100, sample);
    endtask

    // ---- Test infrastructure ------------------------------------------------

    int pass_count = 0;
    int fail_count = 0;

    task automatic check(input string label, input logic cond);
        if (cond) begin $display("  PASS: %s", label); pass_count++; end
        else       begin $display("  FAIL: %s", label); fail_count++; end
    endtask

    // ---- Tests --------------------------------------------------------------

    initial begin
        logic [31:0] rdata;
        logic [31:0] sample;

        // Release reset
        repeat (4) @(posedge sample_clk);
        sample_rst <= 1'b0;
        repeat (2) @(posedge jtag_clk);
        jtag_rst   <= 1'b0;
        repeat (4) @(posedge jtag_clk);

        // ---- Test 1: NUM_CHANNELS register ----------------------------------
        $display("\n=== Test 1: NUM_CHANNELS register ===");
        jtag_read(16'h00A4, rdata);
        check($sformatf("NUM_CHANNELS = %0d", rdata), rdata == NUM_CHANNELS);

        // ---- Test 2: CHAN_SEL default = 0 -----------------------------------
        $display("\n=== Test 2: CHAN_SEL default = 0 ===");
        jtag_read(16'h00A0, rdata);
        check("CHAN_SEL reads back 0 after reset", rdata == 32'h0);

        // ---- Test 3: Capture channel 0 (0xAA) -------------------------------
        $display("\n=== Test 3: Capture channel 0 (expect 0xAA) ===");
        jtag_write(16'h00A0, 32'd0);   // select channel 0
        jtag_write(16'h0004, 32'h2);   // RESET
        repeat (10) @(posedge sample_clk);
        capture_and_read(sample);
        check("Channel 0 sample = 0xAA", sample[7:0] == CH0_VAL);

        // ---- Test 4: Capture channel 1 (0xBB) -------------------------------
        $display("\n=== Test 4: Capture channel 1 (expect 0xBB) ===");
        jtag_write(16'h00A0, 32'd1);   // select channel 1
        jtag_write(16'h0004, 32'h2);   // RESET
        repeat (10) @(posedge sample_clk);
        capture_and_read(sample);
        check("Channel 1 sample = 0xBB", sample[7:0] == CH1_VAL);

        // ---- Test 5: Capture channel 2 (0xCC) -------------------------------
        $display("\n=== Test 5: Capture channel 2 (expect 0xCC) ===");
        jtag_write(16'h00A0, 32'd2);   // select channel 2
        jtag_write(16'h0004, 32'h2);   // RESET
        repeat (10) @(posedge sample_clk);
        capture_and_read(sample);
        check("Channel 2 sample = 0xCC", sample[7:0] == CH2_VAL);

        // ---- Test 6: CHAN_SEL write/readback ---------------------------------
        $display("\n=== Test 6: CHAN_SEL write/readback ===");
        jtag_write(16'h00A0, 32'd1);
        jtag_read(16'h00A0, rdata);
        check("CHAN_SEL readback = 1", rdata == 32'd1);
        jtag_write(16'h00A0, 32'd0);
        jtag_read(16'h00A0, rdata);
        check("CHAN_SEL readback = 0", rdata == 32'd0);

        // ---- Test 7: Out-of-range channel clamped to 0 ----------------------
        $display("\n=== Test 7: Out-of-range channel clamped to 0 ===");
        jtag_write(16'h00A0, 32'd7);   // 7 >= NUM_CHANNELS=3 → clamped to 0 on arm
        jtag_write(16'h0004, 32'h2);   // RESET
        repeat (10) @(posedge sample_clk);
        capture_and_read(sample);
        check("Out-of-range channel → clamped to ch0 (0xAA)", sample[7:0] == CH0_VAL);

        // ---- Summary -------------------------------------------------------
        $display("\n=== Summary: %0d passed, %0d failed ===", pass_count, fail_count);
        if (fail_count > 0)
            $fatal(1, "Channel mux testbench: failures detected");
        $finish;
    end

endmodule
