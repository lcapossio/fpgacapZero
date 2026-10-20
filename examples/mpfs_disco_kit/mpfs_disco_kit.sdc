# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

create_clock -name REF_CLK_50MHz -period 20.000 [get_ports {REF_CLK_50MHz}]

# JTAG TCK, constrained at 6 MHz as in Microchip's Discovery Kit designs.
create_clock -name TCK -period 166.67 -waveform {0 83.33} [get_ports {TCK}]

# The fcapz cores cross between TCK and the sample clock through their own
# synchronizers.
set_clock_groups -name fcapz_async -asynchronous \
    -group [get_clocks {REF_CLK_50MHz}] -group [get_clocks {TCK}]
