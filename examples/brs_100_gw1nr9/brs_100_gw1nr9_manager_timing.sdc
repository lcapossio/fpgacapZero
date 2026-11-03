// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
// brs_100_gw1nr9_timing.sdc, for the core-manager top.

create_clock -name clk_27Mhz        -period 37.037  -waveform {0 18.518}    [get_ports  {pad_clk_27Mhz}]

create_clock -name clk_60Mhz        -period 16.667  -waveform {0 8.335}     [get_pins   {brs_100_gw1nr9_manager_top/rpll_60mhz_inst/CLKOUT}]
create_clock -name clk_60Mhz_p      -period 16.667  -waveform {0 8.335}     [get_pins   {brs_100_gw1nr9_manager_top/rpll_60mhz_inst/CLKOUTP}]

create_clock -name clk_18Mhz        -period 55.556  -waveform {0 27.778}    [get_pins   {brs_100_gw1nr9_manager_top/rpll_18mhz_inst/CLKOUT}]
create_clock -name clk_18Mhz_p      -period 55.556  -waveform {0 27.778}    [get_pins   {brs_100_gw1nr9_manager_top/rpll_18mhz_inst/CLKOUTP}]

create_clock -name clk_tck          -period 400.000 -waveform {0 200.000}   [get_ports  {tck_pad_i}]


# NOTE: all clocks, to/from everything else

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_60Mhz}]
set_false_path -from [get_clocks {clk_60Mhz}]       -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_60Mhz_p}]
set_false_path -from [get_clocks {clk_60Mhz_p}]     -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_60Mhz}]       -to [get_clocks {clk_60Mhz_p}]
set_false_path -from [get_clocks {clk_60Mhz_p}]     -to [get_clocks {clk_60Mhz}]

set_false_path -from [get_clocks {clk_60Mhz}]       -to [get_clocks {clk_tck}]
set_false_path -from [get_clocks {clk_tck}]         -to [get_clocks {clk_60Mhz}]

set_false_path -from [get_clocks {clk_60Mhz}]       -to [get_clocks {clk_18Mhz}]
set_false_path -from [get_clocks {clk_18Mhz}]       -to [get_clocks {clk_60Mhz}]

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_18Mhz}]
set_false_path -from [get_clocks {clk_18Mhz}]       -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_18Mhz_p}]
set_false_path -from [get_clocks {clk_18Mhz_p}]     -to [get_clocks {clk_27Mhz}]

set_false_path -from [get_clocks {clk_18Mhz}]       -to [get_clocks {clk_18Mhz_p}]
set_false_path -from [get_clocks {clk_18Mhz_p}]     -to [get_clocks {clk_18Mhz}]

set_false_path -from [get_clocks {clk_18Mhz}]       -to [get_clocks {clk_tck}]
set_false_path -from [get_clocks {clk_tck}]         -to [get_clocks {clk_18Mhz}]


set_false_path -from [get_clocks {clk_27Mhz}]       -to [get_clocks {clk_tck}]
set_false_path -from [get_clocks {clk_tck}]         -to [get_clocks {clk_27Mhz}]