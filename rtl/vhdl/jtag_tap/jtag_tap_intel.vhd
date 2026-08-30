-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_intel is
    generic (
        CHAIN : positive := 1
    );
    port (
        tck     : out std_logic;
        tdi     : out std_logic;
        tdo     : in  std_logic;
        capture : out std_logic;
        shift   : out std_logic;
        update  : out std_logic;
        sel     : out std_logic
    );
end entity jtag_tap_intel;

architecture rtl of jtag_tap_intel is
    component sld_virtual_jtag is
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
            ir_in             : out std_logic_vector(0 downto 0);
            ir_out            : in  std_logic_vector(0 downto 0)
        );
    end component;

    signal ir_in_unused : std_logic_vector(0 downto 0);
begin
    u_vjtag : sld_virtual_jtag
        generic map (
            sld_auto_instance_index => "NO",
            sld_instance_index      => CHAIN,
            sld_ir_width            => 1
        )
        port map (
            tck               => tck,
            tdi               => tdi,
            tdo               => tdo,
            virtual_state_cdr => capture,
            virtual_state_sdr => shift,
            virtual_state_udr => update,
            ir_in             => ir_in_unused,
            ir_out            => "0"
        );

    sel <= '1';
end architecture rtl;
