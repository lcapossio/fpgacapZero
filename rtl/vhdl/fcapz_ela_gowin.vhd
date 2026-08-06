-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_ela_gowin is
    generic (
        SAMPLE_W       : positive := 8;
        DEPTH          : positive := 1024;
        TRIG_STAGES    : positive := 1;
        STOR_QUAL      : natural := 0;
        INPUT_PIPE     : natural := 0;
        NUM_CHANNELS   : positive := 1;
        TIMESTAMP_W    : natural := 0;
        CHAIN          : positive := 1;
        EIO_EN         : natural := 0;
        EIO_IN_W       : positive := 1;
        EIO_OUT_W      : positive := 1;
        REL_COMPARE    : natural := 0;
        DUAL_COMPARE   : natural := 1;
        USER1_DATA_EN  : natural := 1
    );
    port (
        clk           : in  std_logic;
        jtag_activity : out std_logic;
        sample_clk    : in  std_logic;
        sample_rst    : in  std_logic;
        probe_in      : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0);
        eio_probe_in  : in  std_logic_vector(EIO_IN_W - 1 downto 0);
        eio_probe_out : out std_logic_vector(EIO_OUT_W - 1 downto 0);
        tms_pad_i     : in  std_logic;
        tck_pad_i     : in  std_logic;
        tdi_pad_i     : in  std_logic;
        tdo_pad_o     : out std_logic
    );
end entity fcapz_ela_gowin;

architecture rtl of fcapz_ela_gowin is
    constant PTR_W     : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant CHAIN_IDX : natural := CHAIN - 1;

    signal tap_tdi       : std_logic;
    signal tap_tdo       : std_logic_vector(1 downto 0);
    signal tap_capture   : std_logic_vector(1 downto 0);
    signal tap_shift_in  : std_logic_vector(1 downto 0);
    signal tap_shift_out : std_logic_vector(1 downto 0);
    signal tap_update    : std_logic_vector(1 downto 0);
    signal tap_sel       : std_logic_vector(1 downto 0);

    signal jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en : std_logic;
    signal jtag_addr : std_logic_vector(15 downto 0);
    signal jtag_wdata, jtag_rdata : std_logic_vector(31 downto 0);
    signal jtag_rst_ctrl : std_logic;

    signal burst_rd_addr_dummy : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal burst_rd_data_unused : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_unused : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start_unused, burst_timestamp_unused : std_logic;
    signal burst_start_ptr_unused : std_logic_vector(PTR_W - 1 downto 0);
