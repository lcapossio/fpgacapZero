// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// VexRiscv CPU subsystem for the DE25-Nano fpgacapZero reference design.
//
// Wraps the pre-generated VexRiscv_Lite core (RV32I, plain Wishbone iBus/dBus;
// fetched by examples/de25_nano/vex/get_deps.py) with just enough glue to run
// the bare-metal firmware and drive the monitored AXI bus:
//
//   * a 2->1 classic-Wishbone arbiter merges the instruction and data buses;
//   * an address decoder splits the merged bus into three regions --
//       0x0000_0000  64 KB on-chip BRAM   (firmware image, $readmemh fw.mem)
//       0x1000_0000  free-running 32-bit cycle counter (read-only)
//       0x4000_0000  everything else -> Wishbone-to-AXI4 single-beat master;
//   * the AXI4 master drives the AXI monitor's traffic-generator slave directly
//     (no SmartConnect: Intel/Altera has none, and the DE25-Nano keeps the
//     generator bus separate from the EJTAG-AXI bridge -- the monitor mux shows
//     the CPU whenever the bridge is idle).
//
// VexRiscv_Lite has no cache, so both buses issue single classic Wishbone
// transfers (CTI/BTE are ignored). The design favours obvious correctness over
// throughput: one outstanding transaction, 1-cycle BRAM/counter latency.
//
// This is a self-contained copy of the arbiter/decode/WB->AXI logic in
// examples/arty_a7/vex/vex_cpu.v (kept per-example like the other DE25 RTL);
// it is functionally identical, differing only in this header and in the
// RAM-inference attribute, which here also carries the Intel (ramstyle)
// spelling alongside the Xilinx (ram_style) one. Keep the two in sync.

