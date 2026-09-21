// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// UART virtual-TAP testbench.
//
// Drives fcapz_uart_tap from a behavioural 8N1 host UART and checks that the
// TAP contract it synthesises is good enough to run the *real* jtag_reg_iface
// behind it: identity, register write, register read-back, the 256-bit burst
// width, and the two error paths that must not desynchronise the link.

module fcapz_uart_tap_tb;

    localparam int CLK_HZ      = 50_000_000;
    localparam int BAUD        = 1_000_000;
    localparam int BIT_NS      = 1_000_000_000 / BAUD;
    localparam int NCH         = 4;
    localparam int MAX_DR_BITS = 256;

    logic clk  = 1'b0;
    logic arst = 1'b1;
    always #10 clk = ~clk;              // 50 MHz

    logic host_tx = 1'b1;
    wire  dut_tx;

    wire            tck, tdi, capture, shift, update;
    wire [NCH-1:0]  sel;
    wire [NCH-1:0]  tdo;

    int pass_count = 0;
    int fail_count = 0;

    task automatic check(input string name, input bit cond);
        if (cond) begin
            pass_count++;
            $display("  PASS: %s", name);
        end else begin
            fail_count++;
            $display("  FAIL: %s", name);
        end
    endtask

    // ------------------------------------------------------------------
    //  DUT + a real jtag_reg_iface on chain 1
    // ------------------------------------------------------------------
    fcapz_uart_tap #(
        .CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD),
        .NUM_CHAINS(NCH), .MAX_DR_BITS(MAX_DR_BITS)
    ) dut (
        .clk(clk), .arst(arst),
        .uart_rxd(host_tx), .uart_txd(dut_tx),
        .tck(tck), .tdi(tdi), .tdo(tdo),
        .capture(capture), .shift(shift), .update(update), .sel(sel)
    );

    wire        reg_clk, reg_rst, reg_wr_en, reg_rd_en;
    wire [15:0] reg_addr;
    wire [31:0] reg_wdata;
    logic [31:0] reg_rdata;

    jtag_reg_iface u_reg (
        .arst(arst),
        .tck(tck), .tdi(tdi), .tdo(tdo[0]),
        .capture(capture), .shift_en(shift), .update(update), .sel(sel[0]),
        .reg_clk(reg_clk), .reg_rst(reg_rst),
        .reg_wr_en(reg_wr_en), .reg_rd_en(reg_rd_en),
        .reg_addr(reg_addr), .reg_wdata(reg_wdata), .reg_rdata(reg_rdata)
    );

    // Chain 2 is a plain 256-bit shift register, standing in for the burst
    // readout chain: whatever is shifted in comes back out one scan later.
    logic [MAX_DR_BITS-1:0] burst_sr;
    assign tdo[1] = burst_sr[0];
    assign tdo[3:2] = 2'b00;

    always_ff @(posedge tck or posedge arst) begin
        if (arst)            burst_sr <= '0;
        else if (sel[1] && shift) burst_sr <= {tdi, burst_sr[MAX_DR_BITS-1:1]};
    end

    logic [31:0] mem [0:15];
    always_ff @(posedge reg_clk) if (reg_wr_en) mem[reg_addr[5:2]] <= reg_wdata;
    always @(*) reg_rdata = mem[reg_addr[5:2]];

    // ------------------------------------------------------------------
    //  Behavioural host UART
    // ------------------------------------------------------------------
    task automatic send_byte(input logic [7:0] b);
        host_tx = 1'b0; #(BIT_NS);
        for (int i = 0; i < 8; i++) begin host_tx = b[i]; #(BIT_NS); end
        host_tx = 1'b1; #(BIT_NS);
    endtask

    logic [7:0] rxbuf [0:63];
    int         rxn = 0;

    initial forever begin
        logic [7:0] b;
        @(negedge dut_tx);
        #(BIT_NS/2);
        for (int i = 0; i < 8; i++) begin #(BIT_NS); b[i] = dut_tx; end
        #(BIT_NS);
        rxbuf[rxn] = b;
        rxn++;
    end

    task automatic send_scan(input logic [7:0] chain,
                             input logic [15:0] width,
                             input logic [MAX_DR_BITS-1:0] payload);
        int nb = (width + 7) / 8;
        send_byte(8'h5A);
        send_byte(8'h01);
        send_byte(chain);
        send_byte(width[7:0]);
        send_byte(width[15:8]);
        for (int i = 0; i < nb; i++) send_byte(payload[i*8 +: 8]);
    endtask

    // Wait for a reply of n bytes, with a bounded timeout so a desynchronised
    // link fails loudly instead of hanging the run.
    task automatic await_reply(input int n, input string what);
        // Poll rather than wait(): a desynchronised link must fail loudly
        // instead of hanging the run.  Budget ~40 bit times per expected byte.
        int guard = n * 40 + 400;
        while (rxn < n && guard > 0) begin
            #(BIT_NS);
            guard--;
        end
        if (rxn < n) begin
            $display("  FAIL: %s timed out (rxn=%0d of %0d)", what, rxn, n);
            fail_count++;
        end else begin
            #(BIT_NS);
        end
    endtask

    logic [48:0] frame;
    logic [31:0] got;
    logic [MAX_DR_BITS-1:0] burst_payload, burst_got;

    initial begin
        for (int k = 0; k < 16; k++) mem[k] = 32'h0;
        #200 arst = 1'b0;
        #2000;

        // ---- Test 1: CMD_INFO identity -------------------------------------
        $display("\n=== Test 1: CMD_INFO ===");
        rxn = 0;
        send_byte(8'h5A); send_byte(8'h03);
        await_reply(10, "info");
        check("SOF",        rxbuf[0] == 8'hA5);
        check("status OK",  rxbuf[1] == 8'h00);
        check("magic FCZU", {rxbuf[5],rxbuf[4],rxbuf[3],rxbuf[2]} == 32'h555A4346);
        check("version",    rxbuf[6] == 8'h01);
        check("num chains", rxbuf[7] == NCH);
        check("max dr",     {rxbuf[9],rxbuf[8]} == MAX_DR_BITS);

        // ---- Test 2: register write ----------------------------------------
        $display("\n=== Test 2: register write ===");
        frame = {1'b1, 16'h0010, 32'hDEADBEEF};
        rxn = 0;
        send_scan(8'd1, 16'd49, {{(MAX_DR_BITS-49){1'b0}}, frame});
        await_reply(9, "write");
        check("status OK", rxbuf[1] == 8'h00);
        // Must land on this scan, not the next one: jtag_reg_iface registers
        // reg_wr_en on the update edge, so the TAP owes it trailing clocks.
        check("write landed on this scan", mem[4] == 32'hDEADBEEF);

        // ---- Test 3: register read-back ------------------------------------
        $display("\n=== Test 3: register read-back ===");
        frame = {1'b0, 16'h0010, 32'h0};
        rxn = 0;
        send_scan(8'd1, 16'd49, {{(MAX_DR_BITS-49){1'b0}}, frame});
        await_reply(9, "read addr");

        rxn = 0;                                  // runtest between the halves
        send_byte(8'h5A); send_byte(8'h02); send_byte(8'd8); send_byte(8'd0);
        await_reply(2, "idle");
        check("idle status OK", rxbuf[1] == 8'h00);

        rxn = 0;
        send_scan(8'd1, 16'd49, {{(MAX_DR_BITS-49){1'b0}}, frame});
        await_reply(9, "read data");
        got = {rxbuf[5], rxbuf[4], rxbuf[3], rxbuf[2]};
        check("read-back value", got == 32'hDEADBEEF);

        // ---- Test 4: 256-bit burst width -----------------------------------
        $display("\n=== Test 4: 256-bit burst scan ===");
        burst_payload = {8'hC5, 120'h0, 8'h3C, 112'h0, 8'hA5};
        rxn = 0;                                  // first scan loads the SR
        send_scan(8'd2, 16'd256, burst_payload);
        await_reply(2 + 32, "burst load");
        rxn = 0;                                  // second shifts it back out
        send_scan(8'd2, 16'd256, '0);
        await_reply(2 + 32, "burst read");
        for (int i = 0; i < 32; i++) burst_got[i*8 +: 8] = rxbuf[2 + i];
        check("burst round-trip", burst_got == burst_payload);

        // ---- Test 5: bad chain is reported, link stays in sync -------------
        $display("\n=== Test 5: bad chain ===");
        rxn = 0;
        send_scan(8'd9, 16'd49, {{(MAX_DR_BITS-49){1'b0}}, frame});
        await_reply(2, "bad chain");
        check("bad chain status", rxbuf[1] == 8'h02);

        // ---- Test 6: bad width must not deadlock ---------------------------
        // A zero width implies a zero-byte payload; the parser must not sit
        // waiting for a byte the host will never send.
        $display("\n=== Test 6: bad width ===");
        rxn = 0;
        send_byte(8'h5A); send_byte(8'h01); send_byte(8'd1);
        send_byte(8'h00); send_byte(8'h00);
        await_reply(2, "bad width");
        check("bad width status", rxbuf[1] == 8'h03);

        // ---- Test 7: still usable after the error paths --------------------
        $display("\n=== Test 7: recovery after errors ===");
        frame = {1'b1, 16'h0014, 32'hCAFEF00D};
        rxn = 0;
        send_scan(8'd1, 16'd49, {{(MAX_DR_BITS-49){1'b0}}, frame});
        await_reply(9, "recovery write");
        check("write after errors", mem[5] == 32'hCAFEF00D);

        $display("\n=== Summary: %0d passed, %0d failed ===",
                 pass_count, fail_count);
        if (fail_count > 0)
            $fatal(1, "UART TAP testbench: failures detected");
        $finish;
    end

    initial begin
        #20_000_000;
        $fatal(1, "UART TAP testbench: global timeout");
    end

endmodule
