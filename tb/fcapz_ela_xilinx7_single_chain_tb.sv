// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module fcapz_ela_xilinx7_single_chain_tb;
    localparam SAMPLE_W = 8;
    localparam DEPTH = 64;
    localparam BURST_W = 256;

    reg sample_clk = 1'b0;
    reg sample_rst = 1'b1;
    reg [SAMPLE_W-1:0] counter = {SAMPLE_W{1'b0}};

    reg tck = 1'b0;
    reg tdi = 1'b0;
    reg capture = 1'b0;
    reg shift = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;

    integer pass_count = 0;
    integer fail_count = 0;

    always #3 sample_clk = ~sample_clk;
    always #5 tck = ~tck;

    always @(posedge sample_clk or posedge sample_rst) begin
        if (sample_rst)
            counter <= {SAMPLE_W{1'b0}};
        else
            counter <= counter + 1'b1;
    end

    fcapz_ela_xilinx7 #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .TRIG_STAGES(1),
        .STOR_QUAL(0),
        .INPUT_PIPE(0),
        .NUM_CHANNELS(1),
        .DECIM_EN(0),
        .EXT_TRIG_EN(0),
        .TIMESTAMP_W(0),
        .NUM_SEGMENTS(1),
        .STARTUP_ARM(0),
        .BURST_EN(1),
        .SINGLE_CHAIN_BURST(1),
        .CTRL_CHAIN(1),
        .DATA_CHAIN(2),
        .REL_COMPARE(0),
        .DUAL_COMPARE(0),
        .USER1_DATA_EN(1)
    ) dut (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(counter),
        .trigger_in(1'b0),
        .trigger_out(),
        .armed_out(),
        .eio_probe_in(1'b0),
        .eio_probe_out()
    );

    initial begin
        force dut.u_tap_ctrl.u_bscan.TCK = tck;
        force dut.u_tap_ctrl.u_bscan.TDI = tdi;
        force dut.u_tap_ctrl.u_bscan.CAPTURE = capture;
        force dut.u_tap_ctrl.u_bscan.SHIFT = shift;
        force dut.u_tap_ctrl.u_bscan.UPDATE = update;
        force dut.u_tap_ctrl.u_bscan.SEL = sel;
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

    task tick_tck;
        begin
            @(posedge tck);
            #1;
        end
    endtask

    task idle_tck(input integer n);
        integer i;
        begin
            sel = 1'b0;
            capture = 1'b0;
            shift = 1'b0;
            update = 1'b0;
            tdi = 1'b0;
            for (i = 0; i < n; i = i + 1)
                tick_tck();
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
            tick_tck();
            capture = 1'b0;
            shift = 1'b1;
            for (i = 0; i < 49; i = i + 1) begin
                tdi = frame[i];
                if (i < 32)
                    captured[i] = dut.tap1_tdo;
                tick_tck();
            end
            shift = 1'b0;
            tdi = 1'b0;
            update = 1'b1;
            tick_tck();
            update = 1'b0;
            sel = 1'b0;
        end
    endtask

    task write_reg(input [15:0] addr, input [31:0] data);
        reg [31:0] ignored;
        begin
            scan_reg(make_frame(addr, data, 1'b1), ignored);
            idle_tck(8);
        end
    endtask

    task read_reg(input [15:0] addr, output reg [31:0] data);
        reg [31:0] primed;
        begin
            scan_reg(make_frame(addr, 32'h0, 1'b0), primed);
            idle_tck(2);
            scan_reg(make_frame(addr, 32'h0, 1'b0), data);
            idle_tck(2);
        end
    endtask

    task scan_burst(output reg [BURST_W-1:0] bits);
        integer i;
        begin
            bits = {BURST_W{1'b0}};
            sel = 1'b1;
            capture = 1'b1;
            tick_tck();
            capture = 1'b0;
            shift = 1'b1;
            for (i = 0; i < BURST_W; i = i + 1) begin
                tdi = 1'b0;
                bits[i] = dut.tap1_tdo;
                tick_tck();
            end
            shift = 1'b0;
            update = 1'b1;
            tick_tck();
            update = 1'b0;
            sel = 1'b0;
        end
    endtask

    task expect_counter_stride(
        input string name,
        input reg [BURST_W-1:0] bits,
        input integer count
    );
        integer i;
        reg ok;
        reg [SAMPLE_W-1:0] prev;
        reg [SAMPLE_W-1:0] cur;
        begin
            ok = 1'b1;
            prev = bits[0 +: SAMPLE_W];
            for (i = 1; i < count; i = i + 1) begin
                cur = bits[i*SAMPLE_W +: SAMPLE_W];
                if (cur !== ((prev + 1'b1) & 8'hFF))
                    ok = 1'b0;
                prev = cur;
            end
            check(name, ok);
        end
    endtask

    reg [31:0] rdata;
    reg [BURST_W-1:0] stale_scan;
    reg [BURST_W-1:0] burst_a;
    integer poll;

    initial begin
        idle_tck(8);
        repeat (8) @(posedge sample_clk);
        sample_rst = 1'b0;
        idle_tck(12);

        $display("\n=== Xilinx7 wrapper single-chain capture over split clocks ===");
        read_reg(16'h000C, rdata);
        check("SAMPLE_W read through USER1 pipe", rdata == SAMPLE_W);

        write_reg(16'h0014, 32'd4);       // PRETRIG
        write_reg(16'h0018, 32'd8);       // POSTTRIG
        write_reg(16'h0020, 32'h1);       // value_match
        write_reg(16'h0024, 32'h20);      // TRIG_VALUE
        write_reg(16'h0028, 32'hFF);      // TRIG_MASK
        write_reg(16'h0004, 32'h1);       // CTRL.ARM

        rdata = 32'h0;
        for (poll = 0; poll < 200 && !rdata[2]; poll = poll + 1) begin
            idle_tck(8);
            read_reg(16'h0008, rdata);
        end
        check("capture reaches DONE", rdata[2] == 1'b1);

        read_reg(16'h001C, rdata);
        check("capture length is pre+trigger+post", rdata == 32'd13);

        // The wrapper default keeps burst data on USER1.  Write BURST_PTR,
        // allow staging to fill across the unrelated sample/TCK clocks, then
        // discard the first priming scan and check the valid captured samples.
        write_reg(16'h002C, 32'h0);
        idle_tck(80);
        scan_burst(stale_scan);
        scan_burst(burst_a);
        expect_counter_stride("valid single-chain burst samples are sequential", burst_a, 13);

        $display("\n=== fcapz_ela_xilinx7_single_chain summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1);
        $finish;
    end
endmodule
