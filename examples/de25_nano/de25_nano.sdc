# SPDX-License-Identifier: Apache-2.0

create_clock -name clk_50mhz -period 20.000 [get_ports {CLOCK1_50}]

# The Intel virtual-JTAG instances provide their own TCK domains. The fcapz
# cores use explicit CDC between sample_clk and virtual-JTAG TCK.
derive_clock_uncertainty
