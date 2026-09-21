# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Efinity timing constraints for forgix_top (Trion T8F49).
#
# Verified with Efinity 2025.1, T8F49 / C2, optimization_level TIMING_3,
# placer seed 5:
#   Logic elements   2174 / 7384  (29.4%)
#   Memory blocks       2 / 24    (EFX_RAM_5K, not LUT memory)
#   clk_in           51.8 MHz     (meets the 50 MHz constraint)
#   tap_tck          36.6 MHz     (against its 25 MHz need)
#
# The seed matters: the critical path is inside fcapz_ela (post_count ->
# wr_ptr enable), and across seeds 1/3/5/9/12 clk_in lands between 49.4 and
# 51.8 MHz -- so some seeds miss 50 MHz by under 1%.  If a build fails timing
# by a tenth of a nanosecond, try another seed before changing anything.
#
# Set the clk_in period to your board's actual oscillator, and keep it in step
# with the CLK_HZ parameter of forgix_top.

create_clock -period 20.0 -name clk_in [get_ports clk_in]

# tap_tck is generated inside fcapz_tap_bridge -- a registered output, so it is
# glitch-free, but it is still a fabric clock, and it drives roughly 940 flops
# plus both ports of the sample RAM.  Efinity does not infer a clock for it:
# without this constraint that whole domain is placed and routed but never
# timed, and the timing report silently covers only clk_in.  The bridge toggles
# it at most once every other clk_in edge, so it is clk_in / 2.
create_generated_clock -name tap_tck -source [get_ports {clk_in}] -divide_by 2 \
    [get_nets {u_fcapz/tap_tck}]

# Nothing crosses between the two domains as an ordinary same-edge synchronous
# transfer:
#
#   * The TAP strobes (tdi, capture, shift, update, sel) are always registered
#     a full clk_in cycle before the tck edge that samples them -- the FSM
#     never changes them on the same edge that raises tck.
#   * fcapz_ela passes capture metadata from the sample domain to the JTAG
#     domain through a toggle handshake, so that bus is only read after the
#     toggle has crossed two synchroniser stages and is stable for many cycles.
#   * jtag_rst_sync is released in the sample_clk domain, which it has to be:
#     tap_tck is stopped until the host starts a scan, so a synchroniser
#     clocked by tap_tck would still be asserting through the first scan's
#     CAPTURE and first SHIFT.  tap_tck is idle when the release happens.
#
# With a hard TAP the two clocks are genuinely unrelated and the analyser
# ignores all of this.  Here tap_tck is derived from clk_in, so without the
# declaration below it is timed as a phase-related divide and reports hold
# violations on the handshake bus that do not exist in the design.
#
# The cost of the blunt form is that clk_in -> tap_tck setup stops being
# checked.  It had ~6.4 ns of slack on a 20 ns constraint when it was timed,
# so the margin is real -- but a future change that eroded it would not be
# caught here.
set_clock_groups -asynchronous -group {clk_in} -group {tap_tck}
