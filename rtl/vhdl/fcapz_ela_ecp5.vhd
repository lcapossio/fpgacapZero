-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_ela_ecp5 is
    generic (
        SAMPLE_W     : positive := 8;
        DEPTH        : positive := 1024;
        TRIG_STAGES  : positive := 1;
        STOR_QUAL    : natural := 0;
        INPUT_PIPE   : natural := 0;
        NUM_CHANNELS : positive := 1;
        TIMESTAMP_W  : natural := 0;
        BURST_W      : positive := 256;
        CTRL_CHAIN   : positive := 1;
        DATA_CHAIN   : positive := 2;
        REL_COMPARE  : natural := 0;
        DUAL_COMPARE : natural := 1;
        USER1_DATA_EN : natural := 1
    );
    port (
        sample_clk : in  std_logic;
        sample_rst : in  std_logic;
        probe_in   : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0)
    );
end entity fcapz_ela_ecp5;

architecture rtl of fcapz_ela_ecp5 is
    constant PTR_W     : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE : positive := fcapz_nonzero_width(TIMESTAMP_W);

    signal tap1_tck, tap1_tdi, tap1_tdo : std_logic;
    signal tap1_capture, tap1_shift, tap1_update, tap1_sel : std_logic;
    signal tap2_tck, tap2_tdi, tap2_tdo : std_logic;
    signal tap2_capture, tap2_shift, tap2_update, tap2_sel : std_logic;
    signal jtag_clk, jtag_rst, jtag_wr_en, jtag_rd_en : std_logic;
    signal jtag_addr : std_logic_vector(15 downto 0);
    signal jtag_wdata, jtag_rdata : std_logic_vector(31 downto 0);
    signal burst_rd_addr : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_data : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start, burst_timestamp : std_logic;
    signal burst_start_ptr : std_logic_vector(PTR_W - 1 downto 0);
    signal jtag_rst_ctrl, jtag_rst_data : std_logic;
    signal trigger_out_unused, armed_out_unused : std_logic;
begin
    u_tap_ctrl : entity work.jtag_tap_ecp5
        generic map (CHAIN => CTRL_CHAIN)
        port map (
            tck => tap1_tck, tdi => tap1_tdi, tdo => tap1_tdo,
            capture => tap1_capture, shift => tap1_shift,
            update => tap1_update, sel => tap1_sel
        );

    u_tap_data : entity work.jtag_tap_ecp5
        generic map (CHAIN => DATA_CHAIN)
        port map (
            tck => tap2_tck, tdi => tap2_tdi, tdo => tap2_tdo,
            capture => tap2_capture, shift => tap2_shift,
            update => tap2_update, sel => tap2_sel
        );

    u_rst_sync_ctrl : entity work.reset_sync
        port map (clk => tap1_tck, arst => sample_rst, srst => jtag_rst_ctrl);

    u_rst_sync_data : entity work.reset_sync
        port map (clk => tap2_tck, arst => sample_rst, srst => jtag_rst_data);

    u_reg : entity work.jtag_reg_iface
        port map (
            arst => jtag_rst_ctrl,
            tck => tap1_tck, tdi => tap1_tdi, tdo => tap1_tdo,
            capture => tap1_capture, shift_en => tap1_shift,
            update => tap1_update, sel => tap1_sel,
            reg_clk => jtag_clk, reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en, reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr, reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata
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
            jtag_wr_en => jtag_wr_en, jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            burst_rd_addr => burst_rd_addr, burst_rd_data => burst_rd_data,
            burst_rd_ts_data => burst_rd_ts_data,
            burst_start => burst_start, burst_timestamp => burst_timestamp,
            burst_start_ptr => burst_start_ptr
        );

    u_burst : entity work.jtag_burst_read
        generic map (
            SAMPLE_W => SAMPLE_W, TIMESTAMP_W => TIMESTAMP_W,
            DEPTH => DEPTH, BURST_W => BURST_W, SEG_DEPTH => DEPTH
        )
        port map (
            arst => jtag_rst_data,
            tck => tap2_tck, tdi => tap2_tdi, tdo => tap2_tdo,
            capture => tap2_capture, shift_en => tap2_shift,
            update => tap2_update, sel => tap2_sel,
            mem_addr => burst_rd_addr,
            sample_data => burst_rd_data,
            timestamp_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_ptr_in => burst_start_ptr
        );
end architecture rtl;
