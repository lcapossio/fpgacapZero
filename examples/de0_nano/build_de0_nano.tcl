# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil
#
# Build the DE0-Nano example with Quartus (tested with Quartus II 13.1 Web Edition):
#   quartus_sh -t build_de0_nano.tcl
# Output: output_files/de0_nano.sof
load_package flow
cd [file dirname [info script]]
project_open de0_nano -revision de0_nano
execute_flow -compile
project_close
