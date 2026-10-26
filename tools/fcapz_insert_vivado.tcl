# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Post-synthesis insertion of an fcapz ELA into a Vivado netlist (prototype).
#
# The design is synthesized without any fcapz RTL; the nets to capture carry
# MARK_DEBUG (as for Vivado's own ILA), which also keeps synthesis from
# optimizing them away.  fcapz::insert then:
#
#   1. collects the MARK_DEBUG nets and the clock that drives them,
#   2. synthesizes fcapz_ela_xilinx7 out of context, sized to those nets,
#   3. adds it to the netlist as a black box filled from that checkpoint,
#   4. wires the nets to probe_in and the clock to sample_clk,
#   5. constrains the BSCANE2 TCK, and
#   6. writes the instrumented checkpoint and a .prob sidecar for the host.
#
# Place, route and write_bitstream continue from the written checkpoint.
#
#   source tools/fcapz_insert_vivado.tcl
#   fcapz::insert -in post_synth.dcp -out instrumented.dcp -rtl <repo>/rtl \
#       -prob design.prob
#
# Optional: -depth (1024), -chain (USER chain, 1), -clock <full net name>,
# -clock_hz (written to the .prob), -tck_mhz (TCK constraint, 10), -part,
# -cell (instance name, u_fcapz_ela).

namespace eval fcapz {}

# The RTL fcapz_ela_xilinx7 elaborates (relative to rtl/).
set fcapz::ela_sources {
    reset_sync.v dpram.v trig_compare.v fcapz_ela.v fcapz_ela_xilinx7.v
    jtag_reg_iface.v jtag_pipe_iface.v jtag_burst_read.v
    jtag_tap/jtag_tap_xilinx7.v fcapz_eio.v fcapz_eio_xilinx7.v
    fcapz_regbus_mux.v dff_sync.v dff_reg_sync.v fcapz_async_fifo.v
}

proc fcapz::_opts {defaults argv} {
    array set o $defaults
    if {[llength $argv] % 2} { error "fcapz::insert: options come in -name value pairs" }
    foreach {k v} $argv {
        set k [string trimleft $k -]
        if {![info exists o($k)]} { error "fcapz::insert: unknown option -$k" }
        set o($k) $v
    }
    return [array get o]
}

# {name direction lo hi} per port of the open design; lo/hi empty for a bit.
proc fcapz::_port_spec {} {
    array set bus {}
    set spec {}
    foreach p [get_ports] {
        set dir [get_property DIRECTION $p]
        set bname [get_property BUS_NAME $p]
        if {$bname eq ""} {
            lappend spec [list [get_property NAME $p] $dir {} {}]
            continue
        }
        if {![regexp {\[(\d+)\]$} [get_property NAME $p] -> idx]} { continue }
        if {[info exists bus($bname)]} {
            lassign $bus($bname) d lo hi
            set bus($bname) [list $d [expr {min($lo, $idx)}] [expr {max($hi, $idx)}]]
        } else {
            set bus($bname) [list $dir $idx $idx]
        }
    }
    foreach b [array names bus] {
        lassign $bus($b) d lo hi
        lappend spec [list $b $d $lo $hi]
    }
    return $spec
}

# Group bit nets into probes, in sample order, low bits first.  "u_core/count[3]"
# belongs to probe "u_core/count" (the netlist's own name, so names stay unique);
# a scalar net is 1 bit.  A bus probe spans its lowest to highest marked index
# and must be marked without gaps, so every bit the .prob advertises is wired.
# Returns {order width low bits}, bits holding {base index net-name} per net.
# Takes and keeps net names: object handles go stale on read_checkpoint.
proc fcapz::_probe_groups {names} {
    array set lo {}
    array set hi {}
    array set count {}
    set order {}
    set bits {}
    foreach name $names {
        if {![regexp {^(.*)\[(\d+)\]$} $name -> base idx]} {
            set base $name
            set idx 0
        }
        if {![info exists lo($base)]} {
            set lo($base) $idx
            set hi($base) $idx
            set count($base) 0
            lappend order $base
        }
        lappend bits [list $base $idx $name]
        set lo($base) [expr {min($lo($base), $idx)}]
        set hi($base) [expr {max($hi($base), $idx)}]
        incr count($base)
    }
    array set width {}
    foreach b $order {
        set width($b) [expr {$hi($b) - $lo($b) + 1}]
        if {$count($b) != $width($b)} {
            error "fcapz::insert: only $count($b) bits of $b\[$hi($b):$lo($b)\] carry MARK_DEBUG; mark the whole range"
        }
        if {[regexp {[:,\x00-\x1f]} $b]} {
            error "fcapz::insert: probe name '$b' has a ':', ',' or control character, which the host's probe list cannot carry"
        }
    }
    return [list $order [array get width] [array get lo] $bits]
}

