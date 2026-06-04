-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-- Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_gowin is
    port (
        sysclk    : in  std_logic;
        activity  : out std_logic;
        tdi       : out std_logic;
        tdo       : in  std_logic_vector(1 downto 0);
        capture   : out std_logic_vector(1 downto 0);
        shift_in  : out std_logic_vector(1 downto 0);
        shift_out : out std_logic_vector(1 downto 0);
        update    : out std_logic_vector(1 downto 0);
        sel       : out std_logic_vector(1 downto 0);

        tms_pad_i : in  std_logic;
        tck_pad_i : in  std_logic;
        tdi_pad_i : in  std_logic;
        tdo_pad_o : out std_logic
    );
end entity jtag_tap_gowin;

architecture rtl of jtag_tap_gowin is
    component jtag_tap_gowin_v is
        port (
            sysclk    : in  std_logic;
            activity  : out std_logic;
            tdi       : out std_logic;
            tdo       : in  std_logic_vector(1 downto 0);
            capture   : out std_logic_vector(1 downto 0);
            shift_in  : out std_logic_vector(1 downto 0);
            shift_out : out std_logic_vector(1 downto 0);
            update    : out std_logic_vector(1 downto 0);
            sel       : out std_logic_vector(1 downto 0);
            tms_pad_i : in  std_logic;
            tck_pad_i : in  std_logic;
            tdi_pad_i : in  std_logic;
            tdo_pad_o : out std_logic
        );
    end component;
begin
    u_impl : jtag_tap_gowin_v
        port map (
            sysclk    => sysclk,
            activity  => activity,
            tdi       => tdi,
            tdo       => tdo,
            capture   => capture,
            shift_in  => shift_in,
            shift_out => shift_out,
            update    => update,
            sel       => sel,
            tms_pad_i => tms_pad_i,
            tck_pad_i => tck_pad_i,
            tdi_pad_i => tdi_pad_i,
            tdo_pad_o => tdo_pad_o
        );
end architecture rtl;
