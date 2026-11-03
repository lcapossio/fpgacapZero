-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Simulation stub for the Microchip PolarFire UJTAG primitive: a quiet,
-- inactive TAP whose outputs a cocotb bench can drive.

library ieee;
use ieee.std_logic_1164.all;

entity UJTAG is
    port (
        TCK    : in  std_logic;
        TMS    : in  std_logic;
        TDI    : in  std_logic;
        TRSTB  : in  std_logic;
        TDO    : out std_logic := '0';
        UIREG  : out std_logic_vector(7 downto 0) := (others => '0');
        UTDI   : out std_logic := '0';
        UDRCK  : out std_logic := '0';
        UDRCAP : out std_logic := '0';
        UDRSH  : out std_logic := '0';
        UDRUPD : out std_logic := '0';
        URSTB  : out std_logic := '1';
        UTDO   : in  std_logic
    );
end entity UJTAG;

architecture sim of UJTAG is
begin
end architecture sim;
