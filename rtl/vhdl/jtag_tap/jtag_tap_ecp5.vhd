-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_ecp5 is
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
end entity jtag_tap_ecp5;

architecture rtl of jtag_tap_ecp5 is
    component JTAGG is
        port (
            JTCK    : out std_logic;
            JTDI    : out std_logic;
            JTDO1   : in  std_logic;
            JTDO2   : in  std_logic;
            JSHIFT  : out std_logic;
            JUPDATE : out std_logic;
            JRSTN   : out std_logic;
            JCE1    : out std_logic;
            JCE2    : out std_logic;
            JRTI1   : out std_logic;
            JRTI2   : out std_logic
        );
    end component;

    signal jtck     : std_logic;
    signal jtdi     : std_logic;
    signal jshift   : std_logic;
    signal jupdate  : std_logic;
    signal jce1     : std_logic;
    signal jce2     : std_logic;
    signal sel_i    : std_logic;
    signal sel_prev : std_logic := '0';
    signal jtdo1_i : std_logic;
    signal jtdo2_i : std_logic;
    signal jrstn_unused : std_logic;
    signal jrti1_unused : std_logic;
    signal jrti2_unused : std_logic;
begin
    jtdo1_i <= tdo when CHAIN = 1 else '0';
    jtdo2_i <= tdo when CHAIN = 2 else '0';

    u_jtagg : JTAGG
        port map (
            JTCK    => jtck,
            JTDI    => jtdi,
            JTDO1   => jtdo1_i,
            JTDO2   => jtdo2_i,
            JSHIFT  => jshift,
            JUPDATE => jupdate,
            JRSTN   => jrstn_unused,
            JCE1    => jce1,
            JCE2    => jce2,
            JRTI1   => jrti1_unused,
            JRTI2   => jrti2_unused
        );

    tck <= jtck;
    tdi <= jtdi;
    shift <= jshift;
    update <= jupdate;
    sel_i <= jce1 when CHAIN = 1 else jce2;
    sel <= sel_i;

    p_sel : process(jtck)
    begin
        if rising_edge(jtck) then
            sel_prev <= sel_i;
        end if;
    end process;

    capture <= sel_i and (not sel_prev) and (not jshift);
end architecture rtl;
