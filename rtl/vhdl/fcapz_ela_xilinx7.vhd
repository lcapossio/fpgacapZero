-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_ela_xilinx7 is
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
end entity fcapz_ela_xilinx7;

architecture rtl of fcapz_ela_xilinx7 is
    constant PTR_W           : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE       : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant BURST_SEG_DEPTH : positive := DEPTH / NUM_SEGMENTS;

    signal tap1_tck     : std_logic;
    signal tap1_tdi     : std_logic;
    signal tap1_tdo     : std_logic;
    signal tap1_capture : std_logic;
    signal tap1_shift   : std_logic;
    signal tap1_update  : std_logic;
    signal tap1_sel     : std_logic;

    signal tap2_tck     : std_logic;
    signal tap2_tdi     : std_logic;
    signal tap2_tdo     : std_logic;
    signal tap2_capture : std_logic;
    signal tap2_shift   : std_logic;
    signal tap2_update  : std_logic;
    signal tap2_sel     : std_logic;

    signal jtag_clk   : std_logic;
    signal jtag_rst   : std_logic;
    signal jtag_wr_en : std_logic;
    signal jtag_rd_en : std_logic;
    signal jtag_addr  : std_logic_vector(15 downto 0);
    signal jtag_wdata : std_logic_vector(31 downto 0);
    signal jtag_rdata : std_logic_vector(31 downto 0);

    signal burst_rd_addr    : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_active  : std_logic := '0';
    signal burst_rd_data    : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start      : std_logic;
    signal burst_timestamp  : std_logic;
    signal burst_start_ptr  : std_logic_vector(PTR_W - 1 downto 0);
    signal jtag_rst_ctrl    : std_logic;
    signal jtag_rst_data    : std_logic;
