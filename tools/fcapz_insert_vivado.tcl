# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Post-synthesis insertion of fcapz debug cores into a Vivado netlist.
#
# The design is synthesized without any fcapz RTL; the nets to capture carry
# MARK_DEBUG (as for Vivado's own ILA), which also keeps synthesis from
# optimizing them away.  fcapz::insert then:
#
#   1. collects the MARK_DEBUG nets and groups them into ELAs, one per
#      sample clock (the clock of the flip-flops that drive them), or as
#      -group says,
#   2. synthesizes tools/fcapz_insert_wrap.v out of context, sized to them:
#      the ELAs and an optional EIO behind the core manager on one USER
#      chain, 7-series or UltraScale(+) by the part,
#   3. adds it to the netlist as a black box filled from that checkpoint,
#   4. wires the probes, clocks, EIO and triggers,
#   5. constrains the BSCANE2 TCK and every clock crossing, and
#   6. writes the instrumented checkpoint, a .prob per ELA, and a manifest.
#
# Place, route and write_bitstream continue from the written checkpoint.
#
#   source tools/fcapz_insert_vivado.tcl
#   fcapz::insert -in post_synth.dcp -out instrumented.dcp -rtl <repo>/rtl \
#       -prob design.prob
#
# The host reaches ELA n as core-manager slot n (fcapz --ela-instance n) and
# the EIO as the slot after the last ELA (fcapz eio-read --instance N).
#
# Options (all optional but -in, -out, -rtl):
#   -prob <file>        probe map; one ELA writes <file>, several write
#                       <root>_ela<n>.prob.  Also writes <root>.insert.json.
#   -depth <n>          samples per ELA (1024); -depths {ela n ...} per ELA
#   -group {{name {globs} ?clock?} ...}
#                       nets whose names match a group's globs form an ELA of
#                       their own; its clock is inferred, or the one given
#   -clock <net>        sample every ungrouped net on this clock (one ELA)
#   -default_clock <net> clock for nets not driven by a flip-flop
#   -clock_hz <hz> | {ela hz ...}
#                       sample clock written to the .prob; by default taken
#                       from the timing clock on the net
#   -eio_in {nets}      read by the EIO (any clock; synchronized inside)
#   -eio_out {nets}     driven by the EIO, in the JTAG clock: the net's own
#                       driver (keep a placeholder with DONT_TOUCH) is cut off
#   -trigger_in {ela net ...}   a design net into an ELA's trigger input
#   -trigger_out {ela net ...}  an ELA's trigger pulse onto a design net
#   -armed_out {ela net ...}    an ELA's armed level onto a design net
#   -cross_trigger {dst src ...} ELA src's trigger starts ELA dst
#   -chain (USER chain, 1), -tck_mhz (TCK constraint, 10), -part,
#   -cell (instance name, u_fcapz)
#
# An ELA is named by its group name, or else by the full name of its clock
# net; options take that name or the ELA's instance number.

namespace eval fcapz {}

# The RTL the wrapper elaborates (relative to rtl/), and the wrapper itself.
set fcapz::rtl_sources {
    reset_sync.v dpram.v trig_compare.v fcapz_ela.v fcapz_eio.v
    fcapz_core_manager.v fcapz_debug_multi_core.v fcapz_hub_reset.v
    fcapz_debug_multi.v fcapz_debug_multi_xilinx7.v fcapz_debug_multi_xilinxus.v
    jtag_reg_iface.v jtag_pipe_iface.v jtag_burst_read.v
    jtag_tap/jtag_tap_xilinx7.v jtag_tap/jtag_tap_xilinxus.v
    dff_sync.v dff_reg_sync.v fcapz_async_fifo.v
}
set fcapz::wrap_source [file join [file dirname [file normalize [info script]]] fcapz_insert_wrap.v]

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

