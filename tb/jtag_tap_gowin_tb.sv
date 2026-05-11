// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module GW_JTAG (
    output reg  tck_o,
    output reg  tdi_o,
    output reg  test_logic_reset_o,
    output reg  run_test_idle_er1_o,
    output reg  run_test_idle_er2_o,
    output reg  shift_dr_capture_dr_o,
    output reg  pause_dr_o,
    output reg  update_dr_o,
    output reg  enable_er1_o,
    output reg  enable_er2_o,
    input  wire tdo_er1_i,
    input  wire tdo_er2_i
);
    initial begin
        tck_o = 1'b0;
        tdi_o = 1'b0;
        test_logic_reset_o = 1'b0;
        run_test_idle_er1_o = 1'b0;
        run_test_idle_er2_o = 1'b0;
        shift_dr_capture_dr_o = 1'b0;
        pause_dr_o = 1'b0;
        update_dr_o = 1'b0;
        enable_er1_o = 1'b0;
        enable_er2_o = 1'b0;
    end

    task drive;
        input tck;
        input tdi;
        input reset;
        input shift_capture;
        input pause;
        input update;
        input er1;
        input er2;
        begin
            tck_o = tck;
            tdi_o = tdi;
            test_logic_reset_o = reset;
            shift_dr_capture_dr_o = shift_capture;
            pause_dr_o = pause;
            update_dr_o = update;
            enable_er1_o = er1;
            enable_er2_o = er2;
        end
    endtask

    task drive_tck;
        input tck;
        begin
            tck_o = tck;
        end
    endtask

    wire unused = tdo_er1_i | tdo_er2_i;
endmodule

module jtag_tap_gowin_tb;
    wire tck;
    wire tdi;
    reg  tdo;
    wire capture;
    wire shift;
    wire update;
    wire sel;

    jtag_tap_gowin #(.CHAIN(1)) dut (
        .tck(tck),
        .tdi(tdi),
        .tdo(tdo),
        .capture(capture),
        .shift(shift),
        .update(update),
        .sel(sel)
    );

    integer failures;

    task tick;
        begin
            dut.u_jtag.drive_tck(1'b1);
            #1;
            dut.u_jtag.drive_tck(1'b0);
            #1;
        end
    endtask

    task check_signal;
        input value;
        input [127:0] name;
        begin
            if (!value) begin
                failures = failures + 1;
                $display("FAIL: %0s", name);
            end
        end
    endtask

    initial begin
        failures = 0;
        tdo = 1'b0;

        dut.u_jtag.drive(1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0);
        tick();
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0);
        #1;
        check_signal(sel & !capture & !shift, "selected idle");

        // Hardware appears to keep enable_er1_o asserted after the IR selects
        // ER1.  The first DR-active cycle still must emit CAPTURE-DR.
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0);
        #1;
        check_signal(capture & !shift, "first DR cycle captures with ER already selected");
        tick();
        check_signal(!capture & shift, "second DR cycle shifts");

        // PAUSE-DR must suppress both outputs and must not re-arm capture.
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b1, 1'b1, 1'b0, 1'b1, 1'b0);
        #1;
        check_signal(!capture & !shift, "pause suppresses DR activity");
        tick();
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0);
        #1;
        check_signal(!capture & shift, "pause resume continues shifting");

        // UPDATE-DR terminates the transaction so the next DR scan captures.
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b1, 1'b1, 1'b0);
        tick();
        dut.u_jtag.drive(1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0);
        #1;
        check_signal(capture & !shift, "new DR scan captures after update");

        if (failures == 0) begin
            $display("jtag_tap_gowin_tb: PASS");
            $finish;
        end

        $display("jtag_tap_gowin_tb: %0d failure(s)", failures);
        $finish;
    end
endmodule
