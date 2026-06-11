-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity dpram is
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
end entity dpram;

architecture rtl of dpram is
begin
    u_ram : entity work.fcapz_dpram
        generic map (
            WIDTH => WIDTH,
            DEPTH => DEPTH
        )
        port map (
            clk_a  => clk_a,
            we_a   => we_a,
            addr_a => addr_a,
            din_a  => din_a,
            dout_a => dout_a,
            clk_b  => clk_b,
            addr_b => addr_b,
            dout_b => dout_b
        );
end architecture rtl;
