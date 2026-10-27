-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Simulation stub for the Lattice ECP5 JTAGG primitive: a quiet, inactive
-- TAP whose outputs a cocotb bench can drive.

library ieee;
use ieee.std_logic_1164.all;

entity JTAGG is
    port (
        JTCK    : out std_logic := '0';
        JTDI    : out std_logic := '0';
        JTDO1   : in  std_logic;
        JTDO2   : in  std_logic;
        JSHIFT  : out std_logic := '0';
        JUPDATE : out std_logic := '0';
        JRSTN   : out std_logic := '1';
        JCE1    : out std_logic := '0';
        JCE2    : out std_logic := '0';
        JRTI1   : out std_logic := '0';
        JRTI2   : out std_logic := '0'
    );
end entity JTAGG;

architecture sim of JTAGG is
begin
end architecture sim;