begin
    assert CHAIN >= 1 and CHAIN <= 2
        report "fcapz_ela_gowin CHAIN must be 1 or 2"
        severity failure;

    u_tap_ctrl : entity work.jtag_tap_gowin
        port map (
            sysclk => clk,
            activity => jtag_activity,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift_in => tap_shift_in,
            shift_out => tap_shift_out,
            update => tap_update,
            sel => tap_sel,
            tms_pad_i => tms_pad_i,
            tck_pad_i => tck_pad_i,
            tdi_pad_i => tdi_pad_i,
            tdo_pad_o => tdo_pad_o
        );

    u_rst_sync_ctrl : entity work.reset_sync
        port map (clk => clk, arst => sample_rst, srst => jtag_rst_ctrl);

    u_reg : entity work.jtag_reg_iface_gowin
        port map (
            arst => jtag_rst_ctrl,
            tck => clk,
            tdi => tap_tdi,
            tdo => tap_tdo(CHAIN_IDX),
            capture => tap_capture(CHAIN_IDX),
            shift_in_en => tap_shift_in(CHAIN_IDX),
            shift_out_en => tap_shift_out(CHAIN_IDX),
            update => tap_update(CHAIN_IDX),
            sel => tap_sel(CHAIN_IDX),
            reg_clk => jtag_clk,
            reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en,
            reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr,
            reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata
        );

    g_shared : if EIO_EN /= 0 generate
        signal ela_wr_en, ela_rd_en : std_logic;
        signal ela_addr : std_logic_vector(15 downto 0);
        signal ela_wdata, ela_rdata : std_logic_vector(31 downto 0);
        signal eio_wr_en_i, eio_rd_en_i : std_logic;
        signal eio_addr_i : std_logic_vector(15 downto 0);
        signal eio_wdata_i, eio_rdata_i : std_logic_vector(31 downto 0);
        signal trigger_out_unused, armed_out_unused : std_logic;
    begin
        u_mux : entity work.fcapz_regbus_mux
            port map (
                addr => jtag_addr, wr_en => jtag_wr_en, rd_en => jtag_rd_en,
                wdata => jtag_wdata, rdata => jtag_rdata,
                a_wr_en => ela_wr_en, a_rd_en => ela_rd_en,
                a_addr => ela_addr, a_wdata => ela_wdata, a_rdata => ela_rdata,
                b_wr_en => eio_wr_en_i, b_rd_en => eio_rd_en_i,
                b_addr => eio_addr_i, b_wdata => eio_wdata_i, b_rdata => eio_rdata_i
            );

        u_ela : entity work.fcapz_ela
            generic map (
                SAMPLE_W => SAMPLE_W, DEPTH => DEPTH,
                TRIG_STAGES => TRIG_STAGES, STOR_QUAL => STOR_QUAL,
                INPUT_PIPE => INPUT_PIPE, NUM_CHANNELS => NUM_CHANNELS,
                TIMESTAMP_W => TIMESTAMP_W, REL_COMPARE => REL_COMPARE,
                DUAL_COMPARE => DUAL_COMPARE, USER1_DATA_EN => USER1_DATA_EN
            )
            port map (
                sample_clk => sample_clk, sample_rst => sample_rst,
                probe_in => probe_in, trigger_in => '0',
                trigger_out => trigger_out_unused, armed_out => armed_out_unused,
                jtag_clk => jtag_clk, jtag_rst => jtag_rst,
                jtag_wr_en => ela_wr_en, jtag_rd_en => ela_rd_en,
                jtag_addr => ela_addr, jtag_wdata => ela_wdata,
                jtag_rdata => ela_rdata,
                burst_rd_addr => burst_rd_addr_dummy,
                burst_rd_active => '0',
                burst_rd_data => burst_rd_data_unused,
                burst_rd_ts_data => burst_rd_ts_data_unused,
                burst_start => burst_start_unused,
                burst_timestamp => burst_timestamp_unused,
                burst_start_ptr => burst_start_ptr_unused
            );

        u_eio : entity work.fcapz_eio
            generic map (IN_W => EIO_IN_W, OUT_W => EIO_OUT_W)
            port map (
                probe_in => eio_probe_in, probe_out => eio_probe_out,
                jtag_clk => jtag_clk, jtag_rst => jtag_rst,
                jtag_wr_en => eio_wr_en_i,
                jtag_addr => eio_addr_i, jtag_wdata => eio_wdata_i,
                jtag_rdata => eio_rdata_i
            );
    end generate;

    g_ela_only : if EIO_EN = 0 generate
        signal trigger_out_unused, armed_out_unused : std_logic;
    begin
        u_ela : entity work.fcapz_ela
            generic map (
                SAMPLE_W => SAMPLE_W, DEPTH => DEPTH,
                TRIG_STAGES => TRIG_STAGES, STOR_QUAL => STOR_QUAL,
                INPUT_PIPE => INPUT_PIPE, NUM_CHANNELS => NUM_CHANNELS,
                TIMESTAMP_W => TIMESTAMP_W, REL_COMPARE => REL_COMPARE,
                DUAL_COMPARE => DUAL_COMPARE, USER1_DATA_EN => USER1_DATA_EN
            )
            port map (
                sample_clk => sample_clk, sample_rst => sample_rst,
                probe_in => probe_in, trigger_in => '0',
                trigger_out => trigger_out_unused, armed_out => armed_out_unused,
                jtag_clk => jtag_clk, jtag_rst => jtag_rst,
                jtag_wr_en => jtag_wr_en, jtag_rd_en => jtag_rd_en,
                jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
                jtag_rdata => jtag_rdata,
                burst_rd_addr => burst_rd_addr_dummy,
                burst_rd_active => '0',
                burst_rd_data => burst_rd_data_unused,
                burst_rd_ts_data => burst_rd_ts_data_unused,
                burst_start => burst_start_unused,
                burst_timestamp => burst_timestamp_unused,
                burst_start_ptr => burst_start_ptr_unused
            );
        eio_probe_out <= (others => '0');
    end generate;
end architecture rtl;
