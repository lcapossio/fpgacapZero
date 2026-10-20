// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// fcapz_ela_polarfire through its UJTAG user interface.  The UJTAG stub's
// user-side outputs (UIREG, UDRCK, UTDI, UDRCAP/SH/UPD) are forced from the
// testbench and TDO is read at the wrapper's UTDO mux, so the IR decode is
// part of the test.
//
//   dut_a: default single-chain burst (USER1) with a shared-chain EIO, the
//          configuration of the Discovery Kit example.
//   dut_b: two-chain burst (USER2 readout), EXT_TRIG_EN and DECIM_EN.
//
// Only the selected DUT sees the forced IR; the other one sees IR 0x00.

`timescale 1ns/1ps

module fcapz_ela_polarfire_tb;
    localparam SAMPLE_W = 8;
    localparam DEPTH = 64;
    localparam BURST_W = 256;
    localparam [7:0] IR_USER1 = 8'h20;
    localparam [7:0] IR_USER2 = 8'h21;

    reg sample_clk = 1'b0;
    reg sample_rst = 1'b1;
    reg [SAMPLE_W-1:0] counter = {SAMPLE_W{1'b0}};

    reg       tck = 1'b0;
    reg       tdi = 1'b0;
    reg       capture = 1'b0;
    reg       shift = 1'b0;
    reg       update = 1'b0;
    reg [7:0] uireg = 8'h00;
    reg       tgt = 1'b0;          // 0 = dut_a, 1 = dut_b

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

    wire [5:0] eio_out_a;
    wire       armed_a, trig_out_a, armed_b, trig_out_b;

    fcapz_ela_polarfire #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .EIO_EN(1),
        .EIO_IN_W(2),
        .EIO_OUT_W(6)
    ) dut_a (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(counter),
        .trigger_in(1'b0),
        .trigger_out(trig_out_a),
        .armed_out(armed_a),
        .eio_probe_in(2'b10),
        .eio_probe_out(eio_out_a),
        .tck_pad_i(1'b0),
        .tms_pad_i(1'b0),
        .tdi_pad_i(1'b0),
        .trstb_pad_i(1'b1),
        .tdo_pad_o()
    );

    fcapz_ela_polarfire #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .SINGLE_CHAIN_BURST(0),
        .EXT_TRIG_EN(1),
        .DECIM_EN(1)
    ) dut_b (
        .sample_clk(sample_clk),
        .sample_rst(sample_rst),
        .probe_in(counter),
        .trigger_in(1'b0),
        .trigger_out(trig_out_b),
        .armed_out(armed_b),
        .eio_probe_in(1'b0),
        .eio_probe_out(),
        .tck_pad_i(1'b0),
        .tms_pad_i(1'b0),
        .tdi_pad_i(1'b0),
        .trstb_pad_i(1'b1),
        .tdo_pad_o()
    );

    // iverilog evaluates a forced expression once, so select through nets.
    wire [7:0] uireg_a = tgt ? 8'h00 : uireg;
    wire [7:0] uireg_b = tgt ? uireg : 8'h00;

    initial begin
        force dut_a.u_tap.u_ujtag.UIREG  = uireg_a;
        force dut_a.u_tap.u_ujtag.UDRCK  = tck;
        force dut_a.u_tap.u_ujtag.UTDI   = tdi;
        force dut_a.u_tap.u_ujtag.UDRCAP = capture;
        force dut_a.u_tap.u_ujtag.UDRSH  = shift;
        force dut_a.u_tap.u_ujtag.UDRUPD = update;
        force dut_b.u_tap.u_ujtag.UIREG  = uireg_b;
        force dut_b.u_tap.u_ujtag.UDRCK  = tck;
        force dut_b.u_tap.u_ujtag.UTDI   = tdi;
        force dut_b.u_tap.u_ujtag.UDRCAP = capture;
        force dut_b.u_tap.u_ujtag.UDRSH  = shift;
        force dut_b.u_tap.u_ujtag.UDRUPD = update;
    end

    wire utdo = tgt ? dut_b.u_tap.utdo : dut_a.u_tap.utdo;

    // Sticky monitors for the sample-domain status outputs.
    reg seen_armed_a = 1'b0, seen_armed_b = 1'b0;
    reg seen_trig_a = 1'b0, seen_trig_b = 1'b0;
    always @(posedge sample_clk) begin
        if (armed_a)    seen_armed_a <= 1'b1;
        if (armed_b)    seen_armed_b <= 1'b1;
        if (trig_out_a) seen_trig_a  <= 1'b1;
        if (trig_out_b) seen_trig_b  <= 1'b1;
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

    // One DR scan of `nbits` with the given IR; returns the bits seen on UTDO.
    task scan_dr(input [7:0] ir, input [BURST_W-1:0] din, input integer nbits,
                 output reg [BURST_W-1:0] dout);
        integer i;
        begin
            dout = {BURST_W{1'b0}};
            uireg = ir;
            capture = 1'b1;
            tick_tck();
            capture = 1'b0;
            shift = 1'b1;
            for (i = 0; i < nbits; i = i + 1) begin
                tdi = din[i];
                dout[i] = utdo;
                tick_tck();
            end
            shift = 1'b0;
            tdi = 1'b0;
            update = 1'b1;
            tick_tck();
            update = 1'b0;
        end
    endtask

    task scan_reg_ir(input [7:0] ir, input [48:0] frame, output reg [31:0] captured);
        reg [BURST_W-1:0] bits;
        begin
            scan_dr(ir, {{(BURST_W-49){1'b0}}, frame}, 49, bits);
            captured = bits[31:0];
        end
    endtask

    task write_reg(input [15:0] addr, input [31:0] data);
        reg [31:0] ignored;
        begin
            scan_reg_ir(IR_USER1, make_frame(addr, data, 1'b1), ignored);
            idle_tck(8);
        end
    endtask

    task read_reg(input [15:0] addr, output reg [31:0] data);
        reg [31:0] primed;
        begin
            scan_reg_ir(IR_USER1, make_frame(addr, 32'h0, 1'b0), primed);
            idle_tck(2);
            scan_reg_ir(IR_USER1, make_frame(addr, 32'h0, 1'b0), data);
            idle_tck(2);
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

    // Arm a value-match capture on 0x20 (4 pre + trigger + 8 post) and wait.
    task capture_ramp(input string tag);
        reg [31:0] rdata;
        integer poll;
        begin
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
            check({tag, ": capture reaches DONE"}, rdata[2] == 1'b1);

            read_reg(16'h001C, rdata);
            check({tag, ": capture length is pre+trigger+post"}, rdata == 32'd13);
        end
    endtask

    reg [31:0] rdata;
    reg [31:0] pretrig_was;
    reg [BURST_W-1:0] bits;
    reg [BURST_W-1:0] burst;
    reg quiet;
    integer i;

    initial begin
        idle_tck(8);
        repeat (8) @(posedge sample_clk);
        sample_rst = 1'b0;
        idle_tck(12);

        // ---------------------------------------------------------------
        $display("\n=== dut_a: single-chain burst + shared-chain EIO ===");
        tgt = 1'b0;

        read_reg(16'h000C, rdata);
        check("A: SAMPLE_W through IR 0x20", rdata == SAMPLE_W);

        // A non-user IR must not reach the cores or drive UTDO.
        read_reg(16'h0014, pretrig_was);
        scan_dr(8'h10, {{(BURST_W-49){1'b0}}, make_frame(16'h0014, 32'h7, 1'b1)}, 49, bits);
        quiet = (bits == {BURST_W{1'b0}});
        idle_tck(8);
        read_reg(16'h0014, rdata);
        check("A: IR 0x10 scan leaves UTDO low", quiet);
        check("A: IR 0x10 write is ignored", rdata == pretrig_was);

        read_reg(16'h8004, rdata);
        check("A: EIO IN_W at 0x8004", rdata == 32'd2);
        read_reg(16'h8008, rdata);
        check("A: EIO OUT_W at 0x8008", rdata == 32'd6);
        read_reg(16'h8010, rdata);
        check("A: EIO inputs read back", rdata[1:0] == 2'b10);
        write_reg(16'h8100, 32'h15);
        repeat (8) @(posedge sample_clk);
        check("A: EIO outputs driven", eio_out_a == 6'h15);

        capture_ramp("A");
        check("A: armed_out asserted while armed", seen_armed_a);
        check("A: trigger_out stays low without EXT_TRIG_EN", !seen_trig_a);

        write_reg(16'h002C, 32'h0);           // BURST_PTR
        idle_tck(80);
        scan_dr(IR_USER1, {BURST_W{1'b0}}, BURST_W, bits);   // priming scan
        scan_dr(IR_USER1, {BURST_W{1'b0}}, BURST_W, burst);
        expect_counter_stride("A: USER1 burst samples are sequential", burst, 13);

        // USER2 is unused with SINGLE_CHAIN_BURST=1 and must read as zero.
        scan_dr(IR_USER2, {BURST_W{1'b0}}, BURST_W, bits);
        check("A: USER2 reads zero in single-chain mode", bits == {BURST_W{1'b0}});

        // ---------------------------------------------------------------
        $display("\n=== dut_b: two-chain burst (USER2), EXT_TRIG_EN, DECIM_EN ===");
        tgt = 1'b1;
        idle_tck(4);

        read_reg(16'h003C, rdata);
        check("B: FEATURES reports ext trigger", rdata[6] == 1'b1);
        write_reg(16'h00B4, 32'h2);           // TRIG_EXT: OR mode
        read_reg(16'h00B4, rdata);
        check("B: TRIG_EXT reads back", rdata[1:0] == 2'b10);
        write_reg(16'h00B0, 32'h3);           // DECIM
        read_reg(16'h00B0, rdata);
        check("B: DECIM reads back", rdata == 32'h3);
        write_reg(16'h00B4, 32'h0);           // TRIG_EXT: disabled
        write_reg(16'h00B0, 32'h0);           // DECIM: every sample

        capture_ramp("B");
        check("B: armed_out asserted while armed", seen_armed_b);
        check("B: trigger_out pulsed on the trigger", seen_trig_b);

        write_reg(16'h002C, 32'h0);           // BURST_PTR, still on USER1
        idle_tck(80);
        scan_dr(IR_USER2, {BURST_W{1'b0}}, BURST_W, bits);   // priming scan
        idle_tck(80);
        scan_dr(IR_USER2, {BURST_W{1'b0}}, BURST_W, burst);
        expect_counter_stride("B: USER2 burst samples are sequential", burst, 13);

        $display("\n=== fcapz_ela_polarfire summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1);
        $finish;
    end
endmodule
