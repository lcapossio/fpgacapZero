/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Linker script for the Arty MicroBlaze firmware.  Everything lives in the
 * 32 KB dual-port LMB BRAM at 0x0 (matches the block design's local memory
 * aperture).  The reset vector is forced to 0x0 so the CPU boots into _start.
 */

ENTRY(_start)

MEMORY
{
    LMB (rwx) : ORIGIN = 0x00000000, LENGTH = 0x00008000  /* 32 KB */
}

_STACK_SIZE = 0x800;

SECTIONS
{
    .vectors 0x00000000 :
    {
        KEEP(*(.vectors.reset))
        KEEP(*(.vectors*))
    } > LMB

    .text :
    {
        *(.text.boot)
        *(.text)
        *(.text.*)
    } > LMB

    .rodata :
    {
        *(.rodata)
        *(.rodata.*)
    } > LMB

    .data :
    {
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
    } > LMB

    .bss (NOLOAD) :
    {
        _bss_start = .;
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        *(COMMON)
        _bss_end = .;
    } > LMB

    . = ALIGN(16);
    _stack_end = .;
    . += _STACK_SIZE;
    . = ALIGN(16);
    __stack = .;
}
