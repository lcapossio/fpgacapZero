// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// VexRiscv firmware for the DE25-Nano fpgacapZero reference design.
//
// The open-source VexRiscv replaces the RTL axi4_traffic_gen as a master on
// the monitored AXI bus. The CPU and the EJTAG-AXI bridge are now merged by the
// vendor-neutral fcapz_axi_interconnect onto one shared axi4_test_slave (M_BUS),
// which the AXI monitor (instance 5) taps -- the same interconnect and
// shared-bus topology the Arty A7 VexRiscv variant uses. The host can therefore
// read back CPU writes over EJTAG-AXI, just like on the Arty.
//
// Unlike the Arty firmware, this stays free-running (not host-gated): it
// continuously issues a clean write/write/read burst so the monitor always has
// live CPU traffic to trigger on (aw_hs / w_hs / b_hs / ar_hs / r_hs) with no
// host present -- what makes the monitor demoable from the GUI. It only ever
// touches clean, in-range addresses, so it can never forge an error response;
// the monitor's any_err trigger stays a host-only stimulus.
//
// The CPU writes the shared slave's high words (16/17) so it never collides
// with words 0..15, which the host's EJTAG read/write tests use. The slave has
// 32 words (like the Arty build); addresses are byte offsets off 0x4000_0000:
//   word16 (0x40)  DATA   : PATTERN
//   word17 (0x44)  DATA2  : PATTERN2
//   word16 read-back keeps the read channels live for the monitor.

#include <stdint.h>

#define SLAVE_BASE  0x40000000u
#define DATA_WORD   16u  /* 0x40 */
#define DATA2_WORD  17u  /* 0x44 */

#define PATTERN     0xCAFEF00Du
#define PATTERN2    0x1234ABCDu

/* Cosmetic pacing between transaction bursts (~a few us at 50 MHz): dense
 * enough that an armed capture window shows back-to-back transfers, sparse
 * enough not to saturate the bus. Tuning only -- correctness is independent. */
#define PACING      200u

int main(void)
{
    volatile uint32_t *slave = (volatile uint32_t *)SLAVE_BASE;

    for (;;) {
        slave[DATA_WORD]  = PATTERN;    /* aw_hs / w_hs / b_hs */
        slave[DATA2_WORD] = PATTERN2;
        (void)slave[DATA_WORD];         /* ar_hs / r_hs */

        for (volatile uint32_t d = 0u; d < PACING; d++) {
            /* spin */
        }
    }

    return 0;
}
