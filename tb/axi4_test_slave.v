// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Reusable AXI4 test slave for simulation.
// Features: configurable register file, INCR burst support, stall injection,
// error address (SLVERR), and hang address (never-ready for timeout tests).

module axi4_test_slave #(
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter NUM_WORDS    = 16,
    parameter STALL_CYCLES = 0,
    parameter ERROR_ADDR   = 32'hFFFF_FFFC,
    parameter HANG_ADDR    = 32'hFFFF_FFF8
) (
    input  wire                    clk,
    input  wire                    rst,

    // AXI4 Write Address channel
    input  wire [ADDR_W-1:0]       s_axi_awaddr,
    input  wire [7:0]              s_axi_awlen,
    input  wire [2:0]              s_axi_awsize,
    input  wire [1:0]              s_axi_awburst,
    input  wire                    s_axi_awvalid,
    output reg                     s_axi_awready,

    // AXI4 Write Data channel
    input  wire [DATA_W-1:0]       s_axi_wdata,
    input  wire [(DATA_W/8)-1:0]   s_axi_wstrb,
    input  wire                    s_axi_wlast,
    input  wire                    s_axi_wvalid,
    output reg                     s_axi_wready,

    // AXI4 Write Response channel
    output reg  [1:0]              s_axi_bresp,
    output reg                     s_axi_bvalid,
    input  wire                    s_axi_bready,

    // AXI4 Read Address channel
    input  wire [ADDR_W-1:0]       s_axi_araddr,
    input  wire [7:0]              s_axi_arlen,
    input  wire [2:0]              s_axi_arsize,
    input  wire [1:0]              s_axi_arburst,
    input  wire                    s_axi_arvalid,
    output reg                     s_axi_arready,

    // AXI4 Read Data channel
    output reg  [DATA_W-1:0]       s_axi_rdata,
    output reg  [1:0]              s_axi_rresp,
    output reg                     s_axi_rlast,
    output reg                     s_axi_rvalid,
    input  wire                    s_axi_rready
);

    // ---- Register file -------------------------------------------------------

    reg [DATA_W-1:0] mem [0:NUM_WORDS-1];

    // ---- Helpers -------------------------------------------------------------

    function [ADDR_W-1:0] word_index;
        input [ADDR_W-1:0] byte_addr;
        word_index = (byte_addr >> 2) % NUM_WORDS;
    endfunction

    function is_error_addr;
        input [ADDR_W-1:0] addr;
        is_error_addr = (addr == ERROR_ADDR);
    endfunction

    function is_hang_addr;
        input [ADDR_W-1:0] addr;
        is_hang_addr = (addr == HANG_ADDR);
    endfunction

    // ---- Initialise memory ---------------------------------------------------

    integer init_i;
    initial begin
        for (init_i = 0; init_i < NUM_WORDS; init_i = init_i + 1)
            mem[init_i] = {DATA_W{1'b0}};
    end

    // ---- Write channel FSM ---------------------------------------------------

    localparam W_IDLE   = 2'd0;
    localparam W_DATA   = 2'd1;
    localparam W_RESP   = 2'd2;
    localparam W_STALL  = 2'd3;

    reg [1:0]          w_state;
    reg [ADDR_W-1:0]   w_addr;
    reg [7:0]          w_len;
    reg [7:0]          w_beat;
    reg                w_error;
    reg                w_hang;
    reg [15:0]         w_stall_cnt;

    always @(posedge clk) begin
        if (rst) begin
            w_state       <= W_IDLE;
            s_axi_awready <= 1'b1;
            s_axi_wready  <= 1'b0;
            s_axi_bvalid  <= 1'b0;
            s_axi_bresp   <= 2'b00;
            w_addr        <= {ADDR_W{1'b0}};
            w_len         <= 8'd0;
            w_beat        <= 8'd0;
            w_error       <= 1'b0;
            w_hang        <= 1'b0;
            w_stall_cnt   <= 16'd0;
        end else begin
            case (w_state)
                W_IDLE: begin
                    s_axi_bvalid <= 1'b0;
                    if (s_axi_awvalid && s_axi_awready) begin
                        w_addr        <= s_axi_awaddr;
                        w_len         <= s_axi_awlen;
                        w_beat        <= 8'd0;
                        w_error       <= is_error_addr(s_axi_awaddr);
                        w_hang        <= is_hang_addr(s_axi_awaddr);
                        s_axi_awready <= 1'b0;
                        if (STALL_CYCLES > 0) begin
                            w_stall_cnt <= STALL_CYCLES[15:0];
                            w_state     <= W_STALL;
                        end else begin
                            s_axi_wready <= 1'b1;
                            w_state      <= W_DATA;
                        end
                    end
                end

                W_STALL: begin
                    if (w_stall_cnt == 16'd1) begin
                        s_axi_wready <= ~w_hang;
                        w_state      <= W_DATA;
                    end
                    w_stall_cnt <= w_stall_cnt - 16'd1;
                end

                W_DATA: begin
                    if (w_hang) begin
                        s_axi_wready <= 1'b0; // never ready
                    end else if (s_axi_wvalid && s_axi_wready) begin
                        // Write to register file (skip on error addr)
                        if (!w_error) begin : wr_strobe
                            integer b;
                            for (b = 0; b < (DATA_W/8); b = b + 1) begin
                                if (s_axi_wstrb[b])
                                    mem[word_index(w_addr)][b*8 +: 8] <= s_axi_wdata[b*8 +: 8];
                            end
                        end

                        w_beat <= w_beat + 8'd1;
                        w_addr <= w_addr + (DATA_W / 8); // INCR burst

                        if (s_axi_wlast || (w_beat == w_len)) begin
                            s_axi_wready <= 1'b0;
                            s_axi_bvalid <= 1'b1;
                            s_axi_bresp  <= w_error ? 2'b10 : 2'b00;
                            w_state      <= W_RESP;
                        end
                    end
                end

                W_RESP: begin
                    if (s_axi_bvalid && s_axi_bready) begin
                        s_axi_bvalid  <= 1'b0;
                        s_axi_awready <= 1'b1;
                        w_state       <= W_IDLE;
                    end
                end

                default: w_state <= W_IDLE;
            endcase
        end
    end

    // ---- Read channel FSM ----------------------------------------------------

    localparam R_IDLE   = 2'd0;
    localparam R_DATA   = 2'd1;
    localparam R_STALL  = 2'd2;

    reg [1:0]          r_state;
    reg [ADDR_W-1:0]   r_addr;
    reg [7:0]          r_len;
    reg [7:0]          r_beat;
    reg                r_error;
    reg                r_hang;
    reg [15:0]         r_stall_cnt;

    always @(posedge clk) begin
        if (rst) begin
            r_state       <= R_IDLE;
            s_axi_arready <= 1'b1;
            s_axi_rvalid  <= 1'b0;
            s_axi_rdata   <= {DATA_W{1'b0}};
            s_axi_rresp   <= 2'b00;
            s_axi_rlast   <= 1'b0;
            r_addr        <= {ADDR_W{1'b0}};
            r_len         <= 8'd0;
            r_beat        <= 8'd0;
            r_error       <= 1'b0;
            r_hang        <= 1'b0;
            r_stall_cnt   <= 16'd0;
        end else begin
            case (r_state)
                R_IDLE: begin
                    s_axi_rvalid <= 1'b0;
                    s_axi_rlast  <= 1'b0;
                    if (s_axi_arvalid && s_axi_arready) begin
                        r_addr        <= s_axi_araddr;
                        r_len         <= s_axi_arlen;
                        r_beat        <= 8'd0;
                        r_error       <= is_error_addr(s_axi_araddr);
                        r_hang        <= is_hang_addr(s_axi_araddr);
                        s_axi_arready <= 1'b0;
                        if (STALL_CYCLES > 0) begin
                            r_stall_cnt <= STALL_CYCLES[15:0];
                            r_state     <= R_STALL;
                        end else begin
                            r_state <= R_DATA;
                        end
                    end
                end

                R_STALL: begin
                    if (r_stall_cnt == 16'd1)
                        r_state <= R_DATA;
                    r_stall_cnt <= r_stall_cnt - 16'd1;
                end

                R_DATA: begin
                    if (r_hang) begin
                        s_axi_rvalid <= 1'b0; // never valid — hang
                    end else if (s_axi_rvalid && s_axi_rready) begin
                        // Beat accepted — advance or finish
                        if (r_beat == r_len) begin
                            // Final beat accepted
                            s_axi_rvalid  <= 1'b0;
                            s_axi_rlast   <= 1'b0;
                            s_axi_arready <= 1'b1;
                            r_state       <= R_IDLE;
                        end else begin
                            // Advance to next beat
                            r_beat       <= r_beat + 8'd1;
                            r_addr       <= r_addr + (DATA_W / 8);
                            s_axi_rdata  <= r_error ? {DATA_W{1'b0}}
                                                    : mem[word_index(r_addr + (DATA_W / 8))];
                            s_axi_rresp  <= r_error ? 2'b10 : 2'b00;
                            s_axi_rlast  <= ((r_beat + 8'd1) == r_len);
                        end
                    end else if (!s_axi_rvalid) begin
                        // Present first beat
                        s_axi_rvalid <= 1'b1;
                        s_axi_rdata  <= r_error ? {DATA_W{1'b0}} : mem[word_index(r_addr)];
                        s_axi_rresp  <= r_error ? 2'b10 : 2'b00;
                        s_axi_rlast  <= (r_beat == r_len);
                    end
                end

                default: r_state <= R_IDLE;
            endcase
        end
    end

endmodule
