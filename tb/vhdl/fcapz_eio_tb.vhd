-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library std;
use std.env.all;

library work;
use work.fcapz_pkg.all;

entity fcapz_eio_tb is
end entity fcapz_eio_tb;

architecture sim of fcapz_eio_tb is
    constant IN_W  : positive := 16;
    constant OUT_W : positive := 12;

    signal jtag_clk   : std_logic := '0';
    signal jtag_rst   : std_logic := '1';
    signal fabric_clk : std_logic := '0';

    signal probe_in   : std_logic_vector(IN_W - 1 downto 0) := (others => '0');
    signal probe_out  : std_logic_vector(OUT_W - 1 downto 0);
    signal jtag_wr_en : std_logic := '0';
    signal jtag_addr  : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata : std_logic_vector(31 downto 0);

begin
    dut : entity work.fcapz_eio
        generic map (
            IN_W  => IN_W,
            OUT_W => OUT_W
        )
        port map (
            probe_in   => probe_in,
            probe_out  => probe_out,
            jtag_clk   => jtag_clk,
            jtag_rst   => jtag_rst,
            jtag_wr_en => jtag_wr_en,
            jtag_addr  => jtag_addr,
            jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata
        );

    jtag_clk <= not jtag_clk after 7 ns;
    fabric_clk <= not fabric_clk after 5 ns;

    p_test : process
        variable rdata : std_logic_vector(31 downto 0);
        variable pass_count : natural := 0;
        variable fail_count : natural := 0;

        procedure check(
            constant message : in string;
            constant cond : in boolean
        ) is
        begin
            if cond then
                report "  PASS: " & message;
                pass_count := pass_count + 1;
            else
                report "  FAIL: " & message severity error;
                fail_count := fail_count + 1;
            end if;
        end procedure;

        procedure vio_write(
            constant addr : in std_logic_vector(15 downto 0);
            constant data : in std_logic_vector(31 downto 0)
        ) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr <= addr;
            jtag_wdata <= data;
            jtag_wr_en <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en <= '0';
        end procedure;

        procedure vio_read(
            constant addr : in std_logic_vector(15 downto 0);
            variable data : out std_logic_vector(31 downto 0)
        ) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr <= addr;
            wait until rising_edge(jtag_clk);
            data := jtag_rdata;
        end procedure;
    begin
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        jtag_rst <= '0';
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);

        report "=== Test 1: Identity registers ===";
        vio_read(x"0000", rdata);
        check("VERSION matches FCAPZ_EIO_VERSION_REG", rdata = FCAPZ_EIO_VERSION_REG);
        check("VERSION core_id == FCAPZ_EIO_CORE_ID", rdata(15 downto 0) = FCAPZ_EIO_CORE_ID);
        check("VERSION minor == FCAPZ_VERSION_MINOR", rdata(23 downto 16) = FCAPZ_VERSION_MINOR);
        check("VERSION major == FCAPZ_VERSION_MAJOR", rdata(31 downto 24) = FCAPZ_VERSION_MAJOR);

        vio_read(x"0004", rdata);
        check("EIO_IN_W = 16", rdata = std_logic_vector(to_unsigned(IN_W, 32)));

        vio_read(x"0008", rdata);
        check("EIO_OUT_W = 12", rdata = std_logic_vector(to_unsigned(OUT_W, 32)));

        report "=== Test 2: Output write/readback ===";
        vio_write(x"0100", x"00000ABC");
        wait for 1 ns;
        vio_read(x"0100", rdata);
        check("OUT[0] readback = 0xABC", rdata = x"00000ABC");
        check("probe_out = 12'hABC", probe_out = x"ABC");

        vio_write(x"0100", x"00000000");
        wait for 1 ns;
        vio_read(x"0100", rdata);
        check("OUT[0] cleared", rdata = x"00000000");
        check("probe_out cleared", probe_out = x"000");

        vio_write(x"0100", x"00000FFF");
        wait for 1 ns;
        check("probe_out all ones", probe_out = x"FFF");

        report "=== Test 3: Reset clears outputs ===";
        vio_write(x"0100", x"00000555");
        jtag_rst <= '1';
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        jtag_rst <= '0';
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);

        wait for 1 ns;
        vio_read(x"0100", rdata);
        check("OUT[0] = 0 after reset", rdata = x"00000000");
        check("probe_out = 0 after reset", probe_out = x"000");

        report "=== Test 4: Input probe read after CDC ===";
        probe_in <= x"CAFE";
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);

        vio_read(x"0010", rdata);
        check("IN[0] = 0xCAFE", rdata = x"0000CAFE");

        probe_in <= x"1234";
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);

        vio_read(x"0010", rdata);
        check("IN[0] = 0x1234 after change", rdata = x"00001234");

        report "=== Test 5: Wide probe one word ===";
        probe_in <= x"FFFF";
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        vio_read(x"0010", rdata);
        check("IN[0] = 0xFFFF", rdata = x"0000FFFF");

        probe_in <= x"0001";
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        vio_read(x"0010", rdata);
        check("IN[0] = 0x0001", rdata = x"00000001");

        report "=== Test 6: Unknown address returns 0 ===";
        vio_read(x"0200", rdata);
        check("Unknown addr reads 0", rdata = x"00000000");

        report "=== Test 7: Bit-level output control ===";
        vio_write(x"0100", x"00000000");
        vio_read(x"0100", rdata);
        vio_write(x"0100", rdata or x"00000008");
        vio_read(x"0100", rdata);
        check("Bit 3 set", rdata(3) = '1');
        check("Other bits unchanged", (rdata and x"FFFFFFF7") = x"00000000");
        vio_write(x"0100", rdata and x"FFFFFFF7");
        vio_read(x"0100", rdata);
        check("Bit 3 cleared", rdata(3) = '0');

        wait for 0 ns;
        report "=== Summary: " & integer'image(pass_count) & " passed, " &
               integer'image(fail_count) & " failed ===";
        assert fail_count = 0 report "EIO VHDL testbench: failures detected" severity failure;
        finish;
    end process;
end architecture sim;
