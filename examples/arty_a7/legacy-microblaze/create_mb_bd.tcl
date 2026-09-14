# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Generate the MicroBlaze block design used by the Arty A7 reference build so
# the AXI monitor has real CPU-generated bus traffic to capture.
#
# Built entirely by hand (no apply_bd_automation: the MicroBlaze block-
# automation rule fails headless with nsMap/pcMap errors).  Contents of BD
# "mb_sys":
#   microblaze_0     minimal soft CPU (no cache, JTAG debug, M_AXI_DP master)
#   dlmb/ilmb_v10    local-memory buses
#   d/ilmb_cntlr     LMB->BRAM controllers
#   lmb_bram         32 KB dual-port BRAM (firmware lives here)
#   mdm_1            MicroBlaze Debug Module pinned to BSCAN USER3
#                    (USER1=debug-multi, USER2=axi-mon, USER4=ejtag-axi)
#   rst_ps           proc_sys_reset
#   smartconnect_0   2 slaves -> 1 master crossbar
#       S00 = microblaze M_AXI_DP
#       S01 = external slave  M_EJTAG  (EJTAG-AXI bridge master, wired at top)
#       M00 = external master M_BUS    (drives the test slave + AXI-mon tap)
#
# Exposes external ports: Clk (100 MHz), reset (active-high), plus interfaces
# M_EJTAG (slave) and M_BUS (master).  M_BUS is mapped full-range so the test
# slave still decodes ERROR/HANG addresses exactly as before.

proc _bd_conn {a b} {
    # connect two scalar pins, reporting instead of aborting on a name miss
    if {[catch {connect_bd_net [get_bd_pins $a] [get_bd_pins $b]} e]} {
        puts "  CONN-FAIL net $a <-> $b : $e"
    }
}
proc _bd_iconn {a b} {
    if {[catch {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]} e]} {
        puts "  CONN-FAIL intf $a <-> $b : $e"
    }
}

