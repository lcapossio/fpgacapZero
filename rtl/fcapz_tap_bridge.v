// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Byte-stream to virtual JTAG TAP bridge (transport- and vendor-agnostic).
//
// Presents the standard fpgacapZero TAP interface (tck, tdi, tdo, capture,
// shift, update, sel) to the existing core plumbing -- jtag_reg_iface,
// jtag_burst_read, fcapz_ela, fcapz_eio -- but sources the DR scans from a
// stream of bytes rather than a hard JTAG TAP block.
//
// This module owns the protocol only.  It has no idea how the bytes arrive,
// so any physical layer can carry it: see fcapz_uart_tap.v for a UART PHY.
// An SPI, USB-FIFO or FTDI-style PHY drops in the same way -- implement the
// byte interface below and instantiate this.
//
// Why this exists
// ---------------
// Small and cheap FPGA boards frequently expose no user JTAG to the fabric at
// all: the pins are bonded out nowhere, the vendor TAP is unavailable, or the
// only host link is a serial port on a companion MCU.  Because this module
// reproduces the TAP contract exactly, none of the core RTL changes -- the
// vendor TAP wrapper is simply swapped for this one, and the host talks the
// same register protocol it always did.
//
// Byte interface
// --------------
//   rx_data/rx_valid   one received byte, rx_valid high for a single clk
//   tx_data/tx_start   one byte to send, tx_start pulsed for a single clk
//   tx_busy            PHY cannot accept a byte yet
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
//   CMD_BREAD(0x04): chain[7:0], width[15:0], count[15:0], no payload.
//                    Runs `count` back-to-back scans that shift in zeros and
//                    returns their captured TDO words concatenated, one after
//                    another, under a single reply header.  Semantically it is
//                    `count` CMD_SCANs with an all-zero payload -- same TAP
//                    sequence, same trailing clocks -- but it removes the
//                    per-scan round trip, which dominates a burst readback
//                    over USB CDC, and the all-zero request payload with it.
//                    Protocol version 2 and later.
//   CMD_RST  (0x0F): no payload.  Returns all chains to an idle TAP state.
//
// Replies are framed the same way with SOF 0xA5:
//   SOF 0xA5, STATUS, payload...
// STATUS is 0x00 on success, or one of the STAT_* codes below.  Between
// commands the parser hunts for SOF, so leading junk -- the handover noise a
// configuration-pin bridge leaves behind, say -- is skipped.  It is NOT a
// self-recovering protocol: there is no length, checksum or inter-byte
// timeout, so a command truncated mid-field leaves the parser waiting for the
// bytes it is still owed.
//
// Parameters
//   NUM_CHAINS  - number of user chains exposed via sel[]
//   MAX_DR_BITS - largest DR width accepted (256 covers the burst chain)
//   PROTO_EXTRA - reported in the identity block; a PHY may use it to tell
//                 the host something about itself (0 when unused)

