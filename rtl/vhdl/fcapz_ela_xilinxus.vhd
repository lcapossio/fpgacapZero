-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_ela_xilinxus is
    generic (
        SAMPLE_W         : positive := 8;
        DEPTH            : positive := 1024;
        TRIG_STAGES      : positive := 1;
        STOR_QUAL        : natural := 0;
        INPUT_PIPE       : natural := 0;
        NUM_CHANNELS     : positive := 1;
        DECIM_EN         : natural := 0;
        EXT_TRIG_EN      : natural := 0;
        TIMESTAMP_W      : natural := 0;
        NUM_SEGMENTS     : positive := 1;
        PROBE_MUX_W      : natural := 0;
        STARTUP_ARM      : natural := 0;
        DEFAULT_TRIG_EXT : natural := 0;
        BURST_W          : positive := 256;
        BURST_EN         : natural := 1;
        SINGLE_CHAIN_BURST : natural := 1;
        CTRL_CHAIN       : positive := 1;
        DATA_CHAIN       : positive := 2;
        EIO_EN           : natural := 0;
        EIO_IN_W         : positive := 1;
        EIO_OUT_W        : positive := 1;
        REL_COMPARE      : natural := 0;
        DUAL_COMPARE     : natural := 1;
        USER1_DATA_EN    : natural := 1
    );
    port (
        sample_clk    : in  std_logic;
        sample_rst    : in  std_logic;
        probe_in      : in  std_logic_vector(fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W) - 1 downto 0);
        trigger_in    : in  std_logic;
        trigger_out   : out std_logic;
        armed_out     : out std_logic;
        eio_probe_in  : in  std_logic_vector(EIO_IN_W - 1 downto 0);
        eio_probe_out : out std_logic_vector(EIO_OUT_W - 1 downto 0)
    );
end entity fcapz_ela_xilinxus;

architecture rtl of fcapz_ela_xilinxus is
begin
    u_inner : entity work.fcapz_ela_xilinx7
        generic map (
            SAMPLE_W => SAMPLE_W,
            DEPTH => DEPTH,
            TRIG_STAGES => TRIG_STAGES,
            STOR_QUAL => STOR_QUAL,
            INPUT_PIPE => INPUT_PIPE,
            NUM_CHANNELS => NUM_CHANNELS,
            DECIM_EN => DECIM_EN,
            EXT_TRIG_EN => EXT_TRIG_EN,
            TIMESTAMP_W => TIMESTAMP_W,
            NUM_SEGMENTS => NUM_SEGMENTS,
            PROBE_MUX_W => PROBE_MUX_W,
            STARTUP_ARM => STARTUP_ARM,
            DEFAULT_TRIG_EXT => DEFAULT_TRIG_EXT,
            BURST_W => BURST_W,
            BURST_EN => BURST_EN,
            SINGLE_CHAIN_BURST => SINGLE_CHAIN_BURST,
            CTRL_CHAIN => CTRL_CHAIN,
            DATA_CHAIN => DATA_CHAIN,
            EIO_EN => EIO_EN,
            EIO_IN_W => EIO_IN_W,
            EIO_OUT_W => EIO_OUT_W,
            REL_COMPARE => REL_COMPARE,
            DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN
        )
        port map (
            sample_clk => sample_clk,
            sample_rst => sample_rst,
            probe_in => probe_in,
            trigger_in => trigger_in,
            trigger_out => trigger_out,
            armed_out => armed_out,
            eio_probe_in => eio_probe_in,
            eio_probe_out => eio_probe_out
        );
end architecture rtl;
