// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Single trigger comparator unit.
// Evaluates one of 10 compare modes against the masked probe input.
//
// Compare modes (CMP_MODE[3:0]):
//   0 = EQ      (probe & mask) == (value & mask)
//   1 = NEQ     (probe & mask) != (value & mask)
//   2 = LT      (probe & mask) <  (value & mask)   unsigned
//   3 = GT      (probe & mask) >  (value & mask)   unsigned
//   4 = LEQ     (probe & mask) <= (value & mask)   unsigned
//   5 = GEQ     (probe & mask) >= (value & mask)   unsigned
//   6 = RISING  masked bits: all-zero → non-zero
//   7 = FALLING masked bits: non-zero → all-zero
//   8 = CHANGED masked bits: any bit changed from previous
//   9 = reserved
//
// All relational compares are unsigned and operate on the masked values.

module trig_compare #(
    parameter W = 8
) (
    input  wire [W-1:0] probe,      // current sample
    input  wire [W-1:0] probe_prev, // previous sample
    input  wire [W-1:0] value,      // compare value
    input  wire [W-1:0] mask,       // bit mask
    input  wire [3:0]   mode,       // compare mode
    output reg          hit         // 1 = condition met
);

    wire [W-1:0] mp   = probe      & mask;
    wire [W-1:0] mv   = value      & mask;
    wire [W-1:0] mpp  = probe_prev & mask;

    wire eq  = (mp == mv);
    wire lt  = (mp <  mv);
    wire gt  = (mp >  mv);
    wire zero_prev = (mpp == {W{1'b0}});
    wire zero_cur  = (mp  == {W{1'b0}});
    wire changed   = (mp  != mpp);

    always @(*) begin
        case (mode)
            4'd0:    hit = eq;                        // EQ
            4'd1:    hit = !eq;                       // NEQ
            4'd2:    hit = lt;                        // LT
            4'd3:    hit = gt;                        // GT
            4'd4:    hit = lt | eq;                   // LEQ
            4'd5:    hit = gt | eq;                   // GEQ
            4'd6:    hit = zero_prev & ~zero_cur;     // RISING
            4'd7:    hit = ~zero_prev & zero_cur;     // FALLING
            4'd8:    hit = changed;                   // CHANGED
            default: hit = 1'b0;
        endcase
    end

endmodule
