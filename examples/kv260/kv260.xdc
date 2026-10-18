# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Kria KV260 reference design constraints.  The design has no PL I/O: its
# only clock, pl_clk0, comes from the PS and is constrained by the PS IP.

create_clock -name tck_bscan -period 100.0 \
    [get_pins -of_objects [get_cells -hierarchical -filter {REF_NAME == BSCANE2}] \
              -filter {REF_PIN_NAME == TCK}]

set_clock_groups -asynchronous \
    -group [get_clocks clk_pl_0] \
    -group [get_clocks tck_bscan]

set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
