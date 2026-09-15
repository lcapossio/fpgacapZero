# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# GDB smoke test for VexRiscv CPU debug on the Arty A7 (arty_a7_vex_debug.cfg).
# Proves halt / register read / halted-memory read (progbuf) / single-step /
# hardware breakpoint against the tunnelled RISC-V Debug Module.
#
#   riscv64-unknown-elf-gdb -x examples/arty_a7/arty_a7_vex_debug.gdb
#
# (any riscv*-gdb works; the target is RV32IM). Optionally load the firmware
# ELF first for source-level symbols:  gdb vex/fw/build/fw.elf -x <this>

set pagination off
set confirm off
set architecture riscv:rv32

target extended-remote :3333

echo \n== halt ==\n
monitor halt
info registers pc
info registers ra sp gp
# mstatus proves CSR access through the DM abstract command path.
info registers mstatus

echo \n== read firmware word at 0x0 (progbuf halted-memory access) ==\n
x/4xw 0x0

echo \n== single-step, expect pc to advance ==\n
stepi
info registers pc
stepi
info registers pc

# Hardware breakpoint (the CsrPlugin exposes 2 execute-address triggers).
# Pick an address your firmware actually reaches; 0x8 is just a placeholder
# a few instructions into the reset handler. Uncomment to exercise it:
#   hbreak *0x00000008
#   continue
#   info registers pc

echo \n== done: CPU is halted; 'continue' to resume, 'detach' to leave running ==\n
