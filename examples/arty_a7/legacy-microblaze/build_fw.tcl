# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Compile the Arty MicroBlaze firmware with the MicroBlaze GCC that ships with
# Vivado, and return the path to the resulting ELF.  The ELF is later
# associated with the block design's microblaze_0 so write_bitstream bakes it
# into the LMB BRAM.  No hardcoded toolchain paths: mb-gcc is located relative
# to $XILINX_VIVADO.

# Capture the firmware source dir at source time: [info script] inside a proc
# resolves to the *calling* script, not this file.
set ::fcapz_fw_dir [file normalize [file dirname [info script]]/fw]

proc fcapz_build_fw {out_dir} {
    set fw_dir $::fcapz_fw_dir
    if {![info exists ::env(XILINX_VIVADO)]} {
        error "fcapz: XILINX_VIVADO not set; cannot locate mb-gcc"
    }
    set mb_bin [file normalize [file dirname $::env(XILINX_VIVADO)]/gnu/microblaze/nt/bin]
    set mb_gcc [file join $mb_bin mb-gcc.exe]
    if {![file exists $mb_gcc]} {
        # Some installs ship the non-.exe wrapper name.
        set mb_gcc [file join $mb_bin mb-gcc]
    }
    if {![file exists $mb_gcc]} {
        error "fcapz: mb-gcc not found under $mb_bin"
    }

    # mb-gcc needs its own bin dir on PATH for the runtime DLLs.
    set ::env(PATH) "$mb_bin;$::env(PATH)"

    file mkdir $out_dir
    set elf [file normalize $out_dir/mb_fw.elf]
    set map [file normalize $out_dir/mb_fw.map]

    set cmd [list $mb_gcc -O2 -mlittle-endian -mcpu=v11.0 -nostdlib -ffreestanding \
        -Wl,-T,[file normalize $fw_dir/lscript.ld] \
        [file normalize $fw_dir/boot.S] \
        [file normalize $fw_dir/main.c] \
        -o $elf -Wl,-Map,$map]
    puts "fcapz: building firmware: $cmd"
    if {[catch {exec {*}$cmd} e]} {
        error "fcapz: mb-gcc failed: $e"
    }
    if {![file exists $elf]} { error "fcapz: firmware ELF not produced at $elf" }
    puts "fcapz: firmware ELF = $elf"
    return $elf
}
