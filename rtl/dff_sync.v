// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

`timescale 1ns/1ps

module dff_sync #(
    parameter pSYNC_STAGES    = 2,
        // NOTE: minimum 2; this is the total number of sync flops.
    parameter pSYNC_DEFAULT   = 1'b0
) (
    // ------ 'clk' synchronous ------
    input       clk,
    input       srst,
    output wire sync,

    // ------ asynchronous ------
    input       async
);

    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    generate
        if (pSYNC_STAGES < 2) begin : g_invalid_sync_stages
`ifndef VERILATOR
            __FCAPZ_DFF_SYNC_REQUIRES_AT_LEAST_TWO_STAGES__ invalid();
`endif
            initial begin
                $error("dff_sync: pSYNC_STAGES must be >= 2");
                $finish;
            end
        end
    endgenerate

    reg [pSYNC_STAGES-1:0] sync_stages;

    assign sync = sync_stages[pSYNC_STAGES-1];

    always @(posedge clk) begin
        if (srst == 1'b1) begin
            sync_stages <= {pSYNC_STAGES{pSYNC_DEFAULT}};
        end else begin
            sync_stages <= {sync_stages[pSYNC_STAGES-2:0], async};
        end
    end

endmodule
