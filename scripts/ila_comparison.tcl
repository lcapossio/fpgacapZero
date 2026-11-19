# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Compare fcapz ELA resources against the AMD/Xilinx ILA at matching sample
# widths, depths and trigger features, on one Vivado part.
#
# Every case is synthesized and then run through opt_design, because Vivado
# only inserts the ILA's dbg_hub (its BSCANE2 and JTAG plumbing) at
# opt_design.  The fcapz rows count fcapz_ela_xilinx7, which holds the
# ELA together with its own BSCANE2, register interface and readout, so
# they compare with "ILA + dbg_hub".
#
# Usage:
#   vivado -mode batch -source scripts/ila_comparison.tcl
#
# Optional environment overrides:
#   FPGACAP_ROOT        repo root
#   FPGACAP_PART        Vivado part, default xc7a100tcsg324-1
#   FPGACAP_ILA_OUT     output directory, default vivado/ila_compare
#   FPGACAP_ILA_SIZES   "WIDTHxDEPTH ..." list, default "8x1024 64x4096"
#   FPGACAP_ILA_CASES   case names to run, default all (see the cases table)

proc env_or {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} {
        return $::env($name)
    }
    return $default
}

if {[info exists ::env(FPGACAP_ROOT)] && $::env(FPGACAP_ROOT) ne ""} {
    set root [file normalize $::env(FPGACAP_ROOT)]
} else {
    set root [file normalize [file join [file dirname [info script]] ..]]
}
set part [env_or FPGACAP_PART xc7a100tcsg324-1]
set out_dir [file normalize [env_or FPGACAP_ILA_OUT [file join $root vivado ila_compare]]]
set sizes [env_or FPGACAP_ILA_SIZES "8x1024 64x4096"]
file mkdir $out_dir

# name kind params description
#   kind fcapz: params are fcapz_ela_xilinx7 parameter overrides.
#   kind ila:   params are ILA IP CONFIG values.
set cases {
    {fcapz_min fcapz
        {TRIG_STAGES 1 STOR_QUAL 0 DUAL_COMPARE 0 REL_COMPARE 0 INPUT_PIPE 0
         EXT_TRIG_EN 0 DECIM_EN 0 TIMESTAMP_W 0 NUM_SEGMENTS 1
         SINGLE_CHAIN_BURST 0 BURST_EN 0 USER1_DATA_EN 1}
        "fcapz minimum: one EQ/NEQ/edge comparator, slow USER1 readout"}
    {fcapz_basic fcapz
        {TRIG_STAGES 1 STOR_QUAL 0 DUAL_COMPARE 0 REL_COMPARE 1 INPUT_PIPE 0
         EXT_TRIG_EN 0 DECIM_EN 0 TIMESTAMP_W 0 NUM_SEGMENTS 4
         SINGLE_CHAIN_BURST 1}
        "fcapz like ILA basic: one comparator with relational modes, 4 segments, fast readout"}
    {fcapz_dual fcapz
        {TRIG_STAGES 1 STOR_QUAL 1 DUAL_COMPARE 1 REL_COMPARE 1 INPUT_PIPE 1
         EXT_TRIG_EN 1 DECIM_EN 0 TIMESTAMP_W 0 NUM_SEGMENTS 4
         SINGLE_CHAIN_BURST 1}
        "fcapz like ILA dual: 2 comparators, storage qualification, trigger in/out, no sequencer"}
    {fcapz_adv fcapz
        {TRIG_STAGES 4 STOR_QUAL 1 DUAL_COMPARE 1 REL_COMPARE 1 INPUT_PIPE 1
         EXT_TRIG_EN 1 DECIM_EN 0 TIMESTAMP_W 0 NUM_SEGMENTS 4
         SINGLE_CHAIN_BURST 1}
        "fcapz like ILA advanced: 4-stage sequencer with 2 comparators per stage (8), storage qualification, trigger in/out"}
    {fcapz_all fcapz
        {TRIG_STAGES 4 STOR_QUAL 1 DUAL_COMPARE 1 REL_COMPARE 1 INPUT_PIPE 1
         EXT_TRIG_EN 1 DECIM_EN 1 TIMESTAMP_W 32 NUM_SEGMENTS 4
         SINGLE_CHAIN_BURST 1}
        "fcapz advanced plus decimation and 32-bit timestamps (no ILA equivalent)"}
    {ila_basic ila
        {ALL_PROBE_SAME_MU_CNT 1 C_ADV_TRIGGER false C_EN_STRG_QUAL 0
         C_TRIGIN_EN false C_TRIGOUT_EN false C_INPUT_PIPE_STAGES 0}
        "ILA basic: one comparator per probe, basic trigger"}
    {ila_dual ila
        {ALL_PROBE_SAME_MU_CNT 2 C_ADV_TRIGGER false C_EN_STRG_QUAL 1
         C_TRIGIN_EN true C_TRIGOUT_EN true C_INPUT_PIPE_STAGES 1}
        "ILA dual: 2 comparators, capture control, trigger in/out, basic trigger"}
    {ila_adv ila
        {ALL_PROBE_SAME_MU_CNT 2 C_ADV_TRIGGER true C_EN_STRG_QUAL 1
         C_TRIGIN_EN true C_TRIGOUT_EN true C_INPUT_PIPE_STAGES 1}
        "ILA advanced: 2 comparators, advanced trigger state machine, capture control, trigger in/out"}
    {ila_adv8 ila
        {ALL_PROBE_SAME_MU_CNT 8 C_ADV_TRIGGER true C_EN_STRG_QUAL 1
         C_TRIGIN_EN true C_TRIGOUT_EN true C_INPUT_PIPE_STAGES 1}
        "ILA advanced with 8 comparators (as many as fcapz_adv)"}
}
set only [env_or FPGACAP_ILA_CASES ""]

