// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Kria KV260 (Zynq UltraScale+ MPSoC, xck26) hardware-validation top-level.
//
// The KV260 has no PL oscillator, so a minimal block design (kv260_ps.bd,
// built by create_ps_bd.tcl) exposes the PS pl_clk0 and nothing else.  The
// PS carries no software here; pl_clk0 runs at whatever the board's boot
// firmware programmed, so the hardware test measures it instead of assuming
// it.  pl_resetn0 is deliberately unused: without Linux bringing up the PL
// it is never output-enabled and would hold the design in reset.  A
// power-on shift register (INIT values load at configuration) is the reset.
//
// The design is self-stimulating, like the Arty reference, and puts one
// core on each BSCANE2 USER chain:
//
// - USER1: fcapz_debug_multi_xilinx7 (the manager, on US+ silicon) with
//     slot 0  ELA, 8-bit counter, decimation, external trigger, 32-bit
//             timestamps, 4 segments
//     slot 1  ELA, two 8-bit channels, 4-stage trigger sequencer, storage
//             qualification, relational compares
//     slot 2  EIO, 8 in / 8 out; out[4] is ELA slot 0 trigger_in
//     slot 3  EIO, 32 in / 8 out; in is a free-running pl_clk0 counter, so
//             the host can prove the clock is alive and measure it
// - USER2: fcapz_axi_mon_xilinx7 (DECODE_EN=1) tapping the AXI test bus
// - USER3: fcapz_ejtaguart_xilinxus with TX looped back to RX
// - USER4: fcapz_ejtagaxi_xilinxus driving tb/axi4_test_slave

