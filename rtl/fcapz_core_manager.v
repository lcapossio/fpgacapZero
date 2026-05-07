// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps
`include "fcapz_version.vh"

// Active-slot manager for mixed debug cores behind one JTAG USER chain.
//
// The manager owns 0xF000..0xF0FF.  All other addresses are routed to the
// active slot, which exposes its native register map at 0x0000.  Slots without
// burst support (for example EIO) simply return idle/zero burst controls.

module fcapz_core_manager #(
    parameter NUM_SLOTS = 2,
    parameter SAMPLE_W = 8,
    parameter TIMESTAMP_W = 0,
    parameter DEPTH = 1024,
    parameter [NUM_SLOTS*16-1:0] SLOT_CORE_IDS = {NUM_SLOTS{16'h0000}},
    parameter [NUM_SLOTS-1:0] SLOT_HAS_BURST = {NUM_SLOTS{1'b0}}
) (
    input  wire                       jtag_clk,
    input  wire                       jtag_rst,

    input  wire                       jtag_wr_en,
    input  wire                       jtag_rd_en,
    input  wire [15:0]                jtag_addr,
    input  wire [31:0]                jtag_wdata,
    output wire [31:0]                jtag_rdata,

    output wire [NUM_SLOTS-1:0]       slot_wr_en,
    output wire [NUM_SLOTS-1:0]       slot_rd_en,
    output wire [NUM_SLOTS*16-1:0]    slot_addr,
    output wire [NUM_SLOTS*32-1:0]    slot_wdata,
    input  wire [NUM_SLOTS*32-1:0]    slot_rdata,

    input  wire [$clog2(DEPTH)-1:0]   burst_rd_addr,
    output wire [NUM_SLOTS*$clog2(DEPTH)-1:0] slot_burst_rd_addr,
    input  wire [NUM_SLOTS*SAMPLE_W-1:0] slot_burst_rd_data,
    input  wire [NUM_SLOTS*((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] slot_burst_rd_ts_data,
    input  wire [NUM_SLOTS-1:0]       slot_burst_start,
    input  wire [NUM_SLOTS-1:0]       slot_burst_timestamp,
    input  wire [NUM_SLOTS*$clog2(DEPTH)-1:0] slot_burst_start_ptr,
    output wire [SAMPLE_W-1:0]        burst_rd_data,
    output wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data,
    output wire                       burst_start,
    output wire                       burst_timestamp,
    output wire [$clog2(DEPTH)-1:0]   burst_start_ptr
);

    localparam IDX_W = (NUM_SLOTS <= 2) ? 1 : $clog2(NUM_SLOTS);
    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam [15:0] MANAGER_CORE_ID = 16'h434D; // ASCII "CM"
    localparam [31:0] MANAGER_VERSION =
        {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, MANAGER_CORE_ID};

    localparam ADDR_MGR_VERSION = 16'hF000;
    localparam ADDR_MGR_COUNT   = 16'hF004;
    localparam ADDR_MGR_ACTIVE  = 16'hF008;
    localparam ADDR_MGR_STRIDE  = 16'hF00C;
    localparam ADDR_MGR_CAPS    = 16'hF010;
    localparam ADDR_MGR_DESC_INDEX = 16'hF014;
    localparam ADDR_MGR_DESC_CORE  = 16'hF018;
    localparam ADDR_MGR_DESC_CAPS  = 16'hF01C;

    reg [IDX_W-1:0] active_idx;
    reg [IDX_W-1:0] desc_idx;

    wire manager_hit = (jtag_addr[15:8] == 8'hF0);
    wire [NUM_SLOTS-1:0] active_onehot = {{(NUM_SLOTS-1){1'b0}}, 1'b1} << active_idx;

    integer i;
    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            active_idx <= {IDX_W{1'b0}};
            desc_idx <= {IDX_W{1'b0}};
        end else if (jtag_wr_en) begin
            if (jtag_addr == ADDR_MGR_ACTIVE) begin
                if (jtag_wdata[IDX_W-1:0] < NUM_SLOTS[IDX_W-1:0])
                    active_idx <= jtag_wdata[IDX_W-1:0];
            end else if (jtag_addr == ADDR_MGR_DESC_INDEX) begin
                if (jtag_wdata[IDX_W-1:0] < NUM_SLOTS[IDX_W-1:0])
                    desc_idx <= jtag_wdata[IDX_W-1:0];
            end
        end
    end

    genvar g;
    generate
        for (g = 0; g < NUM_SLOTS; g = g + 1) begin : g_slots
            assign slot_wr_en[g] = jtag_wr_en & ~manager_hit & active_onehot[g];
            assign slot_rd_en[g] = jtag_rd_en & ~manager_hit & active_onehot[g];
            assign slot_addr[g*16 +: 16] = jtag_addr;
            assign slot_wdata[g*32 +: 32] = jtag_wdata;
            assign slot_burst_rd_addr[g*PTR_W +: PTR_W] = burst_rd_addr;
        end
    endgenerate

    reg [31:0] active_rdata;
    reg [SAMPLE_W-1:0] active_burst_data;
    reg [TS_W_SAFE-1:0] active_burst_ts_data;
    reg active_burst_start;
    reg active_burst_timestamp;
    reg [PTR_W-1:0] active_burst_start_ptr;

    always @(*) begin
        active_rdata = 32'h0;
        active_burst_data = {SAMPLE_W{1'b0}};
        active_burst_ts_data = {TS_W_SAFE{1'b0}};
        active_burst_start = 1'b0;
        active_burst_timestamp = 1'b0;
        active_burst_start_ptr = {PTR_W{1'b0}};
        for (i = 0; i < NUM_SLOTS; i = i + 1) begin
            if (active_idx == i[IDX_W-1:0]) begin
                active_rdata = slot_rdata[i*32 +: 32];
                if (SLOT_HAS_BURST[i]) begin
                    active_burst_data = slot_burst_rd_data[i*SAMPLE_W +: SAMPLE_W];
                    active_burst_ts_data = slot_burst_rd_ts_data[i*TS_W_SAFE +: TS_W_SAFE];
                    active_burst_start = slot_burst_start[i];
                    active_burst_timestamp = slot_burst_timestamp[i];
                    active_burst_start_ptr = slot_burst_start_ptr[i*PTR_W +: PTR_W];
                end
            end
        end
    end

    reg [15:0] desc_core_id;
    reg desc_has_burst;
    always @(*) begin
        desc_core_id = 16'h0000;
        desc_has_burst = 1'b0;
        for (i = 0; i < NUM_SLOTS; i = i + 1) begin
            if (desc_idx == i[IDX_W-1:0]) begin
                desc_core_id = SLOT_CORE_IDS[i*16 +: 16];
                desc_has_burst = SLOT_HAS_BURST[i];
            end
        end
    end

    reg [31:0] manager_rdata;
    always @(*) begin
        case (jtag_addr)
            ADDR_MGR_VERSION: manager_rdata = MANAGER_VERSION;
            ADDR_MGR_COUNT:   manager_rdata = NUM_SLOTS;
            ADDR_MGR_ACTIVE:  manager_rdata = {{(32-IDX_W){1'b0}}, active_idx};
            ADDR_MGR_STRIDE:  manager_rdata = 32'h0;
            ADDR_MGR_CAPS:    manager_rdata = 32'h0000_0003; // bit0 active-slot, bit1 descriptors
            ADDR_MGR_DESC_INDEX: manager_rdata = {{(32-IDX_W){1'b0}}, desc_idx};
            ADDR_MGR_DESC_CORE:  manager_rdata = {16'h0, desc_core_id};
            ADDR_MGR_DESC_CAPS:  manager_rdata = {31'h0, desc_has_burst};
            default:          manager_rdata = 32'h0;
        endcase
    end

    assign jtag_rdata = manager_hit ? manager_rdata : active_rdata;
    assign burst_rd_data = active_burst_data;
    assign burst_rd_ts_data = active_burst_ts_data;
    assign burst_start = active_burst_start;
    assign burst_timestamp = active_burst_timestamp;
    assign burst_start_ptr = active_burst_start_ptr;

endmodule
