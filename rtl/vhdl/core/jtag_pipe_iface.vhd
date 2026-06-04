-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_util_pkg.all;

entity jtag_pipe_iface is
    generic (
        SAMPLE_W       : positive := 8;
        TIMESTAMP_W    : natural := 0;
        DEPTH          : positive := 1024;
        BURST_W        : positive := 256;
        SEG_DEPTH      : positive := 1024;
        BURST_PTR_ADDR : natural := 16#002C#
    );
    port (
        arst : in  std_logic;

        tck      : in  std_logic;
        tdi      : in  std_logic;
        tdo      : out std_logic;
        capture  : in  std_logic;
        shift_en : in  std_logic;
        update   : in  std_logic;
        sel      : in  std_logic;

        reg_clk   : out std_logic;
        reg_rst   : out std_logic;
        reg_wr_en : out std_logic;
        reg_rd_en : out std_logic;
        reg_addr  : out std_logic_vector(15 downto 0);
        reg_wdata : out std_logic_vector(31 downto 0);
        reg_rdata : in  std_logic_vector(31 downto 0);

        mem_addr       : out std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        sample_data    : in  std_logic_vector(SAMPLE_W - 1 downto 0);
        timestamp_data : in  std_logic_vector(fcapz_nonzero_width(TIMESTAMP_W) - 1 downto 0);

        burst_start     : in  std_logic;
        burst_timestamp : in  std_logic;
        burst_ptr_in    : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0)
    );
end entity jtag_pipe_iface;

architecture rtl of jtag_pipe_iface is
    function max_positive(a : positive; b : positive) return positive is
    begin
        if a > b then
            return a;
        end if;
        return b;
    end function;

    function is_power_of_two(n : positive) return boolean is
        variable value : positive := n;
    begin
        while value > 1 loop
            if value mod 2 /= 0 then
                return false;
            end if;
            value := value / 2;
        end loop;
        return true;
    end function;

    constant PTR_W            : positive := fcapz_clog2(DEPTH);
    constant SEG_PTR_W        : positive := fcapz_clog2(SEG_DEPTH);
    constant TS_W_SAFE        : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant SAMPLES_PER_SCAN : positive := BURST_W / SAMPLE_W;
    constant TS_PER_SCAN      : positive := BURST_W / TS_W_SAFE;
    constant MAX_PER_SCAN     : positive := max_positive(SAMPLES_PER_SCAN, TS_PER_SCAN);
    constant LOAD_CTR_W       : positive := fcapz_clog2(MAX_PER_SCAN + 1);
    constant SHIFT_CTR_W      : positive := fcapz_clog2(BURST_W + 1);

    signal sr                : std_logic_vector(BURST_W - 1 downto 0) := (others => '0');
    signal cmd_sr            : std_logic_vector(48 downto 0) := (others => '0');
    signal staging           : std_logic_vector(BURST_W - 1 downto 0) := (others => '0');
    signal rd_off            : unsigned(SEG_PTR_W - 1 downto 0) := (others => '0');
    signal next_off          : unsigned(SEG_PTR_W - 1 downto 0) := (others => '0');
    signal burst_seg_base_r  : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal load_cnt          : unsigned(LOAD_CTR_W - 1 downto 0) := (others => '0');
    signal shift_cnt         : unsigned(SHIFT_CTR_W - 1 downto 0) := (others => '0');
    signal burst_timestamp_r : std_logic := '0';
    signal burst_start_seen  : std_logic := '0';
    signal burst_mode        : std_logic := '0';
    signal loading           : std_logic := '0';
    signal reg_wr_en_r       : std_logic := '0';
    signal reg_rd_en_r       : std_logic := '0';
    signal reg_addr_r        : std_logic_vector(15 downto 0) := (others => '0');
    signal reg_wdata_r       : std_logic_vector(31 downto 0) := (others => '0');

    signal words_per_scan       : unsigned(LOAD_CTR_W - 1 downto 0);
    signal start_words_per_scan : unsigned(LOAD_CTR_W - 1 downto 0);
    signal seg_base_of_ptr      : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_ptr_off        : unsigned(SEG_PTR_W - 1 downto 0);
