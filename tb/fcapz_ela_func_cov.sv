// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Bound functional coverage for Verilator ELA coverage runs. This file is not
// part of the Icarus simulation runner; sim/run_verilator_ela_coverage.py adds
// it when collecting --coverage-user data.

module fcapz_ela_func_cov #(
    parameter SAMPLE_W = 32,
    parameter DEPTH = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL = 0,
    parameter NUM_CHANNELS = 1,
    parameter INPUT_PIPE = 0,
    parameter DECIM_EN = 0,
    parameter EXT_TRIG_EN = 0,
    parameter TIMESTAMP_W = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W = 0,
    parameter STARTUP_ARM = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1
) (
    input wire sample_clk,
    input wire sample_rst,
    input wire trigger_in,
    input wire trigger_out,
    input wire armed_out,
    input wire jtag_clk,
    input wire jtag_rst,
    input wire jtag_wr_en,
    input wire jtag_rd_en,
    input wire [15:0] jtag_addr,
    input wire [31:0] jtag_wdata,
    input wire [31:0] jtag_rdata,
    input wire burst_start,
    input wire burst_timestamp,
    input wire armed,
    input wire triggered,
    input wire done,
    input wire overflow,
    input wire all_seg_done,
    input wire trigger_hit,
    input wire trigger_commit_now,
    input wire pre_store_now,
    input wire post_store_now,
    input wire store_enable,
    input wire segment_auto_rearm_now
);
    localparam [15:0] ADDR_CTRL         = 16'h0004;
    localparam [15:0] ADDR_STATUS       = 16'h0008;
    localparam [15:0] ADDR_PRETRIG      = 16'h0014;
    localparam [15:0] ADDR_POSTTRIG     = 16'h0018;
    localparam [15:0] ADDR_TRIG_MODE    = 16'h0020;
    localparam [15:0] ADDR_TRIG_VALUE   = 16'h0024;
    localparam [15:0] ADDR_TRIG_MASK    = 16'h0028;
    localparam [15:0] ADDR_BURST_PTR    = 16'h002C;
    localparam [15:0] ADDR_SQ_MODE      = 16'h0030;
    localparam [15:0] ADDR_DECIM        = 16'h00B0;
    localparam [15:0] ADDR_TRIG_EXT     = 16'h00B4;
    localparam [15:0] ADDR_SEG_STATUS   = 16'h00BC;
    localparam [15:0] ADDR_SEG_SEL      = 16'h00C0;
    localparam [15:0] ADDR_PROBE_SEL    = 16'h00AC;
    localparam [15:0] ADDR_TRIG_DELAY   = 16'h00D4;
    localparam [15:0] ADDR_STARTUP_ARM  = 16'h00D8;
    localparam [15:0] ADDR_TRIG_HOLDOFF = 16'h00DC;
    localparam [15:0] ADDR_DATA_BASE    = 16'h0100;

    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_CTRL && jtag_wdata[0]);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_CTRL && jtag_wdata[1]);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_PRETRIG);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_POSTTRIG);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_MODE && jtag_wdata[1:0] == 2'd1);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_MODE && jtag_wdata[1:0] == 2'd2);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_VALUE);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_MASK);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        STOR_QUAL != 0 && jtag_wr_en && jtag_addr == ADDR_SQ_MODE);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        DECIM_EN != 0 && jtag_wr_en && jtag_addr == ADDR_DECIM && jtag_wdata != 32'h0);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        EXT_TRIG_EN != 0 && jtag_wr_en && jtag_addr == ADDR_TRIG_EXT && jtag_wdata[1:0] != 2'd0);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        NUM_SEGMENTS > 1 && jtag_wr_en && jtag_addr == ADDR_SEG_SEL);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        PROBE_MUX_W > 0 && jtag_wr_en && jtag_addr == ADDR_PROBE_SEL);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_DELAY && jtag_wdata[15:0] != 16'h0);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_STARTUP_ARM && jtag_wdata[0]);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_TRIG_HOLDOFF && jtag_wdata[15:0] != 16'h0);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_rd_en && jtag_addr == ADDR_STATUS);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        USER1_DATA_EN != 0 && jtag_rd_en && jtag_addr >= ADDR_DATA_BASE);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_rd_en && jtag_addr == ADDR_SEG_STATUS);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_wr_en && jtag_addr == ADDR_BURST_PTR);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        $changed(burst_start));
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        $changed(burst_start) && burst_timestamp);
    cover property (@(posedge jtag_clk) disable iff (jtag_rst)
        jtag_rd_en && jtag_rdata != 32'h0);

    cover property (@(posedge sample_clk) disable iff (sample_rst)
        armed_out);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        armed && !triggered && !done);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        trigger_hit);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        trigger_commit_now);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        triggered && !done);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        done);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        overflow);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        pre_store_now);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        post_store_now);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        store_enable);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        EXT_TRIG_EN != 0 && trigger_in);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        EXT_TRIG_EN != 0 && trigger_out);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        NUM_SEGMENTS > 1 && segment_auto_rearm_now);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        NUM_SEGMENTS > 1 && all_seg_done);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        INPUT_PIPE != 0 && trigger_commit_now);
    cover property (@(posedge sample_clk) disable iff (sample_rst)
        TIMESTAMP_W != 0 && post_store_now);
endmodule

bind fcapz_ela fcapz_ela_func_cov #(
    .SAMPLE_W(SAMPLE_W),
    .DEPTH(DEPTH),
    .TRIG_STAGES(TRIG_STAGES),
    .STOR_QUAL(STOR_QUAL),
    .NUM_CHANNELS(NUM_CHANNELS),
    .INPUT_PIPE(INPUT_PIPE),
    .DECIM_EN(DECIM_EN),
    .EXT_TRIG_EN(EXT_TRIG_EN),
    .TIMESTAMP_W(TIMESTAMP_W),
    .NUM_SEGMENTS(NUM_SEGMENTS),
    .PROBE_MUX_W(PROBE_MUX_W),
    .STARTUP_ARM(STARTUP_ARM),
    .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT),
    .REL_COMPARE(REL_COMPARE),
    .DUAL_COMPARE(DUAL_COMPARE),
    .USER1_DATA_EN(USER1_DATA_EN)
) fcapz_ela_func_cov_i (
    .sample_clk(sample_clk),
    .sample_rst(sample_rst),
    .trigger_in(trigger_in),
    .trigger_out(trigger_out),
    .armed_out(armed_out),
    .jtag_clk(jtag_clk),
    .jtag_rst(jtag_rst),
    .jtag_wr_en(jtag_wr_en),
    .jtag_rd_en(jtag_rd_en),
    .jtag_addr(jtag_addr),
    .jtag_wdata(jtag_wdata),
    .jtag_rdata(jtag_rdata),
    .burst_start(burst_start),
    .burst_timestamp(burst_timestamp),
    .armed(armed),
    .triggered(triggered),
    .done(done),
    .overflow(overflow),
    .all_seg_done(all_seg_done),
    .trigger_hit(trigger_hit),
    .trigger_commit_now(trigger_commit_now),
    .pre_store_now(pre_store_now),
    .post_store_now(post_store_now),
    .store_enable(store_enable),
    .segment_auto_rearm_now(segment_auto_rearm_now)
);
