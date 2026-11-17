# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Non-project flow: synthesize a design that has no fcapz RTL, insert the
# debug cores into its netlist, then place, route and write the bitstream.
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

# 2. insertion: one ELA per clock (named by its clock net), an EIO, and the
#    triggers between them.  Writes insert_demo_ela0/1.prob and
#    insert_demo.insert.json, which capture.py reads.
fcapz::insert -in $out/post_synth.dcp -out $out/instrumented.dcp \
    -rtl $root/rtl -prob $here/insert_demo.prob -depth 1024 -chain 1 \
    -depths {clk_slow 512} \
    -eio_in {sw_q[0] sw_q[1] sw_q[2] sw_q[3]
             ctrl_q[0] ctrl_q[1] ctrl_q[2] ctrl_q[3] armed_flag} \
    -eio_out {ctrl[0] ctrl[1] ctrl[2] ctrl[3]} \
    -trigger_in {clk_slow tick} \
    -cross_trigger {clk_IBUF_BUFG clk_slow} \
    -armed_out {clk_IBUF_BUFG armed_flag}

# 3. implementation (the instrumented design is still open)
opt_design
place_design
route_design
report_timing_summary -file $out/timing.rpt
# The debug block's clock crossings with TCK, held to their set_max_delay
# bounds.
set tck [get_clocks u_fcapz_tck]
file delete -force $out/cdc.rpt
foreach sclk [list [get_clocks board_clk] [get_clocks -of_objects [get_nets clk_slow]]] {
    report_timing -from $tck -to $sclk -max_paths 10 -append -file $out/cdc.rpt
    report_timing -from $sclk -to $tck -max_paths 10 -append -file $out/cdc.rpt
}
report_utilization    -file $out/utilization.rpt
write_bitstream -force $here/insert_demo_top.bit
puts "wrote $here/insert_demo_top.bit"
