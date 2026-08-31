# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
#
# Generate the SmartConnect block design used by the Arty A7 VexRiscv reference
# build. It is the MicroBlaze design's shared-bus crossbar (create_mb_bd.tcl)
# with the proprietary CPU/LMB/MDM removed: just a 2-slave -> 1-master
# SmartConnect that merges the external VexRiscv master (M_CPU) and the
# EJTAG-AXI bridge master (M_EJTAG) onto one monitored AXI4 bus (M_BUS).
#
# Contents of BD "vex_bus":
#   smartconnect_0   2 slaves -> 1 master crossbar
#       S00 = external slave  M_CPU    (VexRiscv AXI4 master, wired in vex_sys)
#       S01 = external slave  M_EJTAG  (EJTAG-AXI bridge master, wired at top)
#       M00 = external master M_BUS    (drives the test slave + AXI-mon tap)
#
# External ports: aclk (100 MHz), aresetn (active-low). M_BUS is mapped so the
# CPU sees the shared slave at 0x4000_0000 (same as MicroBlaze), while the
# EJTAG master reaches the whole map (ERROR/HANG addresses still decode).

proc fcapz_build_vex_bd {{bd_name vex_bus}} {
    puts "fcapz: creating block design $bd_name (SmartConnect crossbar)"
    create_bd_design $bd_name

    set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smartconnect_0]
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $sc

    # ---- Clock / reset --------------------------------------------------
    create_bd_port -dir I -type clk -freq_hz 100000000 aclk
    create_bd_port -dir I -type rst aresetn
    set_property CONFIG.POLARITY ACTIVE_LOW [get_bd_ports aresetn]
    connect_bd_net [get_bd_ports aclk]    [get_bd_pins smartconnect_0/aclk]
    connect_bd_net [get_bd_ports aresetn] [get_bd_pins smartconnect_0/aresetn]

    # ---- Export the three bus interfaces --------------------------------
    catch {make_bd_intf_pins_external -name M_CPU \
        [get_bd_intf_pins smartconnect_0/S00_AXI]} e0
    puts "export M_CPU: $e0"
    catch {make_bd_intf_pins_external -name M_EJTAG \
        [get_bd_intf_pins smartconnect_0/S01_AXI]} e1
    puts "export M_EJTAG: $e1"
    catch {make_bd_intf_pins_external -name M_BUS \
        [get_bd_intf_pins smartconnect_0/M00_AXI]} e2
    puts "export M_BUS: $e2"

    # Tie the external clock to every exported interface so Vivado clocks them.
    set_property CONFIG.ASSOCIATED_BUSIF {M_CPU:M_EJTAG:M_BUS} \
        [get_bd_ports aclk]

    # ---- Address map ----------------------------------------------------
    # Mirror create_mb_bd.tcl: the CPU sees the shared slave at 0x4000_0000
    # (SmartConnect forwards the full address, so the monitor taps the CPU's
    # 0x4000_00xx writes), and the EJTAG bridge reaches the whole 4G map so the
    # test slave still decodes its ERROR/HANG addresses.
    set busseg [get_bd_addr_segs M_BUS/Reg]
    assign_bd_address -offset 0x40000000 -range 1G \
        -target_address_space [get_bd_addr_spaces M_CPU] $busseg
    assign_bd_address -offset 0x00000000 -range 4G \
        -target_address_space [get_bd_addr_spaces M_EJTAG] $busseg

    validate_bd_design -force
    puts "fcapz: block design $bd_name validated"
    return $bd_name
}

if {[info exists ::vex_autobuild] && $::vex_autobuild} {
    fcapz_build_vex_bd
}
