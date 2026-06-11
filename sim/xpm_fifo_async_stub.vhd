-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity xpm_fifo_async is
    generic (
        CDC_SYNC_STAGES     : integer := 2;
        FIFO_MEMORY_TYPE    : string := "auto";
        FIFO_READ_LATENCY   : integer := 0;
        FIFO_WRITE_DEPTH    : integer := 16;
        READ_DATA_WIDTH     : integer := 32;
        READ_MODE           : string := "fwft";
        WRITE_DATA_WIDTH    : integer := 32;
        FULL_RESET_VALUE    : integer := 0;
        RD_DATA_COUNT_WIDTH : integer := 5;
        WR_DATA_COUNT_WIDTH : integer := 5;
        USE_ADV_FEATURES    : string := "0404"
    );
    port (
        wr_clk        : in  std_logic;
        rst           : in  std_logic;
        wr_en         : in  std_logic;
        din           : in  std_logic_vector(WRITE_DATA_WIDTH - 1 downto 0);
        full          : out std_logic;
        rd_clk        : in  std_logic;
        rd_en         : in  std_logic;
        dout          : out std_logic_vector(READ_DATA_WIDTH - 1 downto 0);
        empty         : out std_logic;
        rd_data_count : out std_logic_vector(RD_DATA_COUNT_WIDTH - 1 downto 0);
        wr_data_count : out std_logic_vector(WR_DATA_COUNT_WIDTH - 1 downto 0);
        wr_rst_busy   : out std_logic;
        rd_rst_busy   : out std_logic;
        almost_full   : out std_logic;
        almost_empty  : out std_logic;
        data_valid    : out std_logic;
        overflow      : out std_logic;
        underflow     : out std_logic;
        prog_full     : out std_logic;
        prog_empty    : out std_logic;
        sleep         : in  std_logic;
        injectsbiterr : in  std_logic;
        injectdbiterr : in  std_logic;
        sbiterr       : out std_logic;
        dbiterr       : out std_logic
    );
end entity xpm_fifo_async;

architecture sim of xpm_fifo_async is
    signal rd_count_i : std_logic_vector(RD_DATA_COUNT_WIDTH - 1 downto 0);
    signal wr_count_i : std_logic_vector(WR_DATA_COUNT_WIDTH - 1 downto 0);
begin
    assert READ_DATA_WIDTH = WRITE_DATA_WIDTH
        report "xpm_fifo_async_stub requires equal read and write widths"
        severity failure;
    assert FIFO_READ_LATENCY = 0 and READ_MODE = "fwft"
        report "xpm_fifo_async_stub models only fwft, zero-latency FIFO mode"
        severity failure;

    u_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => WRITE_DATA_WIDTH,
            DEPTH => FIFO_WRITE_DEPTH,
            USE_BEHAV_ASYNC_FIFO => 1
        )
        port map (
            wr_clk => wr_clk,
            wr_rst => rst,
            wr_en => wr_en,
            wr_data => din,
            wr_full => full,
            wr_rst_busy => wr_rst_busy,
            rd_clk => rd_clk,
            rd_rst => rst,
            rd_en => rd_en,
            rd_data => dout,
            rd_empty => empty,
            rd_rst_busy => rd_rst_busy,
            rd_count => rd_count_i,
            wr_count => wr_count_i
        );

    rd_data_count <= rd_count_i;
    wr_data_count <= wr_count_i;
    almost_full <= '0';
    almost_empty <= '0';
    data_valid <= '0';
    overflow <= '0';
    underflow <= '0';
    prog_full <= '0';
    prog_empty <= '0';
    sbiterr <= '0';
    dbiterr <= '0';
end architecture sim;