begin
    u_tap_ctrl : entity work.jtag_tap_xilinx7
        generic map (
            CHAIN => CTRL_CHAIN
        )
        port map (
            tck => tap1_tck,
            tdi => tap1_tdi,
            tdo => tap1_tdo,
            capture => tap1_capture,
            shift => tap1_shift,
            update => tap1_update,
            sel => tap1_sel
        );

    u_rst_sync_ctrl : entity work.reset_sync
        port map (
            clk => tap1_tck,
            arst => sample_rst,
            srst => jtag_rst_ctrl
        );

    g_pipe_iface : if SINGLE_CHAIN_BURST /= 0 generate
    begin
        u_pipe : entity work.jtag_pipe_iface
            generic map (
                SAMPLE_W => SAMPLE_W,
                TIMESTAMP_W => TIMESTAMP_W,
                DEPTH => DEPTH,
                BURST_W => BURST_W,
                SEG_DEPTH => BURST_SEG_DEPTH,
                BURST_PTR_ADDR => 16#002C#
            )
            port map (
                arst => jtag_rst_ctrl,
                tck => tap1_tck,
                tdi => tap1_tdi,
                tdo => tap1_tdo,
                capture => tap1_capture,
                shift_en => tap1_shift,
                update => tap1_update,
                sel => tap1_sel,
                reg_clk => jtag_clk,
                reg_rst => jtag_rst,
                reg_wr_en => jtag_wr_en,
                reg_rd_en => jtag_rd_en,
                reg_addr => jtag_addr,
                reg_wdata => jtag_wdata,
                reg_rdata => jtag_rdata,
                mem_addr => burst_rd_addr,
                mem_active => burst_rd_active,
                sample_data => burst_rd_data,
                timestamp_data => burst_rd_ts_data,
                burst_start => burst_start,
                burst_timestamp => burst_timestamp,
                burst_ptr_in => burst_start_ptr
            );
    end generate;

    g_reg_iface : if SINGLE_CHAIN_BURST = 0 generate
    begin
        u_reg : entity work.jtag_reg_iface
            port map (
                arst => jtag_rst_ctrl,
                tck => tap1_tck,
                tdi => tap1_tdi,
                tdo => tap1_tdo,
                capture => tap1_capture,
                shift_en => tap1_shift,
                update => tap1_update,
                sel => tap1_sel,
                reg_clk => jtag_clk,
                reg_rst => jtag_rst,
                reg_wr_en => jtag_wr_en,
                reg_rd_en => jtag_rd_en,
                reg_addr => jtag_addr,
                reg_wdata => jtag_wdata,
                reg_rdata => jtag_rdata
            );
    end generate;

    g_shared : if EIO_EN /= 0 generate
        signal ela_wr_en   : std_logic;
        signal ela_rd_en   : std_logic;
        signal ela_addr    : std_logic_vector(15 downto 0);
        signal ela_wdata   : std_logic_vector(31 downto 0);
        signal ela_rdata   : std_logic_vector(31 downto 0);
        signal eio_wr_en_i : std_logic;
        signal eio_rd_en_i : std_logic;
        signal eio_addr_i  : std_logic_vector(15 downto 0);
        signal eio_wdata_i : std_logic_vector(31 downto 0);
        signal eio_rdata_i : std_logic_vector(31 downto 0);
    begin
        u_mux : entity work.fcapz_regbus_mux
            port map (
                addr => jtag_addr,
                wr_en => jtag_wr_en,
                rd_en => jtag_rd_en,
                wdata => jtag_wdata,
                rdata => jtag_rdata,
                a_wr_en => ela_wr_en,
                a_rd_en => ela_rd_en,
                a_addr => ela_addr,
                a_wdata => ela_wdata,
                a_rdata => ela_rdata,
                b_wr_en => eio_wr_en_i,
                b_rd_en => eio_rd_en_i,
                b_addr => eio_addr_i,
                b_wdata => eio_wdata_i,
                b_rdata => eio_rdata_i
            );

        u_ela : entity work.fcapz_ela
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
                jtag_clk => jtag_clk,
                jtag_rst => jtag_rst,
                jtag_wr_en => ela_wr_en,
                jtag_rd_en => ela_rd_en,
                jtag_addr => ela_addr,
                jtag_wdata => ela_wdata,
                jtag_rdata => ela_rdata,
                burst_rd_addr => burst_rd_addr,
                burst_rd_active => burst_rd_active,
                burst_rd_data => burst_rd_data,
                burst_rd_ts_data => burst_rd_ts_data,
                burst_start => burst_start,
                burst_timestamp => burst_timestamp,
                burst_start_ptr => burst_start_ptr
            );

        u_eio : entity work.fcapz_eio
            generic map (
                IN_W => EIO_IN_W,
                OUT_W => EIO_OUT_W
            )
            port map (
                probe_in => eio_probe_in,
                probe_out => eio_probe_out,
                jtag_clk => jtag_clk,
                jtag_rst => jtag_rst,
                jtag_wr_en => eio_wr_en_i,
                jtag_addr => eio_addr_i,
                jtag_wdata => eio_wdata_i,
                jtag_rdata => eio_rdata_i
            );
    end generate;

    g_ela_only : if EIO_EN = 0 generate
    begin
        u_ela : entity work.fcapz_ela
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
                jtag_clk => jtag_clk,
                jtag_rst => jtag_rst,
                jtag_wr_en => jtag_wr_en,
                jtag_rd_en => jtag_rd_en,
                jtag_addr => jtag_addr,
                jtag_wdata => jtag_wdata,
                jtag_rdata => jtag_rdata,
                burst_rd_addr => burst_rd_addr,
                burst_rd_active => burst_rd_active,
                burst_rd_data => burst_rd_data,
                burst_rd_ts_data => burst_rd_ts_data,
                burst_start => burst_start,
                burst_timestamp => burst_timestamp,
                burst_start_ptr => burst_start_ptr
            );

        eio_probe_out <= (others => '0');
    end generate;

    g_burst : if BURST_EN /= 0 and SINGLE_CHAIN_BURST = 0 generate
    begin
        u_tap_data : entity work.jtag_tap_xilinx7
            generic map (
                CHAIN => DATA_CHAIN
            )
            port map (
                tck => tap2_tck,
                tdi => tap2_tdi,
                tdo => tap2_tdo,
                capture => tap2_capture,
                shift => tap2_shift,
                update => tap2_update,
                sel => tap2_sel
            );

        u_rst_sync_data : entity work.reset_sync
            port map (
                clk => tap2_tck,
                arst => sample_rst,
                srst => jtag_rst_data
            );

        u_burst : entity work.jtag_burst_read
            generic map (
                SAMPLE_W => SAMPLE_W,
                TIMESTAMP_W => TIMESTAMP_W,
                DEPTH => DEPTH,
                BURST_W => BURST_W,
                SEG_DEPTH => BURST_SEG_DEPTH
            )
            port map (
                arst => jtag_rst_data,
                tck => tap2_tck,
                tdi => tap2_tdi,
                tdo => tap2_tdo,
                capture => tap2_capture,
                shift_en => tap2_shift,
                update => tap2_update,
                sel => tap2_sel,
                mem_addr => burst_rd_addr,
                mem_active => burst_rd_active,
                sample_data => burst_rd_data,
                timestamp_data => burst_rd_ts_data,
                burst_start => burst_start,
                burst_timestamp => burst_timestamp,
                burst_ptr_in => burst_start_ptr
            );
    end generate;

    g_no_burst : if BURST_EN = 0 and SINGLE_CHAIN_BURST = 0 generate
    begin
        burst_rd_addr <= (others => '0');
    end generate;
end architecture rtl;
