// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// VexRiscv firmware for the DE25-Nano fpgacapZero reference design.
//
// The open-source VexRiscv replaces the RTL axi4_traffic_gen as the master on
// the monitored AXI bus: the AXI monitor (instance 5) taps a mux that shows the
// EJTAG-AXI bridge while the host drives it and, otherwise, this CPU's traffic.
// So the monitor captures *real CPU bus traffic* the same way the Arty A7
// VexRiscv variant does -- but here the CPU drives its own dedicated
// axi4_test_slave, independent of the EJTAG-AXI bridge's slave.
//
// Because that slave is not reachable from the host (no shared bus / no GO
// flag), the firmware is free-running rather than host-gated: it continuously
// issues a clean write/write/read burst so the monitor always has live traffic
// to trigger on (aw_hs / w_hs / b_hs / ar_hs / r_hs) with no host present. It
// only ever touches a clean, in-range address, so it can never forge an
// error response -- the monitor's any_err trigger stays a host-only stimulus.
//
// Protocol (CPU's own slave, byte addresses off 0x4000_0000, 16-word slave):
//   word0 (0x00)  DATA   : PATTERN
//   word1 (0x04)  DATA2  : PATTERN2
//   word0 read-back keeps the read channels live for the monitor.

#include <stdint.h>

#define SLAVE_BASE  0x40000000u
#define DATA_WORD   0u   /* 0x00 */
#define DATA2_WORD  1u   /* 0x04 */

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
