// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps
`include "fcapz_version.vh"

// Active-slot manager for multiple ELA cores behind one JTAG USER chain.
//
// Normal ELA registers stay at their legacy addresses.  The manager occupies
// 0xF000..0xF0FF and selects which ELA instance receives non-manager register
// accesses and supplies burst readback data.  Reset selects slot 0, so old
// hosts still see the first ELA at VERSION=0x0000.

module fcapz_ela_manager #(
    parameter NUM_ELAS = 2,
    parameter SAMPLE_W = 8,
    parameter TIMESTAMP_W = 0,
    parameter DEPTH = 1024
) (
    input  wire                       jtag_clk,
    input  wire                       jtag_rst,

    // Upstream register bus from jtag_reg_iface / jtag_pipe_iface.
    input  wire                       jtag_wr_en,
    input  wire                       jtag_rd_en,
    input  wire [15:0]                jtag_addr,
    input  wire [31:0]                jtag_wdata,
    output wire [31:0]                jtag_rdata,

    // Downstream ELA register buses, flattened by slot.
    output wire [NUM_ELAS-1:0]        ela_wr_en,
    output wire [NUM_ELAS-1:0]        ela_rd_en,
    output wire [NUM_ELAS*16-1:0]     ela_addr,
    output wire [NUM_ELAS*32-1:0]     ela_wdata,
    input  wire [NUM_ELAS*32-1:0]     ela_rdata,

    // Burst read address from the shared pipe, broadcast to all ELAs.
    input  wire [$clog2(DEPTH)-1:0]   burst_rd_addr,
    output wire [NUM_ELAS*$clog2(DEPTH)-1:0] ela_burst_rd_addr,

    // Burst data/control from ELAs to the shared pipe.
    input  wire [NUM_ELAS*SAMPLE_W-1:0] ela_burst_rd_data,
    input  wire [NUM_ELAS*((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] ela_burst_rd_ts_data,
    input  wire [NUM_ELAS-1:0]        ela_burst_start,
    input  wire [NUM_ELAS-1:0]        ela_burst_timestamp,
    input  wire [NUM_ELAS*$clog2(DEPTH)-1:0] ela_burst_start_ptr,
    output wire [SAMPLE_W-1:0]        burst_rd_data,
    output wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data,
    output wire                       burst_start,
    output wire                       burst_timestamp,
    output wire [$clog2(DEPTH)-1:0]   burst_start_ptr
);

    localparam IDX_W = (NUM_ELAS <= 2) ? 1 : $clog2(NUM_ELAS);
    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam [15:0] MANAGER_CORE_ID = 16'h4C4D; // ASCII "LM" = LA manager
    localparam [31:0] MANAGER_VERSION =
        {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, MANAGER_CORE_ID};

    localparam ADDR_MGR_VERSION = 16'hF000;
    localparam ADDR_MGR_COUNT   = 16'hF004;
    localparam ADDR_MGR_ACTIVE  = 16'hF008;
    localparam ADDR_MGR_STRIDE  = 16'hF00C;
    localparam ADDR_MGR_CAPS    = 16'hF010;

    reg [IDX_W-1:0] active_idx;

    wire manager_hit = (jtag_addr[15:8] == 8'hF0);
    wire [NUM_ELAS-1:0] active_onehot = {{(NUM_ELAS-1){1'b0}}, 1'b1} << active_idx;

    integer i;
    always @(posedge jtag_clk or posedge jtag_rst) begin
        if (jtag_rst) begin
            active_idx <= {IDX_W{1'b0}};
        end else if (jtag_wr_en && jtag_addr == ADDR_MGR_ACTIVE) begin
            if (jtag_wdata[IDX_W-1:0] < NUM_ELAS[IDX_W-1:0])
                active_idx <= jtag_wdata[IDX_W-1:0];
        end
    end

    genvar g;
    generate
        for (g = 0; g < NUM_ELAS; g = g + 1) begin : g_slots
            assign ela_wr_en[g] = jtag_wr_en & ~manager_hit & active_onehot[g];
            assign ela_rd_en[g] = jtag_rd_en & ~manager_hit & active_onehot[g];
            assign ela_addr[g*16 +: 16] = jtag_addr;
            assign ela_wdata[g*32 +: 32] = jtag_wdata;
            assign ela_burst_rd_addr[g*PTR_W +: PTR_W] = burst_rd_addr;
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
        for (i = 0; i < NUM_ELAS; i = i + 1) begin
            if (active_idx == i[IDX_W-1:0]) begin
                active_rdata = ela_rdata[i*32 +: 32];
                active_burst_data = ela_burst_rd_data[i*SAMPLE_W +: SAMPLE_W];
                active_burst_ts_data = ela_burst_rd_ts_data[i*TS_W_SAFE +: TS_W_SAFE];
                active_burst_start = ela_burst_start[i];
                active_burst_timestamp = ela_burst_timestamp[i];
                active_burst_start_ptr = ela_burst_start_ptr[i*PTR_W +: PTR_W];
            end
        end
    end

    reg [31:0] manager_rdata;
    always @(*) begin
        case (jtag_addr)
            ADDR_MGR_VERSION: manager_rdata = MANAGER_VERSION;
            ADDR_MGR_COUNT:   manager_rdata = NUM_ELAS;
            ADDR_MGR_ACTIVE:  manager_rdata = {{(32-IDX_W){1'b0}}, active_idx};
            ADDR_MGR_STRIDE:  manager_rdata = 32'h0; // active-slot model, no windows
            ADDR_MGR_CAPS:    manager_rdata = 32'h0000_0001; // bit0: active-slot select
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
