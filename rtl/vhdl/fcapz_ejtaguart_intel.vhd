-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ejtaguart_intel is
    generic (
        JTAG_CHAIN    : positive := 4;
        CLK_HZ        : positive := 100000000;
        BAUD_RATE     : positive := 115200;
        TX_FIFO_DEPTH : positive := 256;
        RX_FIFO_DEPTH : positive := 256;
        PARITY        : natural := 0
    );
    port (
        uart_clk : in  std_logic;
        uart_rst : in  std_logic;
        uart_txd : out std_logic;
        uart_rxd : in  std_logic
    );
end entity fcapz_ejtaguart_intel;

architecture rtl of fcapz_ejtaguart_intel is
    signal tap_tck     : std_logic;
    signal tap_tdi     : std_logic;
    signal tap_tdo     : std_logic;
    signal tap_capture : std_logic;
    signal tap_shift   : std_logic;
    signal tap_update  : std_logic;
    signal tap_sel     : std_logic;
begin
    u_tap : entity work.jtag_tap_intel
        generic map (CHAIN => JTAG_CHAIN)
        port map (
            tck => tap_tck, tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture, shift => tap_shift,
            update => tap_update, sel => tap_sel
        );

    u_ejtaguart : entity work.fcapz_ejtaguart
        generic map (
            CLK_HZ => CLK_HZ,
            BAUD_RATE => BAUD_RATE,
            TX_FIFO_DEPTH => TX_FIFO_DEPTH,
            RX_FIFO_DEPTH => RX_FIFO_DEPTH,
            PARITY => PARITY,
            USE_BEHAV_ASYNC_FIFO => 0
        )
        port map (
            uart_clk => uart_clk,
            uart_rst => uart_rst,
            uart_txd => uart_txd,
            uart_rxd => uart_rxd,
            tck => tap_tck,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift => tap_shift,
            update => tap_update,
            sel => tap_sel
        );
end architecture rtl;
