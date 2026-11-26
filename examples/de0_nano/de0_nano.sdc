# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
# Copyright (c) 2026 Khush Patil
create_clock -name clk50 -period 20 [get_ports CLOCK_50]
derive_clock_uncertainty
