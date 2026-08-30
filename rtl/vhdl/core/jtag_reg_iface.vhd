-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_reg_iface is
    port (
        arst : in  std_logic;

        tck      : in  std_logic;
        tdi      : in  std_logic;
        tdo      : out std_logic;
        capture  : in  std_logic;
        shift_en : in  std_logic;
        update   : in  std_logic;
        sel      : in  std_logic;

        reg_clk   : out std_logic;
        reg_rst   : out std_logic;
        reg_wr_en : out std_logic;
        reg_rd_en : out std_logic;
        reg_addr  : out std_logic_vector(15 downto 0);
        reg_wdata : out std_logic_vector(31 downto 0);
        reg_rdata : in  std_logic_vector(31 downto 0)
    );
end entity jtag_reg_iface;

architecture rtl of jtag_reg_iface is
    signal sr           : std_logic_vector(48 downto 0) := (others => '0');
    signal reg_wr_en_r  : std_logic := '0';
    signal reg_rd_en_r  : std_logic := '0';
    signal reg_addr_r   : std_logic_vector(15 downto 0) := (others => '0');
    signal reg_wdata_r  : std_logic_vector(31 downto 0) := (others => '0');
begin
    tdo        <= sr(0);
    reg_clk    <= tck;
    reg_rst    <= arst;
    reg_wr_en  <= reg_wr_en_r;
    reg_rd_en  <= reg_rd_en_r;
    reg_addr   <= reg_addr_r;
    reg_wdata  <= reg_wdata_r;

    p_tck : process(tck, arst)
    begin
        if arst = '1' then
            sr <= (others => '0');
            reg_wr_en_r <= '0';
            reg_rd_en_r <= '0';
            reg_addr_r <= (others => '0');
            reg_wdata_r <= (others => '0');
        elsif rising_edge(tck) then
            reg_wr_en_r <= '0';
            reg_rd_en_r <= '0';

            if sel = '1' then
                if capture = '1' then
                    sr(31 downto 0) <= reg_rdata;
                elsif shift_en = '1' then
                    sr <= tdi & sr(48 downto 1);
                elsif update = '1' then
                    reg_addr_r <= sr(47 downto 32);
                    if sr(48) = '1' then
                        reg_wdata_r <= sr(31 downto 0);
                        reg_wr_en_r <= '1';
                    else
                        reg_rd_en_r <= '1';
                    end if;
                end if;
            end if;
        end if;
    end process;
end architecture rtl;
