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
// synchronised Test-Logic-Reset level, for counting.  It powers up low, so it
// is high only once the TAP has been in Test-Logic-Reset; the power-up
// protocol reset comes from por_rst.
//
// hub_por is a power-on reset for flows that drop register initial values
// (Libero on PolarFire), where hub_started could power up set and the hub
// would never see its power-up reset.  Held high from power-up until the
// fabric is initialised, it clears hub_started and holds por_rst; tie it to 0
// where initial values are kept.

module fcapz_hub_reset #(
    parameter TLR_RESET_EN = 0
) (
    input  wire tck,
    input  wire any_sample_rst,
    input  wire hub_por,
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
        .arst(any_sample_rst | hub_por),
        .srst(por_sync)
    );

    reset_sync #(
        .INIT(0)
    ) u_tlr_sync (
        .clk(tck),
        .arst(tlr),
        .srst(tlr_sync)
    );

    always @(posedge tck or posedge hub_por) begin
        if (hub_por)
            hub_started <= 1'b0;
        else if (!por_sync)
            hub_started <= 1'b1;
    end

    assign por_rst = por_sync & ~hub_started;
    assign proto_rst = por_rst | ((TLR_RESET_EN != 0) & tlr_sync);

endmodule
