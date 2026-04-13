// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Arty A7-100T hardware-validation top-level for fpgacapZero.
//
// The design is intentionally small and self-stimulating so the Python
// hardware tests can run without external fabric logic:
//
// - ELA on USER1/USER2 captures a free-running 8-bit counter.
//   Enabled ELA options:
//     DECIM_EN=1       runtime sample decimation register
//     EXT_TRIG_EN=1    external trigger input from EIO probe_out[4]
//     TIMESTAMP_W=32   per-sample timestamp RAM/readback
//     NUM_SEGMENTS=4   segmented capture with auto-rearm
//   Baseline trigger sequencer/storage qualification settings stay at
//   wrapper defaults unless overridden in the wrapper parameters.
//
// - EIO on USER3 exposes {btn[3:0], counter[3:0]} as probe_in and drives
//   the four constrained green LEDs from probe_out[3:0] (resynced into clk).
//   probe_out[4]
//   feeds ELA trigger_in, so a host write can make a manual trigger edge.
//   probe_out[7:5] remains readable/writable over JTAG but is not bonded
//   to LEDs here.
//
// - EJTAG-AXI on USER4 connects to axi4_test_slave so hardware tests can
//   verify single AXI accesses, partial strobes, bursts, and error paths.
//
// All vendor TAP plumbing, JTAG register interfaces, and burst engines are
// contained in the fcapz_*_xilinx7 wrapper instances below.

