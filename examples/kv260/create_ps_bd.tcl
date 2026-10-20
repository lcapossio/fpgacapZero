# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Minimal KV260 PS block design: the Zynq UltraScale+ PS with the board
# preset, exporting only pl_clk0.  No AXI ports, no interrupts, and no
# pl_resetn0 (see kv260_top.v for why the PL uses its own power-on reset).
#
# Sourced by build_kv260.tcl after the project is created:
#   fcapz_create_ps_bd kv260_ps

proc fcapz_create_ps_bd {bd_name} {
    create_bd_design $bd_name

    set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ps]
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
        -config {apply_board_preset 1} $ps

    # The board preset enables the PL-side AXI masters; this design drives
    # nothing from the PS, so turn them off along with the interrupt input.
    # PL0_REF_CTRL only sets the timing constraint: when the bitstream is
    # loaded over JTAG the clock runs at whatever the boot firmware set.
    # 200 MHz bounds every rate the stock KV260 firmware is known to use.
    set_property -dict [list \
        CONFIG.PSU__FPGA_PL0_ENABLE {1} \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {200} \
        CONFIG.PSU__USE__M_AXI_GP0 {0} \
        CONFIG.PSU__USE__M_AXI_GP1 {0} \
        CONFIG.PSU__USE__M_AXI_GP2 {0} \
        CONFIG.PSU__USE__S_AXI_GP0 {0} \
        CONFIG.PSU__USE__IRQ0 {0} \
    ] $ps

    create_bd_port -dir O -type clk pl_clk0
    connect_bd_net [get_bd_pins zynq_ps/pl_clk0] [get_bd_ports pl_clk0]

    validate_bd_design
    save_bd_design
}
