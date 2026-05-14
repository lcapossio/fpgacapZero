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

# Allow build.py to override the project dir (used to sidestep a
# locked stale dir from a prior killed build).
if {[info exists ::env(FPGACAP_PROJECT_DIR)]} {
    set override_project_dir [file normalize $::env(FPGACAP_PROJECT_DIR)]
} else {
    set override_project_dir ""
}

# ── Open or create project ────────────────────────────────────
# If the project already exists on disk, reuse it (and reset any stale
# run state from a killed previous build).  Otherwise create fresh.
# Using create_project -force on a project with a half-dead runs dir
# races against lock files and reports "Project 1-161: Failed to
# remove the directory" on Windows, so we avoid that path.
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

# If the Vivado .xpr is missing but the peripheral run/cache dirs are
# still on disk from a previous killed build, Vivado's own
# create_project -force sometimes fails with
#   [Project 1-161] Failed to remove the directory ...
# on Windows due to a brief OS-level directory handle.  We clear those
# stale directories here using Tcl's file delete (a Tcl builtin, not a
# shell primitive).  Only touched when the .xpr is absent — a valid
# existing project is left untouched and gets reset_run instead.
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
                puts "WARNING: retrying after 2 seconds..."
                after 2000
                if {[catch {file delete -force -- $stale_dir} err2]} {
                    puts "ERROR: still cannot delete $stale_dir: $err2"
                }
            }
        }
    }
}

if {[file exists $project_xpr]} {
    open_project $project_xpr
    # Reset any in-flight / stuck runs so they can be relaunched cleanly.
    if {[get_runs -quiet impl_1] ne {}} {
        reset_run impl_1
    }
    if {[get_runs -quiet synth_1] ne {}} {
        reset_run synth_1
    }
    foreach src [list \
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
        $root/rtl/fcapz_eio.v \
        $root/rtl/fcapz_eio_xilinx7.v \
        $root/tb/axi4_test_slave.v \
        $example_dir/arty_a7_top.v \
    ] {
        if {[llength [get_files -quiet $src]] == 0} {
            add_files $src
        }
    }
    set_property file_type "Verilog Header" \
        [get_files $root/rtl/fcapz_version.vh]
    set_property is_global_include true \
        [get_files $root/rtl/fcapz_version.vh]
} else {
    # No .xpr but partial peripheral dirs may exist from a killed build.
    # Use -force to clear them now that we've removed the stale locks.
    create_project $project_name $project_dir -part $part -force

    # ── Sources (only added on initial creation) ──────────────
    add_files [list \
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
        $root/rtl/fcapz_eio.v \
        $root/rtl/fcapz_eio_xilinx7.v \
        $root/tb/axi4_test_slave.v \
        $example_dir/arty_a7_top.v \
    ]
    # Mark the version header as a global include so every Verilog source
    # in the project can reference it without needing per-file -I.
    set_property file_type "Verilog Header" \
        [get_files $root/rtl/fcapz_version.vh]
    set_property is_global_include true \
        [get_files $root/rtl/fcapz_version.vh]

    add_files -fileset constrs_1 $example_dir/arty_a7.xdc
    set_property top arty_a7_top [current_fileset]
}

# ── Synthesise + implement + write bitstream ──────────────────
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# ── Copy bitfile to example directory ─────────────────────────
file copy -force \
    $project_dir/${project_name}.runs/impl_1/arty_a7_top.bit \
    $example_dir/arty_a7_top.bit

puts "\n=== Build complete: examples/arty_a7/arty_a7_top.bit ==="
