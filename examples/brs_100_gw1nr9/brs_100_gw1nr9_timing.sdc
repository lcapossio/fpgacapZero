create_clock -name clk_27Mhz        -period 37.037  -waveform {0 18.518}    [get_ports  {pad_clk_27Mhz}]

create_clock -name clk_51Mhz        -period 19.608  -waveform {0 9.804}     [get_pins   {brs_100_gw1nr9_top/rpll_51mhz_inst/CLKOUT}]
create_clock -name clk_51Mhz_p      -period 19.608  -waveform {0 9.804}     [get_pins   {brs_100_gw1nr9_top/rpll_51mhz_inst/CLKOUTP}]


# NOTE: all clocks, to/from everything else

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_51Mhz}]
set_false_path -from [get_clocks {clk_51Mhz}]       -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_51Mhz_p}]
set_false_path -from [get_clocks {clk_51Mhz_p}]     -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_51Mhz}]       -to [get_clocks {clk_51Mhz_p}]
set_false_path -from [get_clocks {clk_51Mhz_p}]     -to [get_clocks {clk_51Mhz}]
