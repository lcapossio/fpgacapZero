# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Vivado build script for the Arty A7-100T mixed-language reference design.
# The top and the fcapz_ela/fcapz_eio/fcapz_axi_mon cores are VHDL; the Verilog
# vendor wrappers/TAP plumbing bind to those entities, and the shared-bus CPU is
# the open-source Verilog VexRiscv subsystem (vex_sys + fcapz_axi_interconnect),
# mixed-language into the VHDL top exactly where the MicroBlaze wrapper used to
# sit. The firmware image (vex/fw/fw.mem, $readmemh into the CPU BRAM) is built
# by build_vhdl.py before Vivado, so no MicroBlaze block design / mb-gcc.
#
# Usage (from project root, after build_vhdl.py fetched the core + built fw.mem):
#   vivado -mode batch -source examples/arty_a7/build_arty_vhdl.tcl

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

# Allow build.py to override the project dir (used to sidestep a locked stale
# dir from a prior killed build).
if {[info exists ::env(FPGACAP_PROJECT_DIR)]} {
    set override_project_dir [file normalize $::env(FPGACAP_PROJECT_DIR)]
} else {
    set override_project_dir ""
}

# The VHDL core files that replace rtl/fcapz_ela.v, rtl/fcapz_eio.v and
# rtl/fcapz_axi_mon.v; the Verilog vendor wrappers bind their core instances
# to these entities (mixed-language, by name).
set vhdl_sources [list \
    $root/rtl/vhdl/pkg/fcapz_pkg.vhd \
    $root/rtl/vhdl/pkg/fcapz_util_pkg.vhd \
    $root/rtl/vhdl/core/fcapz_dpram.vhd \
    $root/rtl/vhdl/core/fcapz_ela.vhd \
    $root/rtl/vhdl/core/fcapz_eio.vhd \
    $root/rtl/vhdl/core/fcapz_axi_mon.vhd \
    $example_dir/arty_a7_top.vhd \
]

# Verilog TAP plumbing, vendor wrappers, bridge, monitor wrapper, test slave,
# and the VexRiscv shared-bus subsystem (interconnect + vendored core + shared
# vex_cpu + board vex_sys + firmware image).  The fcapz_ela.v/fcapz_eio.v/
# fcapz_axi_mon.v cores and arty_a7_top.v are replaced by their VHDL versions.
set verilog_sources [list \
    $root/rtl/reset_sync.v \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
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
    $root/rtl/fcapz_axi_mon_xilinx7.v \
    $root/rtl/fcapz_eio_xilinx7.v \
    $root/rtl/fcapz_axi_interconnect.v \
    $root/tb/axi4_test_slave.v \
    $root/third_party/vexriscv/VexRiscv_Lite.v \
    $root/examples/common/vexriscv/vex_cpu.v \
    $example_dir/vex/vex_sys.v \
    $example_dir/vex/fw/fw.mem \
]

proc _vhdl_add_sources {vhdl_sources verilog_sources example_dir} {
    foreach src $vhdl_sources {
        if {[llength [get_files -quiet $src]] == 0} {
            add_files -norecurse $src
        }
        # VHDL cores + top use VHDL-2008 constructs; set per-file so the
        # property sticks regardless of how get_files resolves the path.
        set_property file_type "VHDL 2008" [get_files $src]
    }
    foreach src $verilog_sources {
        if {[llength [get_files -quiet $src]] == 0} {
            add_files -norecurse $src
        }
    }
}

set_param project.enableUnifiedSimulation 0

# ── Open or create project ────────────────────────────────────
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

# Clear stale peripheral dirs from a killed build if the .xpr is gone (mirrors
# build_arty.tcl; avoids the Windows [Project 1-161] delete race).
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

if {[file exists $project_xpr]} {
    open_project $project_xpr
    if {[get_runs -quiet impl_1] ne {}} { reset_run impl_1 }
    if {[get_runs -quiet synth_1] ne {}} { reset_run synth_1 }
    _vhdl_add_sources $vhdl_sources $verilog_sources $example_dir
} else {
    create_project $project_name $project_dir -part $part -force
    _vhdl_add_sources $vhdl_sources $verilog_sources $example_dir
    add_files -fileset constrs_1 $example_dir/arty_a7.xdc
}
set_property top arty_a7_top [current_fileset]

# ── VexRiscv shared-bus subsystem (Verilog into the VHDL top) ──
# arty_a7_top.vhd instantiates the vex_sys component (VexRiscv CPU + EJTAG
# bridge merged onto the monitored bus by fcapz_axi_interconnect), all added to
# verilog_sources above. The firmware lives in the CPU BRAM via $readmemh of
# vex/fw/fw.mem (built by build_vhdl.py before Vivado) -- no block design, no
# LMB ELF to scope. USER3 is left free (the CPU has no JTAG debug module).

# ── Synthesise + implement + write bitstream ──────────────────
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

file copy -force \
    $project_dir/${project_name}.runs/impl_1/arty_a7_top.bit \
    $example_dir/arty_a7_top_vhdl.bit

puts "\n=== VHDL build complete: examples/arty_a7/arty_a7_top_vhdl.bit ==="
