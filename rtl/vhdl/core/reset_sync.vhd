-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity reset_sync is
    generic (
        STAGES : positive := 2
    );
    port (
        clk  : in  std_logic;
        arst : in  std_logic;
        srst : out std_logic
    );
end entity reset_sync;

architecture rtl of reset_sync is
    signal sync_ff : std_logic_vector(STAGES - 1 downto 0) := (others => '1');
    attribute ASYNC_REG : string;
    attribute ASYNC_REG of sync_ff : signal is "TRUE";
begin
    srst <= sync_ff(STAGES - 1);

    p_sync : process(clk, arst)
    begin
        if arst = '1' then
            sync_ff <= (others => '1');
        elsif rising_edge(clk) then
            sync_ff <= sync_ff(STAGES - 2 downto 0) & '0';
        end if;
    end process;
end architecture rtl;
