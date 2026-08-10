-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_eio_xilinx7 is
    generic (
        IN_W  : positive := 32;
        OUT_W : positive := 32;
        CHAIN : positive := 3
    );
    port (
        probe_in  : in  std_logic_vector(IN_W - 1 downto 0);
        probe_out : out std_logic_vector(OUT_W - 1 downto 0)
    );
end entity fcapz_eio_xilinx7;

architecture rtl of fcapz_eio_xilinx7 is
    signal tap_tck     : std_logic;
    signal tap_tdi     : std_logic;
    signal tap_tdo     : std_logic;
    signal tap_capture : std_logic;
    signal tap_shift   : std_logic;
    signal tap_update  : std_logic;
    signal tap_sel     : std_logic;

    signal jtag_clk   : std_logic;
    signal jtag_rst   : std_logic;
    signal jtag_wr_en : std_logic;
    signal jtag_rd_en : std_logic;
    signal jtag_addr  : std_logic_vector(15 downto 0);
    signal jtag_wdata : std_logic_vector(31 downto 0);
    signal jtag_rdata : std_logic_vector(31 downto 0);
begin
    u_tap : entity work.jtag_tap_xilinx7
        generic map (
            CHAIN => CHAIN
        )
        port map (
            tck => tap_tck,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift => tap_shift,
            update => tap_update,
            sel => tap_sel
        );

    u_reg : entity work.jtag_reg_iface
        port map (
            arst => '0',
            tck => tap_tck,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift_en => tap_shift,
            update => tap_update,
            sel => tap_sel,
            reg_clk => jtag_clk,
            reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en,
            reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr,
            reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata
        );

    u_eio : entity work.fcapz_eio
        generic map (
            IN_W => IN_W,
            OUT_W => OUT_W
        )
        port map (
            probe_in => probe_in,
            probe_out => probe_out,
            jtag_clk => jtag_clk,
            jtag_rst => jtag_rst,
            jtag_wr_en => jtag_wr_en,
            jtag_addr => jtag_addr,
            jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata
        );
end architecture rtl;
