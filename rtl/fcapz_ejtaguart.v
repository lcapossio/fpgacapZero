// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Project-wide version + per-core identity defines.  AUTO-generated from
// the canonical VERSION file at the repo root by tools/sync_version.py.
`include "fcapz_version.vh"

// JTAG-to-UART bridge core (vendor-agnostic).
//
// TAP signals are provided by an external vendor-specific wrapper.
// Uses a 32-bit pipelined DR: each scan shifts in a command + tx_byte
// and shifts out status + rx_byte + tx_free.
//
// Parameters:
//   CLK_HZ               - Fabric clock frequency in Hz (default 100 MHz)
//   BAUD_RATE             - UART baud rate (default 115200)
//   TX_FIFO_DEPTH         - TX FIFO depth, must be power of 2 (default 256)
//   RX_FIFO_DEPTH         - RX FIFO depth, must be power of 2 (default 256)
//   PARITY                - 0=none, 1=even, 2=odd (default 0)
//   USE_BEHAV_ASYNC_FIFO  - 1=behavioral, 0=vendor primitive (default 1)
//
// 32-bit DR format (LSB first):
//   Shift-in:  [7:0]=tx_byte, [27:8]=reserved, [31:28]=cmd
//   Shift-out: [7:0]=rx_byte, [15:8]=tx_free, [23:16]=rsvd,
//              [24]=RX_READY, [27:25]=rsvd, [28]=RX_VALID,
//              [29]=TX_FULL, [30]=RX_OVERFLOW, [31]=FRAME_ERR

module fcapz_ejtaguart #(
    parameter CLK_HZ                = 100_000_000,
    parameter BAUD_RATE             = 115200,
    parameter TX_FIFO_DEPTH         = 256,
    parameter RX_FIFO_DEPTH         = 256,
    parameter PARITY                = 0,
    parameter USE_BEHAV_ASYNC_FIFO  = 1
) (
    // Fabric clock
    input  wire       uart_clk,
    input  wire       uart_rst,

    // UART pins
    output wire       uart_txd,
    input  wire       uart_rxd,

    // JTAG TAP interface (from vendor-specific wrapper)
    input  wire       tck,
    input  wire       tdi,
    output wire       tdo,
    input  wire       capture,
    input  wire       shift,
    input  wire       update,
    input  wire       sel
);

    // ---- Parameter assertions -------------------------------------------------
    // Synthesis-safe: generate blocks with undefined module references force
    // an elaboration error in all major synthesis tools.
    generate
        if (TX_FIFO_DEPTH & (TX_FIFO_DEPTH - 1))
            TX_FIFO_DEPTH_must_be_power_of_2 _tx_depth_check_FAILED();
        if (RX_FIFO_DEPTH & (RX_FIFO_DEPTH - 1))
            RX_FIFO_DEPTH_must_be_power_of_2 _rx_depth_check_FAILED();
        if (CLK_HZ / BAUD_RATE < 4)
            BAUD_RATE_too_high_for_CLK_HZ _baud_check_FAILED();
    endgenerate

    // Simulation-friendly versions of the same checks.
    initial begin
        if (TX_FIFO_DEPTH & (TX_FIFO_DEPTH - 1))
            $error("TX_FIFO_DEPTH must be power of 2");
        if (RX_FIFO_DEPTH & (RX_FIFO_DEPTH - 1))
            $error("RX_FIFO_DEPTH must be power of 2");
        if (CLK_HZ / BAUD_RATE < 4)
            $error("BAUD_RATE too high for CLK_HZ: divider must be >= 4");
        // Check realized baud error: |actual_baud - BAUD_RATE| / BAUD_RATE
        // actual_baud = CLK_HZ / divider, divider = CLK_HZ / BAUD_RATE
        begin
            integer div, actual, err;
            div    = CLK_HZ / BAUD_RATE;
            actual = CLK_HZ / div;
            err    = (actual > BAUD_RATE) ? actual - BAUD_RATE
                                          : BAUD_RATE - actual;
            if (err * 100 / BAUD_RATE > 3)
                $warning("Baud rate error > 3%%: CLK_HZ=%0d BAUD_RATE=%0d divider=%0d actual=%0d",
                         CLK_HZ, BAUD_RATE, div, actual);
        end
    end

    // ---- Constants -----------------------------------------------------------
    localparam DR_W = 32;

    // Commands
    localparam [3:0] CMD_NOP     = 4'h0;
    localparam [3:0] CMD_TX_PUSH = 4'h1;
    localparam [3:0] CMD_RX_POP  = 4'h2;
    localparam [3:0] CMD_TXRX    = 4'h3;
    localparam [3:0] CMD_CONFIG  = 4'hE;
    localparam [3:0] CMD_RESET   = 4'hF;

    // UART baud divider (clocks per bit)
    localparam BAUD_DIV = CLK_HZ / BAUD_RATE;

    // Number of frame bits: start + 8 data + [parity] + stop
    localparam FRAME_BITS = (PARITY != 0) ? 11 : 10;

    // Config registers
    localparam [31:0] VERSION    = `FCAPZ_EJTAGUART_VERSION_REG;
    localparam [31:0] FEATURES   = {PARITY[1:0], TX_FIFO_DEPTH[13:0], RX_FIFO_DEPTH[13:0], 2'b00};
    localparam [31:0] BAUD_DIV_R = BAUD_DIV[31:0];

    // FIFO pointer widths
    localparam TX_AW = $clog2(TX_FIFO_DEPTH);
    localparam RX_AW = $clog2(RX_FIFO_DEPTH);

    // ========================================================================
    //  TCK domain registers
    // ========================================================================

    // 32-bit shift register
    reg [DR_W-1:0] sr;
    assign tdo = sr[0];

    // Parsed command fields
    wire [7:0] sr_tx_byte = sr[7:0];
    wire [3:0] sr_cmd     = sr[31:28];

    // Pipeline result registers (visible at next CAPTURE)
    reg [7:0]  rx_byte_reg;
    reg        rx_valid_reg;

    // Config byte register (for CONFIG command results)
    reg [7:0]  config_byte_reg;
    reg        config_valid_reg;

    // Sticky error flags
    reg        rx_overflow_sticky;
    reg        frame_err_sticky;

    // FIFO reset control
    reg        fifo_rst;
    reg [2:0]  fifo_rst_cnt;

    // RX FIFO reset sync into uart_clk domain
    (* ASYNC_REG = "TRUE" *) reg rx_fifo_rst_sync1, rx_fifo_rst_sync2;

    always @(posedge uart_clk or posedge uart_rst) begin
        if (uart_rst) begin
            rx_fifo_rst_sync1 <= 1'b1;
            rx_fifo_rst_sync2 <= 1'b1;
        end else begin
            rx_fifo_rst_sync1 <= fifo_rst;
            rx_fifo_rst_sync2 <= rx_fifo_rst_sync1;
        end
    end

    // ---- TX FIFO -------------------------------------------------------------
    wire        tx_fifo_full;
    reg         tx_fifo_rd_en_r;
    wire [7:0]  tx_fifo_rdata;
    wire        tx_fifo_empty;
    wire [TX_AW:0] tx_fifo_wr_count;
    wire        tx_fifo_wr_rst_busy_unused;
    wire        tx_fifo_rd_rst_busy_unused;

    reg         tx_wr_pulse;

    fcapz_async_fifo #(
        .DATA_W(8), .DEPTH(TX_FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO(USE_BEHAV_ASYNC_FIFO)
    ) u_tx_fifo (
        .wr_clk  (tck),
        .wr_rst  (fifo_rst | uart_rst),
        .wr_en   (tx_wr_pulse),
        .wr_data (sr_tx_byte),
        .wr_full (tx_fifo_full),
        .rd_clk  (uart_clk),
        .rd_rst  (rx_fifo_rst_sync2 | uart_rst),  // synced to uart_clk
        .rd_en   (tx_fifo_rd_en_r),
        .rd_data (tx_fifo_rdata),
        .rd_empty(tx_fifo_empty),
        .rd_rst_busy(tx_fifo_rd_rst_busy_unused),
        .rd_count(),
        .wr_count(tx_fifo_wr_count),
        .wr_rst_busy(tx_fifo_wr_rst_busy_unused)
    );

    // tx_free: TX_FIFO_DEPTH - wr_count, saturated to 255
    // Use 32-bit arithmetic then truncate safely
    wire [TX_AW:0] tx_used    = tx_fifo_wr_count;
    wire [31:0]    tx_free_32 = TX_FIFO_DEPTH - tx_used;
    wire [7:0]     tx_free_sat = (tx_free_32 > 32'd255) ? 8'd255 : tx_free_32[7:0];

    // ---- RX FIFO -------------------------------------------------------------
    wire        rx_fifo_full;
    wire [7:0]  rx_fifo_rdata;
    wire        rx_fifo_empty;
    wire [RX_AW:0] rx_fifo_rd_count;
    wire        rx_fifo_wr_rst_busy_unused;
    wire        rx_fifo_rd_rst_busy_unused;

    reg         rx_rd_pulse;
    reg         rx_fifo_wr_en_r;
    reg  [7:0]  rx_fifo_wr_data_r;

    fcapz_async_fifo #(
        .DATA_W(8), .DEPTH(RX_FIFO_DEPTH),
        .USE_BEHAV_ASYNC_FIFO(USE_BEHAV_ASYNC_FIFO)
    ) u_rx_fifo (
        .wr_clk  (uart_clk),
        .wr_rst  (rx_fifo_rst_sync2 | uart_rst),
        .wr_en   (rx_fifo_wr_en_r),
        .wr_data (rx_fifo_wr_data_r),
        .wr_full (rx_fifo_full),
        .rd_clk  (tck),
        .rd_rst  (fifo_rst),  // synchronous to tck (rd_clk domain)
        .rd_en   (rx_rd_pulse),
        .rd_data (rx_fifo_rdata),
        .rd_empty(rx_fifo_empty),
        .rd_rst_busy(rx_fifo_rd_rst_busy_unused),
        .rd_count(rx_fifo_rd_count),
        .wr_count(),
        .wr_rst_busy(rx_fifo_wr_rst_busy_unused)
    );

    wire rx_ready = !rx_fifo_empty;

    // ---- Config register map -------------------------------------------------
    // Byte-addressed, 16-byte address space (bits [3:0] decoded, upper bits ignored).
    // Addresses 0x00-0x0F map to 4 config registers; all other addresses
    // alias into this range (intentional — keeps the decoder minimal).
    reg [7:0] config_byte;
    always @(*) begin
        case (sr_tx_byte[3:0])  // byte address (low nibble only)
            4'h0: config_byte = VERSION[7:0];
            4'h1: config_byte = VERSION[15:8];
            4'h2: config_byte = VERSION[23:16];
            4'h3: config_byte = VERSION[31:24];
            // Mirror VERSION at the old v0.3 VERSION byte window so manual
            // CONFIG probing at 0x4..0x7 sees an intentional identity word.
            4'h4: config_byte = VERSION[7:0];
            4'h5: config_byte = VERSION[15:8];
            4'h6: config_byte = VERSION[23:16];
            4'h7: config_byte = VERSION[31:24];
            4'h8: config_byte = FEATURES[7:0];
            4'h9: config_byte = FEATURES[15:8];
            4'hA: config_byte = FEATURES[23:16];
            4'hB: config_byte = FEATURES[31:24];
            4'hC: config_byte = BAUD_DIV_R[7:0];
            4'hD: config_byte = BAUD_DIV_R[15:8];
            4'hE: config_byte = BAUD_DIV_R[23:16];
            4'hF: config_byte = BAUD_DIV_R[31:24];
        endcase
    end

    // ---- Status bits ---------------------------------------------------------
    // [24]=RX_READY, [25:27]=0, [28]=RX_VALID, [29]=TX_FULL,
    // [30]=RX_OVERFLOW, [31]=FRAME_ERR
    wire [7:0] status_byte = {frame_err_sticky, rx_overflow_sticky,
                              tx_fifo_full, rx_valid_reg | config_valid_reg,
                              3'b000, rx_ready};

    // ---- Capture data mux ----------------------------------------------------
    wire [7:0] capture_rx_byte = config_valid_reg ? config_byte_reg : rx_byte_reg;

    // ---- TCK: CAPTURE / SHIFT / UPDATE logic ---------------------------------
    always @(posedge tck) begin
        // Default: clear single-cycle pulses
        tx_wr_pulse <= 1'b0;
        rx_rd_pulse <= 1'b0;

        // Sticky error flags: set from synced uart_clk signals
        // (cleared only by CMD_RESET below)
        if (rx_overflow_sync2 && !fifo_rst)
            rx_overflow_sticky <= 1'b1;
        if (frame_err_sync2 && !fifo_rst)
            frame_err_sticky <= 1'b1;

        // FIFO reset hold counter
        if (fifo_rst && fifo_rst_cnt != 3'd0) begin
            fifo_rst_cnt <= fifo_rst_cnt - 1;
        end else if (fifo_rst && fifo_rst_cnt == 3'd0) begin
            fifo_rst <= 1'b0;
        end

        if (sel) begin
            if (capture) begin
                // Load shift-out register
                sr <= {status_byte, 8'b0, tx_free_sat, capture_rx_byte};

            end else if (shift) begin
                sr <= {tdi, sr[DR_W-1:1]};

            end else if (update) begin
                // Clear pipeline valid flags by default
                rx_valid_reg    <= 1'b0;
                config_valid_reg <= 1'b0;

                case (sr_cmd)
                    CMD_NOP: begin
                        // No action
                    end

                    CMD_TX_PUSH: begin
                        if (!tx_fifo_full) begin
                            tx_wr_pulse <= 1'b1;
                        end
                    end

                    CMD_RX_POP: begin
                        if (!rx_fifo_empty) begin
                            rx_byte_reg  <= rx_fifo_rdata;
                            rx_valid_reg <= 1'b1;
                            rx_rd_pulse  <= 1'b1;
                        end
                    end

                    CMD_TXRX: begin
                        // TX part
                        if (!tx_fifo_full) begin
                            tx_wr_pulse <= 1'b1;
                        end
                        // RX part
                        if (!rx_fifo_empty) begin
                            rx_byte_reg  <= rx_fifo_rdata;
                            rx_valid_reg <= 1'b1;
                            rx_rd_pulse  <= 1'b1;
                        end
                    end

                    CMD_CONFIG: begin
                        config_byte_reg  <= config_byte;
                        config_valid_reg <= 1'b1;
                    end

                    CMD_RESET: begin
                        fifo_rst         <= 1'b1;
                        fifo_rst_cnt     <= 3'd4;
                        rx_overflow_sticky <= 1'b0;
                        frame_err_sticky   <= 1'b0;
                        rx_valid_reg     <= 1'b0;
                        config_valid_reg <= 1'b0;
                        rx_byte_reg      <= 8'b0;
                    end

                    default: begin
                        // Unknown command: NOP
                    end
                endcase
            end
        end
    end

    // ---- Sticky error flags (set from uart_clk domain, synced to TCK) --------
    reg rx_overflow_uart;
    reg frame_err_uart;

    // Sync into TCK domain
    (* ASYNC_REG = "TRUE" *) reg rx_overflow_sync1, rx_overflow_sync2;
    (* ASYNC_REG = "TRUE" *) reg frame_err_sync1, frame_err_sync2;

    always @(posedge tck) begin
        rx_overflow_sync1 <= rx_overflow_uart;
        rx_overflow_sync2 <= rx_overflow_sync1;
        frame_err_sync1   <= frame_err_uart;
        frame_err_sync2   <= frame_err_sync1;
    end

    // ========================================================================
    //  UART TX module (uart_clk domain)
    // ========================================================================
    //
    // Simple shift-register TX. Reads from TX FIFO (FWFT), serializes
    // one byte at a time: start + 8 data + [parity] + stop.

    reg [3:0]  tx_bit_cnt;     // counts bits remaining in frame
    reg [10:0] tx_sr;          // shift register: frame bits, LSB first
    reg        tx_active;
    reg [31:0] tx_baud_cnt;

    assign uart_txd = tx_active ? tx_sr[0] : 1'b1;

    always @(posedge uart_clk or posedge uart_rst) begin
        if (uart_rst) begin
            tx_active      <= 1'b0;
            tx_baud_cnt    <= 0;
            tx_bit_cnt     <= 0;
            tx_sr          <= 11'h7FF;
            tx_fifo_rd_en_r <= 1'b0;
        end else begin
            tx_fifo_rd_en_r <= 1'b0;

            if (!tx_active) begin
                if (!tx_fifo_empty) begin
                    // Build frame in shift register: LSB shifts out first
                    // start(0), d0..d7, [parity], stop(1)
                    if (PARITY == 0)
                        // 10-bit frame: start+8data+stop.  SR is 11 wide
                        // to support parity case; MSB pad is never shifted out
                        // (FRAME_BITS=10, only bits [9:0] are transmitted).
                        tx_sr <= {1'b1, 1'b1, tx_fifo_rdata, 1'b0};  // [10]=pad, [9]=stop, [8:1]=data, [0]=start
                    else if (PARITY == 1)
                        tx_sr <= {1'b1, ^tx_fifo_rdata, tx_fifo_rdata, 1'b0};  // stop, parity(even), d7..d0, start
                    else
                        tx_sr <= {1'b1, ~(^tx_fifo_rdata), tx_fifo_rdata, 1'b0};  // stop, parity(odd), d7..d0, start

                    tx_bit_cnt     <= FRAME_BITS[3:0];
                    tx_baud_cnt    <= BAUD_DIV - 1;
                    tx_active      <= 1'b1;
                    tx_fifo_rd_en_r <= 1'b1;  // pop FIFO (FWFT: data was on rd_data)
                end
            end else begin
                if (tx_baud_cnt == 0) begin
                    tx_baud_cnt <= BAUD_DIV - 1;
                    tx_sr       <= {1'b1, tx_sr[10:1]};  // shift right, fill with idle
                    tx_bit_cnt  <= tx_bit_cnt - 1;
                    if (tx_bit_cnt == 1) begin
                        tx_active <= 1'b0;  // done after this bit finishes
                    end
                end else begin
                    tx_baud_cnt <= tx_baud_cnt - 1;
                end
            end
        end
    end

    // ========================================================================
    //  UART RX module (uart_clk domain)
    // ========================================================================
    //
    // Center-sampling receiver. Uses a baud-rate counter to sample at
    // the center of each bit period. Start-bit detection triggers the FSM.
    // Minimum BAUD_DIV is 4 (enforced by parameter assertion).

    // 2-FF synchronizer for uart_rxd
    (* ASYNC_REG = "TRUE" *) reg rxd_sync1, rxd_sync2;
    always @(posedge uart_clk or posedge uart_rst) begin
        if (uart_rst) begin
            rxd_sync1 <= 1'b1;
            rxd_sync2 <= 1'b1;
        end else begin
            rxd_sync1 <= uart_rxd;
            rxd_sync2 <= rxd_sync1;
        end
    end

    localparam HALF_BAUD = BAUD_DIV / 2;

    reg [31:0] rx_baud_cnt;
    reg [3:0]  rx_bit_idx;     // 0=start, 1-8=data, 9=parity/stop, 10=stop(parity mode)
    reg [7:0]  rx_shift_reg;
    reg        rx_active;

    always @(posedge uart_clk or posedge uart_rst) begin
        if (uart_rst) begin
            rx_active          <= 1'b0;
            rx_baud_cnt        <= 0;
            rx_bit_idx         <= 0;
            rx_shift_reg       <= 8'b0;
            rx_fifo_wr_en_r    <= 1'b0;
            rx_fifo_wr_data_r  <= 8'b0;
            rx_overflow_uart   <= 1'b0;
            frame_err_uart     <= 1'b0;
        end else begin
            rx_fifo_wr_en_r <= 1'b0;

            // Clear sticky flags when FIFO reset is active
            if (rx_fifo_rst_sync2) begin
                rx_overflow_uart <= 1'b0;
                frame_err_uart   <= 1'b0;
            end

            if (!rx_active) begin
                // Wait for start bit (low after 2-FF sync)
                if (rxd_sync2 == 1'b0) begin
                    rx_active   <= 1'b1;
                    rx_baud_cnt <= HALF_BAUD - 1;  // sample at center of start bit
                    rx_bit_idx  <= 0;
                end
            end else begin
                if (rx_baud_cnt == 0) begin
                    rx_baud_cnt <= BAUD_DIV - 1;  // next bit center

                    if (rx_bit_idx == 0) begin
                        // Center of start bit: verify it's still low
                        if (rxd_sync2) begin
                            rx_active <= 1'b0;  // false start
                        end else begin
                            rx_bit_idx <= 1;
                        end
                    end else if (rx_bit_idx <= 8) begin
                        // Data bits (LSB first)
                        rx_shift_reg[rx_bit_idx - 1] <= rxd_sync2;
                        rx_bit_idx <= rx_bit_idx + 1;
                    end else if (PARITY != 0 && rx_bit_idx == 9) begin
                        // Parity bit check
                        if (PARITY == 1) begin
                            if ((^rx_shift_reg) != rxd_sync2)
                                frame_err_uart <= 1'b1;
                        end else begin
                            if (~(^rx_shift_reg) != rxd_sync2)
                                frame_err_uart <= 1'b1;
                        end
                        rx_bit_idx <= rx_bit_idx + 1;
                    end else if (rx_bit_idx == (PARITY != 0 ? 4'd10 : 4'd9)) begin
                        // Stop bit: sample at center
                        if (!rxd_sync2)
                            frame_err_uart <= 1'b1;

                        // Write received byte to RX FIFO
                        if (!rx_fifo_full) begin
                            rx_fifo_wr_en_r   <= 1'b1;
                            rx_fifo_wr_data_r <= rx_shift_reg;
                        end else begin
                            rx_overflow_uart <= 1'b1;
                        end

                        // Continue to "wait for stop end" state
                        rx_bit_idx  <= rx_bit_idx + 1;
                        rx_baud_cnt <= HALF_BAUD - 1;  // half bit to end of stop
                    end else begin
                        // End of stop bit period. If the synchronized RX
                        // line is already low, a back-to-back frame has
                        // started with essentially no idle gap. Re-arm
                        // immediately instead of dropping to idle for one
                        // cycle, which makes zero-delay internal loopback
                        // much more robust.
                        if (!rxd_sync2) begin
                            rx_baud_cnt <= HALF_BAUD - 1;
                            rx_bit_idx  <= 0;
                        end else begin
                            rx_active <= 1'b0;
                        end
                    end
                end else begin
                    rx_baud_cnt <= rx_baud_cnt - 1;
                end
            end
        end
    end

    // ---- Initial values (for simulation) -------------------------------------
    initial begin
        sr                  = {DR_W{1'b0}};
        rx_byte_reg         = 8'b0;
        rx_valid_reg        = 1'b0;
        config_byte_reg     = 8'b0;
        config_valid_reg    = 1'b0;
        rx_overflow_sticky  = 1'b0;
        frame_err_sticky    = 1'b0;
        fifo_rst            = 1'b0;
        fifo_rst_cnt        = 3'b0;
        tx_wr_pulse         = 1'b0;
        rx_rd_pulse         = 1'b0;
        rx_overflow_sync1   = 1'b0;
        rx_overflow_sync2   = 1'b0;
        frame_err_sync1     = 1'b0;
        frame_err_sync2     = 1'b0;

        tx_active           = 1'b0;
        tx_baud_cnt         = 0;
        tx_bit_cnt          = 0;
        tx_sr               = 11'h7FF;
        tx_fifo_rd_en_r     = 1'b0;

        rx_active           = 1'b0;
        rx_baud_cnt         = 0;
        rx_bit_idx          = 0;
        rx_shift_reg        = 8'b0;
        rx_fifo_wr_en_r     = 1'b0;
        rx_fifo_wr_data_r   = 8'b0;
        rx_overflow_uart    = 1'b0;
        frame_err_uart      = 1'b0;
        rxd_sync1           = 1'b1;
        rxd_sync2           = 1'b1;
        rx_fifo_rst_sync1   = 1'b0;
        rx_fifo_rst_sync2   = 1'b0;
    end

endmodule
