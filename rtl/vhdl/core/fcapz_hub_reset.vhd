-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

-- Resets of a core-manager hub, all on TCK; see fcapz_hub_reset.v.
entity fcapz_hub_reset is
    generic (
        TLR_RESET_EN : natural := 0
    );
    port (
        tck            : in  std_logic;
        any_sample_rst : in  std_logic;
        -- Power-on reset where initial values are dropped; see fcapz_hub_reset.v.
        hub_por        : in  std_logic;
        tlr            : in  std_logic;
        por_rst        : out std_logic;
        proto_rst      : out std_logic;
        tlr_sync       : out std_logic
    );
end entity fcapz_hub_reset;

architecture rtl of fcapz_hub_reset is
    signal por_sync    : std_logic;
    signal tlr_sync_i  : std_logic;
    signal por_rst_i   : std_logic;
    signal por_arst    : std_logic;
    -- Set once the power-up reset has released; never cleared.
    signal hub_started : std_logic := '0';
begin
    u_por_sync : entity work.reset_sync
        port map (
            clk  => tck,
            arst => por_arst,
            srst => por_sync
        );

    -- Powers up low; see fcapz_hub_reset.v.
    u_tlr_sync : entity work.reset_sync
        generic map (
            INIT => 0
        )
        port map (
            clk  => tck,
            arst => tlr,
            srst => tlr_sync_i
        );

    por_arst <= any_sample_rst or hub_por;

    p_started : process(tck, hub_por)
    begin
        if hub_por = '1' then
            hub_started <= '0';
        elsif rising_edge(tck) then
            if por_sync = '0' then
                hub_started <= '1';
            end if;
        end if;
    end process;

    por_rst_i <= por_sync and not hub_started;
    por_rst <= por_rst_i;
    proto_rst <= por_rst_i or tlr_sync_i when TLR_RESET_EN /= 0 else por_rst_i;
    tlr_sync <= tlr_sync_i;
end architecture rtl;
