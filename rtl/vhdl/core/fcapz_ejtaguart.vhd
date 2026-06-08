-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_ejtaguart is
    generic (
        CLK_HZ               : positive := 100_000_000;
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

    function xor_reduce(value : std_logic_vector) return std_logic is
        variable result : std_logic := '0';
    begin
        for i in value'range loop
            result := result xor value(i);
        end loop;
        return result;
    end function;

    function frame_bits_for(parity_mode : natural) return positive is
    begin
        if parity_mode = 0 then
            return 10;
        end if;
        return 11;
    end function;

    constant DR_W       : positive := 32;
    constant CMD_NOP    : std_logic_vector(3 downto 0) := x"0";
    constant CMD_TX_PUSH : std_logic_vector(3 downto 0) := x"1";
    constant CMD_RX_POP : std_logic_vector(3 downto 0) := x"2";
    constant CMD_TXRX   : std_logic_vector(3 downto 0) := x"3";
    constant CMD_CONFIG : std_logic_vector(3 downto 0) := x"E";
    constant CMD_RESET  : std_logic_vector(3 downto 0) := x"F";

    constant BAUD_DIV  : positive := CLK_HZ / BAUD_RATE;
    constant HALF_BAUD : positive := BAUD_DIV / 2;
    constant FRAME_BITS : positive := frame_bits_for(PARITY);
    constant TX_AW : positive := fcapz_clog2(TX_FIFO_DEPTH);
    constant RX_AW : positive := fcapz_clog2(RX_FIFO_DEPTH);

    constant FEATURES : std_logic_vector(31 downto 0) :=
        std_logic_vector(to_unsigned(PARITY, 2)) &
        std_logic_vector(to_unsigned(TX_FIFO_DEPTH, 14)) &
        std_logic_vector(to_unsigned(RX_FIFO_DEPTH, 14)) &
        "00";
    constant BAUD_DIV_R : std_logic_vector(31 downto 0) :=
        std_logic_vector(to_unsigned(BAUD_DIV, 32));

    signal sr : std_logic_vector(DR_W - 1 downto 0) := (others => '0');
    signal sr_tx_byte : std_logic_vector(7 downto 0);
    signal sr_cmd : std_logic_vector(3 downto 0);

    signal rx_byte_reg : std_logic_vector(7 downto 0) := (others => '0');
    signal rx_valid_reg : std_logic := '0';
    signal config_byte_reg : std_logic_vector(7 downto 0) := (others => '0');
    signal config_valid_reg : std_logic := '0';
    signal rx_overflow_sticky : std_logic := '0';
    signal frame_err_sticky : std_logic := '0';
    signal fifo_rst : std_logic := '0';
    signal fifo_rst_cnt : unsigned(2 downto 0) := (others => '0');

    signal rx_fifo_rst_sync1 : std_logic := '0';
    signal rx_fifo_rst_sync2 : std_logic := '0';

    signal tx_fifo_full : std_logic;
    signal tx_fifo_rd_en_r : std_logic := '0';
    signal tx_fifo_rdata : std_logic_vector(7 downto 0);
    signal tx_fifo_empty : std_logic;
    signal tx_fifo_wr_count : std_logic_vector(TX_AW downto 0);
    signal tx_fifo_wr_rst_busy_unused : std_logic;
    signal tx_fifo_rd_rst_busy_unused : std_logic;
    signal tx_wr_pulse : std_logic := '0';
    signal tx_fifo_wr_rst : std_logic;
    signal tx_fifo_rd_rst : std_logic;

    signal tx_free_32 : unsigned(31 downto 0);
    signal tx_free_sat : std_logic_vector(7 downto 0);

    signal rx_fifo_full : std_logic;
    signal rx_fifo_rdata : std_logic_vector(7 downto 0);
    signal rx_fifo_empty : std_logic;
    signal rx_fifo_rd_count : std_logic_vector(RX_AW downto 0);
    signal rx_fifo_wr_rst_busy_unused : std_logic;
    signal rx_fifo_rd_rst_busy_unused : std_logic;
    signal rx_rd_pulse : std_logic := '0';
    signal rx_fifo_wr_en_r : std_logic := '0';
    signal rx_fifo_wr_data_r : std_logic_vector(7 downto 0) := (others => '0');
    signal rx_fifo_wr_rst : std_logic;

    signal rx_ready : std_logic;
    signal config_byte : std_logic_vector(7 downto 0);
    signal status_byte : std_logic_vector(7 downto 0);
    signal capture_rx_byte : std_logic_vector(7 downto 0);

    signal rx_overflow_uart : std_logic := '0';
    signal frame_err_uart : std_logic := '0';
    signal rx_overflow_sync1 : std_logic := '0';
    signal rx_overflow_sync2 : std_logic := '0';
    signal frame_err_sync1 : std_logic := '0';
    signal frame_err_sync2 : std_logic := '0';

    signal tx_bit_cnt : unsigned(3 downto 0) := (others => '0');
    signal tx_sr : std_logic_vector(10 downto 0) := (others => '1');
    signal tx_active : std_logic := '0';
    signal tx_baud_cnt : unsigned(31 downto 0) := (others => '0');

    signal rxd_sync1 : std_logic := '1';
    signal rxd_sync2 : std_logic := '1';
    signal rx_baud_cnt : unsigned(31 downto 0) := (others => '0');
    signal rx_bit_idx : unsigned(3 downto 0) := (others => '0');
    signal rx_shift_reg : std_logic_vector(7 downto 0) := (others => '0');
    signal rx_active : std_logic := '0';

    attribute ASYNC_REG : string;
    attribute ASYNC_REG of rx_fifo_rst_sync1 : signal is "TRUE";
    attribute ASYNC_REG of rx_fifo_rst_sync2 : signal is "TRUE";
    attribute ASYNC_REG of rx_overflow_sync1 : signal is "TRUE";
    attribute ASYNC_REG of rx_overflow_sync2 : signal is "TRUE";
    attribute ASYNC_REG of frame_err_sync1 : signal is "TRUE";
    attribute ASYNC_REG of frame_err_sync2 : signal is "TRUE";
    attribute ASYNC_REG of rxd_sync1 : signal is "TRUE";
    attribute ASYNC_REG of rxd_sync2 : signal is "TRUE";
begin
    assert is_power_of_two(TX_FIFO_DEPTH)
        report "fcapz_ejtaguart: TX_FIFO_DEPTH must be a power of two"
        severity failure;
    assert is_power_of_two(RX_FIFO_DEPTH)
        report "fcapz_ejtaguart: RX_FIFO_DEPTH must be a power of two"
        severity failure;
    assert BAUD_DIV >= 4
        report "fcapz_ejtaguart: BAUD_RATE too high for CLK_HZ"
        severity failure;

    tdo <= sr(0);
    sr_tx_byte <= sr(7 downto 0);
    sr_cmd <= sr(31 downto 28);
    rx_ready <= not rx_fifo_empty;
    tx_fifo_wr_rst <= fifo_rst or uart_rst;
    tx_fifo_rd_rst <= rx_fifo_rst_sync2 or uart_rst;
    rx_fifo_wr_rst <= rx_fifo_rst_sync2 or uart_rst;

    tx_free_32 <= to_unsigned(TX_FIFO_DEPTH, 32) - resize(unsigned(tx_fifo_wr_count), 32);
    tx_free_sat <= x"FF" when tx_free_32 > to_unsigned(255, 32)
        else std_logic_vector(tx_free_32(7 downto 0));

    status_byte <= frame_err_sticky & rx_overflow_sticky & tx_fifo_full &
        (rx_valid_reg or config_valid_reg) & "000" & rx_ready;
    capture_rx_byte <= config_byte_reg when config_valid_reg = '1' else rx_byte_reg;
    uart_txd <= tx_sr(0) when tx_active = '1' else '1';

    u_tx_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => 8,
            DEPTH => TX_FIFO_DEPTH,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO
        )
        port map (
            wr_clk => tck,
            wr_rst => tx_fifo_wr_rst,
            wr_en => tx_wr_pulse,
            wr_data => sr_tx_byte,
            wr_full => tx_fifo_full,
            wr_rst_busy => tx_fifo_wr_rst_busy_unused,
            rd_clk => uart_clk,
            rd_rst => tx_fifo_rd_rst,
            rd_en => tx_fifo_rd_en_r,
            rd_data => tx_fifo_rdata,
            rd_empty => tx_fifo_empty,
            rd_rst_busy => tx_fifo_rd_rst_busy_unused,
            rd_count => open,
            wr_count => tx_fifo_wr_count
        );

    u_rx_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => 8,
            DEPTH => RX_FIFO_DEPTH,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO
        )
        port map (
            wr_clk => uart_clk,
            wr_rst => rx_fifo_wr_rst,
            wr_en => rx_fifo_wr_en_r,
            wr_data => rx_fifo_wr_data_r,
            wr_full => rx_fifo_full,
            wr_rst_busy => rx_fifo_wr_rst_busy_unused,
            rd_clk => tck,
            rd_rst => fifo_rst,
            rd_en => rx_rd_pulse,
            rd_data => rx_fifo_rdata,
            rd_empty => rx_fifo_empty,
            rd_rst_busy => rx_fifo_rd_rst_busy_unused,
            rd_count => rx_fifo_rd_count,
            wr_count => open
        );

    p_rx_fifo_reset_sync : process(uart_clk, uart_rst)
    begin
        if uart_rst = '1' then
            rx_fifo_rst_sync1 <= '1';
            rx_fifo_rst_sync2 <= '1';
        elsif rising_edge(uart_clk) then
            rx_fifo_rst_sync1 <= fifo_rst;
            rx_fifo_rst_sync2 <= rx_fifo_rst_sync1;
        end if;
    end process;

    p_config_byte : process(all)
    begin
        case sr_tx_byte(3 downto 0) is
            when x"0" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(7 downto 0);
            when x"1" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(15 downto 8);
            when x"2" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(23 downto 16);
            when x"3" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(31 downto 24);
            when x"4" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(7 downto 0);
            when x"5" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(15 downto 8);
            when x"6" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(23 downto 16);
            when x"7" => config_byte <= FCAPZ_EJTAGUART_VERSION_REG(31 downto 24);
            when x"8" => config_byte <= FEATURES(7 downto 0);
            when x"9" => config_byte <= FEATURES(15 downto 8);
            when x"A" => config_byte <= FEATURES(23 downto 16);
            when x"B" => config_byte <= FEATURES(31 downto 24);
            when x"C" => config_byte <= BAUD_DIV_R(7 downto 0);
            when x"D" => config_byte <= BAUD_DIV_R(15 downto 8);
            when x"E" => config_byte <= BAUD_DIV_R(23 downto 16);
            when others => config_byte <= BAUD_DIV_R(31 downto 24);
        end case;
    end process;

    p_tck : process(tck)
    begin
        if rising_edge(tck) then
            tx_wr_pulse <= '0';
            rx_rd_pulse <= '0';

            if rx_overflow_sync2 = '1' and fifo_rst = '0' then
                rx_overflow_sticky <= '1';
            end if;
            if frame_err_sync2 = '1' and fifo_rst = '0' then
                frame_err_sticky <= '1';
            end if;

            if fifo_rst = '1' and fifo_rst_cnt /= 0 then
                fifo_rst_cnt <= fifo_rst_cnt - 1;
            elsif fifo_rst = '1' and fifo_rst_cnt = 0 then
                fifo_rst <= '0';
            end if;

            if sel = '1' then
                if capture = '1' then
                    sr <= status_byte & x"00" & tx_free_sat & capture_rx_byte;
                elsif shift = '1' then
                    sr <= tdi & sr(DR_W - 1 downto 1);
                elsif update = '1' then
                    rx_valid_reg <= '0';
                    config_valid_reg <= '0';

                    case sr_cmd is
                        when CMD_NOP =>
                            null;
                        when CMD_TX_PUSH =>
                            if tx_fifo_full = '0' then
                                tx_wr_pulse <= '1';
                            end if;
                        when CMD_RX_POP =>
                            if rx_fifo_empty = '0' then
                                rx_byte_reg <= rx_fifo_rdata;
                                rx_valid_reg <= '1';
                                rx_rd_pulse <= '1';
                            end if;
                        when CMD_TXRX =>
                            if tx_fifo_full = '0' then
                                tx_wr_pulse <= '1';
                            end if;
                            if rx_fifo_empty = '0' then
                                rx_byte_reg <= rx_fifo_rdata;
                                rx_valid_reg <= '1';
                                rx_rd_pulse <= '1';
                            end if;
                        when CMD_CONFIG =>
                            config_byte_reg <= config_byte;
                            config_valid_reg <= '1';
                        when CMD_RESET =>
                            fifo_rst <= '1';
                            fifo_rst_cnt <= to_unsigned(4, fifo_rst_cnt'length);
                            rx_overflow_sticky <= '0';
                            frame_err_sticky <= '0';
                            rx_valid_reg <= '0';
                            config_valid_reg <= '0';
                            rx_byte_reg <= (others => '0');
                        when others =>
                            null;
                    end case;
                end if;
            end if;
        end if;
    end process;

    p_error_sync : process(tck)
    begin
        if rising_edge(tck) then
            rx_overflow_sync1 <= rx_overflow_uart;
            rx_overflow_sync2 <= rx_overflow_sync1;
            frame_err_sync1 <= frame_err_uart;
            frame_err_sync2 <= frame_err_sync1;
        end if;
    end process;

    p_tx : process(uart_clk, uart_rst)
    begin
        if uart_rst = '1' then
            tx_active <= '0';
            tx_baud_cnt <= (others => '0');
            tx_bit_cnt <= (others => '0');
            tx_sr <= (others => '1');
            tx_fifo_rd_en_r <= '0';
        elsif rising_edge(uart_clk) then
            tx_fifo_rd_en_r <= '0';

            if tx_active = '0' then
                if tx_fifo_empty = '0' then
                    if PARITY = 0 then
                        tx_sr <= '1' & '1' & tx_fifo_rdata & '0';
                    elsif PARITY = 1 then
                        tx_sr <= '1' & xor_reduce(tx_fifo_rdata) & tx_fifo_rdata & '0';
                    else
                        tx_sr <= '1' & (not xor_reduce(tx_fifo_rdata)) & tx_fifo_rdata & '0';
                    end if;
                    tx_bit_cnt <= to_unsigned(FRAME_BITS, tx_bit_cnt'length);
                    tx_baud_cnt <= to_unsigned(BAUD_DIV - 1, tx_baud_cnt'length);
                    tx_active <= '1';
                    tx_fifo_rd_en_r <= '1';
                end if;
            else
                if tx_baud_cnt = 0 then
                    tx_baud_cnt <= to_unsigned(BAUD_DIV - 1, tx_baud_cnt'length);
                    tx_sr <= '1' & tx_sr(10 downto 1);
                    tx_bit_cnt <= tx_bit_cnt - 1;
                    if tx_bit_cnt = 1 then
                        tx_active <= '0';
                    end if;
                else
                    tx_baud_cnt <= tx_baud_cnt - 1;
                end if;
            end if;
        end if;
    end process;

    p_rxd_sync : process(uart_clk, uart_rst)
    begin
        if uart_rst = '1' then
            rxd_sync1 <= '1';
            rxd_sync2 <= '1';
        elsif rising_edge(uart_clk) then
            rxd_sync1 <= uart_rxd;
            rxd_sync2 <= rxd_sync1;
        end if;
    end process;

    p_rx : process(uart_clk, uart_rst)
    begin
        if uart_rst = '1' then
            rx_active <= '0';
            rx_baud_cnt <= (others => '0');
            rx_bit_idx <= (others => '0');
            rx_shift_reg <= (others => '0');
            rx_fifo_wr_en_r <= '0';
            rx_fifo_wr_data_r <= (others => '0');
            rx_overflow_uart <= '0';
            frame_err_uart <= '0';
        elsif rising_edge(uart_clk) then
            rx_fifo_wr_en_r <= '0';

            if rx_fifo_rst_sync2 = '1' then
                rx_overflow_uart <= '0';
                frame_err_uart <= '0';
            end if;

            if rx_active = '0' then
                if rxd_sync2 = '0' then
                    rx_active <= '1';
                    rx_baud_cnt <= to_unsigned(HALF_BAUD - 1, rx_baud_cnt'length);
                    rx_bit_idx <= (others => '0');
                end if;
            else
                if rx_baud_cnt = 0 then
                    rx_baud_cnt <= to_unsigned(BAUD_DIV - 1, rx_baud_cnt'length);

                    if rx_bit_idx = 0 then
                        if rxd_sync2 = '1' then
                            rx_active <= '0';
                        else
                            rx_bit_idx <= to_unsigned(1, rx_bit_idx'length);
                        end if;
                    elsif rx_bit_idx <= 8 then
                        rx_shift_reg(to_integer(rx_bit_idx) - 1) <= rxd_sync2;
                        rx_bit_idx <= rx_bit_idx + 1;
                    elsif PARITY /= 0 and rx_bit_idx = 9 then
                        if PARITY = 1 then
                            if xor_reduce(rx_shift_reg) /= rxd_sync2 then
                                frame_err_uart <= '1';
                            end if;
                        else
                            if (not xor_reduce(rx_shift_reg)) /= rxd_sync2 then
                                frame_err_uart <= '1';
                            end if;
                        end if;
                        rx_bit_idx <= rx_bit_idx + 1;
                    elsif (PARITY /= 0 and rx_bit_idx = 10) or
                          (PARITY = 0 and rx_bit_idx = 9) then
                        if rxd_sync2 = '0' then
                            frame_err_uart <= '1';
                        end if;

                        if rx_fifo_full = '0' then
                            rx_fifo_wr_en_r <= '1';
                            rx_fifo_wr_data_r <= rx_shift_reg;
                        else
                            rx_overflow_uart <= '1';
                        end if;

                        rx_bit_idx <= rx_bit_idx + 1;
                        rx_baud_cnt <= to_unsigned(HALF_BAUD - 1, rx_baud_cnt'length);
                    else
                        if rxd_sync2 = '0' then
                            rx_baud_cnt <= to_unsigned(HALF_BAUD - 1, rx_baud_cnt'length);
                            rx_bit_idx <= (others => '0');
                        else
                            rx_active <= '0';
                        end if;
                    end if;
                else
                    rx_baud_cnt <= rx_baud_cnt - 1;
                end if;
            end if;
        end if;
    end process;
end architecture rtl;
