-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_regbus_mux is
    port (
        addr  : in  std_logic_vector(15 downto 0);
        wr_en : in  std_logic;
        rd_en : in  std_logic;
        wdata : in  std_logic_vector(31 downto 0);
        rdata : out std_logic_vector(31 downto 0);

        a_wr_en : out std_logic;
        a_rd_en : out std_logic;
        a_addr  : out std_logic_vector(15 downto 0);
        a_wdata : out std_logic_vector(31 downto 0);
        a_rdata : in  std_logic_vector(31 downto 0);

        b_wr_en : out std_logic;
        b_rd_en : out std_logic;
        b_addr  : out std_logic_vector(15 downto 0);
        b_wdata : out std_logic_vector(31 downto 0);
        b_rdata : in  std_logic_vector(31 downto 0)
    );
end entity fcapz_regbus_mux;

architecture rtl of fcapz_regbus_mux is
    signal sel_b : std_logic;
begin
    sel_b <= addr(15);

    a_wr_en <= wr_en and not sel_b;
    a_rd_en <= rd_en and not sel_b;
    a_addr  <= addr;
    a_wdata <= wdata;

    b_wr_en <= wr_en and sel_b;
    b_rd_en <= rd_en and sel_b;
    b_addr  <= '0' & addr(14 downto 0);
    b_wdata <= wdata;

    rdata <= b_rdata when sel_b = '1' else a_rdata;
end architecture rtl;
