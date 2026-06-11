-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - www.bard0.com - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

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
    function ela_param32(values : std_logic_vector; idx : natural) return natural is
    begin
        return to_integer(unsigned(values(idx * 32 + 31 downto idx * 32)));
    end function;

    function eio_param32(values : std_logic_vector; idx : natural) return natural is
    begin
        return to_integer(unsigned(values(idx * 32 + 31 downto idx * 32)));
    end function;

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
            if ela_param32(ELA_SAMPLE_WS, i) = SAMPLE_W and
               ela_param32(ELA_DEPTHS, i) = DEPTH and
               ela_param32(ELA_TIMESTAMP_WS, i) = TIMESTAMP_W and
               ela_param32(ELA_NUM_SEGMENTS, i) = NUM_SEGMENTS then
                result(i) := '1';
            end if;
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
        constant ELA_SAMPLE_W_I        : positive := ela_param32(ELA_SAMPLE_WS, i);
        constant ELA_DEPTH_I           : positive := ela_param32(ELA_DEPTHS, i);
        constant ELA_TRIG_STAGES_I     : positive := ela_param32(ELA_TRIG_STAGES, i);
        constant ELA_STOR_QUAL_I       : natural := ela_param32(ELA_STOR_QUALS, i);
        constant ELA_INPUT_PIPE_I      : natural := ela_param32(ELA_INPUT_PIPES, i);
        constant ELA_NUM_CHANNELS_I    : positive := ela_param32(ELA_NUM_CHANNELS, i);
        constant ELA_DECIM_EN_I        : natural := ela_param32(ELA_DECIM_ENS, i);
        constant ELA_EXT_TRIG_EN_I     : natural := ela_param32(ELA_EXT_TRIG_ENS, i);
        constant ELA_TIMESTAMP_W_I     : natural := ela_param32(ELA_TIMESTAMP_WS, i);
        constant ELA_NUM_SEGMENTS_I    : positive := ela_param32(ELA_NUM_SEGMENTS, i);
        constant ELA_PROBE_MUX_W_I     : natural := ela_param32(ELA_PROBE_MUX_WS, i);
        constant ELA_STARTUP_ARM_I     : natural := ela_param32(ELA_STARTUP_ARMS, i);
        constant ELA_DEFAULT_TRIG_EXT_I : natural := ela_param32(ELA_DEFAULT_TRIG_EXTS, i);
        constant ELA_REL_COMPARE_I     : natural := ela_param32(ELA_REL_COMPARES, i);
        constant ELA_DUAL_COMPARE_I    : natural := ela_param32(ELA_DUAL_COMPARES, i);
        constant ELA_USER1_DATA_EN_I   : natural := ela_param32(ELA_USER1_DATA_ENS, i);
        constant ELA_PROBE_W_I         : positive := fcapz_probe_width(ELA_PROBE_MUX_W_I, ELA_NUM_CHANNELS_I, ELA_SAMPLE_W_I);
        constant ELA_PTR_W_I           : positive := fcapz_clog2(ELA_DEPTH_I);
        constant ELA_TS_W_SAFE_I       : positive := fcapz_nonzero_width(ELA_TIMESTAMP_W_I);
        signal ela_burst_rd_data_i     : std_logic_vector(ELA_SAMPLE_W_I - 1 downto 0);
        signal ela_burst_rd_ts_data_i  : std_logic_vector(ELA_TS_W_SAFE_I - 1 downto 0);
        signal ela_burst_start_ptr_i   : std_logic_vector(ELA_PTR_W_I - 1 downto 0);
    begin
        assert ELA_PROBE_W_I <= PROBE_W
            report "fcapz_debug_multi_xilinx7 ELA probe width exceeds scalar slot width"
            severity failure;
        assert ELA_SAMPLE_W_I <= SAMPLE_W
            report "fcapz_debug_multi_xilinx7 ELA SAMPLE_W exceeds scalar SAMPLE_W"
            severity failure;
        assert ELA_TS_W_SAFE_I <= TS_W_SAFE
            report "fcapz_debug_multi_xilinx7 ELA TIMESTAMP_W exceeds scalar TIMESTAMP_W"
            severity failure;
        assert ELA_PTR_W_I <= PTR_W
            report "fcapz_debug_multi_xilinx7 ELA DEPTH exceeds scalar DEPTH"
            severity failure;

        u_ela : entity work.fcapz_ela
            generic map (
                SAMPLE_W => ELA_SAMPLE_W_I, DEPTH => ELA_DEPTH_I,
                TRIG_STAGES => ELA_TRIG_STAGES_I, STOR_QUAL => ELA_STOR_QUAL_I,
                INPUT_PIPE => ELA_INPUT_PIPE_I, NUM_CHANNELS => ELA_NUM_CHANNELS_I,
                DECIM_EN => ELA_DECIM_EN_I, EXT_TRIG_EN => ELA_EXT_TRIG_EN_I,
                TIMESTAMP_W => ELA_TIMESTAMP_W_I, NUM_SEGMENTS => ELA_NUM_SEGMENTS_I,
                PROBE_MUX_W => ELA_PROBE_MUX_W_I, STARTUP_ARM => ELA_STARTUP_ARM_I,
                DEFAULT_TRIG_EXT => ELA_DEFAULT_TRIG_EXT_I,
                REL_COMPARE => ELA_REL_COMPARE_I, DUAL_COMPARE => ELA_DUAL_COMPARE_I,
                USER1_DATA_EN => ELA_USER1_DATA_EN_I
            )
            port map (
                sample_clk => ela_sample_clk(i),
                sample_rst => ela_sample_rst(i),
                probe_in => ela_probe_in(i * PROBE_W + ELA_PROBE_W_I - 1 downto i * PROBE_W),
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
                burst_rd_addr => slot_burst_rd_addr(i * PTR_W + ELA_PTR_W_I - 1 downto i * PTR_W),
                burst_rd_data => ela_burst_rd_data_i,
                burst_rd_ts_data => ela_burst_rd_ts_data_i,
                burst_start => slot_burst_start(i),
                burst_timestamp => slot_burst_timestamp(i),
                burst_start_ptr => ela_burst_start_ptr_i
            );

        p_pad_burst_data : process(all)
        begin
            slot_burst_rd_data((i + 1) * SAMPLE_W - 1 downto i * SAMPLE_W) <= (others => '0');
            slot_burst_rd_data(i * SAMPLE_W + ELA_SAMPLE_W_I - 1 downto i * SAMPLE_W) <= ela_burst_rd_data_i;
        end process;

        p_pad_burst_ts : process(all)
        begin
            slot_burst_rd_ts_data((i + 1) * TS_W_SAFE - 1 downto i * TS_W_SAFE) <= (others => '0');
            slot_burst_rd_ts_data(i * TS_W_SAFE + ELA_TS_W_SAFE_I - 1 downto i * TS_W_SAFE) <= ela_burst_rd_ts_data_i;
        end process;

        p_pad_start_ptr : process(all)
        begin
            slot_burst_start_ptr((i + 1) * PTR_W - 1 downto i * PTR_W) <= (others => '0');
            slot_burst_start_ptr(i * PTR_W + ELA_PTR_W_I - 1 downto i * PTR_W) <= ela_burst_start_ptr_i;
        end process;
    end generate;

    g_eios : for i in 0 to EIO_PORT_COUNT - 1 generate
        g_have_eio : if i < EIO_COUNT generate
            constant slot_i : natural := NUM_ELAS + i;
            constant EIO_IN_W_I : positive := eio_param32(EIO_IN_WS, i);
            constant EIO_OUT_W_I : positive := eio_param32(EIO_OUT_WS, i);
            signal eio_probe_out_i : std_logic_vector(EIO_OUT_W_I - 1 downto 0);
        begin
            assert EIO_IN_W_I <= EIO_IN_W
                report "fcapz_debug_multi_xilinx7 EIO IN_W exceeds scalar EIO_IN_W"
                severity failure;
            assert EIO_OUT_W_I <= EIO_OUT_W
                report "fcapz_debug_multi_xilinx7 EIO OUT_W exceeds scalar EIO_OUT_W"
                severity failure;

            u_eio : entity work.fcapz_eio
                generic map (IN_W => EIO_IN_W_I, OUT_W => EIO_OUT_W_I)
                port map (
                    probe_in => eio_probe_in(i * EIO_IN_W + EIO_IN_W_I - 1 downto i * EIO_IN_W),
                    probe_out => eio_probe_out_i,
                    jtag_clk => jtag_clk, jtag_rst => jtag_rst,
                    jtag_wr_en => slot_wr_en(slot_i),
                    jtag_addr => slot_addr((slot_i + 1) * 16 - 1 downto slot_i * 16),
                    jtag_wdata => slot_wdata((slot_i + 1) * 32 - 1 downto slot_i * 32),
                    jtag_rdata => slot_rdata((slot_i + 1) * 32 - 1 downto slot_i * 32)
                );

            p_pad_eio_out : process(all)
            begin
                eio_probe_out((i + 1) * EIO_OUT_W - 1 downto i * EIO_OUT_W) <= (others => '0');
                eio_probe_out(i * EIO_OUT_W + EIO_OUT_W_I - 1 downto i * EIO_OUT_W) <= eio_probe_out_i;
            end process;

            slot_burst_rd_data((slot_i + 1) * SAMPLE_W - 1 downto slot_i * SAMPLE_W) <= (others => '0');
            slot_burst_rd_ts_data((slot_i + 1) * TS_W_SAFE - 1 downto slot_i * TS_W_SAFE) <= (others => '0');
            slot_burst_start(slot_i) <= '0';
            slot_burst_timestamp(slot_i) <= '0';
            slot_burst_start_ptr((slot_i + 1) * PTR_W - 1 downto slot_i * PTR_W) <= (others => '0');
        end generate;

        g_unused_eio_port : if i >= EIO_COUNT generate
        begin
            eio_probe_out((i + 1) * EIO_OUT_W - 1 downto i * EIO_OUT_W) <= (others => '0');
        end generate;
    end generate;
end architecture rtl;
