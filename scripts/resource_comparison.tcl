# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Compare Verilog and VHDL core synthesis resources on the same Vivado part.
# Usage:
#   vivado -mode batch -source scripts/resource_comparison.tcl
#
# Optional environment overrides:
#   FPGACAP_ROOT       repo root
#   FPGACAP_PART       Vivado part, default xc7a100tcsg324-1
#   FPGACAP_RES_OUT    output directory, default vivado/resource_compare
#   FPGACAP_LUT_TOL    allowed absolute LUT delta percent, default 10
#   FPGACAP_FF_TOL     allowed absolute FF delta percent, default 10
#   FPGACAP_ABS_TOL    allowed absolute LUT/FF delta, default 64
#   FPGACAP_BRAM_TOL   allowed absolute BRAM primitive delta, default 1

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
set out_dir [file normalize [env_or FPGACAP_RES_OUT [file join $root vivado resource_compare]]]
set lut_tol_pct [expr {double([env_or FPGACAP_LUT_TOL 10])}]
set ff_tol_pct [expr {double([env_or FPGACAP_FF_TOL 10])}]
set abs_tol [expr {int([env_or FPGACAP_ABS_TOL 64])}]
set bram_tol [expr {int([env_or FPGACAP_BRAM_TOL 1])}]

file mkdir $out_dir

# Vivado 2025.2 can leave the per-user Tcl store support package outside the
# startup auto_path after an interrupted update. Add the nested support paths
# when they already exist; this is a no-op on clean installations.
if {[info exists ::env(APPDATA)]} {
    regsub -all {\\} $::env(APPDATA) {/} appdata_dir
    set xilinx_tcl_store [file join $appdata_dir Xilinx Vivado [version -short] XilinxTclStore]
    foreach support_dir [list \
        [file join $xilinx_tcl_store support] \
        [file join $xilinx_tcl_store support appinit] \
        [file join $xilinx_tcl_store support args] \
        [file join $xilinx_tcl_store tclapp] \
        [file join $xilinx_tcl_store tclapp xilinx] \
        [file join $xilinx_tcl_store tclapp xilinx xsim] \
    ] {
        if {[file isdirectory $support_dir] && [lsearch -exact $::auto_path $support_dir] < 0} {
            lappend ::auto_path $support_dir
        }
    }
}
set_param project.enableUnifiedSimulation 0

proc emit_ela_verilog_top {path sample_w depth} {
    set fp [open $path w]
    puts $fp "`timescale 1ns/1ps"
    puts $fp "module rc_ela_verilog_top("
    puts $fp "  input wire sample_clk, sample_rst, trigger_in,"
    puts $fp "  input wire jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en,"
    puts $fp "  input wire \[15:0\] jtag_addr,"
    puts $fp "  input wire \[31:0\] jtag_wdata,"
    puts $fp "  input wire \[$sample_w-1:0\] probe_in,"
    puts $fp "  input wire \[\$clog2($depth)-1:0\] burst_rd_addr,"
    puts $fp "  output wire trigger_out, armed_out,"
    puts $fp "  output wire \[31:0\] jtag_rdata,"
    puts $fp "  output wire \[$sample_w-1:0\] burst_rd_data,"
    puts $fp "  output wire burst_start, burst_timestamp,"
    puts $fp "  output wire \[\$clog2($depth)-1:0\] burst_start_ptr"
    puts $fp ");"
    puts $fp "  wire unused_ts;"
    puts $fp "  fcapz_ela #("
    puts $fp "    .SAMPLE_W($sample_w), .DEPTH($depth), .TRIG_STAGES(1), .STOR_QUAL(0),"
    puts $fp "    .INPUT_PIPE(1), .DECIM_EN(1), .EXT_TRIG_EN(1), .TIMESTAMP_W(0),"
    puts $fp "    .NUM_SEGMENTS(1), .REL_COMPARE(0), .DUAL_COMPARE(1), .USER1_DATA_EN(1)"
    puts $fp "  ) u_dut ("
    puts $fp "    .sample_clk(sample_clk), .sample_rst(sample_rst), .probe_in(probe_in),"
    puts $fp "    .trigger_in(trigger_in), .trigger_out(trigger_out), .armed_out(armed_out),"
    puts $fp "    .jtag_clk(jtag_clk), .jtag_rst(jtag_rst), .jtag_wr_en(jtag_wr_en),"
    puts $fp "    .jtag_rd_en(jtag_rd_en), .jtag_addr(jtag_addr), .jtag_wdata(jtag_wdata),"
    puts $fp "    .jtag_rdata(jtag_rdata), .burst_rd_addr(burst_rd_addr),"
    puts $fp "    .burst_rd_data(burst_rd_data), .burst_rd_ts_data(unused_ts),"
    puts $fp "    .burst_start(burst_start), .burst_timestamp(burst_timestamp),"
    puts $fp "    .burst_start_ptr(burst_start_ptr)"
    puts $fp "  );"
    puts $fp "endmodule"
    close $fp
}

