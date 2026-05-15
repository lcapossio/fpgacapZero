// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Gowin JTAG TAP wrapper.
// Presents the standard fpgacapZero TAP interface.
//
// Gowin devices expose user logic through one GW_JTAG primitive per design.
// That primitive provides two user DR chains (ER1/ER2, selected by IR
// 0x42/0x43 on the devices checked so far).

module jtag_tap_gowin #(
) (
    input               sysclk,

    output reg          tdi,
    input  reg  [1:0]   tdo,
    output reg  [1:0]   capture,
    output reg  [1:0]   shift,
    output reg  [1:0]   update,
    output reg  [1:0]   sel,

    output reg  [5:0]   debug,

    input  wire         tms_pad_i,
    input  wire         tck_pad_i,
    input  wire         tdi_pad_i,
    output wire         tdo_pad_o
);

    // jtck domain
    // -------------

    wire        jtck_jtck;
    wire        jtdi_jtck;
    wire        jshift_capture_jtck;
    wire        jupdate_jtck;
    wire [1:0]  jce_jtck;
    wire [5:0]  jtag_in_jtck;


    // sysclk domain
    // -------------

    wire [5:0]  jtag_in;
    wire        jtck;
    wire        jtdi;
    wire        jshift_capture;
    wire        jupdate;
    wire [1:0]  jce;
    reg         jtck_d1;
    reg         jupdate_d1;
    wire        jtck_en;

    reg [4:0]   jtag_in_reg;
    reg         jtdi_reg;
    reg         jshift_capture_reg;
    reg         jupdate_reg;
    reg [1:0]   jce_reg;
    reg         s_reg;
    reg         jhold_reg;
    reg         out_en_reg;


    // NOTE: GoWIN
    // JTAG TAP
    // -------------

    GW_JTAG u_jtag (
        .tck_pad_i              (tck_pad_i),
        .tms_pad_i              (tms_pad_i),
        .tdi_pad_i              (tdi_pad_i),
        .tdo_pad_o              (tdo_pad_o),

        .tck_o                  (jtck_jtck),
        .tdi_o                  (jtdi_jtck),
        .test_logic_reset_o     (),
        .run_test_idle_er1_o    (),
        .run_test_idle_er2_o    (),
        .shift_dr_capture_dr_o  (jshift_capture_jtck),
        .pause_dr_o             (),
        .update_dr_o            (jupdate_jtck),
        .enable_er1_o           (jce_jtck[0]),
        .enable_er2_o           (jce_jtck[1]),
        .tdo_er1_i              (tdo[0]),
        .tdo_er2_i              (tdo[1])
    );


    // NOTE: synchronize *_jtck
    // signals to 'sysclk' domain
    // ----------------------------

    assign jtag_in_jtck = { jtck_jtck, jtdi_jtck, jshift_capture_jtck, jupdate_jtck, jce_jtck };

    assign debug = jtag_in_jtck;

    dff_reg_sync #(
        .pREG_LEN       ($size(jtag_in)),
        .pSYNC_STAGES   (2)
    ) jtag_in_sync_i (
        .clk            (sysclk),
        .srst           (1'b0),
        .syncreg        (jtag_in),

        .asyncreg       (jtag_in_jtck)
    );

    assign { jtck, jtdi, jshift_capture, jupdate, jce } = jtag_in;


    // NOTE: derive
    // 'jtck_en' strobe
    // ------------------

    always @(posedge sysclk) begin
        jtck_d1 <= jtck;
    end

    assign jtck_en = jtck_d1 & ~jtck;


    // NOTE: derive
    // jhold / s regs
    // ----------------

    always @(posedge sysclk) begin
        if (jtck_en == 1'b1) begin
            // defaults
            jupdate_d1 <= jupdate;

            if (jshift_capture == 1'b1) begin
                jhold_reg <= 1'b1;
            end else if ((jupdate == 1'b0) && (jupdate_d1 == 1'b1)) begin
                jhold_reg <= 1'b0;
            end
        end
    end

    always @(posedge sysclk) begin
        if (jtck_en == 1'b1) begin
            if (jshift_capture == 1'b1) begin
                if (jce[0] == 1'b1) begin
                    s_reg <= 1'b0;
                end
                if (jce[1] == 1'b1) begin
                    s_reg <= 1'b1;
                end
            end
        end
    end


    // NOTE: capture 'jtag_in_reg'
    // to align with jhold / s regs
    // -----------------------------

    always @(posedge sysclk) begin
        out_en_reg <= jtck_en;

        if (jtck_en == 1'b1) begin
            jtag_in_reg <= jtag_in[4:0];
        end
    end

    assign { jtdi_reg, jshift_capture_reg, jupdate_reg, jce_reg } = jtag_in_reg;


    // NOTE: output
    // ----------------

    always_comb begin
        // defaults
        capture = 0;
        shift   = 0;
        update  = 0;
        sel     = 0;

        if (out_en_reg == 1'b1) begin
            for (int i = 0; i < 2; i++) begin
                capture[i]  = jce_reg[i] & (~jshift_capture_reg) & (~jhold_reg);

                shift[i]    = jce_reg[i] & jshift_capture_reg;
            end

            update[0]   = jupdate_reg & ~s_reg;
            update[1]   = jupdate_reg & s_reg;

            sel[0]      = jce_reg[0];
            sel[1]      = jce_reg[1];
        end
    end

    assign tdi = jtdi_reg;

endmodule
