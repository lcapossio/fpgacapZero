// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// VexRiscv firmware for the Arty A7 fpgacapZero reference design.
//
// Deliberately identical in behaviour to the MicroBlaze firmware
// (examples/arty_a7/mb/fw/main.c) so arty_a7_vex_top is a drop-in for the same
// hardware tests: the open-source VexRiscv replaces the proprietary MicroBlaze
// as the second AXI master on the shared SmartConnect bus, generating the same
// host-gated pattern traffic the AXI monitor (USER2) captures.
//
// The CPU reaches the shared axi4_test_slave through the Wishbone->AXI4 bridge
// in vex_cpu.v, which maps 0x4000_0000 onto the SmartConnect (the CPU issues --
// and the monitor taps -- the full 0x4000_00xx addresses). The EJTAG-AXI bridge
// (USER4) reaches the same slave through its own 0x0-based segment.
//
// Protocol (all on the shared slave, byte addresses off 0x4000_0000):
//   word31 (0x7C)  GO flag : host writes non-zero via EJTAG to start, 0 to
//                            stop. CPU only polls (reads) it.
//   word16 (0x40)  DATA    : CPU writes PATTERN  here while GO != 0
//   word17 (0x44)  DATA2   : CPU writes PATTERN2 here while GO != 0
//
// Words 0..15 are left untouched so the EJTAG host tests (which use them) are
// unaffected. While GO == 0 the CPU issues only reads, which never assert the
// aw_hs / any_err events the monitor tests arm on.

#include <stdint.h>

#define SLAVE_BASE  0x40000000u
#define GO_WORD     31u   /* 0x7C */
#define DATA_WORD   16u   /* 0x40 */
#define DATA2_WORD  17u   /* 0x44 */

#define PATTERN     0xCAFEF00Du
#define PATTERN2    0x1234ABCDu

int main(void)
{
    volatile uint32_t *slave = (volatile uint32_t *)SLAVE_BASE;

    for (;;) {
        /* Poll the go flag (read-only traffic while idle). */
        if (slave[GO_WORD] != 0u) {
            slave[DATA_WORD]  = PATTERN;
            slave[DATA2_WORD] = PATTERN2;
        }
    }

    return 0;
}