begin
    assert is_power_of_two(SEG_DEPTH)
        report "jtag_pipe_iface: SEG_DEPTH must be a power of two"
        severity failure;

    tdo       <= sr(0);
    reg_clk   <= tck;
    reg_rst   <= arst;
    reg_wr_en <= reg_wr_en_r;
    reg_rd_en <= reg_rd_en_r;
    reg_addr  <= reg_addr_r;
    reg_wdata <= reg_wdata_r;

    words_per_scan <= to_unsigned(TS_PER_SCAN, LOAD_CTR_W)
        when burst_timestamp_r = '1'
        else to_unsigned(SAMPLES_PER_SCAN, LOAD_CTR_W);
    start_words_per_scan <= to_unsigned(TS_PER_SCAN, LOAD_CTR_W)
        when burst_timestamp = '1'
        else to_unsigned(SAMPLES_PER_SCAN, LOAD_CTR_W);

    g_seg_base_flat : if SEG_DEPTH >= DEPTH generate
        seg_base_of_ptr <= (others => '0');
        burst_ptr_off <= resize(unsigned(burst_ptr_in), SEG_PTR_W);
    end generate;

    g_seg_base_split : if SEG_DEPTH < DEPTH generate
        seg_base_of_ptr <= burst_ptr_in(PTR_W - 1 downto SEG_PTR_W) &
            std_logic_vector(to_unsigned(0, SEG_PTR_W));
        burst_ptr_off <= unsigned(burst_ptr_in(SEG_PTR_W - 1 downto 0));
    end generate;

    g_mem_addr_flat : if SEG_DEPTH >= DEPTH generate
        mem_addr <= std_logic_vector(resize(rd_off, PTR_W));
    end generate;

    g_mem_addr_split : if SEG_DEPTH < DEPTH generate
        mem_addr <= burst_seg_base_r(PTR_W - 1 downto SEG_PTR_W) & std_logic_vector(rd_off);
    end generate;

    p_tck : process(tck, arst)
        variable sample_word : std_logic_vector(BURST_W - 1 downto 0);
    begin
        if arst = '1' then
            sr <= (others => '0');
            cmd_sr <= (others => '0');
            staging <= (others => '0');
            rd_off <= (others => '0');
            next_off <= (others => '0');
            burst_seg_base_r <= (others => '0');
            load_cnt <= (others => '0');
            shift_cnt <= (others => '0');
            burst_timestamp_r <= '0';
            burst_start_seen <= '0';
            burst_mode <= '0';
            loading <= '0';
            reg_wr_en_r <= '0';
            reg_rd_en_r <= '0';
            reg_addr_r <= (others => '0');
            reg_wdata_r <= (others => '0');
        elsif rising_edge(tck) then
            reg_wr_en_r <= '0';
            reg_rd_en_r <= '0';

            if sel = '1' then
                if capture = '1' then
                    shift_cnt <= (others => '0');
                    cmd_sr <= (others => '0');
                    if (burst_start xor burst_start_seen) = '1' then
                        burst_start_seen <= burst_start;
                        burst_mode <= '1';
                        burst_seg_base_r <= seg_base_of_ptr;
                        rd_off <= burst_ptr_off +
                            resize(start_words_per_scan, SEG_PTR_W) -
                            to_unsigned(1, SEG_PTR_W);
                        next_off <= burst_ptr_off + resize(start_words_per_scan, SEG_PTR_W);
                        load_cnt <= (others => '0');
                        burst_timestamp_r <= burst_timestamp;
                        loading <= '1';
                    elsif burst_mode = '1' then
                        sr <= staging;
                        rd_off <= next_off +
                            resize(words_per_scan, SEG_PTR_W) -
                            to_unsigned(1, SEG_PTR_W);
                        next_off <= next_off + resize(words_per_scan, SEG_PTR_W);
                        load_cnt <= (others => '0');
                        loading <= '1';
                    else
                        sr(31 downto 0) <= reg_rdata;
                    end if;
                elsif shift_en = '1' then
                    sr <= tdi & sr(BURST_W - 1 downto 1);
                    cmd_sr <= tdi & cmd_sr(48 downto 1);
                    if shift_cnt /= to_unsigned(BURST_W, SHIFT_CTR_W) then
                        shift_cnt <= shift_cnt + to_unsigned(1, SHIFT_CTR_W);
                    end if;
                elsif update = '1' then
                    if shift_cnt = to_unsigned(49, SHIFT_CTR_W) then
                        reg_addr_r <= cmd_sr(47 downto 32);
                        if cmd_sr(48) = '1' then
                            reg_wdata_r <= cmd_sr(31 downto 0);
                            reg_wr_en_r <= '1';
                            if unsigned(cmd_sr(47 downto 32)) = to_unsigned(BURST_PTR_ADDR, 16) then
                                burst_mode <= '1';
                            else
                                burst_mode <= '0';
                            end if;
                        else
                            reg_rd_en_r <= '1';
                            burst_mode <= '0';
                        end if;
                    end if;
                end if;
            end if;

            if loading = '1' and not (sel = '1' and capture = '1') then
                if load_cnt > 0 then
                    sample_word := (others => '0');
                    if burst_timestamp_r = '1' then
                        sample_word(TS_W_SAFE - 1 downto 0) := timestamp_data;
                        staging <= std_logic_vector(shift_left(unsigned(staging), TS_W_SAFE)) or
                            sample_word;
                    else
                        sample_word(SAMPLE_W - 1 downto 0) := sample_data;
                        staging <= std_logic_vector(shift_left(unsigned(staging), SAMPLE_W)) or
                            sample_word;
                    end if;
                end if;

                if load_cnt = words_per_scan then
                    loading <= '0';
                else
                    rd_off <= rd_off - to_unsigned(1, SEG_PTR_W);
                    load_cnt <= load_cnt + to_unsigned(1, LOAD_CTR_W);
                end if;
            end if;
        end if;
    end process;
end architecture rtl;
