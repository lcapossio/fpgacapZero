# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil
#
# Build the Arty S7-25 example (non-project mode; tested with Vivado 2025.2.1):
#   vivado -mode batch -source build_arty_s7.tcl
# Output: arty_s7_fcapz.bit (utilization and timing reports in out/)
cd [file dirname [info script]]
set rtl ../../rtl
read_verilog -sv [list \
    $rtl/fcapz_version.vh $rtl/reset_sync.v $rtl/dpram.v $rtl/trig_compare.v \
    $rtl/fcapz_ela.v $rtl/fcapz_core_manager.v $rtl/fcapz_debug_multi_core.v \
    $rtl/fcapz_hub_reset.v $rtl/fcapz_debug_multi.v $rtl/fcapz_debug_multi_xilinx7.v \
    $rtl/fcapz_ela_xilinx7.v $rtl/jtag_reg_iface.v $rtl/jtag_pipe_iface.v \
    $rtl/jtag_burst_read.v $rtl/jtag_tap/jtag_tap_xilinx7.v $rtl/fcapz_eio.v \
    $rtl/fcapz_eio_xilinx7.v arty_s7_top.v]
set_property file_type {Verilog Header} [get_files $rtl/fcapz_version.vh]
set_property is_global_include true [get_files $rtl/fcapz_version.vh]
read_xdc arty_s7.xdc
synth_design -top arty_s7_top -part xc7s25csga324-1 -include_dirs $rtl
opt_design
place_design
route_design
file mkdir out
report_utilization -file out/utilization.rpt
report_timing_summary -file out/timing_summary.rpt
# No bitstream from a design that misses timing (the JTAG clock included):
# setup, hold and pulse width, as the timing summary judges them.
set summary [report_timing_summary -no_detailed_paths -return_string]
if {![string match "*All user specified timing constraints are met.*" $summary]} {
    error "routed design misses timing; see out/timing_summary.rpt"
}
write_bitstream -force arty_s7_fcapz.bit
