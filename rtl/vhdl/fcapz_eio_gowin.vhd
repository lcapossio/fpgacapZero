-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_eio_gowin is
    generic (
        IN_W  : positive := 32;
        OUT_W : positive := 32;
        CHAIN : positive := 1
    );
    port (
        probe_in  : in  std_logic_vector(IN_W - 1 downto 0);
        probe_out : out std_logic_vector(OUT_W - 1 downto 0)
    );
end entity fcapz_eio_gowin;

architecture rtl of fcapz_eio_gowin is
begin
    probe_out <= (others => '0');
end architecture rtl;
