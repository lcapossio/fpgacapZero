// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps

// Core-manager variant of brs_100_gw1nr9_top: one fcapz_debug_multi_gowin hub
// on GW_JTAG ER1 carries four slots.  The Gowin hub is register-only, so the
// host reads every capture through the register window.
//   slot 0  ELA : 8-bit x 64, probe = free-running counter (60 MHz)
//   slot 1  ELA : 8-bit x 64, probe = that counter XOR 0xA5
//   slot 2  EIO : in  = {buttons[1:0], 2'b00, slow counter[3:0]}
//                 out = {2'b00 unused, LED[5:0]}
//   slot 3  EIO : in  = its own outputs (loopback); out = not connected
// Clocking, pins and constraints are those of brs_100_gw1nr9_top.

module brs_100_gw1nr9_manager_top #()
(
    input           pad_clk_27Mhz,

    input   [1:0]   pad_user_buttons_n,
    inout   [5:0]   pad_leds_n,

    inout   [32:1]  pad_io,

    input   wire    tms_pad_i,
    input   wire    tck_pad_i,
    input   wire    tdi_pad_i,
    output  wire    tdo_pad_o
);
localparam int CLK_FREQUENCY_MHZ    = 60;
localparam int CLK_FREQUENCY_HZ     = CLK_FREQUENCY_MHZ * 1000000;
localparam int SAMPLE_W             = 8;
localparam int DEPTH                = 64;


    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    wire [5:0]                      i_eio_leds;     // host-driven LEDs (EIO out)
    reg [1:0]                       i_buttons;
    reg [3:0]                       i_slow;     // ~31 Hz counter for EIO0

    reg                             i_sysclk;
    reg                             i_sysclk_resetn = 1'b0;
    reg                             i_sysclk_reset;

    reg                             i_microsecond_tick;
    reg                             i_millisecond_tick;
    reg                             i_second_tick;

    reg [8:0]                       i_microsecond_div_counter;
    reg [19:0]                      i_millisecond_div_counter;
    reg [9:0]                       i_millisecond_counter;

    reg [SAMPLE_W-1:0]              i_counter;


    // JTAG Clock
    // -----------

    reg                             i_jtagclk;
    reg                             i_jtagclk_resetn = 1'b0;
    reg                             i_jtagclk_reset;

    reg                             i_jtag_activity_jtagclk;


    // ----------------------------------------------
    //  Implementation
    // ----------------------------------------------


    // NOTE: core manager
    // ------------

    always @(posedge i_sysclk) begin
        if (i_sysclk_resetn == 1'b0) begin
            i_counter   <= 0;
            i_buttons   <= 0;
            i_slow      <= 0;
        end else begin
            i_counter   <= i_counter + 1'b1;
            i_buttons   <= ~pad_user_buttons_n;
            if (i_millisecond_tick == 1'b1 && i_millisecond_counter[4:0] == 5'd0)
                i_slow  <= i_slow + 1'b1;
        end
    end

    wire [15:0] i_eio_out;
    wire [7:0]  i_eio0_in = {i_buttons, 2'b00, i_slow};

    fcapz_debug_multi_gowin #(
        .NUM_ELAS       (2),
        .NUM_EIOS       (2),
        .SAMPLE_W       (SAMPLE_W),
        .DEPTH          (DEPTH),
        .EIO_IN_W       (8),
        .EIO_OUT_W      (8)
    ) u_debug (
        .clk            (i_jtagclk),
            // NOTE: oversamples GW_JTAG; must run well above TCK
        .jtag_activity  (i_jtag_activity_jtagclk),

        .ela_sample_clk ({i_sysclk, i_sysclk}),
        .ela_sample_rst ({i_sysclk_reset, i_sysclk_reset}),
        .ela_probe_in   ({i_counter ^ 8'hA5, i_counter}),
        .ela_trigger_in (2'b00),
        .ela_trigger_out(),
        .ela_armed_out  (),

        .eio_probe_in   ({i_eio_out[15:8], i_eio0_in}),
        .eio_probe_out  (i_eio_out),

        .tms_pad_i      (tms_pad_i),
        .tck_pad_i      (tck_pad_i),
        .tdi_pad_i      (tdi_pad_i),
        .tdo_pad_o      (tdo_pad_o)
    );

    assign i_eio_leds = i_eio_out[5:0];



    // NOTE: Clocking
    // ------------

    rPLL #(
        .FCLKIN     ("27"),
        .IDIV_SEL   (2),
            // NOTE: PFD = 9 MHz (range: 3-400 MHz)
        .FBDIV_SEL  (1),
            // NOTE: CLKOUT = 9 MHz (range: 3.125-500 MHz)
        .ODIV_SEL   (32)
            // NOTE: VCO = 432 MHz (range: 400-1000 MHz)
    ) rpll_18mhz_inst (
        .CLKIN      (pad_clk_27Mhz),
        .CLKOUT     (i_jtagclk),
        .LOCK       (i_jtagclk_resetn),

        .CLKOUTP    (),
        .CLKOUTD    (),
        .CLKOUTD3   (),
        .RESET      (1'b0),
        .RESET_P    (1'b0),
        .CLKFB      (1'b0),
        .FBDSEL     (6'b0),
        .IDSEL      (6'b0),
        .ODSEL      (6'b0),
        .PSDA       (4'b0),
        .DUTYDA     (4'b0),
        .FDLY       (4'b0)
    );

    rPLL #(
        .FCLKIN     ("27"),
        .IDIV_SEL   (8),
            // NOTE: PFD = 3 MHz (range: 3-400 MHz)
        .FBDIV_SEL  (19),
            // NOTE: CLKOUT = 60 MHz (range: 3.125-500 MHz)
        .ODIV_SEL   (8)
            // NOTE: VCO = 480 MHz (range: 400-1000 MHz)
    ) rpll_60mhz_inst (
        .CLKIN      (pad_clk_27Mhz),
        .CLKOUT     (i_sysclk),
        .LOCK       (i_sysclk_resetn),

        .CLKOUTP    (),
        .CLKOUTD    (),
        .CLKOUTD3   (),
        .RESET      (1'b0),
        .RESET_P    (1'b0),
        .CLKFB      (1'b0),
        .FBDSEL     (6'b0),
        .IDSEL      (6'b0),
        .ODSEL      (6'b0),
        .PSDA       (4'b0),
        .DUTYDA     (4'b0),
        .FDLY       (4'b0)
    );

    assign i_sysclk_reset = ~i_sysclk_resetn;


    // NOTE: Timer
    // Related
    // ------------

    always @(posedge i_sysclk) begin
        if (i_sysclk_resetn == 1'b0) begin
            i_microsecond_div_counter   <= 0;
            i_millisecond_div_counter   <= 0;
            i_millisecond_counter       <= 0;

            i_second_tick               <= 1'b0;
            i_millisecond_tick          <= 1'b0;
            i_microsecond_tick          <= 1'b0;
        end else begin
            // defaults
            i_second_tick       <= 1'b0;
            i_millisecond_tick  <= 1'b0;
            i_microsecond_tick  <= 1'b0;

            if (i_millisecond_div_counter == 0) begin
                i_millisecond_div_counter   <= (CLK_FREQUENCY_HZ/1000)-1;
                i_millisecond_tick          <= 1'b1;
            end else begin
                i_millisecond_div_counter <= i_millisecond_div_counter - 1;
            end

            if (i_microsecond_div_counter == 0) begin
                i_microsecond_div_counter   <= (CLK_FREQUENCY_HZ/1000000)-1;
                i_microsecond_tick          <= 1'b1;
            end else begin
                i_microsecond_div_counter <= i_microsecond_div_counter - 1;
            end

            if (i_millisecond_tick == 1'b1) begin
                if (i_millisecond_counter == 1000-1) begin
                    i_second_tick           <= 1'b1;

                    i_millisecond_counter   <= 0;
                end else begin
                    i_millisecond_counter <= i_millisecond_counter + 1;
                end
            end
        end
    end


    // NOTE: Leds
    // ------------
    //
    // EIO demo: all 6 LEDs are driven by the EIO output register, so the
    // host controls them directly over JTAG (eio.write_outputs).  LEDs are
    // active-low on this board.

    assign pad_leds_n = ~i_eio_leds;
        // NOTE: led[5:0] = EIO probe_out[5:0] (host-driven)

endmodule
