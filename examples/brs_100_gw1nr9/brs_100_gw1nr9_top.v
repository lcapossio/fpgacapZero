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
localparam int CLK_FREQUENCY_MHZ    = 51;
localparam int CLK_FREQUENCY_HZ     = CLK_FREQUENCY_MHZ * 1000000;
localparam int SAMPLE_W             = 8;
localparam int DEPTH                = 512;

    // ----------------------------------------------
    //  Constants
    // ----------------------------------------------

    wire    c_vcc;
    wire    c_gnd;

    assign  c_vcc = 1'b1;
    assign  c_gnd = 1'b0;


    // ----------------------------------------------
    //  Definitions
    // ----------------------------------------------

    defparam rpll_51mhz_inst.FCLKIN             = "27";
    defparam rpll_51mhz_inst.DYN_IDIV_SEL       = "false";

    defparam rpll_51mhz_inst.IDIV_SEL           = 8;
    defparam rpll_51mhz_inst.FBDIV_SEL          = 16;
    defparam rpll_51mhz_inst.ODIV_SEL           = 8;
        // NOTE: 51 Mhz

    defparam rpll_51mhz_inst.DYN_FBDIV_SEL      = "false";
    defparam rpll_51mhz_inst.DYN_ODIV_SEL       = "false";
    defparam rpll_51mhz_inst.PSDA_SEL           = "0100";
    defparam rpll_51mhz_inst.DYN_DA_EN          = "false";
    defparam rpll_51mhz_inst.DUTYDA_SEL         = "1000";
    defparam rpll_51mhz_inst.CLKOUT_FT_DIR      = 1'b1;
    defparam rpll_51mhz_inst.CLKOUTP_FT_DIR     = 1'b1;
    defparam rpll_51mhz_inst.CLKOUT_DLY_STEP    = 0;
    defparam rpll_51mhz_inst.CLKOUTP_DLY_STEP   = 0;
    defparam rpll_51mhz_inst.CLKFB_SEL          = "internal";
    defparam rpll_51mhz_inst.CLKOUT_BYPASS      = "false";
    defparam rpll_51mhz_inst.CLKOUTP_BYPASS     = "false";
    defparam rpll_51mhz_inst.CLKOUTD_BYPASS     = "false";
    defparam rpll_51mhz_inst.DYN_SDIV_SEL       = 2;
    defparam rpll_51mhz_inst.CLKOUTD_SRC        = "CLKOUT";
    defparam rpll_51mhz_inst.CLKOUTD3_SRC       = "CLKOUT";
    defparam rpll_51mhz_inst.DEVICE             = "GW1NR-9C";


    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    reg [5:0]           i_leds;

    reg                 i_sysclk;
    reg                 i_sysclk_resetn = 1'b0;
    reg                 i_sysclk_reset;

    reg                 i_microsecond_tick;
    reg                 i_millisecond_tick;
    reg                 i_second_tick;

    reg     [8:0]       i_microsecond_div_counter;
    reg     [19:0]      i_millisecond_div_counter;
    reg     [9:0]       i_millisecond_counter;

    reg                 i_jtag_activity;

    reg [SAMPLE_W-1:0]  i_counter;



    // ----------------------------------------------
    //  Implementation
    // ----------------------------------------------


    // NOTE: ELA
    // Related
    // ------------

    always @(posedge i_sysclk) begin
        if (i_sysclk_resetn == 1'b0) begin
            i_counter <= {SAMPLE_W{1'b0}};
        end else begin
            i_counter <= i_counter + 1'b1;
        end
    end

    fcapz_ela_gowin #(
        .SAMPLE_W       (SAMPLE_W),
        .DEPTH          (DEPTH),
        .EIO_EN         (0)
    ) u_ela (
        .sysclk         (i_sysclk),
            // TODO: different clock for demonstration
            // purposes...

        .sample_clk     (i_sysclk),
        .sample_rst     (i_sysclk_reset),
        .probe_in       (i_counter),

        .eio_probe_in   (0),
        .eio_probe_out  (),
            // NOTE: external trigger ports
            // tie off if not used

        .debug          (i_leds),

        .tms_pad_i      (tms_pad_i),
        .tck_pad_i      (tck_pad_i),
        .tdi_pad_i      (tdi_pad_i),
        .tdo_pad_o      (tdo_pad_o)
    );



    // NOTE: Clocking
    // ------------

    rPLL rpll_51mhz_inst (
        .CLKOUT     (i_sysclk),
        .LOCK       (i_sysclk_resetn),
        .CLKOUTP    (),
        .CLKOUTD    (),
        .CLKOUTD3   (),

        .RESET      (c_gnd),
        .RESET_P    (c_gnd),

        .CLKIN      (pad_clk_27Mhz),

        .CLKFB      (c_gnd),

        .FBDSEL     ({c_gnd,c_gnd,c_gnd,c_gnd,c_gnd,c_gnd}),
        .IDSEL      ({c_gnd,c_gnd,c_gnd,c_gnd,c_gnd,c_gnd}),
        .ODSEL      ({c_gnd,c_gnd,c_gnd,c_gnd,c_gnd,c_gnd}),
        .PSDA       ({c_gnd,c_gnd,c_gnd,c_gnd}),
        .DUTYDA     ({c_gnd,c_gnd,c_gnd,c_gnd}),
        .FDLY       ({c_vcc,c_vcc,c_vcc,c_vcc})
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

/*    always @(posedge i_sysclk) begin
        if (i_second_tick == 1'b1) begin
            i_leds[0] <= ~i_leds[0];
        end

        if (i_jtag_activity == 1'b1) begin
            // TODO

            i_leds[1] <= 1'b1;
        end

        if (|i_millisecond_counter[6:0] == 1'b1) begin
            i_leds[5:1] <= 0;
        end
        if (i_sysclk_resetn == 1'b0) begin
            i_leds <= 0;
        end
    end*/
    assign pad_leds_n = i_leds;
        // NOTE:
        //          led[4]: TODO
        //          led[3]: TODO
        //          led[2]: TODO
        //          led[1]: TODO
        //          led[0]: heartbeat



endmodule
