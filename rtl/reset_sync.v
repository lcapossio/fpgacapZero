// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Asynchronous-assert, synchronous-deassert reset synchronizer.
//
// Use this when a reset source may be unrelated to the destination clock
// domain, but the destination logic expects clean reset release on that clock.

module reset_sync #(
    parameter STAGES = 2
) (
    input  wire clk,
    input  wire arst,
    output wire srst
);

    (* ASYNC_REG = "TRUE" *) reg [STAGES-1:0] sync_ff;

    always @(posedge clk or posedge arst) begin
        if (arst)
            sync_ff <= {STAGES{1'b1}};
        else
            sync_ff <= {sync_ff[STAGES-2:0], 1'b0};
    end

    assign srst = sync_ff[STAGES-1];

endmodule
