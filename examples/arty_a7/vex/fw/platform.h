/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Bare-metal platform layer for the Arty A7 VexRiscv Dhrystone firmware.
 *
 * Memory map (decoded in examples/arty_a7/vex/vex_cpu.v):
 *   0x0000_0000  64 KB on-chip BRAM   code + data + stack (firmware image)
 *   0x1000_0000  cycle counter        RO free-running 32-bit, +1 per CPU clock
 *   0x4000_0000  shared AXI slave      test slave on M_BUS (monitored + host)
 *
 * The firmware never uses the C standard library (compiled -nostdlib): all the
 * string/mem helpers Dhrystone needs are provided in support.c.
 */

#ifndef FCAPZ_VEX_PLATFORM_H
#define FCAPZ_VEX_PLATFORM_H

#include <stdint.h>
#include <stddef.h>

/* ---- CPU / clock ------------------------------------------------------- */
/* Must match the AXI-subsystem clock in arty_a7_vex_top.v (100 MHz board
 * oscillator buffered directly). Published to the host so DMIPS is computed
 * from a self-describing capture, not a hard-coded constant on both sides. */
#define CPU_CLOCK_HZ   100000000u

/* ---- MMIO cycle counter ------------------------------------------------ */
#define CYCLE_CTR_ADDR 0x10000000u

/* ---- Shared AXI test slave (32 words, word = (addr>>2) % 32) ------------
 * Words 0..15 belong to the EJTAG host tests and are never touched here, so
 * the CPU stays quiet on those; results live in words 16..19, the go flag in
 * word 31 -- the same split the MicroBlaze firmware uses. */
#define SLAVE_BASE     0x40000000u
#define GO_WORD        31u   /* 0x7C  host writes non-zero via EJTAG to start */
#define DONE_WORD      16u   /* 0x40  firmware writes DONE_MAGIC when finished */
#define RUNS_WORD      17u   /* 0x44  Dhrystone Number_Of_Runs                */
#define CYCLES_WORD    18u   /* 0x48  measured cycle delta                    */
#define HZ_WORD        19u   /* 0x4C  CPU_CLOCK_HZ (self-describing)          */
#define CHECK_WORD     20u   /* 0x50  checksum of Dhrystone globals           */

/* Sentinel the host polls DONE_WORD for. Written last, after the numeric
 * results, so a host read that sees it can trust RUNS/CYCLES are already set. */
#define DONE_MAGIC     0xD05ED09Eu

static inline uint32_t plat_cycles(void)
{
    return *(volatile uint32_t *)CYCLE_CTR_ADDR;
}

static inline uint32_t plat_go(void)
{
    return ((volatile uint32_t *)SLAVE_BASE)[GO_WORD];
}

static inline void plat_slave_write(unsigned word, uint32_t value)
{
    ((volatile uint32_t *)SLAVE_BASE)[word] = value;
}

/* Publish a completed run. DONE_MAGIC is written last (release order) so the
 * host never reads a half-updated result set. The checksum makes the whole
 * Dhrystone computation observable, so the optimiser cannot delete the
 * measured loop. */
static inline void plat_publish(uint32_t runs, uint32_t cycles, uint32_t checksum)
{
    plat_slave_write(RUNS_WORD, runs);
    plat_slave_write(CYCLES_WORD, cycles);
    plat_slave_write(HZ_WORD, CPU_CLOCK_HZ);
    plat_slave_write(CHECK_WORD, checksum);
    plat_slave_write(DONE_WORD, DONE_MAGIC);
}

/* Freestanding string/mem helpers (support.c) -- Dhrystone uses these, and the
 * compiler emits memcpy for its struct copies. Provided under the standard
 * names so both resolve with -nostdlib (no libc is linked). */
void *memcpy(void *dst, const void *src, size_t n);
char *strcpy(char *dst, const char *src);
int   strcmp(const char *a, const char *b);

#endif /* FCAPZ_VEX_PLATFORM_H */