# The clock a net is sampled on: the clock of the flip-flop that drives it.
# Anything else (LUT, LUTRAM, BRAM, DSP, a port) returns {} and needs -clock,
# since a primitive's clock pin need not be the clock of that output.
proc fcapz::_clock_of {net} {
    set drv [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $drv] != 1} { return {} }
    set cell [get_cells -of_objects $drv]
    if {![regexp {^FD[CPRS]E$} [get_property REF_NAME $cell]]} { return {} }
    set cpin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C}]
    if {[llength $cpin] != 1} { return {} }
    return [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $cpin]
}

# USER chains already spoken for: every BSCANE2 in the netlist, plus the chain
# of the debug hub Vivado will insert at opt_design for its own debug cores.
proc fcapz::_used_chains {} {
    set used {}
    foreach b [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}] {
        lappend used [get_property JTAG_CHAIN $b]
    }
    if {[llength [get_debug_cores -quiet]] > 0} {
        set hub [get_debug_cores -quiet -filter {NAME == dbg_hub}]
        set chain 1
        if {[llength $hub] == 1} {
            set c [get_property -quiet C_USER_SCAN_CHAIN $hub]
            if {$c ne ""} { set chain $c }
        }
        lappend used $chain
    }
    return [lsort -unique -integer $used]
}

# MARK_DEBUG makes a net DONT_TOUCH, which connect_net refuses to edit:
# lift it for the edit and put it back.
proc fcapz::_connect {name pins} {
    set net [get_nets $name]
    set dt [string is true -strict [get_property DONT_TOUCH $net]]
    if {$dt} { set_property DONT_TOUCH false $net }
    connect_net -hierarchical -net $net -objects $pins
    if {$dt} { set_property DONT_TOUCH true [get_nets $name] }
}

# A JSON string literal.
proc fcapz::_json_str {s} {
    set out ""
    foreach ch [split $s ""] {
        scan $ch %c code
        if {$ch eq "\"" || $ch eq "\\"} {
            append out "\\$ch"
        } elseif {$code < 0x20} {
            append out [format "\\u%04x" $code]
        } else {
            append out $ch
        }
    }
    return "\"$out\""
}

