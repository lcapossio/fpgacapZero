// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Arty A7-100T hardware-validation top-level for fpgacapZero.
//
// The design is intentionally small and self-stimulating so the Python
// hardware tests can run without external fabric logic:
//
// - Two managed ELAs share USER1. ELA0 captures a free-running 8-bit counter
//   in a generated 150 MHz sample domain. ELA1 captures a separate 130 MHz
//   counter xored with 0xA5.
//   Enabled ELA options:
//     DECIM_EN=1       runtime sample decimation register
//     EXT_TRIG_EN=1    external trigger input from EIO probe_out[4]
//     TIMESTAMP_W=32   per-sample timestamp RAM/readback
//     NUM_SEGMENTS=4   segmented capture with auto-rearm
//     STARTUP_ARM=1    prove Xilinx configuration/GSR startup auto-arm
//     DEFAULT_TRIG_EXT=2 keeps the default startup arm waiting for EIO trigger_in
//   Baseline trigger sequencer/storage qualification settings stay at
//   wrapper defaults unless overridden in the wrapper parameters.
//
// - Two EIOs share USER1 through the debug core manager as slots 2 and 3.
//   EIO0 exposes {btn[3:0], slow_counter[3:0]} as probe_in and drives the
//   four constrained green LEDs from probe_out[3:0] (resynced into clk_150).
//   EIO0 probe_out[4] feeds ELA trigger_in, so a host write can make a manual
//   trigger edge. EIO1 exposes {counter_130[3:0], btn[3:0]} for slot
//   enumeration and independent EIO read/write validation.
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
    localparam integer CLK150_HZ = 150_000_000;

    wire clk_150;
    wire clk_130;
    wire clk_150_raw;
    wire clk_130_raw;
    wire clk150_fb;
    wire clk150_fb_buf;
    wire clk130_fb;
    wire clk130_fb_buf;
    wire clk150_locked;
    wire clk130_locked;
    wire rst_150_async;
    wire rst_130_async;
    wire rst_150;
    wire rst_130;
    reg [3:0] rst150_pipe;
    reg [3:0] rst130_pipe;

    reg [SAMPLE_W-1:0] counter_150;
    reg [SAMPLE_W-1:0] counter_130;
    reg [3:0] slow_counter;
    reg [27:0] sec_divider;
    wire [1:0] trigger_in_w;
    wire [1:0] trigger_out_w;
    wire [1:0] ela_armed_w;
    wire [7:0] eio0_probe_in;
    wire [7:0] eio0_probe_out;
    wire [7:0] eio1_probe_in;
    wire [7:0] eio1_probe_out;
    reg [7:0] eio_out_sync1;
    reg [7:0] eio_out_sync2;
    reg ela_pretrigger_d;
    reg [3:0] armed_test_count;
    reg armed_test_active;
    reg armed_test_pulse;
    reg armed_test_gate;
    wire ela_pretrigger_phase_w;
    wire ela_fresh_arm_phase_w;

    // EIO probe_out updates on jtag_clk; resync into clk_150 before using it
    // for LEDs or deterministic trigger-test controls.
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync1;
    (* ASYNC_REG = "TRUE" *) reg [3:0] led_sync2;

    // ---- Sample clocks ----
    // Arty A7 provides a 100 MHz board oscillator. The reference design
    // generates independent ELA sample domains so hardware tests exercise
    // managed slots that are not just aliases of the same clock.
    MMCME2_BASE #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKFBOUT_MULT_F(9.0),
        .CLKFBOUT_PHASE(0.0),
        .CLKIN1_PERIOD(10.000),
        .CLKOUT0_DIVIDE_F(6.0),
        .CLKOUT0_DUTY_CYCLE(0.5),
        .CLKOUT0_PHASE(0.0),
        .DIVCLK_DIVIDE(1),
        .REF_JITTER1(0.010),
        .STARTUP_WAIT("FALSE")
    ) u_mmcm_150 (
        .CLKIN1(clk),
        .CLKFBIN(clk150_fb_buf),
        .CLKFBOUT(clk150_fb),
        .CLKFBOUTB(),
        .CLKOUT0(clk_150_raw),
        .CLKOUT0B(),
        .CLKOUT1(),
        .CLKOUT1B(),
        .CLKOUT2(),
        .CLKOUT2B(),
        .CLKOUT3(),
        .CLKOUT3B(),
        .CLKOUT4(),
        .CLKOUT5(),
        .CLKOUT6(),
        .LOCKED(clk150_locked),
        .PWRDWN(1'b0),
        .RST(btn[0])
    );

    MMCME2_BASE #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKFBOUT_MULT_F(6.5),
        .CLKFBOUT_PHASE(0.0),
        .CLKIN1_PERIOD(10.000),
        .CLKOUT0_DIVIDE_F(5.0),
        .CLKOUT0_DUTY_CYCLE(0.5),
        .CLKOUT0_PHASE(0.0),
        .DIVCLK_DIVIDE(1),
        .REF_JITTER1(0.010),
        .STARTUP_WAIT("FALSE")
    ) u_mmcm_130 (
        .CLKIN1(clk),
        .CLKFBIN(clk130_fb_buf),
        .CLKFBOUT(clk130_fb),
        .CLKFBOUTB(),
        .CLKOUT0(clk_130_raw),
        .CLKOUT0B(),
        .CLKOUT1(),
        .CLKOUT1B(),
        .CLKOUT2(),
        .CLKOUT2B(),
        .CLKOUT3(),
        .CLKOUT3B(),
        .CLKOUT4(),
        .CLKOUT5(),
        .CLKOUT6(),
        .LOCKED(clk130_locked),
        .PWRDWN(1'b0),
        .RST(btn[0])
    );

    BUFG u_clk150_fb_buf (.I(clk150_fb), .O(clk150_fb_buf));
    BUFG u_clk150_buf    (.I(clk_150_raw), .O(clk_150));
    BUFG u_clk130_fb_buf (.I(clk130_fb), .O(clk130_fb_buf));
    BUFG u_clk130_buf    (.I(clk_130_raw), .O(clk_130));

    assign eio0_probe_in = {btn, slow_counter};
    assign eio1_probe_in = {counter_130[3:0], btn};

    // ---- Reset ----
    assign rst_150_async = btn[0] | ~clk150_locked;
    assign rst_130_async = btn[0] | ~clk130_locked;

    always @(posedge clk_150 or posedge rst_150_async) begin
        if (rst_150_async)
            rst150_pipe <= 4'hF;
        else
            rst150_pipe <= {rst150_pipe[2:0], 1'b0};
    end
    assign rst_150 = rst150_pipe[3];

    always @(posedge clk_130 or posedge rst_130_async) begin
        if (rst_130_async)
            rst130_pipe <= 4'hF;
        else
            rst130_pipe <= {rst130_pipe[2:0], 1'b0};
    end
    assign rst_130 = rst130_pipe[3];

    // ---- ELA probe counters ----
    always @(posedge clk_150) begin
        if (rst_150)
            counter_150 <= {SAMPLE_W{1'b0}};
        else
            counter_150 <= counter_150 + 1'b1;
    end

    always @(posedge clk_130) begin
        if (rst_130)
            counter_130 <= {SAMPLE_W{1'b0}};
        else
            counter_130 <= counter_130 + 1'b1;
    end

    // ---- Slow counter for EIO visibility ----
    // The visible EIO counter runs in the 150 MHz system/test domain and rolls
    // per second to make manual capture/readback easier to confirm.
    always @(posedge clk_150) begin
        if (rst_150) begin
            sec_divider  <= 28'd0;
            slow_counter <= 4'd0;
        end else if (sec_divider == CLK150_HZ - 1) begin
            sec_divider  <= 28'd0;
            slow_counter <= slow_counter + 1'b1;
        end else begin
            sec_divider <= sec_divider + 1'b1;
        end
    end

    // ---- EIO output resynchronization ----
    always @(posedge clk_150) begin
        if (rst_150) begin
            eio_out_sync1 <= 8'h00;
            eio_out_sync2 <= 8'h00;
        end else begin
            eio_out_sync1 <= eio0_probe_out;
            eio_out_sync2 <= eio_out_sync1;
        end
    end

    assign ela_pretrigger_phase_w = ela_armed_w[0];
    assign ela_fresh_arm_phase_w = ela_pretrigger_phase_w && !ela_pretrigger_d;

    // ---- Deterministic trigger test hook ----
    // eio_probe_out[4]: manual external trigger (legacy host-driven)
    // eio_probe_out[5]: emit one pulse immediately when ELA enters a fresh
    //                   armed/not-triggered phase
    // eio_probe_out[6]: emit one pulse 8 cycles after ELA enters a fresh
    //                   armed/not-triggered phase
    always @(posedge clk_150) begin
        if (rst_150) begin
            ela_pretrigger_d  <= 1'b0;
            armed_test_count  <= 4'd0;
            armed_test_active <= 1'b0;
            armed_test_pulse  <= 1'b0;
            armed_test_gate   <= 1'b0;
        end else begin
            ela_pretrigger_d  <= ela_pretrigger_phase_w;
            armed_test_pulse  <= 1'b0;

            if (ela_fresh_arm_phase_w) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= eio_out_sync2[6];
                if (eio_out_sync2[5])
                    armed_test_pulse <= 1'b1;
                armed_test_gate   <= 1'b0;
            end else if (!ela_armed_w[0]) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= 1'b0;
                armed_test_gate   <= 1'b0;
            end else if (armed_test_active) begin
                armed_test_count <= armed_test_count + 1'b1;
                if (eio_out_sync2[6] && (armed_test_count == 4'd7))
                    armed_test_gate <= 1'b1;
                if (armed_test_count == 4'd7)
                    armed_test_active <= 1'b0;
            end
        end
    end

    assign trigger_in_w = {
        1'b0,
        eio_out_sync2[4] | armed_test_pulse | armed_test_gate
    };

    // ---- ELAs (all features enabled for HW validation) ----
    // Slot 0 preserves the historical Arty capture target on 150 MHz. Slot 1
    // captures a different 130 MHz deterministic pattern so hardware tests can
    // validate the manager path without needing extra board wiring.
    fcapz_debug_multi_xilinx7 #(
        .NUM_ELAS     (2),
        .EIO_EN       (1),
        .NUM_EIOS     (2),
        .SAMPLE_W     (SAMPLE_W),
        .DEPTH        (DEPTH),
        .INPUT_PIPE   (1),
        .DECIM_EN     (1),
        .EXT_TRIG_EN  (1),
        .TIMESTAMP_W  (32),
        .NUM_SEGMENTS (NUM_SEGMENTS),
        .STARTUP_ARM  (1),
        .DEFAULT_TRIG_EXT(2),
        .EIO_IN_W     (8),
        .EIO_OUT_W    (8)
    ) u_debug (
        .ela_sample_clk ({clk_130, clk_150}),
        .ela_sample_rst ({rst_130, rst_150}),
        .ela_probe_in   ({counter_130 ^ 8'hA5, counter_150}),
        .ela_trigger_in (trigger_in_w),
        .ela_trigger_out(trigger_out_w),
        .ela_armed_out  (ela_armed_w),
        .eio_probe_in   ({eio1_probe_in, eio0_probe_in}),
        .eio_probe_out  ({eio1_probe_out, eio0_probe_out})
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

    // DEBUG_EN is intentionally off in the shipping reference design:
    // USER4 validation uses host AXI reads/writes, and no ILA consumes the
    // bridge's internal 256-bit telemetry buses here.
    fcapz_ejtagaxi_xilinx7 #(
        .ADDR_W(32), .DATA_W(32),
        .FIFO_DEPTH(16),
        .CMD_FIFO_DEPTH(16),
        .RESP_FIFO_DEPTH(16),
        .CMD_FIFO_MEMORY_TYPE("distributed"),
        .TIMEOUT(4096),
        .DEBUG_EN(0)
    ) u_ejtagaxi (
        .axi_clk(clk_150),
        .axi_rst(rst_150),
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
        .clk(clk_150), .rst(rst_150),
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

    // ---- EIO LED output resync ----
    // Reads buttons plus the slow counter as probe_in, and drives the four
    // constrained green LEDs via probe_out.  The upper EIO output bits
    // still read back over JTAG, but are not bonded to LEDs in this XDC.

    always @(posedge clk_150) begin
        if (rst_150) begin
            led_sync1 <= 4'b0;
            led_sync2 <= 4'b0;
        end else begin
            led_sync1 <= eio_out_sync2[3:0];
            led_sync2 <= led_sync1;
        end
    end
    assign led = led_sync2;

endmodule
