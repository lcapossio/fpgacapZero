// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// UART-driven virtual JTAG TAP (vendor-agnostic).
//
// Presents the standard fpgacapZero TAP interface (tck, tdi, tdo, capture,
// shift, update, sel) to the existing core plumbing -- jtag_reg_iface,
// jtag_burst_read, fcapz_ela, fcapz_eio -- but sources the DR scans from a
// UART byte stream instead of a hard JTAG TAP block.
//
// Why this exists
// ---------------
// Some boards give the fabric no JTAG at all.  The Forgix board (Efinix Trion
// T8F49 + RP2354) is the reference case: its T8 has no configuration flash and
// is reconfigured at every power-up by the RP2354 over a *write-only* passive
// SPI link.  The T8's JTAG pins are bonded out nowhere -- not to a header, not
// to a test point (confirmed against the board schematic; the only debug
// connector is an ARM SWD Tag-Connect for the RP2354).  The hard JTAG User TAP
// blocks that fcapz_ela_efinix binds are therefore unreachable on that board.
//
// Two of the 18 fabric header pins carry a UART instead, so the host reaches
// the core over serial.  Because this module reproduces the TAP contract
// exactly, no core RTL changes: the vendor TAP wrapper is simply swapped for
// this one.  Nothing here is Efinix-specific -- any JTAG-less FPGA can use it.
//
// Wire protocol (host -> fabric), little-endian:
//   SOF   0x5A
//   CMD   1 byte
//   ...   command-specific payload
//
//   CMD_SCAN (0x01): chain[7:0], width[15:0], then ceil(width/8) payload
//                    bytes shifted in LSB-first (byte 0 = DR bits [7:0]).
//                    Reply carries the same number of captured TDO bytes.
//   CMD_IDLE (0x02): cycles[15:0] -- run tck with sel deasserted, the
//                    equivalent of OpenOCD's "runtest N".  Lets a read settle
//                    between the address scan and the data scan.
//   CMD_INFO (0x03): no payload.  Reply is the identity block below.
//   CMD_RST  (0x0F): no payload.  Returns all chains to an idle TAP state.
//
// Replies are framed the same way with SOF 0xA5:
//   SOF 0xA5, STATUS, payload...
// STATUS is 0x00 on success, or one of the STAT_* codes below.  A framing
// error resynchronises on the next SOF, so a half-written command cannot
// wedge the link -- the host just sees STAT_BAD_FRAME and retries.
//
// Parameters
//   CLK_HZ      - fabric clock frequency in Hz
//   BAUD_RATE   - UART baud rate; CLK_HZ/BAUD_RATE must be >= 4
//   NUM_CHAINS  - number of user chains exposed via sel[]
//   MAX_DR_BITS - largest DR width accepted (256 covers the burst chain)

