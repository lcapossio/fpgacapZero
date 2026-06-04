// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

`timescale 1ns/1ps

module brs_100_gw1nr9_top #()
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
localparam int CHANNELS             = 6;
localparam int DEPTH                = 64;


    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    reg [5:0]                       i_leds;
    reg [1:0]                       i_buttons;
    reg [32-1:0]                    i_pad;

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
    reg [(SAMPLE_W*CHANNELS)-1:0]   i_probe;


    // JTAG Clock
    // -----------

    reg                             i_jtagclk;
    reg                             i_jtagclk_resetn = 1'b0;
    reg                             i_jtagclk_reset;

    reg                             i_jtag_activity_jtagclk;


    // ----------------------------------------------
    //  Implementation
    // ----------------------------------------------


    // NOTE: ELA
    // Related
    // ------------

    always @(posedge i_sysclk) begin
        if (i_sysclk_resetn == 1'b0) begin
            i_counter   <= 0;
            i_buttons   <= 0;
            i_pad       <= 0;
        end else begin
            i_counter   <= i_counter + 1'b1;
            i_buttons   <= ~pad_user_buttons_n;
            i_pad       <= pad_io[32:1];
        end
    end

    assign i_probe = { i_pad, 6'b000000, i_buttons, i_counter};

    fcapz_ela_gowin #(
        .SAMPLE_W       (SAMPLE_W),
        .DEPTH          (DEPTH),
        .NUM_CHANNELS   (CHANNELS),
        .EIO_EN         (0)
    ) u_ela (
        .clk            (i_jtagclk),
            // NOTE: this is a separate clock
            // only for demonstration purposes...
            // this clock must be at least ~10x
            // the JTAG TCK (~2 MHz for BR-100-GW1NR9)
        .jtag_activity  (i_jtag_activity_jtagclk),

        .sample_clk     (i_sysclk),
        .sample_rst     (i_sysclk_reset),
        .probe_in       (i_probe),

        .eio_probe_in   (0),
        .eio_probe_out  (),
            // NOTE: external trigger ports
            // tie off if not used

        .tms_pad_i      (tms_pad_i),
        .tck_pad_i      (tck_pad_i),
        .tdi_pad_i      (tdi_pad_i),
        .tdo_pad_o      (tdo_pad_o)
    );



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

    always @(posedge i_sysclk) begin
        if (i_second_tick == 1'b1) begin
            i_leds[0] <= ~i_leds[0];
        end

        if (i_jtag_activity_jtagclk == 1'b1) begin
            // NOTE: this isn't proper CDC...
            // fit for demonstration only.

            i_leds[1] <= 1'b1;
        end
        if (|i_millisecond_counter[6:0] == 1'b0) begin
            i_leds[1] <= 0;
        end

        i_leds[3:2] <= i_buttons[1:0];
        i_leds[4]   <= i_pad[0];
        i_leds[5]   <= i_pad[1];

        if (i_sysclk_resetn == 1'b0) begin
            i_leds <= 0;
        end
    end
    assign pad_leds_n = ~i_leds;
        // NOTE:
        //          led[5]: i_pad[1]
        //          led[4]: i_pad[0]
        //          led[3]: i_buttons[1]
        //          led[2]: i_buttons[0]
        //          led[1]: JTAG Activity
        //          led[0]: Heartbeat

endmodule
