# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Minimal RISC-V (RV32I) reset/boot for the Arty VexRiscv Dhrystone firmware.
# VexRiscv boots at externalResetVector = 0x0 (tied in vex_cpu.v), so _start
# is placed at 0x0 by the linker (.text.init). It sets gp/sp, zeroes .bss, and
# calls main(). main() runs the Dhrystone loop forever (re-arms on the host go
# flag) and never returns, but a safety spin follows just in case.

    .section .text.init, "ax"
    .global _start
_start:
    # Global pointer for gp-relative (.sdata/.sbss) access. Relaxation must be
    # off across this load or the assembler rewrites it relative to gp itself.
.option push
.option norelax
    la      gp, __global_pointer$
.option pop

    la      sp, __stack_top

    # Zero .bss/.sbss (word-aligned by the linker script).
    la      a0, __bss_start
    la      a1, __bss_end
1:  bgeu    a0, a1, 2f
    sw      zero, 0(a0)
    addi    a0, a0, 4
    j       1b

2:  call    main
3:  j       3b
