// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module jtag_pipe_iface_tb;
    localparam SAMPLE_W = 8;
    localparam TIMESTAMP_W = 32;
    localparam DEPTH = 1024;
    localparam BURST_W = 256;
    localparam SAMPLES_PER_SCAN = BURST_W / SAMPLE_W;

    reg arst = 1'b1;
    reg tck = 1'b0;
    reg tdi = 1'b0;
    wire tdo;
    reg capture = 1'b0;
    reg shift_en = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;

    wire reg_clk;
    wire reg_rst;
    wire reg_wr_en;
    wire reg_rd_en;
    wire [15:0] reg_addr;
    wire [31:0] reg_wdata;
    reg [31:0] reg_rdata = 32'h1234_5678;

    wire [$clog2(DEPTH)-1:0] mem_addr;
    reg [SAMPLE_W-1:0] sample_data = {SAMPLE_W{1'b0}};
    reg [TIMESTAMP_W-1:0] timestamp_data = {TIMESTAMP_W{1'b0}};
    reg burst_start = 1'b0;
    reg burst_timestamp = 1'b0;
    reg [$clog2(DEPTH)-1:0] burst_ptr_in = {$clog2(DEPTH){1'b0}};

    integer pass_count = 0;
    integer fail_count = 0;

    jtag_pipe_iface #(
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .BURST_W(BURST_W),
        .SEG_DEPTH(DEPTH)
    ) dut (
        .arst(arst),
        .tck(tck),
        .tdi(tdi),
        .tdo(tdo),
        .capture(capture),
        .shift_en(shift_en),
        .update(update),
        .sel(sel),
        .reg_clk(reg_clk),
        .reg_rst(reg_rst),
        .reg_wr_en(reg_wr_en),
        .reg_rd_en(reg_rd_en),
        .reg_addr(reg_addr),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata),
        .mem_addr(mem_addr),
        .sample_data(sample_data),
        .timestamp_data(timestamp_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_ptr_in(burst_ptr_in)
    );

    always #5 tck = ~tck;

    always @(posedge tck) begin
        sample_data <= mem_addr[7:0];
        timestamp_data <= 32'hA500_0000 | mem_addr;
        if (reg_wr_en && reg_addr == 16'h002C) begin
            burst_ptr_in <= 10'd42;
            burst_timestamp <= reg_wdata[31];
            burst_start <= ~burst_start;
        end
    end

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

    task tick;
        begin
            @(posedge tck);
            #1;
        end
    endtask

    task idle_cycles(input integer n);
        integer i;
        begin
            sel = 1'b0;
            capture = 1'b0;
            shift_en = 1'b0;
            update = 1'b0;
            for (i = 0; i < n; i = i + 1)
                tick();
        end
    endtask

    function [48:0] make_frame(input [15:0] addr, input [31:0] data, input bit write);
        begin
            make_frame = {write, addr, data};
        end
    endfunction

    task scan_reg(input [48:0] frame, output reg [31:0] captured);
        integer i;
        begin
            captured = 32'h0;
            sel = 1'b1;
            capture = 1'b1;
            tick();
            capture = 1'b0;
            shift_en = 1'b1;
            for (i = 0; i < 49; i = i + 1) begin
                tdi = frame[i];
                if (i < 32)
                    captured[i] = tdo;
                tick();
            end
            shift_en = 1'b0;
            tdi = 1'b0;
            update = 1'b1;
            tick();
            update = 1'b0;
            sel = 1'b0;
        end
    endtask

    task scan_burst(output reg [BURST_W-1:0] bits);
        integer i;
        begin
            bits = {BURST_W{1'b0}};
            sel = 1'b1;
            capture = 1'b1;
            tick();
            capture = 1'b0;
            shift_en = 1'b1;
            for (i = 0; i < BURST_W; i = i + 1) begin
                tdi = 1'b0;
                bits[i] = tdo;
                tick();
            end
            shift_en = 1'b0;
            update = 1'b1;
            tick();
            update = 1'b0;
            sel = 1'b0;
        end
    endtask

    task expect_samples(input string name, input reg [BURST_W-1:0] bits, input integer start_value);
        integer i;
        reg ok;
        reg [SAMPLE_W-1:0] got;
        reg [SAMPLE_W-1:0] exp;
        begin
            ok = 1'b1;
            for (i = 0; i < SAMPLES_PER_SCAN; i = i + 1) begin
                got = bits[i*SAMPLE_W +: SAMPLE_W];
                exp = (start_value + i) & 8'hFF;
                if (got !== exp)
                    ok = 1'b0;
            end
            check(name, ok);
        end
    endtask

    reg [31:0] captured;
    reg [BURST_W-1:0] stale_scan;
    reg [BURST_W-1:0] first_scan;
    reg [BURST_W-1:0] second_scan;

    initial begin
        repeat (4) tick();
        arst = 1'b0;
        repeat (4) tick();

        $display("\n=== 49-bit register protocol on pipe ===");
        scan_reg(make_frame(16'h0024, 32'hCAFE_BABE, 1'b1), captured);
        check("write address reaches register bus", reg_addr == 16'h0024);
        check("write data reaches register bus", reg_wdata == 32'hCAFE_BABE);

        scan_reg(make_frame(16'h0000, 32'h0, 1'b0), captured);
        idle_cycles(4);
        scan_reg(make_frame(16'h0000, 32'h0, 1'b0), captured);
        check("read captures reg_rdata", captured == 32'h1234_5678);

        $display("\n=== 256-bit burst protocol on same chain ===");
        scan_reg(make_frame(16'h002C, 32'h0, 1'b1), captured);
        idle_cycles(80);
        scan_burst(stale_scan);
        scan_burst(first_scan);
        scan_burst(second_scan);
        expect_samples("first returned burst starts at 42", first_scan, 42);
        expect_samples("next returned burst starts at 74", second_scan, 74);

        $display("\n=== jtag_pipe_iface summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1);
        $finish;
    end
endmodule
