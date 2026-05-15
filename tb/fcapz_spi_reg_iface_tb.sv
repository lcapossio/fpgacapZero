`timescale 1ns/1ps

module fcapz_spi_reg_iface_tb;
    reg spi_sck = 1'b0;
    reg spi_cs_n = 1'b1;
    reg spi_mosi = 1'b0;
    wire spi_miso;

    wire reg_clk;
    wire reg_rst;
    wire reg_wr_en;
    wire reg_rd_en;
    wire [15:0] reg_addr;
    wire [31:0] reg_wdata;
    reg  [31:0] reg_rdata = 32'h0000_0000;

    reg [31:0] mem [0:255];
    integer failures = 0;

    fcapz_spi_reg_iface dut (
        .spi_sck(spi_sck),
        .spi_cs_n(spi_cs_n),
        .spi_mosi(spi_mosi),
        .spi_miso(spi_miso),
        .reg_clk(reg_clk),
        .reg_rst(reg_rst),
        .reg_wr_en(reg_wr_en),
        .reg_rd_en(reg_rd_en),
        .reg_addr(reg_addr),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata)
    );

    always @* begin
        reg_rdata = mem[reg_addr[9:2]];
    end

    always @(posedge reg_clk) begin
        if (reg_wr_en)
            mem[reg_addr[9:2]] <= reg_wdata;
    end

    task tick(input bit mosi_bit, output bit miso_bit);
        begin
            spi_mosi = mosi_bit;
            #5 spi_sck = 1'b1;
            #1 miso_bit = spi_miso;
            #5 spi_sck = 1'b0;
            #4;
        end
    endtask

    task spi_xfer_byte(input [7:0] tx, output [7:0] rx);
        integer i;
        bit miso_bit;
        begin
            rx = 8'h00;
            for (i = 7; i >= 0; i = i - 1) begin
                tick(tx[i], miso_bit);
                rx[i] = miso_bit;
            end
        end
    endtask

    task spi_write_reg(input [15:0] addr, input [31:0] value);
        reg [7:0] rx;
        begin
            spi_cs_n = 1'b0;
            spi_xfer_byte(8'h80, rx);
            spi_xfer_byte(addr[15:8], rx);
            spi_xfer_byte(addr[7:0], rx);
            spi_xfer_byte(value[31:24], rx);
            spi_xfer_byte(value[23:16], rx);
            spi_xfer_byte(value[15:8], rx);
            spi_xfer_byte(value[7:0], rx);
            spi_xfer_byte(8'h00, rx);
            spi_cs_n = 1'b1;
            #20;
        end
    endtask

    task spi_read_reg(input [15:0] addr, output [31:0] value);
        reg [7:0] rx0;
        reg [7:0] rx1;
        reg [7:0] rx2;
        reg [7:0] rx3;
        begin
            spi_cs_n = 1'b0;
            spi_xfer_byte(8'h00, rx0);
            spi_xfer_byte(addr[15:8], rx0);
            spi_xfer_byte(addr[7:0], rx0);
            spi_xfer_byte(8'h00, rx0);
            spi_xfer_byte(8'h00, rx0);
            spi_xfer_byte(8'h00, rx1);
            spi_xfer_byte(8'h00, rx2);
            spi_xfer_byte(8'h00, rx3);
            spi_cs_n = 1'b1;
            value = {rx0, rx1, rx2, rx3};
            #20;
        end
    endtask

    task expect_eq(input [31:0] got, input [31:0] exp, input [255:0] msg);
        begin
            if (got !== exp) begin
                $display("FAIL: %0s got=0x%08x exp=0x%08x", msg, got, exp);
                failures = failures + 1;
            end else begin
                $display("PASS: %0s = 0x%08x", msg, got);
            end
        end
    endtask

    initial begin
        mem[16'h0010 >> 2] = 32'h1234_abcd;

        spi_write_reg(16'h0028, 32'hdead_beef);
        expect_eq(mem[16'h0028 >> 2], 32'hdead_beef, "write_reg");

        begin
            reg [31:0] value;
            spi_read_reg(16'h0010, value);
            expect_eq(value, 32'h1234_abcd, "read_reg");
        end

        if (failures != 0) begin
            $display("fcapz_spi_reg_iface_tb: %0d failure(s)", failures);
            $fatal(1);
        end
        $display("fcapz_spi_reg_iface_tb: PASS");
        $finish;
    end
endmodule
