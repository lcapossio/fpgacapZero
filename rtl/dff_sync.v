// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

`timescale 1ns/1ps

module dff_sync #(
    parameter pSYNC_STAGES    = 2,
        // NOTE: minimum 1
    parameter pSYNC_DEFAULT   = 1'b0
) (
    // ------ 'clk' synchronous ------
    input       clk,
    input       srst,
    output reg  sync,

    // ------ asynchronous ------
    input       async
);

    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    logic [pSYNC_STAGES-1:0] i_sync_stages = {(pSYNC_STAGES){pSYNC_DEFAULT}};


    // ----------------------------------------------
    //  Synchronization
    // ----------------------------------------------

    always@(posedge clk) begin
        if (srst == 1'b1) begin
            i_sync_stages   <= {(pSYNC_STAGES){pSYNC_DEFAULT}};
            sync            <= pSYNC_DEFAULT;

        end else begin
            i_sync_stages       <= i_sync_stages << 1;
            i_sync_stages[0]    <= async;

            sync                <= i_sync_stages[$bits(i_sync_stages)-1];
        end
    end

endmodule
