// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>
`timescale 1ns/1ps
// tools/fcapz_insert_wrap.v cross-triggers: each trigger_out pulse of the
// source ELA reaches the destination ELA's trigger input as exactly one
// pulse of one destination clock, whichever clock is faster.
//
// ELA 0 on a 10 ns clock, ELA 1 on 37 ns, ELA 2 on 7 ns.
// ELA 0 triggers ELA 1 (fast to slow); ELA 2 triggers ELA 0 (fast to
// slower); ELA 2 has no source.
module fcapz_insert_wrap_tb;
`ifndef ULTRASCALE
    localparam US = 0;
`else
    localparam US = 1;
`endif
    reg [2:0] clk = 3'b000;
    always #5    clk[0] = ~clk[0];
    always #18.5 clk[1] = ~clk[1];
    always #3.5  clk[2] = ~clk[2];

    reg  [2:0] trig_in = 3'b000;
    wire [2:0] trig_out, armed;
    wire [0:0] eio_out;

    fcapz_insert_wrap #(
        .NUM_ELAS(3), .SAMPLE_W(4), .DEPTH(16),
        .ELA_EXT_TRIG_ENS({32'd0, 32'd1, 32'd1}),
        // Per destination: source slot + 1.  dst2: none, dst1: ELA 0, dst0: ELA 2.
        .XTRIG_SRCS({8'd0, 8'd1, 8'd3}),
        .ULTRASCALE(US)
    ) dut (
        .ela_sample_clk(clk),
        .ela_probe_in(12'h000),
        .ela_trigger_in(trig_in),
        .ela_trigger_out(trig_out),
        .ela_armed_out(armed),
        .eio_probe_in(1'b0),
        .eio_probe_out(eio_out)
    );

    // Pulses seen at each ELA's trigger input, and the longest run of
    // consecutive high destination clocks.
    integer seen [0:2];
    integer run  [0:2];
    integer worst[0:2];
    genvar g;
    generate
        for (g = 0; g < 3; g = g + 1) begin : g_mon
            initial begin seen[g] = 0; run[g] = 0; worst[g] = 0; end
            always @(posedge clk[g]) begin
                if (dut.ela_trig[g]) begin
                    if (run[g] == 0) seen[g] = seen[g] + 1;
                    run[g] = run[g] + 1;
                    if (run[g] > worst[g]) worst[g] = run[g];
                end else begin
                    run[g] = 0;
                end
            end
        end
    endgenerate

    // The ELAs' trigger outputs, driven from here (the ELAs never trigger).
    reg [2:0] tout = 3'b000;

    // One trigger_out pulse of one source clock, as an ELA gives.
    task automatic pulse(input integer src);
        begin
            @(posedge clk[src]);
            #0.1 tout[src] = 1'b1;
            @(posedge clk[src]);
            #0.1 tout[src] = 1'b0;
        end
    endtask

    integer errors = 0;
    task automatic expect_counts(input integer a, input integer b, input integer c);
        begin
            if (seen[0] !== a || seen[1] !== b || seen[2] !== c) begin
                $display("FAIL: pulses seen %0d %0d %0d, expected %0d %0d %0d",
                         seen[0], seen[1], seen[2], a, b, c);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        force dut.ela_trigger_out = tout;
        repeat (20) @(posedge clk[1]);
        // Let the free-running synchronizers settle from their power-up 0s.
        expect_counts(0, 0, 0);

        pulse(0);                       // fast ELA 0 -> slow ELA 1
        repeat (10) @(posedge clk[1]);
        expect_counts(0, 1, 0);

        pulse(2);                       // ELA 2 -> ELA 0
        repeat (10) @(posedge clk[1]);
        expect_counts(1, 1, 0);

        pulse(0);                       // a second trigger is a second pulse
        repeat (10) @(posedge clk[1]);
        expect_counts(1, 2, 0);

        pulse(1);                       // ELA 1 is nobody's source
        repeat (10) @(posedge clk[1]);
        expect_counts(1, 2, 0);

        // The external trigger input still reaches its ELA.
        @(posedge clk[2]); #0.1 trig_in[2] = 1'b1;
        @(posedge clk[2]); #0.1 trig_in[2] = 1'b0;
        repeat (4) @(posedge clk[1]);
        expect_counts(1, 2, 1);

        if (worst[0] != 1 || worst[1] != 1) begin
            $display("FAIL: a cross-trigger pulse lasted %0d / %0d clocks, expected 1",
                     worst[0], worst[1]);
            errors = errors + 1;
        end
        if (errors == 0) $display("PASS");
        $finish;
    end
endmodule
