# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Resource comparison across configurations.
# Usage: vivado -mode batch -source scripts/resource_comparison.tcl

# Repo root = parent of scripts/ (override with env FPGACAP_ROOT if needed).
if {[info exists ::env(FPGACAP_ROOT)] && $::env(FPGACAP_ROOT) ne ""} {
    set root [file normalize $::env(FPGACAP_ROOT)]
} else {
    set root [file normalize [file join [file dirname [info script]] ..]]
}
set part xc7a100tcsg324-1

# {SAMPLE_W DEPTH TRIG_STAGES STOR_QUAL label}
set configs {
    {8    1024  1 0 "8b_1024_base"}
    {8    1024  1 1 "8b_1024_sq"}
    {8    1024  2 0 "8b_1024_2seq"}
    {8    1024  4 0 "8b_1024_4seq"}
    {8    1024  4 1 "8b_1024_full"}
    {8    256   1 0 "8b_256_base"}
    {8    4096  1 0 "8b_4096_base"}
    {32   1024  1 0 "32b_1024_base"}
    {32   4096  1 0 "32b_4096_base"}
    {128  1024  1 0 "128b_1024_base"}
    {256  1024  1 0 "256b_1024_base"}
}

puts ""
puts "=== Resource Comparison (xc7a100t, synth estimates) ==="
puts [format "%-28s %6s %6s %5s" "Config" "LUTs" "FFs" "BRAM"]
puts "-----------------------------------------------------------"

foreach cfg $configs {
    set sw     [lindex $cfg 0]
    set depth  [lindex $cfg 1]
    set stages [lindex $cfg 2]
    set sq     [lindex $cfg 3]
    set label  [lindex $cfg 4]
    set pname  "rc2_${label}"

    create_project $pname $root/vivado/$pname -part $part -force

    set fp [open "$root/vivado/top_${label}.v" w]
    puts $fp "`timescale 1ns/1ps"
    puts $fp "module arty_a7_top (input wire clk, input wire \[3:0\] btn, output wire \[3:0\] led);"
    puts $fp "  localparam SW=$sw, D=$depth, PW=\$clog2(D);"
    puts $fp "  reg \[3:0\] rp; wire rst; reg \[SW-1:0\] ctr;"
    puts $fp "  wire t1k,t1i,t1o,t1c,t1s,t1u,t1l;"
    puts $fp "  wire t2k,t2i,t2o,t2c,t2s,t2u,t2l;"
    puts $fp "  wire jc,jr,jwe,jre; wire \[15:0\] ja; wire \[31:0\] jwd,jrd;"
    puts $fp "  wire \[PW-1:0\] ba,bsp; wire \[SW-1:0\] bd; wire bs;"
    puts $fp "  always @(posedge clk) rp<={rp\[2:0\],btn\[0\]};"
    puts $fp "  assign rst=rp\[3\];"
    puts $fp "  always @(posedge clk) if(rst) ctr<=0; else ctr<=ctr+1;"
    puts $fp "  assign led=ctr\[3:0\];"
    puts $fp "  jtag_tap_xilinx7 #(.CHAIN(1)) u_t1(.tck(t1k),.tdi(t1i),.tdo(t1o),.capture(t1c),.shift(t1s),.update(t1u),.sel(t1l));"
    puts $fp "  jtag_tap_xilinx7 #(.CHAIN(2)) u_t2(.tck(t2k),.tdi(t2i),.tdo(t2o),.capture(t2c),.shift(t2s),.update(t2u),.sel(t2l));"
    puts $fp "  jtag_reg_iface u_j(.arst(rst),.tck(t1k),.tdi(t1i),.tdo(t1o),.capture(t1c),.shift_en(t1s),.update(t1u),.sel(t1l),.reg_clk(jc),.reg_rst(jr),.reg_wr_en(jwe),.reg_rd_en(jre),.reg_addr(ja),.reg_wdata(jwd),.reg_rdata(jrd));"
    puts $fp "  fcapz_ela #(.SAMPLE_W(SW),.DEPTH(D),.TRIG_STAGES($stages),.STOR_QUAL($sq)) u_i(.sample_clk(clk),.sample_rst(rst),.probe_in(ctr),.jtag_clk(jc),.jtag_rst(jr),.jtag_wr_en(jwe),.jtag_rd_en(jre),.jtag_addr(ja),.jtag_wdata(jwd),.jtag_rdata(jrd),.burst_rd_addr(ba),.burst_rd_data(bd),.burst_start(bs),.burst_start_ptr(bsp));"
    puts $fp "  jtag_burst_read #(.SAMPLE_W(SW),.DEPTH(D)) u_b(.arst(rst),.tck(t2k),.tdi(t2i),.tdo(t2o),.capture(t2c),.shift_en(t2s),.update(t2u),.sel(t2l),.mem_addr(ba),.mem_data(bd),.burst_start(bs),.burst_ptr_in(bsp));"
    puts $fp "endmodule"
    close $fp

    add_files [list $root/rtl/dpram.v $root/rtl/reset_sync.v $root/rtl/fcapz_ela.v $root/rtl/jtag_reg_iface.v $root/rtl/jtag_burst_read.v $root/rtl/jtag_tap/jtag_tap_xilinx7.v $root/vivado/top_${label}.v]
    add_files -fileset constrs_1 $root/examples/arty_a7/arty_a7.xdc
    set_property top arty_a7_top [current_fileset]

    launch_runs synth_1 -jobs 4
    wait_on_run synth_1

    set rpt_file [glob -nocomplain $root/vivado/$pname/${pname}.runs/synth_1/*utilization_synth.rpt]
    if {$rpt_file ne ""} {
        set fp2 [open $rpt_file r]
        set rpt [read $fp2]
        close $fp2
        set luts "?"; set ffs "?"; set bram "?"
        foreach line [split $rpt "\n"] {
            if {[regexp {LUT as Logic\s*\|\s*(\d+)} $line -> val]} { set luts $val }
            if {[regexp {Register as Flip Flop\s*\|\s*(\d+)} $line -> val]} { set ffs $val }
            if {[regexp {Block RAM Tile\s*\|\s*([\d.]+)} $line -> val]} { set bram $val }
        }
        puts [format "%-28s %6s %6s %5s" "${sw}b x ${depth} S=${stages} Q=${sq}" $luts $ffs $bram]
    } else {
        puts [format "%-28s %6s" "${sw}b x ${depth} S=${stages} Q=${sq}" "FAILED"]
    }

    close_project
}

puts "-----------------------------------------------------------"
puts "S=TRIG_STAGES, Q=STOR_QUAL"
puts "=== Done ==="
