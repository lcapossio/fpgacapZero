# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

if {$argc < 1} {
    error "Expecting -tclargs <repo path>"
}

set repo_path [lindex $argv 0]
set example_dir "${repo_path}/examples/de25_nano"
set project_dir "${example_dir}/de25_nano_quartus"
set output_dir "${example_dir}/output_files"
set project_name "de25_nano_fcapz"

if {[file isdirectory $project_dir]} {
    file delete -force $project_dir
}

file mkdir $project_dir
project_new -overwrite -revision $project_name $project_dir/$project_name
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY $output_dir
set_global_assignment -name SEARCH_PATH "${repo_path}/rtl"
set_global_assignment -name SEARCH_PATH "${repo_path}/rtl/jtag_tap"
source "${example_dir}/de25_nano.qsf"

set verilog_files [list \
    "${repo_path}/rtl/reset_sync.v" \
    "${repo_path}/rtl/dpram.v" \
    "${repo_path}/rtl/trig_compare.v" \
    "${repo_path}/rtl/fcapz_ela.v" \
    "${repo_path}/rtl/fcapz_ela_intel.v" \
    "${repo_path}/rtl/fcapz_eio.v" \
    "${repo_path}/rtl/fcapz_eio_intel.v" \
    "${repo_path}/rtl/jtag_reg_iface.v" \
    "${repo_path}/rtl/jtag_burst_read.v" \
    "${repo_path}/rtl/jtag_tap/jtag_tap_intel.v" \
    "${example_dir}/de25_nano_top.v" \
]

foreach src $verilog_files {
    set_global_assignment -name VERILOG_FILE $src
}
set_global_assignment -name SDC_FILE "${example_dir}/de25_nano.sdc"

execute_flow -compile
project_close
