-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

-- Mixed debug wrapper for Gowin (GW_JTAG user chain CTRL_CHAIN, 1 = ER1,
-- 2 = ER2): multiple ELAs plus optional EIOs behind the core manager on one
-- JTAG chain. GW_JTAG is oversampled on clk (jtag_tap_gowin), so clk must
-- run well above TCK, and the JTAG pads must reach top-level ports.
--
-- Register access only: the Gowin register adapter (jtag_reg_iface_gowin)
-- has no burst path, so every slot reports no burst and the host reads
-- captures through the register window (keep USER1_DATA_EN=1; the core
-- rejects a slot that could not be read). GW_JTAG's Test-Logic-Reset is not
-- used, so TLR_RESET_EN is not offered. Only one GW_JTAG is allowed per
-- design, so this hub cannot coexist with fcapz_ela_gowin or fcapz_eio_gowin.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_debug_multi_gowin is
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
        CTRL_CHAIN       : positive := 1;  -- 1 = ER1, 2 = ER2
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
        -- Oversampling clock for GW_JTAG; also the register-bus clock.
        clk             : in  std_logic;
        -- High while the GW_JTAG TAP is active (from jtag_tap_gowin).
        jtag_activity   : out std_logic;

        ela_sample_clk  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_sample_rst  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_probe_in    : in  std_logic_vector(ELA_PORT_COUNT * fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W) - 1 downto 0);
        ela_trigger_in  : in  std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_trigger_out : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        ela_armed_out   : out std_logic_vector(ELA_PORT_COUNT - 1 downto 0);
        eio_probe_in    : in  std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_IN_W - 1 downto 0);
        eio_probe_out   : out std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * EIO_OUT_W - 1 downto 0);

        -- GW_JTAG pads: wire straight to top-level ports.
        tms_pad_i       : in  std_logic;
        tck_pad_i       : in  std_logic;
        tdi_pad_i       : in  std_logic;
        tdo_pad_o       : out std_logic
    );
end entity fcapz_debug_multi_gowin;

architecture rtl of fcapz_debug_multi_gowin is
    constant PTR_W     : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant CHAIN_IDX : natural := CTRL_CHAIN - 1;

    signal tap_tdi : std_logic;
    signal tap_tdo, tap_capture, tap_update, tap_sel : std_logic_vector(1 downto 0);
    signal tap_shift_in, tap_shift_out : std_logic_vector(1 downto 0);

    signal any_sample_rst : std_logic;
    signal por_rst, proto_rst, tlr_sync : std_logic;
    signal jtag_clk, reg_rst_unused, jtag_wr_en, jtag_rd_en : std_logic;
    signal jtag_addr : std_logic_vector(15 downto 0);
    signal jtag_wdata, jtag_rdata : std_logic_vector(31 downto 0);

    -- No burst path: the core's burst bus is tied off.
    signal burst_rd_addr_zero : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_data_unused : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_unused : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start_unused, burst_timestamp_unused : std_logic;
    signal burst_start_ptr_unused : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_header_unused : std_logic_vector(159 downto 0);
begin
    assert CTRL_CHAIN = 1 or CTRL_CHAIN = 2
        report "fcapz_debug_multi_gowin: CTRL_CHAIN must be 1 (ER1) or 2 (ER2)"
        severity failure;

    -- The other user chain has no register interface; drive its TDO low.
    tap_tdo(1 - CHAIN_IDX) <= '0';
    burst_rd_addr_zero <= (others => '0');

    u_tap_ctrl : entity work.jtag_tap_gowin
        port map (
            sysclk => clk,
            activity => jtag_activity,
            tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture,
            shift_in => tap_shift_in, shift_out => tap_shift_out,
            update => tap_update, sel => tap_sel,
            tms_pad_i => tms_pad_i, tck_pad_i => tck_pad_i,
            tdi_pad_i => tdi_pad_i, tdo_pad_o => tdo_pad_o
        );

    any_sample_rst <= '1' when ela_sample_rst /= (ela_sample_rst'range => '0') else '0';

    -- The TAP's events are oversampled onto clk, so the hub resets run there.
    u_hub_reset : entity work.fcapz_hub_reset
        generic map (TLR_RESET_EN => 0)
        port map (
            tck => clk, any_sample_rst => any_sample_rst, hub_por => '0', tlr => '0',
            por_rst => por_rst, proto_rst => proto_rst, tlr_sync => tlr_sync
        );

    u_reg : entity work.jtag_reg_iface_gowin
        port map (
            arst => proto_rst,
            tck => clk,
            tdi => tap_tdi,
            tdo => tap_tdo(CHAIN_IDX),
            capture => tap_capture(CHAIN_IDX),
            shift_in_en => tap_shift_in(CHAIN_IDX),
            shift_out_en => tap_shift_out(CHAIN_IDX),
            update => tap_update(CHAIN_IDX),
            sel => tap_sel(CHAIN_IDX),
            reg_clk => jtag_clk,
            reg_rst => reg_rst_unused,
            reg_wr_en => jtag_wr_en,
            reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr,
            reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata
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
            DEFAULT_TRIG_EXT => DEFAULT_TRIG_EXT, BURST_EN => 0,
            REL_COMPARE => REL_COMPARE, DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN,
            HEADER_EN => 0, TLR_RESET_EN => 0,
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
            jtag_clk => jtag_clk, jtag_rst => por_rst,
            proto_rst => proto_rst, tlr => tlr_sync,
            jtag_wr_en => jtag_wr_en, jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            burst_rd_addr => burst_rd_addr_zero,
            burst_rd_active => '0',
            burst_rd_data => burst_rd_data_unused,
            burst_rd_ts_data => burst_rd_ts_data_unused,
            burst_start => burst_start_unused,
            burst_timestamp => burst_timestamp_unused,
            burst_start_ptr => burst_start_ptr_unused,
            burst_header => burst_header_unused
        );
end architecture rtl;