set fcapz_sources [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/reset_sync.v \
    $root/rtl/dff_sync.v \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela.v \
    $root/rtl/fcapz_eio.v \
    $root/rtl/jtag_reg_iface.v \
    $root/rtl/jtag_pipe_iface.v \
    $root/rtl/jtag_burst_read.v \
    $root/rtl/jtag_tap/jtag_tap_xilinx7.v \
    $root/rtl/fcapz_ela_xilinx7.v \
]

proc emit_fcapz_top {path width depth params} {
    set ext 0
    foreach {k v} $params { if {$k eq "EXT_TRIG_EN"} { set ext $v } }
    set fp [open $path w]
    puts $fp "`timescale 1ns/1ps"
    puts $fp "module cmp_top("
    puts $fp "  input wire clk, rst, trig_in,"
    puts $fp "  input wire \[$width-1:0\] probe,"
    puts $fp "  output wire trig_out, armed"
    puts $fp ");"
    set plist [list "    .SAMPLE_W($width)" "    .DEPTH($depth)"]
    foreach {k v} $params { lappend plist "    .$k\($v\)" }
    puts $fp "  fcapz_ela_xilinx7 #("
    puts $fp [join $plist ",\n"]
    puts $fp "  ) u_dut ("
    puts $fp "    .sample_clk(clk), .sample_rst(rst), .probe_in(probe),"
    puts $fp "    .trigger_in([expr {$ext ? "trig_in" : "1'b0"}]), .trigger_out(trig_out), .armed_out(armed),"
    puts $fp "    .eio_probe_in(1'b0), .eio_probe_out()"
    puts $fp "  );"
    puts $fp "endmodule"
    close $fp
}

proc emit_ila_top {path width params} {
    array set c $params
    set tin [expr {$c(C_TRIGIN_EN) eq "true"}]
    set tout [expr {$c(C_TRIGOUT_EN) eq "true"}]
    set fp [open $path w]
    puts $fp "`timescale 1ns/1ps"
    puts $fp "module cmp_top("
    puts $fp "  input wire clk, rst, trig_in,"
    puts $fp "  input wire \[$width-1:0\] probe,"
    puts $fp "  output wire trig_out, armed"
    puts $fp ");"
    puts $fp "  wire unused_rst = rst;"
    puts $fp "  assign armed = 1'b0;"
    set ports [list ".clk(clk)" ".probe0(probe)"]
    if {$tin} {
        lappend ports ".trig_in(trig_in)" ".trig_in_ack()"
    }
    if {$tout} {
        lappend ports ".trig_out(trig_out)" ".trig_out_ack(1'b1)"
    } else {
        puts $fp "  assign trig_out = 1'b0;"
    }
    puts $fp "  ila_cmp u_ila ([join $ports {, }]);"
    puts $fp "endmodule"
    close $fp
}

# The hierarchy rows of report_utilization, as {instance {column value ...}}.
proc hier_rows {} {
    set text [report_utilization -hierarchical -hierarchical_depth 1 -return_string]
    set header {}
    set rows {}
    foreach line [split $text "\n"] {
        if {![string match "|*" $line]} { continue }
        set cells {}
        foreach f [lrange [split $line "|"] 1 end-1] { lappend cells [string trim $f] }
        if {[lindex $cells 0] eq "Instance"} {
            set header $cells
            continue
        }
        if {$header eq {}} { continue }
        set row {}
        foreach h $header v $cells { lappend row $h $v }
        lappend rows [lindex $cells 0] $row
    }
    return $rows
}

proc row_value {row column} {
    array set r $row
    if {[info exists r($column)]} { return $r($column) }
    return 0
}

# LUTs, logic LUTs, LUTRAM+SRL, FFs and BRAM tiles of the named instances.
proc sum_instances {rows names} {
    set lut 0; set logic 0; set mem 0; set ff 0; set bram 0.0
    set found {}
    foreach {inst row} $rows {
        if {[lsearch -exact $names $inst] < 0} { continue }
        lappend found $inst
        incr lut [row_value $row "Total LUTs"]
        incr logic [row_value $row "Logic LUTs"]
        incr mem [expr {[row_value $row "LUTRAMs"] + [row_value $row "SRLs"]}]
        incr ff [row_value $row "FFs"]
        set bram [expr {$bram + [row_value $row "RAMB36"] + 0.5 * [row_value $row "RAMB18"]}]
    }
    return [list $lut $logic $mem $ff $bram $found]
}

