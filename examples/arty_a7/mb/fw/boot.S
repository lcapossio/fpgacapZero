/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Minimal MicroBlaze reset/boot for the Arty fpgacapZero firmware.  Avoids the
 * standalone BSP: the reset vector at 0x0 jumps to _boot, which sets the stack
 * pointer to the top of the 32 KB LMB and calls main().  main() never returns
 * (infinite polling loop), but a safety spin follows just in case.
 *
 * Base-ISA only, little-endian (must match the MicroBlaze C_ENDIANNESS).
 */

    .section .vectors.reset, "ax"
    .global _start
_start:
    brai    _boot            /* absolute branch, no delay slot */

    .section .text.boot, "ax"
    .global _boot
_boot:
    addik   r1, r0, 0x7FF0   /* stack pointer = top of 32 KB LMB, 16-byte aligned */
    brlid   r15, main        /* call main() (delay-slot branch-and-link) */
    nop
1:  bri     1b               /* main returned: spin */
