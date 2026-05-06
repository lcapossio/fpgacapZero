-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_dpram is
    generic (
        WIDTH : positive := 8;
        DEPTH : positive := 1024
    );
    port (
        clk_a  : in  std_logic;
        we_a   : in  std_logic;
        addr_a : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        din_a  : in  std_logic_vector(WIDTH - 1 downto 0);
        dout_a : out std_logic_vector(WIDTH - 1 downto 0);

        clk_b  : in  std_logic;
        addr_b : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        dout_b : out std_logic_vector(WIDTH - 1 downto 0)
    );
end entity fcapz_dpram;

architecture rtl of fcapz_dpram is
    type ram_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    signal ram : ram_t := (others => (others => '0'));
    signal dout_a_i : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');
    signal dout_b_i : std_logic_vector(WIDTH - 1 downto 0) := (others => '0');

    attribute ram_style : string;
    attribute ram_style of ram : signal is "block";
begin
    dout_a <= dout_a_i;
    dout_b <= dout_b_i;

    p_a : process(clk_a)
    begin
        if rising_edge(clk_a) then
            if we_a = '1' then
                ram(to_integer(unsigned(addr_a))) <= din_a;
            end if;
            dout_a_i <= ram(to_integer(unsigned(addr_a)));
        end if;
    end process;

    p_b : process(clk_b)
    begin
        if rising_edge(clk_b) then
            dout_b_i <= ram(to_integer(unsigned(addr_b)));
        end if;
    end process;
end architecture rtl;
