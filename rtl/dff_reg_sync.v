// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

`timescale 1ns/1ps

module dff_reg_sync #(
    parameter pREG_LEN      = 8,
    parameter pSYNC_STAGES  = 2
        // NOTE: minimum 1
) (
    // ------ 'clk' synchronous ------
    input                       clk,
    input                       srst,
    output [pREG_LEN-1:0]   syncreg,

    // ------ asynchronous ------
    input  [pREG_LEN-1:0]       asyncreg
);

    genvar i;
    generate
        for (i = 0; i < pREG_LEN; i = i + 1) begin
            dff_sync
            #(
                .pSYNC_STAGES (pSYNC_STAGES)
            ) sync_i_clk_reg
            (
                .clk    (clk),
                .srst   (srst),
                .sync   (syncreg[i]),

                .async  (asyncreg[i])
            );
        end
    endgenerate

endmodule
