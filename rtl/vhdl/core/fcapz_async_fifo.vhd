-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_async_fifo is
    generic (
        DATA_W               : positive := 32;
        DEPTH                : positive := 16;
        USE_BEHAV_ASYNC_FIFO : natural := 1;
        ASYNC_FIFO_IMPL      : integer := -1;
        XPM_FIFO_MEMORY_TYPE : string := "auto"
    );
    port (
        wr_clk      : in  std_logic;
        wr_rst      : in  std_logic;
        wr_en       : in  std_logic;
        wr_data     : in  std_logic_vector(DATA_W - 1 downto 0);
        wr_full     : out std_logic;
        wr_rst_busy : out std_logic;

        rd_clk      : in  std_logic;
        rd_rst      : in  std_logic;
        rd_en       : in  std_logic;
        rd_data     : out std_logic_vector(DATA_W - 1 downto 0);
        rd_empty    : out std_logic;
        rd_rst_busy : out std_logic;

        rd_count : out std_logic_vector(fcapz_clog2(DEPTH) downto 0);
        wr_count : out std_logic_vector(fcapz_clog2(DEPTH) downto 0)
    );
end entity fcapz_async_fifo;

architecture rtl of fcapz_async_fifo is
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

    function effective_fifo_impl(use_behavioral : natural; impl : integer) return natural is
    begin
        if impl >= 0 then
            return natural(impl);
        elsif use_behavioral /= 0 then
            return 0;
        end if;
        return 1;
    end function;

    constant AW        : positive := fcapz_clog2(DEPTH);
    constant FIFO_IMPL : natural := effective_fifo_impl(USE_BEHAV_ASYNC_FIFO, ASYNC_FIFO_IMPL);

    component xpm_fifo_async is
        generic (
            CDC_SYNC_STAGES     : integer := 2;
            FIFO_MEMORY_TYPE    : string := "auto";
            FIFO_READ_LATENCY   : integer := 0;
            FIFO_WRITE_DEPTH    : integer := 16;
            READ_DATA_WIDTH     : integer := 32;
            READ_MODE           : string := "fwft";
            WRITE_DATA_WIDTH    : integer := 32;
            FULL_RESET_VALUE    : integer := 0;
            RD_DATA_COUNT_WIDTH : integer := 5;
            WR_DATA_COUNT_WIDTH : integer := 5;
            USE_ADV_FEATURES    : string := "0404"
        );
        port (
            wr_clk        : in  std_logic;
            rst           : in  std_logic;
            wr_en         : in  std_logic;
            din           : in  std_logic_vector(DATA_W - 1 downto 0);
            full          : out std_logic;
            rd_clk        : in  std_logic;
            rd_en         : in  std_logic;
            dout          : out std_logic_vector(DATA_W - 1 downto 0);
            empty         : out std_logic;
            rd_data_count : out std_logic_vector(AW downto 0);
            wr_data_count : out std_logic_vector(AW downto 0);
            wr_rst_busy   : out std_logic;
            rd_rst_busy   : out std_logic;
            almost_full   : out std_logic;
            almost_empty  : out std_logic;
            data_valid    : out std_logic;
            overflow      : out std_logic;
            underflow     : out std_logic;
            prog_full     : out std_logic;
            prog_empty    : out std_logic;
            sleep         : in  std_logic;
            injectsbiterr : in  std_logic;
            injectdbiterr : in  std_logic;
            sbiterr       : out std_logic;
            dbiterr       : out std_logic
        );
    end component;
