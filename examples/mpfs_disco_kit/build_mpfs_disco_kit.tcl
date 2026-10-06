# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Libero SoC batch flow for the PolarFire SoC Discovery Kit example.
# Run through build.py, or directly:
#   libero SCRIPT:build_mpfs_disco_kit.tcl "SCRIPT_ARGS:<repo path> [program]"
#
# Builds a fresh project under examples/mpfs_disco_kit/libero/ (synthesis,
# place-and-route, timing, programming data).  With "program", it then
# programs the board through the first FlashPro found.

if {$argc < 1} {
    error "Expecting SCRIPT_ARGS:<repo path> \[program\]"
}
set repo_path [file normalize [lindex $argv 0]]
set do_program [expr {$argc > 1 && [lindex $argv 1] eq "program"}]

set example_dir "${repo_path}/examples/mpfs_disco_kit"
set build_dir   "${example_dir}/libero"
set proj_name   "mpfs_disco_kit_fcapz"
set proj_dir    "${build_dir}/${proj_name}"
set top         "mpfs_disco_kit_top"

if {[file isdirectory $proj_dir]} {
    file delete -force $proj_dir
}
file mkdir $build_dir

new_project \
    -location $proj_dir \
    -name $proj_name \
    -project_description {fpgacapZero ELA + EIO on the PolarFire SoC Discovery Kit} \
    -hdl {VERILOG} \
    -family {PolarFireSoC} \
    -die {MPFS095T} \
    -package {FCSG325} \
    -speed {-1} \
    -die_voltage {1.0} \
    -part_range {EXT} \
    -adv_options {IO_DEFT_STD:LVCMOS 1.8V}

set rtl "${repo_path}/rtl"
set hdl_files [list \
    "${rtl}/fcapz_version.vh" \
    "${rtl}/reset_sync.v" \
    "${rtl}/dpram.v" \
    "${rtl}/trig_compare.v" \
    "${rtl}/fcapz_ela.v" \
    "${rtl}/fcapz_eio.v" \
    "${rtl}/fcapz_regbus_mux.v" \
    "${rtl}/jtag_reg_iface.v" \
    "${rtl}/jtag_burst_read.v" \
    "${rtl}/jtag_tap/jtag_tap_polarfire.v" \
    "${rtl}/fcapz_ela_polarfire.v" \
    "${example_dir}/${top}.v" \
]
foreach src $hdl_files {
    create_links -hdl_source $src
}
create_links -io_pdc "${example_dir}/mpfs_disco_kit_io.pdc"
create_links -sdc    "${example_dir}/mpfs_disco_kit.sdc"

build_design_hierarchy
set_root -module "${top}::work"

organize_tool_files -tool {SYNTHESIZE} \
    -file "${example_dir}/mpfs_disco_kit.sdc" \
    -module "${top}::work" -input_type {constraint}
organize_tool_files -tool {PLACEROUTE} \
    -file "${example_dir}/mpfs_disco_kit_io.pdc" \
    -file "${example_dir}/mpfs_disco_kit.sdc" \
    -module "${top}::work" -input_type {constraint}
organize_tool_files -tool {VERIFYTIMING} \
    -file "${example_dir}/mpfs_disco_kit.sdc" \
    -module "${top}::work" -input_type {constraint}

run_tool -name {SYNTHESIZE}
run_tool -name {PLACEROUTE}
run_tool -name {VERIFYTIMING}
run_tool -name {GENERATEPROGRAMMINGDATA}

if {$do_program} {
    run_tool -name {PROGRAMDEVICE}
}

save_project
close_project
exit 0
