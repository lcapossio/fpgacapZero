-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

-- Mixed debug wrapper for Xilinx 7-series (BSCANE2):
-- multiple ELAs plus optional EIOs behind the core manager on one JTAG
-- chain. Only the TAP is vendor-specific; the rest is fcapz_debug_multi.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_debug_multi_xilinx7 is
    generic (
        NUM_ELAS         : natural := 2;
        EIO_EN           : natural := 1;
        NUM_EIOS         : natural := EIO_EN;
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
        CTRL_CHAIN       : positive := 1;  -- BSCANE2 USER chain
        REL_COMPARE      : natural := 0;
        DUAL_COMPARE     : natural := 1;
        USER1_DATA_EN    : natural := 1;
        TLR_RESET_EN     : natural := 0;
        EIO_IN_W         : positive := 1;
        EIO_OUT_W        : positive := 1;
        ELA_PORT_COUNT   : positive := fcapz_nonzero_width(NUM_ELAS);
        ELA_SAMPLE_WS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, SAMPLE_W);
        ELA_DEPTHS       : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, DEPTH);
        ELA_TRIG_STAGES  : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, TRIG_STAGES);
        ELA_STOR_QUALS   : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, STOR_QUAL);
        ELA_INPUT_PIPES  : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, INPUT_PIPE);
        ELA_NUM_CHANNELS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, NUM_CHANNELS);
        ELA_DECIM_ENS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, DECIM_EN);
        ELA_EXT_TRIG_ENS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, EXT_TRIG_EN);
        ELA_TIMESTAMP_WS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, TIMESTAMP_W);
        ELA_NUM_SEGMENTS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, NUM_SEGMENTS);
        ELA_PROBE_MUX_WS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, PROBE_MUX_W);
        ELA_STARTUP_ARMS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, STARTUP_ARM);
        ELA_DEFAULT_TRIG_EXTS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, DEFAULT_TRIG_EXT);
        ELA_REL_COMPARES      : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, REL_COMPARE);
        ELA_DUAL_COMPARES     : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, DUAL_COMPARE);
        ELA_USER1_DATA_ENS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := fcapz_repeat_u32(ELA_PORT_COUNT, USER1_DATA_EN);
        EIO_IN_WS        : std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * 32 - 1 downto 0) := fcapz_repeat_u32(fcapz_nonzero_width(NUM_EIOS), EIO_IN_W);
        EIO_OUT_WS       : std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * 32 - 1 downto 0) := fcapz_repeat_u32(fcapz_nonzero_width(NUM_EIOS), EIO_OUT_W)
    );
    port (
        ela_sample_clk  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_sample_rst  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_probe_in    : in  std_logic_vector(ELA_PORT_COUNT * fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W) - 1 downto 0);
        ela_trigger_in  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_trigger_out : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_armed_out   : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        eio_probe_in    : in  std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_IN_W - 1 downto 0);
        eio_probe_out   : out std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_OUT_W - 1 downto 0)
    );
end entity fcapz_debug_multi_xilinx7;

architecture rtl of fcapz_debug_multi_xilinx7 is
    signal tap_tck, tap_tdi, tap_tdo : std_logic;
    signal tap_capture, tap_shift, tap_update, tap_sel, tap_tlr : std_logic;
begin
    u_tap_ctrl : entity work.jtag_tap_xilinx7
        generic map (CHAIN => CTRL_CHAIN)
        port map (
            tck => tap_tck, tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture, shift => tap_shift,
            update => tap_update, sel => tap_sel,
            tlr => tap_tlr
        );

    u_multi : entity work.fcapz_debug_multi
        generic map (
            NUM_ELAS => NUM_ELAS,
            EIO_EN => EIO_EN,
            NUM_EIOS => NUM_EIOS,
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
            REL_COMPARE => REL_COMPARE,
            DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN,
            TLR_RESET_EN => TLR_RESET_EN,
            EIO_IN_W => EIO_IN_W,
            EIO_OUT_W => EIO_OUT_W,
            ELA_PORT_COUNT => ELA_PORT_COUNT,
            ELA_SAMPLE_WS => ELA_SAMPLE_WS,
            ELA_DEPTHS => ELA_DEPTHS,
            ELA_TRIG_STAGES => ELA_TRIG_STAGES,
            ELA_STOR_QUALS => ELA_STOR_QUALS,
            ELA_INPUT_PIPES => ELA_INPUT_PIPES,
            ELA_NUM_CHANNELS => ELA_NUM_CHANNELS,
            ELA_DECIM_ENS => ELA_DECIM_ENS,
            ELA_EXT_TRIG_ENS => ELA_EXT_TRIG_ENS,
            ELA_TIMESTAMP_WS => ELA_TIMESTAMP_WS,
            ELA_NUM_SEGMENTS => ELA_NUM_SEGMENTS,
            ELA_PROBE_MUX_WS => ELA_PROBE_MUX_WS,
            ELA_STARTUP_ARMS => ELA_STARTUP_ARMS,
            ELA_DEFAULT_TRIG_EXTS => ELA_DEFAULT_TRIG_EXTS,
            ELA_REL_COMPARES => ELA_REL_COMPARES,
            ELA_DUAL_COMPARES => ELA_DUAL_COMPARES,
            ELA_USER1_DATA_ENS => ELA_USER1_DATA_ENS,
            EIO_IN_WS => EIO_IN_WS,
            EIO_OUT_WS => EIO_OUT_WS
        )
        port map (
            tck => tap_tck, tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture, shift => tap_shift,
            update => tap_update, sel => tap_sel,
            tlr => tap_tlr,
            ela_sample_clk => ela_sample_clk,
            ela_sample_rst => ela_sample_rst,
            ela_probe_in => ela_probe_in,
            ela_trigger_in => ela_trigger_in,
            ela_trigger_out => ela_trigger_out,
            ela_armed_out => ela_armed_out,
            eio_probe_in => eio_probe_in,
            eio_probe_out => eio_probe_out
        );
end architecture rtl;
