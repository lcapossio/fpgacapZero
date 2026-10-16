// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// JTAG driver tasks for a jtag_pipe_iface chain: 49-bit register scans and
// 256-bit burst scans, LSB first, as the host transports shift them.
//
// The including module declares:
//   reg tck, tdi, capture, shift, update, sel;
//   wire tdo_mon;          // the chain's TDO
//   reg sel_idle;          // sel between scans: 0 on BSCANE2, 1 on Intel
//                          // virtual JTAG (its sel is tied high)
//   reg tdi_noise;         // 1: toggle tdi while idle (another instance's
//                          // traffic on a shared Intel TCK)
//   integer pass_count, fail_count;

task automatic check(input string name, input bit cond);
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

task automatic tick_tck;
    begin
        @(posedge tck);
        #1;
    end
endtask

task automatic idle_tck(input integer n);
    integer i;
    begin
        sel = sel_idle;
        capture = 1'b0;
        shift = 1'b0;
        update = 1'b0;
        tdi = 1'b0;
        for (i = 0; i < n; i = i + 1) begin
            if (tdi_noise)
                tdi = $random;
            tick_tck();
        end
        tdi = 1'b0;
    end
endtask

task automatic scan_reg(input [48:0] frame, output reg [31:0] captured);
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
                captured[i] = tdo_mon;
            tick_tck();
        end
        shift = 1'b0;
        tdi = 1'b0;
        update = 1'b1;
        tick_tck();
        update = 1'b0;
        sel = sel_idle;
    end
endtask

task automatic write_reg(input [15:0] addr, input [31:0] data);
    reg [31:0] ignored;
    begin
        scan_reg({1'b1, addr, data}, ignored);
        idle_tck(8);
    end
endtask

// A read is a request scan, then a response scan (the pipe's one-deep queue).
task automatic read_reg(input [15:0] addr, output reg [31:0] data);
    reg [31:0] primed;
    begin
        scan_reg({1'b0, addr, 32'h0}, primed);
        idle_tck(2);
        scan_reg({1'b0, addr, 32'h0}, data);
        idle_tck(2);
    end
endtask

task automatic scan_burst(output reg [255:0] bits);
    integer i;
    begin
        bits = 256'h0;
        sel = 1'b1;
        capture = 1'b1;
        tick_tck();
        capture = 1'b0;
        shift = 1'b1;
        for (i = 0; i < 256; i = i + 1) begin
            tdi = 1'b0;
            bits[i] = tdo_mon;
            tick_tck();
        end
        shift = 1'b0;
        update = 1'b1;
        tick_tck();
        update = 1'b0;
        sel = sel_idle;
    end
endtask

// Write BURST_PTR, let the pipe stage, discard the priming scan, return the
// next two packets.
task automatic read_burst(
    input bit timestamp,
    output reg [255:0] first,
    output reg [255:0] second
);
    reg [255:0] prime;
    begin
        write_reg(16'h002C, timestamp ? 32'h8000_0000 : 32'h0);
        idle_tck(160);
        scan_burst(prime);
        scan_burst(first);
        scan_burst(second);
        idle_tck(4);
    end
endtask
