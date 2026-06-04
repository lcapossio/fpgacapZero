-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ejtaguart_xilinx7 is
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
end entity fcapz_ejtaguart_xilinx7;

architecture rtl of fcapz_ejtaguart_xilinx7 is
    component fcapz_ejtaguart_xilinx7_v is
        generic (
            JTAG_CHAIN    : positive;
            CLK_HZ        : positive;
            BAUD_RATE     : positive;
            TX_FIFO_DEPTH : positive;
            RX_FIFO_DEPTH : positive;
            PARITY        : natural
        );
        port (
            uart_clk : in  std_logic;
            uart_rst : in  std_logic;
            uart_txd : out std_logic;
            uart_rxd : in  std_logic
        );
    end component;
begin
    u_impl : fcapz_ejtaguart_xilinx7_v
        generic map (
            JTAG_CHAIN => JTAG_CHAIN,
            CLK_HZ => CLK_HZ,
            BAUD_RATE => BAUD_RATE,
            TX_FIFO_DEPTH => TX_FIFO_DEPTH,
            RX_FIFO_DEPTH => RX_FIFO_DEPTH,
            PARITY => PARITY
        )
        port map (
            uart_clk => uart_clk,
            uart_rst => uart_rst,
            uart_txd => uart_txd,
            uart_rxd => uart_rxd
        );
end architecture rtl;