module kv260_top;

    localparam SAMPLE_W     = 8;
    localparam DEPTH        = 1024;
    localparam NUM_SEGMENTS = 4;

    // ---- Clock and power-on reset ----
    wire clk;

    kv260_ps_wrapper u_ps (
        .pl_clk0(clk)
    );

    (* ASYNC_REG = "TRUE" *) reg [7:0] por_pipe = 8'hFF;
    always @(posedge clk)
        por_pipe <= {por_pipe[6:0], 1'b0};
    wire rst = por_pipe[7];

    // ---- Probe stimulus ----
    reg [SAMPLE_W-1:0] counter_a;
    reg [15:0]         counter_b;
    reg [31:0]         free_counter = 32'd0;
    reg [3:0]          slow_counter;
    reg [23:0]         slow_divider;

    always @(posedge clk) begin
        if (rst) begin
            counter_a    <= {SAMPLE_W{1'b0}};
            counter_b    <= 16'd0;
            slow_counter <= 4'd0;
            slow_divider <= 24'd0;
        end else begin
            counter_a    <= counter_a + 1'b1;
            counter_b    <= counter_b + 1'b1;
            slow_divider <= slow_divider + 1'b1;
            if (&slow_divider)
                slow_counter <= slow_counter + 1'b1;
        end
    end

    // Not reset: the host reads it to measure pl_clk0, and a counter that
    // advances proves the clock is running and the POR has released.
    always @(posedge clk)
        free_counter <= free_counter + 1'b1;

    // ---- EIO outputs, resynchronised from jtag_clk into clk ----
    wire [7:0] eio0_probe_out;
    wire [7:0] eio1_probe_out;
    (* ASYNC_REG = "TRUE" *) reg [7:0] eio_out_sync1;
    (* ASYNC_REG = "TRUE" *) reg [7:0] eio_out_sync2;
    always @(posedge clk) begin
        if (rst) begin
            eio_out_sync1 <= 8'h00;
            eio_out_sync2 <= 8'h00;
        end else begin
            eio_out_sync1 <= eio0_probe_out;
            eio_out_sync2 <= eio_out_sync1;
        end
    end

    wire [1:0] ela_trigger_out;
    wire [1:0] ela_armed;

    // ---- USER1: managed ELAs + EIOs ----
    // The scalar parameters give the widest slot shape (two channels, 32-bit
    // EIO input); the per-slot vectors narrow slot 0 and EIO slot 2.  Slot 1
    // keeps the scalar depth, timestamp width and segment count, so both
    // ELAs keep the USER1 burst readback path.
    fcapz_debug_multi_xilinx7 #(
        .NUM_ELAS     (2),
        .EIO_EN       (1),
        .NUM_EIOS     (2),
        .SAMPLE_W     (SAMPLE_W),
        .DEPTH        (DEPTH),
        .INPUT_PIPE   (1),
        .NUM_CHANNELS (2),
        .DECIM_EN     (1),
        .EXT_TRIG_EN  (1),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (NUM_SEGMENTS),
        .EIO_IN_W     (32),
        .EIO_OUT_W    (8),
        .ELA_NUM_CHANNELS({32'd2, 32'd1}),
        .ELA_TRIG_STAGES ({32'd4, 32'd1}),
        .ELA_STOR_QUALS  ({32'd1, 32'd0}),
        .ELA_REL_COMPARES({32'd1, 32'd0}),
        .ELA_EXT_TRIG_ENS({32'd0, 32'd1}),
        .EIO_IN_WS       ({32'd32, 32'd8})
    ) u_debug (
        .ela_sample_clk ({clk, clk}),
        .ela_sample_rst ({rst, rst}),
        // Slot 1: channel 1 = counter_b[15:8], channel 0 = counter_b[7:0]^A5.
        // Slot 0: counter_a in the low byte; the high byte is unused.
        .ela_probe_in   ({counter_b[15:8], counter_b[7:0] ^ 8'hA5,
                          8'h00, counter_a}),
        .ela_trigger_in ({1'b0, eio_out_sync2[4]}),
        .ela_trigger_out(ela_trigger_out),
        .ela_armed_out  (ela_armed),
        .eio_probe_in   ({free_counter, 24'd0, ela_armed, 2'b00, slow_counter}),
        .eio_probe_out  ({eio1_probe_out, eio0_probe_out})
    );

    // ---- USER4: EJTAG-AXI bridge -> AXI4 test slave ----
    wire [31:0] axi_awaddr, axi_wdata, axi_araddr, axi_rdata;
    wire [7:0]  axi_awlen, axi_arlen;
    wire [2:0]  axi_awsize, axi_arsize, axi_awprot, axi_arprot;
    wire [1:0]  axi_awburst, axi_arburst, axi_bresp, axi_rresp;
    wire [3:0]  axi_wstrb;
    wire        axi_awvalid, axi_awready, axi_wvalid, axi_wready, axi_wlast;
    wire        axi_bvalid, axi_bready;
    wire        axi_arvalid, axi_arready, axi_rvalid, axi_rready, axi_rlast;

    fcapz_ejtagaxi_xilinxus #(
        .ADDR_W(32), .DATA_W(32),
        .FIFO_DEPTH(16),
        .CMD_FIFO_DEPTH(16),
        .RESP_FIFO_DEPTH(16),
        .CMD_FIFO_MEMORY_TYPE("distributed"),
        .TIMEOUT(4096),
        .DEBUG_EN(0),
        .CHAIN(4)
    ) u_ejtagaxi (
        .axi_clk(clk),
        .axi_rst(rst),
        .m_axi_awaddr(axi_awaddr), .m_axi_awlen(axi_awlen),
        .m_axi_awsize(axi_awsize), .m_axi_awburst(axi_awburst),
        .m_axi_awvalid(axi_awvalid), .m_axi_awready(axi_awready),
        .m_axi_awprot(axi_awprot),
        .m_axi_wdata(axi_wdata), .m_axi_wstrb(axi_wstrb),
        .m_axi_wvalid(axi_wvalid), .m_axi_wready(axi_wready),
        .m_axi_wlast(axi_wlast),
        .m_axi_bresp(axi_bresp), .m_axi_bvalid(axi_bvalid),
        .m_axi_bready(axi_bready),
        .m_axi_araddr(axi_araddr), .m_axi_arlen(axi_arlen),
        .m_axi_arsize(axi_arsize), .m_axi_arburst(axi_arburst),
        .m_axi_arvalid(axi_arvalid), .m_axi_arready(axi_arready),
        .m_axi_arprot(axi_arprot),
        .m_axi_rdata(axi_rdata), .m_axi_rresp(axi_rresp),
        .m_axi_rvalid(axi_rvalid), .m_axi_rready(axi_rready),
        .m_axi_rlast(axi_rlast)
    );

    axi4_test_slave #(.NUM_WORDS(32), .ERROR_ADDR(32'hFFFF_FFFC)) u_axi_slave (
        .clk(clk), .rst(rst),
        .s_axi_awaddr(axi_awaddr), .s_axi_awlen(axi_awlen),
        .s_axi_awsize(axi_awsize), .s_axi_awburst(axi_awburst),
        .s_axi_awvalid(axi_awvalid), .s_axi_awready(axi_awready),
        .s_axi_wdata(axi_wdata), .s_axi_wstrb(axi_wstrb),
        .s_axi_wvalid(axi_wvalid), .s_axi_wready(axi_wready),
        .s_axi_wlast(axi_wlast),
        .s_axi_bresp(axi_bresp), .s_axi_bvalid(axi_bvalid),
        .s_axi_bready(axi_bready),
        .s_axi_araddr(axi_araddr), .s_axi_arlen(axi_arlen),
        .s_axi_arsize(axi_arsize), .s_axi_arburst(axi_arburst),
        .s_axi_arvalid(axi_arvalid), .s_axi_arready(axi_arready),
        .s_axi_rdata(axi_rdata), .s_axi_rresp(axi_rresp),
        .s_axi_rvalid(axi_rvalid), .s_axi_rready(axi_rready),
        .s_axi_rlast(axi_rlast)
    );

    // ---- USER2: AXI monitor on the bridge <-> test slave bus ----
    fcapz_axi_mon_xilinx7 #(
        .ADDR_W(32), .DATA_W(32),
        .DEPTH(256),
        .TRIG_STAGES(1),
        .STOR_QUAL(0),
        .TIMESTAMP_W(0),
        .INPUT_PIPE(1),
        .REL_COMPARE(0),
        .DECODE_EN(1),
        .CTRL_CHAIN(2)
    ) u_axi_mon (
        .ACLK(clk), .ARESETN(~rst),
        .AWADDR(axi_awaddr), .AWPROT(axi_awprot),
        .AWVALID(axi_awvalid), .AWREADY(axi_awready),
        .WDATA(axi_wdata), .WSTRB(axi_wstrb),
        .WVALID(axi_wvalid), .WREADY(axi_wready),
        .BRESP(axi_bresp), .BVALID(axi_bvalid), .BREADY(axi_bready),
        .ARADDR(axi_araddr), .ARPROT(axi_arprot),
        .ARVALID(axi_arvalid), .ARREADY(axi_arready),
        .RDATA(axi_rdata), .RRESP(axi_rresp),
        .RVALID(axi_rvalid), .RREADY(axi_rready),
        .trigger_in(1'b0), .trigger_out(), .armed_out()
    );

    // ---- USER3: EJTAG-UART, TX looped back to RX ----
    // TX and RX share one baud divider, so the loopback works whatever
    // pl_clk0 frequency the boot firmware chose.
    wire uart_loop;

    fcapz_ejtaguart_xilinxus #(
        .JTAG_CHAIN(3),
        .CLK_HZ(100_000_000),
        .BAUD_RATE(115200)
    ) u_uart (
        .uart_clk(clk),
        .uart_rst(rst),
        .uart_txd(uart_loop),
        .uart_rxd(uart_loop)
    );

endmodule