proc emit_eio_verilog_top {path in_w out_w} {
    set fp [open $path w]
    puts $fp "`timescale 1ns/1ps"
    puts $fp "module rc_eio_verilog_top("
    puts $fp "  input wire jtag_clk, jtag_rst, jtag_wr_en,"
    puts $fp "  input wire \[15:0\] jtag_addr,"
    puts $fp "  input wire \[31:0\] jtag_wdata,"
    puts $fp "  input wire \[$in_w-1:0\] probe_in,"
    puts $fp "  output wire \[$out_w-1:0\] probe_out,"
    puts $fp "  output wire \[31:0\] jtag_rdata"
    puts $fp ");"
    puts $fp "  fcapz_eio #(.IN_W($in_w), .OUT_W($out_w)) u_dut ("
    puts $fp "    .probe_in(probe_in), .probe_out(probe_out), .jtag_clk(jtag_clk),"
    puts $fp "    .jtag_rst(jtag_rst), .jtag_wr_en(jtag_wr_en), .jtag_addr(jtag_addr),"
    puts $fp "    .jtag_wdata(jtag_wdata), .jtag_rdata(jtag_rdata)"
    puts $fp "  );"
    puts $fp "endmodule"
    close $fp
}

proc emit_ela_vhdl_top {path sample_w depth} {
    set ptr_w [expr {int(ceil(log($depth) / log(2)))}]
    set fp [open $path w]
    puts $fp "library ieee;"
    puts $fp "use ieee.std_logic_1164.all;"
    puts $fp "entity rc_ela_vhdl_top is"
    puts $fp "  port ("
    puts $fp "    sample_clk : in std_logic; sample_rst : in std_logic; trigger_in : in std_logic;"
    puts $fp "    jtag_clk : in std_logic; jtag_rst : in std_logic; jtag_wr_en : in std_logic; jtag_rd_en : in std_logic;"
    puts $fp "    jtag_addr : in std_logic_vector(15 downto 0);"
    puts $fp "    jtag_wdata : in std_logic_vector(31 downto 0);"
    puts $fp "    probe_in : in std_logic_vector($sample_w - 1 downto 0);"
    puts $fp "    burst_rd_addr : in std_logic_vector($ptr_w - 1 downto 0);"
    puts $fp "    trigger_out : out std_logic; armed_out : out std_logic;"
    puts $fp "    jtag_rdata : out std_logic_vector(31 downto 0);"
    puts $fp "    burst_rd_data : out std_logic_vector($sample_w - 1 downto 0);"
    puts $fp "    burst_start : out std_logic; burst_timestamp : out std_logic;"
    puts $fp "    burst_start_ptr : out std_logic_vector($ptr_w - 1 downto 0)"
    puts $fp "  );"
    puts $fp "end entity;"
    puts $fp "architecture rtl of rc_ela_vhdl_top is"
    puts $fp "  signal unused_ts : std_logic_vector(0 downto 0);"
    puts $fp "begin"
    puts $fp "  u_dut : entity work.fcapz_ela"
    puts $fp "    generic map ("
    puts $fp "      SAMPLE_W => $sample_w, DEPTH => $depth, TRIG_STAGES => 1, STOR_QUAL => 0,"
    puts $fp "      INPUT_PIPE => 1, DECIM_EN => 1, EXT_TRIG_EN => 1, TIMESTAMP_W => 0,"
    puts $fp "      NUM_SEGMENTS => 1, REL_COMPARE => 0, DUAL_COMPARE => 1, USER1_DATA_EN => 1"
    puts $fp "    )"
    puts $fp "    port map ("
    puts $fp "      sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in,"
    puts $fp "      trigger_in => trigger_in, trigger_out => trigger_out, armed_out => armed_out,"
    puts $fp "      jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en,"
    puts $fp "      jtag_rd_en => jtag_rd_en, jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,"
    puts $fp "      jtag_rdata => jtag_rdata, burst_rd_addr => burst_rd_addr,"
    puts $fp "      burst_rd_data => burst_rd_data, burst_rd_ts_data => unused_ts,"
    puts $fp "      burst_start => burst_start, burst_timestamp => burst_timestamp,"
    puts $fp "      burst_start_ptr => burst_start_ptr"
    puts $fp "    );"
    puts $fp "end architecture;"
    close $fp
}

