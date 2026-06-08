-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_debug_multi_xilinx7 is
    generic (
        NUM_ELAS         : natural := 2;
        EIO_EN           : natural := 1;
        NUM_EIOS         : natural := 1;
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
        CTRL_CHAIN       : positive := 1;
        REL_COMPARE      : natural := 0;
        DUAL_COMPARE     : natural := 1;
        USER1_DATA_EN    : natural := 1;
        EIO_IN_W         : positive := 1;
        EIO_OUT_W        : positive := 1;
        ELA_PORT_COUNT   : positive := 2;
        ELA_SAMPLE_WS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_DEPTHS       : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_TRIG_STAGES  : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_STOR_QUALS   : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_INPUT_PIPES  : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_NUM_CHANNELS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_DECIM_ENS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_EXT_TRIG_ENS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_TIMESTAMP_WS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_NUM_SEGMENTS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_PROBE_MUX_WS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_STARTUP_ARMS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_DEFAULT_TRIG_EXTS : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_REL_COMPARES      : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_DUAL_COMPARES     : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        ELA_USER1_DATA_ENS    : std_logic_vector(ELA_PORT_COUNT * 32 - 1 downto 0) := (others => '0');
        EIO_IN_WS        : std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * 32 - 1 downto 0) := (others => '0');
        EIO_OUT_WS       : std_logic_vector(fcapz_nonzero_width(NUM_EIOS) * 32 - 1 downto 0) := (others => '0')
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
    function make_core_ids return std_logic_vector is
        variable result : std_logic_vector((NUM_ELAS + NUM_EIOS) * 16 - 1 downto 0) := (others => '0');
    begin
        for i in 0 to NUM_ELAS - 1 loop
            result(i * 16 + 15 downto i * 16) := x"4C41";
        end loop;
        for i in 0 to NUM_EIOS - 1 loop
            result((NUM_ELAS + i) * 16 + 15 downto (NUM_ELAS + i) * 16) := x"494F";
        end loop;
        return result;
    end function;

    function make_has_burst return std_logic_vector is
        variable result : std_logic_vector(NUM_ELAS + NUM_EIOS - 1 downto 0) := (others => '0');
    begin
        for i in 0 to NUM_ELAS - 1 loop
            result(i) := '1';
        end loop;
        return result;
    end function;

    constant EIO_COUNT       : natural := NUM_EIOS;
    constant EIO_PORT_COUNT  : positive := fcapz_nonzero_width(NUM_EIOS);
    constant NUM_SLOTS       : positive := NUM_ELAS + EIO_COUNT;
    constant PTR_W           : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE       : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant PROBE_W         : positive := fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W);
    constant BURST_SEG_DEPTH : positive := DEPTH / NUM_SEGMENTS;
    constant SLOT_CORE_IDS   : std_logic_vector(NUM_SLOTS * 16 - 1 downto 0) := make_core_ids;
    constant SLOT_HAS_BURST  : std_logic_vector(NUM_SLOTS - 1 downto 0) := make_has_burst;

    signal debug_arst : std_logic;
    signal tap_tck, tap_tdi, tap_tdo : std_logic;
    signal tap_capture, tap_shift, tap_update, tap_sel : std_logic;
    signal jtag_rst_ctrl : std_logic;
    signal jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en : std_logic;
    signal jtag_addr : std_logic_vector(15 downto 0);
    signal jtag_wdata, jtag_rdata : std_logic_vector(31 downto 0);
    signal burst_rd_addr : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_data : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start, burst_timestamp : std_logic;
    signal burst_start_ptr : std_logic_vector(PTR_W - 1 downto 0);
    signal slot_wr_en, slot_rd_en : std_logic_vector(NUM_SLOTS - 1 downto 0);
    signal slot_addr : std_logic_vector(NUM_SLOTS * 16 - 1 downto 0);
    signal slot_wdata, slot_rdata : std_logic_vector(NUM_SLOTS * 32 - 1 downto 0);
    signal slot_burst_rd_addr : std_logic_vector(NUM_SLOTS * PTR_W - 1 downto 0);
    signal slot_burst_rd_data : std_logic_vector(NUM_SLOTS * SAMPLE_W - 1 downto 0);
    signal slot_burst_rd_ts_data : std_logic_vector(NUM_SLOTS * TS_W_SAFE - 1 downto 0);
    signal slot_burst_start, slot_burst_timestamp : std_logic_vector(NUM_SLOTS - 1 downto 0);
    signal slot_burst_start_ptr : std_logic_vector(NUM_SLOTS * PTR_W - 1 downto 0);
