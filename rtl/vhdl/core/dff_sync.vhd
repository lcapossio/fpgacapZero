-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-- Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

library ieee;
use ieee.std_logic_1164.all;

entity dff_sync is
    generic (
        pSYNC_STAGES  : positive := 2;
        pSYNC_DEFAULT : std_logic := '0'
    );
    port (
        clk   : in  std_logic;
        srst  : in  std_logic;
        sync  : out std_logic;
        async : in  std_logic
    );
end entity dff_sync;

architecture rtl of dff_sync is
    signal sync_stages : std_logic_vector(pSYNC_STAGES - 1 downto 0) :=
        (others => pSYNC_DEFAULT);
begin
    assert pSYNC_STAGES >= 2
        report "dff_sync: pSYNC_STAGES must be >= 2"
        severity failure;

    sync <= sync_stages(pSYNC_STAGES - 1);

    p_sync : process(clk)
    begin
        if rising_edge(clk) then
            if srst = '1' then
                sync_stages <= (others => pSYNC_DEFAULT);
            else
                sync_stages <= sync_stages(pSYNC_STAGES - 2 downto 0) & async;
            end if;
        end if;
    end process;
end architecture rtl;
