# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Vivado build script for the Arty A7-100T mixed-language reference design.
# Verilog vendor wrappers/TAP plumbing instantiate VHDL fcapz_ela/fcapz_eio
# core entities.

set project_name fpgacapZero_arty_vhdl
set part         xc7a100tcsg324-1
set example_dir  [file normalize [file dirname [info script]]]
set root         [file normalize $example_dir/../..]

# Vivado 2025.2 can leave the per-user Tcl store support package outside the
# startup auto_path after an interrupted update. Add the nested support paths
# when they already exist; this is a no-op on clean installations.
if {[info exists ::env(APPDATA)]} {
    regsub -all {\\} $::env(APPDATA) {/} appdata_dir
    set xilinx_tcl_store [file join $appdata_dir Xilinx Vivado [version -short] XilinxTclStore]
    foreach support_dir [list \
        [file join $xilinx_tcl_store support] \
        [file join $xilinx_tcl_store support appinit] \
        [file join $xilinx_tcl_store support args] \
        [file join $xilinx_tcl_store tclapp] \
        [file join $xilinx_tcl_store tclapp xilinx] \
        [file join $xilinx_tcl_store tclapp xilinx xsim] \
    ] {
        if {[file isdirectory $support_dir] && [lsearch -exact $::auto_path $support_dir] < 0} {
            lappend ::auto_path $support_dir
        }
    }
}

set_param project.enableUnifiedSimulation 0

if {[info exists ::env(FPGACAP_PROJECT_DIR)]} {
    set project_dir [file normalize $::env(FPGACAP_PROJECT_DIR)]
} else {
    set project_dir $root/vivado/$project_name
}

if {[llength [current_project -quiet]] > 0} {
    close_project
}

create_project $project_name $project_dir -part $part -force

add_files [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/vhdl/pkg/fcapz_pkg.vhd \
    $root/rtl/vhdl/pkg/fcapz_util_pkg.vhd \
    $root/rtl/vhdl/core/fcapz_dpram.vhd \
    $root/rtl/vhdl/core/fcapz_ela.vhd \
    $root/rtl/vhdl/core/fcapz_eio.vhd \
    $root/rtl/reset_sync.v \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela_xilinx7.v \
    $root/rtl/jtag_reg_iface.v \
    $root/rtl/jtag_pipe_iface.v \
    $root/rtl/jtag_burst_read.v \
    $root/rtl/jtag_tap/jtag_tap_xilinx7.v \
    $root/rtl/fcapz_async_fifo.v \
    $root/rtl/fcapz_ejtagaxi.v \
    $root/rtl/fcapz_ejtagaxi_xilinx7.v \
    $root/rtl/fcapz_eio_xilinx7.v \
    $root/tb/axi4_test_slave.v \
    $example_dir/arty_a7_top.vhd \
]

set_property file_type "Verilog Header" [get_files $root/rtl/fcapz_version.vh]
set_property is_global_include true [get_files $root/rtl/fcapz_version.vh]
set_property file_type "VHDL 2008" [get_files [list \
    $root/rtl/vhdl/pkg/fcapz_pkg.vhd \
    $root/rtl/vhdl/pkg/fcapz_util_pkg.vhd \
    $root/rtl/vhdl/core/fcapz_dpram.vhd \
    $root/rtl/vhdl/core/fcapz_ela.vhd \
    $root/rtl/vhdl/core/fcapz_eio.vhd \
    $example_dir/arty_a7_top.vhd \
]]

update_compile_order -fileset sources_1

add_files -fileset constrs_1 $example_dir/arty_a7.xdc
set_property top arty_a7_top [current_fileset]

synth_design -top arty_a7_top -part $part
opt_design
place_design
route_design
write_bitstream -force $example_dir/arty_a7_top_vhdl.bit

puts "\n=== VHDL build complete: examples/arty_a7/arty_a7_top_vhdl.bit ==="
