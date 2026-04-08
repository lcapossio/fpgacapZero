// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Project-wide version + per-core identity defines (auto-generated from
// the canonical VERSION file).  Pulling them in here means Test 1 stays
// in sync with the RTL automatically; bumping VERSION + re-running
// tools/sync_version.py is the only place a release version lives.
`include "fcapz_version.vh"

// ELA core simulation testbench.
// Targets iverilog -g2012; concurrent SVA assertions are gated behind
// `ifdef SVA_ENABLED so the file compiles cleanly without a full SV tool.

module fcapz_ela_tb;
    localparam int SAMPLE_W = 8;
    localparam int DEPTH    = 16;

    logic sample_clk = 1'b0;
    logic jtag_clk   = 1'b0;
    logic sample_rst = 1'b1;
    logic jtag_rst   = 1'b1;

    logic [SAMPLE_W-1:0] probe_in = '0;

    logic        jtag_wr_en = 1'b0;
    logic        jtag_rd_en = 1'b0;
    logic [15:0] jtag_addr  = '0;
    logic [31:0] jtag_wdata = '0;
    logic [31:0] jtag_rdata;

    // Burst read port (driven to 0; burst read tested separately)
    logic [$clog2(DEPTH)-1:0] burst_rd_addr = '0;
    wire  [SAMPLE_W-1:0]      burst_rd_data;
    wire                       burst_start;
    wire  [$clog2(DEPTH)-1:0]  burst_start_ptr;

    // External trigger signals for default DUT
    logic trigger_in_dut = 1'b0;
    wire  trigger_out_dut;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .DECIM_EN(1),
        .EXT_TRIG_EN(1)
    ) dut (
        .sample_clk      (sample_clk),
        .sample_rst      (sample_rst),
        .probe_in        (probe_in),
        .trigger_in      (trigger_in_dut),
        .trigger_out     (trigger_out_dut),
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

    // ==== DUT2: Timestamp-enabled instance (TIMESTAMP_W=32) ====
    logic [31:0] jtag_rdata_ts;
    logic        jtag_wr_en_ts = 1'b0;
    logic        jtag_rd_en_ts = 1'b0;
    logic [15:0] jtag_addr_ts  = '0;
    logic [31:0] jtag_wdata_ts = '0;
    logic [SAMPLE_W-1:0] probe_in_ts = '0;
    logic [$clog2(DEPTH)-1:0] burst_rd_addr_ts = '0;
    wire  [SAMPLE_W-1:0]      burst_rd_data_ts;
    wire                       burst_start_ts;
    wire  [$clog2(DEPTH)-1:0]  burst_start_ptr_ts;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .DECIM_EN(1),
        .TIMESTAMP_W(32)
    ) dut_ts (
        .sample_clk      (sample_clk),
        .sample_rst      (sample_rst),
        .probe_in        (probe_in_ts),
        .trigger_in      (1'b0),
        .trigger_out     (),
        .jtag_clk        (jtag_clk),
        .jtag_rst        (jtag_rst),
        .jtag_wr_en      (jtag_wr_en_ts),
        .jtag_rd_en      (jtag_rd_en_ts),
        .jtag_addr       (jtag_addr_ts),
        .jtag_wdata      (jtag_wdata_ts),
        .jtag_rdata      (jtag_rdata_ts),
        .burst_rd_addr   (burst_rd_addr_ts),
        .burst_rd_data   (burst_rd_data_ts),
        .burst_start     (burst_start_ts),
        .burst_start_ptr (burst_start_ptr_ts)
    );

    // ==== DUT3: Segmented memory instance (NUM_SEGMENTS=4) ====
    logic [31:0] jtag_rdata_seg;
    logic        jtag_wr_en_seg = 1'b0;
    logic        jtag_rd_en_seg = 1'b0;
    logic [15:0] jtag_addr_seg  = '0;
    logic [31:0] jtag_wdata_seg = '0;
    logic [SAMPLE_W-1:0] probe_in_seg = '0;
    logic [$clog2(DEPTH)-1:0] burst_rd_addr_seg = '0;
    wire  [SAMPLE_W-1:0]      burst_rd_data_seg;
    wire                       burst_start_seg;
    wire  [$clog2(DEPTH)-1:0]  burst_start_ptr_seg;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .NUM_SEGMENTS(4)
    ) dut_seg (
        .sample_clk      (sample_clk),
        .sample_rst      (sample_rst),
        .probe_in        (probe_in_seg),
        .trigger_in      (1'b0),
        .trigger_out     (),
        .jtag_clk        (jtag_clk),
        .jtag_rst        (jtag_rst),
        .jtag_wr_en      (jtag_wr_en_seg),
        .jtag_rd_en      (jtag_rd_en_seg),
        .jtag_addr       (jtag_addr_seg),
        .jtag_wdata      (jtag_wdata_seg),
        .jtag_rdata      (jtag_rdata_seg),
        .burst_rd_addr   (burst_rd_addr_seg),
        .burst_rd_data   (burst_rd_data_seg),
        .burst_start     (burst_start_seg),
        .burst_start_ptr (burst_start_ptr_seg)
    );

    // ==== DUT4: Probe mux instance (PROBE_MUX_W=32, SAMPLE_W=8 => 4 slices) ====
    logic [31:0] jtag_rdata_pmux;
    logic        jtag_wr_en_pmux = 1'b0;
    logic        jtag_rd_en_pmux = 1'b0;
    logic [15:0] jtag_addr_pmux  = '0;
    logic [31:0] jtag_wdata_pmux = '0;
    logic [31:0] probe_in_pmux = '0;  // 32-bit wide probe bus
    logic [$clog2(DEPTH)-1:0] burst_rd_addr_pmux = '0;
    wire  [SAMPLE_W-1:0]      burst_rd_data_pmux;
    wire                       burst_start_pmux;
    wire  [$clog2(DEPTH)-1:0]  burst_start_ptr_pmux;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .PROBE_MUX_W(32)
    ) dut_pmux (
        .sample_clk      (sample_clk),
        .sample_rst      (sample_rst),
        .probe_in        (probe_in_pmux),
        .trigger_in      (1'b0),
        .trigger_out     (),
        .jtag_clk        (jtag_clk),
        .jtag_rst        (jtag_rst),
        .jtag_wr_en      (jtag_wr_en_pmux),
        .jtag_rd_en      (jtag_rd_en_pmux),
        .jtag_addr       (jtag_addr_pmux),
        .jtag_wdata      (jtag_wdata_pmux),
        .jtag_rdata      (jtag_rdata_pmux),
        .burst_rd_addr   (burst_rd_addr_pmux),
        .burst_rd_data   (burst_rd_data_pmux),
        .burst_start     (burst_start_pmux),
        .burst_start_ptr (burst_start_ptr_pmux)
    );

    // Clocks
    always #5  sample_clk = ~sample_clk; // 100 MHz
    always #7  jtag_clk   = ~jtag_clk;   // ~71 MHz

    // ---- JTAG helpers -------------------------------------------------------

    task automatic jtag_write(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr  <= addr;
        jtag_wdata <= data;
        jtag_wr_en <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en <= 1'b0;
    endtask

    task automatic jtag_read(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr  <= addr;
        jtag_rd_en <= 1'b1;
        @(posedge jtag_clk);
        jtag_rd_en <= 1'b0;
        repeat (8) @(posedge jtag_clk);  // allow CDC handshake
        data = jtag_rdata;
    endtask

    // Helpers for dut_ts
    task automatic jtag_write_ts(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_ts  <= addr;
        jtag_wdata_ts <= data;
        jtag_wr_en_ts <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en_ts <= 1'b0;
    endtask

    task automatic jtag_read_ts(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_ts  <= addr;
        jtag_rd_en_ts <= 1'b1;
        @(posedge jtag_clk);
        jtag_rd_en_ts <= 1'b0;
        repeat (8) @(posedge jtag_clk);
        data = jtag_rdata_ts;
    endtask

    // Helpers for dut_pmux
    task automatic jtag_write_pmux(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_pmux  <= addr;
        jtag_wdata_pmux <= data;
        jtag_wr_en_pmux <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en_pmux <= 1'b0;
    endtask

    task automatic jtag_read_pmux(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_pmux  <= addr;
        jtag_rd_en_pmux <= 1'b1;
        @(posedge jtag_clk);
        jtag_rd_en_pmux <= 1'b0;
        repeat (8) @(posedge jtag_clk);
        data = jtag_rdata_pmux;
    endtask

    // Helpers for dut_seg
    task automatic jtag_write_seg(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_seg  <= addr;
        jtag_wdata_seg <= data;
        jtag_wr_en_seg <= 1'b1;
        @(posedge jtag_clk);
        jtag_wr_en_seg <= 1'b0;
    endtask

    task automatic jtag_read_seg(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        jtag_addr_seg  <= addr;
        jtag_rd_en_seg <= 1'b1;
        @(posedge jtag_clk);
        jtag_rd_en_seg <= 1'b0;
        repeat (8) @(posedge jtag_clk);
        data = jtag_rdata_seg;
    endtask

    // ---- Procedural assertions (iverilog-compatible) ------------------------

    always @(posedge sample_clk) begin
        if (!sample_rst) begin
            // post_count must not exceed posttrig_len+1
            if (dut.armed && dut.triggered) begin
                assert (dut.post_count <= dut.posttrig_len + 1)
                    else $error("ASSERT: post_count %0d > posttrig_len+1 %0d",
                                dut.post_count, dut.posttrig_len + 1);
            end
        end
    end

`ifdef SVA_ENABLED
    property armed_clears_on_done;
        @(posedge sample_clk) disable iff (sample_rst)
        $rose(dut.done) |-> !dut.armed;
    endproperty
    assert property (armed_clears_on_done)
        else $error("ASSERT: armed not cleared when done asserted");

    property done_after_triggered;
        @(posedge sample_clk) disable iff (sample_rst)
        $rose(dut.done) |-> dut.triggered;
    endproperty
    assert property (done_after_triggered)
        else $error("ASSERT: done asserted before triggered");

    property capture_len_correct;
        @(posedge sample_clk) disable iff (sample_rst)
        $rose(dut.triggered) |->
            (dut.capture_len == dut.pretrig_len + dut.posttrig_len + 32'd1);
    endproperty
    assert property (capture_len_correct)
        else $error("ASSERT: capture_len mismatch");
`endif

    // ---- Test infrastructure ------------------------------------------------

    int test_pass_count = 0;
    int test_fail_count = 0;

    task automatic check(input string label, input logic cond);
        if (cond) begin
            $display("  PASS: %s", label);
            test_pass_count++;
        end else begin
            $display("  FAIL: %s", label);
            test_fail_count++;
        end
    endtask

    // ---- Test scenarios -----------------------------------------------------

    initial begin
        int          cycles;
        int          i;
        logic [31:0] status;
        logic [31:0] sample_word;
        logic [31:0] version;
        logic [31:0] sample_w_reg;
        logic [31:0] depth_reg;
        logic [31:0] cap_len;
        logic [31:0] features;
        logic [31:0] ts_val, ts_prev;
        logic [31:0] seg_status;

        // Release reset
        repeat (4) @(posedge sample_clk);
        sample_rst <= 1'b0;
        repeat (2) @(posedge jtag_clk);
        jtag_rst <= 1'b0;
        repeat (4) @(posedge jtag_clk);

        // ---- Test 1: Identity registers ------------------------------------
        // Both the RTL and this testbench reference `FCAPZ_ELA_VERSION_REG
        // from rtl/fcapz_version.vh, so bumping VERSION updates both
        // automatically with one git diff.
        $display("\n=== Test 1: Identity registers (VERSION = %s) ===",
                 `FCAPZ_VERSION_STRING);
        jtag_read(16'h0000, version);
        check("VERSION matches `FCAPZ_ELA_VERSION_REG",
              version == `FCAPZ_ELA_VERSION_REG);
        check("VERSION core_id == `FCAPZ_ELA_CORE_ID ('LA')",
              version[15:0]  == `FCAPZ_ELA_CORE_ID);
        check("VERSION minor   == `FCAPZ_VERSION_MINOR",
              version[23:16] == `FCAPZ_VERSION_MINOR);
        check("VERSION major   == `FCAPZ_VERSION_MAJOR",
              version[31:24] == `FCAPZ_VERSION_MAJOR);
        jtag_read(16'h000C, sample_w_reg);
        check($sformatf("SAMPLE_W = %0d", sample_w_reg), sample_w_reg == SAMPLE_W);
        jtag_read(16'h0010, depth_reg);
        check($sformatf("DEPTH = %0d", depth_reg), depth_reg == DEPTH);

        // ---- Test 2: Register round-trip -----------------------------------
        $display("\n=== Test 2: Register round-trip ===");
        jtag_write(16'h0024, 32'hDEAD_BEEF);
        jtag_read(16'h0024, sample_word);
        check("TRIG_VALUE round-trip", sample_word == 32'hDEAD_BEEF);

        jtag_write(16'h0028, 32'h5A5A_5A5A);
        jtag_read(16'h0028, sample_word);
        check("TRIG_MASK round-trip", sample_word == 32'h5A5A_5A5A);

        // ---- Test 3: Value-match capture -----------------------------------
        $display("\n=== Test 3: Value-match capture ===");
        jtag_write(16'h0014, 32'd2);    // PRETRIG_LEN
        jtag_write(16'h0018, 32'd3);    // POSTTRIG_LEN
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'd8);    // TRIG_VALUE
        jtag_write(16'h0028, 32'hFF);   // TRIG_MASK
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        repeat (13) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Status.done set",      status[2] == 1'b1);
        check("Status.triggered set", status[1] == 1'b1);
        check("Status.armed cleared", status[0] == 1'b0);
        check("Status.overflow clear",status[3] == 1'b0);

        jtag_read(16'h001C, cap_len);
        check($sformatf("CAPTURE_LEN = %0d (expect 6)", cap_len), cap_len == 6);

        $display("  Captured samples:");
        for (i = 0; i < 6; i++) begin
            jtag_read(16'h0100 + i*4, sample_word);
            $display("    DATA[%0d] = 0x%02x", i, sample_word[SAMPLE_W-1:0]);
        end

        // ---- Test 4: Edge-detect trigger -----------------------------------
        $display("\n=== Test 4: Edge-detect trigger ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h0014, 32'd1);    // PRETRIG_LEN
        jtag_write(16'h0018, 32'd2);    // POSTTRIG_LEN
        jtag_write(16'h0020, 32'h2);    // TRIG_MODE: edge_detect
        jtag_write(16'h0024, 32'h0);
        jtag_write(16'h0028, 32'h01);   // detect edge on bit 0
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = 8'h00;
        repeat (3) @(posedge sample_clk);
        probe_in <= 8'h01;
        @(posedge sample_clk);
        probe_in <= 8'h03;
        @(posedge sample_clk);
        probe_in <= 8'h07;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Edge trigger: done",      status[2] == 1'b1);
        check("Edge trigger: triggered", status[1] == 1'b1);

        // ---- Test 5: Overflow detection ------------------------------------
        $display("\n=== Test 5: Overflow detection ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h0014, 32'd8);    // PRETRIG_LEN
        jtag_write(16'h0018, 32'd8);    // POSTTRIG_LEN  (8+8+1=17 > DEPTH=16)
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'd5);
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = 8'h00;
        repeat (20) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Overflow: overflow flag set", status[3] == 1'b1);

        // ---- Test 6: Reset clears state ------------------------------------
        $display("\n=== Test 6: Reset clears state ===");
        jtag_write(16'h0004, 32'h2);    // CTRL.reset
        repeat (10) @(posedge sample_clk);

        jtag_read(16'h0008, status);
        check("Reset: armed=0",    status[0] == 1'b0);
        check("Reset: triggered=0",status[1] == 1'b0);
        check("Reset: done=0",     status[2] == 1'b0);
        check("Reset: overflow=0", status[3] == 1'b0);

        // ---- Test 7: Features register (default DUT) -----------------------
        $display("\n=== Test 7: Features register ===");
        jtag_read(16'h003C, features);
        check("FEATURES[5]=HAS_DECIM",     features[5] == 1'b1);
        check("FEATURES[6]=HAS_EXT_TRIG",  features[6] == 1'b1);
        check("FEATURES[7]=0 (no TS)",     features[7] == 1'b0);
        check("FEATURES[23:16]=1 (NUM_SEG)", features[23:16] == 8'd1);

        // ---- Test 8: Decimation register round-trip ------------------------
        $display("\n=== Test 8: Decimation register round-trip ===");
        jtag_write(16'h00B0, 32'h00ABCDEF);
        jtag_read(16'h00B0, sample_word);
        check("DECIM round-trip (24-bit)", sample_word == 32'h00ABCDEF);

        // ---- Test 9: DECIM=0 regression (every sample stored) --------------
        $display("\n=== Test 9: DECIM=0 regression ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B0, 32'd0);    // DECIM=0 (every cycle)
        jtag_write(16'h0014, 32'd2);    // PRETRIG_LEN
        jtag_write(16'h0018, 32'd3);    // POSTTRIG_LEN
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'd8);    // TRIG_VALUE
        jtag_write(16'h0028, 32'hFF);   // TRIG_MASK
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        repeat (13) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("DECIM=0: done", status[2] == 1'b1);
        jtag_read(16'h001C, cap_len);
        check($sformatf("DECIM=0: CAPTURE_LEN=%0d (expect 6)", cap_len), cap_len == 6);

        // ---- Test 10: DECIM=3 (every 4th sample stored) -------------------
        $display("\n=== Test 10: DECIM=3 (store every 4th) ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B0, 32'd3);    // DECIM=3 (store every 4th cycle)
        jtag_write(16'h0014, 32'd1);    // PRETRIG_LEN
        jtag_write(16'h0018, 32'd2);    // POSTTRIG_LEN
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'd16);   // TRIG_VALUE = 16
        jtag_write(16'h0028, 32'hFF);   // TRIG_MASK
        jtag_write(16'h0004, 32'h1);    // ARM

        // Drive incrementing probe: 0, 1, 2, ...
        // Trigger fires at probe=16.  With DECIM=3, samples stored are every 4th cycle.
        probe_in = '0;
        repeat (60) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end

        cycles = 0;
        while (cycles < 200) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("DECIM=3: done", status[2] == 1'b1);
        jtag_read(16'h001C, cap_len);
        check($sformatf("DECIM=3: CAPTURE_LEN=%0d (expect 4)", cap_len), cap_len == 4);

        // ---- Test 11: Ext trigger disabled ---------------------------------
        $display("\n=== Test 11: Ext trigger disabled ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B0, 32'd0);    // DECIM=0
        jtag_write(16'h00B4, 32'd0);    // EXT_TRIG disabled
        jtag_write(16'h0014, 32'd1);
        jtag_write(16'h0018, 32'd2);
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'd5);
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        trigger_in_dut = 1'b1;  // ext trigger asserted but disabled
        repeat (10) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end
        trigger_in_dut = 1'b0;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Ext disabled: done (internal trigger hit)", status[2] == 1'b1);

        // ---- Test 12: Ext trigger OR mode ----------------------------------
        $display("\n=== Test 12: Ext trigger OR mode ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B0, 32'd0);    // DECIM=0
        jtag_write(16'h00B4, 32'd1);    // EXT_TRIG = OR
        jtag_write(16'h0014, 32'd0);
        jtag_write(16'h0018, 32'd2);
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'hFF);   // value_match = 0xFF (won't match any probe)
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = 8'h01;
        repeat (5) @(posedge sample_clk);
        // Assert ext trigger to fire via OR mode
        trigger_in_dut = 1'b1;
        repeat (3) @(posedge sample_clk);
        trigger_in_dut = 1'b0;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Ext OR: done", status[2] == 1'b1);
        check("Ext OR: triggered", status[1] == 1'b1);

        // ---- Test 13: Ext trigger AND mode ---------------------------------
        $display("\n=== Test 13: Ext trigger AND mode ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B4, 32'd2);    // EXT_TRIG = AND
        jtag_write(16'h0014, 32'd0);
        jtag_write(16'h0018, 32'd2);
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'd10);
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        trigger_in_dut = 1'b0;
        // Probe hits 10 but ext trigger not asserted -- should NOT trigger
        repeat (15) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end

        jtag_read(16'h0008, status);
        check("Ext AND: not triggered without ext_in", status[1] == 1'b0);

        // Now assert ext trigger while probe == 10
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B4, 32'd2);    // AND mode
        jtag_write(16'h0014, 32'd0);
        jtag_write(16'h0018, 32'd1);
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'd6);
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        trigger_in_dut = 1'b1;          // ext trigger asserted
        repeat (12) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end
        trigger_in_dut = 1'b0;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read(16'h0008, status);
        check("Ext AND: done when both conditions met", status[2] == 1'b1);

        // ---- Test 14: trigger_out pulse width ------------------------------
        $display("\n=== Test 14: trigger_out pulse width ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h00B0, 32'd0);    // DECIM=0
        jtag_write(16'h00B4, 32'd0);    // EXT_TRIG disabled
        jtag_write(16'h0014, 32'd0);
        jtag_write(16'h0018, 32'd2);
        jtag_write(16'h0020, 32'h1);
        jtag_write(16'h0024, 32'd3);
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h0004, 32'h1);    // ARM

        probe_in = '0;
        begin
            int trig_out_count;
            trig_out_count = 0;
            fork
                begin
                    repeat (20) begin
                        @(posedge sample_clk);
                        probe_in <= probe_in + 1'b1;
                    end
                end
                begin
                    repeat (30) begin
                        @(posedge sample_clk);
                        if (trigger_out_dut) trig_out_count++;
                    end
                end
            join
            check("trigger_out is 1-cycle pulse", trig_out_count == 1);
        end

        // ---- Test 15: Timestamp FEATURES + width register ------------------
        $display("\n=== Test 15: Timestamp instance checks ===");
        jtag_read_ts(16'h003C, features);
        check("TS: FEATURES[7]=HAS_TIMESTAMP", features[7] == 1'b1);
        check("TS: FEATURES[31:24]=32",        features[31:24] == 8'd32);
        jtag_read_ts(16'h00C4, sample_word);
        check("TS: TIMESTAMP_W reg = 32", sample_word == 32'd32);

        // ---- Test 16: Timestamp monotonic capture --------------------------
        $display("\n=== Test 16: Timestamp monotonic capture ===");
        jtag_write_ts(16'h0004, 32'h2); // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write_ts(16'h00B0, 32'd0); // DECIM=0
        jtag_write_ts(16'h0014, 32'd1); // PRETRIG
        jtag_write_ts(16'h0018, 32'd3); // POSTTRIG
        jtag_write_ts(16'h0020, 32'h1); // value_match
        jtag_write_ts(16'h0024, 32'd5); // TRIG_VALUE
        jtag_write_ts(16'h0028, 32'hFF);
        jtag_write_ts(16'h0004, 32'h1); // ARM

        probe_in_ts = '0;
        repeat (15) begin
            @(posedge sample_clk);
            probe_in_ts <= probe_in_ts + 1'b1;
        end

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read_ts(16'h0008, status);
        check("TS capture: done", status[2] == 1'b1);

        // Read timestamps and verify monotonicity
        // TS_DATA_BASE = 0x0100 + 16*1*4 = 0x0100 + 0x40 = 0x0140
        begin
            logic [31:0] ts_vals [0:4];
            logic all_mono;
            jtag_read_ts(16'h001C, cap_len);
            $display("  TS capture_len = %0d", cap_len);
            for (i = 0; i < 5 && i < cap_len; i++) begin
                jtag_read_ts(16'h0140 + i*4, ts_vals[i]);
                $display("    TS[%0d] = %0d", i, ts_vals[i]);
            end
            all_mono = 1'b1;
            for (i = 1; i < 5 && i < cap_len; i++) begin
                if (ts_vals[i] <= ts_vals[i-1]) all_mono = 1'b0;
            end
            check("TS: timestamps monotonically increasing", all_mono);
        end

        // ---- Test 17: Timestamp + DECIM (wider gaps) ----------------------
        $display("\n=== Test 17: Timestamp + DECIM=1 ===");
        jtag_write_ts(16'h0004, 32'h2); // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write_ts(16'h00B0, 32'd1); // DECIM=1 (every 2nd cycle)
        jtag_write_ts(16'h0014, 32'd1);
        jtag_write_ts(16'h0018, 32'd2);
        jtag_write_ts(16'h0020, 32'h1);
        jtag_write_ts(16'h0024, 32'd8);
        jtag_write_ts(16'h0028, 32'hFF);
        jtag_write_ts(16'h0004, 32'h1); // ARM

        probe_in_ts = '0;
        repeat (30) begin
            @(posedge sample_clk);
            probe_in_ts <= probe_in_ts + 1'b1;
        end

        cycles = 0;
        while (cycles < 150) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read_ts(16'h0008, status);
        check("TS+DECIM: done", status[2] == 1'b1);
        begin
            logic [31:0] ts0, ts1;
            jtag_read_ts(16'h0140, ts0);
            jtag_read_ts(16'h0144, ts1);
            // With DECIM=1, consecutive timestamps should differ by >= 2
            check($sformatf("TS+DECIM: gap >= 2 (ts0=%0d ts1=%0d)", ts0, ts1),
                  (ts1 - ts0) >= 2);
        end

        // ---- Test 18: Segmented memory (NUM_SEGMENTS=4, DEPTH=16) ---------
        $display("\n=== Test 18: Segmented memory (4 segments) ===");
        jtag_read_seg(16'h00B8, sample_word);
        check("SEG: NUM_SEGMENTS reg = 4", sample_word == 32'd4);

        jtag_write_seg(16'h0004, 32'h2); // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write_seg(16'h00B0, 32'd0); // DECIM=0
        // SEG_DEPTH = 16/4 = 4.  pretrig+posttrig+1 <= 4 => pre=0 post=3
        jtag_write_seg(16'h0014, 32'd0); // PRETRIG
        jtag_write_seg(16'h0018, 32'd3); // POSTTRIG
        jtag_write_seg(16'h0020, 32'h1); // value_match
        // Trigger on probe value matching 3 (will trigger repeatedly as probe increments)
        jtag_write_seg(16'h0024, 32'd3);
        jtag_write_seg(16'h0028, 32'h03); // mask = 0x03 (match lower 2 bits)
        jtag_write_seg(16'h0004, 32'h1);  // ARM

        probe_in_seg = '0;
        repeat (80) begin
            @(posedge sample_clk);
            probe_in_seg <= probe_in_seg + 1'b1;
        end

        cycles = 0;
        while (cycles < 200) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read_seg(16'h0008, status);
        check("SEG: done", status[2] == 1'b1);
        jtag_read_seg(16'h00BC, seg_status);
        check("SEG: all_seg_done flag", seg_status[31] == 1'b1);

        // ---- Test 19: NUM_SEGMENTS=1 regression (dut_seg features) ---------
        $display("\n=== Test 19: Feature flags for segmented DUT ===");
        jtag_read_seg(16'h003C, features);
        check("SEG FEATURES[23:16]=4", features[23:16] == 8'd4);

        // ---- Test 20: Probe mux PROBE_MUX_W register ----------------------
        $display("\n=== Test 20: Probe mux PROBE_MUX_W register ===");
        jtag_read_pmux(16'h00D0, sample_word);
        check("PROBE_MUX_W = 32", sample_word == 32'd32);

        // ---- Test 21: Probe mux slice selection ----------------------------
        $display("\n=== Test 21: Probe mux slice selection ===");
        // probe_in_pmux = 32'h{slice3}{slice2}{slice1}{slice0}
        //                     [31:24]  [23:16] [15:8]  [7:0]
        // Select slice 0, trigger on value 0x11 in slice 0
        jtag_write_pmux(16'h0004, 32'h2); // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write_pmux(16'h00AC, 32'd0); // PROBE_SEL = 0 (bits [7:0])
        jtag_write_pmux(16'h0014, 32'd0); // PRETRIG
        jtag_write_pmux(16'h0018, 32'd2); // POSTTRIG
        jtag_write_pmux(16'h0020, 32'h1); // value_match
        jtag_write_pmux(16'h0024, 32'hAA); // TRIG_VALUE = 0xAA
        jtag_write_pmux(16'h0028, 32'hFF); // TRIG_MASK
        jtag_write_pmux(16'h0004, 32'h1); // ARM

        // Drive probe_in_pmux: slice0=incrementing, slice1=0x11, slice2=0x22, slice3=0x33
        probe_in_pmux = 32'h33_22_11_00;
        repeat (3) @(posedge sample_clk);
        probe_in_pmux = 32'h33_22_11_AA;  // slice 0 = 0xAA (trigger)
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_22_11_BB;
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_22_11_CC;
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_22_11_DD;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read_pmux(16'h0008, status);
        check("Probe mux slice 0: done", status[2] == 1'b1);

        // Now test slice 2 (bits [23:16])
        jtag_write_pmux(16'h0004, 32'h2); // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write_pmux(16'h00AC, 32'd2); // PROBE_SEL = 2 (bits [23:16])
        jtag_write_pmux(16'h0014, 32'd0); // PRETRIG
        jtag_write_pmux(16'h0018, 32'd2); // POSTTRIG
        jtag_write_pmux(16'h0020, 32'h1); // value_match
        jtag_write_pmux(16'h0024, 32'hFF); // TRIG_VALUE = 0xFF in slice 2
        jtag_write_pmux(16'h0028, 32'hFF); // TRIG_MASK
        jtag_write_pmux(16'h0004, 32'h1); // ARM

        probe_in_pmux = 32'h33_00_11_AA;  // slice2 = 0x00 (no trigger yet)
        repeat (3) @(posedge sample_clk);
        probe_in_pmux = 32'h33_FF_11_AA;  // slice2 = 0xFF (trigger!)
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_EE_11_AA;
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_DD_11_AA;
        @(posedge sample_clk);
        probe_in_pmux = 32'h33_CC_11_AA;

        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end

        jtag_read_pmux(16'h0008, status);
        check("Probe mux slice 2: done", status[2] == 1'b1);

        // Verify readback: first sample after trigger should be from slice 2
        jtag_read_pmux(16'h0100, sample_word);
        check($sformatf("Probe mux slice 2: first sample=0xFF (got 0x%02x)", sample_word[7:0]),
              sample_word[7:0] == 8'hFF);

        // ---- Test 22: PROBE_SEL register round-trip -------------------------
        $display("\n=== Test 22: PROBE_SEL register round-trip ===");
        jtag_write_pmux(16'h00AC, 32'd3);
        jtag_read_pmux(16'h00AC, sample_word);
        check("PROBE_SEL round-trip", sample_word == 32'd3);

        // ---- Test 23: TRIG_DELAY register round-trip ------------------------
        $display("\n=== Test 23: TRIG_DELAY register round-trip ===");
        jtag_write(16'h00D4, 32'd5);
        jtag_read(16'h00D4, sample_word);
        check("TRIG_DELAY round-trip = 5", sample_word == 32'd5);
        jtag_write(16'h00D4, 32'd0);  // restore
        jtag_read(16'h00D4, sample_word);
        check("TRIG_DELAY round-trip = 0", sample_word == 32'd0);

        // ---- Test 24: TRIG_DELAY=0 equivalence with legacy capture ----------
        // With delay=0 the captured window must be identical to Test 3.
        $display("\n=== Test 24: TRIG_DELAY=0 equivalence ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h0014, 32'd2);    // PRETRIG_LEN = 2
        jtag_write(16'h0018, 32'd3);    // POSTTRIG_LEN = 3
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'd8);    // TRIG_VALUE = 8
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h00D4, 32'd0);    // TRIG_DELAY = 0
        jtag_write(16'h0004, 32'h1);    // ARM
        probe_in = '0;
        repeat (16) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end
        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end
        jtag_read(16'h0008, status);
        check("Delay=0: done",      status[2] == 1'b1);
        jtag_read(16'h001C, cap_len);
        check($sformatf("Delay=0: CAPTURE_LEN=6 (got %0d)", cap_len), cap_len == 6);
        // The trigger sample (index 2 in the 6-sample window) should be 8.
        jtag_read(16'h0100 + 2*4, sample_word);
        check($sformatf("Delay=0: trig sample = 8 (got 0x%02x)",
              sample_word[7:0]),
              sample_word[SAMPLE_W-1:0] == 8'd8);

        // ---- Test 25: TRIG_DELAY=4 shifts trigger sample by 4 cycles --------
        // Same stimulus as Test 24 but TRIG_DELAY=4.  The committed trigger
        // sample should be the value 4 cycles after the cause (counter = 8),
        // so the sample at the trigger index should be 12.
        $display("\n=== Test 25: TRIG_DELAY=4 ===");
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (10) @(posedge sample_clk);
        jtag_write(16'h0014, 32'd2);    // PRETRIG_LEN = 2
        jtag_write(16'h0018, 32'd3);    // POSTTRIG_LEN = 3
        jtag_write(16'h0020, 32'h1);    // TRIG_MODE: value_match
        jtag_write(16'h0024, 32'd8);    // TRIG_VALUE = 8 (cause)
        jtag_write(16'h0028, 32'hFF);
        jtag_write(16'h00D4, 32'd4);    // TRIG_DELAY = 4
        jtag_write(16'h0004, 32'h1);    // ARM
        probe_in = '0;
        repeat (24) begin
            @(posedge sample_clk);
            probe_in <= probe_in + 1'b1;
        end
        cycles = 0;
        while (cycles < 100) begin
            @(posedge sample_clk);
            cycles++;
        end
        jtag_read(16'h0008, status);
        check("Delay=4: done", status[2] == 1'b1);
        jtag_read(16'h001C, cap_len);
        check($sformatf("Delay=4: CAPTURE_LEN=6 (got %0d)", cap_len), cap_len == 6);
        // The captured window should contain values 10..15: trigger sample
        // is at index 2 with value 12 (= 8 + delay 4).  Pre = 10, 11; post
        // = 13, 14, 15.
        jtag_read(16'h0100 + 2*4, sample_word);
        check($sformatf("Delay=4: trig sample = 12 (got 0x%02x)",
              sample_word[7:0]),
              sample_word[SAMPLE_W-1:0] == 8'd12);
        jtag_read(16'h0100 + 0*4, sample_word);
        check($sformatf("Delay=4: pre[0] = 10 (got 0x%02x)",
              sample_word[7:0]),
              sample_word[SAMPLE_W-1:0] == 8'd10);
        jtag_read(16'h0100 + 5*4, sample_word);
        check($sformatf("Delay=4: post[2] = 15 (got 0x%02x)",
              sample_word[7:0]),
              sample_word[SAMPLE_W-1:0] == 8'd15);

        // Restore TRIG_DELAY = 0 for any later tests
        jtag_write(16'h0004, 32'h2);    // RESET
        repeat (4) @(posedge sample_clk);
        jtag_write(16'h00D4, 32'd0);

        // ---- Summary -------------------------------------------------------
        $display("\n=== Summary: %0d passed, %0d failed ===",
                 test_pass_count, test_fail_count);
        if (test_fail_count > 0)
            $fatal(1, "ELA testbench: failures detected");
        $finish;
    end

endmodule
