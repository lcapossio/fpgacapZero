// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// DE25-Nano VexRiscv variant of the fpgacapZero Intel/Altera top-level.
//
// A drop-in for de25_nano_top: identical debug cores (ELA on instances 1/2, EIO
// on 3, EJTAG-AXI on 4, AXI monitor on 5) -- the one difference is that the
// self-stimulating master feeding the monitored bus is an open-source VexRiscv
// CPU (examples/de25_nano/vex/vex_cpu.v) running baked-in firmware, instead of
// the RTL axi4_traffic_gen. The CPU and the EJTAG-AXI bridge are merged by the
// vendor-neutral fcapz_axi_interconnect onto one shared axi4_test_slave, which
// the AXI monitor taps directly (no bus mux). The CPU uses the slave's high
// words (16/17) and the host's EJTAG read/write tests use words 0..15, so they
// never collide and the host can read CPU writes back over EJTAG-AXI.
//
// The firmware is free-running (it continuously issues clean write/write/read
// bursts to 0x4000_0000) so the monitor always has live CPU traffic with no
// host present; it never touches an error/hang address, so it cannot forge an
// any_err event.

module de25_nano_vex_top (
    input  wire       CLOCK1_50,
    input  wire [1:0] KEY,
    input  wire [3:0] SW,
    output wire [7:0] LEDR
);

    localparam SAMPLE_W = 8;
    localparam DEPTH = 1024;

    reg [7:0] por_count = 8'hFF;
    wire por_rst = |por_count;
    reg [SAMPLE_W-1:0] counter = {SAMPLE_W{1'b0}};
    reg [25:0] heartbeat_div = 26'd0;
    reg heartbeat = 1'b0;
    wire [7:0] eio_probe_in;
    wire [7:0] eio_probe_out;
    wire trigger_out_unused;
    wire ela_armed;
    wire axi_mon_trig_out_unused;
    wire axi_mon_armed_unused;
    reg [7:0] eio_out_sync1 = 8'h00;
    reg [7:0] eio_out_sync2 = 8'h00;
    reg ela_armed_d = 1'b0;
    reg [3:0] armed_test_count = 4'd0;
    reg armed_test_active = 1'b0;
    reg armed_test_pulse = 1'b0;
    reg armed_test_gate = 1'b0;
    wire ela_fresh_arm_w;
    wire trigger_in_w;

    wire [31:0] bridge_awaddr;
    wire [31:0] bridge_wdata;
    wire [31:0] bridge_araddr;
    wire [31:0] bridge_rdata;
    wire [7:0]  bridge_awlen;
    wire [7:0]  bridge_arlen;
    wire [2:0]  bridge_awsize;
    wire [2:0]  bridge_arsize;
    wire [2:0]  bridge_awprot;
    wire [2:0]  bridge_arprot;
    wire [1:0]  bridge_awburst;
    wire [1:0]  bridge_arburst;
    wire [1:0]  bridge_bresp;
    wire [1:0]  bridge_rresp;
    wire [3:0]  bridge_wstrb;
    wire        bridge_awvalid;
    wire        bridge_awready;
    wire        bridge_wvalid;
    wire        bridge_wready;
    wire        bridge_wlast;
    wire        bridge_bvalid;
    wire        bridge_bready;
    wire        bridge_arvalid;
    wire        bridge_arready;
    wire        bridge_rvalid;
    wire        bridge_rready;
    wire        bridge_rlast;
    wire [255:0] debug_tck_unused;
    wire [255:0] debug_tck_edge_unused;
    wire [255:0] debug_axi_unused;
    wire [255:0] debug_axi_edge_unused;

    // VexRiscv CPU master (s0 of the merged bus). Same wire names as the
    // axi4_traffic_gen it replaces, so the downstream taps below are unchanged.
    wire [31:0] gen_awaddr;
    wire [31:0] gen_wdata;
    wire [31:0] gen_araddr;
    wire [31:0] gen_rdata;
    wire [7:0]  gen_awlen;
    wire [7:0]  gen_arlen;
    wire [2:0]  gen_awsize;
    wire [2:0]  gen_arsize;
    wire [2:0]  gen_awprot;
    wire [2:0]  gen_arprot;
    wire [1:0]  gen_awburst;
    wire [1:0]  gen_arburst;
    wire [1:0]  gen_bresp;
    wire [1:0]  gen_rresp;
    wire [3:0]  gen_wstrb;
    wire        gen_awvalid;
    wire        gen_awready;
    wire        gen_wvalid;
    wire        gen_wready;
    wire        gen_wlast;
    wire        gen_bvalid;
    wire        gen_bready;
    wire        gen_arvalid;
    wire        gen_arready;
    wire        gen_rvalid;
    wire        gen_rready;
    wire        gen_rlast;

    // Shared merged bus (M_BUS): the fcapz_axi_interconnect drives both the
    // VexRiscv CPU (s0) and the EJTAG-AXI bridge (s1) onto this one bus, which
    // feeds the single shared axi4_test_slave. Same vendor-neutral shared-bus
    // topology as the Arty A7 VexRiscv build (there the SmartConnect's job) --
    // both masters now reach the same slave, so the host can read back CPU
    // writes over EJTAG-AXI. Full AXI4 subset; single-beat traffic only.
    wire [31:0] mbus_awaddr;
    wire [7:0]  mbus_awlen;
    wire [2:0]  mbus_awsize;
    wire [1:0]  mbus_awburst;
    wire [2:0]  mbus_awprot;
    wire        mbus_awvalid, mbus_awready;
    wire [31:0] mbus_wdata;
    wire [3:0]  mbus_wstrb;
    wire        mbus_wlast, mbus_wvalid, mbus_wready;
    wire [1:0]  mbus_bresp;
    wire        mbus_bvalid, mbus_bready;
    wire [31:0] mbus_araddr;
    wire [7:0]  mbus_arlen;
    wire [2:0]  mbus_arsize;
    wire [1:0]  mbus_arburst;
    wire [2:0]  mbus_arprot;
    wire        mbus_arvalid, mbus_arready;
    wire [31:0] mbus_rdata;
    wire [1:0]  mbus_rresp;
    wire        mbus_rlast, mbus_rvalid, mbus_rready;

    // The AXI monitor taps the AXI4-Lite subset of the merged bus, so it now
    // captures both the CPU's and the bridge's transactions directly (no mux).
    wire [31:0] mon_awaddr  = mbus_awaddr;
    wire [2:0]  mon_awprot  = mbus_awprot;
    wire        mon_awvalid = mbus_awvalid;
    wire        mon_awready = mbus_awready;
    wire [31:0] mon_wdata   = mbus_wdata;
    wire [3:0]  mon_wstrb   = mbus_wstrb;
    wire        mon_wvalid  = mbus_wvalid;
    wire        mon_wready  = mbus_wready;
    wire [1:0]  mon_bresp   = mbus_bresp;
    wire        mon_bvalid  = mbus_bvalid;
    wire        mon_bready  = mbus_bready;
    wire [31:0] mon_araddr  = mbus_araddr;
    wire [2:0]  mon_arprot  = mbus_arprot;
    wire        mon_arvalid = mbus_arvalid;
    wire        mon_arready = mbus_arready;
    wire [31:0] mon_rdata   = mbus_rdata;
    wire [1:0]  mon_rresp   = mbus_rresp;
    wire        mon_rvalid  = mbus_rvalid;
    wire        mon_rready  = mbus_rready;

    always @(posedge CLOCK1_50) begin
        if (por_rst) begin
            por_count <= por_count - 1'b1;
            counter <= {SAMPLE_W{1'b0}};
            heartbeat_div <= 26'd0;
            heartbeat <= 1'b0;
            eio_out_sync1 <= 8'h00;
            eio_out_sync2 <= 8'h00;
            ela_armed_d <= 1'b0;
            armed_test_count <= 4'd0;
            armed_test_active <= 1'b0;
            armed_test_pulse <= 1'b0;
            armed_test_gate <= 1'b0;
        end else begin
            counter <= counter + 1'b1;
            eio_out_sync1 <= eio_probe_out;
            eio_out_sync2 <= eio_out_sync1;
            ela_armed_d <= ela_armed;
            armed_test_pulse <= 1'b0;

            if (ela_fresh_arm_w) begin
                armed_test_count  <= 4'd0;
                armed_test_active <= eio_out_sync2[6];
                if (eio_out_sync2[5])
                    armed_test_pulse <= 1'b1;
                armed_test_gate <= 1'b0;
            end else if (!ela_armed) begin
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

            if (heartbeat_div == 26'd24_999_999) begin
                heartbeat_div <= 26'd0;
                heartbeat <= ~heartbeat;
            end else begin
                heartbeat_div <= heartbeat_div + 1'b1;
            end
        end
    end

    assign eio_probe_in = {SW, ~KEY, counter[1:0]};
    assign ela_fresh_arm_w = ela_armed && !ela_armed_d;
    assign trigger_in_w = eio_out_sync2[4] | armed_test_pulse | armed_test_gate;

    fcapz_ela_intel #(
        .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH),
        .CTRL_CHAIN(1),
        .DATA_CHAIN(2),
        .INPUT_PIPE(1),
        .DECIM_EN(1),
        .EXT_TRIG_EN(1),
        .TIMESTAMP_W(32),
        .NUM_SEGMENTS(4),
        .STARTUP_ARM(1),
        .DEFAULT_TRIG_EXT(2)
    ) u_ela (
        .sample_clk(CLOCK1_50),
        .sample_rst(por_rst),
        .probe_in(counter),
        .trigger_in(trigger_in_w),
        .trigger_out(trigger_out_unused),
        .armed_out(ela_armed)
    );

    fcapz_eio_intel #(
        .IN_W(8),
        .OUT_W(8),
        .CHAIN(3)
    ) u_eio (
        .probe_in(eio_probe_in),
        .probe_out(eio_probe_out)
    );

    fcapz_ejtagaxi_intel #(
        .ADDR_W(32),
        .DATA_W(32),
        .FIFO_DEPTH(16),
        .CMD_FIFO_DEPTH(16),
        .RESP_FIFO_DEPTH(16),
        .CMD_FIFO_MEMORY_TYPE("distributed"),
        .TIMEOUT(4096),
        .DEBUG_EN(0),
        .ASYNC_FIFO_IMPL(0),
        .CHAIN(4)
    ) u_ejtagaxi (
        .axi_clk(CLOCK1_50),
        .axi_rst(por_rst),
        .m_axi_awaddr(bridge_awaddr),
        .m_axi_awlen(bridge_awlen),
        .m_axi_awsize(bridge_awsize),
        .m_axi_awburst(bridge_awburst),
        .m_axi_awvalid(bridge_awvalid),
        .m_axi_awready(bridge_awready),
        .m_axi_awprot(bridge_awprot),
        .m_axi_wdata(bridge_wdata),
        .m_axi_wstrb(bridge_wstrb),
        .m_axi_wvalid(bridge_wvalid),
        .m_axi_wready(bridge_wready),
        .m_axi_wlast(bridge_wlast),
        .m_axi_bresp(bridge_bresp),
        .m_axi_bvalid(bridge_bvalid),
        .m_axi_bready(bridge_bready),
        .m_axi_araddr(bridge_araddr),
        .m_axi_arlen(bridge_arlen),
        .m_axi_arsize(bridge_arsize),
        .m_axi_arburst(bridge_arburst),
        .m_axi_arvalid(bridge_arvalid),
        .m_axi_arready(bridge_arready),
        .m_axi_arprot(bridge_arprot),
        .m_axi_rdata(bridge_rdata),
        .m_axi_rresp(bridge_rresp),
        .m_axi_rvalid(bridge_rvalid),
        .m_axi_rlast(bridge_rlast),
        .m_axi_rready(bridge_rready),
        .debug_tck(debug_tck_unused),
        .debug_tck_edge(debug_tck_edge_unused),
        .debug_axi(debug_axi_unused),
        .debug_axi_edge(debug_axi_edge_unused)
    );

    // Vendor-neutral AXI4 interconnect: merges the VexRiscv CPU (s0) and the
    // EJTAG-AXI bridge (s1) onto the shared M_BUS (m0). Single global slave map
    // covering the whole 4 GiB, so the host's 0xFFFF_FFFC error probe still
    // reaches the slave. Masters are single-ID so awid/arid/awregion/arregion
    // are tied off; the CPU does not drive awcache/awlock/awqos so those get
    // sane defaults while the bridge forwards its own. m0 ID/qualifier outputs
    // are unused downstream; bid/rid inputs are tied off because response
    // routing is by internal grant tracking (maxOutstanding=1 blocking).
    fcapz_axi_interconnect u_bus (
        .aclk    (CLOCK1_50),
        .aresetn (~por_rst),

        // ---- s0: VexRiscv CPU master (gen_*) ----
        .s0_axi_awvalid(gen_awvalid), .s0_axi_awready(gen_awready),
        .s0_axi_awaddr (gen_awaddr), .s0_axi_awid(4'd0), .s0_axi_awregion(4'd0),
        .s0_axi_awlen  (gen_awlen), .s0_axi_awsize(gen_awsize), .s0_axi_awburst(gen_awburst),
        .s0_axi_awlock (1'b0), .s0_axi_awcache(4'b0011), .s0_axi_awqos(4'b0000),
        .s0_axi_awprot (gen_awprot),
        .s0_axi_wvalid (gen_wvalid), .s0_axi_wready(gen_wready),
        .s0_axi_wdata  (gen_wdata), .s0_axi_wstrb(gen_wstrb), .s0_axi_wlast(gen_wlast),
        .s0_axi_bvalid (gen_bvalid), .s0_axi_bready(gen_bready),
        .s0_axi_bid    (), .s0_axi_bresp(gen_bresp),
        .s0_axi_arvalid(gen_arvalid), .s0_axi_arready(gen_arready),
        .s0_axi_araddr (gen_araddr), .s0_axi_arid(4'd0), .s0_axi_arregion(4'd0),
        .s0_axi_arlen  (gen_arlen), .s0_axi_arsize(gen_arsize), .s0_axi_arburst(gen_arburst),
        .s0_axi_arlock (1'b0), .s0_axi_arcache(4'b0011), .s0_axi_arqos(4'b0000),
        .s0_axi_arprot (gen_arprot),
        .s0_axi_rvalid (gen_rvalid), .s0_axi_rready(gen_rready),
        .s0_axi_rdata  (gen_rdata), .s0_axi_rid(), .s0_axi_rresp(gen_rresp), .s0_axi_rlast(gen_rlast),

        // ---- s1: EJTAG-AXI bridge master (bridge_*) ----
        .s1_axi_awvalid(bridge_awvalid), .s1_axi_awready(bridge_awready),
        .s1_axi_awaddr (bridge_awaddr), .s1_axi_awid(4'd0), .s1_axi_awregion(4'd0),
        .s1_axi_awlen  (bridge_awlen), .s1_axi_awsize(bridge_awsize), .s1_axi_awburst(bridge_awburst),
        .s1_axi_awlock (1'b0), .s1_axi_awcache(4'b0011), .s1_axi_awqos(4'b0000),
        .s1_axi_awprot (bridge_awprot),
        .s1_axi_wvalid (bridge_wvalid), .s1_axi_wready(bridge_wready),
        .s1_axi_wdata  (bridge_wdata), .s1_axi_wstrb(bridge_wstrb), .s1_axi_wlast(bridge_wlast),
        .s1_axi_bvalid (bridge_bvalid), .s1_axi_bready(bridge_bready),
        .s1_axi_bid    (), .s1_axi_bresp(bridge_bresp),
        .s1_axi_arvalid(bridge_arvalid), .s1_axi_arready(bridge_arready),
        .s1_axi_araddr (bridge_araddr), .s1_axi_arid(4'd0), .s1_axi_arregion(4'd0),
        .s1_axi_arlen  (bridge_arlen), .s1_axi_arsize(bridge_arsize), .s1_axi_arburst(bridge_arburst),
        .s1_axi_arlock (1'b0), .s1_axi_arcache(4'b0011), .s1_axi_arqos(4'b0000),
        .s1_axi_arprot (bridge_arprot),
        .s1_axi_rvalid (bridge_rvalid), .s1_axi_rready(bridge_rready),
        .s1_axi_rdata  (bridge_rdata), .s1_axi_rid(), .s1_axi_rresp(bridge_rresp), .s1_axi_rlast(bridge_rlast),

        // ---- m0: shared bus master (M_BUS) -> shared slave + monitor tap ----
        .m0_axi_awvalid(mbus_awvalid), .m0_axi_awready(mbus_awready),
        .m0_axi_awaddr (mbus_awaddr), .m0_axi_awid(), .m0_axi_awregion(),
        .m0_axi_awlen  (mbus_awlen), .m0_axi_awsize(mbus_awsize), .m0_axi_awburst(mbus_awburst),
        .m0_axi_awlock (), .m0_axi_awcache(), .m0_axi_awqos(), .m0_axi_awprot(mbus_awprot),
        .m0_axi_wvalid (mbus_wvalid), .m0_axi_wready(mbus_wready),
        .m0_axi_wdata  (mbus_wdata), .m0_axi_wstrb(mbus_wstrb), .m0_axi_wlast(mbus_wlast),
        .m0_axi_bvalid (mbus_bvalid), .m0_axi_bready(mbus_bready),
        .m0_axi_bid    (5'd0), .m0_axi_bresp(mbus_bresp),
        .m0_axi_arvalid(mbus_arvalid), .m0_axi_arready(mbus_arready),
        .m0_axi_araddr (mbus_araddr), .m0_axi_arid(), .m0_axi_arregion(),
        .m0_axi_arlen  (mbus_arlen), .m0_axi_arsize(mbus_arsize), .m0_axi_arburst(mbus_arburst),
        .m0_axi_arlock (), .m0_axi_arcache(), .m0_axi_arqos(), .m0_axi_arprot(mbus_arprot),
        .m0_axi_rvalid (mbus_rvalid), .m0_axi_rready(mbus_rready),
        .m0_axi_rdata  (mbus_rdata), .m0_axi_rid(5'd0), .m0_axi_rresp(mbus_rresp), .m0_axi_rlast(mbus_rlast)
    );

    // VexRiscv CPU: the self-stimulating master on the monitored bus. Runs the
    // baked-in firmware ($readmemh vex/fw/fw.mem into its 64 KB BRAM), which
    // continuously issues clean write/write/read bursts to 0x4000_0000. Gives
    // the AXI monitor live CPU traffic to trigger on when the EJTAG-AXI bridge
    // is idle. Independent of the bridge's slave, so the EJTAG read/write tests
    // are unaffected. rst is active-high (VexRiscv reset polarity) = por_rst.
    vex_cpu #(
        .MEM_INIT_FILE("fw.mem"),
        .RAM_WORDS(16384)
    ) u_vex_cpu (
        .clk(CLOCK1_50), .rst(por_rst),
        .m_axi_awaddr(gen_awaddr), .m_axi_awlen(gen_awlen), .m_axi_awsize(gen_awsize),
        .m_axi_awburst(gen_awburst), .m_axi_awprot(gen_awprot),
        .m_axi_awvalid(gen_awvalid), .m_axi_awready(gen_awready),
        .m_axi_wdata(gen_wdata), .m_axi_wstrb(gen_wstrb), .m_axi_wlast(gen_wlast),
        .m_axi_wvalid(gen_wvalid), .m_axi_wready(gen_wready),
        .m_axi_bresp(gen_bresp), .m_axi_bvalid(gen_bvalid), .m_axi_bready(gen_bready),
        .m_axi_araddr(gen_araddr), .m_axi_arlen(gen_arlen), .m_axi_arsize(gen_arsize),
        .m_axi_arburst(gen_arburst), .m_axi_arprot(gen_arprot),
        .m_axi_arvalid(gen_arvalid), .m_axi_arready(gen_arready),
        .m_axi_rdata(gen_rdata), .m_axi_rresp(gen_rresp), .m_axi_rlast(gen_rlast),
        .m_axi_rvalid(gen_rvalid), .m_axi_rready(gen_rready)
    );

    // Single shared test slave on the merged bus (M_BUS). 32 words like the
    // Arty A7 build: the host uses words 0..15 for its EJTAG read/write tests,
    // while the free-running CPU writes words 16/17 (0x4000_0040/44), so the
    // two masters share the slave without colliding. ERROR_ADDR (0xFFFF_FFFC)
    // still returns SLVERR because the interconnect maps the whole 4 GiB here.
    // HANG_EN=0: on this shared bus a never-ready hang would wedge the blocking
    // interconnect for both masters, so 0xFFFF_FFF8 is just a normal word.
    axi4_test_slave #(.NUM_WORDS(32), .ERROR_ADDR(32'hFFFF_FFFC), .HANG_EN(0)) u_axi_slave (
        .clk(CLOCK1_50),
        .rst(por_rst),
        .s_axi_awaddr(mbus_awaddr),
        .s_axi_awlen(mbus_awlen),
        .s_axi_awsize(mbus_awsize),
        .s_axi_awburst(mbus_awburst),
        .s_axi_awvalid(mbus_awvalid),
        .s_axi_awready(mbus_awready),
        .s_axi_wdata(mbus_wdata),
        .s_axi_wstrb(mbus_wstrb),
        .s_axi_wlast(mbus_wlast),
        .s_axi_wvalid(mbus_wvalid),
        .s_axi_wready(mbus_wready),
        .s_axi_bresp(mbus_bresp),
        .s_axi_bvalid(mbus_bvalid),
        .s_axi_bready(mbus_bready),
        .s_axi_araddr(mbus_araddr),
        .s_axi_arlen(mbus_arlen),
        .s_axi_arsize(mbus_arsize),
        .s_axi_arburst(mbus_arburst),
        .s_axi_arvalid(mbus_arvalid),
        .s_axi_arready(mbus_arready),
        .s_axi_rdata(mbus_rdata),
        .s_axi_rresp(mbus_rresp),
        .s_axi_rlast(mbus_rlast),
        .s_axi_rvalid(mbus_rvalid),
        .s_axi_rready(mbus_rready)
    );

    // AXI monitor (instance 5): passively tap the muxed AXI4-Lite bus (bridge
    // when active, else the VexRiscv CPU). Inputs only -- it never drives the
    // bus. DECODE_EN adds the transaction-events word (aw_hs / any_err / ...)
    // at the sample LSB so the host can trigger on bus events. ARESETN is
    // active-low; por_rst is active-high.
    // TRIG_STAGES=1 keeps the trigger on the simple comparator path that the
    // host's event_capture_config programs (TRIG_VALUE/MASK/MODE); the
    // multi-stage sequencer (TRIG_STAGES>1) would ignore that config. STOR_QUAL
    // and REL_COMPARE off match the hardware-validated Arty event-trigger setup.
    fcapz_axi_mon_intel #(
        .PROTO("AXI4LITE"),
        .ADDR_W(32),
        .DATA_W(32),
        .DEPTH(DEPTH),
        .TRIG_STAGES(1),
        .STOR_QUAL(0),
        .TIMESTAMP_W(32),
        .INPUT_PIPE(1),
        .NUM_SEGMENTS(1),
        .REL_COMPARE(0),
        .DECODE_EN(1),
        .CTRL_CHAIN(5)
    ) u_axi_mon (
        .ACLK(CLOCK1_50),
        .ARESETN(~por_rst),
        .AWADDR(mon_awaddr),
        .AWPROT(mon_awprot),
        .AWVALID(mon_awvalid),
        .AWREADY(mon_awready),
        .WDATA(mon_wdata),
        .WSTRB(mon_wstrb),
        .WVALID(mon_wvalid),
        .WREADY(mon_wready),
        .BRESP(mon_bresp),
        .BVALID(mon_bvalid),
        .BREADY(mon_bready),
        .ARADDR(mon_araddr),
        .ARPROT(mon_arprot),
        .ARVALID(mon_arvalid),
        .ARREADY(mon_arready),
        .RDATA(mon_rdata),
        .RRESP(mon_rresp),
        .RVALID(mon_rvalid),
        .RREADY(mon_rready),
        .trigger_in(1'b0),
        .trigger_out(axi_mon_trig_out_unused),
        .armed_out(axi_mon_armed_unused)
    );

    // DE25-Nano user LEDs are active-low. LEDR[0] shows heartbeat unless
    // overridden by EIO bit 0; other LEDs are direct EIO outputs.
    assign LEDR = ~({eio_out_sync2[7:1], eio_out_sync2[0] | heartbeat});

endmodule
