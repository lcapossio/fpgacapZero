-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Simulation stub for Intel/Altera sld_virtual_jtag. The outputs have no
-- driver, so a testbench can drive them directly.

library ieee;
use ieee.std_logic_1164.all;

entity sld_virtual_jtag is
    generic (
        sld_auto_instance_index : string := "NO";
        sld_instance_index      : integer := 1;
        sld_ir_width            : integer := 1
    );
    port (
        tck               : out std_logic;
        tdi               : out std_logic;
        tdo               : in  std_logic;
        virtual_state_cdr : out std_logic;
        virtual_state_sdr : out std_logic;
        virtual_state_udr : out std_logic;
        ir_in             : out std_logic_vector(sld_ir_width - 1 downto 0);
        ir_out            : in  std_logic_vector(sld_ir_width - 1 downto 0)
    );
end entity sld_virtual_jtag;

architecture sim of sld_virtual_jtag is
begin
end architecture sim;
