-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_xilinxus is
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
end entity jtag_tap_xilinxus;

architecture rtl of jtag_tap_xilinxus is
begin
    u_tap : entity work.jtag_tap_xilinx7
        generic map (
            CHAIN => CHAIN
        )
        port map (
            tck     => tck,
            tdi     => tdi,
            tdo     => tdo,
            capture => capture,
            shift   => shift,
            update  => update,
            sel     => sel
        );
end architecture rtl;
