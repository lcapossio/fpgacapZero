# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Vivado build script for the fpgacapZero Kria KV260 reference design.
#
# Usage (from project root):
#   python examples/kv260/build.py
#   vivado -mode batch -source examples/kv260/build_kv260.tcl
#
# Needs the KV260 SOM board files (Vivado's board store: "kv260_som").

set project_name fpgacapZero_kv260
set part         xck26-sfvc784-2LV-c
set example_dir  [file normalize [file dirname [info script]]]
set root         [file normalize $example_dir/../..]

if {[info exists ::env(FPGACAP_PROJECT_DIR)]} {
    set project_dir [file normalize $::env(FPGACAP_PROJECT_DIR)]
} else {
    set project_dir [file normalize $root/vivado/$project_name]
}

create_project $project_name $project_dir -part $part -force

set board [lindex [lsort -dictionary [get_board_parts -quiet *:kv260_som:*]] end]
if {$board eq ""} {
    error "KV260 SOM board files not found; install kv260_som from the\
           Vivado board store (Tools > Vivado Store > Boards)"
}
set_property board_part $board [current_project]
puts "Board part: $board"

add_files [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/reset_sync.v \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela.v \
    $root/rtl/fcapz_core_manager.v \
    $root/rtl/fcapz_debug_multi_xilinx7.v \
    $root/rtl/jtag_reg_iface.v \
    $root/rtl/jtag_pipe_iface.v \
    $root/rtl/jtag_burst_read.v \
    $root/rtl/jtag_tap/jtag_tap_xilinx7.v \
    $root/rtl/fcapz_async_fifo.v \
    $root/rtl/fcapz_ejtagaxi.v \
    $root/rtl/fcapz_ejtagaxi_xilinx7.v \
    $root/rtl/fcapz_ejtagaxi_xilinxus.v \
    $root/rtl/fcapz_ejtaguart.v \
    $root/rtl/fcapz_ejtaguart_xilinx7.v \
    $root/rtl/fcapz_ejtaguart_xilinxus.v \
    $root/rtl/fcapz_axi_mon.v \
    $root/rtl/fcapz_axi_mon_xilinx7.v \
    $root/rtl/fcapz_eio.v \
    $root/rtl/fcapz_eio_xilinx7.v \
    $root/tb/axi4_test_slave.v \
    $example_dir/kv260_top.v \
]
set_property file_type "Verilog Header" [get_files $root/rtl/fcapz_version.vh]
set_property is_global_include true     [get_files $root/rtl/fcapz_version.vh]
add_files -fileset constrs_1 $example_dir/kv260.xdc
# Timing and bitstream settings only, and the PS clock it names exists only
# once the out-of-context PS netlist is linked: implementation-only.
set_property USED_IN_SYNTHESIS false [get_files $example_dir/kv260.xdc]

source $example_dir/create_ps_bd.tcl
fcapz_create_ps_bd kv260_ps
generate_target all [get_files kv260_ps.bd]
make_wrapper -files [get_files kv260_ps.bd] -top -import

set_property top kv260_top [current_fileset]

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match "*Complete*" $impl_status]} {
    error "impl_1 did not complete: $impl_status"
}

open_run impl_1
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "Worst setup slack: $wns ns"
if {$wns < 0} {
    error "timing not met (WNS $wns ns)"
}

file copy -force \
    $project_dir/${project_name}.runs/impl_1/kv260_top.bit \
    $example_dir/kv260_top.bit

puts "\n=== Build complete: examples/kv260/kv260_top.bit ==="