module vex_cpu #(
    parameter MEM_INIT_FILE = "fw.mem",
    parameter integer RAM_WORDS = 16384   // 64 KB / 4
) (
    input  wire        clk,
    input  wire        rst,               // active-high (VexRiscv reset polarity)

    // AXI4 master -> monitored traffic-generator slave. Single-beat (len = 0).
    output wire [31:0] m_axi_awaddr,
    output wire [7:0]  m_axi_awlen,
    output wire [2:0]  m_axi_awsize,
    output wire [1:0]  m_axi_awburst,
    output wire [2:0]  m_axi_awprot,
    output wire        m_axi_awvalid,
    input  wire        m_axi_awready,
    output wire [31:0] m_axi_wdata,
    output wire [3:0]  m_axi_wstrb,
    output wire        m_axi_wlast,
    output wire        m_axi_wvalid,
    input  wire        m_axi_wready,
    input  wire [1:0]  m_axi_bresp,
    input  wire        m_axi_bvalid,
    output wire        m_axi_bready,
    output wire [31:0] m_axi_araddr,
    output wire [7:0]  m_axi_arlen,
    output wire [2:0]  m_axi_arsize,
    output wire [1:0]  m_axi_arburst,
    output wire [2:0]  m_axi_arprot,
    output wire        m_axi_arvalid,
    input  wire        m_axi_arready,
    input  wire [31:0] m_axi_rdata,
    input  wire [1:0]  m_axi_rresp,
    input  wire        m_axi_rlast,
    input  wire        m_axi_rvalid,
    output wire        m_axi_rready
);

    // ---- VexRiscv core + its two Wishbone buses ------------------------
    wire        ibus_cyc, ibus_stb, ibus_we, ibus_ack, ibus_err;
    wire [29:0] ibus_adr;
    wire [31:0] ibus_dat_miso, ibus_dat_mosi;
    wire [3:0]  ibus_sel;
    wire [2:0]  ibus_cti;
    wire [1:0]  ibus_bte;

    wire        dbus_cyc, dbus_stb, dbus_we, dbus_ack, dbus_err;
    wire [29:0] dbus_adr;
    wire [31:0] dbus_dat_miso, dbus_dat_mosi;
    wire [3:0]  dbus_sel;
    wire [2:0]  dbus_cti;
    wire [1:0]  dbus_bte;

    VexRiscv u_core (
        .externalResetVector    (32'h0000_0000),
        .timerInterrupt         (1'b0),
        .softwareInterrupt      (1'b0),
        .externalInterruptArray (32'h0000_0000),
        .iBusWishbone_CYC       (ibus_cyc),
        .iBusWishbone_STB       (ibus_stb),
        .iBusWishbone_ACK       (ibus_ack),
        .iBusWishbone_WE        (ibus_we),
        .iBusWishbone_ADR       (ibus_adr),
        .iBusWishbone_DAT_MISO  (ibus_dat_miso),
        .iBusWishbone_DAT_MOSI  (ibus_dat_mosi),
        .iBusWishbone_SEL       (ibus_sel),
        .iBusWishbone_ERR       (ibus_err),
        .iBusWishbone_CTI       (ibus_cti),
        .iBusWishbone_BTE       (ibus_bte),
        .dBusWishbone_CYC       (dbus_cyc),
        .dBusWishbone_STB       (dbus_stb),
        .dBusWishbone_ACK       (dbus_ack),
        .dBusWishbone_WE        (dbus_we),
        .dBusWishbone_ADR       (dbus_adr),
        .dBusWishbone_DAT_MISO  (dbus_dat_miso),
        .dBusWishbone_DAT_MOSI  (dbus_dat_mosi),
        .dBusWishbone_SEL       (dbus_sel),
        .dBusWishbone_ERR       (dbus_err),
        .dBusWishbone_CTI       (dbus_cti),
        .dBusWishbone_BTE       (dbus_bte),
        .clk                    (clk),
        .reset                  (rst)
    );

    // ---- 2->1 classic-Wishbone arbiter ---------------------------------
    // Grant one bus at a time and hold until the transfer is acked. Data bus
    // wins a tie (keeps loads/stores moving); the instruction bus is read-only.
    wire ibus_req = ibus_cyc & ibus_stb;
    wire dbus_req = dbus_cyc & dbus_stb;

    reg  busy;     // a transfer is in progress
    reg  owner;    // 0 = instruction bus, 1 = data bus
    wire ack_int;  // slave ack for the current transfer

    always @(posedge clk) begin
        if (rst) begin
            busy  <= 1'b0;
            owner <= 1'b0;
        end else if (!busy) begin
            if (dbus_req) begin busy <= 1'b1; owner <= 1'b1; end
            else if (ibus_req) begin busy <= 1'b1; owner <= 1'b0; end
        end else if (ack_int) begin
            busy <= 1'b0;
        end
    end

    // Selected master view (valid while busy).
    wire        v_stb = busy;
    wire        v_we  = owner ? dbus_we  : 1'b0;      // iBus never writes
    wire [29:0] v_adr = owner ? dbus_adr : ibus_adr;
    wire [31:0] v_dat = owner ? dbus_dat_mosi : 32'h0;
    wire [3:0]  v_sel = owner ? dbus_sel : ibus_sel;

    // ---- Region decode (byte_addr = v_adr << 2) ------------------------
    // byte_addr[31:28] == v_adr[29:26]: 0x0=RAM, 0x1=cycle ctr, 0x4=periph.
    wire is_ram    = v_stb & (v_adr[29:26] == 4'h0);
    wire is_cycle  = v_stb & (v_adr[29:26] == 4'h1);
    wire is_periph = v_stb & (v_adr[29:26] == 4'h4);
    wire is_unmap  = v_stb & ~is_ram & ~is_cycle & ~is_periph;

    // ---- On-chip BRAM (firmware image) ---------------------------------
    (* ram_style = "block", ramstyle = "no_rw_check, M20K" *)
    reg [31:0] ram [0:RAM_WORDS-1];
    initial begin
        $readmemh(MEM_INIT_FILE, ram);
    end

    localparam integer RAM_AW = $clog2(RAM_WORDS);
    wire [RAM_AW-1:0] ram_addr = v_adr[RAM_AW-1:0];

    reg        ram_ack;
    reg [31:0] ram_rdata;
    wire       ram_go = is_ram & ~ram_ack;   // one-shot request

    always @(posedge clk) begin
        ram_ack <= 1'b0;
        if (ram_go) begin
            if (v_we) begin
                if (v_sel[0]) ram[ram_addr][7:0]   <= v_dat[7:0];
                if (v_sel[1]) ram[ram_addr][15:8]  <= v_dat[15:8];
                if (v_sel[2]) ram[ram_addr][23:16] <= v_dat[23:16];
                if (v_sel[3]) ram[ram_addr][31:24] <= v_dat[31:24];
            end
            ram_rdata <= ram[ram_addr];
            ram_ack   <= 1'b1;
        end
    end

    // ---- Free-running cycle counter (read-only) ------------------------
    reg [31:0] cycle_ctr;
    always @(posedge clk) begin
        if (rst) cycle_ctr <= 32'h0;
        else     cycle_ctr <= cycle_ctr + 32'h1;
    end

    reg        cyc_ack;
    reg [31:0] cyc_rdata;
    wire       cyc_go = is_cycle & ~cyc_ack;
    always @(posedge clk) begin
        cyc_ack <= 1'b0;
        if (cyc_go) begin
            cyc_rdata <= cycle_ctr;   // writes to this region are ignored
            cyc_ack   <= 1'b1;
        end
    end

    // ---- Decode-error slave (unmapped) ---------------------------------
    reg def_ack;
    wire def_go = is_unmap & ~def_ack;
    always @(posedge clk) def_ack <= def_go;

    // ---- Wishbone -> AXI4 single-beat bridge (peripheral window) -------
    localparam P_IDLE = 3'd0, P_AW = 3'd1, P_W = 3'd2,
               P_B    = 3'd3, P_AR = 3'd4, P_R = 3'd5;
    reg [2:0]  pstate;
    reg [31:0] p_addr, p_wdata, p_rdata;
    reg [3:0]  p_wstrb;
    reg        p_awvalid, p_wvalid, p_bready, p_arvalid, p_rready;
    reg        periph_ack, periph_err;

    wire periph_go = is_periph & (pstate == P_IDLE) & ~periph_ack;

    always @(posedge clk) begin
        if (rst) begin
            pstate     <= P_IDLE;
            p_awvalid  <= 1'b0;
            p_wvalid   <= 1'b0;
            p_bready   <= 1'b0;
            p_arvalid  <= 1'b0;
            p_rready   <= 1'b0;
            periph_ack <= 1'b0;
            periph_err <= 1'b0;
        end else begin
            periph_ack <= 1'b0;   // one-cycle pulse
            case (pstate)
                P_IDLE: begin
                    periph_err <= 1'b0;
                    if (periph_go) begin
                        p_addr  <= {v_adr, 2'b00};
                        p_wdata <= v_dat;
                        p_wstrb <= v_sel;
                        if (v_we) begin
                            p_awvalid <= 1'b1;
                            p_wvalid  <= 1'b1;
                            pstate    <= P_AW;
                        end else begin
                            p_arvalid <= 1'b1;
                            pstate    <= P_AR;
                        end
                    end
                end
                P_AW: begin
                    if (m_axi_awready) p_awvalid <= 1'b0;
                    if (m_axi_wready)  p_wvalid  <= 1'b0;
                    // Advance once both address and data are accepted.
                    if ((~p_awvalid | m_axi_awready) &&
                        (~p_wvalid  | m_axi_wready)) begin
                        p_bready <= 1'b1;
                        pstate   <= P_B;
                    end
                end
                P_W: begin
                    // (unused: AW and W are issued together in P_AW)
                    pstate <= P_B;
                end
                P_B: begin
                    if (m_axi_bvalid) begin
                        p_bready   <= 1'b0;
                        periph_err <= m_axi_bresp[1];
                        periph_ack <= 1'b1;
                        pstate     <= P_IDLE;
                    end
                end
                P_AR: begin
                    if (m_axi_arready) p_arvalid <= 1'b0;
                    if (~p_arvalid | m_axi_arready) begin
                        p_rready <= 1'b1;
                        pstate   <= P_R;
                    end
                end
                P_R: begin
                    if (m_axi_rvalid) begin
                        p_rready   <= 1'b0;
                        p_rdata    <= m_axi_rdata;
                        periph_err <= m_axi_rresp[1];
                        periph_ack <= 1'b1;
                        pstate     <= P_IDLE;
                    end
                end
                default: pstate <= P_IDLE;
            endcase
        end
    end

    // ---- Merge slave responses back onto the arbitrated bus ------------
    assign ack_int = ram_ack | cyc_ack | periph_ack | def_ack;
    wire        err_int = periph_err | def_ack;   // RAM/cycle never error
    wire [31:0] dat_int = ram_ack ? ram_rdata
                        : cyc_ack ? cyc_rdata
                        : p_rdata;

    assign ibus_ack      = busy & ~owner & ack_int;
    assign ibus_err      = busy & ~owner & err_int;
    assign ibus_dat_miso = dat_int;
    assign dbus_ack      = busy &  owner & ack_int;
    assign dbus_err      = busy &  owner & err_int;
    assign dbus_dat_miso = dat_int;

    // ---- AXI4 master outputs (single-beat) -----------------------------
    assign m_axi_awaddr  = p_addr;
    assign m_axi_awlen   = 8'd0;
    assign m_axi_awsize  = 3'b010;   // 4 bytes
    assign m_axi_awburst = 2'b01;    // INCR
    assign m_axi_awprot  = 3'b000;
    assign m_axi_awvalid = p_awvalid;
    assign m_axi_wdata   = p_wdata;
    assign m_axi_wstrb   = p_wstrb;
    assign m_axi_wlast   = 1'b1;
    assign m_axi_wvalid  = p_wvalid;
    assign m_axi_bready  = p_bready;
    assign m_axi_araddr  = p_addr;
    assign m_axi_arlen   = 8'd0;
    assign m_axi_arsize  = 3'b010;
    assign m_axi_arburst = 2'b01;
    assign m_axi_arprot  = 3'b000;
    assign m_axi_arvalid = p_arvalid;
    assign m_axi_rready  = p_rready;

endmodule
