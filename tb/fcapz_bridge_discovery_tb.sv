// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Core discovery against the EJTAG bridges.
//
// fcapz.discovery identifies a chain by reading register-protocol addresses
// below 0x2000 (49-bit frames {wr, addr[15:0], data[31:0]}).  On the
// EJTAG-AXI bridge (72-bit DR) and the EJTAG-UART bridge (32-bit DR) the top
// four frame bits, {wr, addr[15:13]}, land in the command field, so those
// reads are NOPs.  A chain that answers neither "LA" nor "IO" then gets the
// UART's 32-bit identity reads, which on the AXI bridge are CONFIG reads.
//
// This bench shifts exactly those scans into both bridges and checks that no
// AXI transaction, command-queue entry, UART push or UART pop happens, and
// that a byte waiting in the UART's RX FIFO is still delivered afterwards.
// Controls show the counters see a real command: a read of 0x8000 is
// READ_INC on the AXI bridge and a read of 0x2000 is TX_PUSH on the UART.

module fcapz_bridge_discovery_tb;

    localparam CLK_HZ     = 10_000_000;
    localparam BAUD_RATE  = 100_000;
    localparam BIT_PERIOD = 1_000_000_000 / BAUD_RATE;

    logic tck      = 1'b0;
    logic axi_clk  = 1'b0;
    logic uart_clk = 1'b0;
    logic axi_rst  = 1'b1;
    logic uart_rst = 1'b1;

    always #50 tck      = ~tck;
    always #15 axi_clk  = ~axi_clk;
    always #50 uart_clk = ~uart_clk;

    logic tdi      = 1'b0;
    logic capture  = 1'b0;
    logic shift_en = 1'b0;
    logic update   = 1'b0;
    logic sel_axi  = 1'b0;
    logic sel_uart = 1'b0;
    wire  tdo_axi;
    wire  tdo_uart;

    // ---- EJTAG-AXI bridge + slave ---------------------------------------------

    wire [31:0] awaddr, wdata, araddr, rdata;
    wire [7:0]  awlen, arlen;
    wire [2:0]  awsize, arsize, awprot, arprot;
    wire [1:0]  awburst, arburst, bresp, rresp;
    wire [3:0]  wstrb;
    wire awvalid, awready, wvalid, wready, wlast, bvalid, bready;
    wire arvalid, arready, rvalid, rlast, rready;

    fcapz_ejtagaxi #(
        .ADDR_W     (32),
        .DATA_W     (32),
        .FIFO_DEPTH (16),
        .TIMEOUT    (4096)
    ) dut_axi (
        .tck (tck), .tdi (tdi), .tdo (tdo_axi),
        .capture (capture), .shift_en (shift_en), .update (update), .sel (sel_axi),
        .axi_clk (axi_clk), .axi_rst (axi_rst),
        .m_axi_awaddr (awaddr), .m_axi_awlen (awlen), .m_axi_awsize (awsize),
        .m_axi_awburst (awburst), .m_axi_awvalid (awvalid), .m_axi_awready (awready),
        .m_axi_awprot (awprot),
        .m_axi_wdata (wdata), .m_axi_wstrb (wstrb), .m_axi_wvalid (wvalid),
        .m_axi_wready (wready), .m_axi_wlast (wlast),
        .m_axi_bresp (bresp), .m_axi_bvalid (bvalid), .m_axi_bready (bready),
        .m_axi_araddr (araddr), .m_axi_arlen (arlen), .m_axi_arsize (arsize),
        .m_axi_arburst (arburst), .m_axi_arvalid (arvalid), .m_axi_arready (arready),
        .m_axi_arprot (arprot),
        .m_axi_rdata (rdata), .m_axi_rresp (rresp), .m_axi_rvalid (rvalid),
        .m_axi_rlast (rlast), .m_axi_rready (rready)
    );

    axi4_test_slave #(
        .ADDR_W    (32),
        .DATA_W    (32),
        .NUM_WORDS (16)
    ) slave (
        .clk (axi_clk), .rst (axi_rst),
        .s_axi_awaddr (awaddr), .s_axi_awlen (awlen), .s_axi_awsize (awsize),
        .s_axi_awburst (awburst), .s_axi_awvalid (awvalid), .s_axi_awready (awready),
        .s_axi_wdata (wdata), .s_axi_wstrb (wstrb), .s_axi_wlast (wlast),
        .s_axi_wvalid (wvalid), .s_axi_wready (wready),
        .s_axi_bresp (bresp), .s_axi_bvalid (bvalid), .s_axi_bready (bready),
        .s_axi_araddr (araddr), .s_axi_arlen (arlen), .s_axi_arsize (arsize),
        .s_axi_arburst (arburst), .s_axi_arvalid (arvalid), .s_axi_arready (arready),
        .s_axi_rdata (rdata), .s_axi_rresp (rresp), .s_axi_rlast (rlast),
        .s_axi_rvalid (rvalid), .s_axi_rready (rready)
    );

    // ---- EJTAG-UART bridge -----------------------------------------------------

    wire  uart_txd;
    logic uart_rxd = 1'b1;

    fcapz_ejtaguart #(
        .CLK_HZ        (CLK_HZ),
        .BAUD_RATE     (BAUD_RATE),
        .TX_FIFO_DEPTH (16),
        .RX_FIFO_DEPTH (16),
        .PARITY        (0)
    ) dut_uart (
        .uart_clk (uart_clk), .uart_rst (uart_rst),
        .uart_txd (uart_txd), .uart_rxd (uart_rxd),
        .tck (tck), .tdi (tdi), .tdo (tdo_uart),
        .capture (capture), .shift (shift_en), .update (update), .sel (sel_uart)
    );

    // ---- Activity counters -----------------------------------------------------

    integer axi_aw = 0, axi_ar = 0, axi_cmdq = 0, axi_resets = 0;
    integer uart_push = 0, uart_pop = 0, uart_resets = 0;

    always @(posedge axi_clk) begin
        if (awvalid && awready) axi_aw = axi_aw + 1;
        if (arvalid && arready) axi_ar = axi_ar + 1;
    end

    always @(posedge tck) begin
        if (dut_axi.cmdq_wr_en) axi_cmdq = axi_cmdq + 1;
        if (dut_axi.fifo_rst_tck || dut_axi.cmdq_rst_tck) axi_resets = axi_resets + 1;
        if (dut_uart.tx_wr_pulse) uart_push = uart_push + 1;
        if (dut_uart.rx_rd_pulse) uart_pop = uart_pop + 1;
        if (dut_uart.fifo_rst && dut_uart.fifo_rst_cnt == 3'd4) uart_resets = uart_resets + 1;
    end

    integer pass_count = 0;
    integer fail_count = 0;

    task automatic check(input string name, input logic cond);
        if (cond) pass_count++;
        else begin
            fail_count++;
            $display("FAIL: %s", name);
        end
    endtask

    // ---- Scans ---------------------------------------------------------------

    // One DR scan of n bits (LSB first) into the selected bridge.
    task automatic scan(input logic to_axi, input integer n, input logic [127:0] din,
                        output logic [127:0] dout);
        integer i;
        begin
            dout = '0;
            @(posedge tck);
            sel_axi  <= to_axi;
            sel_uart <= !to_axi;
            capture  <= 1'b1;
            @(posedge tck);
            capture  <= 1'b0;
            shift_en <= 1'b1;
            for (i = 0; i < n; i = i + 1) begin
                tdi <= din[i];
                @(negedge tck);
                dout[i] = to_axi ? tdo_axi : tdo_uart;
                @(posedge tck);
            end
            shift_en <= 1'b0;
            @(posedge tck);
            update <= 1'b1;
            @(posedge tck);
            update   <= 1'b0;
            sel_axi  <= 1'b0;
            sel_uart <= 1'b0;
        end
    endtask

    function automatic [48:0] reg_read(input [15:0] addr);
        reg_read = {1'b0, addr, 32'h0};
    endfunction

    // The register reads discovery and Analyzer.probe_optional() send to a
    // chain nobody has identified: VERSION and the probe registers.  Each
    // read is a request scan then a collect scan.
    localparam integer N_ADDRS = 11;

    function automatic [15:0] probe_addr(input integer k);
        case (k)
            0: probe_addr = 16'h0000;   // VERSION
            1: probe_addr = 16'h000C;   // SAMPLE_W
            2: probe_addr = 16'h0010;   // DEPTH
            3: probe_addr = 16'h00A4;   // NUM_CHAN
            4: probe_addr = 16'h003C;   // FEATURES
            5: probe_addr = 16'h00C4;   // TIMESTAMP_W
            6: probe_addr = 16'h00B8;   // NUM_SEGMENTS
            7: probe_addr = 16'h00D0;   // PROBE_MUX_W
            8: probe_addr = 16'h00E0;   // COMPARE_CAPS
            9: probe_addr = 16'h0008;   // EIO OUT_W
            default: probe_addr = 16'h1FFC;  // the highest safe address
        endcase
    endfunction

    task automatic discovery_reads(input logic to_axi);
        logic [127:0] dout;
        integer k;
        begin
            for (k = 0; k < N_ADDRS; k = k + 1) begin
                scan(to_axi, 49, {79'd0, reg_read(probe_addr(k))}, dout);
                scan(to_axi, 49, {79'd0, reg_read(16'h0000)}, dout);
            end
        end
    endtask

    // EjtagUartController.attach() on a chain that is not a UART: CONFIG
    // reads of 0x00..0x03, a NOP, two more NOPs, then the same again.
    task automatic uart_identity_reads(input logic to_axi);
        logic [127:0] dout;
        integer pass, b;
        begin
            for (pass = 0; pass < 2; pass = pass + 1) begin
                for (b = 0; b < 4; b = b + 1)
                    scan(to_axi, 32, {96'd0, 4'hE, 20'd0, 8'(b)}, dout);
                scan(to_axi, 32, 128'd0, dout);
                if (pass == 0) begin
                    scan(to_axi, 32, 128'd0, dout);
                    scan(to_axi, 32, 128'd0, dout);
                end
            end
        end
    endtask

    task automatic uart_send_byte(input [7:0] data);
        integer i;
        begin
            uart_rxd <= 1'b0;
            #(BIT_PERIOD);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rxd <= data[i];
                #(BIT_PERIOD);
            end
            uart_rxd <= 1'b1;
            #(BIT_PERIOD);
        end
    endtask

    initial begin
        logic [127:0] dout;
        integer ar_before;
        integer push_before;

        repeat (4) @(posedge axi_clk);
        axi_rst  <= 1'b0;
        uart_rst <= 1'b0;
        repeat (20) @(posedge tck);

        // A byte waits in the UART RX FIFO, as one would on a live console.
        uart_send_byte(8'h3C);
        repeat (50) @(posedge tck);

        // ---- Discovery scans -------------------------------------------------
        discovery_reads(1'b1);
        discovery_reads(1'b0);
        uart_identity_reads(1'b1);
        repeat (200) @(posedge axi_clk);

        check("AXI: no write address handshake", axi_aw == 0);
        check("AXI: no read address handshake", axi_ar == 0);
        check("AXI: no command queued", axi_cmdq == 0);
        check("AXI: no reset", axi_resets == 0);
        check("AXI: nothing pending", dut_axi.pending_count == 0);
        check("AXI: no sticky error", dut_axi.error_sticky == 1'b0);
        check("UART: no TX push", uart_push == 0);
        check("UART: no RX pop", uart_pop == 0);
        check("UART: no FIFO reset", uart_resets == 0);
        check("UART: line stayed idle", uart_txd === 1'b1);

        // The waiting byte is still there: pop it and read it out.
        scan(1'b0, 32, {96'd0, 4'h2, 28'd0}, dout);
        scan(1'b0, 32, 128'd0, dout);
        check("UART: RX byte survives discovery", dout[7:0] == 8'h3C && dout[28]);

        // ---- Controls: the counters see a real command ----------------------
        ar_before = axi_ar;
        scan(1'b1, 49, {79'd0, reg_read(16'h8000)}, dout);   // READ_INC
        repeat (200) @(posedge axi_clk);
        check("control: a read of 0x8000 is an AXI read", axi_ar == ar_before + 1);

        push_before = uart_push;
        scan(1'b0, 49, {79'd0, reg_read(16'h2000)}, dout);   // TX_PUSH
        repeat (5) @(posedge tck);
        check("control: a read of 0x2000 is a UART push", uart_push == push_before + 1);

        $display("BRIDGE DISCOVERY TB: %0d passed, %0d failed", pass_count, fail_count);
        if (fail_count == 0) $display("PASS: bridge discovery");
        if (fail_count > 0) $fatal(1, "TESTS FAILED");
        $finish;
    end

    initial begin
        #50_000_000;
        $fatal(1, "timeout");
    end

endmodule
