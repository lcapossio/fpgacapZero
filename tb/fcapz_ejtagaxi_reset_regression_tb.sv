// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Focused regression for reset bookkeeping around the EJTAG-AXI bridge.
//
// This bench checks the class of failure we now suspect on hardware:
// 1. perform real AXI traffic
// 2. issue CMD_RESET and drain to idle
// 3. ensure no phantom prev_valid remains after reset
// 4. verify the first post-reset READ / READ_INC returns the real memory value
//
// The slave memory is not reset by CMD_RESET, only the bridge state is.

module fcapz_ejtagaxi_reset_regression_tb;

    logic tck     = 1'b0;
    logic axi_clk = 1'b0;
    logic axi_rst = 1'b1;

    always #50  tck     = ~tck;
    always #15  axi_clk = ~axi_clk;

    logic tdi      = 1'b0;
    wire  tdo;
    logic capture  = 1'b0;
    logic shift_en = 1'b0;
    logic update   = 1'b0;
    logic sel      = 1'b0;

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

    integer pass_count = 0;
    integer fail_count = 0;

    localparam [3:0] CMD_NOP       = 4'h0;
    localparam [3:0] CMD_WRITE     = 4'h1;
    localparam [3:0] CMD_READ      = 4'h2;
    localparam [3:0] CMD_READ_INC  = 4'h4;
    localparam [3:0] CMD_SET_ADDR  = 4'h5;
    localparam [3:0] CMD_RESET     = 4'hF;

    fcapz_ejtagaxi #(
        .ADDR_W     (32),
        .DATA_W     (32),
        .FIFO_DEPTH (16),
        .TIMEOUT    (4096)
    ) dut (
        .tck           (tck),
        .tdi           (tdi),
        .tdo           (tdo),
        .capture       (capture),
        .shift_en      (shift_en),
        .update        (update),
        .sel           (sel),
        .axi_clk       (axi_clk),
        .axi_rst       (axi_rst),
        .m_axi_awaddr  (m_axi_awaddr),
        .m_axi_awlen   (m_axi_awlen),
        .m_axi_awsize  (m_axi_awsize),
        .m_axi_awburst (m_axi_awburst),
        .m_axi_awvalid (m_axi_awvalid),
        .m_axi_awready (m_axi_awready),
        .m_axi_awprot  (m_axi_awprot),
        .m_axi_wdata   (m_axi_wdata),
        .m_axi_wstrb   (m_axi_wstrb),
        .m_axi_wvalid  (m_axi_wvalid),
        .m_axi_wready  (m_axi_wready),
        .m_axi_wlast   (m_axi_wlast),
        .m_axi_bresp   (m_axi_bresp),
        .m_axi_bvalid  (m_axi_bvalid),
        .m_axi_bready  (m_axi_bready),
        .m_axi_araddr  (m_axi_araddr),
        .m_axi_arlen   (m_axi_arlen),
        .m_axi_arsize  (m_axi_arsize),
        .m_axi_arburst (m_axi_arburst),
        .m_axi_arvalid (m_axi_arvalid),
        .m_axi_arready (m_axi_arready),
        .m_axi_arprot  (m_axi_arprot),
        .m_axi_rdata   (m_axi_rdata),
        .m_axi_rresp   (m_axi_rresp),
        .m_axi_rvalid  (m_axi_rvalid),
        .m_axi_rlast   (m_axi_rlast),
        .m_axi_rready  (m_axi_rready)
    );

    axi4_test_slave #(
        .ADDR_W    (32),
        .DATA_W    (32),
        .NUM_WORDS (16)
    ) slave (
        .clk           (axi_clk),
        .rst           (axi_rst),
        .s_axi_awaddr  (m_axi_awaddr),
        .s_axi_awlen   (m_axi_awlen),
        .s_axi_awsize  (m_axi_awsize),
        .s_axi_awburst (m_axi_awburst),
        .s_axi_awvalid (m_axi_awvalid),
        .s_axi_awready (m_axi_awready),
        .s_axi_wdata   (m_axi_wdata),
        .s_axi_wstrb   (m_axi_wstrb),
        .s_axi_wlast   (m_axi_wlast),
        .s_axi_wvalid  (m_axi_wvalid),
        .s_axi_wready  (m_axi_wready),
        .s_axi_bresp   (m_axi_bresp),
        .s_axi_bvalid  (m_axi_bvalid),
        .s_axi_bready  (m_axi_bready),
        .s_axi_araddr  (m_axi_araddr),
        .s_axi_arlen   (m_axi_arlen),
        .s_axi_arsize  (m_axi_arsize),
        .s_axi_arburst (m_axi_arburst),
        .s_axi_arvalid (m_axi_arvalid),
        .s_axi_arready (m_axi_arready),
        .s_axi_rdata   (m_axi_rdata),
        .s_axi_rresp   (m_axi_rresp),
        .s_axi_rlast   (m_axi_rlast),
        .s_axi_rvalid  (m_axi_rvalid),
        .s_axi_rready  (m_axi_rready)
    );

    task automatic check(input string name, input logic cond);
        if (cond) begin
            pass_count++;
        end else begin
            fail_count++;
            $display("FAIL: %s", name);
        end
    endtask

    function automatic [71:0] make_cmd(
        input [3:0] cmd,
        input [31:0] addr,
        input [31:0] payload,
        input [3:0] wstrb
    );
        make_cmd = {cmd, wstrb, payload, addr};
    endfunction

    function automatic [3:0] get_status(input [71:0] dout);
        get_status = dout[71:68];
    endfunction

    function automatic [31:0] get_rdata(input [71:0] dout);
        get_rdata = dout[31:0];
    endfunction

    function automatic [1:0] get_resp(input [71:0] dout);
        get_resp = dout[65:64];
    endfunction

    task automatic dr_scan_72(input [71:0] din, output [71:0] dout);
        integer i;
        begin
            @(posedge tck);
            sel     <= 1'b1;
            capture <= 1'b1;
            @(posedge tck);
            capture <= 1'b0;

            shift_en <= 1'b1;
            for (i = 0; i < 72; i = i + 1) begin
                tdi <= din[i];
                @(negedge tck);
                dout[i] = tdo;
                @(posedge tck);
            end
            shift_en <= 1'b0;

            @(posedge tck);
            update <= 1'b1;
            @(posedge tck);
            update <= 1'b0;
            sel    <= 1'b0;
        end
    endtask

    task automatic cdc_wait;
        repeat (10) @(posedge tck);
    endtask

    task automatic issue_and_wait_valid(
        input [71:0] issue_cmd,
        output [71:0] result_scan,
        input string label
    );
        integer j;
        logic [71:0] scan_out_local;
        logic [3:0] status_local;
        logic [1:0] resp_local;
        begin : wait_block
            dr_scan_72(issue_cmd, scan_out_local);
            cdc_wait();
            for (j = 0; j < 32; j = j + 1) begin
                dr_scan_72(make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0), scan_out_local);
                status_local = get_status(scan_out_local);
                resp_local   = get_resp(scan_out_local);
                if (j < 6) begin
                    $display(
                        "TRACE %s poll=%0d status=0x%0x resp=0x%0x pending=%0d respq_empty=%0b head_seen=%0b axi_state=%0d",
                        label,
                        j,
                        status_local,
                        resp_local,
                        dut.pending_count,
                        dut.respq_empty,
                        dut.respq_head_seen,
                        dut.axi_state
                    );
                end
                if (status_local[0]) begin
                    result_scan = scan_out_local;
                    disable wait_block;
                end
                if (!status_local[1]) begin
                    check({label, ": became idle before prev_valid"}, 1'b0);
                    result_scan = scan_out_local;
                    disable wait_block;
                end
                if (status_local[2]) begin
                    check({label, ": error_sticky set"}, 1'b0);
                    result_scan = scan_out_local;
                    disable wait_block;
                end
                cdc_wait();
            end
            $display(
                "DEBUG %s timeout: status=0x%0x pending=%0d respq_empty=%0b respq_rd_count=%0d respq_wr_count=%0d head_seen=%0b axi_state=%0d launch_cmd=%0d resp_wr_en=%0b mem0=0x%08x mem1=0x%08x awvalid=%0b wvalid=%0b bvalid=%0b arvalid=%0b rvalid=%0b",
                label,
                status_local,
                dut.pending_count,
                dut.respq_empty,
                dut.respq_rd_count,
                dut.respq_wr_count,
                dut.respq_head_seen,
                dut.axi_state,
                dut.launch_cmd,
                dut.respq_wr_en,
                slave.mem[0],
                slave.mem[1],
                m_axi_awvalid,
                m_axi_wvalid,
                m_axi_bvalid,
                m_axi_arvalid,
                m_axi_rvalid
            );
            check({label, ": timed out waiting for prev_valid"}, 1'b0);
            result_scan = scan_out_local;
        end
    endtask

    task automatic drain_until_idle(
        output [71:0] last_scan,
        output integer polls
    );
        integer j;
        logic [71:0] scan_out_local;
        logic [3:0] status_local;
        begin : idle_block
            polls = 0;
            for (j = 0; j < 32; j = j + 1) begin
                dr_scan_72(make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0), scan_out_local);
                status_local = get_status(scan_out_local);
                polls = j + 1;
                if (!status_local[1]) begin
                    last_scan = scan_out_local;
                    disable idle_block;
                end
                cdc_wait();
            end
            $display(
                "DEBUG reset drain timeout: status=0x%0x pending=%0d respq_empty=%0b cmdq_empty=%0b reset_busy=%0b axi_state=%0d",
                status_local,
                dut.pending_count,
                dut.respq_empty,
                dut.cmdq_empty,
                dut.reset_busy_tck,
                dut.axi_state
            );
            check("reset drain timed out waiting for idle", 1'b0);
            last_scan = scan_out_local;
        end
    endtask

    initial begin
        logic [71:0] scan_out;
        logic [3:0]  status;
        logic [1:0]  resp;
        logic [31:0] rdata;
        integer polls;

        repeat (4) @(posedge axi_clk);
        axi_rst <= 1'b0;
        repeat (10) @(posedge tck);

        issue_and_wait_valid(
            make_cmd(CMD_WRITE, 32'h0000_0000, 32'h1234_5678, 4'hF),
            scan_out,
            "write addr 0"
        );
        resp = get_resp(scan_out);
        check("write addr 0 resp=OKAY", resp == 2'b00);

        issue_and_wait_valid(
            make_cmd(CMD_WRITE, 32'h0000_0004, 32'h89AB_CDEF, 4'hF),
            scan_out,
            "write addr 4"
        );
        resp = get_resp(scan_out);
        check("write addr 4 resp=OKAY", resp == 2'b00);
        check("slave mem[0] seeded", slave.mem[0] == 32'h1234_5678);
        check("slave mem[1] seeded", slave.mem[1] == 32'h89AB_CDEF);

        dr_scan_72(make_cmd(CMD_RESET, 32'h0, 32'h0, 4'h0), scan_out);
        cdc_wait();
        drain_until_idle(scan_out, polls);
        status = get_status(scan_out);
        check("reset drain reached idle", status[1] == 1'b0);
        check("pending_count cleared after reset", dut.pending_count == 0);
        check("last_cmd cleared after reset", dut.last_cmd == CMD_NOP);

        dr_scan_72(make_cmd(CMD_NOP, 32'h0, 32'h0, 4'h0), scan_out);
        status = get_status(scan_out);
        check("no phantom prev_valid after reset drain", status[0] == 1'b0);
        check("no sticky error after reset drain", status[2] == 1'b0);
        cdc_wait();

        issue_and_wait_valid(
            make_cmd(CMD_READ, 32'h0000_0000, 32'h0, 4'h0),
            scan_out,
            "first post-reset read"
        );
        rdata = get_rdata(scan_out);
        resp  = get_resp(scan_out);
        check("first post-reset read resp=OKAY", resp == 2'b00);
        check("first post-reset read data correct", rdata == 32'h1234_5678);

        dr_scan_72(make_cmd(CMD_SET_ADDR, 32'h0000_0004, 32'h0, 4'h0), scan_out);
        cdc_wait();
        issue_and_wait_valid(
            make_cmd(CMD_READ_INC, 32'h0, 32'h0, 4'h0),
            scan_out,
            "first post-reset read_inc"
        );
        rdata = get_rdata(scan_out);
        resp  = get_resp(scan_out);
        check("first post-reset read_inc resp=OKAY", resp == 2'b00);
        check("first post-reset read_inc data correct", rdata == 32'h89AB_CDEF);

        if (fail_count == 0) begin
            $display("PASS: reset regression (%0d checks)", pass_count);
        end else begin
            $display("FAIL: reset regression (%0d passed, %0d failed)", pass_count, fail_count);
            $fatal(1, "RESET REGRESSION FAILED");
        end
        $finish;
    end

endmodule