proc fcapz::insert {args} {
    array set o [fcapz::_opts {
        in {} out {} rtl {} prob {} depth 1024 chain 1 clock {} cell u_fcapz_ela
        part {} clock_hz {} tck_mhz 10
    } $args]
    foreach req {in out rtl} {
        if {$o($req) eq ""} { error "fcapz::insert: -$req is required" }
    }

    # -- 1. what to capture ------------------------------------------------
    open_checkpoint $o(in)
    set part [expr {$o(part) ne "" ? $o(part) : [get_property PART [current_design]]}]
    set nets [get_nets -hierarchical -filter {MARK_DEBUG == TRUE}]
    if {[llength $nets] == 0} {
        error "fcapz::insert: no MARK_DEBUG nets in $o(in)"
    }
    set net_names {}
    foreach n $nets { lappend net_names [get_property NAME $n] }
    lassign [fcapz::_probe_groups [lsort -dictionary $net_names]] \
        order width_list low_list bits
    array set width $width_list
    array set low $low_list
    set lsb 0
    array set base_lsb {}
    foreach b $order {
        set base_lsb($b) $lsb
        incr lsb $width($b)
    }
    set sample_w $lsb

    if {$o(clock) eq ""} {
        set clks {}
        foreach n $nets {
            set c [fcapz::_clock_of $n]
            if {$c eq ""} {
                error "fcapz::insert: $n is not driven by a flip-flop, so its clock is not known; pass -clock"
            }
            if {[lsearch -exact $clks $c] < 0} { lappend clks $c }
        }
        if {[llength $clks] != 1} {
            error "fcapz::insert: the nets come from several clocks ($clks); one ELA samples one clock, pass -clock"
        }
        set clk_net [lindex $clks 0]
    } else {
        set clk_net [get_nets -quiet $o(clock)]
        if {[llength $clk_net] != 1} {
            error "fcapz::insert: no net named $o(clock) (give its full hierarchical name)"
        }
    }
    set used_chains [fcapz::_used_chains]
    if {[lsearch -exact $used_chains $o(chain)] >= 0} {
        error "fcapz::insert: USER$o(chain) is taken (by a BSCANE2 or Vivado's debug hub; in use: $used_chains); pass -chain"
    }
    set clk_name [get_property NAME $clk_net]
    close_design

    # -- 2. the ELA, sized to the nets ------------------------------------
    # A project of its own, so the caller's sources and XDC stay out of it.
    set ela_dcp [file rootname $o(out)]_ela.dcp
    close_project -quiet
    create_project -in_memory -part $part
    set srcs {}
    foreach f $fcapz::ela_sources { lappend srcs [file join $o(rtl) $f] }
    read_verilog $srcs
    synth_design -top fcapz_ela_xilinx7 -part $part -mode out_of_context \
        -include_dirs [list $o(rtl)] \
        -generic SAMPLE_W=$sample_w -generic DEPTH=$o(depth) \
        -generic CTRL_CHAIN=$o(chain) -generic BURST_EN=0
    set ports [fcapz::_port_spec]
    write_checkpoint -force $ela_dcp
    close_project

    # -- 3. into the netlist ----------------------------------------------
    open_checkpoint $o(in)
    set cell $o(cell)
    create_cell -reference fcapz_ela_xilinx7 -black_box $cell
    foreach p $ports {
        lassign $p name dir lo hi
        if {$lo eq ""} {
            create_pin -direction $dir $cell/$name
        } else {
            create_pin -direction $dir -from $hi -to $lo $cell/$name
        }
    }
    read_checkpoint -cell $cell $ela_dcp

    # -- 4. wiring ----------------------------------------------------------
    foreach entry $bits {
        lassign $entry base idx name
        set bit [expr {$base_lsb($base) + $idx - $low($base)}]
        fcapz::_connect $name [get_pins $cell/probe_in[$bit]]
    }
    fcapz::_connect $clk_name [get_pins $cell/sample_clk]
    create_cell -reference GND ${cell}_gnd
    create_net ${cell}_gnd_net
    set tie [list [get_pins ${cell}_gnd/G] [get_pins $cell/sample_rst] [get_pins $cell/trigger_in]]
    foreach p [get_pins -quiet $cell/eio_probe_in*] { lappend tie $p }
    connect_net -net ${cell}_gnd_net -objects $tie

    # -- 5. constraints -----------------------------------------------------
    # TCK at the cable's speed (-tck_mhz). Every crossing between TCK and the
    # sample clock gets a datapath-only bound of one period of the faster of
    # the two. Each settings and readback bundle is registered with its
    # toggle and copied at least two destination clocks after the toggle
    # reaches its first synchronizer stage, so within that bound it arrives
    # settled. Hold is not checked on these paths.
    set tck [get_pins -of_objects \
        [get_cells -hierarchical -filter "REF_NAME == BSCANE2 && NAME =~ $cell/*"] \
        -filter {REF_PIN_NAME == TCK}]
    set tck_ns [expr {1000.0 / $o(tck_mhz)}]
    create_clock -name ${cell}_tck -period $tck_ns $tck
    set tck_clk [get_clocks ${cell}_tck]
    set sclks [get_clocks -quiet -of_objects [get_nets $clk_name]]
    if {[llength $sclks] == 0} {
        puts "WARNING: fcapz::insert: no clock is defined on $clk_name, so the\
              ELA's clock crossings are not timed; constrain the sample clock"
    }
    foreach sclk $sclks {
        set bound [expr {min($tck_ns, [get_property PERIOD $sclk])}]
        set_max_delay -datapath_only -from $tck_clk -to $sclk $bound
        set_max_delay -datapath_only -from $sclk -to $tck_clk $bound
    }

    write_checkpoint -force $o(out)

    # -- 6. the host's probe map ------------------------------------------
    if {$o(prob) ne ""} {
        set rows {}
        foreach b $order {
            lappend rows "    {\"name\": [fcapz::_json_str $b], \"width\": $width($b), \"lsb\": $base_lsb($b)}"
        }
        set fh [open $o(prob) w]
        puts $fh "{"
        puts $fh "  \"format\": \"fpgacapzero.probes.v1\","
        puts $fh "  \"core\": \"ela\","
        puts $fh "  \"probes\": \["
        puts $fh [join $rows ",\n"]
        puts $fh "  \],"
        if {$o(clock_hz) ne ""} {
            puts $fh "  \"sample_clock_hz\": [expr {int($o(clock_hz))}],"
        }
        puts $fh "  \"sample_width\": $sample_w"
        puts $fh "}"
        close $fh
    }
    puts "fcapz::insert: $sample_w probe bit(s) from [llength $order] signal(s) on $clk_name, USER$o(chain), depth $o(depth) -> $o(out)"
    return [list sample_width $sample_w clock $clk_name nets $net_names]
}
