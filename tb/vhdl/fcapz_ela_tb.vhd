-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library std;
use std.env.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_ela_tb is
end entity fcapz_ela_tb;

architecture sim of fcapz_ela_tb is
    constant SAMPLE_W : positive := 8;
    constant DEPTH    : positive := 16;
    constant PIPE_DEPTH : positive := 1024;

    signal sample_clk : std_logic := '0';
    signal jtag_clk   : std_logic := '0';
    signal sample_rst : std_logic := '1';
    signal jtag_rst   : std_logic := '1';

    signal probe_in : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trigger_in_dut : std_logic := '0';
    signal trigger_out_dut : std_logic;
    signal armed_out_dut : std_logic;
    signal jtag_wr_en : std_logic := '0';
    signal jtag_rd_en : std_logic := '0';
    signal jtag_addr : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata : std_logic_vector(31 downto 0);
    signal burst_rd_addr : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(0 downto 0);
    signal burst_start : std_logic;
    signal burst_timestamp : std_logic;
    signal burst_start_ptr : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);

    signal probe_in_ts : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal jtag_wr_en_ts : std_logic := '0';
    signal jtag_rd_en_ts : std_logic := '0';
    signal jtag_addr_ts : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata_ts : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_ts : std_logic_vector(31 downto 0);
    signal burst_rd_addr_ts : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data_ts : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_ts : std_logic_vector(31 downto 0);
    signal burst_start_ts : std_logic;
    signal burst_timestamp_ts : std_logic;
    signal burst_start_ptr_ts : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);

    signal probe_in_seg : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal jtag_wr_en_seg : std_logic := '0';
    signal jtag_rd_en_seg : std_logic := '0';
    signal jtag_addr_seg : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata_seg : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_seg : std_logic_vector(31 downto 0);
    signal burst_rd_addr_seg : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data_seg : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_seg : std_logic_vector(0 downto 0);
    signal burst_start_seg : std_logic;
    signal burst_timestamp_seg : std_logic;
    signal burst_start_ptr_seg : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);

    signal probe_in_pmux : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_wr_en_pmux : std_logic := '0';
    signal jtag_rd_en_pmux : std_logic := '0';
    signal jtag_addr_pmux : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata_pmux : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_pmux : std_logic_vector(31 downto 0);
    signal burst_rd_addr_pmux : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data_pmux : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_pmux : std_logic_vector(0 downto 0);
    signal burst_start_pmux : std_logic;
    signal burst_timestamp_pmux : std_logic;
    signal burst_start_ptr_pmux : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);

    signal probe_in_pipe : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trigger_in_pipe : std_logic := '0';
    signal jtag_wr_en_pipe : std_logic := '0';
    signal jtag_rd_en_pipe : std_logic := '0';
    signal jtag_addr_pipe : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata_pipe : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_pipe : std_logic_vector(31 downto 0);
    signal burst_rd_addr_pipe : std_logic_vector(fcapz_clog2(PIPE_DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data_pipe : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_pipe : std_logic_vector(31 downto 0);
    signal burst_start_pipe : std_logic;
    signal burst_timestamp_pipe : std_logic;
    signal burst_start_ptr_pipe : std_logic_vector(fcapz_clog2(PIPE_DEPTH) - 1 downto 0);

    signal probe_in_combo : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal jtag_wr_en_combo : std_logic := '0';
    signal jtag_rd_en_combo : std_logic := '0';
    signal jtag_addr_combo : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_wdata_combo : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_combo : std_logic_vector(31 downto 0);
    signal burst_rd_addr_combo : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0) := (others => '0');
    signal burst_rd_data_combo : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_combo : std_logic_vector(31 downto 0);
    signal burst_start_combo : std_logic;
    signal burst_timestamp_combo : std_logic;
    signal burst_start_ptr_combo : std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
begin
    sample_clk <= not sample_clk after 5 ns;
    jtag_clk <= not jtag_clk after 7 ns;

    dut : entity work.fcapz_ela
        generic map (SAMPLE_W => SAMPLE_W, DEPTH => DEPTH, DECIM_EN => 1, EXT_TRIG_EN => 1)
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in,
            trigger_in => trigger_in_dut, trigger_out => trigger_out_dut, armed_out => armed_out_dut,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en,
            jtag_rd_en => jtag_rd_en, jtag_addr => jtag_addr, jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata, burst_rd_addr => burst_rd_addr,
            burst_rd_data => burst_rd_data, burst_rd_ts_data => burst_rd_ts_data,
            burst_start => burst_start, burst_timestamp => burst_timestamp,
            burst_start_ptr => burst_start_ptr
        );

    dut_ts : entity work.fcapz_ela
        generic map (SAMPLE_W => SAMPLE_W, DEPTH => DEPTH, DECIM_EN => 1, TIMESTAMP_W => 32)
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in_ts,
            trigger_in => '0', trigger_out => open, armed_out => open,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en_ts,
            jtag_rd_en => jtag_rd_en_ts, jtag_addr => jtag_addr_ts, jtag_wdata => jtag_wdata_ts,
            jtag_rdata => jtag_rdata_ts, burst_rd_addr => burst_rd_addr_ts,
            burst_rd_data => burst_rd_data_ts, burst_rd_ts_data => burst_rd_ts_data_ts,
            burst_start => burst_start_ts, burst_timestamp => burst_timestamp_ts,
            burst_start_ptr => burst_start_ptr_ts
        );

    dut_seg : entity work.fcapz_ela
        generic map (SAMPLE_W => SAMPLE_W, DEPTH => DEPTH, NUM_SEGMENTS => 4)
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in_seg,
            trigger_in => '0', trigger_out => open, armed_out => open,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en_seg,
            jtag_rd_en => jtag_rd_en_seg, jtag_addr => jtag_addr_seg, jtag_wdata => jtag_wdata_seg,
            jtag_rdata => jtag_rdata_seg, burst_rd_addr => burst_rd_addr_seg,
            burst_rd_data => burst_rd_data_seg, burst_rd_ts_data => burst_rd_ts_data_seg,
            burst_start => burst_start_seg, burst_timestamp => burst_timestamp_seg,
            burst_start_ptr => burst_start_ptr_seg
        );

    dut_pmux : entity work.fcapz_ela
        generic map (SAMPLE_W => SAMPLE_W, DEPTH => DEPTH, PROBE_MUX_W => 32)
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in_pmux,
            trigger_in => '0', trigger_out => open, armed_out => open,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en_pmux,
            jtag_rd_en => jtag_rd_en_pmux, jtag_addr => jtag_addr_pmux, jtag_wdata => jtag_wdata_pmux,
            jtag_rdata => jtag_rdata_pmux, burst_rd_addr => burst_rd_addr_pmux,
            burst_rd_data => burst_rd_data_pmux, burst_rd_ts_data => burst_rd_ts_data_pmux,
            burst_start => burst_start_pmux, burst_timestamp => burst_timestamp_pmux,
            burst_start_ptr => burst_start_ptr_pmux
        );

    dut_pipe : entity work.fcapz_ela
        generic map (
            SAMPLE_W => SAMPLE_W, DEPTH => PIPE_DEPTH, DECIM_EN => 1,
            EXT_TRIG_EN => 1, TIMESTAMP_W => 32, NUM_SEGMENTS => 4, INPUT_PIPE => 1
        )
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in_pipe,
            trigger_in => trigger_in_pipe, trigger_out => open, armed_out => open,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en_pipe,
            jtag_rd_en => jtag_rd_en_pipe, jtag_addr => jtag_addr_pipe, jtag_wdata => jtag_wdata_pipe,
            jtag_rdata => jtag_rdata_pipe, burst_rd_addr => burst_rd_addr_pipe,
            burst_rd_data => burst_rd_data_pipe, burst_rd_ts_data => burst_rd_ts_data_pipe,
            burst_start => burst_start_pipe, burst_timestamp => burst_timestamp_pipe,
            burst_start_ptr => burst_start_ptr_pipe
        );

    dut_combo : entity work.fcapz_ela
        generic map (
            SAMPLE_W => SAMPLE_W, DEPTH => DEPTH, TRIG_STAGES => 2,
            STOR_QUAL => 1, REL_COMPARE => 1, DUAL_COMPARE => 1,
            NUM_SEGMENTS => 4, TIMESTAMP_W => 32
        )
        port map (
            sample_clk => sample_clk, sample_rst => sample_rst, probe_in => probe_in_combo,
            trigger_in => '0', trigger_out => open, armed_out => open,
            jtag_clk => jtag_clk, jtag_rst => jtag_rst, jtag_wr_en => jtag_wr_en_combo,
            jtag_rd_en => jtag_rd_en_combo, jtag_addr => jtag_addr_combo,
            jtag_wdata => jtag_wdata_combo, jtag_rdata => jtag_rdata_combo,
            burst_rd_addr => burst_rd_addr_combo, burst_rd_data => burst_rd_data_combo,
            burst_rd_ts_data => burst_rd_ts_data_combo, burst_start => burst_start_combo,
            burst_timestamp => burst_timestamp_combo, burst_start_ptr => burst_start_ptr_combo
        );

    p_test : process
        variable pass_count : natural := 0;
        variable fail_count : natural := 0;
        variable status : std_logic_vector(31 downto 0);
        variable word : std_logic_vector(31 downto 0);
        variable cap_len : std_logic_vector(31 downto 0);
        variable ts0 : std_logic_vector(31 downto 0);
        variable ts1 : std_logic_vector(31 downto 0);

        procedure check(constant message : in string; constant cond : in boolean) is
        begin
            if cond then
                report "  PASS: " & message;
                pass_count := pass_count + 1;
            else
                report "  FAIL: " & message severity error;
                fail_count := fail_count + 1;
            end if;
        end procedure;

        procedure write_default(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr <= addr; jtag_wdata <= data; jtag_wr_en <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en <= '0';
        end procedure;

        procedure wait_readback(constant addr : in std_logic_vector(15 downto 0)) is
        begin
            if unsigned(addr) >= to_unsigned(16#0100#, 16) then
                for i in 0 to 8 loop
                    wait until rising_edge(sample_clk);
                end loop;
                for i in 0 to 2 loop
                    wait until rising_edge(jtag_clk);
                end loop;
            else
                wait until rising_edge(jtag_clk);
            end if;
        end procedure;

        procedure read_default(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr <= addr; jtag_rd_en <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en <= '0';
            wait_readback(addr);
            data := jtag_rdata;
        end procedure;

        procedure write_ts(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_ts <= addr; jtag_wdata_ts <= data; jtag_wr_en_ts <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en_ts <= '0';
        end procedure;

        procedure read_ts(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_ts <= addr; jtag_rd_en_ts <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en_ts <= '0';
            wait_readback(addr);
            data := jtag_rdata_ts;
        end procedure;

        procedure write_seg(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_seg <= addr; jtag_wdata_seg <= data; jtag_wr_en_seg <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en_seg <= '0';
        end procedure;

        procedure read_seg(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_seg <= addr; jtag_rd_en_seg <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en_seg <= '0';
            wait_readback(addr);
            data := jtag_rdata_seg;
        end procedure;

        procedure write_pmux(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_pmux <= addr; jtag_wdata_pmux <= data; jtag_wr_en_pmux <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en_pmux <= '0';
        end procedure;

        procedure read_pmux(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_pmux <= addr; jtag_rd_en_pmux <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en_pmux <= '0';
            wait_readback(addr);
            data := jtag_rdata_pmux;
        end procedure;

        procedure write_pipe(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_pipe <= addr; jtag_wdata_pipe <= data; jtag_wr_en_pipe <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en_pipe <= '0';
        end procedure;

        procedure read_pipe(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_pipe <= addr; jtag_rd_en_pipe <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en_pipe <= '0';
            wait_readback(addr);
            data := jtag_rdata_pipe;
        end procedure;

        procedure write_combo(constant addr : in std_logic_vector(15 downto 0); constant data : in std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_combo <= addr; jtag_wdata_combo <= data; jtag_wr_en_combo <= '1';
            wait until rising_edge(jtag_clk);
            jtag_wr_en_combo <= '0';
        end procedure;

        procedure read_combo(constant addr : in std_logic_vector(15 downto 0); variable data : out std_logic_vector(31 downto 0)) is
        begin
            wait until rising_edge(jtag_clk);
            jtag_addr_combo <= addr; jtag_rd_en_combo <= '1';
            wait until rising_edge(jtag_clk);
            jtag_rd_en_combo <= '0';
            wait_readback(addr);
            data := jtag_rdata_combo;
        end procedure;
    begin
        repeat_reset : for i in 0 to 3 loop
            wait until rising_edge(sample_clk);
        end loop;
        sample_rst <= '0';
        wait until rising_edge(jtag_clk);
        wait until rising_edge(jtag_clk);
        jtag_rst <= '0';
        for i in 0 to 3 loop
            wait until rising_edge(jtag_clk);
        end loop;

        report "=== Test 1: Identity and register round-trip ===";
        read_default(x"0000", word);
        check("VERSION matches FCAPZ_ELA_VERSION_REG", word = FCAPZ_ELA_VERSION_REG);
        read_default(x"000C", word);
        check("SAMPLE_W = 8", word = x"00000008");
        read_default(x"0010", word);
        check("DEPTH = 16", word = x"00000010");
        write_default(x"0024", x"DEADBEEF");
        read_default(x"0024", word);
        check("TRIG_VALUE round-trip", word = x"DEADBEEF");
        write_default(x"0028", x"5A5A5A5A");
        read_default(x"0028", word);
        check("TRIG_MASK round-trip", word = x"5A5A5A5A");

        report "=== Test 2: Value-match capture ===";
        write_default(x"0014", x"00000002");
        write_default(x"0018", x"00000003");
        write_default(x"0020", x"00000001");
        write_default(x"0024", x"00000008");
        write_default(x"0028", x"000000FF");
        write_default(x"0004", x"00000001");
        probe_in <= x"00";
        for i in 0 to 15 loop
            wait until rising_edge(sample_clk);
            probe_in <= std_logic_vector(unsigned(probe_in) + 1);
        end loop;
        for i in 0 to 80 loop
            wait until rising_edge(sample_clk);
        end loop;
        read_default(x"0008", status);
        check("Value capture: done", status(2) = '1');
        check("Value capture: triggered", status(1) = '1');
        read_default(x"001C", cap_len);
        check("Value capture: CAPTURE_LEN=6", cap_len = x"00000006");

        report "=== Test 3: Edge trigger ===";
        write_default(x"0004", x"00000002");
        for i in 0 to 8 loop wait until rising_edge(sample_clk); end loop;
        write_default(x"0014", x"00000001");
        write_default(x"0018", x"00000002");
        write_default(x"0020", x"00000002");
        write_default(x"0028", x"00000001");
        write_default(x"0004", x"00000001");
        probe_in <= x"00";
        for i in 0 to 2 loop wait until rising_edge(sample_clk); end loop;
        probe_in <= x"01";
        for i in 0 to 80 loop wait until rising_edge(sample_clk); end loop;
        read_default(x"0008", status);
        check("Edge trigger: done", status(2) = '1');

        report "=== Test 4: Decimation and external trigger ===";
        write_default(x"0004", x"00000002");
        for i in 0 to 8 loop wait until rising_edge(sample_clk); end loop;
        write_default(x"00B0", x"00000003");
        write_default(x"0014", x"00000001");
        write_default(x"0018", x"00000002");
        write_default(x"0020", x"00000001");
        write_default(x"0024", x"00000010");
        write_default(x"0028", x"000000FF");
        write_default(x"0004", x"00000001");
        probe_in <= x"00";
        for i in 0 to 32 loop
            wait until rising_edge(sample_clk);
            probe_in <= std_logic_vector(unsigned(probe_in) + 1);
        end loop;
        for i in 0 to 80 loop wait until rising_edge(sample_clk); end loop;
        read_default(x"0008", status);
        check("DECIM=3: done", status(2) = '1');
        read_default(x"001C", cap_len);
        check("DECIM=3: CAPTURE_LEN=4", cap_len = x"00000004");

        write_default(x"0004", x"00000002");
        for i in 0 to 8 loop wait until rising_edge(sample_clk); end loop;
        write_default(x"00B0", x"00000000");
        write_default(x"00B4", x"00000001");
        write_default(x"0014", x"00000000");
        write_default(x"0018", x"00000002");
        write_default(x"0020", x"00000001");
        write_default(x"0024", x"000000FF");
        write_default(x"0028", x"000000FF");
        write_default(x"0004", x"00000001");
        trigger_in_dut <= '0';
        for i in 0 to 4 loop wait until rising_edge(sample_clk); end loop;
        trigger_in_dut <= '1';
        wait until rising_edge(sample_clk);
        trigger_in_dut <= '0';
        for i in 0 to 80 loop wait until rising_edge(sample_clk); end loop;
        read_default(x"0008", status);
        check("External OR: done", status(2) = '1');

        report "=== Test 5: Timestamp capture ===";
        read_ts(x"003C", word);
        check("TS FEATURES[7]=1", word(7) = '1');
        read_ts(x"00C4", word);
        check("TIMESTAMP_W=32", word = x"00000020");
        write_ts(x"0014", x"00000001");
        write_ts(x"0018", x"00000002");
        write_ts(x"0020", x"00000001");
        write_ts(x"0024", x"00000008");
        write_ts(x"0028", x"000000FF");
        write_ts(x"0004", x"00000001");
        probe_in_ts <= x"00";
        for i in 0 to 24 loop
            wait until rising_edge(sample_clk);
            probe_in_ts <= std_logic_vector(unsigned(probe_in_ts) + 1);
        end loop;
        for i in 0 to 100 loop wait until rising_edge(sample_clk); end loop;
        read_ts(x"0008", status);
        check("TS capture: done", status(2) = '1');
        read_ts(x"0140", ts0);
        read_ts(x"0144", ts1);
        check("TS monotonic", unsigned(ts1) >= unsigned(ts0));

        report "=== Test 6: Segmented capture ===";
        read_seg(x"00B8", word);
        check("NUM_SEGMENTS=4", word = x"00000004");
        write_seg(x"0014", x"00000000");
        write_seg(x"0018", x"00000003");
        write_seg(x"0020", x"00000001");
        write_seg(x"0024", x"00000003");
        write_seg(x"0028", x"00000003");
        write_seg(x"0004", x"00000001");
        probe_in_seg <= x"00";
        for i in 0 to 80 loop
            wait until rising_edge(sample_clk);
            probe_in_seg <= std_logic_vector(unsigned(probe_in_seg) + 1);
        end loop;
        for i in 0 to 120 loop wait until rising_edge(sample_clk); end loop;
        read_seg(x"0008", status);
        check("SEG: done", status(2) = '1');
        read_seg(x"00BC", word);
        check("SEG: all segments done", word(31) = '1');

        report "=== Test 7: Probe mux and readback ===";
        read_pmux(x"00D0", word);
        check("PROBE_MUX_W=32", word = x"00000020");
        write_pmux(x"00AC", x"00000002");
        write_pmux(x"0014", x"00000000");
        write_pmux(x"0018", x"00000002");
        write_pmux(x"0020", x"00000001");
        write_pmux(x"0024", x"000000FF");
        write_pmux(x"0028", x"000000FF");
        write_pmux(x"0004", x"00000001");
        probe_in_pmux <= x"330011AA";
        for i in 0 to 3 loop wait until rising_edge(sample_clk); end loop;
        probe_in_pmux <= x"33FF11AA";
        for i in 0 to 80 loop wait until rising_edge(sample_clk); end loop;
        read_pmux(x"0008", status);
        check("Probe mux slice 2: done", status(2) = '1');
        read_pmux(x"0100", word);
        check("Probe mux first sample is 0xFF", word(7 downto 0) = x"FF");

        report "=== Test 8: Trigger delay and startup/holdoff ===";
        write_default(x"0004", x"00000002");
        for i in 0 to 8 loop wait until rising_edge(sample_clk); end loop;
        write_default(x"0014", x"00000002");
        write_default(x"0018", x"00000003");
        write_default(x"0020", x"00000001");
        write_default(x"0024", x"00000008");
        write_default(x"0028", x"000000FF");
        write_default(x"00D4", x"00000004");
        write_default(x"0004", x"00000001");
        probe_in <= x"00";
        for i in 0 to 24 loop
            wait until rising_edge(sample_clk);
            probe_in <= std_logic_vector(unsigned(probe_in) + 1);
        end loop;
        for i in 0 to 100 loop wait until rising_edge(sample_clk); end loop;
        read_default(x"0008", status);
        check("Delay=4: done", status(2) = '1');
        read_default(x"0108", word);
        check("Delay=4: trigger sample is 12", word(7 downto 0) = x"0C");
        write_default(x"00D4", x"00000000");

        write_default(x"00D8", x"00000001");
        write_default(x"0004", x"00000002");
        for i in 0 to 16 loop wait until rising_edge(sample_clk); end loop;
        read_default(x"0008", status);
        check("STARTUP_ARM: armed after reset", status(0) = '1');
        write_default(x"00D8", x"00000000");

        write_default(x"0004", x"00000002");
        for i in 0 to 8 loop wait until rising_edge(sample_clk); end loop;
        write_default(x"00DC", x"00000004");
        write_default(x"0014", x"00000000");
        write_default(x"0018", x"00000002");
        write_default(x"0020", x"00000001");
        write_default(x"0024", x"00000003");
        write_default(x"0028", x"000000FF");
        write_default(x"0004", x"00000001");
        probe_in <= x"00";
        for i in 0 to 12 loop
            wait until rising_edge(sample_clk);
            probe_in <= std_logic_vector(unsigned(probe_in) + 1);
        end loop;
        read_default(x"0008", status);
        check("TRIG_HOLDOFF: early hit ignored", status(1) = '0' and status(2) = '0');
        write_default(x"00DC", x"00000000");

        report "=== Test 9: INPUT_PIPE=1 capture ===";
        write_pipe(x"0014", x"00000000");
        write_pipe(x"0018", x"00000000");
        write_pipe(x"0020", x"00000001");
        write_pipe(x"0024", x"00000000");
        write_pipe(x"0028", x"000000FF");
        write_pipe(x"0004", x"00000001");
        probe_in_pipe <= x"00";
        for i in 0 to 1200 loop
            wait until rising_edge(sample_clk);
            probe_in_pipe <= std_logic_vector(unsigned(probe_in_pipe) + 1);
        end loop;
        for i in 0 to 120 loop wait until rising_edge(sample_clk); end loop;
        read_pipe(x"0008", status);
        check("INPUT_PIPE=1: done", status(2) = '1');
        read_pipe(x"001C", cap_len);
        check("INPUT_PIPE=1: CAPTURE_LEN=1", cap_len = x"00000001");

        report "=== Test 10: Sequencer, SQ, relational, and dual compare ===";
        read_combo(x"003C", word);
        check("Combo FEATURES advertise SQ", word(4) = '1');
        check("Combo FEATURES advertise 4 segments", word(23 downto 16) = x"04");
        read_combo(x"00E0", word);
        check("Combo compare caps include relational and dual", word = x"000301FF");
        write_combo(x"0030", x"00000001");
        write_combo(x"0034", x"00000000");
        write_combo(x"0038", x"00000001");
        read_combo(x"0030", word);
        check("SQ_MODE round-trip", word = x"00000001");
        write_combo(x"0030", x"00000000");
        write_combo(x"0038", x"00000000");
        write_combo(x"0040", x"00001002");
        write_combo(x"0044", x"0000000A");
        write_combo(x"0048", x"000000FF");
        write_combo(x"004C", x"00000055");
        write_combo(x"0050", x"000000FF");
        read_combo(x"004C", word);
        check("Sequencer B value round-trip when dual enabled", word = x"00000055");
        write_combo(x"0014", x"00000000");
        write_combo(x"0018", x"00000002");
        write_combo(x"0004", x"00000001");
        probe_in_combo <= x"08";
        for i in 0 to 100 loop
            wait until rising_edge(sample_clk);
            probe_in_combo <= x"08";
        end loop;
        read_combo(x"0008", status);
        check("Sequencer LT capture reaches done", status(2) = '1');
        read_combo(x"001C", cap_len);
        check("Sequencer LT capture length is 3", cap_len = x"00000003");

        report "=== Summary: " & integer'image(pass_count) & " passed, " &
               integer'image(fail_count) & " failed ===";
        assert fail_count = 0 report "ELA VHDL testbench: failures detected" severity failure;
        finish;
    end process;
end architecture sim;
