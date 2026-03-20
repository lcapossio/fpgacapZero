# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# Auto-calibrate and validate fpgacapZero JTAG register access via XSDB.
#
# Usage:
#   xsdb scripts/xsdb_autocal_rnw.tcl ?host? ?port? ?fpga_name? ?tap_name? ?bitfile? ?verbose?
#
# This script uses the -bits format for drshift which provides standard
# JTAG bit ordering (bit[k] of the string = sr[k] in the shift register).
# The -hex format has a non-standard byte/nibble transformation in XSDB.
#
# 49-bit DR protocol (bit string position = sr index):
#   bits[31:0]  = wdata / rdata
#   bits[47:32] = addr[15:0]
#   bit[48]     = rnw (1 = write, 0 = read)

set host "127.0.0.1"
set port "3121"
set fpga_name "xc7a100t"
set tap_name "xc7a100t"
set bitfile ""
set verbose 0

if {$argc >= 1} { set host [lindex $argv 0] }
if {$argc >= 2} { set port [lindex $argv 1] }
if {$argc >= 3} { set fpga_name [lindex $argv 2] }
if {$argc >= 4} { set tap_name [lindex $argv 3] }
if {$argc >= 5} { set bitfile [lindex $argv 4] }
if {$argc >= 6} { set verbose [lindex $argv 5] }

set USER1_IR 0x02
set DR_BITS 49
set READ_IDLE_CYCLES 20

set ADDR_VERSION    0x0000
set ADDR_SAMPLE_W   0x000C
set ADDR_DEPTH      0x0010
set ADDR_TRIG_MASK  0x0028

proc make_frame_bits {rnw addr data} {
    set s ""
    for {set i 0} {$i < 32} {incr i} {
        if {[expr {($data >> $i) & 1}]} {
            append s "1"
        } else {
            append s "0"
        }
    }
    for {set i 0} {$i < 16} {incr i} {
        if {[expr {($addr >> $i) & 1}]} {
            append s "1"
        } else {
            append s "0"
        }
    }
    if {$rnw} {
        append s "1"
    } else {
        append s "0"
    }
    return $s
}

proc select_jtag_target {name} {
    if {[catch {jtag targets -set -filter "name =~ \"$name\""} msg]} {
        error "cannot select JTAG target '$name': $msg"
    }
}

proc run_dr_bits {bits_frame capture_en} {
    global USER1_IR DR_BITS
    set seq [jtag sequence]
    $seq irshift -state IRUPDATE -hex 6 [format "%02x" $USER1_IR]
    if {$capture_en} {
        $seq drshift -state DRUPDATE -capture -bits $DR_BITS $bits_frame
    } else {
        $seq drshift -state DRUPDATE -bits $DR_BITS $bits_frame
    }
    set raw [$seq run -bits]
    $seq delete
    return $raw
}

proc run_idle {cycles} {
    set seq [jtag sequence]
    $seq delay $cycles
    $seq run
    $seq delete
}

proc extract_bits {raw} {
    set tokens [regexp -all -inline {[01]+} $raw]
    set best ""
    foreach t $tokens {
        if {[string length $t] > [string length $best]} { set best $t }
    }
    return $best
}

proc bits_to_u32 {bits} {
    set out 0
    set n [string length $bits]
    if {$n > 32} { set n 32 }
    for {set i 0} {$i < $n} {incr i} {
        if {[string index $bits $i] eq "1"} {
            set out [expr {$out | (1 << $i)}]
        }
    }
    return $out
}

proc read_reg {addr} {
    global READ_IDLE_CYCLES tap_name verbose
    select_jtag_target $tap_name
    set frame [make_frame_bits 0 $addr 0]
    run_dr_bits $frame 0
    run_idle $READ_IDLE_CYCLES
    set raw [run_dr_bits $frame 1]
    if {$verbose} {
        puts [format "    read_reg addr=0x%04x raw='%s'" $addr $raw]
    }
    set bits [extract_bits $raw]
    return [bits_to_u32 $bits]
}

proc write_reg {addr value} {
    global tap_name verbose
    select_jtag_target $tap_name
    set frame [make_frame_bits 1 $addr $value]
    if {$verbose} {
        puts [format "    write_reg addr=0x%04x value=0x%08x frame=%s" $addr $value $frame]
    }
    run_dr_bits $frame 0
}

# ---- main ----

puts [format "Connecting to hw_server at %s:%s ..." $host $port]
connect -url "tcp:$host:$port"
after 500

if {$verbose} {
    puts "Available JTAG targets:"
    catch {jtag targets} jt
    puts $jt
}

# Program FPGA
if {$bitfile eq ""} {
    set script_dir [file dirname [info script]]
    set bitfile [file normalize [file join $script_dir .. examples arty_a7 arty_a7_top.bit]]
}
if {[file exists $bitfile]} {
    puts "Programming FPGA: $bitfile"
    targets -set -filter "name =~ \"$fpga_name\""
    fpga -file $bitfile
    after 500
} else {
    puts "Bitfile not found at $bitfile, skipping programming."
}

# Validate reads
puts ""
puts "Validating register reads..."
set ver [read_reg $ADDR_VERSION]
set sw  [read_reg $ADDR_SAMPLE_W]
set dep [read_reg $ADDR_DEPTH]
set tm  [read_reg $ADDR_TRIG_MASK]
puts [format "  VERSION    = 0x%08x (expect 0x00010001)" $ver]
puts [format "  SAMPLE_W   = %d" $sw]
puts [format "  DEPTH      = %d" $dep]
puts [format "  TRIG_MASK  = 0x%08x (expect 0xFFFFFFFF)" $tm]

set read_ok [expr {$ver == 0x00010001 && $sw >= 1 && $sw <= 4096 && $dep >= 16 && $dep <= (1 << 24)}]
if {!$read_ok} {
    puts "\nRESULT: FAIL - register reads not plausible"
    exit 2
}
puts "  -> reads OK"

# Validate writes: TRIG_MASK round-trip
puts ""
puts "Validating register writes (TRIG_MASK round-trip)..."

write_reg $ADDR_TRIG_MASK 0x00000000
run_idle 4
set tm0 [read_reg $ADDR_TRIG_MASK]
puts [format "  write 0x00000000 -> read back 0x%08x" $tm0]

write_reg $ADDR_TRIG_MASK 0xA5A5A5A5
run_idle 4
set tma [read_reg $ADDR_TRIG_MASK]
puts [format "  write 0xA5A5A5A5 -> read back 0x%08x" $tma]

write_reg $ADDR_TRIG_MASK 0xFFFFFFFF
run_idle 4
set tm1 [read_reg $ADDR_TRIG_MASK]
puts [format "  write 0xFFFFFFFF -> read back 0x%08x" $tm1]

set write_ok [expr {$tm0 == 0x00000000 && $tma == 0xA5A5A5A5 && $tm1 == 0xFFFFFFFF}]
if {!$write_ok} {
    puts "\nRESULT: FAIL - write round-trip mismatch"
    exit 2
}
puts "  -> writes OK"

puts ""
puts "RESULT: PASS"
puts "  Transport: XSDB jtag sequence with -bits format"
puts "  DR width: 49 bits"
puts "  Bit layout: data\[31:0\] | addr\[15:0\] | rnw"
puts [format "  Board: %s (SAMPLE_W=%d, DEPTH=%d)" $fpga_name $sw $dep]
exit 0
