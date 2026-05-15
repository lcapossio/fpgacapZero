// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

module fcapz_core_manager_tb;
    localparam NUM_SLOTS = 3;
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
    wire [NUM_SLOTS*PTR_W-1:0] slot_burst_rd_addr;
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

    integer errors = 0;

    always #5 clk = ~clk;

    fcapz_core_manager #(
        .NUM_SLOTS(NUM_SLOTS),
        .SAMPLE_W(SAMPLE_W),
        .TIMESTAMP_W(TIMESTAMP_W),
        .DEPTH(DEPTH),
        .SLOT_CORE_IDS({16'h494F, 16'h4C41, 16'h4C41}),
        .SLOT_HAS_BURST(3'b011)
    ) dut (
        .jtag_clk(clk),
        .jtag_rst(rst),
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
        .burst_rd_addr(burst_rd_addr),
        .slot_burst_rd_addr(slot_burst_rd_addr),
        .slot_burst_rd_data(slot_burst_rd_data),
        .slot_burst_rd_ts_data(slot_burst_rd_ts_data),
        .slot_burst_start(slot_burst_start),
        .slot_burst_timestamp(slot_burst_timestamp),
        .slot_burst_start_ptr(slot_burst_start_ptr),
        .burst_rd_data(burst_rd_data),
        .burst_rd_ts_data(burst_rd_ts_data),
        .burst_start(burst_start),
        .burst_timestamp(burst_timestamp),
        .burst_start_ptr(burst_start_ptr)
    );

    task expect32(input [31:0] got, input [31:0] exp, input [255:0] msg);
        begin
            if (got !== exp) begin
                $display("[FAIL] %0s got=0x%08x exp=0x%08x", msg, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task expect_bits(input [7:0] got, input [7:0] exp, input [255:0] msg);
        begin
            if (got !== exp) begin
                $display("[FAIL] %0s got=0x%02x exp=0x%02x", msg, got, exp);
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

    initial begin
        slot_rdata = {32'h2222_0000, 32'h1111_0000, 32'h0000_0000};
        slot_burst_rd_data = {8'hC2, 8'hB1, 8'hA0};
        slot_burst_rd_ts_data = {4'h2, 4'h1, 4'h0};
        slot_burst_start = 3'b111;
        slot_burst_timestamp = 3'b101;
        slot_burst_start_ptr = {4'hC, 4'hB, 4'hA};

        repeat (3) @(negedge clk);
        rst = 1'b0;
        repeat (1) @(negedge clk);

        read_reg(16'hF000, 32'h0004_434D, "manager version");
        read_reg(16'hF004, 32'h0000_0003, "manager slot count");
        read_reg(16'hF008, 32'h0000_0000, "reset active slot");

        read_reg(16'hEFFF, 32'h0000_0000, "0xEFFF routes to active slot 0");
        expect_bits({7'b0, slot_rd_en[0]}, 8'h01, "0xEFFF asserted slot0 read");
        read_reg(16'hF000, 32'h0004_434D, "0xF000 stays in manager window");
        expect_bits({7'b0, |slot_rd_en}, 8'h00, "0xF000 did not touch slots");

        write_reg(16'hF014, 32'h0000_0002);
        read_reg(16'hF018, 32'h0000_494F, "descriptor core id for EIO slot");
        read_reg(16'hF01C, 32'h0000_0000, "descriptor caps for no-burst slot");

        write_reg(16'hF008, 32'h0000_0001);
        read_reg(16'hF008, 32'h0000_0001, "active slot switches to 1");
        read_reg(16'h0020, 32'h1111_0000, "first transaction after switch reads slot1");
        expect_bits({7'b0, slot_rd_en[1]}, 8'h01, "slot1 read asserted after switch");

        write_reg(16'hF008, 32'h0000_0002);
        read_reg(16'h0020, 32'h2222_0000, "slot2 register read");
        expect32({24'h0, burst_rd_data}, 32'h0000_0000, "no-burst slot masks burst data");
        expect32({28'h0, burst_rd_ts_data}, 32'h0000_0000, "no-burst slot masks timestamp data");
        expect_bits({7'b0, burst_start}, 8'h00, "no-burst slot masks burst_start");
        expect_bits({7'b0, burst_timestamp}, 8'h00, "no-burst slot masks burst_timestamp");
        expect_bits({4'h0, burst_start_ptr}, 8'h00, "no-burst slot masks start_ptr");

        write_reg(16'hF008, 32'h0000_0001);
        #1;
        expect32({24'h0, burst_rd_data}, 32'h0000_00B1, "burst data follows slot1");
        expect32({28'h0, burst_rd_ts_data}, 32'h0000_0001, "burst ts follows slot1");
        expect_bits({7'b0, burst_start}, 8'h01, "burst_start follows slot1");
        expect_bits({7'b0, burst_timestamp}, 8'h00, "burst_timestamp follows slot1");
        expect_bits({4'h0, burst_start_ptr}, 8'h0B, "burst_start_ptr follows slot1");

        write_reg(16'hF008, 32'h0000_0004);
        read_reg(16'hF008, 32'h0000_0001, "out-of-range active write 4 ignored");
        write_reg(16'hF008, 32'h0000_0003);
        read_reg(16'hF008, 32'h0000_0001, "out-of-range active write NUM_SLOTS ignored");
        write_reg(16'hF008, 32'hFFFF_FFFF);
        read_reg(16'hF008, 32'h0000_0001, "out-of-range active write all ones ignored");
        write_reg(16'hF014, 32'h0000_0004);
        read_reg(16'hF014, 32'h0000_0002, "out-of-range descriptor write 4 ignored");
        write_reg(16'hF014, 32'h0000_0003);
        read_reg(16'hF014, 32'h0000_0002, "out-of-range descriptor write NUM_SLOTS ignored");

        if (errors == 0) begin
            $display("fcapz_core_manager_tb PASS");
            $finish;
        end
        $display("fcapz_core_manager_tb FAIL errors=%0d", errors);
        $fatal(1);
    end
endmodule