module fcapz_uart_tap #(
    parameter CLK_HZ      = 50_000_000,
    parameter BAUD_RATE   = 1_000_000,
    parameter NUM_CHAINS  = 4,
    parameter MAX_DR_BITS = 256
) (
    input  wire                   clk,
    input  wire                   arst,

    // UART pins (to the RP2354 passthrough, or any USB-serial cable)
    input  wire                   uart_rxd,
    output wire                   uart_txd,

    // fpgacapZero TAP interface -- shared strobes, per-chain select.
    // Mirrors real JTAG: one TAP, the IR selects which chain is active.
    output wire                   tck,
    output wire                   tdi,
    input  wire [NUM_CHAINS-1:0]  tdo,
    output wire                   capture,
    output wire                   shift,
    output wire                   update,
    output wire [NUM_CHAINS-1:0]  sel
);

    // ------------------------------------------------------------------
    //  Protocol constants
    // ------------------------------------------------------------------
    localparam [7:0] SOF_CMD   = 8'h5A;
    localparam [7:0] SOF_RSP   = 8'hA5;

    localparam [7:0] CMD_SCAN  = 8'h01;
    localparam [7:0] CMD_IDLE  = 8'h02;
    localparam [7:0] CMD_INFO  = 8'h03;
    localparam [7:0] CMD_RST   = 8'h0F;

    localparam [7:0] STAT_OK        = 8'h00;
    localparam [7:0] STAT_BAD_FRAME = 8'h01;
    localparam [7:0] STAT_BAD_CHAIN = 8'h02;
    localparam [7:0] STAT_BAD_WIDTH = 8'h03;

    // Identity block returned by CMD_INFO, so the host can probe the bridge
    // before it probes the core behind it:
    //   byte 0..3 : magic "FCZU"  (0x46 0x43 0x5A 0x55)
    //   byte 4    : protocol version
    //   byte 5    : NUM_CHAINS
    //   byte 6..7 : MAX_DR_BITS, little-endian
    localparam [7:0] PROTO_VERSION = 8'h01;
    localparam INFO_BYTES = 8;

    localparam MAX_DR_BYTES = (MAX_DR_BITS + 7) / 8;

    // Guard the baud divider the same way fcapz_ejtaguart does: a divider
    // below 4 cannot sample the start bit reliably.
    localparam BAUD_DIV = CLK_HZ / BAUD_RATE;

    // synthesis translate_off
    initial begin
        if (CLK_HZ / BAUD_RATE < 4)
            $error("BAUD_RATE too high for CLK_HZ: divider must be >= 4");
        if (NUM_CHAINS < 1)
            $error("NUM_CHAINS must be >= 1");
    end
    // synthesis translate_on

    // ------------------------------------------------------------------
    //  UART receiver -- 8N1, 16x-free oversampling at the bit midpoint
    // ------------------------------------------------------------------
    localparam BAUD_CNT_W = $clog2(BAUD_DIV);

    // Two-stage synchroniser: uart_rxd is asynchronous to clk.
    (* ASYNC_REG = "TRUE" *) reg rxd_meta, rxd_sync;
    always @(posedge clk or posedge arst) begin
        if (arst) begin
            rxd_meta <= 1'b1;
            rxd_sync <= 1'b1;
        end else begin
            rxd_meta <= uart_rxd;
            rxd_sync <= rxd_meta;
        end
    end

    reg                   rx_busy;
    reg [BAUD_CNT_W:0]    rx_cnt;
    reg [3:0]             rx_bit;
    reg [7:0]             rx_sr;
    reg [7:0]             rx_data;
    reg                   rx_valid;   // one-clk strobe

    always @(posedge clk or posedge arst) begin
        if (arst) begin
            rx_busy  <= 1'b0;
            rx_cnt   <= 0;
            rx_bit   <= 4'd0;
            rx_sr    <= 8'h0;
            rx_data  <= 8'h0;
            rx_valid <= 1'b0;
        end else begin
            rx_valid <= 1'b0;
            if (!rx_busy) begin
                // Idle: wait for the falling edge that starts a frame, then
                // aim at the middle of the start bit.
                if (!rxd_sync) begin
                    rx_busy <= 1'b1;
                    rx_cnt  <= BAUD_DIV / 2;
                    rx_bit  <= 4'd0;
                end
            end else if (rx_cnt != 0) begin
                rx_cnt <= rx_cnt - 1'b1;
            end else begin
                rx_cnt <= BAUD_DIV - 1;
                if (rx_bit == 4'd0) begin
                    // Midpoint of the start bit.  A high here is noise, not a
                    // frame -- abandon it rather than shifting in garbage.
                    if (rxd_sync) rx_busy <= 1'b0;
                    else          rx_bit  <= 4'd1;
                end else if (rx_bit <= 4'd8) begin
                    rx_sr  <= {rxd_sync, rx_sr[7:1]};   // LSB first
                    rx_bit <= rx_bit + 1'b1;
                end else begin
                    // Stop bit.  Accept the byte even if the stop bit is low
                    // (framing error); the command parser resynchronises on
                    // SOF, which recovers faster than dropping bytes here.
                    rx_data  <= rx_sr;
                    rx_valid <= 1'b1;
                    rx_busy  <= 1'b0;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    //  UART transmitter -- 8N1
    // ------------------------------------------------------------------
    reg                rt_busy;
    reg [BAUD_CNT_W:0] tx_cnt;
    reg [3:0]          tx_bit;
    reg [9:0]          tx_sr;      // {stop, data[7:0], start}
    reg [7:0]          tx_data;
    reg                tx_start;   // one-clk request

    assign uart_txd = rt_busy ? tx_sr[0] : 1'b1;

    always @(posedge clk or posedge arst) begin
        if (arst) begin
            rt_busy <= 1'b0;
            tx_cnt  <= 0;
            tx_bit  <= 4'd0;
            tx_sr   <= 10'h3FF;
        end else if (!rt_busy) begin
            if (tx_start) begin
                tx_sr   <= {1'b1, tx_data, 1'b0};
                rt_busy <= 1'b1;
                tx_cnt  <= BAUD_DIV - 1;
                tx_bit  <= 4'd0;
            end
        end else if (tx_cnt != 0) begin
            tx_cnt <= tx_cnt - 1'b1;
        end else begin
            tx_cnt <= BAUD_DIV - 1;
            tx_sr  <= {1'b1, tx_sr[9:1]};
            tx_bit <= tx_bit + 1'b1;
            if (tx_bit == 4'd9) rt_busy <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    //  Scan buffer
    //
    //  One buffer serves both directions: the host's payload is shifted in
    //  from the MSB end as it arrives, the captured TDO replaces it bit by
    //  bit during the scan, and the result is streamed straight back out.
    //  That keeps a 256-bit burst scan down to a single register bank.
    // ------------------------------------------------------------------
    reg [MAX_DR_BITS-1:0]      scan_buf;
    reg [15:0]                 scan_width;
    reg [15:0]                 scan_bits_left;
    reg [15:0]                 byte_count;   // payload bytes in/out
    reg [15:0]                 byte_index;
    reg [7:0]                  chain_sel;
    reg [15:0]                 idle_cycles;
    reg [7:0]                  status;

    // ------------------------------------------------------------------
    //  TAP drive
    //
    //  tck is generated as a two-phase toggle: the FSM presents tdi and the
    //  strobes while tck is low, then raises tck so the core samples on its
    //  rising edge.  tdo is combinational out of jtag_reg_iface (tdo = sr[0]),
    //  so it is sampled in the low phase, before the edge that shifts it.
    // ------------------------------------------------------------------
    reg tck_r, tdi_r, cap_r, shf_r, upd_r;
    reg [NUM_CHAINS-1:0] sel_r;

    assign tck     = tck_r;
    assign tdi     = tdi_r;
    assign capture = cap_r;
    assign shift   = shf_r;
    assign update  = upd_r;
    assign sel     = sel_r;

    // TDO of the currently selected chain.
    reg tdo_mux;
    integer ci;
    always @(*) begin
        tdo_mux = 1'b0;
        for (ci = 0; ci < NUM_CHAINS; ci = ci + 1)
            if (sel_r[ci]) tdo_mux = tdo[ci];
    end

    // ------------------------------------------------------------------
    //  Command FSM
    // ------------------------------------------------------------------
    localparam [4:0] S_SOF        = 5'd0;
    localparam [4:0] S_CMD        = 5'd1;
    localparam [4:0] S_SCAN_CHAIN = 5'd2;
    localparam [4:0] S_SCAN_W0    = 5'd3;
    localparam [4:0] S_SCAN_W1    = 5'd4;
    localparam [4:0] S_SCAN_PAY   = 5'd5;
    localparam [4:0] S_CAP_LO     = 5'd6;
    localparam [4:0] S_CAP_HI     = 5'd7;
    localparam [4:0] S_SHF_LO     = 5'd8;
    localparam [4:0] S_SHF_HI     = 5'd9;
    localparam [4:0] S_UPD_LO     = 5'd10;
    localparam [4:0] S_UPD_HI     = 5'd11;
    localparam [4:0] S_IDLE_C0    = 5'd12;
    localparam [4:0] S_IDLE_C1    = 5'd13;
    localparam [4:0] S_IDLE_RUN_L = 5'd14;
    localparam [4:0] S_IDLE_RUN_H = 5'd15;
    localparam [4:0] S_RSP_SOF    = 5'd16;
    localparam [4:0] S_RSP_STAT   = 5'd17;
    localparam [4:0] S_RSP_PAY    = 5'd18;
    localparam [4:0] S_RSP_WAIT   = 5'd19;

    reg [4:0] state;
    reg [4:0] rsp_next;      // state to enter once the reply has drained
    reg       rsp_is_info;

    // INFO payload, indexed byte-wise during the reply.
    reg [7:0] info_byte;
    always @(*) begin
        case (byte_index[2:0])
            3'd0: info_byte = 8'h46;               // 'F'
            3'd1: info_byte = 8'h43;               // 'C'
            3'd2: info_byte = 8'h5A;               // 'Z'
            3'd3: info_byte = 8'h55;               // 'U'
            3'd4: info_byte = PROTO_VERSION;
            3'd5: info_byte = NUM_CHAINS[7:0];
            3'd6: info_byte = MAX_DR_BITS[7:0];
            default: info_byte = MAX_DR_BITS[15:8];
        endcase
    end

    always @(posedge clk or posedge arst) begin
        if (arst) begin
            state          <= S_SOF;
            tck_r          <= 1'b0;
            tdi_r          <= 1'b0;
            cap_r          <= 1'b0;
            shf_r          <= 1'b0;
            upd_r          <= 1'b0;
            sel_r          <= {NUM_CHAINS{1'b0}};
            scan_buf       <= {MAX_DR_BITS{1'b0}};
            scan_width     <= 16'd0;
            scan_bits_left <= 16'd0;
            byte_count     <= 16'd0;
            byte_index     <= 16'd0;
            chain_sel      <= 8'd0;
            idle_cycles    <= 16'd0;
            status         <= STAT_OK;
            tx_start       <= 1'b0;
            tx_data        <= 8'h0;
            rsp_next       <= S_SOF;
            rsp_is_info    <= 1'b0;
        end else begin
            tx_start <= 1'b0;

            case (state)
            // ---- command parse -------------------------------------------
            S_SOF: begin
                sel_r <= {NUM_CHAINS{1'b0}};
                if (rx_valid && rx_data == SOF_CMD) state <= S_CMD;
            end

            S_CMD: begin
                if (rx_valid) begin
                    status      <= STAT_OK;
                    byte_index  <= 16'd0;
                    rsp_is_info <= 1'b0;
                    case (rx_data)
                    CMD_SCAN: state <= S_SCAN_CHAIN;
                    CMD_IDLE: state <= S_IDLE_C0;
                    CMD_INFO: begin
                        rsp_is_info <= 1'b1;
                        byte_count  <= INFO_BYTES[15:0];
                        state       <= S_RSP_SOF;
                    end
                    CMD_RST: begin
                        scan_buf   <= {MAX_DR_BITS{1'b0}};
                        byte_count <= 16'd0;
                        state      <= S_RSP_SOF;
                    end
                    default: begin
                        // Unknown opcode: report it rather than silently
                        // consuming an unknown-length payload.
                        status     <= STAT_BAD_FRAME;
                        byte_count <= 16'd0;
                        state      <= S_RSP_SOF;
                    end
                    endcase
                end
            end

            S_SCAN_CHAIN: begin
                if (rx_valid) begin
                    chain_sel <= rx_data;
                    state     <= S_SCAN_W0;
                end
            end

            S_SCAN_W0: begin
                if (rx_valid) begin
                    scan_width[7:0] <= rx_data;
                    state           <= S_SCAN_W1;
                end
            end

            S_SCAN_W1: begin
                if (rx_valid) begin
                    scan_width[15:8] <= rx_data;
                    byte_index       <= 16'd0;
                    scan_buf         <= {MAX_DR_BITS{1'b0}};
                    // Validate the width *before* the payload phase.  A bad
                    // width makes the payload length itself untrustworthy, so
                    // there is no safe number of bytes to drain -- reply at
                    // once and let the SOF hunt resynchronise.  (A zero-byte
                    // payload would otherwise park S_SCAN_PAY forever waiting
                    // on a byte the host never sends.)
                    if ({rx_data, scan_width[7:0]} == 16'd0 ||
                        {rx_data, scan_width[7:0]} > MAX_DR_BITS[15:0]) begin
                        status     <= STAT_BAD_WIDTH;
                        byte_count <= 16'd0;
                        state      <= S_RSP_SOF;
                    end else begin
                        state <= S_SCAN_PAY;
                    end
                end
            end

            S_SCAN_PAY: begin
                // The width is known good here, so the payload length is
                // trustworthy: drain it before replying, or the next command
                // would be parsed out of this one's leftover bytes.  A bad
                // chain is latched now and reported after the drain.
                if (chain_sel == 8'd0 || chain_sel > NUM_CHAINS[7:0])
                    status <= STAT_BAD_CHAIN;

                if (rx_valid) begin
                    // Place each byte at its final offset -- byte 0 is DR
                    // bits [7:0].  The buffer was zeroed on entry, so a
                    // payload whose width is not a byte multiple leaves the
                    // unused top bits clear.
                    scan_buf[byte_index[4:0]*8 +: 8] <= rx_data;
                    byte_index <= byte_index + 1'b1;
                    if (byte_index + 1'b1 >= ((scan_width + 16'd7) >> 3)) begin
                        byte_count     <= (scan_width + 16'd7) >> 3;
                        byte_index     <= 16'd0;
                        scan_bits_left <= scan_width;
                        if (status != STAT_OK) begin
                            byte_count <= 16'd0;
                            state      <= S_RSP_SOF;
                        end else begin
                            sel_r <= {{(NUM_CHAINS-1){1'b0}}, 1'b1} << (chain_sel - 8'd1);
                            state <= S_CAP_LO;
                        end
                    end
                end
            end

            // ---- DR scan: capture, shift x width, update -----------------
            S_CAP_LO: begin
                // scan_buf is already bit-0-aligned (see S_SCAN_PAY), so the
                // shift path can start straight away.
                cap_r    <= 1'b1;
                tck_r    <= 1'b0;
                state    <= S_CAP_HI;
            end

            S_CAP_HI: begin
                tck_r <= 1'b1;
                state <= S_SHF_LO;
            end

            S_SHF_LO: begin
                cap_r <= 1'b0;
                tck_r <= 1'b0;
                if (scan_bits_left == 16'd0) begin
                    shf_r <= 1'b0;
                    upd_r <= 1'b1;
                    state <= S_UPD_HI;
                end else begin
                    shf_r <= 1'b1;
                    tdi_r <= scan_buf[0];
                    state <= S_SHF_HI;
                end
            end

            S_SHF_HI: begin
                tck_r <= 1'b1;
                // Rotate the captured bit into the top: after `scan_width`
                // shifts the buffer holds the TDO word, LSB-first.
                scan_buf       <= {tdo_mux, scan_buf[MAX_DR_BITS-1:1]};
                scan_bits_left <= scan_bits_left - 1'b1;
                state          <= S_SHF_LO;
            end

            S_UPD_HI: begin
                tck_r <= 1'b1;
                state <= S_UPD_LO;
            end

            S_UPD_LO: begin
                tck_r <= 1'b0;
                upd_r <= 1'b0;
                sel_r <= {NUM_CHAINS{1'b0}};
                // The TDO word sits in the high bits after the rotation;
                // bring it back down so byte 0 is DR bits [7:0].
                scan_buf   <= scan_buf >> (MAX_DR_BITS[15:0] - scan_width);
                byte_index <= 16'd0;
                // Trailing clocks.  jtag_reg_iface registers reg_wr_en/rd_en
                // *on* the update edge, so the register bus needs at least one
                // further tck edge to latch the access -- a hard TAP gets that
                // for free from free-running TCK, but this FSM would otherwise
                // stop the clock the instant update deasserts and strand the
                // write until the next scan.  Four gives margin.
                idle_cycles <= 16'd4;
                state       <= S_IDLE_RUN_L;
            end

            // ---- idle / runtest ------------------------------------------
            S_IDLE_C0: begin
                if (rx_valid) begin
                    idle_cycles[7:0] <= rx_data;
                    state            <= S_IDLE_C1;
                end
            end

            S_IDLE_C1: begin
                if (rx_valid) begin
                    idle_cycles[15:8] <= rx_data;
                    byte_count        <= 16'd0;
                    state             <= S_IDLE_RUN_L;
                end
            end

            S_IDLE_RUN_L: begin
                tck_r <= 1'b0;
                if (idle_cycles == 16'd0) state <= S_RSP_SOF;
                else                      state <= S_IDLE_RUN_H;
            end

            S_IDLE_RUN_H: begin
                tck_r       <= 1'b1;
                idle_cycles <= idle_cycles - 1'b1;
                state       <= S_IDLE_RUN_L;
            end

            // ---- reply ---------------------------------------------------
            S_RSP_SOF: begin
                if (!rt_busy && !tx_start) begin
                    tx_data  <= SOF_RSP;
                    tx_start <= 1'b1;
                    state    <= S_RSP_STAT;
                end
            end

            S_RSP_STAT: begin
                if (!rt_busy && !tx_start) begin
                    tx_data  <= status;
                    tx_start <= 1'b1;
                    rsp_next <= (byte_count == 16'd0) ? S_SOF : S_RSP_PAY;
                    state    <= S_RSP_WAIT;
                end
            end

            S_RSP_WAIT: begin
                if (!rt_busy && !tx_start) state <= rsp_next;
            end

            S_RSP_PAY: begin
                if (!rt_busy && !tx_start) begin
                    tx_data  <= rsp_is_info ? info_byte : scan_buf[7:0];
                    tx_start <= 1'b1;
                    if (!rsp_is_info) scan_buf <= scan_buf >> 8;
                    byte_index <= byte_index + 1'b1;
                    rsp_next   <= (byte_index + 1'b1 >= byte_count)
                                  ? S_SOF : S_RSP_PAY;
                    state      <= S_RSP_WAIT;
                end
            end

            default: state <= S_SOF;
            endcase
        end
    end

endmodule