# Group bit nets into signals, in order, low bits first.  "u_core/count[3]"
# belongs to signal "u_core/count" (the netlist's own name, so names stay
# unique); a scalar net is 1 bit.  A bus spans its lowest to highest listed
# index and must be listed without gaps, so every bit a map advertises is
# wired.  Returns {order widths lows bits total}: widths and lows as array
# lists, bits holding {lsb net-name} per net with lsb its bit in the packed
# vector, total its width.  Takes and keeps net names: object handles go
# stale on read_checkpoint.
proc fcapz::_pack {names what} {
    array set lo {}
    array set hi {}
    array set count {}
    set order {}
    set raw {}
    foreach name [lsort -dictionary -unique $names] {
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
        lappend raw [list $base $idx $name]
        set lo($base) [expr {min($lo($base), $idx)}]
        set hi($base) [expr {max($hi($base), $idx)}]
        incr count($base)
    }
    array set width {}
    array set lsb {}
    set total 0
    foreach b $order {
        set width($b) [expr {$hi($b) - $lo($b) + 1}]
        if {$count($b) != $width($b)} {
            error "fcapz::insert: only $count($b) bits of $b\[$hi($b):$lo($b)\] are $what; take the whole range"
        }
        if {[regexp {[:,\x00-\x1f]} $b]} {
            error "fcapz::insert: signal name '$b' has a ':', ',' or control character, which the host's probe list cannot carry"
        }
        set lsb($b) $total
        incr total $width($b)
    }
    set bits {}
    foreach entry $raw {
        lassign $entry base idx name
        lappend bits [list [expr {$lsb($base) + $idx - $lo($base)}] $name]
    }
    return [list $order [array get width] [array get lsb] $bits $total]
}

# The clock a net is sampled on: the clock of the flip-flop that drives it.
# Anything else (LUT, LUTRAM, BRAM, DSP, a port) returns {} and needs a
# clock given, since a primitive's clock pin need not be the clock of that
# output.
proc fcapz::_clock_of {net} {
    set drv [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $drv] != 1} { return {} }
    set cell [get_cells -of_objects $drv]
    if {![regexp {^FD[CPRS]E$} [get_property REF_NAME $cell]]} { return {} }
    set cpin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C}]
    if {[llength $cpin] != 1} { return {} }
    return [get_property NAME \
        [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $cpin]]
}

