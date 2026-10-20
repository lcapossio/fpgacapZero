// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Resets of a core-manager hub, all on TCK.
//
// por_rst follows the slots' sample resets (any_sample_rst) only until it is
// first released.  After that a slot's reset no longer reaches the hub, so one
// ELA's reset cannot clear ACTIVE, the EIO outputs or the other slots; each
// slot is reset in its own domain instead.
//
// proto_rst resets the burst protocol: the pipe and the manager's burst start
// event, which must reset together.  It is por_rst, plus the TAP's
// Test-Logic-Reset when TLR_RESET_EN, so a host that restarts mid-burst
// cannot leave the pipe expecting more burst scans.  tlr_sync is the
// synchronised Test-Logic-Reset level, for counting.

module fcapz_hub_reset #(
    parameter TLR_RESET_EN = 0
) (
    input  wire tck,
    input  wire any_sample_rst,
    // TAP in Test-Logic-Reset; tie to 0 if the TAP primitive has no such output.
    input  wire tlr,
    output wire por_rst,
    output wire proto_rst,
    output wire tlr_sync
);

    wire por_sync;
    // Set once the power-up reset has released; never cleared.
    reg  hub_started;

    initial hub_started = 1'b0;

    reset_sync u_por_sync (
        .clk(tck),
        .arst(any_sample_rst),
        .srst(por_sync)
    );

    reset_sync u_tlr_sync (
        .clk(tck),
        .arst(tlr),
        .srst(tlr_sync)
    );

    always @(posedge tck) begin
        if (!por_sync)
            hub_started <= 1'b1;
    end

    assign por_rst = por_sync & ~hub_started;
    assign proto_rst = por_rst | ((TLR_RESET_EN != 0) & tlr_sync);

endmodule
