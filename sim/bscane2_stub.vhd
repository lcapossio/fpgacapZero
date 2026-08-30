-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity BSCANE2 is
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
end entity BSCANE2;

architecture sim of BSCANE2 is
begin
end architecture sim;
