-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity trig_compare is
    generic (
        W           : positive := 8;
        REL_COMPARE : integer := 0
    );
    port (
        probe      : in  std_logic_vector(W - 1 downto 0);
        probe_prev : in  std_logic_vector(W - 1 downto 0);
        value      : in  std_logic_vector(W - 1 downto 0);
        mask       : in  std_logic_vector(W - 1 downto 0);
        mode       : in  std_logic_vector(3 downto 0);
        hit        : out std_logic
    );
end entity trig_compare;

architecture rtl of trig_compare is
begin
    p_compare : process(all)
        variable mp        : std_logic_vector(W - 1 downto 0);
        variable mv        : std_logic_vector(W - 1 downto 0);
        variable mpp       : std_logic_vector(W - 1 downto 0);
        variable eq        : boolean;
        variable lt        : boolean;
        variable gt        : boolean;
        variable leq       : boolean;
        variable geq       : boolean;
        variable zero_prev : boolean;
        variable zero_cur  : boolean;
        variable changed   : boolean;
    begin
        mp := probe and mask;
        mv := value and mask;
        mpp := probe_prev and mask;

        eq := mp = mv;
        lt := REL_COMPARE /= 0 and unsigned(mp) < unsigned(mv);
        gt := REL_COMPARE /= 0 and unsigned(mp) > unsigned(mv);
        leq := REL_COMPARE /= 0 and (lt or eq);
        geq := REL_COMPARE /= 0 and (gt or eq);
        zero_prev := mpp = std_logic_vector(to_unsigned(0, W));
        zero_cur := mp = std_logic_vector(to_unsigned(0, W));
        changed := mp /= mpp;

        case mode is
            when "0000" => hit <= '1' when eq else '0';
            when "0001" => hit <= '0' when eq else '1';
            when "0010" => hit <= '1' when lt else '0';
            when "0011" => hit <= '1' when gt else '0';
            when "0100" => hit <= '1' when leq else '0';
            when "0101" => hit <= '1' when geq else '0';
            when "0110" => hit <= '1' when zero_prev and not zero_cur else '0';
            when "0111" => hit <= '1' when not zero_prev and zero_cur else '0';
            when "1000" => hit <= '1' when changed else '0';
            when others => hit <= '0';
        end case;
    end process;
end architecture rtl;