begin
    assert NUM_ELAS > 0
        report "fcapz_debug_multi_xilinx7 requires at least one ELA slot"
        severity failure;
    assert ELA_PORT_COUNT >= NUM_ELAS
        report "fcapz_debug_multi_xilinx7 ELA_PORT_COUNT must cover NUM_ELAS"
        severity failure;

    debug_arst <= '1' when ela_sample_rst /= (ela_sample_rst'range => '0') else '0';

    u_tap_ctrl : entity work.jtag_tap_xilinx7
        generic map (CHAIN => CTRL_CHAIN)
        port map (
            tck => tap_tck, tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture, shift => tap_shift,
            update => tap_update, sel => tap_sel
        );

    u_rst_sync_ctrl : entity work.reset_sync
        port map (clk => tap_tck, arst => debug_arst, srst => jtag_rst_ctrl);

    u_pipe : entity work.jtag_pipe_iface
        generic map (
            SAMPLE_W => SAMPLE_W, TIMESTAMP_W => TIMESTAMP_W,
            DEPTH => DEPTH, BURST_W => BURST_W,
            SEG_DEPTH => BURST_SEG_DEPTH, BURST_PTR_ADDR => 16#002C#
        )
        port map (
            arst => jtag_rst_ctrl,
            tck => tap_tck, tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture, shift_en => tap_shift,
            update => tap_update, sel => tap_sel,
            reg_clk => jtag_clk, reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en, reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr, reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata,
            mem_addr => burst_rd_addr,
            sample_data => burst_rd_data,
            timestamp_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_ptr_in => burst_start_ptr
        );

    u_manager : entity work.fcapz_core_manager
        generic map (
            NUM_SLOTS => NUM_SLOTS,
            SAMPLE_W => SAMPLE_W,
            TIMESTAMP_W => TIMESTAMP_W,
            DEPTH => DEPTH,
            SLOT_CORE_IDS => SLOT_CORE_IDS,
            SLOT_HAS_BURST => SLOT_HAS_BURST
        )
        port map (
            jtag_clk => jtag_clk, jtag_rst => jtag_rst,
            jtag_wr_en => jtag_wr_en, jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            slot_wr_en => slot_wr_en, slot_rd_en => slot_rd_en,
            slot_addr => slot_addr, slot_wdata => slot_wdata, slot_rdata => slot_rdata,
            burst_rd_addr => burst_rd_addr,
            slot_burst_rd_addr => slot_burst_rd_addr,
            slot_burst_rd_data => slot_burst_rd_data,
            slot_burst_rd_ts_data => slot_burst_rd_ts_data,
            slot_burst_start => slot_burst_start,
            slot_burst_timestamp => slot_burst_timestamp,
            slot_burst_start_ptr => slot_burst_start_ptr,
            burst_rd_data => burst_rd_data,
            burst_rd_ts_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_start_ptr => burst_start_ptr
        );

    g_elas : for i in 0 to NUM_ELAS - 1 generate
    begin
        u_ela : entity work.fcapz_ela
            generic map (
                SAMPLE_W => SAMPLE_W, DEPTH => DEPTH,
                TRIG_STAGES => TRIG_STAGES, STOR_QUAL => STOR_QUAL,
                INPUT_PIPE => INPUT_PIPE, NUM_CHANNELS => NUM_CHANNELS,
                DECIM_EN => DECIM_EN, EXT_TRIG_EN => EXT_TRIG_EN,
                TIMESTAMP_W => TIMESTAMP_W, NUM_SEGMENTS => NUM_SEGMENTS,
                PROBE_MUX_W => PROBE_MUX_W, STARTUP_ARM => STARTUP_ARM,
                DEFAULT_TRIG_EXT => DEFAULT_TRIG_EXT,
                REL_COMPARE => REL_COMPARE, DUAL_COMPARE => DUAL_COMPARE,
                USER1_DATA_EN => USER1_DATA_EN
            )
            port map (
                sample_clk => ela_sample_clk(i),
                sample_rst => ela_sample_rst(i),
                probe_in => ela_probe_in((i + 1) * PROBE_W - 1 downto i * PROBE_W),
                trigger_in => ela_trigger_in(i),
                trigger_out => ela_trigger_out(i),
                armed_out => ela_armed_out(i),
                jtag_clk => jtag_clk,
                jtag_rst => jtag_rst,
                jtag_wr_en => slot_wr_en(i),
                jtag_rd_en => slot_rd_en(i),
                jtag_addr => slot_addr((i + 1) * 16 - 1 downto i * 16),
                jtag_wdata => slot_wdata((i + 1) * 32 - 1 downto i * 32),
                jtag_rdata => slot_rdata((i + 1) * 32 - 1 downto i * 32),
                burst_rd_addr => slot_burst_rd_addr((i + 1) * PTR_W - 1 downto i * PTR_W),
                burst_rd_data => slot_burst_rd_data((i + 1) * SAMPLE_W - 1 downto i * SAMPLE_W),
                burst_rd_ts_data => slot_burst_rd_ts_data((i + 1) * TS_W_SAFE - 1 downto i * TS_W_SAFE),
                burst_start => slot_burst_start(i),
                burst_timestamp => slot_burst_timestamp(i),
                burst_start_ptr => slot_burst_start_ptr((i + 1) * PTR_W - 1 downto i * PTR_W)
            );
    end generate;

    g_eios : for i in 0 to EIO_COUNT - 1 generate
        constant slot_i : natural := NUM_ELAS + i;
    begin
        u_eio : entity work.fcapz_eio
            generic map (IN_W => EIO_IN_W, OUT_W => EIO_OUT_W)
            port map (
                probe_in => eio_probe_in((i + 1) * EIO_IN_W - 1 downto i * EIO_IN_W),
                probe_out => eio_probe_out((i + 1) * EIO_OUT_W - 1 downto i * EIO_OUT_W),
                jtag_clk => jtag_clk, jtag_rst => jtag_rst,
                jtag_wr_en => slot_wr_en(slot_i),
                jtag_addr => slot_addr((slot_i + 1) * 16 - 1 downto slot_i * 16),
                jtag_wdata => slot_wdata((slot_i + 1) * 32 - 1 downto slot_i * 32),
                jtag_rdata => slot_rdata((slot_i + 1) * 32 - 1 downto slot_i * 32)
            );
        slot_burst_rd_data((slot_i + 1) * SAMPLE_W - 1 downto slot_i * SAMPLE_W) <= (others => '0');
        slot_burst_rd_ts_data((slot_i + 1) * TS_W_SAFE - 1 downto slot_i * TS_W_SAFE) <= (others => '0');
        slot_burst_start(slot_i) <= '0';
        slot_burst_timestamp(slot_i) <= '0';
        slot_burst_start_ptr((slot_i + 1) * PTR_W - 1 downto slot_i * PTR_W) <= (others => '0');
    end generate;

    g_no_eio : if EIO_COUNT = 0 generate
    begin
        eio_probe_out <= (others => '0');
    end generate;
end architecture rtl;
