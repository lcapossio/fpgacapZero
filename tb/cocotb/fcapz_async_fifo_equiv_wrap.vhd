-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_async_fifo_equiv_wrap is
    generic (
        DATA_W : positive := 8;
        DEPTH  : positive := 16
    );
    port (
        wr_clk     : in  std_logic;
        rd_clk     : in  std_logic;
        rst        : in  std_logic;
        wr_en      : in  std_logic;
        wr_data    : in  std_logic_vector(DATA_W - 1 downto 0);
        rd_en      : in  std_logic;
        rd_data_a  : out std_logic_vector(DATA_W - 1 downto 0);
        rd_data_b  : out std_logic_vector(DATA_W - 1 downto 0);
        rd_empty_a : out std_logic;
        rd_empty_b : out std_logic;
        wr_full_a  : out std_logic;
        wr_full_b  : out std_logic
    );
end entity fcapz_async_fifo_equiv_wrap;

architecture sim of fcapz_async_fifo_equiv_wrap is
    signal wr_rst_busy_a : std_logic;
    signal wr_rst_busy_b : std_logic;
    signal rd_rst_busy_a : std_logic;
    signal rd_rst_busy_b : std_logic;
begin
    dut_a : entity work.fcapz_async_fifo
        generic map (
            DATA_W => DATA_W,
            DEPTH => DEPTH,
            USE_BEHAV_ASYNC_FIFO => 1
        )
        port map (
            wr_clk => wr_clk,
            wr_rst => rst,
            wr_en => wr_en,
            wr_data => wr_data,
            wr_full => wr_full_a,
            wr_rst_busy => wr_rst_busy_a,
            rd_clk => rd_clk,
            rd_rst => rst,
            rd_en => rd_en,
            rd_data => rd_data_a,
            rd_empty => rd_empty_a,
            rd_rst_busy => rd_rst_busy_a,
            rd_count => open,
            wr_count => open
        );

    dut_b : entity work.fcapz_async_fifo
        generic map (
            DATA_W => DATA_W,
            DEPTH => DEPTH,
            USE_BEHAV_ASYNC_FIFO => 0
        )
        port map (
            wr_clk => wr_clk,
            wr_rst => rst,
            wr_en => wr_en,
            wr_data => wr_data,
            wr_full => wr_full_b,
            wr_rst_busy => wr_rst_busy_b,
            rd_clk => rd_clk,
            rd_rst => rst,
            rd_en => rd_en,
            rd_data => rd_data_b,
            rd_empty => rd_empty_b,
            rd_rst_busy => rd_rst_busy_b,
            rd_count => open,
            wr_count => open
        );
end architecture sim;
