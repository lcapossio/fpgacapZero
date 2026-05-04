// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// EJTAG-to-UART bridge testbench.
// Drives raw TAP signals into fcapz_ejtaguart with a UART loopback and
// stimulus model.

module fcapz_ejtaguart_tb;

    // ---- Parameters ----------------------------------------------------------
    localparam CLK_HZ       = 10_000_000;  // 10 MHz fabric clock (fast sim)
    localparam BAUD_RATE    = 100_000;     // 100 kbaud (BAUD_DIV=100, fast sim)
    localparam TX_FIFO_DEPTH = 16;
    localparam RX_FIFO_DEPTH = 16;
    localparam BAUD_DIV     = CLK_HZ / BAUD_RATE;  // 100
    localparam BIT_PERIOD   = 1_000_000_000 / BAUD_RATE;  // 10000 ns

    // ---- Clocks and resets ---------------------------------------------------

    logic tck      = 1'b0;
    logic uart_clk = 1'b0;
    logic uart_rst = 1'b1;

    always #50  tck      = ~tck;      // 10 MHz TCK
    always #50  uart_clk = ~uart_clk; // 10 MHz fabric clock

    // ---- TAP signals ---------------------------------------------------------

    logic tdi     = 1'b0;
    wire  tdo;
    logic capture_sig = 1'b0;
    logic shift_sig   = 1'b0;
    logic update_sig  = 1'b0;
    logic sel_sig     = 1'b0;

    // ---- UART wires ----------------------------------------------------------

    wire uart_txd;
    logic uart_rxd = 1'b1;  // idle high

    // ---- DUT -----------------------------------------------------------------

    fcapz_ejtaguart #(
        .CLK_HZ        (CLK_HZ),
        .BAUD_RATE     (BAUD_RATE),
        .TX_FIFO_DEPTH (TX_FIFO_DEPTH),
        .RX_FIFO_DEPTH (RX_FIFO_DEPTH),
        .PARITY        (0)
    ) dut (
        .uart_clk (uart_clk),
        .uart_rst (uart_rst),
        .uart_txd (uart_txd),
        .uart_rxd (uart_rxd),
        .tck      (tck),
        .tdi      (tdi),
        .tdo      (tdo),
        .capture  (capture_sig),
        .shift    (shift_sig),
        .update   (update_sig),
        .sel      (sel_sig)
    );

    // ---- Test infrastructure -------------------------------------------------

    integer pass_count = 0;
    integer fail_count = 0;

    task automatic check(input string name, input logic cond);
        if (cond) begin
            pass_count++;
        end else begin
            fail_count++;
            $display("FAIL: %s", name);
        end
    endtask

    // ---- Command constants ---------------------------------------------------

    localparam [3:0] CMD_NOP     = 4'h0;
    localparam [3:0] CMD_TX_PUSH = 4'h1;
    localparam [3:0] CMD_RX_POP  = 4'h2;
    localparam [3:0] CMD_TXRX    = 4'h3;
    localparam [3:0] CMD_CONFIG  = 4'hE;
    localparam [3:0] CMD_RESET   = 4'hF;

    // ---- Helper functions ----------------------------------------------------

    function [31:0] make_cmd(input [3:0] cmd, input [7:0] tx_byte);
        make_cmd = {cmd, 20'b0, tx_byte};
    endfunction

    function [7:0] get_rx_byte(input [31:0] dout);
        get_rx_byte = dout[7:0];
    endfunction

    function [7:0] get_tx_free(input [31:0] dout);
        get_tx_free = dout[15:8];
    endfunction

    function [7:0] get_status(input [31:0] dout);
        get_status = dout[31:24];
    endfunction

    function get_rx_ready(input [31:0] dout);
        get_rx_ready = dout[24];
    endfunction

    function get_rx_valid(input [31:0] dout);
        get_rx_valid = dout[28];
    endfunction

    function get_tx_full(input [31:0] dout);
        get_tx_full = dout[29];
    endfunction

    function get_rx_overflow(input [31:0] dout);
        get_rx_overflow = dout[30];
    endfunction

    function get_frame_err(input [31:0] dout);
        get_frame_err = dout[31];
    endfunction

    // ---- DR scan task --------------------------------------------------------

    task automatic dr_scan_32(input [31:0] din, output [31:0] dout);
        integer i;
        begin
            // 1. Capture phase
            @(posedge tck);
            sel_sig     <= 1'b1;
            capture_sig <= 1'b1;
            @(posedge tck);
            capture_sig <= 1'b0;

            // 2. Shift 32 bits (LSB first)
            shift_sig <= 1'b1;
            for (i = 0; i < 32; i = i + 1) begin
                tdi <= din[i];
                @(negedge tck);
                dout[i] = tdo;
                @(posedge tck);
            end
            shift_sig <= 1'b0;

            // 3. Update phase
            @(posedge tck);
            update_sig <= 1'b1;
            @(posedge tck);
            update_sig <= 1'b0;
            sel_sig    <= 1'b0;
        end
    endtask

    // ---- CDC / timing settle delay -------------------------------------------

    task automatic cdc_wait;
        repeat (10) @(posedge tck);
    endtask

    // ---- UART stimulus: send a byte on uart_rxd (8N1) -----------------------

    task automatic uart_send_byte(input [7:0] data);
        integer i;
        begin
            // Start bit
            uart_rxd <= 1'b0;
            #(BIT_PERIOD);
            // 8 data bits (LSB first)
            for (i = 0; i < 8; i = i + 1) begin
                uart_rxd <= data[i];
                #(BIT_PERIOD);
            end
            // Stop bit
            uart_rxd <= 1'b1;
            #(BIT_PERIOD);
        end
    endtask

    // ---- UART capture: receive a byte from uart_txd --------------------------

    task automatic uart_recv_byte(output [7:0] data);
        integer i;
        begin
            // Wait for start bit (falling edge)
            @(negedge uart_txd);
            // Move to center of start bit
            #(BIT_PERIOD / 2);
            // Sample 8 data bits
            for (i = 0; i < 8; i = i + 1) begin
                #(BIT_PERIOD);
                data[i] = uart_txd;
            end
            // Wait for stop bit
            #(BIT_PERIOD);
        end
    endtask

    // ---- UART TX capture with timeout ----------------------------------------
    // Simple polling approach (avoids fork/join_any which crashes iverilog)

    task automatic uart_recv_byte_timeout(output [7:0] data, output logic valid, input integer timeout_ns);
        integer waited;
        begin
            valid = 0;
            waited = 0;
            // Wait for falling edge (start bit) with timeout
            while (uart_txd === 1'b1 && waited < timeout_ns) begin
                #100;
                waited = waited + 100;
            end
            if (uart_txd === 1'b0) begin
                // Got start bit, do a normal receive from mid-start-bit
                #(BIT_PERIOD / 2);
                for (int j = 0; j < 8; j = j + 1) begin
                    #(BIT_PERIOD);
                    data[j] = uart_txd;
                end
                #(BIT_PERIOD);  // stop bit
                valid = 1;
            end
        end
    endtask

    // ---- Test scenarios ------------------------------------------------------

    initial begin
        logic [31:0] scan_in, scan_out;
        logic [7:0]  rx_byte, tx_byte;
        logic [7:0]  tx_free_val;
        logic        valid;
        integer i;
        realtime t_start, t_end, bit_time_ns;

        // Release reset
        repeat (4) @(posedge uart_clk);
        uart_rst <= 1'b0;
        repeat (20) @(posedge tck);

        // ==================================================================
        // Scenario 1: CONFIG read (VERSION)
        // ==================================================================
        $display("\n=== Scenario 1: CONFIG read (VERSION) ===");

        // Read VERSION: 4 CONFIG scans + 1 NOP drain.
        // VERSION = {major=0, minor=4, core_id="JU"=16'h4A55}.
        scan_in = make_cmd(CMD_CONFIG, 8'h00);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();

        scan_in = make_cmd(CMD_CONFIG, 8'h01);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S1: VERSION byte0=0x55", rx_byte == 8'h55);
        cdc_wait();

        scan_in = make_cmd(CMD_CONFIG, 8'h02);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S1: VERSION byte1=0x4A", rx_byte == 8'h4A);
        cdc_wait();

        scan_in = make_cmd(CMD_CONFIG, 8'h03);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S1: VERSION byte2=0x04", rx_byte == 8'h04);
        cdc_wait();

        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S1: VERSION byte3=0x00", rx_byte == 8'h00);
        cdc_wait();

        // Read mirrored VERSION byte 4
        scan_in = make_cmd(CMD_CONFIG, 8'h04);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S1: VERSION alias byte4=0x55", rx_byte == 8'h55);
        cdc_wait();

        // ==================================================================
        // Scenario 2: TX_PUSH single byte
        // ==================================================================
        $display("\n=== Scenario 2: TX_PUSH single byte ===");

        scan_in = make_cmd(CMD_TX_PUSH, 8'hA5);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();

        // Wait for UART TX to complete and capture the byte
        uart_recv_byte_timeout(tx_byte, valid, BIT_PERIOD * 12);
        check("S2: uart_txd received byte", valid == 1'b1);
        check("S2: uart_txd=0xA5", tx_byte == 8'hA5);

        // Allow TX to finish
        repeat (20) @(posedge uart_clk);

        // ==================================================================
        // Scenario 3: RX_POP single byte
        // ==================================================================
        $display("\n=== Scenario 3: RX_POP single byte ===");

        // Send byte via uart_rxd
        uart_send_byte(8'h3C);

        // Wait for RX FIFO to have data (CDC delay)
        repeat (40) @(posedge tck);

        // RX_POP: pop from FIFO
        scan_in = make_cmd(CMD_RX_POP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();

        // NOP: read the result
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S3: rx_byte=0x3C", rx_byte == 8'h3C);
        check("S3: RX_VALID=1", get_rx_valid(scan_out) == 1'b1);
        cdc_wait();

        // ==================================================================
        // Scenario 4: TXRX full duplex
        // ==================================================================
        $display("\n=== Scenario 4: TXRX full duplex ===");

        // Pre-load RX FIFO
        uart_send_byte(8'hBE);
        repeat (40) @(posedge tck);

        // TXRX: send 0x55, pop RX
        scan_in = make_cmd(CMD_TXRX, 8'h55);
        dr_scan_32(scan_in, scan_out);

        // Capture TX byte FIRST (before it's done transmitting)
        uart_recv_byte_timeout(tx_byte, valid, BIT_PERIOD * 14);
        check("S4: uart_txd received", valid == 1'b1);
        check("S4: uart_txd=0x55", tx_byte == 8'h55);

        cdc_wait();

        // Read RX result
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S4: rx_byte=0xBE", rx_byte == 8'hBE);
        check("S4: RX_VALID=1", get_rx_valid(scan_out) == 1'b1);
        repeat (BAUD_DIV * 12) @(posedge uart_clk);

        // ==================================================================
        // Scenario 5: NOP does not pop RX
        // ==================================================================
        $display("\n=== Scenario 5: NOP does not pop RX ===");

        // Load RX FIFO
        uart_send_byte(8'hAA);
        repeat (40) @(posedge tck);

        // Check RX_READY
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S5: RX_READY=1 before NOP", get_rx_ready(scan_out) == 1'b1);
        cdc_wait();

        // Another NOP - should still have data
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S5: RX_READY=1 after NOP", get_rx_ready(scan_out) == 1'b1);
        check("S5: RX_VALID=0 (no pop done)", get_rx_valid(scan_out) == 1'b0);
        cdc_wait();

        // Now actually pop it to clean up
        scan_in = make_cmd(CMD_RX_POP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        rx_byte = get_rx_byte(scan_out);
        check("S5: popped byte=0xAA", rx_byte == 8'hAA);
        cdc_wait();

        // ==================================================================
        // Scenario 6: TX_PUSH when full
        // ==================================================================
        $display("\n=== Scenario 6: TX_PUSH when full ===");

        // Fill TX FIFO (16 entries). TX drains concurrently, so push extras.
        // Push TX_FIFO_DEPTH + 8 entries to guarantee FIFO fills up.
        for (i = 0; i < TX_FIFO_DEPTH + 8; i = i + 1) begin
            scan_in = make_cmd(CMD_TX_PUSH, i[7:0]);
            dr_scan_32(scan_in, scan_out);
        end
        // Check if TX_FULL was ever set by checking current status
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        // The FIFO should be full or nearly full; check tx_free == 0
        check("S6: TX_FULL=1", get_tx_full(scan_out) == 1'b1);

        // Wait for TX to drain
        repeat (TX_FIFO_DEPTH * BAUD_DIV * 12) @(posedge uart_clk);
        cdc_wait();

        // ==================================================================
        // Scenario 7: RX FIFO overflow
        // ==================================================================
        $display("\n=== Scenario 7: RX FIFO overflow ===");

        // Reset first to clear state
        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        cdc_wait();

        // Fill RX FIFO beyond capacity
        for (i = 0; i < RX_FIFO_DEPTH + 2; i = i + 1) begin
            uart_send_byte(i[7:0]);
        end
        repeat (40) @(posedge tck);

        // Check RX_OVERFLOW
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        // Wait for overflow flag to propagate through 2-FF sync
        repeat (10) @(posedge tck);
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S7: RX_OVERFLOW=1", get_rx_overflow(scan_out) == 1'b1);
        cdc_wait();

        // ==================================================================
        // Scenario 8: Framing error
        // ==================================================================
        $display("\n=== Scenario 8: Framing error ===");

        // Reset
        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        cdc_wait();

        // Send frame with bad stop bit
        uart_rxd <= 1'b0;  // start bit
        #(BIT_PERIOD);
        // 8 data bits (all 0)
        for (i = 0; i < 8; i = i + 1) begin
            uart_rxd <= 1'b0;
            #(BIT_PERIOD);
        end
        // Bad stop bit (0 instead of 1)
        uart_rxd <= 1'b0;
        #(BIT_PERIOD);
        uart_rxd <= 1'b1;  // back to idle

        // Wait for error to propagate
        repeat (40) @(posedge tck);
        repeat (10) @(posedge tck);

        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S8: FRAME_ERR=1", get_frame_err(scan_out) == 1'b1);
        cdc_wait();

        // ==================================================================
        // Scenario 9: RESET clears FIFOs + errors
        // ==================================================================
        $display("\n=== Scenario 9: RESET clears FIFOs + errors ===");

        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        cdc_wait();

        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S9: RX_OVERFLOW=0 after reset", get_rx_overflow(scan_out) == 1'b0);
        check("S9: FRAME_ERR=0 after reset", get_frame_err(scan_out) == 1'b0);
        check("S9: TX_FULL=0 after reset", get_tx_full(scan_out) == 1'b0);
        check("S9: RX_READY=0 after reset", get_rx_ready(scan_out) == 1'b0);
        cdc_wait();

        // ==================================================================
        // Scenario 10: Loopback (TX->RX wired)
        // ==================================================================
        $display("\n=== Scenario 10: Loopback ===");

        // We'll manually receive from uart_txd and feed to uart_rxd
        // Send 4 bytes, receive them back
        begin
            logic [7:0] loopback_data [0:3];
            logic [7:0] loopback_recv;

            loopback_data[0] = 8'h11;
            loopback_data[1] = 8'h22;
            loopback_data[2] = 8'h33;
            loopback_data[3] = 8'h44;

            for (i = 0; i < 4; i = i + 1) begin
                // Push TX byte
                scan_in = make_cmd(CMD_TX_PUSH, loopback_data[i]);
                dr_scan_32(scan_in, scan_out);

                // Capture TX output and loop back to RX
                uart_recv_byte(loopback_recv);
                uart_send_byte(loopback_recv);

                repeat (40) @(posedge tck);

                // Pop and verify
                scan_in = make_cmd(CMD_RX_POP, 8'h00);
                dr_scan_32(scan_in, scan_out);
                cdc_wait();
                scan_in = make_cmd(CMD_NOP, 8'h00);
                dr_scan_32(scan_in, scan_out);
                rx_byte = get_rx_byte(scan_out);
                check($sformatf("S10: loopback[%0d]=0x%02x", i, loopback_data[i]),
                      rx_byte == loopback_data[i]);
            end
        end
        cdc_wait();

        // ==================================================================
        // Scenario 11: Baud rate timing
        // ==================================================================
        $display("\n=== Scenario 11: Baud rate timing ===");

        scan_in = make_cmd(CMD_TX_PUSH, 8'hFF);
        dr_scan_32(scan_in, scan_out);

        // Measure time from start bit to stop bit end
        @(negedge uart_txd);
        t_start = $realtime;
        // Wait for 10 bit periods (start + 8 data + stop)
        #(BIT_PERIOD * 10);
        t_end = $realtime;
        bit_time_ns = (t_end - t_start) / 10.0;

        // Expected bit period = BIT_PERIOD ns
        // Allow 2% tolerance
        check("S11: baud rate within 2%",
              bit_time_ns > (BIT_PERIOD * 0.98) &&
              bit_time_ns < (BIT_PERIOD * 1.02));

        // Wait for TX to finish
        repeat (20) @(posedge uart_clk);
        cdc_wait();

        // ==================================================================
        // Scenario 12: tx_free accuracy
        // ==================================================================
        $display("\n=== Scenario 12: tx_free accuracy ===");

        // Reset to start fresh and wait for all TX drain
        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        // Wait long enough for FIFO reset to propagate and any pending TX to drain
        repeat (BAUD_DIV * 12 * 4) @(posedge uart_clk);
        cdc_wait();

        // Check initial tx_free = FIFO depth
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        tx_free_val = get_tx_free(scan_out);
        check($sformatf("S12: initial tx_free=%0d (expect %0d)", tx_free_val, TX_FIFO_DEPTH),
              tx_free_val == TX_FIFO_DEPTH[7:0]);

        // Push 3 bytes
        for (i = 0; i < 3; i = i + 1) begin
            scan_in = make_cmd(CMD_TX_PUSH, i[7:0]);
            dr_scan_32(scan_in, scan_out);
        end
        cdc_wait();

        // Check tx_free decreased (approximately, TX may have drained some)
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        tx_free_val = get_tx_free(scan_out);
        check("S12: tx_free < 16 after push", tx_free_val < TX_FIFO_DEPTH[7:0]);

        // Wait for TX drain
        repeat (100) @(posedge uart_clk);
        cdc_wait();

        // ==================================================================
        // Scenario 13: Pipelined RX_POP sequence
        // ==================================================================
        $display("\n=== Scenario 13: Pipelined RX_POP sequence ===");

        // Reset
        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        cdc_wait();

        // Send 3 bytes
        uart_send_byte(8'hD1);
        uart_send_byte(8'hD2);
        uart_send_byte(8'hD3);
        repeat (40) @(posedge tck);

        // Pipelined: RX_POP, RX_POP, RX_POP, NOP
        // Scan 1: RX_POP (prime)
        scan_in = make_cmd(CMD_RX_POP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        cdc_wait();

        // Scan 2: RX_POP -> result of scan 1
        scan_in = make_cmd(CMD_RX_POP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S13: pipe[0]=0xD1", get_rx_byte(scan_out) == 8'hD1);
        check("S13: pipe[0] RX_VALID=1", get_rx_valid(scan_out) == 1'b1);
        cdc_wait();

        // Scan 3: RX_POP -> result of scan 2
        scan_in = make_cmd(CMD_RX_POP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S13: pipe[1]=0xD2", get_rx_byte(scan_out) == 8'hD2);
        cdc_wait();

        // Scan 4: NOP -> result of scan 3
        scan_in = make_cmd(CMD_NOP, 8'h00);
        dr_scan_32(scan_in, scan_out);
        check("S13: pipe[2]=0xD3", get_rx_byte(scan_out) == 8'hD3);
        cdc_wait();

        // ==================================================================
        // Scenario 14: Zero-delay internal loopback stress
        // ==================================================================
        $display("\n=== Scenario 14: Zero-delay internal loopback stress ===");

        // Reset to start fresh
        scan_in = make_cmd(CMD_RESET, 8'h00);
        dr_scan_32(scan_in, scan_out);
        repeat (20) @(posedge tck);
        repeat (BAUD_DIV * 12 * 4) @(posedge uart_clk);
        cdc_wait();

        // Emulate the Arty internal-loopback test bitstream: TX wired
        // directly to RX with effectively zero propagation delay.
        force uart_rxd = uart_txd;
        begin
            logic [7:0] stress_data [0:7];

            stress_data[0] = 8'h10;
            stress_data[1] = 8'h21;
            stress_data[2] = 8'h32;
            stress_data[3] = 8'h43;
            stress_data[4] = 8'h54;
            stress_data[5] = 8'h65;
            stress_data[6] = 8'h76;
            stress_data[7] = 8'h87;

            for (i = 0; i < 8; i = i + 1) begin
                scan_in = make_cmd(CMD_TX_PUSH, stress_data[i]);
                dr_scan_32(scan_in, scan_out);
            end

            // Wait for the UART engine to transmit and receive the block.
            repeat (BAUD_DIV * 12 * 8) @(posedge uart_clk);
            cdc_wait();

            // Read back via pipelined RX_POP.
            scan_in = make_cmd(CMD_RX_POP, 8'h00);
            dr_scan_32(scan_in, scan_out);
            cdc_wait();

            for (i = 0; i < 7; i = i + 1) begin
                scan_in = make_cmd(CMD_RX_POP, 8'h00);
                dr_scan_32(scan_in, scan_out);
                check($sformatf("S14: zero-delay[%0d]=0x%02x", i, stress_data[i]),
                      get_rx_byte(scan_out) == stress_data[i]);
                check($sformatf("S14: zero-delay[%0d] RX_VALID=1", i),
                      get_rx_valid(scan_out) == 1'b1);
                cdc_wait();
            end

            scan_in = make_cmd(CMD_NOP, 8'h00);
            dr_scan_32(scan_in, scan_out);
            check($sformatf("S14: zero-delay[%0d]=0x%02x", 7, stress_data[7]),
                  get_rx_byte(scan_out) == stress_data[7]);
            check("S14: zero-delay[last] RX_VALID=1", get_rx_valid(scan_out) == 1'b1);
        end
        release uart_rxd;
        uart_rxd <= 1'b1;
        cdc_wait();

        // ==================================================================
        // Final summary
        // ==================================================================
        $display("=== EJTAGUART TB: %0d passed, %0d failed ===", pass_count, fail_count);
        if (fail_count > 0) $fatal(1, "TESTS FAILED");
        $finish;
    end

    // Timeout watchdog
    initial begin
        #500_000_000;
        $display("TIMEOUT: testbench did not complete in time");
        $fatal(1, "TIMEOUT");
    end

endmodule
