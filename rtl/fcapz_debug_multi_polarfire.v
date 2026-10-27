// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

`timescale 1ns/1ps

// Mixed debug wrapper: multiple ELAs plus optional EIOs behind one USER chain.
// Slot order is ELA[0..NUM_ELAS-1], then EIO[0..NUM_EIOS-1].
//
// Microchip PolarFire / PolarFire SoC: the UJTAG user instruction IR_USER1.
// IR_USER2 is unused (the hub needs one chain) but kept so it matches
// fcapz_ela_polarfire.  UJTAG's JTAG pins must reach top-level ports:
// connect tck_pad_i, tms_pad_i, tdi_pad_i, trstb_pad_i and tdo_pad_o
// straight to ports of the same direction; Libero binds them to the
// dedicated JTAG pins.  Only one UJTAG is allowed per device, so this hub
// cannot coexist with fcapz_ela_polarfire or fcapz_eio_polarfire.
// UJTAG has no Test-Logic-Reset output, so TLR_RESET_EN is not offered.
// Everything but the TAP lives in the vendor-free fcapz_debug_multi.

module fcapz_debug_multi_polarfire #(
    parameter NUM_ELAS = 2,
    parameter EIO_EN = 1,
    parameter NUM_EIOS = EIO_EN,
    parameter SAMPLE_W = 8,
    parameter DEPTH = 1024,
    parameter TRIG_STAGES = 1,
    parameter STOR_QUAL = 0,
    parameter INPUT_PIPE = 0,
    parameter NUM_CHANNELS = 1,
    parameter DECIM_EN = 0,
    parameter EXT_TRIG_EN = 0,
    parameter TIMESTAMP_W = 0,
    parameter NUM_SEGMENTS = 1,
    parameter PROBE_MUX_W = 0,
    parameter STARTUP_ARM = 0,
    parameter DEFAULT_TRIG_EXT = 0,
    parameter BURST_W = 256,
    // UJTAG user IR opcodes (16..127 are free; 0x10/0x11 belong to the
    // PolarFire SoC MSS debug module, see jtag_tap_polarfire.v).
    parameter [7:0] IR_USER1 = 8'h20,
    parameter [7:0] IR_USER2 = 8'h21,
    parameter REL_COMPARE = 0,
    parameter DUAL_COMPARE = 1,
    parameter USER1_DATA_EN = 1,
    parameter EIO_IN_W = 1,
    parameter EIO_OUT_W = 1,
    parameter ELA_PORT_COUNT = (NUM_ELAS > 0) ? NUM_ELAS : 1,
    // Per-slot overrides. The scalar parameters above remain the max/default
    // shape so existing instantiations can keep using one shared setting.
    parameter [ELA_PORT_COUNT*32-1:0] ELA_SAMPLE_WS = {ELA_PORT_COUNT{(SAMPLE_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEPTHS = {ELA_PORT_COUNT{(DEPTH + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TRIG_STAGES = {ELA_PORT_COUNT{(TRIG_STAGES + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STOR_QUALS = {ELA_PORT_COUNT{(STOR_QUAL + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_INPUT_PIPES = {ELA_PORT_COUNT{(INPUT_PIPE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_CHANNELS = {ELA_PORT_COUNT{(NUM_CHANNELS + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DECIM_ENS = {ELA_PORT_COUNT{(DECIM_EN + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_EXT_TRIG_ENS = {ELA_PORT_COUNT{(EXT_TRIG_EN + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_TIMESTAMP_WS = {ELA_PORT_COUNT{(TIMESTAMP_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_NUM_SEGMENTS = {ELA_PORT_COUNT{(NUM_SEGMENTS + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_PROBE_MUX_WS = {ELA_PORT_COUNT{(PROBE_MUX_W + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_STARTUP_ARMS = {ELA_PORT_COUNT{(STARTUP_ARM + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DEFAULT_TRIG_EXTS = {ELA_PORT_COUNT{(DEFAULT_TRIG_EXT + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_REL_COMPARES = {ELA_PORT_COUNT{(REL_COMPARE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_DUAL_COMPARES = {ELA_PORT_COUNT{(DUAL_COMPARE + 32'd0)}},
    parameter [ELA_PORT_COUNT*32-1:0] ELA_USER1_DATA_ENS = {ELA_PORT_COUNT{(USER1_DATA_EN + 32'd0)}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_IN_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){(EIO_IN_W + 32'd0)}},
    parameter [((NUM_EIOS > 0) ? NUM_EIOS : 1)*32-1:0] EIO_OUT_WS =
        {((NUM_EIOS > 0) ? NUM_EIOS : 1){(EIO_OUT_W + 32'd0)}}
) (
    input  wire [ELA_PORT_COUNT-1:0] ela_sample_clk,
    input  wire [ELA_PORT_COUNT-1:0] ela_sample_rst,
    input  wire [ELA_PORT_COUNT*(PROBE_MUX_W > 0 ? PROBE_MUX_W : SAMPLE_W*NUM_CHANNELS)-1:0] ela_probe_in,
    input  wire [ELA_PORT_COUNT-1:0] ela_trigger_in,
    output wire [ELA_PORT_COUNT-1:0] ela_trigger_out,
    output wire [ELA_PORT_COUNT-1:0] ela_armed_out,
    input  wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_IN_W-1:0] eio_probe_in,
    output wire [((NUM_EIOS > 0) ? NUM_EIOS : 1)*EIO_OUT_W-1:0] eio_probe_out,

    // UJTAG JTAG pins: wire straight to top-level ports.
    input  wire tck_pad_i,
    input  wire tms_pad_i,
    input  wire tdi_pad_i,
    input  wire trstb_pad_i,
    output wire tdo_pad_o
);

    wire tap_tck, tap_tdi, tap_tdo;
    wire tap_capture, tap_shift, tap_update, tap_sel;
    wire ch2_tck_unused, ch2_tdi_unused, ch2_capture_unused;
    wire ch2_shift_unused, ch2_update_unused, ch2_sel_unused;

    jtag_tap_polarfire #(
        .IR_USER1(IR_USER1), .IR_USER2(IR_USER2)
    ) u_tap_ctrl (
        .tck_pad_i(tck_pad_i), .tms_pad_i(tms_pad_i), .tdi_pad_i(tdi_pad_i),
        .trstb_pad_i(trstb_pad_i), .tdo_pad_o(tdo_pad_o),
        .ch1_tck(tap_tck), .ch1_tdi(tap_tdi), .ch1_tdo(tap_tdo),
        .ch1_capture(tap_capture), .ch1_shift(tap_shift),
        .ch1_update(tap_update), .ch1_sel(tap_sel),
        .ch2_tck(ch2_tck_unused), .ch2_tdi(ch2_tdi_unused), .ch2_tdo(1'b0),
        .ch2_capture(ch2_capture_unused), .ch2_shift(ch2_shift_unused),
        .ch2_update(ch2_update_unused), .ch2_sel(ch2_sel_unused)
    );

    fcapz_debug_multi #(
        .NUM_ELAS(NUM_ELAS), .EIO_EN(EIO_EN), .NUM_EIOS(NUM_EIOS), .SAMPLE_W(SAMPLE_W),
        .DEPTH(DEPTH), .TRIG_STAGES(TRIG_STAGES), .STOR_QUAL(STOR_QUAL),
        .INPUT_PIPE(INPUT_PIPE), .NUM_CHANNELS(NUM_CHANNELS), .DECIM_EN(DECIM_EN),
        .EXT_TRIG_EN(EXT_TRIG_EN), .TIMESTAMP_W(TIMESTAMP_W),
        .NUM_SEGMENTS(NUM_SEGMENTS), .PROBE_MUX_W(PROBE_MUX_W),
        .STARTUP_ARM(STARTUP_ARM), .DEFAULT_TRIG_EXT(DEFAULT_TRIG_EXT),
        .BURST_W(BURST_W), .REL_COMPARE(REL_COMPARE), .DUAL_COMPARE(DUAL_COMPARE),
        .USER1_DATA_EN(USER1_DATA_EN), .TLR_RESET_EN(0),
        .EIO_IN_W(EIO_IN_W), .EIO_OUT_W(EIO_OUT_W),
        .ELA_PORT_COUNT(ELA_PORT_COUNT), .ELA_SAMPLE_WS(ELA_SAMPLE_WS),
        .ELA_DEPTHS(ELA_DEPTHS), .ELA_TRIG_STAGES(ELA_TRIG_STAGES),
        .ELA_STOR_QUALS(ELA_STOR_QUALS), .ELA_INPUT_PIPES(ELA_INPUT_PIPES),
        .ELA_NUM_CHANNELS(ELA_NUM_CHANNELS), .ELA_DECIM_ENS(ELA_DECIM_ENS),
        .ELA_EXT_TRIG_ENS(ELA_EXT_TRIG_ENS), .ELA_TIMESTAMP_WS(ELA_TIMESTAMP_WS),
        .ELA_NUM_SEGMENTS(ELA_NUM_SEGMENTS), .ELA_PROBE_MUX_WS(ELA_PROBE_MUX_WS),
        .ELA_STARTUP_ARMS(ELA_STARTUP_ARMS),
        .ELA_DEFAULT_TRIG_EXTS(ELA_DEFAULT_TRIG_EXTS),
        .ELA_REL_COMPARES(ELA_REL_COMPARES), .ELA_DUAL_COMPARES(ELA_DUAL_COMPARES),
        .ELA_USER1_DATA_ENS(ELA_USER1_DATA_ENS), .EIO_IN_WS(EIO_IN_WS),
        .EIO_OUT_WS(EIO_OUT_WS)
    ) u_multi (
        .tck(tap_tck), .tdi(tap_tdi), .tdo(tap_tdo),
        .capture(tap_capture), .shift(tap_shift),
        .update(tap_update), .sel(tap_sel),
        .tlr(1'b0),
        .ela_sample_clk(ela_sample_clk),
        .ela_sample_rst(ela_sample_rst),
        .ela_probe_in(ela_probe_in),
        .ela_trigger_in(ela_trigger_in),
        .ela_trigger_out(ela_trigger_out),
        .ela_armed_out(ela_armed_out),
        .eio_probe_in(eio_probe_in),
        .eio_probe_out(eio_probe_out)
    );

endmodule