module fcapz_tap_bridge #(
    parameter NUM_CHAINS  = 4,
    parameter MAX_DR_BITS = 256,
    parameter PROTO_EXTRA = 0
) (
    input  wire                   clk,
    input  wire                   arst,

    // Byte stream from/to the physical layer
    input  wire [7:0]             rx_data,
    input  wire                   rx_valid,
    output reg  [7:0]             tx_data,
    output reg                    tx_start,
    input  wire                   tx_busy,

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
    localparam [7:0] CMD_BREAD = 8'h04;
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
    //   byte 8    : PROTO_EXTRA (PHY-defined, 0 when unused)
    // 2 added CMD_BREAD.  A version-1 host still works against a version-2
    // bridge: every earlier command is unchanged.
    localparam [7:0] PROTO_VERSION = 8'h02;
    localparam INFO_BYTES = 9;

    localparam MAX_DR_BYTES = (MAX_DR_BITS + 7) / 8;
    // The buffer is rounded up to whole bytes so that the byte-indexed
    // payload write can never run off the end of the vector, whatever
    // MAX_DR_BITS is; the rotation maths below uses BUF_W throughout.
    localparam BUF_W        = MAX_DR_BYTES * 8;
    // $clog2(n) bits address 0..n-1, which is exactly the payload range.
    localparam IDX_W        = (MAX_DR_BYTES <= 1) ? 1 : $clog2(MAX_DR_BYTES);

    // synthesis translate_off
    initial begin
        if (NUM_CHAINS < 1)
            $error("NUM_CHAINS must be >= 1");
        if (MAX_DR_BITS < 8)
            $error("MAX_DR_BITS must be >= 8");
        // scan_width and the identity block both carry the width in 16 bits.
        if (MAX_DR_BITS > 65535)
            $error("MAX_DR_BITS must be <= 65535");
    end
    // synthesis translate_on

    // ------------------------------------------------------------------
    //  Scan buffer
    //
    //  One buffer serves both directions: the host's payload is written in
    //  byte by byte as it arrives, the captured TDO replaces it bit by bit
    //  during the scan, and the result is streamed straight back out.  That
    //  keeps a 256-bit burst scan down to a single register bank.
    // ------------------------------------------------------------------
    reg [BUF_W-1:0]            scan_buf;
    reg [15:0]                 scan_width;
    reg [15:0]                 scan_bits_left;
    reg [15:0]                 byte_count;   // payload bytes in/out
    reg [15:0]                 byte_index;
    reg [7:0]                  chain_sel;
    reg [15:0]                 idle_cycles;
    reg [7:0]                  status;

    // Combinational, deliberately: S_SCAN_PAY both latches this into
    // status and branches on it, and with a one-byte payload both happen
    // on the same cycle.  Reading the register there would see the stale
    // STAT_OK, run a zero-selected scan, and emit BAD_CHAIN followed by a
    // payload byte the host never drains -- desyncing the link.  A UART
    // PHY leaves enough slack to hide that; a PHY that delivers bytes
    // back to back does not.
    wire chain_bad = (chain_sel == 8'd0) || (chain_sel > NUM_CHAINS[7:0]);

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
    localparam [4:0] S_BR_C0      = 5'd20;
    localparam [4:0] S_BR_C1      = 5'd21;
    localparam [4:0] S_BR_NEXT    = 5'd22;

    reg [4:0] state;
    reg [4:0] rsp_next;      // state to enter once the reply has drained
    reg [4:0] idle_next;     // state to enter once the tck idle run finishes
    reg       rsp_is_info;

    // CMD_BREAD: `scans_left` counts the scans still owed, and br_hdr_sent
    // records that the single reply header has already gone out, so the
    // second and later scans stream straight into S_RSP_PAY.
    reg        br_active;
    reg        br_hdr_sent;
    reg [15:0] scans_left;

    // INFO payload, indexed byte-wise during the reply.
    reg [7:0] info_byte;
    always @(*) begin
        case (byte_index[3:0])
            4'd0: info_byte = 8'h46;               // 'F'
            4'd1: info_byte = 8'h43;               // 'C'
            4'd2: info_byte = 8'h5A;               // 'Z'
            4'd3: info_byte = 8'h55;               // 'U'
            4'd4: info_byte = PROTO_VERSION;
            4'd5: info_byte = NUM_CHAINS[7:0];
            4'd6: info_byte = MAX_DR_BITS[7:0];
            4'd7: info_byte = MAX_DR_BITS[15:8];
            default: info_byte = PROTO_EXTRA[7:0];
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
            scan_buf       <= {BUF_W{1'b0}};
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
            idle_next      <= S_RSP_SOF;
            rsp_is_info    <= 1'b0;
            br_active      <= 1'b0;
            br_hdr_sent    <= 1'b0;
            scans_left     <= 16'd0;
        end else begin
            tx_start <= 1'b0;

            case (state)
            // ---- command parse -------------------------------------------
            S_SOF: begin
                sel_r     <= {NUM_CHAINS{1'b0}};
                br_active <= 1'b0;
                if (rx_valid && rx_data == SOF_CMD) state <= S_CMD;
            end

            S_CMD: begin
                if (rx_valid) begin
                    status      <= STAT_OK;
                    byte_index  <= 16'd0;
                    rsp_is_info <= 1'b0;
                    br_hdr_sent <= 1'b0;
                    case (rx_data)
                    CMD_SCAN: state <= S_SCAN_CHAIN;
                    CMD_BREAD: begin
                        // Shares the chain/width parse with CMD_SCAN; the
                        // branch back out is in S_SCAN_W1.
                        br_active <= 1'b1;
                        state     <= S_SCAN_CHAIN;
                    end
                    CMD_IDLE: state <= S_IDLE_C0;
                    CMD_INFO: begin
                        rsp_is_info <= 1'b1;
                        byte_count  <= INFO_BYTES[15:0];
                        state       <= S_RSP_SOF;
                    end
                    CMD_RST: begin
                        scan_buf   <= {BUF_W{1'b0}};
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
                    scan_buf         <= {BUF_W{1'b0}};
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
                        state <= br_active ? S_BR_C0 : S_SCAN_PAY;
                    end
                end
            end

            S_SCAN_PAY: begin
                // The width is known good here, so the payload length is
                // trustworthy: drain it before replying, or the next command
                // would be parsed out of this one's leftover bytes.  A bad
                // chain is latched now and reported after the drain.
                if (chain_bad)
                    status <= STAT_BAD_CHAIN;

                if (rx_valid) begin
                    // Place each byte at its final offset -- byte 0 is DR
                    // bits [7:0].  The buffer was zeroed on entry, so a
                    // payload whose width is not a byte multiple leaves the
                    // unused top bits clear.
                    scan_buf[byte_index[IDX_W-1:0]*8 +: 8] <= rx_data;
                    byte_index <= byte_index + 1'b1;
                    if (byte_index + 1'b1 >= ((scan_width + 16'd7) >> 3)) begin
                        byte_count     <= (scan_width + 16'd7) >> 3;
                        byte_index     <= 16'd0;
                        scan_bits_left <= scan_width;
                        if (chain_bad || status != STAT_OK) begin
                            byte_count <= 16'd0;
                            state      <= S_RSP_SOF;
                        end else begin
                            sel_r <= {{(NUM_CHAINS-1){1'b0}}, 1'b1} << (chain_sel - 8'd1);
                            state <= S_CAP_LO;
                        end
                    end
                end
            end

            // ---- burst read: count, then back-to-back scans --------------
            S_BR_C0: begin
                if (rx_valid) begin
                    scans_left[7:0] <= rx_data;
                    state           <= S_BR_C1;
                end
            end

            S_BR_C1: begin
                if (rx_valid) begin
                    scans_left[15:8] <= rx_data;
                    byte_count       <= (scan_width + 16'd7) >> 3;
                    byte_index       <= 16'd0;
                    scan_bits_left   <= scan_width;
                    scan_buf         <= {BUF_W{1'b0}};
                    // The chain is checked here rather than after a payload
                    // drain: CMD_BREAD has no payload, so there is nothing to
                    // drain and nothing untrustworthy about the length.
                    if (chain_bad) begin
                        status     <= STAT_BAD_CHAIN;
                        byte_count <= 16'd0;
                        state      <= S_RSP_SOF;
                    end else if ({rx_data, scans_left[7:0]} == 16'd0) begin
                        // Zero scans is well defined: an empty reply.
                        byte_count <= 16'd0;
                        state      <= S_RSP_SOF;
                    end else begin
                        sel_r <= {{(NUM_CHAINS-1){1'b0}}, 1'b1} << (chain_sel - 8'd1);
                        state <= S_CAP_LO;
                    end
                end
            end

            S_BR_NEXT: begin
                // One scan's worth of payload has drained; set up the next.
                scans_left     <= scans_left - 1'b1;
                scan_buf       <= {BUF_W{1'b0}};
                scan_bits_left <= scan_width;
                byte_index     <= 16'd0;
                sel_r          <= {{(NUM_CHAINS-1){1'b0}}, 1'b1} << (chain_sel - 8'd1);
                state          <= S_CAP_LO;
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
                scan_buf       <= {tdo_mux, scan_buf[BUF_W-1:1]};
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
                scan_buf   <= scan_buf >> (BUF_W[15:0] - scan_width);
                byte_index <= 16'd0;
                // Trailing clocks.  jtag_reg_iface registers reg_wr_en/rd_en
                // *on* the update edge, so the register bus needs at least one
                // further tck edge to latch the access -- a hard TAP gets that
                // for free from free-running TCK, but this FSM would otherwise
                // stop the clock the instant update deasserts and strand the
                // write until the next scan.  Four gives margin.
                idle_cycles <= 16'd4;
                // Scans after the first in a CMD_BREAD stream have already had
                // their reply header sent, so they resume mid-reply.
                idle_next   <= (br_active && br_hdr_sent) ? S_RSP_PAY : S_RSP_SOF;
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
                    idle_next         <= S_RSP_SOF;
                    state             <= S_IDLE_RUN_L;
                end
            end

            S_IDLE_RUN_L: begin
                tck_r <= 1'b0;
                if (idle_cycles == 16'd0) state <= idle_next;
                else                      state <= S_IDLE_RUN_H;
            end

            S_IDLE_RUN_H: begin
                tck_r       <= 1'b1;
                idle_cycles <= idle_cycles - 1'b1;
                state       <= S_IDLE_RUN_L;
            end

            // ---- reply ---------------------------------------------------
            S_RSP_SOF: begin
                if (!tx_busy && !tx_start) begin
                    tx_data  <= SOF_RSP;
                    tx_start <= 1'b1;
                    state    <= S_RSP_STAT;
                end
            end

            S_RSP_STAT: begin
                if (!tx_busy && !tx_start) begin
                    tx_data     <= status;
                    tx_start    <= 1'b1;
                    br_hdr_sent <= 1'b1;
                    rsp_next    <= (byte_count == 16'd0) ? S_SOF : S_RSP_PAY;
                    state    <= S_RSP_WAIT;
                end
            end

            S_RSP_WAIT: begin
                if (!tx_busy && !tx_start) state <= rsp_next;
            end

            S_RSP_PAY: begin
                if (!tx_busy && !tx_start) begin
                    tx_data  <= rsp_is_info ? info_byte : scan_buf[7:0];
                    tx_start <= 1'b1;
                    if (!rsp_is_info) scan_buf <= scan_buf >> 8;
                    byte_index <= byte_index + 1'b1;
                    if (byte_index + 1'b1 < byte_count)
                        rsp_next <= S_RSP_PAY;
                    else if (br_active && scans_left > 16'd1)
                        rsp_next <= S_BR_NEXT;
                    else
                        rsp_next <= S_SOF;
                    state      <= S_RSP_WAIT;
                end
            end

            default: state <= S_SOF;
            endcase
        end
    end

endmodule
