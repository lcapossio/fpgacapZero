# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Vivado build script for the fpgacapZero Arty A7-100T VexRiscv reference
# design. Sibling of build_arty.tcl; the CPU subsystem is an
# open-source VexRiscv (examples/arty_a7/vex/) instead of MicroBlaze.
#
# Prerequisites (done by build_arty_vex.py before Vivado): vex/VexRiscv_Lite.v
# is fetched and vex/fw/fw.mem is built. Usage (from project root):
#   vivado -mode batch -source examples/arty_a7/build_arty_vex.tcl

set project_name fpgacapZero_arty_vex
set part         xc7a100tcsg324-1
set example_dir  [file normalize [file dirname [info script]]]
set root         [file normalize $example_dir/../..]

if {[info exists ::env(FPGACAP_PROJECT_DIR)]} {
    set override_project_dir [file normalize $::env(FPGACAP_PROJECT_DIR)]
} else {
    set override_project_dir ""
}

if {[llength [current_project -quiet]] > 0} {
    close_project
}

if {$override_project_dir ne ""} {
    set project_dir $override_project_dir
    puts "Using override project dir: $project_dir"
} else {
    set project_dir $root/vivado/$project_name
}
set project_xpr $project_dir/$project_name.xpr

# Clear stale peripheral dirs if the .xpr is gone but a killed build left them.
if {![file exists $project_xpr]} {
    foreach stale_dir [list \
        $project_dir/$project_name.runs \
        $project_dir/$project_name.cache \
        $project_dir/$project_name.hw \
        $project_dir/$project_name.ip_user_files \
        $project_dir/$project_name.sim \
    ] {
        if {[file exists $stale_dir]} {
            puts "Removing stale Vivado dir: $stale_dir"
            if {[catch {file delete -force -- $stale_dir} err]} {
                puts "WARNING: could not delete $stale_dir: $err"
                after 2000
                catch {file delete -force -- $stale_dir}
            }
        }
    }
}

# Source list shared by the create and open paths. Adds the fcapz cores, the
# on-chip test slave, the new top, and the VexRiscv subsystem RTL + firmware
# image ($readmemh loads vex/fw/fw.mem into the CPU BRAM).
set src_list [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/reset_sync.v \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela.v \
    $root/rtl/fcapz_core_manager.v \
    $root/rtl/fcapz_debug_multi_xilinx7.v \
    $root/rtl/fcapz_ela_xilinx7.v \
    $root/rtl/jtag_reg_iface.v \
    $root/rtl/jtag_pipe_iface.v \
    $root/rtl/jtag_burst_read.v \
    $root/rtl/jtag_tap/jtag_tap_xilinx7.v \
    $root/rtl/fcapz_async_fifo.v \
    $root/rtl/fcapz_ejtagaxi.v \
    $root/rtl/fcapz_ejtagaxi_xilinx7.v \
    $root/rtl/fcapz_axi_mon.v \
    $root/rtl/fcapz_axi_mon_xilinx7.v \
    $root/rtl/fcapz_eio.v \
    $root/rtl/fcapz_eio_xilinx7.v \
    $root/tb/axi4_test_slave.v \
    $example_dir/arty_a7_vex_top.v \
    $example_dir/vex/VexRiscv_Lite.v \
    $example_dir/vex/vex_cpu.v \
    $example_dir/vex/vex_sys.v \
    $example_dir/vex/fw/fw.mem \
]

proc _mark_version_header {root} {
    set_property file_type "Verilog Header" [get_files $root/rtl/fcapz_version.vh]
    set_property is_global_include true     [get_files $root/rtl/fcapz_version.vh]
}

if {[file exists $project_xpr]} {
    open_project $project_xpr
    if {[get_runs -quiet impl_1]  ne {}} { reset_run impl_1 }
    if {[get_runs -quiet synth_1] ne {}} { reset_run synth_1 }
    foreach src $src_list {
        if {[llength [get_files -quiet $src]] == 0} {
            add_files $src
        }
    }
    _mark_version_header $root
} else {
    create_project $project_name $project_dir -part $part -force
    add_files $src_list
    _mark_version_header $root
    add_files -fileset constrs_1 $example_dir/arty_a7.xdc
    set_property top arty_a7_vex_top [current_fileset]
}

# ── VexRiscv SmartConnect block design + HDL wrapper ──────────
# vex_sys instantiates vex_bus_wrapper (SmartConnect: S00=vex_cpu master,
# S01=EJTAG bridge, M00=M_BUS). Generated fresh into the project if absent.
source $example_dir/vex/create_vex_bd.tcl
if {[llength [get_files -quiet vex_bus.bd]] == 0} {
    fcapz_build_vex_bd vex_bus
    make_wrapper -files [get_files vex_bus.bd] -top -import
}
set_property top arty_a7_vex_top [current_fileset]

# ── Synthesise + implement + write bitstream ──────────────────
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# ── Copy bitfile to example directory ─────────────────────────
file copy -force \
    $project_dir/${project_name}.runs/impl_1/arty_a7_vex_top.bit \
    $example_dir/arty_a7_vex_top.bit

puts "\n=== Build complete: examples/arty_a7/arty_a7_vex_top.bit ==="
