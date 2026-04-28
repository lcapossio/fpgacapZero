// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module jtag_burst_read_tb;
    localparam SAMPLE_W = 8;
    localparam TIMESTAMP_W = 32;
    localparam DEPTH = 1024;
    localparam SEG_DEPTH = 256;
    localparam BURST_W = 256;
    localparam SAMPLES_PER_SCAN = BURST_W / SAMPLE_W;
    localparam TS_PER_SCAN = BURST_W / TIMESTAMP_W;

    reg arst = 1'b1;
    reg tck = 1'b0;
    reg tdi = 1'b0;
    wire tdo;
    reg capture = 1'b0;
    reg shift_en = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;

    wire [$clog2(DEPTH)-1:0] mem_addr;
    reg [SAMPLE_W-1:0] sample_data = {SAMPLE_W{1'b0}};
    reg [TIMESTAMP_W-1:0] timestamp_data = {TIMESTAMP_W{1'b0}};
    reg burst_start = 1'b0;
    reg burst_timestamp = 1'b0;
    reg [$clog2(DEPTH)-1:0] burst_ptr_in = {$clog2(DEPTH){1'b0}};

    integer pass_count = 0;
    integer fail_count = 0;

    jtag_burst_read #(
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .BURST_W(BURST_W),
        .SEG_DEPTH(SEG_DEPTH)
    ) dut (
        .arst(arst),
        .tck(tck),
        .tdi(tdi),
        .tdo(tdo),
        .capture(capture),
        .shift_en(shift_en),
        .update(update),
        .sel(sel),
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

    task start_burst(input [$clog2(DEPTH)-1:0] ptr, input bit timestamp);
        begin
            sel = 1'b0;
            burst_ptr_in = ptr;
            burst_timestamp = timestamp;
            burst_start = ~burst_start;
            tick();
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

    task scan_sample_burst(output reg [BURST_W-1:0] bits);
        integer i;
        begin
            bits = {BURST_W{1'b0}};
            sel = 1'b1;
            capture = 1'b1;
            tick();
            capture = 1'b0;
            shift_en = 1'b1;
            for (i = 0; i < BURST_W; i = i + 1) begin
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

    task expect_samples(
        input string name,
        input reg [BURST_W-1:0] bits,
        input integer start_value
    );
        integer i;
        reg ok;
        reg [SAMPLE_W-1:0] got;
        reg [SAMPLE_W-1:0] exp;
        begin
            ok = 1'b1;
            for (i = 0; i < SAMPLES_PER_SCAN; i = i + 1) begin
                got = bits[i*SAMPLE_W +: SAMPLE_W];
                exp = (start_value + i) & 8'hFF;
                if (got !== exp) begin
                    ok = 1'b0;
                    $display("  %s[%0d]: got 0x%02x expected 0x%02x",
                             name, i, got, exp);
                end
            end
            check(name, ok);
        end
    endtask

    task expect_timestamps(
        input string name,
        input reg [BURST_W-1:0] bits,
        input integer start_value
    );
        integer i;
        reg ok;
        reg [TIMESTAMP_W-1:0] got;
        reg [TIMESTAMP_W-1:0] exp;
        begin
            ok = 1'b1;
            for (i = 0; i < TS_PER_SCAN; i = i + 1) begin
                got = bits[i*TIMESTAMP_W +: TIMESTAMP_W];
                exp = 32'hA500_0000 | ((start_value + i) & (SEG_DEPTH - 1));
                if (got !== exp) begin
                    ok = 1'b0;
                    $display("  %s[%0d]: got 0x%08x expected 0x%08x",
                             name, i, got, exp);
                end
            end
            check(name, ok);
        end
    endtask

    reg [BURST_W-1:0] scan0;
    reg [BURST_W-1:0] scan1;

    initial begin
        repeat (4) tick();
        arst = 1'b0;
        repeat (4) tick();

        $display("\n=== Sample burst starts at requested pointer ===");
        start_burst(10'd42, 1'b0);
        idle_cycles(80);
        scan_sample_burst(scan0);
        scan_sample_burst(scan1);
        expect_samples("primed sample scan starts at 42", scan1, 42);
        scan_sample_burst(scan0);
        expect_samples("next sample scan starts at 74", scan0, 74);

        $display("\n=== Sample burst wraps within segment ===");
        start_burst(10'd250, 1'b0);
        idle_cycles(80);
        scan_sample_burst(scan0);
        scan_sample_burst(scan1);
        expect_samples("sample scan wraps at segment boundary", scan1, 250);

        $display("\n=== Timestamp burst starts at requested pointer ===");
        start_burst(10'd64, 1'b1);
        idle_cycles(80);
        scan_sample_burst(scan0);
        scan_sample_burst(scan1);
        expect_timestamps("primed timestamp scan starts at 64", scan1, 64);

        $display("\n=== jtag_burst_read summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1);
        $finish;
    end
endmodule
