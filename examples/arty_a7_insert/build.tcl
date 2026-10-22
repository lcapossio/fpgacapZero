# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Non-project flow: synthesize a design that has no fcapz RTL, insert the
# ELA into its netlist, then place, route and write the bitstream.
#
#   vivado -mode batch -source examples/arty_a7_insert/build.tcl

set here [file normalize [file dirname [info script]]]
set root [file normalize $here/../..]
set out  $root/vivado/arty_a7_insert
set part xc7a100tcsg324-1
file mkdir $out

source $root/tools/fcapz_insert_vivado.tcl

# 1. the user's own synthesis, untouched
read_verilog $here/insert_demo_top.v
read_xdc     $here/insert_demo.xdc
synth_design -top insert_demo_top -part $part
write_checkpoint -force $out/post_synth.dcp
close_design

# 2. insertion
fcapz::insert -in $out/post_synth.dcp -out $out/instrumented.dcp \
    -rtl $root/rtl -prob $here/insert_demo.prob -depth 1024 -chain 1 \
    -clock_hz 100000000

# 3. implementation (the instrumented design is still open)
opt_design
place_design
route_design
report_timing_summary -file $out/timing.rpt
# The ELA's clock crossings, held to their set_max_delay bounds.
set sclk [get_clocks board_clk]
report_timing -from [get_clocks u_fcapz_ela_tck] -to $sclk -max_paths 10 \
    -file $out/cdc.rpt
report_timing -from $sclk -to [get_clocks u_fcapz_ela_tck] -max_paths 10 \
    -append -file $out/cdc.rpt
report_utilization    -file $out/utilization.rpt
write_bitstream -force $here/insert_demo_top.bit
puts "wrote $here/insert_demo_top.bit"
