// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

// Simulation model of the Lattice ECP5 JTAGG primitive.
//
// A testbench drives the device's JTAG pins through tck_pin, tms_pin and
// tdi_pin and reads tdo_pin; left alone they keep the TAP in
// Test-Logic-Reset.  The outputs follow JTAGG's timing as LiteX's ECP5JTAG and
// the Hazard3 ECP5 debug module rely on it on hardware:
//   - JTDI is TDI registered on the rising edge of TCK;
//   - JSHIFT, JUPDATE, JCE1/JCE2, JRTI1/JRTI2 and JRSTN decode the TAP state,
//     which changes on the rising edge (JSHIFT and JUPDATE for any
//     instruction, JCE<n> and JRTI<n> for ER<n> only);
//   - in Shift-DR, JTDO1/JTDO2 are registered on the falling edge onto TDO.
// The instruction register is 8 bits: ER1 = 0x32, ER2 = 0x38, and any other
// instruction scans a one-bit bypass register.

`timescale 1ns/1ps

module JTAGG (
    output wire JTCK,
    output wire JTDI,
    input  wire JTDO1,
    input  wire JTDO2,
    output wire JSHIFT,
    output wire JUPDATE,
    output wire JRSTN,
    output wire JCE1,
    output wire JCE2,
    output wire JRTI1,
    output wire JRTI2
);

    reg tck_pin = 1'b0;
    reg tms_pin = 1'b1;
    reg tdi_pin = 1'b0;
    reg tdo_pin;

    localparam [7:0] IR_ER1    = 8'h32;
    localparam [7:0] IR_ER2    = 8'h38;
    localparam [7:0] IR_IDCODE = 8'hE0;

    localparam [3:0] TLR = 4'd0,  RTI = 4'd1,  SEL_DR = 4'd2,  CAP_DR = 4'd3,
                     SH_DR = 4'd4, EX1_DR = 4'd5, PAU_DR = 4'd6, EX2_DR = 4'd7,
                     UPD_DR = 4'd8, SEL_IR = 4'd9, CAP_IR = 4'd10, SH_IR = 4'd11,
                     EX1_IR = 4'd12, PAU_IR = 4'd13, EX2_IR = 4'd14, UPD_IR = 4'd15;

    reg [3:0] state;
    reg [7:0] ir;
    reg [7:0] ir_sr;
    reg       bypass;
    reg       jtdi_q;
    initial begin
        state   = TLR;
        ir      = IR_IDCODE;
        ir_sr   = 8'h00;
        bypass  = 1'b0;
        jtdi_q  = 1'b0;
        tdo_pin = 1'b0;
    end

    always @(posedge tck_pin) begin
        jtdi_q <= tdi_pin;
        case (state)
            CAP_IR: ir_sr <= 8'h01;
            SH_IR:  ir_sr <= {tdi_pin, ir_sr[7:1]};
            UPD_IR: ir <= ir_sr;
            TLR:    ir <= IR_IDCODE;
            CAP_DR: bypass <= 1'b0;
            SH_DR:  bypass <= tdi_pin;
            default: ;
        endcase
        case (state)
            TLR:    state <= tms_pin ? TLR    : RTI;
            RTI:    state <= tms_pin ? SEL_DR : RTI;
            SEL_DR: state <= tms_pin ? SEL_IR : CAP_DR;
            CAP_DR: state <= tms_pin ? EX1_DR : SH_DR;
            SH_DR:  state <= tms_pin ? EX1_DR : SH_DR;
            EX1_DR: state <= tms_pin ? UPD_DR : PAU_DR;
            PAU_DR: state <= tms_pin ? EX2_DR : PAU_DR;
            EX2_DR: state <= tms_pin ? UPD_DR : SH_DR;
            UPD_DR: state <= tms_pin ? SEL_DR : RTI;
            SEL_IR: state <= tms_pin ? TLR    : CAP_IR;
            CAP_IR: state <= tms_pin ? EX1_IR : SH_IR;
            SH_IR:  state <= tms_pin ? EX1_IR : SH_IR;
            EX1_IR: state <= tms_pin ? UPD_IR : PAU_IR;
            PAU_IR: state <= tms_pin ? EX2_IR : PAU_IR;
            EX2_IR: state <= tms_pin ? UPD_IR : SH_IR;
            default: state <= tms_pin ? SEL_DR : RTI;  // UPD_IR
        endcase
    end

    always @(negedge tck_pin) begin
        if (state == SH_DR)
            tdo_pin <= (ir == IR_ER1) ? JTDO1 : (ir == IR_ER2) ? JTDO2 : bypass;
        else if (state == SH_IR)
            tdo_pin <= ir_sr[0];
    end

    assign JTCK    = tck_pin;
    assign JTDI    = jtdi_q;
    assign JSHIFT  = (state == SH_DR);
    assign JUPDATE = (state == UPD_DR);
    assign JRSTN   = (state != TLR);
    assign JCE1    = (state == CAP_DR || state == SH_DR) && ir == IR_ER1;
    assign JCE2    = (state == CAP_DR || state == SH_DR) && ir == IR_ER2;
    assign JRTI1   = (state == RTI) && ir == IR_ER1;
    assign JRTI2   = (state == RTI) && ir == IR_ER2;

endmodule
