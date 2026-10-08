// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// The host's burst sequences against a core manager from before MGR_CAPS
// bit 2 (tb/legacy/) and against the current one.
//
// The old manager passed on the owner slot's own start toggle.  The burst
// reader keeps one last-seen copy, so after a slot switch the new slot's
// toggle can equal it: the start is missed and the burst reads the new slot
// from the previous burst's pointer.  The host's sync (Transport.
// burst_start_sync) writes BURST_PTR, runs one burst scan whose capture copies
// the toggle, then writes BURST_PTR again; that start cannot be missed.
//
// Every case runs the same slot/pointer script.  A model of the slots' start
// toggles and the reader's last-seen copy predicts which naive bursts miss
// their start; each burst must read correctly, or misread exactly where the
// model predicts.  Two slots each return {slot + 1, 2'b00, address}, so a
// miss shows as the right slot's data at stale addresses.
//
// The two-chain reader (jtag_burst_read) compares the toggle at burst scan
// captures; the single-chain pipe compares it at every capture.  Register
// scans between the slot switch and the BURST_PTR write (GAP_SCANS) change
// nothing on either: the old manager moves the burst owner only on the
// BURST_PTR write or on burst activity, so they still compare the old
// owner's toggle, which the reader has already seen.

module legacy_burst_case #(
    parameter LEGACY = 1,
    parameter SINGLE_CHAIN = 1,
    parameter GAP_SCANS = 0,
    parameter SYNC = 0
) (
    output reg        done,
    output reg [31:0] fails,
    output reg [31:0] misses_seen0,
    output reg [31:0] misses_seen1
);
    localparam NUM_SLOTS = 2;
    localparam SAMPLE_W = 16;
    localparam DEPTH = 1024;
    localparam PTR_W = 10;
    localparam BURST_W = 256;
    localparam SPS = BURST_W / SAMPLE_W;
    localparam DATA_SCANS = 2;
    localparam WRITE_IDLE = 40;

    reg tck = 1'b0;
    always #5 tck = ~tck;

    reg arst = 1'b1;
    reg tdi = 1'b0;
    reg capture = 1'b0;
    reg shift_en = 1'b0;
    reg update = 1'b0;
    reg sel = 1'b0;
    wire tdo;

    // Register bus into the manager: the pipe's in single-chain mode, driven
    // directly in two-chain mode (USER1 is invisible to the burst reader).
    reg tb_wr_en = 1'b0;
    reg tb_rd_en = 1'b0;
    reg [15:0] tb_addr = 16'h0;
    reg [31:0] tb_wdata = 32'h0;
    wire pipe_wr_en, pipe_rd_en;
    wire [15:0] pipe_addr;
    wire [31:0] pipe_wdata;
    wire mgr_wr_en = SINGLE_CHAIN ? pipe_wr_en : tb_wr_en;
    wire mgr_rd_en = SINGLE_CHAIN ? pipe_rd_en : tb_rd_en;
    wire [15:0] mgr_addr = SINGLE_CHAIN ? pipe_addr : tb_addr;
    wire [31:0] mgr_wdata = SINGLE_CHAIN ? pipe_wdata : tb_wdata;
    wire [31:0] mgr_rdata;

    wire [PTR_W-1:0] rd_addr;
    wire rd_active;
    wire [SAMPLE_W-1:0] rd_data;
    wire rd_ts_data;
    wire bstart;
    wire bts;
    wire [PTR_W-1:0] bptr;

    wire [NUM_SLOTS-1:0] slot_wr_en;
    wire [NUM_SLOTS-1:0] slot_rd_en;
    wire [NUM_SLOTS*16-1:0] slot_addr;
    wire [NUM_SLOTS*32-1:0] slot_wdata;
    wire [NUM_SLOTS*PTR_W-1:0] slot_rd_addr;
    wire [NUM_SLOTS-1:0] slot_rd_active;
    reg [NUM_SLOTS*SAMPLE_W-1:0] slot_rd_data = {NUM_SLOTS*SAMPLE_W{1'b0}};
    reg [NUM_SLOTS-1:0] slot_flag = {NUM_SLOTS{1'b0}};
    reg [NUM_SLOTS*PTR_W-1:0] slot_ptr = {NUM_SLOTS*PTR_W{1'b0}};

    // Burst slot stubs: a BURST_PTR write latches the pointer and toggles the
    // slot's own start flag (as the ELA does); RAM reads take one clock.
    integer si;
    always @(posedge tck) begin
        for (si = 0; si < NUM_SLOTS; si = si + 1) begin
            slot_rd_data[si*SAMPLE_W +: SAMPLE_W] <=
                {(si == 0) ? 4'd1 : 4'd2, 2'b00, slot_rd_addr[si*PTR_W +: PTR_W]};
            if (slot_wr_en[si] && slot_addr[si*16 +: 16] == 16'h002C) begin
                slot_ptr[si*PTR_W +: PTR_W] <= slot_wdata[si*32 +: PTR_W];
                slot_flag[si] <= ~slot_flag[si];
            end
        end
    end

    generate
        if (LEGACY) begin : g_mgr
            fcapz_core_manager_pre_burst_start #(
                .NUM_SLOTS(NUM_SLOTS), .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0),
                .DEPTH(DEPTH), .SLOT_CORE_IDS({16'h4C41, 16'h4C41}),
                .SLOT_HAS_BURST(2'b11)
            ) mgr (
                .jtag_clk(tck), .jtag_rst(arst),
                .jtag_wr_en(mgr_wr_en), .jtag_rd_en(mgr_rd_en),
                .jtag_addr(mgr_addr), .jtag_wdata(mgr_wdata), .jtag_rdata(mgr_rdata),
                .slot_wr_en(slot_wr_en), .slot_rd_en(slot_rd_en),
                .slot_addr(slot_addr), .slot_wdata(slot_wdata),
                .slot_rdata({NUM_SLOTS*32{1'b0}}),
                .burst_rd_addr(rd_addr), .burst_rd_active(rd_active),
                .slot_burst_rd_addr(slot_rd_addr), .slot_burst_rd_active(slot_rd_active),
                .slot_burst_rd_data(slot_rd_data),
                .slot_burst_rd_ts_data({NUM_SLOTS{1'b0}}),
                .slot_burst_start(slot_flag),
                .slot_burst_timestamp({NUM_SLOTS{1'b0}}),
                .slot_burst_start_ptr(slot_ptr),
                .burst_rd_data(rd_data), .burst_rd_ts_data(rd_ts_data),
                .burst_start(bstart), .burst_timestamp(bts), .burst_start_ptr(bptr)
            );
        end else begin : g_mgr
            fcapz_core_manager #(
                .NUM_SLOTS(NUM_SLOTS), .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0),
                .DEPTH(DEPTH), .SLOT_CORE_IDS({16'h4C41, 16'h4C41}),
                .SLOT_HAS_BURST(2'b11)
            ) mgr (
                .jtag_clk(tck), .jtag_rst(arst),
                .jtag_wr_en(mgr_wr_en), .jtag_rd_en(mgr_rd_en),
                .jtag_addr(mgr_addr), .jtag_wdata(mgr_wdata), .jtag_rdata(mgr_rdata),
                .slot_wr_en(slot_wr_en), .slot_rd_en(slot_rd_en),
                .slot_addr(slot_addr), .slot_wdata(slot_wdata),
                .slot_rdata({NUM_SLOTS*32{1'b0}}),
                .burst_rd_addr(rd_addr), .burst_rd_active(rd_active),
                .slot_burst_rd_addr(slot_rd_addr), .slot_burst_rd_active(slot_rd_active),
                .slot_burst_rd_data(slot_rd_data),
                .slot_burst_rd_ts_data({NUM_SLOTS{1'b0}}),
                .slot_burst_start(slot_flag),
                .slot_burst_timestamp({NUM_SLOTS{1'b0}}),
                .slot_burst_start_ptr(slot_ptr),
                .burst_rd_data(rd_data), .burst_rd_ts_data(rd_ts_data),
                .burst_start(bstart), .burst_timestamp(bts), .burst_start_ptr(bptr)
            );
        end

        if (SINGLE_CHAIN) begin : g_chain
            jtag_pipe_iface #(
                .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0), .DEPTH(DEPTH),
                .BURST_W(BURST_W), .SEG_DEPTH(DEPTH)
            ) pipe (
                .arst(arst), .tck(tck), .tdi(tdi), .tdo(tdo),
                .capture(capture), .shift_en(shift_en), .update(update), .sel(sel),
                .reg_clk(), .reg_rst(),
                .reg_wr_en(pipe_wr_en), .reg_rd_en(pipe_rd_en),
                .reg_addr(pipe_addr), .reg_wdata(pipe_wdata), .reg_rdata(mgr_rdata),
                .mem_addr(rd_addr), .mem_active(rd_active),
                .sample_data(rd_data), .timestamp_data(1'b0),
                .burst_start(bstart), .burst_timestamp(bts), .burst_ptr_in(bptr)
            );
        end else begin : g_chain
            assign pipe_wr_en = 1'b0;
            assign pipe_rd_en = 1'b0;
            assign pipe_addr = 16'h0;
            assign pipe_wdata = 32'h0;
            jtag_burst_read #(
                .SAMPLE_W(SAMPLE_W), .TIMESTAMP_W(0), .DEPTH(DEPTH),
                .BURST_W(BURST_W), .SEG_DEPTH(DEPTH)
            ) burst (
                .arst(arst), .tck(tck), .tdi(tdi), .tdo(tdo),
                .capture(capture), .shift_en(shift_en), .update(update), .sel(sel),
                .mem_addr(rd_addr), .mem_active(rd_active),
                .sample_data(rd_data), .timestamp_data(1'b0),
                .burst_start(bstart), .burst_timestamp(bts), .burst_ptr_in(bptr)
            );
        end
    endgenerate

    task tick;
        begin
            @(posedge tck);
            #1;
        end
    endtask

    task idle(input integer n);
        integer i;
        begin
            for (i = 0; i < n; i = i + 1)
                tick();
        end
    endtask

    // One DR scan: Capture-DR, nbits of Shift-DR, Update-DR, then the two
    // TCKs back to the next Capture-DR.
    task scan(input integer nbits, input [BURST_W-1:0] din, output reg [BURST_W-1:0] dout);
        integer i;
        begin
            dout = {BURST_W{1'b0}};
            sel = 1'b1;
            capture = 1'b1;
            tick();
            capture = 1'b0;
            shift_en = 1'b1;
            for (i = 0; i < nbits; i = i + 1) begin
                tdi = din[i];
                dout[i] = tdo;
                tick();
            end
            shift_en = 1'b0;
            tdi = 1'b0;
            update = 1'b1;
            tick();
            update = 1'b0;
            sel = 1'b0;
            idle(2);
        end
    endtask

    reg [BURST_W-1:0] discard;

    task reg_access(input bit write, input [15:0] addr, input [31:0] data);
        begin
            if (SINGLE_CHAIN) begin
                scan(49, {{(BURST_W-49){1'b0}}, write, addr, data}, discard);
            end else begin
                tb_addr = addr;
                tb_wdata = data;
                tb_wr_en = write;
                tb_rd_en = !write;
                tick();
                tb_wr_en = 1'b0;
                tb_rd_en = 1'b0;
                idle(52);  // as long as the USER1 scan it stands for
            end
        end
    endtask

    // Model: the slots' own toggles and the reader's last-seen copy.
    reg [NUM_SLOTS-1:0] model_flag = {NUM_SLOTS{1'b0}};
    reg model_seen = 1'b0;
    integer current_slot = 0;
    reg [BURST_W-1:0] data_scan [0:DATA_SCANS-1];

    task host_burst(input integer slot, input [PTR_W-1:0] ptr);
        integer j;
        integer k;
        reg miss;
        reg correct;
        reg right_slot;
        reg [SAMPLE_W-1:0] got;
        reg [SAMPLE_W-1:0] want;
        reg [PTR_W-1:0] addr;
        begin
            if (slot != current_slot)
                reg_access(1'b1, 16'hF008, slot);
            current_slot = slot;
            for (j = 0; j < GAP_SCANS; j = j + 1)
                reg_access(1'b0, 16'h0008, 32'h0);  // e.g. a STATUS read

            // The naive flow on the old manager misses the start when the
            // slot's toggle after the write equals the reader's copy.
            model_flag[slot] = ~model_flag[slot];
            miss = LEGACY && !SYNC && (model_flag[slot] == model_seen);

            reg_access(1'b1, 16'h002C, ptr);
            idle(WRITE_IDLE);
            if (SYNC) begin
                scan(BURST_W, {BURST_W{1'b0}}, discard);
                reg_access(1'b1, 16'h002C, ptr);
                idle(WRITE_IDLE);
                model_flag[slot] = ~model_flag[slot];
            end
            if (!miss)
                model_seen = model_flag[slot];
            else if (model_seen)
                misses_seen1 = misses_seen1 + 1;
            else
                misses_seen0 = misses_seen0 + 1;

            scan(BURST_W, {BURST_W{1'b0}}, discard);  // prime, discarded
            for (j = 0; j < DATA_SCANS; j = j + 1)
                scan(BURST_W, {BURST_W{1'b0}}, data_scan[j]);

            correct = 1'b1;
            right_slot = 1'b1;
            for (j = 0; j < DATA_SCANS; j = j + 1) begin
                for (k = 0; k < SPS; k = k + 1) begin
                    got = data_scan[j][k*SAMPLE_W +: SAMPLE_W];
                    addr = ptr + j*SPS + k;
                    want = {(slot == 0) ? 4'd1 : 4'd2, 2'b00, addr};
                    if (got !== want)
                        correct = 1'b0;
                    if (got[15:12] !== want[15:12])
                        right_slot = 1'b0;
                end
            end
            if (miss ? (correct || !right_slot) : !correct) begin
                fails = fails + 1;
                $display("FAIL: legacy=%0d single_chain=%0d gap=%0d sync=%0d: burst on slot %0d from %0d %s (first sample 0x%04h)",
                         LEGACY, SINGLE_CHAIN, GAP_SCANS, SYNC, slot, ptr,
                         miss ? "should have missed its start" : "misread",
                         data_scan[0][SAMPLE_W-1:0]);
            end
        end
    endtask

    integer b;
    // Slot/pointer script.  The predicted naive misses on the old manager
    // cover a last-seen copy of 0 and of 1.  A missed burst continues from
    // the previous burst's offset in steps of 16 samples, so consecutive
    // pointers differ mod 16 and a stale read can never match by chance.
    integer script_slot [0:9];
    integer script_ptr [0:9];

    initial begin
        done = 1'b0;
        fails = 0;
        misses_seen0 = 0;
        misses_seen1 = 0;
        script_slot[0] = 0; script_ptr[0] = 16;
        script_slot[1] = 1; script_ptr[1] = 99;
        script_slot[2] = 1; script_ptr[2] = 202;
        script_slot[3] = 0; script_ptr[3] = 325;
        script_slot[4] = 0; script_ptr[4] = 452;
        script_slot[5] = 1; script_ptr[5] = 519;
        script_slot[6] = 0; script_ptr[6] = 646;
        script_slot[7] = 1; script_ptr[7] = 711;
        script_slot[8] = 1; script_ptr[8] = 808;
        script_slot[9] = 0; script_ptr[9] = 905;
        idle(4);
        arst = 1'b0;
        idle(4);
        for (b = 0; b < 10; b = b + 1)
            host_burst(script_slot[b], script_ptr[b]);
        done = 1'b1;
    end
endmodule

module fcapz_core_manager_legacy_burst_tb;
    localparam N = 16;
    wire [N-1:0] done;
    wire [N*32-1:0] fails;
    wire [N*32-1:0] misses0;
    wire [N*32-1:0] misses1;

    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : g_case
            legacy_burst_case #(
                .LEGACY((g >> 3) & 1),
                .SINGLE_CHAIN((g >> 2) & 1),
                .GAP_SCANS(((g >> 1) & 1) * 2),
                .SYNC(g & 1)
            ) c (
                .done(done[g]),
                .fails(fails[g*32 +: 32]),
                .misses_seen0(misses0[g*32 +: 32]),
                .misses_seen1(misses1[g*32 +: 32])
            );
        end
    endgenerate

    integer i;
    integer total_fails;
    integer legacy;
    integer single_chain;
    integer gap;
    integer sync;
    integer m0;
    integer m1;
    initial begin
        wait (&done);
        total_fails = 0;
        for (i = 0; i < N; i = i + 1) begin
            legacy = (i >> 3) & 1;
            single_chain = (i >> 2) & 1;
            gap = ((i >> 1) & 1) * 2;
            sync = i & 1;
            m0 = misses0[i*32 +: 32];
            m1 = misses1[i*32 +: 32];
            total_fails = total_fails + fails[i*32 +: 32];
            $display("%s manager, %s, %0d gap scans, %s: %0d failures, naive misses %0d (seen=0) %0d (seen=1)",
                     legacy ? "old    " : "current",
                     single_chain ? "single-chain" : "two-chain   ",
                     gap, sync ? "sync " : "naive",
                     fails[i*32 +: 32], m0, m1);
            // The naive flow on the old manager must miss with both values.
            if (legacy && !sync && (m0 == 0 || m1 == 0)) begin
                total_fails = total_fails + 1;
                $display("FAIL: the script does not miss with both last-seen values");
            end
        end
        $display("\n=== fcapz_core_manager legacy burst summary: %0d failed ===", total_fails);
        if (total_fails != 0)
            $fatal(1);
        $finish;
    end
endmodule
