# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# KV260: synthesize a design that has no fcapz RTL (a project, for the PS
# block design), insert the debug cores into its netlist, then place, route
# and write the bitstream from the instrumented checkpoint.
#
#   vivado -mode batch -source examples/kv260_insert/build.tcl
#
# Needs the KV260 SOM board files (Vivado's board store: "kv260_som").

set here [file normalize [file dirname [info script]]]
set root [file normalize $here/../..]
set out  $root/vivado/kv260_insert
set part xck26-sfvc784-2LV-c
file mkdir $out

source $root/tools/fcapz_insert_vivado.tcl

# 1. the user's own synthesis, untouched
create_project kv260_insert $out/proj -part $part -force
set board [lindex [lsort -dictionary [get_board_parts -quiet *:kv260_som:*]] end]
if {$board eq ""} {
    error "KV260 SOM board files not found; install kv260_som from the\
           Vivado board store (Tools > Vivado Store > Boards)"
}
set_property board_part $board [current_project]
add_files $here/insert_demo_top.v
source $root/examples/kv260/create_ps_bd.tcl
fcapz_create_ps_bd kv260_ps
generate_target all [get_files kv260_ps.bd]
make_wrapper -files [get_files kv260_ps.bd] -top -import
set_property top insert_demo_top [current_fileset]
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "synth_1 did not complete: [get_property STATUS [get_runs synth_1]]"
}
open_run synth_1
write_checkpoint -force $out/post_synth.dcp
close_project

# 2. insertion (names an ELA by its clock net, as the Arty demo does)
fcapz::insert -in $out/post_synth.dcp -out $out/instrumented.dcp \
    -rtl $root/rtl -prob $here/insert_demo.prob -depth 1024 -chain 1 \
    -depths {clk_div 512} \
    -eio_in {ctrl_q[0] ctrl_q[1] ctrl_q[2] ctrl_q[3] armed_flag} \
    -eio_out {ctrl[0] ctrl[1] ctrl[2] ctrl[3]} \
    -trigger_in {clk_div tick} \
    -cross_trigger {clk clk_div} \
    -armed_out {clk armed_flag}

# 3. implementation (the instrumented design is still open)
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
opt_design
place_design
route_design
report_timing_summary -file $out/timing.rpt
report_utilization    -file $out/utilization.rpt
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
if {$wns < 0 || $whs < 0} {
    error "timing not met (WNS $wns ns, WHS $whs ns)"
}
write_bitstream -force $here/insert_demo_top.bit
puts "wrote $here/insert_demo_top.bit"
