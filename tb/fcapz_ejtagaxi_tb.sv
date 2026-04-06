// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// EJTAG-to-AXI4 bridge testbench.
// Drives raw TAP signals into fcapz_ejtagaxi with an axi4_test_slave backend.

module fcapz_ejtagaxi_tb;

    // ---- Clocks and resets ---------------------------------------------------

    logic tck     = 1'b0;
    logic axi_clk = 1'b0;
    logic axi_rst = 1'b1;

    always #50  tck     = ~tck;     // 10 MHz
    always #15  axi_clk = ~axi_clk; // ~33.33 MHz

    // ---- TAP signals ---------------------------------------------------------

    logic tdi      = 1'b0;
    wire  tdo;
    logic capture  = 1'b0;
    logic shift_en = 1'b0;
    logic update   = 1'b0;
    logic sel      = 1'b0;

    // ---- AXI4 wires ----------------------------------------------------------

    wire [31:0] m_axi_awaddr;
    wire [7:0]  m_axi_awlen;
    wire [2:0]  m_axi_awsize;
    wire [1:0]  m_axi_awburst;
    wire        m_axi_awvalid;
    wire        m_axi_awready;
    wire [2:0]  m_axi_awprot;

    wire [31:0] m_axi_wdata;
    wire [3:0]  m_axi_wstrb;
    wire        m_axi_wvalid;
    wire        m_axi_wready;
    wire        m_axi_wlast;

    wire [1:0]  m_axi_bresp;
    wire        m_axi_bvalid;
    wire        m_axi_bready;

    wire [31:0] m_axi_araddr;
    wire [7:0]  m_axi_arlen;
    wire [2:0]  m_axi_arsize;
    wire [1:0]  m_axi_arburst;
    wire        m_axi_arvalid;
    wire        m_axi_arready;
    wire [2:0]  m_axi_arprot;

    wire [31:0] m_axi_rdata;
    wire [1:0]  m_axi_rresp;
    wire        m_axi_rvalid;
    wire        m_axi_rlast;
    wire        m_axi_rready;

    // ---- DUT -----------------------------------------------------------------

    fcapz_ejtagaxi #(
        .ADDR_W     (32),
        .DATA_W     (32),
        .FIFO_DEPTH (16),
        .TIMEOUT    (4096)
    ) dut (
        .tck            (tck),
        .tdi            (tdi),
        .tdo            (tdo),
        .capture        (capture),
        .shift_en       (shift_en),
        .update         (update),
        .sel            (sel),

        .axi_clk        (axi_clk),
        .axi_rst         (axi_rst),

        .m_axi_awaddr   (m_axi_awaddr),
        .m_axi_awlen    (m_axi_awlen),
        .m_axi_awsize   (m_axi_awsize),
        .m_axi_awburst  (m_axi_awburst),
        .m_axi_awvalid  (m_axi_awvalid),
        .m_axi_awready  (m_axi_awready),
        .m_axi_awprot   (m_axi_awprot),

        .m_axi_wdata    (m_axi_wdata),
        .m_axi_wstrb    (m_axi_wstrb),
        .m_axi_wvalid   (m_axi_wvalid),
        .m_axi_wready   (m_axi_wready),
        .m_axi_wlast    (m_axi_wlast),

        .m_axi_bresp    (m_axi_bresp),
        .m_axi_bvalid   (m_axi_bvalid),
        .m_axi_bready   (m_axi_bready),

        .m_axi_araddr   (m_axi_araddr),
        .m_axi_arlen    (m_axi_arlen),
        .m_axi_arsize   (m_axi_arsize),
        .m_axi_arburst  (m_axi_arburst),
        .m_axi_arvalid  (m_axi_arvalid),
        .m_axi_arready  (m_axi_arready),
        .m_axi_arprot   (m_axi_arprot),

        .m_axi_rdata    (m_axi_rdata),
        .m_axi_rresp    (m_axi_rresp),
        .m_axi_rvalid   (m_axi_rvalid),
        .m_axi_rlast    (m_axi_rlast),
        .m_axi_rready   (m_axi_rready)
    );

    // ---- AXI4 test slave (16 words) ------------------------------------------

    axi4_test_slave #(
        .ADDR_W    (32),
        .DATA_W    (32),
        .NUM_WORDS (16)
    ) slave (
        .clk             (axi_clk),
        .rst             (axi_rst),

        .s_axi_awaddr    (m_axi_awaddr),
        .s_axi_awlen     (m_axi_awlen),
        .s_axi_awsize    (m_axi_awsize),
        .s_axi_awburst   (m_axi_awburst),
        .s_axi_awvalid   (m_axi_awvalid),
        .s_axi_awready   (m_axi_awready),

        .s_axi_wdata     (m_axi_wdata),
        .s_axi_wstrb     (m_axi_wstrb),
        .s_axi_wlast     (m_axi_wlast),
        .s_axi_wvalid    (m_axi_wvalid),
        .s_axi_wready    (m_axi_wready),

        .s_axi_bresp     (m_axi_bresp),
        .s_axi_bvalid    (m_axi_bvalid),
        .s_axi_bready    (m_axi_bready),

        .s_axi_araddr    (m_axi_araddr),
        .s_axi_arlen     (m_axi_arlen),
        .s_axi_arsize    (m_axi_arsize),
        .s_axi_arburst   (m_axi_arburst),
        .s_axi_arvalid   (m_axi_arvalid),
        .s_axi_arready   (m_axi_arready),

        .s_axi_rdata     (m_axi_rdata),
        .s_axi_rresp     (m_axi_rresp),
        .s_axi_rlast     (m_axi_rlast),
        .s_axi_rvalid    (m_axi_rvalid),
        .s_axi_rready    (m_axi_rready)
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

    // ---- Command encoding constants ------------------------------------------

    localparam [3:0] CMD_NOP          = 4'h0;
    localparam [3:0] CMD_WRITE        = 4'h1;
    localparam [3:0] CMD_READ         = 4'h2;
    localparam [3:0] CMD_WRITE_INC    = 4'h3;
    localparam [3:0] CMD_READ_INC     = 4'h4;
    localparam [3:0] CMD_SET_ADDR     = 4'h5;
    localparam [3:0] CMD_BURST_SETUP  = 4'h6;
    localparam [3:0] CMD_BURST_WDATA  = 4'h7;
    localparam [3:0] CMD_BURST_RDATA  = 4'h8;
    localparam [3:0] CMD_BURST_RSTART = 4'h9;
    localparam [3:0] CMD_CONFIG       = 4'hE;
    localparam [3:0] CMD_RESET        = 4'hF;

    // ---- Helper functions ----------------------------------------------------

    function [71:0] make_cmd(input [3:0] cmd, input [31:0] addr,
                             input [31:0] payload, input [3:0] wstrb);
        make_cmd = {cmd, wstrb, payload, addr};
    endfunction

    function [3:0] get_status(input [71:0] dout);
        get_status = dout[71:68];
    endfunction

    function [31:0] get_rdata(input [71:0] dout);
        get_rdata = dout[31:0];
    endfunction

    function [1:0] get_resp(input [71:0] dout);
        get_resp = dout[65:64];
    endfunction

    // ---- DR scan task --------------------------------------------------------

    task automatic dr_scan_72(input [71:0] din, output [71:0] dout);
        integer i;
        begin
            // 1. Capture phase
            @(posedge tck);
            sel     <= 1'b1;
            capture <= 1'b1;
            @(posedge tck);
            capture <= 1'b0;

            // 2. Shift 72 bits (LSB first)
            shift_en <= 1'b1;
            for (i = 0; i < 72; i = i + 1) begin
                tdi <= din[i];
                @(negedge tck);
                dout[i] = tdo;
                @(posedge tck);
            end
            shift_en <= 1'b0;

            // 3. Update phase
            @(posedge tck);
            update <= 1'b1;
            @(posedge tck);
            update <= 1'b0;
            sel    <= 1'b0;
        end
    endtask

    // ---- CDC settling delay --------------------------------------------------

    task automatic cdc_wait;
        repeat (10) @(posedge tck);
    endtask

    // ---- Test scenarios ------------------------------------------------------

    initial begin
        logic [71:0] scan_in, scan_out;
        logic [31:0] rdata;
        logic [3:0]  status;
        logic [1:0]  resp;
        integer i;

        // Release AXI reset
        repeat (4) @(posedge axi_clk);
        axi_rst <= 1'b0;
        repeat (10) @(posedge tck);

        // ==================================================================
        // Scenario 1: Single WRITE + NOP
        // ==================================================================
        $display("\n=== Scenario 1: Single WRITE + NOP ===");
        scan_in = make_cmd(CMD_WRITE, 32'h0000_0000, 32'hDEAD_BEEF, 4'hF);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // NOP to drain result
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        status = get_status(scan_out);
        resp   = get_resp(scan_out);
        check("S1: prev_valid=1", status[0] == 1'b1);
        check("S1: resp=OKAY",    resp == 2'b00);
        check("S1: slave reg[0]=0xDEADBEEF", slave.mem[0] == 32'hDEAD_BEEF);
        cdc_wait();

        // ==================================================================
        // Scenario 2: Single READ + NOP
        // ==================================================================
        $display("\n=== Scenario 2: Single READ + NOP ===");
        scan_in = make_cmd(CMD_READ, 32'h0000_0000, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata  = get_rdata(scan_out);
        status = get_status(scan_out);
        check("S2: rdata=0xDEADBEEF", rdata == 32'hDEAD_BEEF);
        check("S2: prev_valid=1",     status[0] == 1'b1);
        cdc_wait();

        // ==================================================================
        // Scenario 3: Write then read roundtrip
        // ==================================================================
        $display("\n=== Scenario 3: Write then read roundtrip ===");
        scan_in = make_cmd(CMD_WRITE, 32'h0000_0004, 32'h1234_5678, 4'hF);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // NOP to drain write result
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        scan_in = make_cmd(CMD_READ, 32'h0000_0004, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata = get_rdata(scan_out);
        check("S3: read back 0x12345678", rdata == 32'h1234_5678);
        cdc_wait();

        // ==================================================================
        // Scenario 4: WRITE with wstrb
        // ==================================================================
        $display("\n=== Scenario 4: WRITE with wstrb ===");
        // First write full word
        scan_in = make_cmd(CMD_WRITE, 32'h0000_0008, 32'hFFFF_FFFF, 4'hF);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // Partial write: only low 2 bytes (wstrb=0x3)
        scan_in = make_cmd(CMD_WRITE, 32'h0000_0008, 32'hAABB_CCDD, 4'h3);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // Read back
        scan_in = make_cmd(CMD_READ, 32'h0000_0008, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata = get_rdata(scan_out);
        // Upper 2 bytes unchanged (0xFFFF), lower 2 bytes = 0xCCDD
        check("S4: wstrb partial write", rdata == 32'hFFFF_CCDD);
        cdc_wait();

        // ==================================================================
        // Scenario 5: SET_ADDR + 4x WRITE_INC
        // ==================================================================
        $display("\n=== Scenario 5: SET_ADDR + 4x WRITE_INC ===");
        scan_in = make_cmd(CMD_SET_ADDR, 32'h0000_0010, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        for (i = 0; i < 4; i = i + 1) begin
            scan_in = make_cmd(CMD_WRITE_INC, 32'h0, 32'hA000_0000 + i, 4'hF);
            dr_scan_72(scan_in, scan_out);
            cdc_wait();
            // Drain with NOP
            scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
            dr_scan_72(scan_in, scan_out);
            cdc_wait();
        end

        check("S5: slave reg[4]=0xA0000000", slave.mem[4] == 32'hA000_0000);
        check("S5: slave reg[5]=0xA0000001", slave.mem[5] == 32'hA000_0001);
        check("S5: slave reg[6]=0xA0000002", slave.mem[6] == 32'hA000_0002);
        check("S5: slave reg[7]=0xA0000003", slave.mem[7] == 32'hA000_0003);

        // ==================================================================
        // Scenario 6: SET_ADDR + 4x READ_INC + NOP
        // ==================================================================
        $display("\n=== Scenario 6: SET_ADDR + 4x READ_INC ===");
        scan_in = make_cmd(CMD_SET_ADDR, 32'h0000_0010, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        for (i = 0; i < 4; i = i + 1) begin
            scan_in = make_cmd(CMD_READ_INC, 32'h0, 32'h0, 4'h0);
            dr_scan_72(scan_in, scan_out);
            cdc_wait();

            scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
            dr_scan_72(scan_in, scan_out);
            rdata = get_rdata(scan_out);
            check($sformatf("S6: read_inc[%0d]=0x%08x", i, 32'hA000_0000 + i),
                  rdata == 32'hA000_0000 + i);
            cdc_wait();
        end

        // ==================================================================
        // Scenario 7: BURST_SETUP + 4x BURST_WDATA + NOP
        // ==================================================================
        $display("\n=== Scenario 7: AXI4 burst write ===");
        // BURST_SETUP: addr=0x20, payload={burst=INCR(01), size=2(010), len=3}
        //   payload[7:0]=len=3, [10:8]=size=010, [13:12]=burst=01
        scan_in = make_cmd(CMD_BURST_SETUP, 32'h0000_0020,
                           {18'h0, 2'b01, 1'b0, 3'b010, 8'd3}, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        for (i = 0; i < 4; i = i + 1) begin
            scan_in = make_cmd(CMD_BURST_WDATA, 32'h0, 32'hB000_0000 + i, 4'hF);
            dr_scan_72(scan_in, scan_out);
            cdc_wait();
            // Drain
            scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
            dr_scan_72(scan_in, scan_out);
            cdc_wait();
        end

        check("S7: slave reg[8]=0xB0000000",  slave.mem[8]  == 32'hB000_0000);
        check("S7: slave reg[9]=0xB0000001",  slave.mem[9]  == 32'hB000_0001);
        check("S7: slave reg[10]=0xB0000002", slave.mem[10] == 32'hB000_0002);
        check("S7: slave reg[11]=0xB0000003", slave.mem[11] == 32'hB000_0003);

        // ==================================================================
        // Scenario 8: BURST_SETUP + BURST_RSTART + 4x BURST_RDATA
        // ==================================================================
        $display("\n=== Scenario 8: AXI4 burst read ===");
        scan_in = make_cmd(CMD_BURST_SETUP, 32'h0000_0020,
                           {18'h0, 2'b01, 1'b0, 3'b010, 8'd3}, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // BURST_RSTART kicks off the AXI AR transaction
        scan_in = make_cmd(CMD_BURST_RSTART, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // Wait for FIFO to fill
        repeat (20) @(posedge tck);

        // Priming BURST_RDATA: sets last_cmd=CMD_BURST_RDATA so the next
        // capture's mux selects FIFO data.  Capture output is discarded.
        scan_in = make_cmd(CMD_BURST_RDATA, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // Read 4 words from FIFO (each capture reads fifo_rdata, each update
        // advances the FIFO read pointer)
        for (i = 0; i < 4; i = i + 1) begin
            scan_in = make_cmd(CMD_BURST_RDATA, 32'h0, 32'h0, 4'h0);
            dr_scan_72(scan_in, scan_out);
            rdata = get_rdata(scan_out);
            check($sformatf("S8: burst_rdata[%0d]=0x%08x", i, 32'hB000_0000 + i),
                  rdata == 32'hB000_0000 + i);
            cdc_wait();
        end

        // ==================================================================
        // Scenario 9: CONFIG reads
        // ==================================================================
        $display("\n=== Scenario 9: CONFIG reads ===");

        // BRIDGE_ID
        scan_in = make_cmd(CMD_CONFIG, 32'h0000_0000, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        // NOP to read back config result
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata  = get_rdata(scan_out);
        status = get_status(scan_out);
        check("S9: BRIDGE_ID=0x454A4158",  rdata == 32'h454A4158);
        check("S9: BRIDGE_ID prev_valid=1", status[0] == 1'b1);
        cdc_wait();

        // VERSION
        scan_in = make_cmd(CMD_CONFIG, 32'h0000_0004, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata = get_rdata(scan_out);
        check("S9: VERSION=0x00000001", rdata == 32'h0000_0001);
        cdc_wait();

        // FEATURES: {8'd0, (FIFO_DEPTH-1)[7:0]=15, DATA_W[7:0]=32, ADDR_W[7:0]=32}
        // = 0x000F2020 (default FIFO_DEPTH=16)
        scan_in = make_cmd(CMD_CONFIG, 32'h0000_002C, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        rdata = get_rdata(scan_out);
        check("S9: FEATURES=0x000F2020", rdata == 32'h000F_2020);
        cdc_wait();

        // ==================================================================
        // Scenario 10: RESET
        // ==================================================================
        $display("\n=== Scenario 10: RESET ===");
        scan_in = make_cmd(CMD_RESET, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        cdc_wait();

        // NOP to verify clean state
        scan_in = make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0);
        dr_scan_72(scan_in, scan_out);
        status = get_status(scan_out);
        check("S10: no error after reset", status[2] == 1'b0); // error_sticky
        check("S10: not busy after reset", status[1] == 1'b0); // busy
        cdc_wait();

        // ==================================================================
        // Final summary
        // ==================================================================
        $display("=== EJTAGAXI TB: %0d passed, %0d failed ===", pass_count, fail_count);
        if (fail_count > 0) $fatal(1, "TESTS FAILED");
        $finish;
    end

endmodule
