-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_core_manager is
    generic (
        NUM_SLOTS      : positive := 2;
        SAMPLE_W       : positive := 8;
        TIMESTAMP_W    : natural := 0;
        DEPTH          : positive := 1024;
        SLOT_CORE_IDS  : std_logic_vector(NUM_SLOTS * 16 - 1 downto 0) := (others => '0');
        SLOT_HAS_BURST : std_logic_vector(NUM_SLOTS - 1 downto 0) := (others => '0')
    );
    port (
        jtag_clk   : in  std_logic;
        jtag_rst   : in  std_logic;

        jtag_wr_en : in  std_logic;
        jtag_rd_en : in  std_logic;
        jtag_addr  : in  std_logic_vector(15 downto 0);
        jtag_wdata : in  std_logic_vector(31 downto 0);
        jtag_rdata : out std_logic_vector(31 downto 0);

        slot_wr_en : out std_logic_vector(NUM_SLOTS - 1 downto 0);
        slot_rd_en : out std_logic_vector(NUM_SLOTS - 1 downto 0);
        slot_addr  : out std_logic_vector(NUM_SLOTS * 16 - 1 downto 0);
        slot_wdata : out std_logic_vector(NUM_SLOTS * 32 - 1 downto 0);
        slot_rdata : in  std_logic_vector(NUM_SLOTS * 32 - 1 downto 0);

        burst_rd_addr          : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        slot_burst_rd_addr     : out std_logic_vector(NUM_SLOTS * fcapz_clog2(DEPTH) - 1 downto 0);
        slot_burst_rd_data     : in  std_logic_vector(NUM_SLOTS * SAMPLE_W - 1 downto 0);
        slot_burst_rd_ts_data  : in  std_logic_vector(NUM_SLOTS * fcapz_nonzero_width(TIMESTAMP_W) - 1 downto 0);
        slot_burst_start       : in  std_logic_vector(NUM_SLOTS - 1 downto 0);
        slot_burst_timestamp   : in  std_logic_vector(NUM_SLOTS - 1 downto 0);
        slot_burst_start_ptr   : in  std_logic_vector(NUM_SLOTS * fcapz_clog2(DEPTH) - 1 downto 0);
        burst_rd_data          : out std_logic_vector(SAMPLE_W - 1 downto 0);
        burst_rd_ts_data       : out std_logic_vector(fcapz_nonzero_width(TIMESTAMP_W) - 1 downto 0);
        burst_start            : out std_logic;
        burst_timestamp        : out std_logic;
        burst_start_ptr        : out std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0)
    );
end entity fcapz_core_manager;

architecture rtl of fcapz_core_manager is
    constant IDX_W     : positive := fcapz_clog2(NUM_SLOTS);
    constant PTR_W     : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE : positive := fcapz_nonzero_width(TIMESTAMP_W);

    constant MANAGER_CORE_ID : std_logic_vector(15 downto 0) := x"434D";
    constant MANAGER_VERSION : std_logic_vector(31 downto 0) :=
        FCAPZ_VERSION_MAJOR & FCAPZ_VERSION_MINOR & MANAGER_CORE_ID;

    constant ADDR_MGR_VERSION    : std_logic_vector(15 downto 0) := x"F000";
    constant ADDR_MGR_COUNT      : std_logic_vector(15 downto 0) := x"F004";
    constant ADDR_MGR_ACTIVE     : std_logic_vector(15 downto 0) := x"F008";
    constant ADDR_MGR_STRIDE     : std_logic_vector(15 downto 0) := x"F00C";
    constant ADDR_MGR_CAPS       : std_logic_vector(15 downto 0) := x"F010";
    constant ADDR_MGR_DESC_INDEX : std_logic_vector(15 downto 0) := x"F014";
    constant ADDR_MGR_DESC_CORE  : std_logic_vector(15 downto 0) := x"F018";
    constant ADDR_MGR_DESC_CAPS  : std_logic_vector(15 downto 0) := x"F01C";

    signal active_idx : unsigned(IDX_W - 1 downto 0) := (others => '0');
    signal desc_idx   : unsigned(IDX_W - 1 downto 0) := (others => '0');

    signal manager_hit         : std_logic;
    signal requested_idx_valid : std_logic;
    signal active_onehot       : std_logic_vector(NUM_SLOTS - 1 downto 0);

    signal active_rdata           : std_logic_vector(31 downto 0);
    signal active_burst_data      : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal active_burst_ts_data   : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal active_burst_start     : std_logic;
    signal active_burst_timestamp : std_logic;
    signal active_burst_start_ptr : std_logic_vector(PTR_W - 1 downto 0);

    signal desc_core_id   : std_logic_vector(15 downto 0);
    signal desc_has_burst : std_logic;
    signal manager_rdata  : std_logic_vector(31 downto 0);