proc fcapz_build_mb_bd {{bd_name mb_sys}} {
    puts "fcapz: creating block design $bd_name (manual)"
    create_bd_design $bd_name

    # ---- Cells ----------------------------------------------------------
    set mb  [create_bd_cell -type ip -vlnv xilinx.com:ip:microblaze microblaze_0]
    set_property -dict [list \
        CONFIG.C_USE_ICACHE {0} CONFIG.C_USE_DCACHE {0} \
        CONFIG.C_DEBUG_ENABLED {1} CONFIG.C_AREA_OPTIMIZED {1} \
        CONFIG.C_D_AXI {1} CONFIG.C_ENDIANNESS {1} \
        CONFIG.C_USE_BARREL {0} CONFIG.C_USE_DIV {0} \
        CONFIG.C_USE_HW_MUL {0} CONFIG.C_USE_FPU {0} \
        CONFIG.C_USE_MSR_INSTR {0} CONFIG.C_USE_PCMP_INSTR {0} \
        CONFIG.C_NUMBER_OF_PC_BRK {1} CONFIG.C_NUMBER_OF_RD_ADDR_BRK {0} \
        CONFIG.C_NUMBER_OF_WR_ADDR_BRK {0} \
    ] $mb

    create_bd_cell -type ip -vlnv xilinx.com:ip:lmb_v10 dlmb_v10
    create_bd_cell -type ip -vlnv xilinx.com:ip:lmb_v10 ilmb_v10
    create_bd_cell -type ip -vlnv xilinx.com:ip:lmb_bram_if_cntlr dlmb_cntlr
    create_bd_cell -type ip -vlnv xilinx.com:ip:lmb_bram_if_cntlr ilmb_cntlr
    set bram [create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen lmb_bram]
    set_property -dict [list \
        CONFIG.Memory_Type {True_Dual_Port_RAM} \
        CONFIG.use_bram_block {BRAM_Controller} \
        CONFIG.EN_SAFETY_CKT {false} \
    ] $bram

    set mdm [create_bd_cell -type ip -vlnv xilinx.com:ip:mdm mdm_1]
    set_property CONFIG.C_JTAG_CHAIN {3} $mdm

    create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ps
    set vcc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant vcc]
    set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $vcc

    set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smartconnect_0]
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $sc

    # ---- External ports -------------------------------------------------
    create_bd_port -dir I -type clk -freq_hz 100000000 Clk
    create_bd_port -dir I -type rst reset
    set_property CONFIG.POLARITY ACTIVE_HIGH [get_bd_ports reset]

    # ---- Interface connections ------------------------------------------
    _bd_iconn microblaze_0/DLMB      dlmb_v10/LMB_M
    _bd_iconn microblaze_0/ILMB      ilmb_v10/LMB_M
    _bd_iconn dlmb_v10/LMB_Sl_0      dlmb_cntlr/SLMB
    _bd_iconn ilmb_v10/LMB_Sl_0      ilmb_cntlr/SLMB
    _bd_iconn dlmb_cntlr/BRAM_PORT   lmb_bram/BRAM_PORTA
    _bd_iconn ilmb_cntlr/BRAM_PORT   lmb_bram/BRAM_PORTB
    _bd_iconn microblaze_0/DEBUG     mdm_1/MBDEBUG_0
    _bd_iconn microblaze_0/M_AXI_DP  smartconnect_0/S00_AXI

    # ---- Clock / reset nets ---------------------------------------------
    foreach p {microblaze_0/Clk dlmb_v10/LMB_Clk ilmb_v10/LMB_Clk \
               dlmb_cntlr/LMB_Clk ilmb_cntlr/LMB_Clk \
               rst_ps/slowest_sync_clk smartconnect_0/aclk} {
        _bd_conn Clk $p
    }
    _bd_conn reset rst_ps/ext_reset_in
    foreach p {dlmb_v10/SYS_Rst ilmb_v10/SYS_Rst dlmb_cntlr/LMB_Rst ilmb_cntlr/LMB_Rst} {
        _bd_conn rst_ps/bus_struct_reset $p
    }
    _bd_conn rst_ps/mb_reset             microblaze_0/Reset
    _bd_conn rst_ps/interconnect_aresetn smartconnect_0/aresetn
    _bd_conn mdm_1/Debug_SYS_Rst         rst_ps/mb_debug_sys_rst
    _bd_conn vcc/dout                    rst_ps/dcm_locked

    # ---- Export the two shared-bus interfaces ---------------------------
    catch {make_bd_intf_pins_external -name M_EJTAG [get_bd_intf_pins smartconnect_0/S01_AXI]} e1
    puts "export M_EJTAG: $e1"
    catch {make_bd_intf_pins_external -name M_BUS   [get_bd_intf_pins smartconnect_0/M00_AXI]} e2
    puts "export M_BUS: $e2"

    # ---- Address map ----------------------------------------------------
    # CPU: 32 KB LMB at 0x0 (firmware), test-slave window at 0x4000_0000.
    assign_bd_address -offset 0x00000000 -range 32K \
        -target_address_space [get_bd_addr_spaces microblaze_0/Data] \
        [get_bd_addr_segs dlmb_cntlr/SLMB/Mem]
    assign_bd_address -offset 0x00000000 -range 32K \
        -target_address_space [get_bd_addr_spaces microblaze_0/Instruction] \
        [get_bd_addr_segs ilmb_cntlr/SLMB/Mem]
    set busseg [get_bd_addr_segs M_BUS/Reg]
    assign_bd_address -offset 0x40000000 -range 1G \
        -target_address_space [get_bd_addr_spaces microblaze_0/Data] $busseg
    # EJTAG bridge reaches the whole map so the slave still decodes its
    # ERROR/HANG addresses (0xFFFF_FFFC/F8) exactly as in the direct design.
    # (The 4G aperture overlapping the CPU's local LMB is a benign
    #  cross-master "same network" critical warning.)
    assign_bd_address -offset 0x00000000 -range 4G \
        -target_address_space [get_bd_addr_spaces M_EJTAG] $busseg

    validate_bd_design -force
    # proc_sys_reset ext_reset polarity is inferred from the connected port;
    # it must end up active-high to match the top-level rst_100.
    set ehi [get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells rst_ps]]
    puts "fcapz: rst_ps C_EXT_RESET_HIGH = $ehi (expect 1 = active-high)"
    if {$ehi ne "1"} {
        error "fcapz: proc_sys_reset external reset is not active-high ($ehi); MB reset polarity would be inverted"
    }
    puts "fcapz: block design $bd_name validated"
    return $bd_name
}

if {[info exists ::mb_autobuild] && $::mb_autobuild} {
    fcapz_build_mb_bd
}