proc run_case {name kind params width depth} {
    global root part out_dir fcapz_sources
    set tag ${name}_${width}x${depth}
    set dir [file join $out_dir $tag]
    file delete -force $dir
    file mkdir $dir
    set top [file join $dir cmp_top.v]
    create_project -in_memory -part $part
    if {$kind eq "fcapz"} {
        emit_fcapz_top $top $width $depth $params
        foreach src $fcapz_sources {
            if {[file extension $src] eq ".vh"} {
                read_verilog $src
                set_property file_type "Verilog Header" [get_files $src]
                set_property is_global_include true [get_files $src]
            } else {
                read_verilog $src
            }
        }
        set count_names {u_dut}
    } else {
        emit_ila_top $top $width $params
        create_ip -name ila -vendor xilinx.com -library ip -module_name ila_cmp -dir $dir
        set cfg [list CONFIG.C_NUM_OF_PROBES 1 CONFIG.C_PROBE0_WIDTH $width \
            CONFIG.C_DATA_DEPTH $depth]
        foreach {k v} $params { lappend cfg CONFIG.$k $v }
        set_property -dict $cfg [get_ips ila_cmp]
        # The per-probe comparator count follows ALL_PROBE_SAME_MU_CNT;
        # check that the IP took the count the case asks for.
        array set want $params
        set got [get_property CONFIG.C_PROBE0_MU_CNT [get_ips ila_cmp]]
        if {$got != $want(ALL_PROBE_SAME_MU_CNT)} {
            error "$name: ILA has $got comparators, expected $want(ALL_PROBE_SAME_MU_CNT)"
        }
        puts "ILA_CONFIG $name ${width}x${depth}: [join $cfg { }]"
        # Synthesize the IP with the design (not out of context), so
        # synth_design and opt_design see it like the fcapz core.
        set xci [get_files [get_property IP_FILE [get_ips ila_cmp]]]
        set_property GENERATE_SYNTH_CHECKPOINT false $xci
        generate_target {synthesis} [get_ips ila_cmp]
        set count_names {u_ila dbg_hub}
    }
    read_verilog $top
    # dbg_hub's own constraints look up the clock it runs on.
    set xdc [file join $dir cmp_top.xdc]
    set fp [open $xdc w]
    puts $fp "create_clock -period 10.000 -name clk \[get_ports clk\]"
    close $fp
    read_xdc $xdc
    synth_design -top cmp_top -part $part -flatten_hierarchy rebuilt
    opt_design
    report_utilization -hierarchical -file [file join $dir util_hier.rpt]
    set rows [hier_rows]
    set result {}
    foreach n $count_names {
        lappend result $n [sum_instances $rows [list $n]]
    }
    close_project
    return $result
}

puts ""
puts "=== fcapz ELA vs AMD/Xilinx ILA ($part, post-opt_design) ==="
set summary {}
foreach size $sizes {
    lassign [split $size x] width depth
    foreach case $cases {
        lassign $case name kind params desc
        if {$only ne "" && [lsearch -exact $only $name] < 0} { continue }
        set res [run_case $name $kind $params $width $depth]
        lappend summary [list $name $kind $width $depth $desc $res]
    }
}

set csv [file join $out_dir ila_comparison.csv]
set fp [open $csv w]
puts $fp "case,width,depth,part,luts,logic_luts,lutram_srl,ffs,bram_tiles,description"
puts ""
puts [format "%-14s %8s | %6s %6s %6s %6s %5s | %s" case size LUTs logic mem FFs BRAM description]
puts [string repeat - 100]
foreach s $summary {
    lassign $s name kind width depth desc res
    array unset part_of
    array set part_of $res
    if {$kind eq "fcapz"} {
        set lines [list [list $name $part_of(u_dut)]]
    } else {
        set ip $part_of(u_ila)
        set hub $part_of(dbg_hub)
        set tot {}
        foreach a [lrange $ip 0 4] b [lrange $hub 0 4] { lappend tot [expr {$a + $b}] }
        set lines [list [list "${name}_ip" $ip] [list "${name}_hub" $hub] \
            [list "${name}+hub" $tot]]
        if {[llength [lindex $hub 5]] == 0} {
            puts "WARNING: no dbg_hub row for $name ${width}x${depth}"
        }
    }
    foreach l $lines {
        lassign $l label vals
        lassign $vals lut logic mem ff bram
        puts [format "%-14s %8s | %6d %6d %6d %6d %5.1f | %s" \
            $label ${width}x${depth} $lut $logic $mem $ff $bram $desc]
        puts $fp "$label,$width,$depth,$part,$lut,$logic,$mem,$ff,$bram,\"$desc\""
    }
}
close $fp
puts [string repeat - 100]
puts "CSV: $csv"
