-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_core_manager_cocotb_wrap is
    port (
        jtag_clk   : in  std_logic;
        jtag_rst   : in  std_logic;
        jtag_wr_en : in  std_logic;
        jtag_rd_en : in  std_logic;
        jtag_addr  : in  std_logic_vector(15 downto 0);
        jtag_wdata : in  std_logic_vector(31 downto 0);
        jtag_rdata : out std_logic_vector(31 downto 0);

        slot_wr_en : out std_logic_vector(2 downto 0);
        slot_rd_en : out std_logic_vector(2 downto 0);
        slot_addr  : out std_logic_vector(47 downto 0);
        slot_wdata : out std_logic_vector(95 downto 0);
        slot_rdata : in  std_logic_vector(95 downto 0);

        burst_rd_addr         : in  std_logic_vector(3 downto 0);
        slot_burst_rd_addr    : out std_logic_vector(11 downto 0);
        slot_burst_rd_data    : in  std_logic_vector(23 downto 0);
        slot_burst_rd_ts_data : in  std_logic_vector(11 downto 0);
        slot_burst_start      : in  std_logic_vector(2 downto 0);
        slot_burst_timestamp  : in  std_logic_vector(2 downto 0);
        slot_burst_start_ptr  : in  std_logic_vector(11 downto 0);
        burst_rd_data         : out std_logic_vector(7 downto 0);
        burst_rd_ts_data      : out std_logic_vector(3 downto 0);
        burst_start           : out std_logic;
        burst_timestamp       : out std_logic;
        burst_start_ptr       : out std_logic_vector(3 downto 0)
    );
end entity fcapz_core_manager_cocotb_wrap;

architecture sim of fcapz_core_manager_cocotb_wrap is
begin
    u_dut : entity work.fcapz_core_manager
        generic map (
            NUM_SLOTS => 3,
            SAMPLE_W => 8,
            TIMESTAMP_W => 4,
            DEPTH => 16,
            SLOT_CORE_IDS => x"494F_4C41_4C41",
            SLOT_HAS_BURST => "011"
        )
        port map (
            jtag_clk => jtag_clk,
            jtag_rst => jtag_rst,
            jtag_wr_en => jtag_wr_en,
            jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr,
            jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            slot_wr_en => slot_wr_en,
            slot_rd_en => slot_rd_en,
            slot_addr => slot_addr,
            slot_wdata => slot_wdata,
            slot_rdata => slot_rdata,
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
end architecture sim;