proc emit_eio_vhdl_top {path in_w out_w} {
    set fp [open $path w]
    puts $fp "library ieee;"
    puts $fp "use ieee.std_logic_1164.all;"
    puts $fp "entity rc_eio_vhdl_top is"
    puts $fp "  port ("
    puts $fp "    jtag_clk : in std_logic; jtag_rst : in std_logic; jtag_wr_en : in std_logic;"
    puts $fp "    jtag_addr : in std_logic_vector(15 downto 0);"
    puts $fp "    jtag_wdata : in std_logic_vector(31 downto 0);"
    puts $fp "    probe_in : in std_logic_vector($in_w - 1 downto 0);"
    puts $fp "    probe_out : out std_logic_vector($out_w - 1 downto 0);"
    puts $fp "    jtag_rdata : out std_logic_vector(31 downto 0)"
    puts $fp "  );"
    puts $fp "end entity;"
    puts $fp "architecture rtl of rc_eio_vhdl_top is"
    puts $fp "begin"
    puts $fp "  u_dut : entity work.fcapz_eio"
    puts $fp "    generic map (IN_W => $in_w, OUT_W => $out_w)"
    puts $fp "    port map ("
    puts $fp "      probe_in => probe_in, probe_out => probe_out, jtag_clk => jtag_clk,"
    puts $fp "      jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en, jtag_addr => jtag_addr,"
    puts $fp "      jtag_wdata => jtag_wdata, jtag_rdata => jtag_rdata"
    puts $fp "    );"
    puts $fp "end architecture;"
    close $fp
}

proc primitive_counts {} {
    set luts [llength [get_cells -hier -quiet -filter {REF_NAME =~ LUT*}]]
    set ffs [llength [get_cells -hier -quiet -filter {REF_NAME =~ FD*}]]
    set ramb18 [llength [get_cells -hier -quiet -filter {REF_NAME =~ RAMB18*}]]
    set ramb36 [llength [get_cells -hier -quiet -filter {REF_NAME =~ RAMB36*}]]
    return [list $luts $ffs $ramb18 $ramb36]
}

proc run_case {name lang top sources} {
    global root part out_dir
    set proj_dir [file join $out_dir $name]
    create_project $name $proj_dir -part $part -force
    add_files $sources
    foreach src $sources {
        if {[string equal -nocase [file extension $src] ".vhd"]} {
            set vhdl_file [get_files -quiet $src]
            if {[llength $vhdl_file] > 0} {
                set_property file_type "VHDL 2008" $vhdl_file
            }
        }
    }
    set header_file [get_files -quiet $root/rtl/fcapz_version.vh]
    if {[llength $header_file] > 0} {
        set_property file_type "Verilog Header" $header_file
        set_property is_global_include true $header_file
    }
    update_compile_order -fileset sources_1
    synth_design -top $top -part $part -flatten_hierarchy rebuilt
    set counts [primitive_counts]
    report_utilization -file [file join $out_dir ${name}_util.rpt]
    close_project
    return $counts
}

proc pct_delta {a b} {
    if {$a == 0 && $b == 0} {
        return 0.0
    }
    set base [expr {max(1.0, double($a))}]
    return [expr {abs(double($b - $a)) * 100.0 / $base}]
}

