-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ela_polarfire is
    generic (
        SAMPLE_W       : positive := 8;
        DEPTH          : positive := 1024;
        TRIG_STAGES    : positive := 1;
        STOR_QUAL      : natural := 0;
        INPUT_PIPE     : natural := 0;
        NUM_CHANNELS   : positive := 1;
        TIMESTAMP_W    : natural := 0;
        STARTUP_ARM    : natural := 0;
        BURST_W        : positive := 256;
        IR_USER1       : std_logic_vector(7 downto 0) := x"10";
        IR_USER2       : std_logic_vector(7 downto 0) := x"11";
        EIO_EN         : natural := 0;
        EIO_IN_W       : positive := 1;
        EIO_OUT_W      : positive := 1;
        REL_COMPARE    : natural := 0;
        DUAL_COMPARE   : natural := 1;
        USER1_DATA_EN  : natural := 1
    );
    port (
        sample_clk    : in  std_logic;
        sample_rst    : in  std_logic;
        probe_in      : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0);
        eio_probe_in  : in  std_logic_vector(EIO_IN_W - 1 downto 0);
        eio_probe_out : out std_logic_vector(EIO_OUT_W - 1 downto 0)
    );
end entity fcapz_ela_polarfire;

architecture rtl of fcapz_ela_polarfire is
    component fcapz_ela_polarfire_v is
        generic (
            SAMPLE_W       : positive;
            DEPTH          : positive;
            TRIG_STAGES    : positive;
            STOR_QUAL      : natural;
            INPUT_PIPE     : natural;
            NUM_CHANNELS   : positive;
            TIMESTAMP_W    : natural;
            STARTUP_ARM    : natural;
            BURST_W        : positive;
            IR_USER1       : std_logic_vector(7 downto 0);
            IR_USER2       : std_logic_vector(7 downto 0);
            EIO_EN         : natural;
            EIO_IN_W       : positive;
            EIO_OUT_W      : positive;
            REL_COMPARE    : natural;
            DUAL_COMPARE   : natural;
            USER1_DATA_EN  : natural
        );
        port (
            sample_clk    : in  std_logic;
            sample_rst    : in  std_logic;
            probe_in      : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0);
            eio_probe_in  : in  std_logic_vector(EIO_IN_W - 1 downto 0);
            eio_probe_out : out std_logic_vector(EIO_OUT_W - 1 downto 0)
        );
    end component;
begin
    u_impl : fcapz_ela_polarfire_v
        generic map (
            SAMPLE_W => SAMPLE_W, DEPTH => DEPTH,
            TRIG_STAGES => TRIG_STAGES, STOR_QUAL => STOR_QUAL,
            INPUT_PIPE => INPUT_PIPE, NUM_CHANNELS => NUM_CHANNELS,
            TIMESTAMP_W => TIMESTAMP_W, STARTUP_ARM => STARTUP_ARM,
            BURST_W => BURST_W, IR_USER1 => IR_USER1, IR_USER2 => IR_USER2,
            EIO_EN => EIO_EN, EIO_IN_W => EIO_IN_W, EIO_OUT_W => EIO_OUT_W,
            REL_COMPARE => REL_COMPARE, DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN
        )
        port map (
            sample_clk    => sample_clk,
            sample_rst    => sample_rst,
            probe_in      => probe_in,
            eio_probe_in  => eio_probe_in,
            eio_probe_out => eio_probe_out
        );
end architecture rtl;
