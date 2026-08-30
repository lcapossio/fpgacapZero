# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

# ==============================================================
# Arty A7-100T  –  fpgacapZero MVP constraints
# Board: Digilent Arty A7-100T  (xc7a100tcsg324-1)
# ==============================================================

# ── System clock (100 MHz) ─────────────────────────────────────
set_property -dict {PACKAGE_PIN E3 IOSTANDARD LVCMOS33} [get_ports clk]
create_clock -period 10.000 -name board_clk [get_ports clk]

# ── Push-buttons (active-high) ─────────────────────────────────
set_property -dict {PACKAGE_PIN D9  IOSTANDARD LVCMOS33} [get_ports {btn[0]}]
set_property -dict {PACKAGE_PIN C9  IOSTANDARD LVCMOS33} [get_ports {btn[1]}]
set_property -dict {PACKAGE_PIN B9  IOSTANDARD LVCMOS33} [get_ports {btn[2]}]
set_property -dict {PACKAGE_PIN B8  IOSTANDARD LVCMOS33} [get_ports {btn[3]}]

# ── Discrete LEDs (LD4–LD7 on silk; Digilent calls them led[4]–[7] in sch) ──
# Must match Digilent Arty-A7-100-Master.xdc (Rev D / E). Older wrong pins
# (H17/K15/J13/N14) were not wired to these LEDs — EIO JTAG worked but nothing lit.
set_property -dict {PACKAGE_PIN H5  IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN J5  IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN T9  IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports {led[3]}]

# ── BSCANE2 TCK / CDC ──────────────────────────────────────────
# Every BSCANE2 (fcapz USER1/2/4 cores + the MicroBlaze MDM on USER3, inside
# the block design) shares the one physical JTAG TCK.  Declare a single clock
# on all of their TCK pins so the CDC false-path to the fabric is unambiguous.
create_clock -name tck_bscan -period 100.0 \
    [get_pins -of_objects [get_cells -hierarchical -filter {REF_NAME == BSCANE2}] \
              -filter {REF_PIN_NAME == TCK}]

set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks board_clk] \
    -group [get_clocks tck_bscan]