begin
    manager_hit <= '1' when jtag_addr(15 downto 8) = x"F0" else '0';
    requested_idx_valid <= '1' when unsigned(jtag_wdata) < NUM_SLOTS else '0';
    active_onehot <= std_logic_vector(shift_left(to_unsigned(1, NUM_SLOTS), to_integer(active_idx)));

    p_regs : process(jtag_clk, jtag_rst)
    begin
        if jtag_rst = '1' then
            active_idx <= (others => '0');
            desc_idx <= (others => '0');
        elsif rising_edge(jtag_clk) then
            if jtag_wr_en = '1' then
                if jtag_addr = ADDR_MGR_ACTIVE then
                    if requested_idx_valid = '1' then
                        active_idx <= resize(unsigned(jtag_wdata), IDX_W);
                    end if;
                elsif jtag_addr = ADDR_MGR_DESC_INDEX then
                    if requested_idx_valid = '1' then
                        desc_idx <= resize(unsigned(jtag_wdata), IDX_W);
                    end if;
                end if;
            end if;
        end if;
    end process;

    g_slots : for g in 0 to NUM_SLOTS - 1 generate
        slot_wr_en(g) <= jtag_wr_en and not manager_hit and active_onehot(g);
        slot_rd_en(g) <= jtag_rd_en and not manager_hit and active_onehot(g);
        slot_addr((g + 1) * 16 - 1 downto g * 16) <= jtag_addr;
        slot_wdata((g + 1) * 32 - 1 downto g * 32) <= jtag_wdata;
        slot_burst_rd_addr((g + 1) * PTR_W - 1 downto g * PTR_W) <= burst_rd_addr;
    end generate;

    p_active : process(all)
        variable rdata_v      : std_logic_vector(31 downto 0);
        variable data_v       : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable ts_data_v    : std_logic_vector(TS_W_SAFE - 1 downto 0);
        variable start_v      : std_logic;
        variable timestamp_v  : std_logic;
        variable start_ptr_v  : std_logic_vector(PTR_W - 1 downto 0);
    begin
        rdata_v := (others => '0');
        data_v := (others => '0');
        ts_data_v := (others => '0');
        start_v := '0';
        timestamp_v := '0';
        start_ptr_v := (others => '0');

        for i in 0 to NUM_SLOTS - 1 loop
            if active_idx = to_unsigned(i, IDX_W) then
                rdata_v := slot_rdata((i + 1) * 32 - 1 downto i * 32);
                if SLOT_HAS_BURST(i) = '1' then
                    data_v := slot_burst_rd_data((i + 1) * SAMPLE_W - 1 downto i * SAMPLE_W);
                    ts_data_v := slot_burst_rd_ts_data((i + 1) * TS_W_SAFE - 1 downto i * TS_W_SAFE);
                    start_v := slot_burst_start(i);
                    timestamp_v := slot_burst_timestamp(i);
                    start_ptr_v := slot_burst_start_ptr((i + 1) * PTR_W - 1 downto i * PTR_W);
                end if;
            end if;
        end loop;

        active_rdata <= rdata_v;
        active_burst_data <= data_v;
        active_burst_ts_data <= ts_data_v;
        active_burst_start <= start_v;
        active_burst_timestamp <= timestamp_v;
        active_burst_start_ptr <= start_ptr_v;
    end process;

    p_desc : process(all)
        variable core_id_v   : std_logic_vector(15 downto 0);
        variable has_burst_v : std_logic;
    begin
        core_id_v := (others => '0');
        has_burst_v := '0';

        for i in 0 to NUM_SLOTS - 1 loop
            if desc_idx = to_unsigned(i, IDX_W) then
                core_id_v := SLOT_CORE_IDS((i + 1) * 16 - 1 downto i * 16);
                has_burst_v := SLOT_HAS_BURST(i);
            end if;
        end loop;

        desc_core_id <= core_id_v;
        desc_has_burst <= has_burst_v;
    end process;

    p_manager_rdata : process(all)
    begin
        case jtag_addr is
            when ADDR_MGR_VERSION =>
                manager_rdata <= MANAGER_VERSION;
            when ADDR_MGR_COUNT =>
                manager_rdata <= std_logic_vector(to_unsigned(NUM_SLOTS, 32));
            when ADDR_MGR_ACTIVE =>
                manager_rdata <= std_logic_vector(resize(active_idx, 32));
            when ADDR_MGR_STRIDE =>
                manager_rdata <= (others => '0');
            when ADDR_MGR_CAPS =>
                manager_rdata <= x"00000003";
            when ADDR_MGR_DESC_INDEX =>
                manager_rdata <= std_logic_vector(resize(desc_idx, 32));
            when ADDR_MGR_DESC_CORE =>
                manager_rdata <= x"0000" & desc_core_id;
            when ADDR_MGR_DESC_CAPS =>
                manager_rdata <= std_logic_vector(to_unsigned(0, 31)) & desc_has_burst;
            when others =>
                manager_rdata <= (others => '0');
        end case;
    end process;

    jtag_rdata <= manager_rdata when manager_hit = '1' else active_rdata;
    burst_rd_data <= active_burst_data;
    burst_rd_ts_data <= active_burst_ts_data;
    burst_start <= active_burst_start;
    burst_timestamp <= active_burst_timestamp;
    burst_start_ptr <= active_burst_start_ptr;
end architecture rtl;
