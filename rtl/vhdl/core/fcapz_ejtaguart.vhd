-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ejtaguart is
    generic (
        CLK_HZ               : positive := 100000000;
        BAUD_RATE            : positive := 115200;
        TX_FIFO_DEPTH        : positive := 256;
        RX_FIFO_DEPTH        : positive := 256;
        PARITY               : natural := 0;
        USE_BEHAV_ASYNC_FIFO : natural := 1
    );
    port (
        uart_clk : in  std_logic;
        uart_rst : in  std_logic;
        uart_txd : out std_logic;
        uart_rxd : in  std_logic;
        tck      : in  std_logic;
        tdi      : in  std_logic;
        tdo      : out std_logic;
        capture  : in  std_logic;
        shift    : in  std_logic;
        update   : in  std_logic;
        sel      : in  std_logic
    );
end entity fcapz_ejtaguart;

architecture rtl of fcapz_ejtaguart is
    component fcapz_ejtaguart_v is
        generic (
            CLK_HZ               : positive;
            BAUD_RATE            : positive;
            TX_FIFO_DEPTH        : positive;
            RX_FIFO_DEPTH        : positive;
            PARITY               : natural;
            USE_BEHAV_ASYNC_FIFO : natural
        );
        port (
            uart_clk : in  std_logic;
            uart_rst : in  std_logic;
            uart_txd : out std_logic;
            uart_rxd : in  std_logic;
            tck      : in  std_logic;
            tdi      : in  std_logic;
            tdo      : out std_logic;
            capture  : in  std_logic;
            shift    : in  std_logic;
            update   : in  std_logic;
            sel      : in  std_logic
        );
    end component;
begin
    u_impl : fcapz_ejtaguart_v
        generic map (
            CLK_HZ               => CLK_HZ,
            BAUD_RATE            => BAUD_RATE,
            TX_FIFO_DEPTH        => TX_FIFO_DEPTH,
            RX_FIFO_DEPTH        => RX_FIFO_DEPTH,
            PARITY               => PARITY,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO
        )
        port map (
            uart_clk => uart_clk,
            uart_rst => uart_rst,
            uart_txd => uart_txd,
            uart_rxd => uart_rxd,
            tck      => tck,
            tdi      => tdi,
            tdo      => tdo,
            capture  => capture,
            shift    => shift,
            update   => update,
            sel      => sel
        );
end architecture rtl;
