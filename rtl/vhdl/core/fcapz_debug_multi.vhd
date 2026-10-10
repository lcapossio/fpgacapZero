-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

-- Vendor-free mixed debug wrapper: multiple ELAs plus optional EIOs behind
-- one JTAG chain, driven by any TAP wrapper with the standard
-- tck/tdi/tdo/capture/shift/update/sel interface (jtag_tap_<vendor>).
-- Slot order is ELA[0..NUM_ELAS-1], then EIO[0..NUM_EIOS-1].
--
-- Registers and burst readout share the one chain (jtag_pipe_iface). The
-- per-vendor fcapz_debug_multi_<vendor> wrappers only add the TAP instance.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_debug_multi is
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
        REL_COMPARE      : natural := 0;
        DUAL_COMPARE     : natural := 1;
        USER1_DATA_EN    : natural := 1;
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
        -- TAP signals (from the vendor's jtag_tap_<vendor>)
        tck     : in  std_logic;
        tdi     : in  std_logic;
        tdo     : out std_logic;
        capture : in  std_logic;
        shift   : in  std_logic;
        update  : in  std_logic;
        sel     : in  std_logic;

        ela_sample_clk  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_sample_rst  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_probe_in    : in  std_logic_vector(ELA_PORT_COUNT * fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W) - 1 downto 0);
        ela_trigger_in  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_trigger_out : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_armed_out   : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        eio_probe_in    : in  std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_IN_W - 1 downto 0);
        eio_probe_out   : out std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_OUT_W - 1 downto 0)
    );
end entity fcapz_debug_multi;

architecture rtl of fcapz_debug_multi is
    constant PTR_W           : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE       : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant BURST_SEG_DEPTH : positive := DEPTH / NUM_SEGMENTS;

    signal debug_arst : std_logic;
    signal jtag_rst_ctrl : std_logic;
    signal jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en : std_logic;
    signal jtag_addr : std_logic_vector(15 downto 0);
    signal jtag_wdata, jtag_rdata : std_logic_vector(31 downto 0);
    signal burst_rd_addr : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_active : std_logic;
    signal burst_rd_data : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start, burst_timestamp : std_logic;
    signal burst_start_ptr : std_logic_vector(PTR_W - 1 downto 0);
begin
    debug_arst <= '1' when ela_sample_rst /= (ela_sample_rst'range => '0') else '0';

    u_rst_sync_ctrl : entity work.reset_sync
        port map (clk => tck, arst => debug_arst, srst => jtag_rst_ctrl);

    u_pipe : entity work.jtag_pipe_iface
        generic map (
            SAMPLE_W => SAMPLE_W, TIMESTAMP_W => TIMESTAMP_W,
            DEPTH => DEPTH, BURST_W => BURST_W,
            SEG_DEPTH => BURST_SEG_DEPTH, BURST_PTR_ADDR => 16#002C#
        )
        port map (
            arst => jtag_rst_ctrl,
            tck => tck, tdi => tdi, tdo => tdo,
            capture => capture, shift_en => shift,
            update => update, sel => sel,
            reg_clk => jtag_clk, reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en, reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr, reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata,
            mem_addr => burst_rd_addr,
            mem_active => burst_rd_active,
            sample_data => burst_rd_data,
            timestamp_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_ptr_in => burst_start_ptr
        );

    u_core : entity work.fcapz_debug_multi_core
        generic map (
            NUM_ELAS => NUM_ELAS, EIO_EN => EIO_EN, NUM_EIOS => NUM_EIOS,
            SAMPLE_W => SAMPLE_W, DEPTH => DEPTH,
            TRIG_STAGES => TRIG_STAGES, STOR_QUAL => STOR_QUAL,
            INPUT_PIPE => INPUT_PIPE, NUM_CHANNELS => NUM_CHANNELS,
            DECIM_EN => DECIM_EN, EXT_TRIG_EN => EXT_TRIG_EN,
            TIMESTAMP_W => TIMESTAMP_W, NUM_SEGMENTS => NUM_SEGMENTS,
            PROBE_MUX_W => PROBE_MUX_W, STARTUP_ARM => STARTUP_ARM,
            DEFAULT_TRIG_EXT => DEFAULT_TRIG_EXT, BURST_EN => 1,
            REL_COMPARE => REL_COMPARE, DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN,
            EIO_IN_W => EIO_IN_W, EIO_OUT_W => EIO_OUT_W,
            ELA_PORT_COUNT => ELA_PORT_COUNT,
            ELA_SAMPLE_WS => ELA_SAMPLE_WS, ELA_DEPTHS => ELA_DEPTHS,
            ELA_TRIG_STAGES => ELA_TRIG_STAGES, ELA_STOR_QUALS => ELA_STOR_QUALS,
            ELA_INPUT_PIPES => ELA_INPUT_PIPES, ELA_NUM_CHANNELS => ELA_NUM_CHANNELS,
            ELA_DECIM_ENS => ELA_DECIM_ENS, ELA_EXT_TRIG_ENS => ELA_EXT_TRIG_ENS,
            ELA_TIMESTAMP_WS => ELA_TIMESTAMP_WS, ELA_NUM_SEGMENTS => ELA_NUM_SEGMENTS,
            ELA_PROBE_MUX_WS => ELA_PROBE_MUX_WS, ELA_STARTUP_ARMS => ELA_STARTUP_ARMS,
            ELA_DEFAULT_TRIG_EXTS => ELA_DEFAULT_TRIG_EXTS,
            ELA_REL_COMPARES => ELA_REL_COMPARES, ELA_DUAL_COMPARES => ELA_DUAL_COMPARES,
            ELA_USER1_DATA_ENS => ELA_USER1_DATA_ENS,
            EIO_IN_WS => EIO_IN_WS, EIO_OUT_WS => EIO_OUT_WS
        )
        port map (
            ela_sample_clk => ela_sample_clk, ela_sample_rst => ela_sample_rst,
            ela_probe_in => ela_probe_in, ela_trigger_in => ela_trigger_in,
            ela_trigger_out => ela_trigger_out, ela_armed_out => ela_armed_out,
            eio_probe_in => eio_probe_in, eio_probe_out => eio_probe_out,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst,
            jtag_wr_en => jtag_wr_en, jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            burst_rd_addr => burst_rd_addr,
            burst_rd_active => burst_rd_active,
            burst_rd_data => burst_rd_data,
            burst_rd_ts_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_start_ptr => burst_start_ptr
        );
end architecture rtl;
