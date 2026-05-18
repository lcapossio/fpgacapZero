// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

module dff_reg_sync
#(
    parameter int pREG_LEN,
    parameter int pSYNC_STAGES
        // NOTE: minimum 1
)
(
    // ------ 'clk' synchronous ------
    input   logic                clk,
    input   logic                srst,
    output  logic [pREG_LEN-1:0] syncreg,

    // ------ asynchronous ------
    input   logic [pREG_LEN-1:0] asyncreg
);

    genvar i;
    generate
        for (i = 0; i < pREG_LEN; i++) begin
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

endmodule : dff_reg_sync