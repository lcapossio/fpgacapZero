-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_xilinx7 is
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
end entity jtag_tap_xilinx7;

architecture rtl of jtag_tap_xilinx7 is
    component BSCANE2 is
        generic (
            JTAG_CHAIN : integer := 1
        );
        port (
            TCK     : out std_logic;
            TDI     : out std_logic;
            TDO     : in  std_logic;
            CAPTURE : out std_logic;
            SHIFT   : out std_logic;
            UPDATE  : out std_logic;
            SEL     : out std_logic;
            DRCK    : out std_logic;
            RUNTEST : out std_logic;
            RESET   : out std_logic
        );
    end component;

    signal drck_unused    : std_logic;
    signal runtest_unused : std_logic;
    signal reset_unused   : std_logic;
begin
    u_bscan : BSCANE2
        generic map (
            JTAG_CHAIN => CHAIN
        )
        port map (
            TCK     => tck,
            TDI     => tdi,
            TDO     => tdo,
            CAPTURE => capture,
            SHIFT   => shift,
            UPDATE  => update,
            SEL     => sel,
            DRCK    => drck_unused,
            RUNTEST => runtest_unused,
            RESET   => reset_unused
        );
end architecture rtl;
