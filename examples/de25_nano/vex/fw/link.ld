/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Linker script for the DE25-Nano VexRiscv firmware. Everything lives in
 * the 64 KB on-chip BRAM at 0x0 (matches the RAM aperture decoded in
 * vex_cpu.v). The reset vector is forced to 0x0 so the CPU boots into _start.
 */

ENTRY(_start)

MEMORY
{
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 0x00010000  /* 64 KB */
}

SECTIONS
{
    .text.init 0x00000000 :
    {
        KEEP(*(.text.init))
    } > RAM

    .text :
    {
        *(.text)
        *(.text.*)
    } > RAM

    .rodata :
    {
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
    } > RAM

    .data :
    {
        *(.data)
        *(.data.*)
        . = ALIGN(8);
        __global_pointer$ = . + 0x800;
        *(.sdata)
        *(.sdata.*)
    } > RAM

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        __bss_start = .;
        *(.sbss)
        *(.sbss.*)
        *(.bss)
        *(.bss.*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM

    /* Stack grows down from the top of BRAM. */
    __stack_top = ORIGIN(RAM) + LENGTH(RAM);
}
