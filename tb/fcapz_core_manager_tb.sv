// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module fcapz_core_manager_case #(
    parameter integer NUM_SLOTS = 3,
    parameter [NUM_SLOTS*16-1:0] SLOT_CORE_IDS = {NUM_SLOTS{16'h4C41}},
    parameter [NUM_SLOTS-1:0] SLOT_HAS_BURST = {NUM_SLOTS{1'b1}},
    parameter integer CASE_ID = 0
) (
    output reg done
);
    localparam SAMPLE_W = 8;
    localparam TIMESTAMP_W = 4;
    localparam DEPTH = 16;
    localparam PTR_W = 4;
    localparam TS_W = TIMESTAMP_W;

    reg clk = 1'b0;
    reg rst = 1'b1;
    reg wr_en = 1'b0;
    reg rd_en = 1'b0;
    reg [15:0] addr = 16'h0000;
    reg [31:0] wdata = 32'h0000_0000;
    wire [31:0] rdata;

    wire [NUM_SLOTS-1:0] slot_wr_en;
    wire [NUM_SLOTS-1:0] slot_rd_en;
    wire [NUM_SLOTS*16-1:0] slot_addr;
    wire [NUM_SLOTS*32-1:0] slot_wdata;
    reg  [NUM_SLOTS*32-1:0] slot_rdata;

    reg [PTR_W-1:0] burst_rd_addr = 4'h0;
    reg burst_rd_active = 1'b0;
    wire [NUM_SLOTS*PTR_W-1:0] slot_burst_rd_addr;
    wire [NUM_SLOTS-1:0] slot_burst_rd_active;
    reg [NUM_SLOTS*SAMPLE_W-1:0] slot_burst_rd_data;
    reg [NUM_SLOTS*TS_W-1:0] slot_burst_rd_ts_data;
    reg [NUM_SLOTS-1:0] slot_burst_start;
    reg [NUM_SLOTS-1:0] slot_burst_timestamp;
    reg [NUM_SLOTS*PTR_W-1:0] slot_burst_start_ptr;
    wire [SAMPLE_W-1:0] burst_rd_data;
    wire [TS_W-1:0] burst_rd_ts_data;
    wire burst_start;
    wire burst_timestamp;
    wire [PTR_W-1:0] burst_start_ptr;
    wire [159:0] burst_header;
    reg proto_rst = 1'b1;
    reg tlr = 1'b0;
    reg [NUM_SLOTS-1:0] slot_rst = {NUM_SLOTS{1'b0}};
    wire [NUM_SLOTS-1:0] slot_rst_req;

    // Every reset request the manager raises, per slot, and its width.
    integer req_pulses [0:NUM_SLOTS-1];
    integer req_wide = 0;
    reg [NUM_SLOTS-1:0] slot_rst_req_d = {NUM_SLOTS{1'b0}};
    integer k;
    initial for (k = 0; k < NUM_SLOTS; k = k + 1) req_pulses[k] = 0;
    always @(posedge clk) begin
        slot_rst_req_d <= slot_rst_req;
        for (k = 0; k < NUM_SLOTS; k = k + 1) begin
            if (slot_rst_req[k] && !slot_rst_req_d[k])
                req_pulses[k] = req_pulses[k] + 1;
            if (slot_rst_req[k] && slot_rst_req_d[k])
                req_wide = req_wide + 1;
        end
    end

    integer errors = 0;
    integer i;
    reg [31:0] expected_rdata;
    reg [SAMPLE_W-1:0] expected_burst_data;
    reg [TS_W-1:0] expected_ts_data;
    reg [PTR_W-1:0] expected_start_ptr;
    reg expected_has_burst;

    always #5 clk = ~clk;

    fcapz_core_manager #(
        .NUM_SLOTS(NUM_SLOTS),
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .SLOT_CORE_IDS(SLOT_CORE_IDS),
        .SLOT_HAS_BURST(SLOT_HAS_BURST),
        .HEADER_EN(1)
    ) dut (
        .jtag_clk(clk),
        .jtag_rst(rst),
        .proto_rst(proto_rst),
        .tlr(tlr),
        .jtag_wr_en(wr_en),
        .jtag_rd_en(rd_en),
        .jtag_addr(addr),
        .jtag_wdata(wdata),
        .jtag_rdata(rdata),
        .slot_wr_en(slot_wr_en),
        .slot_rd_en(slot_rd_en),
        .slot_addr(slot_addr),
        .slot_wdata(slot_wdata),
        .slot_rdata(slot_rdata),
        .slot_rst(slot_rst),
        .slot_rst_req(slot_rst_req),
        .burst_rd_addr(burst_rd_addr),
        .burst_rd_active(burst_rd_active),
        .slot_burst_rd_addr(slot_burst_rd_addr),
        .slot_burst_rd_active(slot_burst_rd_active),
        .slot_burst_rd_data(slot_burst_rd_data),
        .slot_burst_rd_ts_data(slot_burst_rd_ts_data),
        .slot_burst_start(slot_burst_start),
        .slot_burst_timestamp(slot_burst_timestamp),
        .slot_burst_start_ptr(slot_burst_start_ptr),
        .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr),
        .burst_header(burst_header)
    );

    task expect32(input [31:0] got, input [31:0] exp, input [255:0] msg);
        begin
            if (got !== exp) begin
                $display("[FAIL:slots%0d] %0s got=0x%08x exp=0x%08x", CASE_ID, msg, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task expect_bits(input [7:0] got, input [7:0] exp, input [255:0] msg);
        begin
            if (got !== exp) begin
                $display("[FAIL:slots%0d] %0s got=0x%02x exp=0x%02x", CASE_ID, msg, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task write_reg(input [15:0] a, input [31:0] d);
        begin
            @(negedge clk);
            addr = a;
            wdata = d;
            wr_en = 1'b1;
            rd_en = 1'b0;
            @(negedge clk);
            wr_en = 1'b0;
        end
    endtask

    task read_reg(input [15:0] a, input [31:0] exp, input [255:0] msg);
        begin
            @(negedge clk);
            addr = a;
            rd_en = 1'b1;
            wr_en = 1'b0;
            #1 expect32(rdata, exp, msg);
            @(negedge clk);
            rd_en = 1'b0;
        end
    endtask

    task check_active_slot(input integer idx, input [255:0] msg);
        begin
            expected_rdata = 32'h1111_0000 + idx;
            expected_has_burst = SLOT_HAS_BURST[idx];
            expected_burst_data = expected_has_burst ? (8'hA0 + idx[7:0]) : 8'h00;
            expected_ts_data = expected_has_burst ? idx[TS_W-1:0] : {TS_W{1'b0}};
            expected_start_ptr = expected_has_burst ? (4'h8 + idx[PTR_W-1:0]) : {PTR_W{1'b0}};
            read_reg(16'h0020, expected_rdata, msg);
            expect_bits({{(8-NUM_SLOTS){1'b0}}, slot_rd_en}, (8'h01 << idx), "selected slot read asserted");
            expect32({24'h0, burst_rd_data}, {24'h0, expected_burst_data}, "burst data follows active burst-capable slot");
            expect32({28'h0, burst_rd_ts_data}, {28'h0, expected_ts_data}, "burst timestamp follows active burst-capable slot");
            expect_bits({7'b0, burst_timestamp}, {7'b0, expected_has_burst & idx[0]}, "burst_timestamp follows active burst-capable slot");
            expect_bits({4'h0, burst_start_ptr}, {4'h0, expected_start_ptr}, "burst_start_ptr follows active burst-capable slot");
        end
    endtask

    // The manager raises the burst start event itself, once per BURST_PTR
    // write to a burst-capable slot; selecting a slot is not a start.
    reg start_before;
    task check_burst_ptr_write(input integer idx);
        begin
            start_before = burst_start;
            write_reg(16'h002C, 32'h0);
            #1 expect_bits({7'b0, burst_start}, {7'b0, start_before ^ SLOT_HAS_BURST[idx]},
                           "BURST_PTR write toggles burst_start on a burst slot only");
            start_before = burst_start;
            write_reg(16'h0020, 32'h0);
            #1 expect_bits({7'b0, burst_start}, {7'b0, start_before}, "other writes are not starts");
        end
    endtask

    initial begin
        done = 1'b0;
        slot_rdata = {NUM_SLOTS{32'h0}};
        slot_burst_rd_data = {NUM_SLOTS{8'h0}};
        slot_burst_rd_ts_data = {NUM_SLOTS{4'h0}};
        slot_burst_start = {NUM_SLOTS{1'b0}};
        slot_burst_timestamp = {NUM_SLOTS{1'b0}};
        slot_burst_start_ptr = {NUM_SLOTS{4'h0}};
        for (i = 0; i < NUM_SLOTS; i = i + 1) begin
            slot_rdata[i*32 +: 32] = 32'h1111_0000 + i;
            slot_burst_rd_data[i*SAMPLE_W +: SAMPLE_W] = 8'hA0 + i[7:0];
            slot_burst_rd_ts_data[i*TS_W +: TS_W] = i[TS_W-1:0];
            slot_burst_start[i] = 1'b1;
            slot_burst_timestamp[i] = i[0];
            slot_burst_start_ptr[i*PTR_W +: PTR_W] = 4'h8 + i[PTR_W-1:0];
        end

        repeat (3) @(negedge clk);
        rst = 1'b0;
        proto_rst = 1'b0;
        repeat (1) @(negedge clk);

        read_reg(16'hF000, 32'h0004_434D, "manager version");
        read_reg(16'hF004, NUM_SLOTS[31:0], "manager slot count");
        // bit2 burst start per BURST_PTR write, bit3 epochs/owner, bit4
        // header (HEADER_EN), bit5 MGR_CTRL; no TLR protocol reset
        read_reg(16'hF010, 32'h0000_003F, "manager caps");
        read_reg(16'hF020, 32'h0000_0002, "power-up reset counted at both edges");
        read_reg(16'hF024, 32'h0000_0000, "owner clear after reset");
        read_reg(16'hF008, 32'h0000_0000, "reset active slot");
        check_active_slot(0, "0xEFFF routes to active slot 0");
        read_reg(16'hF000, 32'h0004_434D, "0xF000 stays in manager window");
        expect_bits({7'b0, |slot_rd_en}, 8'h00, "0xF000 did not touch slots");

        write_reg(16'hF014, NUM_SLOTS - 1);
        read_reg(16'hF018, {16'h0, SLOT_CORE_IDS[(NUM_SLOTS-1)*16 +: 16]}, "descriptor core id for last slot");
        read_reg(16'hF01C, {31'h0, SLOT_HAS_BURST[NUM_SLOTS-1]}, "descriptor caps for last slot");

        start_before = burst_start;
        write_reg(16'hF008, NUM_SLOTS - 1);
        #1 expect_bits({7'b0, burst_start}, {7'b0, start_before}, "selecting a slot is not a start");
        read_reg(16'hF008, NUM_SLOTS - 1, "active slot switches to last slot");
        check_active_slot(NUM_SLOTS - 1, "last slot register read");
        check_burst_ptr_write(NUM_SLOTS - 1);
        write_reg(16'hF008, 0);
        check_burst_ptr_write(0);
        write_reg(16'hF008, NUM_SLOTS - 1);

        write_reg(16'hF008, NUM_SLOTS);
        read_reg(16'hF008, NUM_SLOTS - 1, "out-of-range active write NUM_SLOTS ignored");
        write_reg(16'hF008, NUM_SLOTS + 1);
        read_reg(16'hF008, NUM_SLOTS - 1, "out-of-range active write NUM_SLOTS+1 ignored");
        write_reg(16'hF008, 32'hFFFF_FFFF);
        read_reg(16'hF008, NUM_SLOTS - 1, "out-of-range active write all ones ignored");
        write_reg(16'hF014, NUM_SLOTS);
        read_reg(16'hF014, NUM_SLOTS - 1, "out-of-range descriptor write NUM_SLOTS ignored");
        write_reg(16'hF014, NUM_SLOTS + 1);
        read_reg(16'hF014, NUM_SLOTS - 1, "out-of-range descriptor write NUM_SLOTS+1 ignored");

        // The BURST_PTR write binds the burst owner: an ACTIVE switch before
        // the burst starts must not move it, and an ACTIVE write while the
        // bound burst loads is taken.
        if (NUM_SLOTS >= 2 && SLOT_HAS_BURST[0]) begin
            write_reg(16'hF008, 0);
            write_reg(16'h002C, 0);
            write_reg(16'hF008, 1);
            read_reg(16'hF008, 1, "ACTIVE switch after BURST_PTR");
            @(negedge clk);
            burst_rd_active = 1'b1;
            @(negedge clk);
            expect_bits({{(8-NUM_SLOTS){1'b0}}, slot_burst_rd_active}, 8'h01,
                        "burst stays on the BURST_PTR owner after an ACTIVE switch");
            write_reg(16'hF008, 0);
            read_reg(16'hF008, 0, "ACTIVE write lands while the bound burst loads");
            @(negedge clk);
            burst_rd_active = 1'b0;
        end

        // ---- epochs, owner, MGR_CTRL, Test-Logic-Reset count, header ----
        write_reg(16'hF008, 0);
        write_reg(16'hF014, NUM_SLOTS - 1);
        write_reg(16'hF024, 32'hCAFE_0001);
        read_reg(16'hF024, 32'hCAFE_0001, "owner reads back");
        start_before = burst_start;
        write_reg(16'hF028, 32'h1);  // hub soft reset
        repeat (2) @(negedge clk);  // the request, then its count
        // Power-up reset: assert and release (2); soft reset: 2 more.
        read_reg(16'hF020, 32'h0000_0004, "soft reset counted in MGR_EPOCH");
        read_reg(16'hF024, 32'h0000_0000, "soft reset clears the owner");
        read_reg(16'hF014, 32'h0000_0000, "soft reset clears DESC_INDEX");
        #1 expect_bits({7'b0, burst_start}, {7'b0, start_before},
                       "soft reset keeps the burst start paired with the pipe");
        for (k = 0; k < NUM_SLOTS; k = k + 1)
            expect32(req_pulses[k], 0, "hub soft reset requests no slot reset");

        write_reg(16'hF014, NUM_SLOTS - 1);
        write_reg(16'hF028, 32'h2);  // reset the DESC_INDEX slot
        repeat (2) @(negedge clk);  // the request, then its count
        for (k = 0; k < NUM_SLOTS; k = k + 1)
            expect32(req_pulses[k], (k == NUM_SLOTS - 1) ? 1 : 0,
                     "bit 1 requests a reset of the DESC_INDEX slot only");
        write_reg(16'hF028, 32'h4);  // reset every slot
        repeat (2) @(negedge clk);  // the request, then its count
        for (k = 0; k < NUM_SLOTS; k = k + 1)
            expect32(req_pulses[k], (k == NUM_SLOTS - 1) ? 2 : 1,
                     "bit 2 requests a reset of every slot");
        expect32(req_wide, 0, "reset requests last one cycle");
        write_reg(16'h0028, 32'h7);  // a slot register, not MGR_CTRL
        repeat (2) @(negedge clk);  // the request, then its count
        expect32(req_pulses[0], (NUM_SLOTS == 1) ? 2 : 1, "slot address 0x0028 is not MGR_CTRL");
        read_reg(16'hF028, 32'h0000_0000, "MGR_CTRL reads 0");

        // A slot's own reset is counted for that slot only, at both edges:
        // odd while it is held.
        @(negedge clk) slot_rst[NUM_SLOTS - 1] = 1'b1;
        repeat (2) @(negedge clk);
        read_reg(16'hF02C, 32'h0000_0001, "slot reset assertion counted: odd while held");
        slot_rst[NUM_SLOTS - 1] = 1'b0;
        read_reg(16'hF02C, 32'h0000_0002, "slot reset release counted for that slot");
        write_reg(16'hF014, 0);
        if (NUM_SLOTS > 1)
            read_reg(16'hF02C, 32'h0000_0000, "other slots' epochs unchanged");

        // Test-Logic-Reset is counted once per entry, however long.
        @(negedge clk) tlr = 1'b1;
        repeat (4) @(negedge clk);
        tlr = 1'b0;
        read_reg(16'hF030, 32'h0000_0001, "Test-Logic-Reset counted per entry");

        // The header describes the burst the BURST_PTR write just started.
        write_reg(16'hF008, 0);
        write_reg(16'hF024, 32'h1234_5678);
        @(negedge clk) slot_rst[0] = 1'b1;
        @(negedge clk) slot_rst[0] = 1'b0;
        write_reg(16'h002C, 32'h0);
        if (SLOT_HAS_BURST[0]) begin
            expect32(burst_header[31:0], 32'h0000_4248, "header magic and owner slot");
            expect32(burst_header[63:32], 32'h8, "header start pointer");
            expect32(burst_header[95:64], 32'h0004_0000, "header epoch, timestamp select");
            expect32(burst_header[127:96], 32'h5678_0002 + ((NUM_SLOTS == 1) ? 2 : 0),
                     "header owner slot epoch, owner low half");
            expect32(burst_header[159:128], 32'h0008_1234, "header SAMPLE_W, owner high half");
        end

        // The protocol reset clears only the burst start event and owner.
        start_before = burst_start;
        @(negedge clk) proto_rst = 1'b1;
        @(negedge clk) proto_rst = 1'b0;
        #1 expect_bits({7'b0, burst_start}, 8'h00, "protocol reset clears the burst start");
        read_reg(16'hF024, 32'h1234_5678, "protocol reset keeps the owner");
        read_reg(16'hF020, 32'h0000_0004, "protocol reset is not a hub reset");

        if (errors == 0) begin
            $display("fcapz_core_manager_tb slots%0d PASS", CASE_ID);
            done = 1'b1;
        end
        if (errors != 0) begin
            $display("fcapz_core_manager_tb slots%0d FAIL errors=%0d", CASE_ID, errors);
            $fatal(1);
        end
    end
endmodule

module fcapz_core_manager_tb;
    wire done1;
    wire done3;
    wire done4;

    fcapz_core_manager_case #(
        .NUM_SLOTS(1),
        .SLOT_CORE_IDS(16'h4C41),
        .SLOT_HAS_BURST(1'b1),
        .CASE_ID(1)
    ) slots1(.done(done1));

    fcapz_core_manager_case #(
        .NUM_SLOTS(3),
        .SLOT_CORE_IDS({16'h494F, 16'h4C41, 16'h4C41}),
        .SLOT_HAS_BURST(3'b011),
        .CASE_ID(3)
    ) slots3(.done(done3));

    fcapz_core_manager_case #(
        .NUM_SLOTS(4),
        .SLOT_CORE_IDS({16'h494F, 16'h4C41, 16'h4C41, 16'h4C41}),
        .SLOT_HAS_BURST(4'b1011),
        .CASE_ID(4)
    ) slots4(.done(done4));

    initial begin
        wait (done1 && done3 && done4);
        $display("fcapz_core_manager_tb PASS");
        $finish;
    end
endmodule
