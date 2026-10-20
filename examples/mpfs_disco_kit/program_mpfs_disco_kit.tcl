# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Program the PolarFire SoC Discovery Kit from the project that
# build_mpfs_disco_kit.tcl made, through the first FlashPro found.
#   libero SCRIPT:program_mpfs_disco_kit.tcl "SCRIPT_ARGS:<repo path>"
#
# Nothing else may hold the FlashPro's JTAG channel (OpenOCD, a bit-bang
# bridge) while this runs.

if {$argc < 1} {
    error "Expecting SCRIPT_ARGS:<repo path>"
}
set repo_path [file normalize [lindex $argv 0]]
set proj_name "mpfs_disco_kit_fcapz"
set proj_file "${repo_path}/examples/mpfs_disco_kit/libero/${proj_name}/${proj_name}.prjx"

open_project -file $proj_file
run_tool -name {PROGRAMDEVICE}
close_project
exit 0
