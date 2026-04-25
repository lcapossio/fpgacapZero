// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Focused configuration-matrix simulation for area/timing-sensitive ELA
// parameter combinations. The main ELA testbench covers deep behavior; this
// one catches parameter-gating regressions across small/full build shapes.

module fcapz_ela_config_matrix_tb;
    localparam int SAMPLE_W = 8;
    localparam int DEPTH = 16;

    localparam [15:0] ADDR_CTRL         = 16'h0004;
    localparam [15:0] ADDR_STATUS       = 16'h0008;
    localparam [15:0] ADDR_PRETRIG      = 16'h0014;
    localparam [15:0] ADDR_POSTTRIG     = 16'h0018;
    localparam [15:0] ADDR_CAPTURE_LEN  = 16'h001C;
    localparam [15:0] ADDR_TRIG_MODE    = 16'h0020;
    localparam [15:0] ADDR_TRIG_VALUE   = 16'h0024;
    localparam [15:0] ADDR_TRIG_MASK    = 16'h0028;
    localparam [15:0] ADDR_SQ_MODE      = 16'h0030;
    localparam [15:0] ADDR_SQ_VALUE     = 16'h0034;
    localparam [15:0] ADDR_SQ_MASK      = 16'h0038;
    localparam [15:0] ADDR_FEATURES     = 16'h003C;
    localparam [15:0] ADDR_SEQ_BASE     = 16'h0040;
    localparam [15:0] ADDR_CHAN_SEL     = 16'h00A0;
    localparam [15:0] ADDR_DECIM        = 16'h00B0;
    localparam [15:0] ADDR_TRIG_EXT     = 16'h00B4;
    localparam [15:0] ADDR_SEG_STATUS   = 16'h00BC;
    localparam [15:0] ADDR_SEG_SEL      = 16'h00C0;
    localparam [15:0] ADDR_PROBE_SEL    = 16'h00AC;
    localparam [15:0] ADDR_COMPARE_CAPS = 16'h00E0;
    localparam [15:0] ADDR_DATA_BASE    = 16'h0100;

    reg sample_clk = 1'b0;
    reg jtag_clk = 1'b0;
    reg sample_rst = 1'b1;
    reg jtag_rst = 1'b1;

    integer pass_count = 0;
    integer fail_count = 0;

    always #5 sample_clk = ~sample_clk;
    always #7 jtag_clk = ~jtag_clk;

    task check(input string name, input bit cond);
        begin
            if (cond) begin
                pass_count = pass_count + 1;
                $display("PASS: %s", name);
            end else begin
                fail_count = fail_count + 1;
                $display("FAIL: %s", name);
            end
        end
    endtask

    // ---- Smallest USER1-readable ELA shape --------------------------------
    reg [SAMPLE_W-1:0] probe_min = 8'h00;
    reg min_wr = 1'b0;
    reg min_rd = 1'b0;
    reg [15:0] min_addr = 16'h0;
    reg [31:0] min_wdata = 32'h0;
    wire [31:0] min_rdata;
    reg [$clog2(DEPTH)-1:0] min_burst_addr = '0;
    wire [SAMPLE_W-1:0] min_burst_data;
    wire min_burst_start;
    wire [$clog2(DEPTH)-1:0] min_burst_start_ptr;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(1),
        .STOR_QUAL(0),
        .NUM_CHANNELS(1),
        .INPUT_PIPE(0),
        .DECIM_EN(0),
        .EXT_TRIG_EN(0),
        .TIMESTAMP_W(0),
        .NUM_SEGMENTS(1),
        .PROBE_MUX_W(0),
        .REL_COMPARE(0),
        .DUAL_COMPARE(0),
        .USER1_DATA_EN(1)
    ) dut_min (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(probe_min),
        .trigger_in(1'b0),
        .trigger_out(),
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(min_wr),
        .jtag_rd_en(min_rd),
        .jtag_addr(min_addr),
        .jtag_wdata(min_wdata),
        .jtag_rdata(min_rdata),
        .burst_rd_addr(min_burst_addr),
        .burst_rd_data(min_burst_data),
        .burst_start(min_burst_start),
        .burst_start_ptr(min_burst_start_ptr)
    );

    // ---- Same small core, but no slow USER1 DATA window --------------------
    reg [SAMPLE_W-1:0] probe_nouser1 = 8'h00;
    reg nouser1_wr = 1'b0;
    reg nouser1_rd = 1'b0;
    reg [15:0] nouser1_addr = 16'h0;
    reg [31:0] nouser1_wdata = 32'h0;
    wire [31:0] nouser1_rdata;
    reg [$clog2(DEPTH)-1:0] nouser1_burst_addr = '0;
    wire [SAMPLE_W-1:0] nouser1_burst_data;
    wire nouser1_burst_start;
    wire [$clog2(DEPTH)-1:0] nouser1_burst_start_ptr;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(1),
        .STOR_QUAL(0),
        .NUM_CHANNELS(1),
        .INPUT_PIPE(0),
        .DECIM_EN(0),
        .EXT_TRIG_EN(0),
        .TIMESTAMP_W(0),
        .NUM_SEGMENTS(1),
        .PROBE_MUX_W(0),
        .REL_COMPARE(0),
        .DUAL_COMPARE(0),
        .USER1_DATA_EN(0)
    ) dut_nouser1 (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(probe_nouser1),
        .trigger_in(1'b0),
        .trigger_out(),
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(nouser1_wr),
        .jtag_rd_en(nouser1_rd),
        .jtag_addr(nouser1_addr),
        .jtag_wdata(nouser1_wdata),
        .jtag_rdata(nouser1_rdata),
        .burst_rd_addr(nouser1_burst_addr),
        .burst_rd_data(nouser1_burst_data),
        .burst_start(nouser1_burst_start),
        .burst_start_ptr(nouser1_burst_start_ptr)
    );

    // ---- Relational comparator + sequencer build --------------------------
    reg [SAMPLE_W-1:0] probe_rel = 8'h20;
    reg rel_wr = 1'b0;
    reg rel_rd = 1'b0;
    reg [15:0] rel_addr = 16'h0;
    reg [31:0] rel_wdata = 32'h0;
    wire [31:0] rel_rdata;
    reg [$clog2(DEPTH)-1:0] rel_burst_addr = '0;
    wire [SAMPLE_W-1:0] rel_burst_data;
    wire rel_burst_start;
    wire [$clog2(DEPTH)-1:0] rel_burst_start_ptr;

    fcapz_ela #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(2),
        .STOR_QUAL(0),
        .NUM_CHANNELS(1),
        .INPUT_PIPE(1),
        .DECIM_EN(0),
        .EXT_TRIG_EN(0),
        .TIMESTAMP_W(0),
        .NUM_SEGMENTS(1),
        .PROBE_MUX_W(0),
        .REL_COMPARE(1),
        .DUAL_COMPARE(0),
        .USER1_DATA_EN(1)
    ) dut_rel (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(probe_rel),
        .trigger_in(1'b0),
        .trigger_out(),
        .jtag_clk(jtag_clk),
        .jtag_rst(jtag_rst),
        .jtag_wr_en(rel_wr),
        .jtag_rd_en(rel_rd),
        .jtag_addr(rel_addr),
        .jtag_wdata(rel_wdata),
        .jtag_rdata(rel_rdata),
        .burst_rd_addr(rel_burst_addr),
        .burst_rd_data(rel_burst_data),
        .burst_start(rel_burst_start),
        .burst_start_ptr(rel_burst_start_ptr)
    );

    task automatic write_min(input [15:0] addr, input [31:0] data);
        begin
            @(posedge jtag_clk);
            min_addr <= addr;
            min_wdata <= data;
            min_wr <= 1'b1;
            @(posedge jtag_clk);
            min_wr <= 1'b0;
        end
    endtask

    task automatic read_min(input [15:0] addr, output [31:0] data);
        begin
            @(posedge jtag_clk);
            min_addr <= addr;
            min_rd <= 1'b1;
            @(posedge jtag_clk);
            min_rd <= 1'b0;
            repeat (8) @(posedge jtag_clk);
            data = min_rdata;
        end
    endtask

    task automatic write_nouser1(input [15:0] addr, input [31:0] data);
        begin
            @(posedge jtag_clk);
            nouser1_addr <= addr;
            nouser1_wdata <= data;
            nouser1_wr <= 1'b1;
            @(posedge jtag_clk);
            nouser1_wr <= 1'b0;
        end
    endtask

    task automatic read_nouser1(input [15:0] addr, output [31:0] data);
        begin
            @(posedge jtag_clk);
            nouser1_addr <= addr;
            nouser1_rd <= 1'b1;
            @(posedge jtag_clk);
            nouser1_rd <= 1'b0;
            repeat (8) @(posedge jtag_clk);
            data = nouser1_rdata;
        end
    endtask

    task automatic write_rel(input [15:0] addr, input [31:0] data);
        begin
            @(posedge jtag_clk);
            rel_addr <= addr;
            rel_wdata <= data;
            rel_wr <= 1'b1;
            @(posedge jtag_clk);
            rel_wr <= 1'b0;
        end
    endtask

    task automatic read_rel(input [15:0] addr, output [31:0] data);
        begin
            @(posedge jtag_clk);
            rel_addr <= addr;
            rel_rd <= 1'b1;
            @(posedge jtag_clk);
            rel_rd <= 1'b0;
            repeat (8) @(posedge jtag_clk);
            data = rel_rdata;
        end
    endtask

    task automatic drive_min_counter(input integer cycles);
        integer i;
        begin
            for (i = 0; i < cycles; i = i + 1) begin
                @(posedge sample_clk);
                probe_min <= probe_min + 8'h1;
                probe_nouser1 <= probe_nouser1 + 8'h1;
                if (probe_rel > 8'h00)
                    probe_rel <= probe_rel - 8'h1;
            end
        end
    endtask

    task automatic wait_done_min(output [31:0] status);
        integer i;
        begin
            status = 32'h0;
            for (i = 0; i < 80 && status[2] == 1'b0; i = i + 1) begin
                drive_min_counter(2);
                read_min(ADDR_STATUS, status);
            end
        end
    endtask

    task automatic wait_done_nouser1(output [31:0] status);
        integer i;
        begin
            status = 32'h0;
            for (i = 0; i < 80 && status[2] == 1'b0; i = i + 1) begin
                drive_min_counter(2);
                read_nouser1(ADDR_STATUS, status);
            end
        end
    endtask

    task automatic wait_done_rel(output [31:0] status);
        integer i;
        begin
            status = 32'h0;
            for (i = 0; i < 80 && status[2] == 1'b0; i = i + 1) begin
                drive_min_counter(2);
                read_rel(ADDR_STATUS, status);
            end
        end
    endtask

    reg [31:0] rdata;
    reg [31:0] status;
    reg [31:0] cap_len;

    initial begin
        repeat (8) @(posedge sample_clk);
        sample_rst = 1'b0;
        jtag_rst = 1'b0;
        repeat (8) @(posedge sample_clk);

        $display("\n=== Config 1: minimal single-comparator USER1-readable ELA ===");
        write_min(ADDR_SQ_MODE, 32'hF);
        write_min(ADDR_SQ_VALUE, 32'hA5);
        write_min(ADDR_SQ_MASK, 32'hFF);
        write_min(ADDR_CHAN_SEL, 32'd2);
        write_min(ADDR_DECIM, 32'h00FF_FFFF);
        write_min(ADDR_TRIG_EXT, 32'd3);
        write_min(ADDR_SEG_SEL, 32'd1);
        write_min(ADDR_PROBE_SEL, 32'd3);

        read_min(ADDR_FEATURES, rdata);
        check("minimal features report no optional gates", rdata == 32'h0001_0101);
        read_min(ADDR_COMPARE_CAPS, rdata);
        check("minimal compare caps are A-only EQ/NEQ/edges/changed",
              rdata == 32'h0002_01C3);
        read_min(ADDR_SQ_MODE, rdata);
        check("disabled SQ_MODE ignores writes", rdata == 32'h0);
        read_min(ADDR_SQ_VALUE, rdata);
        check("disabled SQ_VALUE ignores writes", rdata == 32'h0);
        read_min(ADDR_SQ_MASK, rdata);
        check("disabled SQ_MASK ignores writes", rdata == 32'h0);
        read_min(ADDR_CHAN_SEL, rdata);
        check("disabled channel select ignores writes", rdata == 32'h0);
        read_min(ADDR_DECIM, rdata);
        check("disabled decimation register ignores writes", rdata == 32'h0);
        read_min(ADDR_TRIG_EXT, rdata);
        check("disabled external trigger register ignores writes", rdata == 32'h0);
        read_min(ADDR_SEG_STATUS, rdata);
        check("single segment reports all segments done constant", rdata == 32'h8000_0000);
        read_min(ADDR_SEG_SEL, rdata);
        check("disabled segment select ignores writes", rdata == 32'h0);
        read_min(ADDR_PROBE_SEL, rdata);
        check("disabled probe mux select ignores writes", rdata == 32'h0);
        write_min(ADDR_SEQ_BASE + 16'd12, 32'h1234_5678);
        write_min(ADDR_SEQ_BASE + 16'd16, 32'h8765_4321);
        read_min(ADDR_SEQ_BASE + 16'd12, rdata);
        check("DUAL_COMPARE=0 B value reads zero", rdata == 32'h0);
        read_min(ADDR_SEQ_BASE + 16'd16, rdata);
        check("disabled sequencer B mask read is pruned to zero", rdata == 32'h0);

        probe_min = 8'h00;
        write_min(ADDR_CTRL, 32'h2);
        write_min(ADDR_PRETRIG, 32'd1);
        write_min(ADDR_POSTTRIG, 32'd2);
        write_min(ADDR_TRIG_MODE, 32'h1);
        write_min(ADDR_TRIG_VALUE, 32'd5);
        write_min(ADDR_TRIG_MASK, 32'hFF);
        write_min(ADDR_CTRL, 32'h1);
        wait_done_min(status);
        read_min(ADDR_CAPTURE_LEN, cap_len);
        check("minimal capture reaches done", status[2] == 1'b1);
        check("minimal capture length is pre+trigger+post", cap_len == 32'd4);
        read_min(ADDR_DATA_BASE, rdata);
        check("minimal USER1 data window returns captured data", rdata[7:0] != 8'h00);

        $display("\n=== Config 2: USER1 data window compiled out ===");
        probe_nouser1 = 8'h00;
        write_nouser1(ADDR_CTRL, 32'h2);
        write_nouser1(ADDR_PRETRIG, 32'd1);
        write_nouser1(ADDR_POSTTRIG, 32'd2);
        write_nouser1(ADDR_TRIG_MODE, 32'h1);
        write_nouser1(ADDR_TRIG_VALUE, 32'd5);
        write_nouser1(ADDR_TRIG_MASK, 32'hFF);
        write_nouser1(ADDR_CTRL, 32'h1);
        wait_done_nouser1(status);
        read_nouser1(ADDR_CAPTURE_LEN, cap_len);
        check("USER1_DATA_EN=0 capture still reaches done", status[2] == 1'b1);
        check("USER1_DATA_EN=0 capture length is valid", cap_len == 32'd4);
        read_nouser1(ADDR_DATA_BASE, rdata);
        check("USER1_DATA_EN=0 DATA window reads zero", rdata == 32'h0);

        $display("\n=== Config 3: REL_COMPARE=1, INPUT_PIPE=1, DUAL_COMPARE=0 ===");
        read_rel(ADDR_COMPARE_CAPS, rdata);
        check("relational compare caps include LT/GT/LE/GE and A-only",
              rdata == 32'h0002_01FF);
        write_rel(ADDR_SEQ_BASE + 16'd12, 32'hDEAD_BEEF);
        write_rel(ADDR_SEQ_BASE + 16'd16, 32'h1234_5678);
        read_rel(ADDR_SEQ_BASE + 16'd12, rdata);
        check("sequencer B value still zero when DUAL_COMPARE=0", rdata == 32'h0);
        read_rel(ADDR_SEQ_BASE + 16'd16, rdata);
        check("sequencer B mask reads all ones when DUAL_COMPARE=0", rdata == 32'hFFFF_FFFF);

        probe_rel = 8'h20;
        write_rel(ADDR_CTRL, 32'h2);
        write_rel(ADDR_PRETRIG, 32'd0);
        write_rel(ADDR_POSTTRIG, 32'd2);
        write_rel(ADDR_SEQ_BASE + 16'd0, 32'h0000_1002); // final LT stage
        write_rel(ADDR_SEQ_BASE + 16'd4, 32'd10);
        write_rel(ADDR_SEQ_BASE + 16'd8, 32'hFF);
        write_rel(ADDR_CTRL, 32'h1);
        wait_done_rel(status);
        read_rel(ADDR_CAPTURE_LEN, cap_len);
        check("REL_COMPARE=1 LT sequencer capture reaches done", status[2] == 1'b1);
        check("REL_COMPARE=1 LT sequencer capture has expected length", cap_len == 32'd3);

        $display("\n=== fcapz_ela_config_matrix summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1, "ELA configuration matrix failures detected");
        $finish;
    end
endmodule
