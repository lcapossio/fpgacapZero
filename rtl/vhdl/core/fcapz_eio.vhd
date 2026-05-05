-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;

entity fcapz_eio is
    generic (
        IN_W  : positive := 32;
        OUT_W : positive := 32
    );
    port (
        probe_in   : in  std_logic_vector(IN_W - 1 downto 0);
        probe_out  : out std_logic_vector(OUT_W - 1 downto 0);

        jtag_clk   : in  std_logic;
        jtag_rst   : in  std_logic;
        jtag_wr_en : in  std_logic;
        jtag_addr  : in  std_logic_vector(15 downto 0);
        jtag_wdata : in  std_logic_vector(31 downto 0);
        jtag_rdata : out std_logic_vector(31 downto 0)
    );
end entity fcapz_eio;

architecture rtl of fcapz_eio is
    constant IN_WORDS  : positive := (IN_W + 31) / 32;
    constant OUT_WORDS : positive := (OUT_W + 31) / 32;
    constant IN_PAD    : positive := IN_WORDS * 32;
    constant OUT_PAD   : positive := OUT_WORDS * 32;

    constant ADDR_VERSION  : natural := 16#0000#;
    constant ADDR_IN_W     : natural := 16#0004#;
    constant ADDR_OUT_W    : natural := 16#0008#;
    constant ADDR_IN_BASE  : natural := 16#0010#;
    constant ADDR_OUT_BASE : natural := 16#0100#;

    signal out_regs     : std_logic_vector(OUT_PAD - 1 downto 0) := (others => '0');
    signal probe_in_pad : std_logic_vector(IN_PAD - 1 downto 0);
    signal in_sync1     : std_logic_vector(IN_PAD - 1 downto 0) := (others => '0');
    signal in_sync2     : std_logic_vector(IN_PAD - 1 downto 0) := (others => '0');
begin
    probe_out <= out_regs(OUT_W - 1 downto 0);

    p_probe_in_pad : process(all)
    begin
        probe_in_pad <= (others => '0');
        probe_in_pad(IN_W - 1 downto 0) <= probe_in;
    end process;

    p_out_regs : process(jtag_clk, jtag_rst)
        variable addr : natural;
        variable idx  : natural;
    begin
        if jtag_rst = '1' then
            out_regs <= (others => '0');
        elsif rising_edge(jtag_clk) then
            addr := to_integer(unsigned(jtag_addr));
            if jtag_wr_en = '1' and
               addr >= ADDR_OUT_BASE and
               addr < ADDR_OUT_BASE + OUT_WORDS * 4 then
                idx := (addr - ADDR_OUT_BASE) / 4;
                out_regs(idx * 32 + 31 downto idx * 32) <= jtag_wdata;
            end if;
        end if;
    end process;

    p_input_sync : process(jtag_clk, jtag_rst)
    begin
        if jtag_rst = '1' then
            in_sync1 <= (others => '0');
            in_sync2 <= (others => '0');
        elsif rising_edge(jtag_clk) then
            in_sync1 <= probe_in_pad;
            in_sync2 <= in_sync1;
        end if;
    end process;

    p_rdata : process(all)
        variable addr  : natural;
        variable idx   : natural;
        variable rdata : std_logic_vector(31 downto 0);
    begin
        addr := to_integer(unsigned(jtag_addr));
        rdata := (others => '0');

        if addr = ADDR_VERSION then
            rdata := FCAPZ_EIO_VERSION_REG;
        elsif addr = ADDR_IN_W then
            rdata := std_logic_vector(to_unsigned(IN_W, 32));
        elsif addr = ADDR_OUT_W then
            rdata := std_logic_vector(to_unsigned(OUT_W, 32));
        elsif addr >= ADDR_IN_BASE and
              addr < ADDR_IN_BASE + IN_WORDS * 4 then
            idx := (addr - ADDR_IN_BASE) / 4;
            rdata := in_sync2(idx * 32 + 31 downto idx * 32);
        elsif addr >= ADDR_OUT_BASE and
              addr < ADDR_OUT_BASE + OUT_WORDS * 4 then
            idx := (addr - ADDR_OUT_BASE) / 4;
            rdata := out_regs(idx * 32 + 31 downto idx * 32);
        end if;

        jtag_rdata <= rdata;
    end process;
end architecture rtl;
