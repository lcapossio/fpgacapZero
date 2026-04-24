// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// fpgacapZero ELA wrapper for Xilinx UltraScale / UltraScale+.
//
// UltraScale and UltraScale+ both expose the same BSCANE2 primitive
// from the unisim library that 7-series uses, so this module is a thin
// shim over fcapz_ela_xilinx7 -- there is one definition of the wrapper
// internals (TAP wrapper, register interface, ELA core, burst engine)
// in the project, and both the 7-series and UltraScale entry points
// route through it.  See jtag_tap_xilinxus.v for the list of confirmed
// device families and the IR encoding.
//
// Usage:
//   fcapz_ela_xilinxus #(.SAMPLE_W(8), .DEPTH(1024)) u_ela (
//       .sample_clk(clk), .sample_rst(rst), .probe_in(signals)
//   );
//
// Note: Xilinx Versal devices (XCVM/VC/VP/VE/VH) are NOT covered here;
// they need a separate wrapper that targets their TAP primitive.

module fcapz_ela_xilinxus #(
    parameter SAMPLE_W    = 8,
    parameter DEPTH       = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL   = 0,
    parameter INPUT_PIPE  = 0,
    parameter NUM_CHANNELS = 1,
    parameter DECIM_EN    = 0,
    parameter EXT_TRIG_EN = 0,
    parameter TIMESTAMP_W = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W = 0,
    parameter STARTUP_ARM = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter BURST_W     = 256,
    parameter CTRL_CHAIN  = 1,
    parameter DATA_CHAIN  = 2,
    // Optional EIO (shares CTRL_CHAIN via address mux; host talks to EIO at 0x8000+)
    parameter EIO_EN      = 0,
    parameter EIO_IN_W    = 1,
    parameter EIO_OUT_W   = 1,
    parameter REL_COMPARE = 0
) (
    input  wire                          sample_clk,
    input  wire                          sample_rst,
    input  wire [(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] probe_in,
    input  wire                          trigger_in,
    output wire                          trigger_out,
    output wire                          armed_out,
    // EIO ports (active when EIO_EN=1; ignored / tied-off otherwise)
    input  wire [EIO_IN_W-1:0]           eio_probe_in,
    output wire [EIO_OUT_W-1:0]          eio_probe_out
);

    // Direct shim — every parameter and port forwarded.
    fcapz_ela_xilinx7 #(
        .SAMPLE_W(SAMPLE_W), .DEPTH(DEPTH),
        .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS),
        .DECIM_EN(DECIM_EN), .EXT_TRIG_EN(EXT_TRIG_EN),
        .TIMESTAMP_W(TIMESTAMP_W), .NUM_SEGMENTS(NUM_SEGMENTS),
        .PROBE_MUX_W(PROBE_MUX_W), .STARTUP_ARM(STARTUP_ARM),
        .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT), .REL_COMPARE(REL_COMPARE),
        .BURST_W(BURST_W),
        .CTRL_CHAIN(CTRL_CHAIN), .DATA_CHAIN(DATA_CHAIN),
        .EIO_EN(EIO_EN), .EIO_IN_W(EIO_IN_W), .EIO_OUT_W(EIO_OUT_W)
    ) u_inner (
        .sample_clk(sample_clk), .sample_rst(sample_rst),
        .probe_in(probe_in),
        .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),
        .eio_probe_in(eio_probe_in), .eio_probe_out(eio_probe_out)
    );

endmodule
