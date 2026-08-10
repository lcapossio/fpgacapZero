-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-- Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

library ieee;
use ieee.std_logic_1164.all;

entity dff_reg_sync is
    generic (
        pREG_LEN     : positive := 8;
        pSYNC_STAGES : positive := 2
    );
    port (
        clk      : in  std_logic;
        srst     : in  std_logic;
        syncreg  : out std_logic_vector(pREG_LEN - 1 downto 0);
        asyncreg : in  std_logic_vector(pREG_LEN - 1 downto 0)
    );
end entity dff_reg_sync;

architecture rtl of dff_reg_sync is
begin
    g_bits : for i in 0 to pREG_LEN - 1 generate
        u_sync : entity work.dff_sync
            generic map (
                pSYNC_STAGES => pSYNC_STAGES
            )
            port map (
                clk   => clk,
                srst  => srst,
                sync  => syncreg(i),
                async => asyncreg(i)
            );
    end generate;
end architecture rtl;