# The full name of a net given by name, or an error naming the option.
proc fcapz::_net_name {name what} {
    set n [get_nets -quiet $name]
    if {[llength $n] != 1} {
        error "fcapz::insert: $what: no net named $name (give its full hierarchical name)"
    }
    return [get_property NAME $n]
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

# 7-series or UltraScale(+), from the part's architecture.
proc fcapz::_family {part} {
    set arch [string tolower [get_property ARCHITECTURE [get_parts $part]]]
    if {[regexp {^(artix7|kintex7|virtex7|spartan7|zynq|aartix7|akintex7|azynq|qartix7|qkintex7|qvirtex7|qzynq)$} $arch]} {
        return 7
    }
    # kintexu, virtexu, and every UltraScale+ (kintexuplus, zynquplusrfsoc,
    # virtexuplushbm, ...), with the a/q grade prefixes.
    if {[regexp {uplus|^a?q?(kintex|virtex)u$} $arch]} {
        return us
    }
    error "fcapz::insert: part $part ($arch) is not 7-series or UltraScale(+)"
}

# The instance number of the ELA $key names (a name or a number); $slots is
# {name->instance array list, ELA count}.
proc fcapz::_slot {slots key what} {
    lassign $slots names num
    array set s $names
    if {[string is integer -strict $key] && $key >= 0 && $key < $num} { return $key }
    if {[info exists s($key)]} { return $s($key) }
    error "fcapz::insert: $what: no ELA $key (ELAs: [lsort [array names s]])"
}

# DONT_TOUCH (MARK_DEBUG sets it on a net, and designs set it on cells and
# hierarchies) makes connect_net and disconnect_net refuse an edit. Lift it
# on $objs and on every hierarchical cell above them; the result is the list
# to hand back to _relock.
proc fcapz::_unlock {objs} {
    set todo {}
    foreach obj $objs {
        lappend todo $obj
        set class [get_property CLASS $obj]
        set p [expr {$class eq "cell" ? [get_property PARENT $obj] : [get_property PARENT_CELL $obj]}]
        while {$p ne ""} {
            set c [get_cells -quiet $p]
            if {[llength $c] != 1} { break }
            lappend todo $c
            set p [get_property PARENT $c]
        }
    }
    set lifted {}
    foreach obj $todo {
        if {[string is true -strict [get_property DONT_TOUCH $obj]]} {
            set_property DONT_TOUCH false $obj
            lappend lifted [list [get_property CLASS $obj] [get_property NAME $obj]]
        }
    }
    return $lifted
}

proc fcapz::_relock {lifted} {
    foreach l $lifted {
        lassign $l class name
        set obj [expr {$class eq "cell" ? [get_cells -quiet $name] : [get_nets -quiet $name]}]
        if {[llength $obj]} { set_property DONT_TOUCH true $obj }
    }
}

proc fcapz::_connect {name pins} {
    set lifted [fcapz::_unlock [get_nets $name]]
    set err [catch {connect_net -hierarchical -net [get_nets $name] -objects $pins} msg]
    fcapz::_relock $lifted
    if {$err} { error "fcapz::insert: cannot connect $name: $msg" }
}

# Drive net $name from $pin instead of its own driver, which is cut off. If
# the new connection fails, the driver is put back.
proc fcapz::_drive {name pin what} {
    set net [get_nets $name]
    if {[llength [get_ports -quiet -of_objects $net -filter {DIRECTION == IN}]]} {
        error "fcapz::insert: $what: $name is driven by an input port"
    }
    set drv [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $drv] != 1} {
        error "fcapz::insert: $what: $name has [llength $drv] drivers, expected 1"
    }
    set seg [get_nets -of_objects $drv]
    set seg_name [get_property NAME $seg]
    set lifted [fcapz::_unlock [list $net $seg [get_cells -of_objects $drv]]]
    if {[catch {disconnect_net -net $seg -objects $drv} msg]} {
        fcapz::_relock $lifted
        error "fcapz::insert: $what: cannot cut the driver of $name: $msg"
    }
    if {[catch {connect_net -hierarchical -net [get_nets $name] -objects $pin} msg]} {
        connect_net -net [get_nets $seg_name] -objects $drv
        fcapz::_relock $lifted
        error "fcapz::insert: $what: cannot drive $name: $msg"
    }
    fcapz::_relock $lifted
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

# A JSON array of {"name", "width", "lsb"} rows, indented by $pad.
proc fcapz::_json_signals {order widths lsbs pad} {
    array set w $widths
    array set l $lsbs
    set rows {}
    foreach b $order {
        lappend rows "$pad{\"name\": [fcapz::_json_str $b], \"width\": $w($b), \"lsb\": $l($b)}"
    }
    return "\[\n[join $rows ",\n"]\n[string range $pad 2 end]\]"
}

# A packed Verilog literal of 32-bit words, word 0 lowest.
proc fcapz::_words {values bits} {
    set hex ""
    foreach v [lreverse $values] {
        append hex [format "%0*x" [expr {$bits / 4}] $v]
    }
    return "[expr {[llength $values] * $bits}]'h$hex"
}

proc fcapz::insert {args} {
    array set o [fcapz::_opts {
        in {} out {} rtl {} prob {} depth 1024 depths {} chain 1 clock {}
        default_clock {} group {} cell u_fcapz part {} clock_hz {} tck_mhz 10
        eio_in {} eio_out {} trigger_in {} trigger_out {} armed_out {}
        cross_trigger {}
    } $args]
    foreach req {in out rtl} {
        if {$o($req) eq ""} { error "fcapz::insert: -$req is required" }
    }
    foreach opt {trigger_in trigger_out armed_out cross_trigger depths} {
        if {[llength $o($opt)] % 2} {
            error "fcapz::insert: -$opt takes {ela value ...} pairs"
        }
    }

    # -- 1. what to capture, and on which clock ---------------------------
    open_checkpoint $o(in)
    set part [expr {$o(part) ne "" ? $o(part) : [get_property PART [current_design]]}]
    set family [fcapz::_family $part]

    # Nets the cores drive are not captured: their driver changes.
    set driven {}
    foreach n $o(eio_out) { lappend driven [fcapz::_net_name $n -eio_out] }
    foreach opt {trigger_out armed_out} {
        foreach {e n} $o($opt) { lappend driven [fcapz::_net_name $n -$opt] }
    }
    set nets {}
    foreach n [get_nets -hierarchical -filter {MARK_DEBUG == TRUE}] {
        set name [get_property NAME $n]
        if {[lsearch -exact $driven $name] < 0} { lappend nets $name }
    }
    if {[llength $nets] == 0} {
        error "fcapz::insert: no MARK_DEBUG nets to capture in $o(in)"
    }

    set clock_all [expr {$o(clock) ne "" ? [fcapz::_net_name $o(clock) -clock] : ""}]
    set clock_def [expr {$o(default_clock) ne "" ? [fcapz::_net_name $o(default_clock) -default_clock] : ""}]

    # ELAs as {name clock nets}: groups first, in the order given, then one
    # per clock of the nets left, by clock name.
    set elas {}
    set left $nets
    foreach g $o(group) {
        lassign $g gname globs gclock
        if {$gname eq "" || [llength $globs] == 0} {
            error "fcapz::insert: -group entries are {name {globs} ?clock?}, got {$g}"
        }
        set mine {}
        set rest {}
        foreach n $left {
            set hit 0
            foreach pat $globs { if {[string match $pat $n]} { set hit 1; break } }
            if {$hit} { lappend mine $n } else { lappend rest $n }
        }
        if {[llength $mine] == 0} {
            error "fcapz::insert: -group $gname matches no MARK_DEBUG net"
        }
        set left $rest
        if {$gclock ne ""} {
            set clk [fcapz::_net_name $gclock "-group $gname"]
        } else {
            set clks {}
            foreach n $mine {
                set c [fcapz::_clock_of [get_nets $n]]
                if {$c eq ""} { set c $clock_def }
                if {$c eq ""} {
                    error "fcapz::insert: $n is not driven by a flip-flop, so its clock is not known; give -group $gname a clock, or -default_clock"
                }
                if {[lsearch -exact $clks $c] < 0} { lappend clks $c }
            }
            if {[llength $clks] != 1} {
                error "fcapz::insert: -group $gname has nets from several clocks ($clks); give it a clock"
            }
            set clk [lindex $clks 0]
        }
        lappend elas [list $gname $clk $mine]
    }
    array set by_clock {}
    foreach n $left {
        if {$clock_all ne ""} {
            set c $clock_all
        } else {
            set c [fcapz::_clock_of [get_nets $n]]
            if {$c eq ""} { set c $clock_def }
            if {$c eq ""} {
                error "fcapz::insert: $n is not driven by a flip-flop, so its clock is not known; pass -default_clock, -clock or -group"
            }
        }
        lappend by_clock($c) $n
    }
    foreach c [lsort -dictionary [array names by_clock]] {
        lappend elas [list $c $c $by_clock($c)]
    }
    set num_elas [llength $elas]

    # ELA by name or instance number.
    array set slot_of {}
    set i 0
    foreach e $elas {
        set nm [lindex $e 0]
        if {[info exists slot_of($nm)]} {
            error "fcapz::insert: two ELAs are named $nm"
        }
        set slot_of($nm) $i
        incr i
    }
    set slots [list [array get slot_of] $num_elas]

    # Each ELA's probe map and depth.
    set packs {}
    set depths {}
    set sample_w 1
    foreach e $elas {
        lassign $e nm clk enets
        set p [fcapz::_pack $enets "MARK_DEBUG in ELA $nm"]
        lappend packs $p
        set sample_w [expr {max($sample_w, [lindex $p 4])}]
        lappend depths $o(depth)
    }
    foreach {e d} $o(depths) {
        set s [fcapz::_slot $slots $e -depths]
        lset depths $s $d
    }
    foreach d $depths {
        if {![string is integer -strict $d] || $d < 16 || ($d & ($d - 1))} {
            error "fcapz::insert: ELA depth $d is not a power of two of at least 16"
        }
    }

    # Triggers.
    set ext_trig [lrepeat $num_elas 0]
    set xtrig [lrepeat $num_elas 0]
    set trig_in {}
    foreach {e n} $o(trigger_in) {
        set s [fcapz::_slot $slots $e -trigger_in]
        lappend trig_in [list $s [fcapz::_net_name $n -trigger_in]]
        lset ext_trig $s 1
    }
    set trig_out {}
    foreach opt {trigger_out armed_out} {
        foreach {e n} $o($opt) {
            set s [fcapz::_slot $slots $e -$opt]
            lappend trig_out [list $opt $s [fcapz::_net_name $n -$opt]]
            if {$opt eq "trigger_out"} { lset ext_trig $s 1 }
        }
    }
    foreach {dst src} $o(cross_trigger) {
        set d [fcapz::_slot $slots $dst -cross_trigger]
        set s [fcapz::_slot $slots $src -cross_trigger]
        if {$d == $s} { error "fcapz::insert: -cross_trigger: ELA $dst cannot trigger itself" }
        if {[lindex $xtrig $d]} { error "fcapz::insert: -cross_trigger: ELA $dst has two sources" }
        # XTRIG_SRCS holds source + 1 in 8 bits.
        if {$s > 254} { error "fcapz::insert: -cross_trigger: source ELA $src is above 254" }
        lset xtrig $d [expr {$s + 1}]
        lset ext_trig $d 1
        lset ext_trig $s 1
    }

    # EIO.
    set eio_en [expr {[llength $o(eio_in)] + [llength $o(eio_out)] > 0}]
    set eio_in_names {}
    foreach n $o(eio_in) { lappend eio_in_names [fcapz::_net_name $n -eio_in] }
    set eio_out_names {}
    foreach n $o(eio_out) { lappend eio_out_names [fcapz::_net_name $n -eio_out] }
    set eio_in_pack [expr {[llength $eio_in_names] ? [fcapz::_pack $eio_in_names "-eio_in"] : [list {} {} {} {} 0]}]
    set eio_out_pack [expr {[llength $eio_out_names] ? [fcapz::_pack $eio_out_names "-eio_out"] : [list {} {} {} {} 0]}]
    set eio_in_w [expr {max(1, [lindex $eio_in_pack 4])}]
    set eio_out_w [expr {max(1, [lindex $eio_out_pack 4])}]

    set used_chains [fcapz::_used_chains]
    if {[lsearch -exact $used_chains $o(chain)] >= 0} {
        error "fcapz::insert: USER$o(chain) is taken (by a BSCANE2 or Vivado's debug hub; in use: $used_chains); pass -chain"
    }

    # Sample clock rates, from the timing clocks unless given.
    set clock_hz {}
    foreach e $elas {
        set hz ""
        set sc [get_clocks -quiet -of_objects [get_nets [lindex $e 1]]]
        if {[llength $sc] == 1} {
            set hz [expr {round(1e9 / [get_property PERIOD $sc])}]
        }
        lappend clock_hz $hz
    }
    if {[llength $o(clock_hz)] > 1 && [llength $o(clock_hz)] % 2} {
        error "fcapz::insert: -clock_hz: give one rate, or ELA/rate pairs"
    }
    foreach hz [expr {[llength $o(clock_hz)] == 1 ? $o(clock_hz) : [dict values $o(clock_hz)]}] {
        if {![string is double -strict $hz] || $hz <= 0} {
            error "fcapz::insert: -clock_hz: $hz is not a rate in Hz"
        }
    }
    if {[llength $o(clock_hz)] == 1} {
        set clock_hz [lrepeat $num_elas $o(clock_hz)]
    } else {
        foreach {e hz} $o(clock_hz) { lset clock_hz [fcapz::_slot $slots $e -clock_hz] $hz }
    }
    close_design

    # -- 2. the debug block, sized to the nets ------------------------------
    # A project of its own, so the caller's sources and XDC stay out of it.
    set wrap_dcp [file rootname $o(out)]_fcapz.dcp
    close_project -quiet
    create_project -in_memory -part $part
    set srcs [list $fcapz::wrap_source]
    foreach f $fcapz::rtl_sources { lappend srcs [file join $o(rtl) $f] }
    read_verilog $srcs
    set widths {}
    foreach p $packs { lappend widths [lindex $p 4] }
    synth_design -top fcapz_insert_wrap -part $part -mode out_of_context \
        -include_dirs [list $o(rtl)] \
        -generic NUM_ELAS=$num_elas -generic SAMPLE_W=$sample_w \
        -generic DEPTH=[tcl::mathfunc::max {*}$depths] \
        -generic ELA_SAMPLE_WS=[fcapz::_words $widths 32] \
        -generic ELA_DEPTHS=[fcapz::_words $depths 32] \
        -generic ELA_EXT_TRIG_ENS=[fcapz::_words $ext_trig 32] \
        -generic XTRIG_SRCS=[fcapz::_words $xtrig 8] \
        -generic EIO_EN=$eio_en -generic EIO_IN_W=$eio_in_w \
        -generic EIO_OUT_W=$eio_out_w -generic CTRL_CHAIN=$o(chain) \
        -generic ULTRASCALE=[expr {$family eq "us"}]
    set ports [fcapz::_port_spec]
    write_checkpoint -force $wrap_dcp
    close_project

    # -- 3. into the netlist ----------------------------------------------
    open_checkpoint $o(in)
    set cell $o(cell)
    create_cell -reference fcapz_insert_wrap -black_box $cell
    foreach p $ports {
        lassign $p name dir lo hi
        if {$lo eq ""} {
            create_pin -direction $dir $cell/$name
        } else {
            create_pin -direction $dir -from $hi -to $lo $cell/$name
        }
    }
    read_checkpoint -cell $cell $wrap_dcp

    # -- 4. wiring ----------------------------------------------------------
    set s 0
    foreach e $elas p $packs {
        foreach entry [lindex $p 3] {
            lassign $entry bit name
            set idx [expr {$s * $sample_w + $bit}]
            fcapz::_connect $name [get_pins "$cell/ela_probe_in\[$idx\]"]
        }
        fcapz::_connect [lindex $e 1] [get_pins "$cell/ela_sample_clk\[$s\]"]
        incr s
    }
    foreach entry [lindex $eio_in_pack 3] {
        lassign $entry bit name
        fcapz::_connect $name [get_pins "$cell/eio_probe_in\[$bit\]"]
    }
    foreach entry [lindex $eio_out_pack 3] {
        lassign $entry bit name
        fcapz::_drive $name [get_pins "$cell/eio_probe_out\[$bit\]"] -eio_out
    }
    foreach t $trig_in {
        lassign $t s name
        fcapz::_connect $name [get_pins "$cell/ela_trigger_in\[$s\]"]
    }
    foreach t $trig_out {
        lassign $t opt s name
        set port [expr {$opt eq "trigger_out" ? "ela_trigger_out" : "ela_armed_out"}]
        fcapz::_drive $name [get_pins "$cell/$port\[$s\]"] -$opt
    }
    # Every input left open is tied low.
    set tie {}
    foreach p [get_pins -quiet $cell/* -filter {DIRECTION == IN}] {
        if {[llength [get_nets -quiet -of_objects $p]] == 0} { lappend tie $p }
    }
    if {[llength $tie]} {
        create_cell -reference GND ${cell}_gnd
        create_net ${cell}_gnd_net
        connect_net -net ${cell}_gnd_net -objects [concat [get_pins ${cell}_gnd/G] $tie]
    }

    # -- 5. constraints -----------------------------------------------------
    # TCK at the cable's speed (-tck_mhz). Every crossing between TCK and a
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
    set done_clks {}
    foreach e $elas {
        set clk_name [lindex $e 1]
        set sclks [get_clocks -quiet -of_objects [get_nets $clk_name]]
        if {[llength $sclks] == 0} {
            puts "WARNING: fcapz::insert: no clock is defined on $clk_name, so the\
                  clock crossings of ELA [lindex $e 0] are not timed; constrain it"
        }
        foreach sclk $sclks {
            if {[lsearch -exact $done_clks [get_property NAME $sclk]] >= 0} { continue }
            lappend done_clks [get_property NAME $sclk]
            set bound [expr {min($tck_ns, [get_property PERIOD $sclk])}]
            set_max_delay -datapath_only -from $tck_clk -to $sclk $bound
            set_max_delay -datapath_only -from $sclk -to $tck_clk $bound
        }
    }
    # The cross-trigger toggles enter a two-stage synchronizer: cut the path
    # into its first stage only (it exists only when -cross_trigger is used).
    set xmeta [get_pins -quiet -filter {REF_PIN_NAME == D} -of_objects \
        [get_cells -quiet -hierarchical -filter "NAME =~ $cell/*xtrig_meta_reg\[0\]"]]
    if {[llength $xmeta]} { set_false_path -to $xmeta }
    # The EIO's inputs have a synchronizer behind them and its outputs are
    # levels that change under host control; -trigger_in nets enter the ELA's
    # synchronizer. trigger_out and armed_out leave in the ELA's clock and
    # stay timed: synchronizing them into another clock is the design's job.
    foreach port {eio_probe_in eio_probe_out ela_trigger_in} {
        set pins {}
        foreach p [get_pins -quiet $cell/$port*] {
            if {[llength [get_nets -quiet -of_objects $p]]} { lappend pins $p }
        }
        if {[llength $pins]} { set_false_path -through $pins }
    }

    write_checkpoint -force $o(out)

    # -- 6. the host's probe maps and the manifest --------------------------
    set result {}
    set ela_rows {}
    set s 0
    foreach e $elas p $packs d $depths hz $clock_hz {
        lassign $e nm clk
        lassign $p order wl ll bits total
        set prob ""
        if {$o(prob) ne ""} {
            set prob [expr {$num_elas == 1 ? $o(prob) : "[file rootname $o(prob)]_ela$s.prob"}]
            set fh [open $prob w]
            puts $fh "{"
            puts $fh "  \"format\": \"fpgacapzero.probes.v1\","
            puts $fh "  \"core\": \"ela\","
            puts $fh "  \"probes\": [fcapz::_json_signals $order $wl $ll {    }],"
            if {$hz ne ""} { puts $fh "  \"sample_clock_hz\": [expr {int($hz)}]," }
            puts $fh "  \"sample_width\": $total"
            puts $fh "}"
            close $fh
        }
        set hz_json [expr {$hz eq "" ? "null" : int($hz)}]
        lappend ela_rows "    {\"instance\": $s, \"name\": [fcapz::_json_str $nm], \"clock\": [fcapz::_json_str $clk], \"sample_clock_hz\": $hz_json, \"sample_width\": $total, \"depth\": $d, \"prob\": [fcapz::_json_str [file tail $prob]], \"probes\": [fcapz::_json_signals $order $wl $ll {        }]}"
        lappend result [list instance $s name $nm clock $clk sample_width $total depth $d prob $prob]
        puts "fcapz::insert: ELA $s '$nm': $total bit(s) from [llength $order] signal(s) on $clk, depth $d"
        incr s
    }
    if {$o(prob) ne ""} {
        set fh [open "[file rootname $o(prob)].insert.json" w]
        puts $fh "{"
        puts $fh "  \"format\": \"fpgacapzero.insert.v1\","
        puts $fh "  \"part\": [fcapz::_json_str $part],"
        puts $fh "  \"chain\": $o(chain),"
        puts $fh "  \"elas\": \[\n[join $ela_rows ",\n"]\n  \],"
        if {$eio_en} {
            lassign $eio_in_pack io iw il
            lassign $eio_out_pack oo ow ol
            set in_json [expr {[llength $io] ? [fcapz::_json_signals $io $iw $il {      }] : "\[\]"}]
            set out_json [expr {[llength $oo] ? [fcapz::_json_signals $oo $ow $ol {      }] : "\[\]"}]
            puts $fh "  \"eio\": {\"instance\": $num_elas, \"in\": $in_json, \"out\": $out_json}"
        } else {
            puts $fh "  \"eio\": null"
        }
        puts $fh "}"
        close $fh
    }
    if {$eio_en} {
        puts "fcapz::insert: EIO (instance $num_elas): [lindex $eio_in_pack 4] in, [lindex $eio_out_pack 4] out"
    }
    puts "fcapz::insert: USER$o(chain), [expr {$family eq "us" ? "UltraScale" : "7-series"}] -> $o(out)"
    return [list elas $result eio $eio_en]
}
