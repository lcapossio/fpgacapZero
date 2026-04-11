// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Focused ELA regressions for edge cases that previously failed.

module fcapz_ela_bug_probe_tb;
    logic sample_clk = 1'b0;
    logic jtag_clk   = 1'b0;
    logic sample_rst = 1'b1;
    logic jtag_rst   = 1'b1;

    always #5 sample_clk = ~sample_clk;
    always #7 jtag_clk   = ~jtag_clk;

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

    task automatic wait_sample(input int n);
        repeat (n) @(posedge sample_clk);
    endtask

    // ---------------------------------------------------------------------
    // Regression 1: exactly-full capture must not write one extra sample
    // and overwrite the oldest entry after wrap.
    localparam int FULL_W = 8;
    localparam int FULL_DEPTH = 8;
    logic [FULL_W-1:0] probe_full = '0;
    logic wr_full = 1'b0, rd_full = 1'b0;
    logic [15:0] addr_full = '0;
    logic [31:0] wdata_full = '0, rdata_full;
    logic [$clog2(FULL_DEPTH)-1:0] burst_addr_full = '0;
    wire [FULL_W-1:0] burst_data_full;
    wire burst_start_full;
    wire [$clog2(FULL_DEPTH)-1:0] burst_start_ptr_full;

    fcapz_ela #(.SAMPLE_W(FULL_W), .DEPTH(FULL_DEPTH)) dut_full (
        .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_full),
        .trigger_in(1'b0), .trigger_out(),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(wr_full), .jtag_rd_en(rd_full),
        .jtag_addr(addr_full), .jtag_wdata(wdata_full), .jtag_rdata(rdata_full),
        .burst_rd_addr(burst_addr_full), .burst_rd_data(burst_data_full),
        .burst_start(burst_start_full), .burst_start_ptr(burst_start_ptr_full)
    );

    task automatic write_full(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        addr_full <= addr; wdata_full <= data; wr_full <= 1'b1;
        @(posedge jtag_clk);
        wr_full <= 1'b0;
    endtask

    task automatic read_full(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        addr_full <= addr; rd_full <= 1'b1;
        @(posedge jtag_clk);
        rd_full <= 1'b0;
        repeat (10) @(posedge jtag_clk);
        data = rdata_full;
    endtask

    // ---------------------------------------------------------------------
    // Regression 2: a trigger on a non-decimated cycle still force-stores
    // the committed trigger sample at samples[pretrigger].
    localparam int DEC_W = 8;
    localparam int DEC_DEPTH = 16;
    logic [DEC_W-1:0] probe_dec = '0;
    logic wr_dec = 1'b0, rd_dec = 1'b0;
    logic [15:0] addr_dec = '0;
    logic [31:0] wdata_dec = '0, rdata_dec;
    logic [$clog2(DEC_DEPTH)-1:0] burst_addr_dec = '0;
    wire [DEC_W-1:0] burst_data_dec;
    wire burst_start_dec;
    wire [$clog2(DEC_DEPTH)-1:0] burst_start_ptr_dec;

    fcapz_ela #(.SAMPLE_W(DEC_W), .DEPTH(DEC_DEPTH), .DECIM_EN(1)) dut_dec (
        .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_dec),
        .trigger_in(1'b0), .trigger_out(),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(wr_dec), .jtag_rd_en(rd_dec),
        .jtag_addr(addr_dec), .jtag_wdata(wdata_dec), .jtag_rdata(rdata_dec),
        .burst_rd_addr(burst_addr_dec), .burst_rd_data(burst_data_dec),
        .burst_start(burst_start_dec), .burst_start_ptr(burst_start_ptr_dec)
    );

    task automatic write_dec(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        addr_dec <= addr; wdata_dec <= data; wr_dec <= 1'b1;
        @(posedge jtag_clk);
        wr_dec <= 1'b0;
    endtask

    task automatic read_dec(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        addr_dec <= addr; rd_dec <= 1'b1;
        @(posedge jtag_clk);
        rd_dec <= 1'b0;
        repeat (10) @(posedge jtag_clk);
        data = rdata_dec;
    endtask

    // ---------------------------------------------------------------------
    // Regression 3: sequencer count_target=1 fires on one hit.
    localparam int SEQ_W = 8;
    localparam int SEQ_DEPTH = 16;
    logic [SEQ_W-1:0] probe_seq = '0;
    logic wr_seq = 1'b0, rd_seq = 1'b0;
    logic [15:0] addr_seq = '0;
    logic [31:0] wdata_seq = '0, rdata_seq;
    logic [$clog2(SEQ_DEPTH)-1:0] burst_addr_seq = '0;
    wire [SEQ_W-1:0] burst_data_seq;
    wire burst_start_seq;
    wire [$clog2(SEQ_DEPTH)-1:0] burst_start_ptr_seq;

    fcapz_ela #(.SAMPLE_W(SEQ_W), .DEPTH(SEQ_DEPTH), .TRIG_STAGES(2)) dut_seq (
        .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_seq),
        .trigger_in(1'b0), .trigger_out(),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(wr_seq), .jtag_rd_en(rd_seq),
        .jtag_addr(addr_seq), .jtag_wdata(wdata_seq), .jtag_rdata(rdata_seq),
        .burst_rd_addr(burst_addr_seq), .burst_rd_data(burst_data_seq),
        .burst_start(burst_start_seq), .burst_start_ptr(burst_start_ptr_seq)
    );

    task automatic write_seq(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        addr_seq <= addr; wdata_seq <= data; wr_seq <= 1'b1;
        @(posedge jtag_clk);
        wr_seq <= 1'b0;
    endtask

    task automatic read_seq(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        addr_seq <= addr; rd_seq <= 1'b1;
        @(posedge jtag_clk);
        rd_seq <= 1'b0;
        repeat (10) @(posedge jtag_clk);
        data = rdata_seq;
    endtask

    // ---------------------------------------------------------------------
    // Regression 4: TIMESTAMP_W=48 upper word survives CDC/readback.
    localparam int TS_W = 8;
    localparam int TS_DEPTH = 16;
    logic [TS_W-1:0] probe_ts = '0;
    logic wr_ts = 1'b0, rd_ts = 1'b0;
    logic [15:0] addr_ts = '0;
    logic [31:0] wdata_ts = '0, rdata_ts;
    logic [$clog2(TS_DEPTH)-1:0] burst_addr_ts = '0;
    wire [TS_W-1:0] burst_data_ts;
    wire burst_start_ts;
    wire [$clog2(TS_DEPTH)-1:0] burst_start_ptr_ts;

    fcapz_ela #(.SAMPLE_W(TS_W), .DEPTH(TS_DEPTH), .TIMESTAMP_W(48)) dut_ts (
        .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_ts),
        .trigger_in(1'b0), .trigger_out(),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(wr_ts), .jtag_rd_en(rd_ts),
        .jtag_addr(addr_ts), .jtag_wdata(wdata_ts), .jtag_rdata(rdata_ts),
        .burst_rd_addr(burst_addr_ts), .burst_rd_data(burst_data_ts),
        .burst_start(burst_start_ts), .burst_start_ptr(burst_start_ptr_ts)
    );

    task automatic write_ts(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        addr_ts <= addr; wdata_ts <= data; wr_ts <= 1'b1;
        @(posedge jtag_clk);
        wr_ts <= 1'b0;
    endtask

    task automatic read_ts(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        addr_ts <= addr; rd_ts <= 1'b1;
        @(posedge jtag_clk);
        rd_ts <= 1'b0;
        repeat (10) @(posedge jtag_clk);
        data = rdata_ts;
    endtask

    // ---------------------------------------------------------------------
    // Regression 5: SAMPLE_W=48 final data word is zero-extended.
    localparam int W48 = 48;
    localparam int W48_DEPTH = 16;
    logic [W48-1:0] probe_w48 = '0;
    logic wr_w48 = 1'b0, rd_w48 = 1'b0;
    logic [15:0] addr_w48 = '0;
    logic [31:0] wdata_w48 = '0, rdata_w48;
    logic [$clog2(W48_DEPTH)-1:0] burst_addr_w48 = '0;
    wire [W48-1:0] burst_data_w48;
    wire burst_start_w48;
    wire [$clog2(W48_DEPTH)-1:0] burst_start_ptr_w48;

    fcapz_ela #(.SAMPLE_W(W48), .DEPTH(W48_DEPTH)) dut_w48 (
        .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_w48),
        .trigger_in(1'b0), .trigger_out(),
        .jtag_clk(jtag_clk), .jtag_rst(jtag_rst),
        .jtag_wr_en(wr_w48), .jtag_rd_en(rd_w48),
        .jtag_addr(addr_w48), .jtag_wdata(wdata_w48), .jtag_rdata(rdata_w48),
        .burst_rd_addr(burst_addr_w48), .burst_rd_data(burst_data_w48),
        .burst_start(burst_start_w48), .burst_start_ptr(burst_start_ptr_w48)
    );

    task automatic write_w48(input [15:0] addr, input [31:0] data);
        @(posedge jtag_clk);
        addr_w48 <= addr; wdata_w48 <= data; wr_w48 <= 1'b1;
        @(posedge jtag_clk);
        wr_w48 <= 1'b0;
    endtask

    task automatic read_w48(input [15:0] addr, output [31:0] data);
        @(posedge jtag_clk);
        addr_w48 <= addr; rd_w48 <= 1'b1;
        @(posedge jtag_clk);
        rd_w48 <= 1'b0;
        repeat (10) @(posedge jtag_clk);
        data = rdata_w48;
    endtask

    initial begin
        logic [31:0] word0, word1, word2, status;
        int i;

        repeat (4) @(posedge sample_clk);
        sample_rst <= 1'b0;
        repeat (2) @(posedge jtag_clk);
        jtag_rst <= 1'b0;
        repeat (4) @(posedge jtag_clk);

        $display("\n=== Regression 1: full-depth capture keeps oldest sample ===");
        write_full(16'h0014, 32'd2);   // pre
        write_full(16'h0018, 32'd5);   // post, total = DEPTH
        write_full(16'h0020, 32'h1);
        write_full(16'h0024, 32'd4);
        write_full(16'h0028, 32'hFF);
        write_full(16'h0004, 32'h1);
        probe_full = '0;
        repeat (20) begin
            @(posedge sample_clk);
            probe_full <= probe_full + 1'b1;
        end
        wait_sample(40);
        read_full(16'h0008, status);
        read_full(16'h0100, word0);
        read_full(16'h0100 + 2*4, word1);
        $display("  status=0x%08x data[0]=0x%02x data[2]=0x%02x",
                 status, word0[7:0], word1[7:0]);
        check("exact full-depth window starts at 2", status[2] && (word0[7:0] == 8'd2));
        check("trigger sample remains at index pretrigger", word1[7:0] == 8'd4);

        $display("\n=== Regression 2: decimated trigger sample is anchored ===");
        write_dec(16'h0004, 32'h2);
        wait_sample(6);
        write_dec(16'h00B0, 32'd3);    // store every fourth cycle
        write_dec(16'h0014, 32'd1);
        write_dec(16'h0018, 32'd2);
        write_dec(16'h0020, 32'h1);
        write_dec(16'h0024, 32'd19);   // deliberately between store ticks
        write_dec(16'h0028, 32'hFF);
        write_dec(16'h0004, 32'h1);
        probe_dec = '0;
        repeat (50) begin
            @(posedge sample_clk);
            probe_dec <= probe_dec + 1'b1;
        end
        wait_sample(80);
        read_dec(16'h0008, status);
        read_dec(16'h0100 + 1*4, word0);
        $display("  status=0x%08x trigger-index sample=0x%02x", status, word0[7:0]);
        check("decimation trigger index is 19", status[2] && (word0[7:0] == 8'd19));

        $display("\n=== Regression 3: sequencer count_target=1 fires on first hit ===");
        write_seq(16'h0014, 32'd0);
        write_seq(16'h0018, 32'd0);
        write_seq(16'h0040, 32'h0001_1000); // count=1, final, A-only EQ
        write_seq(16'h0044, 32'd5);
        write_seq(16'h0048, 32'hFF);
        write_seq(16'h0004, 32'h1);
        probe_seq = 8'd0;
        wait_sample(4);
        @(posedge sample_clk); probe_seq <= 8'd5;
        @(posedge sample_clk); probe_seq <= 8'd0;
        wait_sample(20);
        read_seq(16'h0008, status);
        check("one sequencer hit with count_target=1 fires", status[2] == 1'b1);

        $display("\n=== Regression 4: TIMESTAMP_W=48 upper word readback ===");
        write_ts(16'h0014, 32'd0);
        write_ts(16'h0018, 32'd1);
        write_ts(16'h0020, 32'h1);
        write_ts(16'h0024, 32'd3);
        write_ts(16'h0028, 32'hFF);
        dut_ts.g_ts.ts_counter = 48'h0001_0000_0100;
        write_ts(16'h0004, 32'h1);
        probe_ts = '0;
        repeat (10) begin
            @(posedge sample_clk);
            probe_ts <= probe_ts + 1'b1;
        end
        wait_sample(40);
        read_ts(16'h0140, word0); // TS sample 0 low word: data base + 16*4
        read_ts(16'h0144, word1); // TS sample 0 high word
        $display("  ts[0] low=0x%08x high=0x%08x", word0, word1);
        check("48-bit timestamp upper word is 0x0001", word1 === 32'h0000_0001);

        $display("\n=== Regression 5: SAMPLE_W=48 final data word readback ===");
        write_w48(16'h0014, 32'd0);
        write_w48(16'h0018, 32'd1);
        write_w48(16'h0020, 32'h1);
        write_w48(16'h0024, 32'h2222_3333);
        write_w48(16'h0028, 32'hFFFF_FFFF);
        probe_w48 = 48'h1111_2222_3333;
        wait_sample(2);
        write_w48(16'h0004, 32'h1);
        wait_sample(40);
        read_w48(16'h0100, word0);
        read_w48(16'h0104, word1);
        $display("  sample[0] chunk0=0x%08x chunk1=0x%08x", word0, word1);
        check("48-bit data low chunk is 0x22223333", word0 === 32'h2222_3333);
        check("48-bit data high chunk is zero-extended", word1 === 32'h0000_1111);

        $display("\n=== Regression summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1, "ELA focused regression failures detected");
        $finish;
    end
endmodule