module arty_a7_top (
    input  wire       clk,
    input  wire [3:0] btn,
    output wire [3:0] led
);

    localparam SAMPLE_W     = 8;
    localparam DEPTH        = 1024;
    localparam NUM_SEGMENTS = 4;

    reg [3:0] rst_pipe;
    wire rst;

    reg [SAMPLE_W-1:0] counter;
    wire trigger_out_w;
    wire [7:0] eio_probe_in;
    wire [7:0] eio_probe_out;

    // EIO probe_out updates on jtag_clk; LEDs are static I/O on the fabric clock domain.
    // Resync into sys_clk so the pins see clean levels (matches CDC note in docs/06_eio_core.md).
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync1;
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync2;

    assign eio_probe_in = {btn, counter[3:0]};

    // ---- Reset ----
    always @(posedge clk) begin
        rst_pipe <= {rst_pipe[2:0], btn[0]};
    end
    assign rst = rst_pipe[3];

    // ---- Counter (probe target) ----
    always @(posedge clk) begin
        if (rst)
            counter <= {SAMPLE_W{1'b0}};
        else
            counter <= counter + 1'b1;
    end

    // ---- ELA (all features enabled for HW validation) ----
    fcapz_ela_xilinx7 #(
        .SAMPLE_W     (SAMPLE_W),
        .DEPTH        (DEPTH),
        .DECIM_EN     (1),
        .EXT_TRIG_EN  (1),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (NUM_SEGMENTS)
    ) u_ela (
        .sample_clk (clk),
        .sample_rst (rst),
        .probe_in   (counter),
        .trigger_in (eio_probe_out[4]), // JTAG-driven manual trigger via EIO
        .trigger_out(trigger_out_w)
    );

    // ---- EJTAGAXI: JTAG-to-AXI4 bridge (USER4) ----
    // Bridges JTAG to AXI4 master, connected to a test slave for validation.

    wire [31:0] bridge_awaddr, bridge_wdata, bridge_araddr, bridge_rdata;
    wire [7:0]  bridge_awlen, bridge_arlen;
    wire [2:0]  bridge_awsize, bridge_arsize, bridge_awprot, bridge_arprot;
    wire [1:0]  bridge_awburst, bridge_arburst, bridge_bresp, bridge_rresp;
    wire [3:0]  bridge_wstrb;
    wire        bridge_awvalid, bridge_awready, bridge_wvalid, bridge_wready;
    wire        bridge_wlast, bridge_bvalid, bridge_bready;
    wire        bridge_arvalid, bridge_arready, bridge_rvalid, bridge_rready, bridge_rlast;

    fcapz_ejtagaxi_xilinx7 #(
        .ADDR_W(32), .DATA_W(32), .FIFO_DEPTH(16), .TIMEOUT(4096)
    ) u_ejtagaxi (
        .axi_clk(clk),
        .axi_rst(rst),
        .m_axi_awaddr(bridge_awaddr), .m_axi_awlen(bridge_awlen),
        .m_axi_awsize(bridge_awsize), .m_axi_awburst(bridge_awburst),
        .m_axi_awvalid(bridge_awvalid), .m_axi_awready(bridge_awready),
        .m_axi_awprot(bridge_awprot),
        .m_axi_wdata(bridge_wdata), .m_axi_wstrb(bridge_wstrb),
        .m_axi_wvalid(bridge_wvalid), .m_axi_wready(bridge_wready),
        .m_axi_wlast(bridge_wlast),
        .m_axi_bresp(bridge_bresp), .m_axi_bvalid(bridge_bvalid),
        .m_axi_bready(bridge_bready),
        .m_axi_araddr(bridge_araddr), .m_axi_arlen(bridge_arlen),
        .m_axi_arsize(bridge_arsize), .m_axi_arburst(bridge_arburst),
        .m_axi_arvalid(bridge_arvalid), .m_axi_arready(bridge_arready),
        .m_axi_arprot(bridge_arprot),
        .m_axi_rdata(bridge_rdata), .m_axi_rresp(bridge_rresp),
        .m_axi_rvalid(bridge_rvalid), .m_axi_rready(bridge_rready),
        .m_axi_rlast(bridge_rlast)
    );

    axi4_test_slave #(.NUM_WORDS(16), .ERROR_ADDR(32'hFFFF_FFFC)) u_axi_slave (
        .clk(clk), .rst(rst),
        .s_axi_awaddr(bridge_awaddr), .s_axi_awlen(bridge_awlen),
        .s_axi_awsize(bridge_awsize), .s_axi_awburst(bridge_awburst),
        .s_axi_awvalid(bridge_awvalid), .s_axi_awready(bridge_awready),
        .s_axi_wdata(bridge_wdata), .s_axi_wstrb(bridge_wstrb),
        .s_axi_wvalid(bridge_wvalid), .s_axi_wready(bridge_wready),
        .s_axi_wlast(bridge_wlast),
        .s_axi_bresp(bridge_bresp), .s_axi_bvalid(bridge_bvalid),
        .s_axi_bready(bridge_bready),
        .s_axi_araddr(bridge_araddr), .s_axi_arlen(bridge_arlen),
        .s_axi_arsize(bridge_arsize), .s_axi_arburst(bridge_arburst),
        .s_axi_arvalid(bridge_arvalid), .s_axi_arready(bridge_arready),
        .s_axi_rdata(bridge_rdata), .s_axi_rresp(bridge_rresp),
        .s_axi_rvalid(bridge_rvalid), .s_axi_rready(bridge_rready),
        .s_axi_rlast(bridge_rlast)
    );

    // ---- EIO: Embedded I/O (USER3) ----
    // Reads buttons plus the counter as probe_in, and drives the four
    // constrained green LEDs via probe_out.  The upper EIO output bits
    // still read back over JTAG, but are not bonded to LEDs in this XDC.

    always @(posedge clk) begin
        if (rst) begin
            led_sync1 <= 4'b0;
            led_sync2 <= 4'b0;
        end else begin
            led_sync1 <= eio_probe_out[3:0];
            led_sync2 <= led_sync1;
        end
    end
    assign led = led_sync2;

    fcapz_eio_xilinx7 #(
        .IN_W  (8),     // btn[3:0] + counter[3:0]
        .OUT_W (8),     // lower 4 bits drive physical LEDs
        .CHAIN (3)
    ) u_eio (
        .probe_in  (eio_probe_in),
        .probe_out (eio_probe_out)
    );

endmodule
