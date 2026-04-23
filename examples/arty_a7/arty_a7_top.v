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
// - EIO on USER3 exposes {btn[3:0], slow_counter[3:0]} as probe_in and drives
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
    localparam integer CLK_HZ = 100_000_000;

    reg [3:0] rst_pipe;
    wire rst;

    reg [SAMPLE_W-1:0] counter;
    reg [3:0] slow_counter;
    reg [26:0] sec_divider;
    wire trigger_out_w;
    wire ela_armed_w;
    wire [7:0] eio_probe_in;
    wire [7:0] eio_probe_out;
    reg [7:0] eio_out_sync1;
    reg [7:0] eio_out_sync2;
    reg ela_armed_d;
    reg [3:0] armed_test_count;
    reg armed_test_active;
    reg armed_test_pulse;
    reg armed_test_gate;
    wire trigger_in_w;

    // EIO probe_out updates on jtag_clk; resync into sys_clk before using it
    // for LEDs or deterministic trigger-test controls.
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync1;
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync2;

    assign eio_probe_in = {btn, slow_counter};

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

    // ---- Slow counter for EIO visibility ----
    // Arty A7 reference clock is 100 MHz, so roll the visible EIO counter once
    // per second to make manual capture/readback easier to confirm.
    always @(posedge clk) begin
        if (rst) begin
            sec_divider  <= 27'd0;
            slow_counter <= 4'd0;
        end else if (sec_divider == CLK_HZ - 1) begin
            sec_divider  <= 27'd0;
            slow_counter <= slow_counter + 1'b1;
        end else begin
            sec_divider <= sec_divider + 1'b1;
        end
    end

    // ---- EIO output resynchronization ----
    always @(posedge clk) begin
        if (rst) begin
            eio_out_sync1 <= 8'h00;
            eio_out_sync2 <= 8'h00;
        end else begin
            eio_out_sync1 <= eio_probe_out;
            eio_out_sync2 <= eio_out_sync1;
        end
    end

    // ---- Deterministic trigger test hook ----
    // eio_probe_out[4]: manual external trigger (legacy host-driven)
    // eio_probe_out[5]: emit one pulse 2 cycles after ELA enters ARMED
    // eio_probe_out[6]: emit one pulse 8 cycles after ELA enters ARMED
    always @(posedge clk) begin
        if (rst) begin
            ela_armed_d       <= 1'b0;
            armed_test_count  <= 4'd0;
            armed_test_active <= 1'b0;
            armed_test_pulse  <= 1'b0;
            armed_test_gate   <= 1'b0;
        end else begin
            ela_armed_d       <= ela_armed_w;
            armed_test_pulse  <= 1'b0;

            if (ela_armed_w && !ela_armed_d) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= eio_out_sync2[5] | eio_out_sync2[6];
                armed_test_gate   <= 1'b0;
            end else if (!ela_armed_w) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= 1'b0;
                armed_test_gate   <= 1'b0;
            end else if (armed_test_active) begin
                armed_test_count <= armed_test_count + 1'b1;
                if (eio_out_sync2[5] && (armed_test_count == 4'd1))
                    armed_test_pulse <= 1'b1;
                if (eio_out_sync2[6] && (armed_test_count == 4'd7))
                    armed_test_gate <= 1'b1;
                if (armed_test_count == 4'd7)
                    armed_test_active <= 1'b0;
            end
        end
    end

    assign trigger_in_w = eio_out_sync2[4] | armed_test_pulse | armed_test_gate;

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
        .trigger_in (trigger_in_w),
        .trigger_out(trigger_out_w),
        .armed_out  (ela_armed_w)
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
    // Reads buttons plus the slow counter as probe_in, and drives the four
    // constrained green LEDs via probe_out.  The upper EIO output bits
    // still read back over JTAG, but are not bonded to LEDs in this XDC.

    always @(posedge clk) begin
        if (rst) begin
            led_sync1 <= 4'b0;
            led_sync2 <= 4'b0;
        end else begin
            led_sync1 <= eio_out_sync2[3:0];
            led_sync2 <= led_sync1;
        end
    end
    assign led = led_sync2;

    fcapz_eio_xilinx7 #(
        .IN_W  (8),     // btn[3:0] + slow_counter[3:0]
        .OUT_W (8),     // lower 4 bits drive physical LEDs
        .CHAIN (3)
    ) u_eio (
        .probe_in  (eio_probe_in),
        .probe_out (eio_probe_out)
    );

endmodule
