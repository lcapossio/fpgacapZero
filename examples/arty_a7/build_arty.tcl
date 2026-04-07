# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Vivado build script for fpgacapZero Arty A7-100T reference design.
#
# Usage (from project root):
#   vivado -mode batch -source examples/arty_a7/build_arty.tcl

set project_name fpgacapZero_arty
set part         xc7a100tcsg324-1
set example_dir  [file normalize [file dirname [info script]]]
set root         [file normalize $example_dir/../..]

# ── Create project (force overwrites any existing project) ────
# If a stale project is open from a previous run, close it first.
if {[llength [current_project -quiet]] > 0} {
    close_project
}
create_project $project_name $root/vivado/$project_name \
    -part $part -force

# ── Sources ───────────────────────────────────────────────────
add_files [list \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela.v \
    $root/rtl/fcapz_ela_xilinx7.v \
    $root/rtl/jtag_reg_iface.v \
    $root/rtl/jtag_burst_read.v \
    $root/rtl/jtag_tap/jtag_tap_xilinx7.v \
    $root/rtl/fcapz_async_fifo.v \
    $root/rtl/fcapz_ejtagaxi.v \
    $root/rtl/fcapz_ejtagaxi_xilinx7.v \
    $root/rtl/fcapz_eio.v \
    $root/rtl/fcapz_eio_xilinx7.v \
    $root/tb/axi4_test_slave.v \
    $example_dir/arty_a7_top.v \
]

add_files -fileset constrs_1 $example_dir/arty_a7.xdc

set_property top arty_a7_top [current_fileset]

# ── Synthesise + implement + write bitstream ──────────────────
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# ── Copy bitfile to example directory ─────────────────────────
file copy -force \
    $root/vivado/$project_name/${project_name}.runs/impl_1/arty_a7_top.bit \
    $example_dir/arty_a7_top.bit

puts "\n=== Build complete: examples/arty_a7/arty_a7_top.bit ==="
