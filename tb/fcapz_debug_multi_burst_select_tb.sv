// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// A core-manager slot switch right after a burst. The pipe stays in burst
// mode until a register command updates, so the switch scan's capture starts
// one more preload (~256/SAMPLE_W TCKs). With narrow samples that preload
// still runs when the ACTIVE write commits, and the manager ignores the
// write. The host confirms the selection by reading ACTIVE back and writes
// again (Transport.select_manager_instance_cached); this bench checks that
// its three attempts land the switch at every width.

module fcapz_debug_multi_burst_select_tb #(
    parameter SAMPLE_W = 4
);
    localparam DEPTH = 64;

    reg tck = 1'b0;
    reg tdi = 1'b0;
    reg capture = 1'b0;
    reg shift = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;
    wire tdo_mon;
    reg sel_idle;
    reg tdi_noise = 1'b0;
    integer pass_count = 0;
    integer fail_count = 0;

    reg sample_clk = 1'b0;
    reg [1:0] sample_rst = 2'b11;

    always #5 tck = ~tck;
    always #3 sample_clk = ~sample_clk;

    fcapz_debug_multi #(
        .NUM_ELAS(2),
        .EIO_EN(1),
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH)
    ) dut (
        .tck(tck), .tdi(tdi), .tdo(tdo_mon),
        .capture(capture), .shift(shift), .update(update), .sel(sel),
        .ela_sample_clk({2{sample_clk}}),
        .ela_sample_rst(sample_rst),
        .ela_probe_in({2*SAMPLE_W{1'b0}}),
        .ela_trigger_in(2'b00),
        .ela_trigger_out(),
        .ela_armed_out(),
        .eio_probe_in(1'b0),
        .eio_probe_out()
    );

`include "fcapz_pipe_jtag_tasks.svh"

    reg [31:0] active;
    reg [255:0] first, second;
    integer writes;
    integer first_write_landed;

    initial begin
        // The Intel gate shape: sel stays high between scans.
        sel_idle = 1'b1;
        idle_tck(8);
        sample_rst = 2'b00;
        idle_tck(16);

        write_reg(16'hF008, 32'd0);
        read_burst(1'b0, first, second);

        // Switch slots straight after the burst, then confirm as the host does.
        writes = 0;
        first_write_landed = 0;
        active = 32'hFFFF_FFFF;
        // Transport.MANAGER_SELECT_ATTEMPTS
        while (active != 32'd1 && writes < 3) begin
            write_reg(16'hF008, 32'd1);
            writes = writes + 1;
            read_reg(16'hF008, active);
            if (writes == 1 && active == 32'd1)
                first_write_landed = 1;
        end
        $display("SAMPLE_W=%0d: first ACTIVE write %s, %0d write(s)", SAMPLE_W,
                 first_write_landed ? "landed" : "ignored", writes);
        check("ACTIVE switch lands after a burst", active == 32'd1);

        $display("=== fcapz_debug_multi_burst_select SAMPLE_W=%0d: %0d passed, %0d failed ===",
                 SAMPLE_W, pass_count, fail_count);
        $finish;
    end
endmodule
