-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- fpgacapZero EIO wrapper for Lattice ECP5 (VHDL).
--
-- Thin VHDL wrapper over the Verilog fcapz_eio_ecp5 module.
-- Instantiate this entity in VHDL designs; the underlying Verilog
-- source files must still be included in the project.
--
-- Usage:
--   u_eio : entity work.fcapz_eio_ecp5
--       generic map (IN_W => 32, OUT_W => 32)
--       port map (probe_in => signals_in, probe_out => signals_out);

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_eio_ecp5 is
    generic (
        IN_W  : positive := 32;
        OUT_W : positive := 32;
        CHAIN : positive := 3
    );
    port (
        probe_in  : in  std_logic_vector(IN_W - 1 downto 0);
        probe_out : out std_logic_vector(OUT_W - 1 downto 0)
    );
end entity fcapz_eio_ecp5;

architecture rtl of fcapz_eio_ecp5 is

    component fcapz_eio_ecp5_v is
        generic (
            IN_W  : positive;
            OUT_W : positive;
            CHAIN : positive
        );
        port (
            probe_in  : in  std_logic_vector(IN_W - 1 downto 0);
            probe_out : out std_logic_vector(OUT_W - 1 downto 0)
        );
    end component;

begin

    u_impl : fcapz_eio_ecp5_v
        generic map (
            IN_W  => IN_W,
            OUT_W => OUT_W,
            CHAIN => CHAIN
        )
        port map (
            probe_in  => probe_in,
            probe_out => probe_out
        );

end architecture rtl;