begin
    assert is_power_of_two(DEPTH)
        report "fcapz_async_fifo: DEPTH must be a power of two"
        severity failure;

    g_xpm : if FIFO_IMPL = 1 generate
        signal unused_almost_full  : std_logic;
        signal unused_almost_empty : std_logic;
        signal unused_data_valid   : std_logic;
        signal unused_overflow     : std_logic;
        signal unused_underflow    : std_logic;
        signal unused_prog_full    : std_logic;
        signal unused_prog_empty   : std_logic;
        signal unused_sbiterr      : std_logic;
        signal unused_dbiterr      : std_logic;
    begin
        assert DEPTH >= 16
            report "fcapz_async_fifo: XPM FIFO depth must be >= 16"
            severity failure;

        u_xpm_fifo : xpm_fifo_async
            generic map (
                CDC_SYNC_STAGES     => 2,
                FIFO_MEMORY_TYPE    => XPM_FIFO_MEMORY_TYPE,
                FIFO_READ_LATENCY   => 0,
                FIFO_WRITE_DEPTH    => DEPTH,
                READ_DATA_WIDTH     => DATA_W,
                READ_MODE           => "fwft",
                WRITE_DATA_WIDTH    => DATA_W,
                FULL_RESET_VALUE    => 0,
                RD_DATA_COUNT_WIDTH => AW + 1,
                WR_DATA_COUNT_WIDTH => AW + 1,
                USE_ADV_FEATURES    => "0404"
            )
            port map (
                wr_clk        => wr_clk,
                rst           => wr_rst or rd_rst,
                wr_en         => wr_en,
                din           => wr_data,
                full          => wr_full,
                rd_clk        => rd_clk,
                rd_en         => rd_en,
                dout          => rd_data,
                empty         => rd_empty,
                rd_data_count => rd_count,
                wr_data_count => wr_count,
                wr_rst_busy   => wr_rst_busy,
                rd_rst_busy   => rd_rst_busy,
                almost_full   => unused_almost_full,
                almost_empty  => unused_almost_empty,
                data_valid    => unused_data_valid,
                overflow      => unused_overflow,
                underflow     => unused_underflow,
                prog_full     => unused_prog_full,
                prog_empty    => unused_prog_empty,
                sleep         => '0',
                injectsbiterr => '0',
                injectdbiterr => '0',
                sbiterr       => unused_sbiterr,
                dbiterr       => unused_dbiterr
            );
    end generate;

    g_behavioral : if FIFO_IMPL /= 1 generate
        type mem_t is array (0 to DEPTH - 1) of std_logic_vector(DATA_W - 1 downto 0);

        function bin2gray(b : unsigned(AW downto 0)) return unsigned is
        begin
            return b xor shift_right(b, 1);
        end function;

        function gray2bin(g : unsigned(AW downto 0)) return unsigned is
            variable result : unsigned(AW downto 0);
        begin
            result(AW) := g(AW);
            for k in AW - 1 downto 0 loop
                result(k) := result(k + 1) xor g(k);
            end loop;
            return result;
        end function;

        signal mem : mem_t;

        signal wptr_bin  : unsigned(AW downto 0) := (others => '0');
        signal wptr_gray : unsigned(AW downto 0) := (others => '0');
        signal rptr_sync1_w : unsigned(AW downto 0) := (others => '0');
        signal rptr_sync2_w : unsigned(AW downto 0) := (others => '0');

        signal rptr_gray : unsigned(AW downto 0) := (others => '0');
        signal rptr_bin  : unsigned(AW downto 0);
        signal wptr_sync1_r : unsigned(AW downto 0) := (others => '0');
        signal wptr_sync2_r : unsigned(AW downto 0) := (others => '0');

        signal wr_full_i   : std_logic;
        signal rd_empty_i  : std_logic;
        signal wptr_bin_rd : unsigned(AW downto 0);
        signal rptr_bin_wr : unsigned(AW downto 0);

        attribute ASYNC_REG : string;
        attribute ASYNC_REG of rptr_sync1_w : signal is "TRUE";
        attribute ASYNC_REG of rptr_sync2_w : signal is "TRUE";
        attribute ASYNC_REG of wptr_sync1_r : signal is "TRUE";
        attribute ASYNC_REG of wptr_sync2_r : signal is "TRUE";
    begin
        wr_full <= wr_full_i;
        rd_empty <= rd_empty_i;
        wr_rst_busy <= '0';
        rd_rst_busy <= '0';

        rptr_bin <= gray2bin(rptr_gray);
        wptr_bin_rd <= gray2bin(wptr_sync2_r);
        rptr_bin_wr <= gray2bin(rptr_sync2_w);

        wr_full_i <= '1' when wptr_gray =
            (not rptr_sync2_w(AW downto AW - 1)) & rptr_sync2_w(AW - 2 downto 0)
            else '0';
        rd_empty_i <= '1' when rptr_gray = wptr_sync2_r else '0';

        rd_data <= mem(to_integer(rptr_bin(AW - 1 downto 0)));
        rd_count <= std_logic_vector(wptr_bin_rd - rptr_bin);
        wr_count <= std_logic_vector(wptr_bin - rptr_bin_wr);

        p_wr_sync : process(wr_clk, wr_rst)
        begin
            if wr_rst = '1' then
                rptr_sync1_w <= (others => '0');
                rptr_sync2_w <= (others => '0');
            elsif rising_edge(wr_clk) then
                rptr_sync1_w <= rptr_gray;
                rptr_sync2_w <= rptr_sync1_w;
            end if;
        end process;

        p_wr : process(wr_clk, wr_rst)
            variable wptr_next : unsigned(AW downto 0);
        begin
            if wr_rst = '1' then
                wptr_bin <= (others => '0');
                wptr_gray <= (others => '0');
            elsif rising_edge(wr_clk) then
                if wr_en = '1' and wr_full_i = '0' then
                    mem(to_integer(wptr_bin(AW - 1 downto 0))) <= wr_data;
                    wptr_next := wptr_bin + to_unsigned(1, AW + 1);
                    wptr_bin <= wptr_next;
                    wptr_gray <= bin2gray(wptr_next);
                end if;
            end if;
        end process;

        p_rd_sync : process(rd_clk, rd_rst)
        begin
            if rd_rst = '1' then
                wptr_sync1_r <= (others => '0');
                wptr_sync2_r <= (others => '0');
            elsif rising_edge(rd_clk) then
                wptr_sync1_r <= wptr_gray;
                wptr_sync2_r <= wptr_sync1_r;
            end if;
        end process;

        p_rd : process(rd_clk, rd_rst)
        begin
            if rd_rst = '1' then
                rptr_gray <= (others => '0');
            elsif rising_edge(rd_clk) then
                if rd_en = '1' and rd_empty_i = '0' then
                    rptr_gray <= bin2gray(rptr_bin + to_unsigned(1, AW + 1));
                end if;
            end if;
        end process;
    end generate;
end architecture rtl;
