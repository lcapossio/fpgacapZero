// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// SPI-to-register bridge for small FPGAs without a fabric-visible user JTAG TAP.
//
// SPI mode: mode 0 (CPOL=0, CPHA=0), MSB-first bytes.
//
// Read transaction, 8 bytes:
//   MOSI: 0x00 addr[15:8] addr[7:0] 0x00 0x00 0x00 0x00 0x00
//   MISO: 0x00 0x00       0x00      0x00 rdata[31:24] ... rdata[7:0]
//
// Write transaction, 8 bytes:
//   MOSI: 0x80 addr[15:8] addr[7:0] wdata[31:24] ... wdata[7:0] 0x00
//
// The generated register strobes are synchronous to spi_sck, which is also
// exported as reg_clk. Keep SCK comfortably slower than the target device's
// timing allows; this is intended as a portable bring-up/debug transport, not
// a high-throughput capture path.

module fcapz_spi_reg_iface (
    input  wire        spi_sck,
    input  wire        spi_cs_n,
    input  wire        spi_mosi,
    output reg         spi_miso,

    output wire        reg_clk,
    output reg         reg_rst,
    output wire        reg_wr_en,
    output wire        reg_rd_en,
    output reg  [15:0] reg_addr,
    output reg  [31:0] reg_wdata,
    input  wire [31:0] reg_rdata
);

    localparam CMD_READ  = 8'h00;
    localparam CMD_WRITE = 8'h80;

    assign reg_clk = spi_sck;
    assign reg_rd_en = read_cmd && !spi_cs_n && (byte_idx == 4'd3) && (bit_idx == 3'd0);
    assign reg_wr_en = write_cmd && !spi_cs_n && (byte_idx == 4'd7) && (bit_idx == 3'd0);

    reg [2:0] bit_idx;
    reg [3:0] byte_idx;
    reg [7:0] rx_shift;
    reg [7:0] cmd;
    reg [31:0] tx_word;
    reg [31:0] wdata_shift;
    reg read_cmd;
    reg write_cmd;

    wire [7:0] rx_byte = {rx_shift[6:0], spi_mosi};

    initial begin
        bit_idx = 3'd0;
        byte_idx = 4'd0;
        rx_shift = 8'h00;
        cmd = 8'h00;
        reg_rst = 1'b0;
        reg_addr = 16'h0000;
        reg_wdata = 32'h0000_0000;
        tx_word = 32'h0000_0000;
        wdata_shift = 32'h0000_0000;
        read_cmd = 1'b0;
        write_cmd = 1'b0;
        spi_miso = 1'b0;
    end

    always @(posedge spi_sck or posedge spi_cs_n) begin
        if (spi_cs_n) begin
            bit_idx <= 3'd0;
            byte_idx <= 4'd0;
            rx_shift <= 8'h00;
            cmd <= 8'h00;
            reg_rst <= 1'b0;
            reg_addr <= 16'h0000;
            reg_wdata <= 32'h0000_0000;
            tx_word <= 32'h0000_0000;
            wdata_shift <= 32'h0000_0000;
            read_cmd <= 1'b0;
            write_cmd <= 1'b0;
        end else begin
            reg_rst <= 1'b0;
            rx_shift <= rx_byte;

            if (bit_idx == 3'd7) begin
                bit_idx <= 3'd0;
                byte_idx <= byte_idx + 4'd1;

                case (byte_idx)
                    4'd0: begin
                        cmd <= rx_byte;
                        read_cmd <= (rx_byte == CMD_READ);
                        write_cmd <= (rx_byte == CMD_WRITE);
                    end
                    4'd1: begin
                        reg_addr[15:8] <= rx_byte;
                    end
                    4'd2: begin
                        reg_addr[7:0] <= rx_byte;
                    end
                    4'd3: begin
                        wdata_shift[31:24] <= rx_byte;
                        tx_word <= reg_rdata;
                    end
                    4'd4: begin
                        wdata_shift[23:16] <= rx_byte;
                    end
                    4'd5: begin
                        wdata_shift[15:8] <= rx_byte;
                    end
                    4'd6: begin
                        wdata_shift[7:0] <= rx_byte;
                        if (write_cmd) begin
                            reg_wdata <= {wdata_shift[31:8], rx_byte};
                        end
                    end
                    default: begin
                    end
                endcase
            end else begin
                bit_idx <= bit_idx + 3'd1;
            end
        end
    end

    always @(negedge spi_sck or posedge spi_cs_n) begin
        if (spi_cs_n) begin
            spi_miso <= 1'b0;
        end else begin
            if (read_cmd && byte_idx >= 4'd4 && byte_idx <= 4'd7) begin
                spi_miso <= tx_word[31 - (((byte_idx - 4'd4) * 8) + bit_idx)];
            end else begin
                spi_miso <= 1'b0;
            end
        end
    end

endmodule
