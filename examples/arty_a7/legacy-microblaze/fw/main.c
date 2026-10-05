// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// MicroBlaze firmware for the Arty A7 fpgacapZero reference design.
//
// The CPU's M_AXI_DP master shares one SmartConnect bus with the EJTAG-AXI
// bridge; both reach the same axi4_test_slave, which the AXI monitor (USER2)
// taps.  This firmware gives the monitor real, repeatable CPU bus traffic --
// but only on demand, so the CPU stays write-quiet during the existing EJTAG /
// monitor hardware tests.
//
// Protocol (all on the shared slave, byte addresses off 0x4000_0000):
//   word31 (0x7C)  GO flag     : host writes non-zero via EJTAG to start,
//                                0 to stop.  CPU only polls (reads) it.
//   word16 (0x40)  DATA        : CPU writes PATTERN  here while GO != 0
//   word17 (0x44)  DATA2       : CPU writes PATTERN2 here while GO != 0
//
// Words 0..15 are left untouched so the EJTAG host tests (which use them) are
// unaffected.  While GO == 0 the CPU issues only reads, which never assert the
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
