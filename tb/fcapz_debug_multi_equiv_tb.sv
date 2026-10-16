// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fcapz_debug_multi_xilinx7 after the vendor-free split must behave exactly
// as before it. Both versions -- the frozen pre-split copy
// (tb/legacy/fcapz_debug_multi_xilinx7_ref.v) and the current wrapper -- get
// the same TAP stimulus and probes; TDO and every output must match on every
// TCK, except where the hub changed on purpose: the reference keeps the
// manager from before the burst header (tb/legacy), so each burst's priming
// scan (junk there, the header here) and the MGR_CAPS read are not compared;
// the header is checked on its own. SHAPE picks a parameter set:
//   0 default (2 ELAs + 1 EIO)        1 heterogeneous slots + timestamps
//   2 EIO only (NUM_ELAS=0)           3 dependent defaults (3 ELAs, EIO_EN=0)
//   4 segments + timestamps           5 4-bit samples

module fcapz_debug_multi_equiv_tb #(
    parameter integer SHAPE = 0
);
    reg tck = 1'b0;
    reg tdi = 1'b0;
    reg capture = 1'b0;
    reg shift = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;
    reg sel_idle = 1'b0;
    reg tdi_noise = 1'b0;
    wire tdo_mon;

    integer pass_count = 0;
    integer fail_count = 0;

    reg clk_a = 1'b0;
    reg clk_b = 1'b0;
    reg sample_rst = 1'b1;
    reg [63:0] cnt_a = 64'h0;
    reg [63:0] cnt_b = 64'h0;
    reg [2:0] trig_in = 3'b000;

    always #5 tck = ~tck;
    always #3 clk_a = ~clk_a;
    always #4 clk_b = ~clk_b;
    always @(posedge clk_a) cnt_a <= sample_rst ? 64'h0 : cnt_a + 64'h0001_0001_0001_0001;
    always @(posedge clk_b) cnt_b <= sample_rst ? 64'h0 : cnt_b + 64'h0003_0003_0003_0003;

    // The probe bus is wider than any shape needs; ports take the low bits.
    wire [511:0] probes = {4{cnt_b ^ 64'h5A5A_A5A5_0F0F_F0F0, cnt_a}};
    wire [63:0] eio_in = {cnt_b[31:0], cnt_a[31:0]};
    // Neighbouring ELAs sample on unrelated clocks.
    wire [2:0] sample_clks = {clk_a, clk_b, clk_a};

    localparam integer N_ELA = (SHAPE == 3) ? 3 : (SHAPE == 2) ? 1 : 2;
    localparam integer NUM_ELAS = (SHAPE == 2) ? 0 : N_ELA;
    localparam integer N_EIO = (SHAPE == 1 || SHAPE == 2) ? 2 : (SHAPE == 3) ? 0 : 1;
    localparam integer TS = (SHAPE == 1 || SHAPE == 4) ? 1 : 0;
    localparam integer BURST_SAMPLE_W = (SHAPE == 1) ? 32 : (SHAPE == 5) ? 4 : 8;

    `include "fcapz_pipe_jtag_tasks.svh"

    // ---- the two versions, same parameters ------------------------------
`define FCAPZ_EQUIV_PAIR(PARAMS, N_ELA, PROBE_BITS, EIO_IN_BITS, EIO_OUT_BITS) \
    wire [N_ELA-1:0] trig_ref, trig_new, armed_ref, armed_new; \
    wire [EIO_OUT_BITS-1:0] eio_ref, eio_new; \
    fcapz_debug_multi_xilinx7_ref #PARAMS u_ref ( \
        .ela_sample_clk(sample_clks[N_ELA-1:0]), \
        .ela_sample_rst({N_ELA{sample_rst}}), \
        .ela_probe_in(probes[PROBE_BITS-1:0]), \
        .ela_trigger_in(trig_in[N_ELA-1:0]), \
        .ela_trigger_out(trig_ref), .ela_armed_out(armed_ref), \
        .eio_probe_in(eio_in[EIO_IN_BITS-1:0]), .eio_probe_out(eio_ref)); \
    fcapz_debug_multi_xilinx7 #PARAMS u_new ( \
        .ela_sample_clk(sample_clks[N_ELA-1:0]), \
        .ela_sample_rst({N_ELA{sample_rst}}), \
        .ela_probe_in(probes[PROBE_BITS-1:0]), \
        .ela_trigger_in(trig_in[N_ELA-1:0]), \
        .ela_trigger_out(trig_new), .ela_armed_out(armed_new), \
        .eio_probe_in(eio_in[EIO_IN_BITS-1:0]), .eio_probe_out(eio_new));

    generate
        if (SHAPE == 0) begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(2), .EIO_EN(1), .SAMPLE_W(8), .DEPTH(64),
                .EIO_IN_W(8), .EIO_OUT_W(8)), 2, 16, 8, 8)
        end else if (SHAPE == 1) begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(2), .EIO_EN(1), .NUM_EIOS(2), .SAMPLE_W(32),
                .DEPTH(128), .TIMESTAMP_W(32), .NUM_SEGMENTS(4), .EIO_IN_W(16),
                .EIO_OUT_W(16), .ELA_SAMPLE_WS({32'd32, 32'd16}),
                .ELA_DEPTHS({32'd128, 32'd64}), .ELA_TIMESTAMP_WS({32'd32, 32'd0}),
                .ELA_NUM_SEGMENTS({32'd4, 32'd1}), .ELA_DECIM_ENS({32'd1, 32'd0}),
                .ELA_EXT_TRIG_ENS({32'd1, 32'd0}), .EIO_IN_WS({32'd12, 32'd8}),
                .EIO_OUT_WS({32'd16, 32'd4})), 2, 64, 32, 32)
        end else if (SHAPE == 2) begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(0), .EIO_EN(1), .NUM_EIOS(2), .SAMPLE_W(8),
                .DEPTH(64), .EIO_IN_W(8), .EIO_OUT_W(8)), 1, 8, 16, 16)
        end else if (SHAPE == 3) begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(3), .EIO_EN(0), .SAMPLE_W(8), .DEPTH(64)),
                3, 24, 1, 1)
        end else if (SHAPE == 4) begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(2), .EIO_EN(1), .SAMPLE_W(8), .DEPTH(64),
                .TIMESTAMP_W(8), .NUM_SEGMENTS(2), .EIO_IN_W(4), .EIO_OUT_W(4)),
                2, 16, 4, 4)
        end else begin : g_dut
            `FCAPZ_EQUIV_PAIR((.NUM_ELAS(2), .EIO_EN(1), .SAMPLE_W(4), .DEPTH(64),
                .EIO_IN_W(8), .EIO_OUT_W(8)), 2, 8, 8, 8)
        end
    endgenerate

    // Both stubs' BSCANE2 outputs carry the same TAP stimulus.
    initial begin
        force g_dut.u_ref.u_tap_ctrl.u_bscan.TCK = tck;
        force g_dut.u_ref.u_tap_ctrl.u_bscan.TDI = tdi;
        force g_dut.u_ref.u_tap_ctrl.u_bscan.CAPTURE = capture;
        force g_dut.u_ref.u_tap_ctrl.u_bscan.SHIFT = shift;
        force g_dut.u_ref.u_tap_ctrl.u_bscan.UPDATE = update;
        force g_dut.u_ref.u_tap_ctrl.u_bscan.SEL = sel;
        force g_dut.u_new.u_tap_ctrl.u_bscan.TCK = tck;
        force g_dut.u_new.u_tap_ctrl.u_bscan.TDI = tdi;
        force g_dut.u_new.u_tap_ctrl.u_bscan.CAPTURE = capture;
        force g_dut.u_new.u_tap_ctrl.u_bscan.SHIFT = shift;
        force g_dut.u_new.u_tap_ctrl.u_bscan.UPDATE = update;
        force g_dut.u_new.u_tap_ctrl.u_bscan.SEL = sel;
    end
    assign tdo_mon = g_dut.u_ref.tap_tdo;

    // ---- lockstep comparison ---------------------------------------------
    integer mismatches = 0;
    integer compared = 0;
    reg compare_en = 1'b1;
    always @(negedge tck) if (compare_en) begin
        compared = compared + 1;
        if (g_dut.u_ref.tap_tdo !== g_dut.u_new.tap_tdo ||
            g_dut.trig_ref !== g_dut.trig_new ||
            g_dut.armed_ref !== g_dut.armed_new ||
            g_dut.eio_ref !== g_dut.eio_new) begin
            if (mismatches < 10)
                $display("MISMATCH @%0t: tdo %b/%b trig %b/%b armed %b/%b eio %h/%h",
                         $time, g_dut.u_ref.tap_tdo, g_dut.u_new.tap_tdo,
                         g_dut.trig_ref, g_dut.trig_new,
                         g_dut.armed_ref, g_dut.armed_new,
                         g_dut.eio_ref, g_dut.eio_new);
            mismatches = mismatches + 1;
        end
    end

    // ---- stimulus ----------------------------------------------------------
    reg [31:0] rdata;
    reg [255:0] pkt_a, pkt_b;
    reg [15:0] core_ids [0:7];
    reg has_burst [0:7];
    integer slot, round, poll, n_slots, bursts;
    reg [31:0] other;
    reg any_data;

    task automatic select_slot(input integer s);
        begin
            write_reg(16'hF008, s);
        end
    endtask

    // read_burst, but the priming scan is captured from the new hub and
    // checked as a header instead of compared.
    reg [255:0] header;
    task automatic equiv_read_burst(
        input bit timestamp,
        input integer owner_slot,
        output reg [255:0] first,
        output reg [255:0] second
    );
        integer b;
        begin
            write_reg(16'h002C, timestamp ? 32'h8000_0000 : 32'h0);
            idle_tck(160);
            compare_en = 1'b0;
            header = 256'h0;
            sel = 1'b1;
            capture = 1'b1;
            tick_tck();
            capture = 1'b0;
            shift = 1'b1;
            for (b = 0; b < 256; b = b + 1) begin
                tdi = 1'b0;
                header[b] = g_dut.u_new.tap_tdo;
                tick_tck();
            end
            shift = 1'b0;
            update = 1'b1;
            tick_tck();
            update = 1'b0;
            sel = sel_idle;
            compare_en = 1'b1;
            check($sformatf("burst header names slot %0d, timestamp %0d", owner_slot, timestamp),
                  header[15:0] == 16'h4248 && header[31:16] == owner_slot &&
                  header[64] == timestamp && header[79:65] == 15'h0 &&
                  header[159:144] == BURST_SAMPLE_W && header[255:160] == 96'h0);
            scan_burst(first);
            scan_burst(second);
            idle_tck(4);
        end
    endtask

    task automatic arm_all_elas(input integer round_no);
        integer s;
        begin
            for (s = 0; s < NUM_ELAS; s = s + 1) begin
                select_slot(s);
                write_reg(16'h0014, 32'd3 + round_no);   // PRETRIG
                write_reg(16'h0018, 32'd9 + 2*round_no); // POSTTRIG
                write_reg(16'h0020, 32'h1);              // value_match
                write_reg(16'h0024, 32'h0);
                write_reg(16'h0028, 32'h0);              // mask 0: fires at once
                write_reg(16'h0004, 32'h1);              // ARM
            end
        end
    endtask

    initial begin
        idle_tck(8);
        repeat (8) @(posedge clk_a);
        // Between edges, not on one: released on an edge of any clock it
        // races that clock, and the two hubs can start a sample apart.
        #0.5 sample_rst = 1'b0;
        idle_tck(16);

        $display("\n=== fcapz_debug_multi equivalence, SHAPE=%0d ===", SHAPE);
        read_reg(16'hF000, rdata);
        check("manager identity reads 'CM'", rdata[15:0] == 16'h434D);
        read_reg(16'hF004, rdata);
        n_slots = rdata;
        check("slot count is NUM_ELAS + NUM_EIOS", n_slots == NUM_ELAS + N_EIO);
        // The old hub's CAPS differs, and the next scan's capture shows it again.
        compare_en = 1'b0;
        read_reg(16'hF010, rdata);
        read_reg(16'hF000, rdata);
        compare_en = 1'b1;

        // Descriptors, then each slot's identity through ACTIVE.
        for (slot = 0; slot < n_slots; slot = slot + 1) begin
            write_reg(16'hF014, slot);
            read_reg(16'hF018, rdata);
            core_ids[slot] = rdata[15:0];
            read_reg(16'hF01C, rdata);
            has_burst[slot] = rdata[0];
            select_slot(slot);
            read_reg(16'h0000, rdata);
            check($sformatf("slot %0d answers with its descriptor's identity", slot),
                  rdata[15:0] == core_ids[slot]);
            read_reg(16'h0004, rdata);
            read_reg(16'h000C, rdata);
            read_reg(16'h0010, rdata);
        end
        // An out-of-range ACTIVE write is ignored.
        select_slot(n_slots + 3);
        read_reg(16'hF008, rdata);

        // Two capture rounds; bursts alternate between ELA slots, each read
        // twice, so the owner switch and the start pointer both move.
        any_data = 1'b0;
        bursts = 0;
        for (round = 0; round < 2; round = round + 1) begin
            arm_all_elas(round);
            trig_in = 3'b111;
            idle_tck(4);
            trig_in = 3'b000;
            for (slot = 0; slot < NUM_ELAS; slot = slot + 1) begin
                select_slot(slot);
                rdata = 32'h0;
                for (poll = 0; poll < 100 && !rdata[2]; poll = poll + 1) begin
                    idle_tck(16);
                    read_reg(16'h0008, rdata);
                end
                check($sformatf("round %0d: ELA slot %0d completes", round, slot), rdata[2]);
                read_reg(16'h001C, rdata);
                read_reg(16'h00BC, rdata);  // SEG_STATUS
                read_reg(16'h00C8, rdata);  // SEG_START
            end
            for (slot = 0; slot < NUM_ELAS; slot = slot + 1) begin
                if (has_burst[slot]) begin
                    select_slot(slot);
                    equiv_read_burst(1'b0, slot, pkt_a, pkt_b);
                    any_data = any_data | (|pkt_a) | (|pkt_b);
                    bursts = bursts + 1;
                    if (TS) begin
                        equiv_read_burst(1'b1, slot, pkt_a, pkt_b);
                        bursts = bursts + 1;
                    end
                    // Back to back: ACTIVE right after the burst, no idle.
                    other = NUM_ELAS - 1 - slot;
                    scan_reg({1'b1, 16'hF008, other}, rdata);
                    read_reg(16'hF008, rdata);
                end
            end
            // The second ELA again, without re-selecting through a register.
            if (NUM_ELAS > 1 && has_burst[1]) begin
                select_slot(1);
                equiv_read_burst(1'b0, 1, pkt_a, pkt_b);
                bursts = bursts + 1;
            end
        end
        if (NUM_ELAS > 0 && has_burst[0])
            check("bursts carried captured data", any_data);

        // EIO slots: widths, inputs, an output write and its readback.
        for (slot = NUM_ELAS; slot < n_slots; slot = slot + 1) begin
            select_slot(slot);
            read_reg(16'h0004, rdata);
            read_reg(16'h0008, rdata);
            read_reg(16'h0010, rdata);
            write_reg(16'h0100, 32'hA5C3_0000 | slot);
            read_reg(16'h0100, rdata);
            check($sformatf("EIO slot %0d output write reads back", slot),
                  rdata[0] == slot[0]);
        end

        idle_tck(32);
        $display("compared %0d TCK edges over %0d bursts: %0d mismatches",
                 compared, bursts, mismatches);
        check("old and new wrappers match on every TCK", mismatches == 0 && compared > 1000);
        $display("\n=== fcapz_debug_multi_equiv SHAPE=%0d: %0d passed, %0d failed ===",
                 SHAPE, pass_count, fail_count);
        if (fail_count != 0)
            $fatal(1);
        $finish;
    end
endmodule