proc check_pair {label v_counts h_counts} {
    global lut_tol_pct ff_tol_pct abs_tol bram_tol failures
    lassign $v_counts vlut vff vr18 vr36
    lassign $h_counts hlut hff hr18 hr36
    set dlut [expr {$hlut - $vlut}]
    set dff [expr {$hff - $vff}]
    set dr18 [expr {$hr18 - $vr18}]
    set dr36 [expr {$hr36 - $vr36}]
    set lut_pct [pct_delta $vlut $hlut]
    set ff_pct [pct_delta $vff $hff]
    puts [format "%-12s | %6d %6d %5d %5d | %6d %6d %5d %5d | %+6d %+6d %+5d %+5d | %5.1f%% %5.1f%%" \
        $label $vlut $vff $vr18 $vr36 $hlut $hff $hr18 $hr36 $dlut $dff $dr18 $dr36 $lut_pct $ff_pct]
    set fail 0
    if {abs($dlut) > $abs_tol && $lut_pct > $lut_tol_pct} { set fail 1 }
    if {abs($dff) > $abs_tol && $ff_pct > $ff_tol_pct} { set fail 1 }
    if {abs($dr18) > $bram_tol || abs($dr36) > $bram_tol} { set fail 1 }
    if {$fail} {
        puts "  FAIL: resource delta exceeds tolerance"
        incr failures
    }
}

set top_dir [file join $out_dir tops]
file mkdir $top_dir

set ela_v_top [file join $top_dir rc_ela_verilog_top.v]
set eio_v_top [file join $top_dir rc_eio_verilog_top.v]
set ela_h_top [file join $top_dir rc_ela_vhdl_top.vhd]
set eio_h_top [file join $top_dir rc_eio_vhdl_top.vhd]
emit_ela_verilog_top $ela_v_top 8 1024
emit_eio_verilog_top $eio_v_top 32 32
emit_ela_vhdl_top $ela_h_top 8 1024
emit_eio_vhdl_top $eio_h_top 32 32

set ela_verilog_sources [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/dpram.v \
    $root/rtl/trig_compare.v \
    $root/rtl/fcapz_ela.v \
    $ela_v_top \
]
set eio_verilog_sources [list \
    $root/rtl/fcapz_version.vh \
    $root/rtl/fcapz_eio.v \
    $eio_v_top \
]
set ela_vhdl_sources [list \
    $root/rtl/vhdl/pkg/fcapz_pkg.vhd \
    $root/rtl/vhdl/pkg/fcapz_util_pkg.vhd \
    $root/rtl/vhdl/core/fcapz_dpram.vhd \
    $root/rtl/vhdl/core/fcapz_ela.vhd \
    $ela_h_top \
]
set eio_vhdl_sources [list \
    $root/rtl/vhdl/pkg/fcapz_pkg.vhd \
    $root/rtl/vhdl/core/fcapz_eio.vhd \
    $eio_h_top \
]

puts ""
puts "=== Verilog vs VHDL core resource comparison ($part) ==="
puts [format "Tolerance: LUT/FF delta <= %d absolute or <= %.1f%%/%.1f%%, BRAM primitive delta <= %d" \
    $abs_tol $lut_tol_pct $ff_tol_pct $bram_tol]
puts "             |      Verilog resources       |        VHDL resources        |             delta        | delta pct"
puts "Core         |   LUTs    FFs   R18   R36 |   LUTs    FFs   R18   R36 |   LUTs    FFs   R18   R36 |  LUTs   FFs"
puts "-------------+-----------------------------+-----------------------------+--------------------------+------------"

set failures 0
set ela_v [run_case rc_ela_verilog verilog rc_ela_verilog_top $ela_verilog_sources]
set ela_h [run_case rc_ela_vhdl vhdl rc_ela_vhdl_top $ela_vhdl_sources]
check_pair "ELA" $ela_v $ela_h

set eio_v [run_case rc_eio_verilog verilog rc_eio_verilog_top $eio_verilog_sources]
set eio_h [run_case rc_eio_vhdl vhdl rc_eio_vhdl_top $eio_vhdl_sources]
check_pair "EIO" $eio_v $eio_h

puts "-------------+-----------------------------+-----------------------------+--------------------------+------------"
puts [format "Reports written under %s" $out_dir]

if {$failures > 0} {
    error "$failures resource comparison(s) exceeded tolerance"
}
