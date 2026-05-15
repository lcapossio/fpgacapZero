-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_ela is
    generic (
        SAMPLE_W         : positive := 32;
        DEPTH            : positive := 1024;
        TRIG_STAGES      : positive := 1;
        STOR_QUAL        : natural  := 0;
        NUM_CHANNELS     : positive := 1;
        INPUT_PIPE       : natural  := 0;
        DECIM_EN         : natural  := 0;
        EXT_TRIG_EN      : natural  := 0;
        TIMESTAMP_W      : natural  := 0;
        NUM_SEGMENTS     : positive := 1;
        PROBE_MUX_W      : natural  := 0;
        STARTUP_ARM      : natural  := 0;
        DEFAULT_TRIG_EXT : natural  := 0;
        REL_COMPARE      : natural  := 0;
        DUAL_COMPARE     : natural  := 1;
        USER1_DATA_EN    : natural  := 1
    );
    port (
        sample_clk       : in  std_logic;
        sample_rst       : in  std_logic;
        probe_in         : in  std_logic_vector(fcapz_probe_width(PROBE_MUX_W, NUM_CHANNELS, SAMPLE_W) - 1 downto 0);

        trigger_in       : in  std_logic;
        trigger_out      : out std_logic;
        armed_out        : out std_logic;

        jtag_clk         : in  std_logic;
        jtag_rst         : in  std_logic;
        jtag_wr_en       : in  std_logic;
        jtag_rd_en       : in  std_logic;
        jtag_addr        : in  std_logic_vector(15 downto 0);
        jtag_wdata       : in  std_logic_vector(31 downto 0);
        jtag_rdata       : out std_logic_vector(31 downto 0);

        burst_rd_addr    : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        burst_rd_data    : out std_logic_vector(SAMPLE_W - 1 downto 0);
        burst_rd_ts_data : out std_logic_vector(fcapz_nonzero_width(TIMESTAMP_W) - 1 downto 0);
        burst_start      : out std_logic;
        burst_timestamp  : out std_logic;
        burst_start_ptr  : out std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0)
    );
end entity fcapz_ela;

architecture rtl of fcapz_ela is
    function bool_to_nat(cond : boolean) return natural is
    begin
        if cond then
            return 1;
        end if;
        return 0;
    end function;

    function bool_to_sl(cond : boolean) return std_logic is
    begin
        if cond then
            return '1';
        end if;
        return '0';
    end function;

    function u32(n : natural) return std_logic_vector is
    begin
        return std_logic_vector(to_unsigned(n, 32));
    end function;

    function low_u32(v : std_logic_vector) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable n : natural := v'length;
    begin
        if n > 32 then
            n := 32;
        end if;
        for i in 0 to n - 1 loop
            r(i) := v(v'low + i);
        end loop;
        return r;
    end function;

    function cmp_hit(
        probe      : std_logic_vector;
        probe_prev : std_logic_vector;
        value      : std_logic_vector;
        mask       : std_logic_vector;
        mode       : std_logic_vector(3 downto 0)
    ) return std_logic is
        variable mp        : unsigned(probe'range);
        variable mv        : unsigned(value'range);
        variable mpp       : unsigned(probe_prev'range);
        variable zero_cur  : boolean;
        variable zero_prev : boolean;
    begin
        mp := unsigned(probe and mask);
        mv := unsigned(value and mask);
        mpp := unsigned(probe_prev and mask);
        zero_cur := mp = 0;
        zero_prev := mpp = 0;

        case to_integer(unsigned(mode)) is
            when 0 => if mp = mv then return '1'; end if;
            when 1 => if mp /= mv then return '1'; end if;
            when 2 => if REL_COMPARE /= 0 and mp < mv then return '1'; end if;
            when 3 => if REL_COMPARE /= 0 and mp > mv then return '1'; end if;
            when 4 => if REL_COMPARE /= 0 and mp <= mv then return '1'; end if;
            when 5 => if REL_COMPARE /= 0 and mp >= mv then return '1'; end if;
            when 6 => if zero_prev and not zero_cur then return '1'; end if;
            when 7 => if not zero_prev and zero_cur then return '1'; end if;
            when 8 => if mp /= mpp then return '1'; end if;
            when others => null;
        end case;
        return '0';
    end function;

    constant PTR_W            : positive := fcapz_clog2(DEPTH);
    constant WORDS_PER_SAMPLE : positive := (SAMPLE_W + 31) / 32;
    constant SEG_DEPTH        : positive := DEPTH / NUM_SEGMENTS;
    constant SEG_PTR_W        : positive := fcapz_clog2(SEG_DEPTH);
    constant SEG_IDX_W        : positive := fcapz_clog2(NUM_SEGMENTS);
    constant TS_WIDTH         : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant TS_WORDS         : natural := (TIMESTAMP_W + 31) / 32;

    constant ADDR_VERSION      : natural := 16#0000#;
    constant ADDR_CTRL         : natural := 16#0004#;
    constant ADDR_STATUS       : natural := 16#0008#;
    constant ADDR_SAMPLE_W     : natural := 16#000C#;
    constant ADDR_DEPTH        : natural := 16#0010#;
    constant ADDR_PRETRIG      : natural := 16#0014#;
    constant ADDR_POSTTRIG     : natural := 16#0018#;
    constant ADDR_CAPTURE_LEN  : natural := 16#001C#;
    constant ADDR_TRIG_MODE    : natural := 16#0020#;
    constant ADDR_TRIG_VALUE   : natural := 16#0024#;
    constant ADDR_TRIG_MASK    : natural := 16#0028#;
    constant ADDR_BURST_PTR    : natural := 16#002C#;
    constant ADDR_SQ_MODE      : natural := 16#0030#;
    constant ADDR_SQ_VALUE     : natural := 16#0034#;
    constant ADDR_SQ_MASK      : natural := 16#0038#;
    constant ADDR_FEATURES     : natural := 16#003C#;
    constant ADDR_SEQ_BASE     : natural := 16#0040#;
    constant SEQ_STRIDE        : natural := 20;
    constant ADDR_CHAN_SEL     : natural := 16#00A0#;
    constant ADDR_NUM_CHAN     : natural := 16#00A4#;
    constant ADDR_PROBE_SEL    : natural := 16#00AC#;
    constant ADDR_DECIM        : natural := 16#00B0#;
    constant ADDR_TRIG_EXT     : natural := 16#00B4#;
    constant ADDR_NUM_SEGMENTS : natural := 16#00B8#;
    constant ADDR_SEG_STATUS   : natural := 16#00BC#;
    constant ADDR_SEG_SEL      : natural := 16#00C0#;
    constant ADDR_TIMESTAMP_W  : natural := 16#00C4#;
    constant ADDR_SEG_START    : natural := 16#00C8#;
    constant ADDR_PROBE_MUX_W  : natural := 16#00D0#;
    constant ADDR_TRIG_DELAY   : natural := 16#00D4#;
    constant ADDR_STARTUP_ARM  : natural := 16#00D8#;
    constant ADDR_TRIG_HOLDOFF : natural := 16#00DC#;
    constant ADDR_COMPARE_CAPS : natural := 16#00E0#;
    constant ADDR_DATA_BASE    : natural := 16#0100#;
    constant ADDR_TS_DATA_BASE : natural := ADDR_DATA_BASE + DEPTH * WORDS_PER_SAMPLE * 4;

    constant FEATURES : std_logic_vector(31 downto 0) :=
        std_logic_vector(to_unsigned(TIMESTAMP_W, 8)) &
        std_logic_vector(to_unsigned(NUM_SEGMENTS, 8)) &
        std_logic_vector(to_unsigned(NUM_CHANNELS, 8)) &
        bool_to_sl(TIMESTAMP_W > 0) &
        bool_to_sl(EXT_TRIG_EN /= 0) &
        bool_to_sl(DECIM_EN /= 0) &
        bool_to_sl(STOR_QUAL /= 0) &
        std_logic_vector(to_unsigned(TRIG_STAGES, 4));

    type seg_ptr_t is array (0 to NUM_SEGMENTS - 1) of natural range 0 to DEPTH - 1;
    type reg32_array_t is array (natural range <>) of std_logic_vector(31 downto 0);

    signal jtag_ctrl         : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_pretrig_len  : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_posttrig_len : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_trig_mode    : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_trig_value   : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_trig_mask    : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_sq_mode      : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_sq_value     : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_sq_mask      : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_seq_cfg      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_value_a  : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_mask_a   : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_value_b  : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_mask_b   : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal jtag_decim        : std_logic_vector(23 downto 0) := (others => '0');
    signal jtag_trig_ext     : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal jtag_probe_sel    : natural range 0 to 255 := 0;
    signal jtag_chan_sel     : natural range 0 to 255 := 0;
    signal jtag_seg_sel      : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal jtag_startup_arm  : std_logic := '0';
    signal jtag_trig_delay   : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_trig_holdoff : std_logic_vector(15 downto 0) := (others => '0');

    signal pretrig_len_sync1      : natural range 0 to DEPTH := 0;
    signal pretrig_len_sync2      : natural range 0 to DEPTH := 0;
    signal posttrig_len_sync1     : natural range 0 to DEPTH := 0;
    signal posttrig_len_sync2     : natural range 0 to DEPTH := 0;
    signal trig_mode_sync1        : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_mode_sync2        : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_value_sync1       : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_value_sync2       : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_mask_sync1        : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_mask_sync2        : std_logic_vector(31 downto 0) := (others => '0');
    signal decim_sync1            : natural range 0 to 16#FFFFFF# := 0;
    signal decim_sync2            : natural range 0 to 16#FFFFFF# := 0;
    signal trig_ext_sync1         : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal trig_ext_sync2         : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal probe_sel_sync1        : natural range 0 to 255 := 0;
    signal probe_sel_sync2        : natural range 0 to 255 := 0;
    signal chan_sel_sync1         : natural range 0 to 255 := 0;
    signal chan_sel_sync2         : natural range 0 to 255 := 0;
    signal startup_arm_sync1      : std_logic := '0';
    signal startup_arm_sync2      : std_logic := '0';
    signal trig_delay_sync1       : natural range 0 to 65535 := 0;
    signal trig_delay_sync2       : natural range 0 to 65535 := 0;
    signal trig_holdoff_sync1     : natural range 0 to 65535 := 0;
    signal trig_holdoff_sync2     : natural range 0 to 65535 := 0;
    signal sq_mode_sync1          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mode_sync2          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_value_sync1         : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_value_sync2         : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mask_sync1          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mask_sync2          : std_logic_vector(31 downto 0) := (others => '0');
    signal seq_cfg_sync1          : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_cfg_sync2          : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_a_sync1      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_a_sync2      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_a_sync1       : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_a_sync2       : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_b_sync1      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_b_sync2      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_b_sync1       : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal seq_mask_b_sync2       : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));

    signal arm_toggle_jtag   : std_logic := '0';
    signal reset_toggle_jtag : std_logic := '0';
    signal arm_sync          : std_logic_vector(2 downto 0) := (others => '0');
    signal reset_sync        : std_logic_vector(2 downto 0) := (others => '0');

    signal armed             : std_logic := bool_to_sl(STARTUP_ARM /= 0);
    signal triggered         : std_logic := '0';
    signal done              : std_logic := '0';
    signal overflow          : std_logic := '0';
    signal trigger_out_i     : std_logic := '0';
    signal wr_ptr            : natural range 0 to DEPTH - 1 := 0;
    signal start_ptr         : natural range 0 to DEPTH - 1 := 0;
    signal trig_ptr          : natural range 0 to DEPTH - 1 := 0;
    signal pre_count         : natural range 0 to DEPTH := 0;
    signal post_count        : natural range 0 to DEPTH := 0;
    signal capture_len       : natural range 0 to DEPTH + 1 := 0;
    signal probe_prev        : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal decim_count       : natural range 0 to 16#FFFFFF# := 0;
    signal timestamp_counter : unsigned(TS_WIDTH - 1 downto 0) := (others => '0');
    signal cur_segment       : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal seg_count         : natural range 0 to NUM_SEGMENTS := 0;
    signal all_seg_done      : std_logic := '0';
    signal seg_start_ptr     : seg_ptr_t := (others => 0);
    signal seg_start_ptr_jtag_sync1 : seg_ptr_t := (others => 0);
    signal seg_start_ptr_jtag_sync2 : seg_ptr_t := (others => 0);
    signal segment_wrapped   : std_logic := '0';
    signal trig_delay_pending: std_logic := '0';
    signal trig_delay_count  : natural range 0 to 65535 := 0;
    signal trig_holdoff_count: natural range 0 to 65535 := 0;
    signal trig_holdoff_active : std_logic := '0';
    signal pipe_probe        : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal hit_pipe          : std_logic := '0';
    signal sq_pipe           : std_logic := '1';
    signal jtag_rdata_mux    : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_i      : std_logic_vector(31 downto 0) := (others => '0');
    signal mem_we_a          : std_logic := '0';
    signal mem_we_a_q        : std_logic := '0';
    signal mem_we_a_ram      : std_logic := '0';
    signal mem_addr_a        : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_addr_a_eff    : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_wr_addr_q     : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_rd_pending    : std_logic := '0';
    signal mem_rd_idx        : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal sample_mem_din    : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal sample_mem_din_ram : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal mem_wr_data_q     : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal sample_mem_dout_a : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal sample_mem_dout_b : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal ts_mem_din        : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_mem_din_ram    : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal mem_wr_ts_q       : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_mem_dout_a     : std_logic_vector(TS_WIDTH - 1 downto 0);
    signal ts_mem_dout_b     : std_logic_vector(TS_WIDTH - 1 downto 0);

    signal rd_req_toggle_jtag : std_logic := '0';
    signal rd_req_sync        : std_logic_vector(2 downto 0) := (others => '0');
    signal rd_ack_toggle_sample : std_logic := '0';
    signal rd_ack_sync        : std_logic_vector(1 downto 0) := (others => '0');
    signal rd_addr_jtag       : std_logic_vector(15 downto 0) := (others => '0');
    signal rd_addr_sync1      : std_logic_vector(15 downto 0) := (others => '0');
    signal rd_addr_sync2      : std_logic_vector(15 downto 0) := (others => '0');
    signal rd_addr_req        : std_logic_vector(15 downto 0) := (others => '0');
    signal rd_addr_data_window : std_logic := '0';
    signal rd_is_ts           : std_logic := '0';
    signal rd_phase           : unsigned(2 downto 0) := (others => '0');
    signal rd_data_sample     : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal rd_data_sync1      : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal rd_data_sync2      : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal ts_rd_data_sample  : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_rd_data_sync1   : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_rd_data_sync2   : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal seg_sel_rd_sync1   : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal seg_sel_rd_sync2   : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal seg_start_ptr_rd   : natural range 0 to DEPTH - 1 := 0;
    signal burst_start_ptr_i  : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');

    constant RD_IDLE      : unsigned(2 downto 0) := "000";
    constant RD_DECODE    : unsigned(2 downto 0) := "001";
    constant RD_WAIT_ADDR : unsigned(2 downto 0) := "010";
    constant RD_WAIT_DATA : unsigned(2 downto 0) := "011";
    constant RD_CAPTURE   : unsigned(2 downto 0) := "100";
    constant RD_ACK       : unsigned(2 downto 0) := "101";

    function expand32(v : std_logic_vector(31 downto 0)) return std_logic_vector is
        variable r : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
        variable n : natural := SAMPLE_W;
    begin
        if n > 32 then
            n := 32;
        end if;
        r(n - 1 downto 0) := v(n - 1 downto 0);
        return r;
    end function;

    function sample_word(addr : natural; sample : std_logic_vector(SAMPLE_W - 1 downto 0)) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable chunk : natural;
        variable bit_base : natural;
    begin
        chunk := ((addr - ADDR_DATA_BASE) / 4) mod WORDS_PER_SAMPLE;
        bit_base := chunk * 32;
        for i in 0 to 31 loop
            if bit_base + i < SAMPLE_W then
                r(i) := sample(bit_base + i);
            end if;
        end loop;
        return r;
    end function;

    function ts_word(addr : natural; ts : std_logic_vector(TS_WIDTH - 1 downto 0)) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable chunk : natural;
        variable bit_base : natural;
    begin
        if TIMESTAMP_W > 0 then
            chunk := ((addr - ADDR_TS_DATA_BASE) / 4) mod TS_WORDS;
            bit_base := chunk * 32;
            for i in 0 to 31 loop
                if bit_base + i < TIMESTAMP_W then
                    r(i) := ts(bit_base + i);
                end if;
            end loop;
        end if;
        return r;
    end function;

    function cfg_len(v : std_logic_vector(31 downto 0)) return natural is
    begin
        return to_integer(unsigned(v(PTR_W - 1 downto 0)));
    end function;

    function next_ptr(ptr : natural; base : natural) return natural is
    begin
        if ptr = base + SEG_DEPTH - 1 then
            return base;
        end if;
        return ptr + 1;
    end function;

    function seg_base(seg : natural) return natural is
    begin
        return seg * SEG_DEPTH;
    end function;

    function capture_start_ptr(
        trig       : natural;
        pre_len    : natural;
        post_len   : natural;
        base       : natural;
        wrapped    : std_logic
    ) return natural is
        variable off : natural;
    begin
        if trig < base or trig >= base + SEG_DEPTH then
            return base;
        end if;
        if pre_len + post_len + 1 >= SEG_DEPTH then
            return base;
        end if;
        off := trig - base;
        if wrapped = '0' and off < pre_len then
            return base;
        end if;
        return base + ((off + SEG_DEPTH - (pre_len mod SEG_DEPTH)) mod SEG_DEPTH);
    end function;
begin
    trigger_out <= trigger_out_i;
    armed_out <= armed;
    jtag_rdata <= jtag_rdata_i;
    burst_start_ptr <= burst_start_ptr_i;
    burst_rd_data <= sample_mem_dout_b;
    burst_rd_ts_data <= ts_mem_dout_b;
    mem_we_a_ram <= mem_we_a_q when INPUT_PIPE > 0 else mem_we_a;
    sample_mem_din_ram <= mem_wr_data_q when INPUT_PIPE > 0 else sample_mem_din;
    ts_mem_din_ram <= mem_wr_ts_q when INPUT_PIPE > 0 else ts_mem_din;
    mem_addr_a_eff <= mem_wr_addr_q when INPUT_PIPE > 0 and mem_we_a_q = '1' else
                      mem_rd_idx when USER1_DATA_EN /= 0 and mem_rd_pending = '1' else
                      mem_addr_a;

    u_sample_mem : entity work.fcapz_dpram
        generic map (
            WIDTH => SAMPLE_W,
            DEPTH => DEPTH
        )
        port map (
            clk_a  => sample_clk,
            we_a   => mem_we_a_ram,
            addr_a => mem_addr_a_eff,
            din_a  => sample_mem_din_ram,
            dout_a => sample_mem_dout_a,
            clk_b  => jtag_clk,
            addr_b => burst_rd_addr,
            dout_b => sample_mem_dout_b
        );

    g_ts_mem : if TIMESTAMP_W > 0 generate
        u_ts_mem : entity work.fcapz_dpram
            generic map (
                WIDTH => TS_WIDTH,
                DEPTH => DEPTH
            )
            port map (
                clk_a  => sample_clk,
                we_a   => mem_we_a_ram,
                addr_a => mem_addr_a_eff,
                din_a  => ts_mem_din_ram,
                dout_a => ts_mem_dout_a,
                clk_b  => jtag_clk,
                addr_b => burst_rd_addr,
                dout_b => ts_mem_dout_b
            );
    end generate;

    g_no_ts_mem : if TIMESTAMP_W = 0 generate
        ts_mem_dout_a <= (others => '0');
        ts_mem_dout_b <= (others => '0');
    end generate;

    p_mem_write_pipe : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            mem_we_a_q <= '0';
            mem_wr_addr_q <= (others => '0');
            mem_wr_data_q <= (others => '0');
            mem_wr_ts_q <= (others => '0');
        elsif rising_edge(sample_clk) then
            mem_we_a_q <= mem_we_a;
            if mem_we_a = '1' then
                mem_wr_addr_q <= mem_addr_a;
                mem_wr_data_q <= sample_mem_din;
                mem_wr_ts_q <= ts_mem_din;
            end if;
        end if;
    end process;

    p_jtag_regs : process(jtag_clk, jtag_rst)
        variable addr : natural;
        variable seq_stage : natural;
        variable seq_off : natural;
    begin
        if jtag_rst = '1' then
            jtag_ctrl <= (others => '0');
            jtag_pretrig_len <= (others => '0');
            jtag_posttrig_len <= (others => '0');
            jtag_trig_mode <= (others => '0');
            jtag_trig_value <= (others => '0');
            jtag_trig_mask <= (others => '0');
            jtag_sq_mode <= (others => '0');
            jtag_sq_value <= (others => '0');
            jtag_sq_mask <= (others => '0');
            jtag_seq_cfg <= (others => (others => '0'));
            jtag_seq_value_a <= (others => (others => '0'));
            jtag_seq_mask_a <= (others => (others => '0'));
            jtag_seq_value_b <= (others => (others => '0'));
            jtag_seq_mask_b <= (others => (others => '1'));
            jtag_decim <= (others => '0');
            jtag_trig_ext <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            jtag_probe_sel <= 0;
            jtag_chan_sel <= 0;
            jtag_seg_sel <= 0;
            jtag_startup_arm <= '1' when STARTUP_ARM /= 0 else '0';
            jtag_trig_delay <= (others => '0');
            jtag_trig_holdoff <= (others => '0');
            arm_toggle_jtag <= '0';
            reset_toggle_jtag <= '0';
            rd_req_toggle_jtag <= '0';
            rd_addr_jtag <= (others => '0');
            burst_start <= '0';
            burst_timestamp <= '0';
            burst_start_ptr_i <= (others => '0');
            seg_start_ptr_jtag_sync1 <= (others => 0);
            seg_start_ptr_jtag_sync2 <= (others => 0);
        elsif rising_edge(jtag_clk) then
            seg_start_ptr_jtag_sync1 <= seg_start_ptr;
            seg_start_ptr_jtag_sync2 <= seg_start_ptr_jtag_sync1;
            addr := to_integer(unsigned(jtag_addr));
            if jtag_wr_en = '1' then
                case addr is
                    when ADDR_CTRL =>
                        jtag_ctrl <= jtag_wdata;
                        if jtag_wdata(0) = '1' then
                            arm_toggle_jtag <= not arm_toggle_jtag;
                        end if;
                        if jtag_wdata(1) = '1' then
                            reset_toggle_jtag <= not reset_toggle_jtag;
                        end if;
                    when ADDR_PRETRIG =>
                        jtag_pretrig_len <= jtag_wdata;
                    when ADDR_POSTTRIG =>
                        jtag_posttrig_len <= jtag_wdata;
                    when ADDR_TRIG_MODE =>
                        jtag_trig_mode <= jtag_wdata;
                    when ADDR_TRIG_VALUE =>
                        jtag_trig_value <= jtag_wdata;
                    when ADDR_TRIG_MASK =>
                        jtag_trig_mask <= jtag_wdata;
                    when ADDR_SQ_MODE =>
                        if STOR_QUAL /= 0 then
                            jtag_sq_mode <= jtag_wdata;
                        end if;
                    when ADDR_SQ_VALUE =>
                        if STOR_QUAL /= 0 then
                            jtag_sq_value <= jtag_wdata;
                        end if;
                    when ADDR_SQ_MASK =>
                        if STOR_QUAL /= 0 then
                            jtag_sq_mask <= jtag_wdata;
                        end if;
                    when ADDR_DECIM =>
                        if DECIM_EN /= 0 then
                            jtag_decim <= jtag_wdata(23 downto 0);
                        end if;
                    when ADDR_TRIG_EXT =>
                        if EXT_TRIG_EN /= 0 then
                            jtag_trig_ext <= jtag_wdata(1 downto 0);
                        end if;
                    when ADDR_PROBE_SEL =>
                        if PROBE_MUX_W > 0 then
                            jtag_probe_sel <= to_integer(unsigned(jtag_wdata(7 downto 0)));
                        end if;
                    when ADDR_CHAN_SEL =>
                        if NUM_CHANNELS > 1 then
                            jtag_chan_sel <= to_integer(unsigned(jtag_wdata(7 downto 0)));
                        end if;
                    when ADDR_SEG_SEL =>
                        if NUM_SEGMENTS > 1 then
                            jtag_seg_sel <= to_integer(unsigned(jtag_wdata(SEG_IDX_W - 1 downto 0))) mod NUM_SEGMENTS;
                        end if;
                    when ADDR_STARTUP_ARM =>
                        jtag_startup_arm <= jtag_wdata(0);
                    when ADDR_TRIG_DELAY =>
                        jtag_trig_delay <= jtag_wdata(15 downto 0);
                    when ADDR_TRIG_HOLDOFF =>
                        jtag_trig_holdoff <= jtag_wdata(15 downto 0);
                    when ADDR_BURST_PTR =>
                        burst_start <= not burst_start;
                        burst_timestamp <= jtag_wdata(31);
                        if NUM_SEGMENTS > 1 then
                            burst_start_ptr_i <= std_logic_vector(to_unsigned(seg_start_ptr_jtag_sync2(jtag_seg_sel), PTR_W));
                        else
                            burst_start_ptr_i <= std_logic_vector(to_unsigned(start_ptr, PTR_W));
                        end if;
                    when others =>
                        if TRIG_STAGES > 1 and addr >= ADDR_SEQ_BASE and addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE then
                            seq_stage := (addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                            seq_off := (addr - ADDR_SEQ_BASE) mod SEQ_STRIDE;
                            case seq_off is
                                when 0 => jtag_seq_cfg(seq_stage) <= jtag_wdata;
                                when 4 => jtag_seq_value_a(seq_stage) <= jtag_wdata;
                                when 8 => jtag_seq_mask_a(seq_stage) <= jtag_wdata;
                                when 12 =>
                                    if DUAL_COMPARE /= 0 then
                                        jtag_seq_value_b(seq_stage) <= jtag_wdata;
                                    end if;
                                when 16 =>
                                    if DUAL_COMPARE /= 0 then
                                        jtag_seq_mask_b(seq_stage) <= jtag_wdata;
                                    end if;
                                when others => null;
                            end case;
                        end if;
                end case;
            end if;
            if jtag_rd_en = '1' then
                rd_addr_jtag <= jtag_addr;
                if USER1_DATA_EN /= 0 and
                   (to_integer(unsigned(jtag_addr)) >= ADDR_DATA_BASE or
                    (TIMESTAMP_W > 0 and to_integer(unsigned(jtag_addr)) >= ADDR_TS_DATA_BASE)) then
                    rd_req_toggle_jtag <= not rd_req_toggle_jtag;
                end if;
            end if;
        end if;
    end process;

    p_capture : process(sample_clk, sample_rst)
        variable active_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable compare_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable hit_internal : std_logic;
        variable hit_a : std_logic;
        variable hit_b : std_logic;
        variable hit : std_logic;
        variable hit_eff : std_logic;
        variable sq_ok : boolean;
        variable sq_eff : boolean;
        variable store_tick : boolean;
        variable store_ok : boolean;
        variable base : natural;
        variable start_calc : natural;
        variable next_segment : natural;
        variable post_limit : natural;
        variable trigger_commit_now : boolean;
        variable store_now : boolean;
        variable idx : natural;
    begin
        if sample_rst = '1' then
            arm_sync <= (others => '0');
            reset_sync <= (others => '0');
            pretrig_len_sync1 <= 0;
            pretrig_len_sync2 <= 0;
            posttrig_len_sync1 <= 0;
            posttrig_len_sync2 <= 0;
            trig_mode_sync1 <= (others => '0');
            trig_mode_sync2 <= (others => '0');
            trig_value_sync1 <= (others => '0');
            trig_value_sync2 <= (others => '0');
            trig_mask_sync1 <= (others => '0');
            trig_mask_sync2 <= (others => '0');
            decim_sync1 <= 0;
            decim_sync2 <= 0;
            trig_ext_sync1 <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            trig_ext_sync2 <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            probe_sel_sync1 <= 0;
            probe_sel_sync2 <= 0;
            chan_sel_sync1 <= 0;
            chan_sel_sync2 <= 0;
            startup_arm_sync1 <= bool_to_sl(STARTUP_ARM /= 0);
            startup_arm_sync2 <= bool_to_sl(STARTUP_ARM /= 0);
            trig_delay_sync1 <= 0;
            trig_delay_sync2 <= 0;
            trig_holdoff_sync1 <= 0;
            trig_holdoff_sync2 <= 0;
            sq_mode_sync1 <= (others => '0');
            sq_mode_sync2 <= (others => '0');
            sq_value_sync1 <= (others => '0');
            sq_value_sync2 <= (others => '0');
            sq_mask_sync1 <= (others => '0');
            sq_mask_sync2 <= (others => '0');
            seq_cfg_sync1 <= (others => (others => '0'));
            seq_cfg_sync2 <= (others => (others => '0'));
            seq_value_a_sync1 <= (others => (others => '0'));
            seq_value_a_sync2 <= (others => (others => '0'));
            seq_mask_a_sync1 <= (others => (others => '0'));
            seq_mask_a_sync2 <= (others => (others => '0'));
            seq_value_b_sync1 <= (others => (others => '0'));
            seq_value_b_sync2 <= (others => (others => '0'));
            seq_mask_b_sync1 <= (others => (others => '1'));
            seq_mask_b_sync2 <= (others => (others => '1'));
            armed <= '0';
            triggered <= '0';
            done <= '0';
            overflow <= '0';
            trigger_out_i <= '0';
            wr_ptr <= 0;
            start_ptr <= 0;
            trig_ptr <= 0;
            pre_count <= 0;
            post_count <= 0;
            capture_len <= 0;
            probe_prev <= (others => '0');
            decim_count <= 0;
            timestamp_counter <= (others => '0');
            cur_segment <= 0;
            seg_count <= 0;
            all_seg_done <= '0';
            seg_start_ptr <= (others => 0);
            segment_wrapped <= '0';
            trig_delay_pending <= '0';
            trig_delay_count <= 0;
            trig_holdoff_count <= 0;
            trig_holdoff_active <= '0';
            pipe_probe <= (others => '0');
            hit_pipe <= '0';
            sq_pipe <= '1';
            mem_we_a <= '0';
            mem_addr_a <= (others => '0');
            sample_mem_din <= (others => '0');
            ts_mem_din <= (others => '0');
        elsif rising_edge(sample_clk) then
            arm_sync <= arm_sync(1 downto 0) & arm_toggle_jtag;
            reset_sync <= reset_sync(1 downto 0) & reset_toggle_jtag;
            pretrig_len_sync1 <= cfg_len(jtag_pretrig_len);
            pretrig_len_sync2 <= pretrig_len_sync1;
            posttrig_len_sync1 <= cfg_len(jtag_posttrig_len);
            posttrig_len_sync2 <= posttrig_len_sync1;
            trig_mode_sync1 <= jtag_trig_mode;
            trig_mode_sync2 <= trig_mode_sync1;
            trig_value_sync1 <= jtag_trig_value;
            trig_value_sync2 <= trig_value_sync1;
            trig_mask_sync1 <= jtag_trig_mask;
            trig_mask_sync2 <= trig_mask_sync1;
            decim_sync1 <= to_integer(unsigned(jtag_decim));
            decim_sync2 <= decim_sync1;
            trig_ext_sync1 <= jtag_trig_ext;
            trig_ext_sync2 <= trig_ext_sync1;
            probe_sel_sync1 <= jtag_probe_sel;
            probe_sel_sync2 <= probe_sel_sync1;
            chan_sel_sync1 <= jtag_chan_sel;
            chan_sel_sync2 <= chan_sel_sync1;
            startup_arm_sync1 <= jtag_startup_arm;
            startup_arm_sync2 <= startup_arm_sync1;
            trig_delay_sync1 <= to_integer(unsigned(jtag_trig_delay));
            trig_delay_sync2 <= trig_delay_sync1;
            trig_holdoff_sync1 <= to_integer(unsigned(jtag_trig_holdoff));
            trig_holdoff_sync2 <= trig_holdoff_sync1;
            sq_mode_sync1 <= jtag_sq_mode;
            sq_mode_sync2 <= sq_mode_sync1;
            sq_value_sync1 <= jtag_sq_value;
            sq_value_sync2 <= sq_value_sync1;
            sq_mask_sync1 <= jtag_sq_mask;
            sq_mask_sync2 <= sq_mask_sync1;
            seq_cfg_sync1 <= jtag_seq_cfg;
            seq_cfg_sync2 <= seq_cfg_sync1;
            seq_value_a_sync1 <= jtag_seq_value_a;
            seq_value_a_sync2 <= seq_value_a_sync1;
            seq_mask_a_sync1 <= jtag_seq_mask_a;
            seq_mask_a_sync2 <= seq_mask_a_sync1;
            seq_value_b_sync1 <= jtag_seq_value_b;
            seq_value_b_sync2 <= seq_value_b_sync1;
            seq_mask_b_sync1 <= jtag_seq_mask_b;
            seq_mask_b_sync2 <= seq_mask_b_sync1;
            trigger_out_i <= '0';
            mem_we_a <= '0';

            if TIMESTAMP_W > 0 then
                timestamp_counter <= timestamp_counter + 1;
            end if;

            active_probe := (others => '0');
            if PROBE_MUX_W > 0 then
                idx := (probe_sel_sync2 mod (PROBE_MUX_W / SAMPLE_W)) * SAMPLE_W;
                active_probe := probe_in(idx + SAMPLE_W - 1 downto idx);
            elsif NUM_CHANNELS > 1 then
                idx := (chan_sel_sync2 mod NUM_CHANNELS) * SAMPLE_W;
                active_probe := probe_in(idx + SAMPLE_W - 1 downto idx);
            else
                active_probe := probe_in(SAMPLE_W - 1 downto 0);
            end if;
            if INPUT_PIPE > 0 then
                compare_probe := pipe_probe;
                pipe_probe <= active_probe;
            else
                compare_probe := active_probe;
            end if;

            if DECIM_EN = 0 or decim_sync2 = 0 then
                store_tick := true;
            else
                store_tick := decim_count = 0;
                if decim_count >= decim_sync2 then
                    decim_count <= 0;
                else
                    decim_count <= decim_count + 1;
                end if;
            end if;

            if trig_holdoff_active = '1' then
                if trig_holdoff_count = 0 then
                    trig_holdoff_active <= '0';
                else
                    trig_holdoff_count <= trig_holdoff_count - 1;
                end if;
            end if;

            hit_internal := '0';
            if TRIG_STAGES > 1 then
                hit_a := cmp_hit(
                    compare_probe,
                    probe_prev,
                    expand32(seq_value_a_sync2(0)),
                    expand32(seq_mask_a_sync2(0)),
                    seq_cfg_sync2(0)(3 downto 0)
                );
                hit_b := '0';
                if DUAL_COMPARE /= 0 then
                    hit_b := cmp_hit(
                        compare_probe,
                        probe_prev,
                        expand32(seq_value_b_sync2(0)),
                        expand32(seq_mask_b_sync2(0)),
                        seq_cfg_sync2(0)(7 downto 4)
                    );
                end if;
                case seq_cfg_sync2(0)(9 downto 8) is
                    when "01" => hit_internal := hit_b;
                    when "10" => hit_internal := hit_a and hit_b;
                    when "11" => hit_internal := hit_a or hit_b;
                    when others => hit_internal := hit_a;
                end case;
            elsif trig_mode_sync2(1) = '1' then
                if ((compare_probe xor probe_prev) and expand32(trig_mask_sync2)) /= (SAMPLE_W - 1 downto 0 => '0') then
                    hit_internal := '1';
                end if;
            elsif trig_mode_sync2(0) = '1' then
                hit_internal := cmp_hit(compare_probe, probe_prev, expand32(trig_value_sync2), expand32(trig_mask_sync2), x"0");
            end if;

            case trig_ext_sync2 is
                when "01" => hit := hit_internal or trigger_in;
                when "10" => hit := hit_internal and trigger_in;
                when others => hit := hit_internal;
            end case;

            sq_ok := true;
            if STOR_QUAL /= 0 then
                sq_ok := cmp_hit(
                    compare_probe,
                    probe_prev,
                    expand32(sq_value_sync2),
                    expand32(sq_mask_sync2),
                    sq_mode_sync2(3 downto 0)
                ) = '1';
            end if;

            if INPUT_PIPE > 0 then
                hit_eff := hit_pipe;
                sq_eff := sq_pipe = '1';
            else
                hit_eff := hit;
                sq_eff := sq_ok;
            end if;
            store_ok := store_tick and sq_eff;
            hit_pipe <= hit;
            sq_pipe <= bool_to_sl(sq_ok);

            if (reset_sync(1) xor reset_sync(0)) = '1' then
                armed <= startup_arm_sync2;
                triggered <= '0';
                done <= '0';
                overflow <= '0';
                wr_ptr <= 0;
                start_ptr <= 0;
                trig_ptr <= 0;
                pre_count <= 0;
                post_count <= 0;
                capture_len <= 0;
                cur_segment <= 0;
                seg_count <= 0;
                all_seg_done <= '0';
                segment_wrapped <= '0';
                trig_delay_pending <= '0';
                trig_delay_count <= 0;
                trig_holdoff_active <= '0';
                hit_pipe <= '0';
                sq_pipe <= '1';
                if startup_arm_sync2 = '1' and trig_holdoff_sync2 > 0 then
                    trig_holdoff_active <= '1';
                    trig_holdoff_count <= trig_holdoff_sync2 - 1;
                end if;
            elsif (arm_sync(1) xor arm_sync(0)) = '1' then
                armed <= '1';
                triggered <= '0';
                done <= '0';
                overflow <= '1' when pretrig_len_sync2 + posttrig_len_sync2 + 1 > SEG_DEPTH else '0';
                wr_ptr <= 0;
                start_ptr <= 0;
                trig_ptr <= 0;
                pre_count <= 0;
                post_count <= 0;
                capture_len <= 0;
                cur_segment <= 0;
                seg_count <= 0;
                all_seg_done <= '0';
                segment_wrapped <= '0';
                trig_delay_pending <= '0';
                trig_delay_count <= 0;
                trig_holdoff_active <= '1' when trig_holdoff_sync2 > 0 else '0';
                trig_holdoff_count <= trig_holdoff_sync2 - 1 when trig_holdoff_sync2 > 0 else 0;
                hit_pipe <= '0';
                sq_pipe <= '1';
            elsif armed = '1' and done = '0' then
                base := seg_base(cur_segment);
                trigger_commit_now := false;

                if triggered = '0' then
                    if trig_delay_pending = '1' then
                        if trig_delay_count = 0 then
                            trigger_commit_now := true;
                            trig_delay_pending <= '0';
                        else
                            trig_delay_count <= trig_delay_count - 1;
                        end if;
                    elsif pre_count >= pretrig_len_sync2 and trig_holdoff_active = '0' and hit_eff = '1' then
                        if trig_delay_sync2 = 0 then
                            trigger_commit_now := true;
                        else
                            trig_delay_pending <= '1';
                            trig_delay_count <= trig_delay_sync2 - 1;
                        end if;
                    end if;

                    store_now := store_ok or trigger_commit_now;
                    if store_now then
                        mem_we_a <= '1';
                        mem_addr_a <= std_logic_vector(to_unsigned(wr_ptr, PTR_W));
                        sample_mem_din <= compare_probe;
                        ts_mem_din <= std_logic_vector(timestamp_counter);
                    end if;

                    if store_ok and not trigger_commit_now then
                        if pre_count < SEG_DEPTH then
                            pre_count <= pre_count + 1;
                        end if;
                        if wr_ptr = base + SEG_DEPTH - 1 then
                            segment_wrapped <= '1';
                        end if;
                    end if;

                    if trigger_commit_now then
                        triggered <= '1';
                        trigger_out_i <= '1';
                        trig_ptr <= wr_ptr;
                        capture_len <= pretrig_len_sync2 + posttrig_len_sync2 + 1;
                        post_count <= 0;
                        if posttrig_len_sync2 = 0 then
                            start_calc := capture_start_ptr(wr_ptr, pretrig_len_sync2, posttrig_len_sync2, base, segment_wrapped);
                            seg_start_ptr(cur_segment) <= start_calc;
                            if cur_segment = NUM_SEGMENTS - 1 then
                                done <= '1';
                                armed <= '0';
                                all_seg_done <= '1';
                                start_ptr <= start_calc;
                                seg_count <= NUM_SEGMENTS;
                            else
                                next_segment := cur_segment + 1;
                                cur_segment <= next_segment;
                                seg_count <= seg_count + 1;
                                triggered <= '0';
                                pre_count <= 0;
                                post_count <= 0;
                                wr_ptr <= seg_base(next_segment);
                                segment_wrapped <= '0';
                                hit_pipe <= '0';
                                sq_pipe <= '1';
                            end if;
                        end if;
                    end if;

                    if store_now and not (trigger_commit_now and posttrig_len_sync2 = 0) then
                        wr_ptr <= next_ptr(wr_ptr, base);
                    end if;
                else
                    post_limit := posttrig_len_sync2;
                    if store_ok then
                        mem_we_a <= '1';
                        mem_addr_a <= std_logic_vector(to_unsigned(wr_ptr, PTR_W));
                        sample_mem_din <= compare_probe;
                        ts_mem_din <= std_logic_vector(timestamp_counter);
                        if post_count + 1 >= post_limit then
                            start_calc := capture_start_ptr(trig_ptr, pretrig_len_sync2, posttrig_len_sync2, base, segment_wrapped);
                            seg_start_ptr(cur_segment) <= start_calc;
                            if cur_segment = NUM_SEGMENTS - 1 then
                                done <= '1';
                                armed <= '0';
                                all_seg_done <= '1';
                                start_ptr <= start_calc when NUM_SEGMENTS = 1 else seg_start_ptr(0);
                                seg_count <= NUM_SEGMENTS;
                            else
                                next_segment := cur_segment + 1;
                                cur_segment <= next_segment;
                                seg_count <= seg_count + 1;
                                triggered <= '0';
                                pre_count <= 0;
                                post_count <= 0;
                                wr_ptr <= seg_base(next_segment);
                                segment_wrapped <= '0';
                                trig_delay_pending <= '0';
                                trig_holdoff_active <= '1' when trig_holdoff_sync2 > 0 else '0';
                                trig_holdoff_count <= trig_holdoff_sync2 - 1 when trig_holdoff_sync2 > 0 else 0;
                                hit_pipe <= '0';
                                sq_pipe <= '1';
                            end if;
                        else
                            post_count <= post_count + 1;
                        end if;
                        wr_ptr <= next_ptr(wr_ptr, base);
                    end if;
                end if;
            end if;

            probe_prev <= compare_probe;
        end if;
    end process;

    p_data_read_sample : process(sample_clk, sample_rst)
        variable addr : natural;
        variable word_index : natural;
        variable sample_index : natural;
        variable rd_start : natural;
        variable rd_start_u : unsigned(PTR_W - 1 downto 0);
        variable rd_base_u : unsigned(PTR_W - 1 downto 0);
        variable wrap_mask : unsigned(PTR_W - 1 downto 0);
    begin
        if sample_rst = '1' then
            rd_req_sync <= (others => '0');
            rd_addr_sync1 <= (others => '0');
            rd_addr_sync2 <= (others => '0');
            rd_addr_req <= (others => '0');
            seg_sel_rd_sync1 <= 0;
            seg_sel_rd_sync2 <= 0;
            seg_start_ptr_rd <= 0;
            rd_phase <= RD_IDLE;
            rd_is_ts <= '0';
            rd_data_sample <= (others => '0');
            ts_rd_data_sample <= (others => '0');
            rd_ack_toggle_sample <= '0';
            mem_rd_pending <= '0';
            mem_rd_idx <= (others => '0');
        elsif rising_edge(sample_clk) then
            rd_req_sync <= rd_req_sync(1 downto 0) & rd_req_toggle_jtag;
            rd_addr_sync1 <= rd_addr_jtag;
            rd_addr_sync2 <= rd_addr_sync1;
            seg_sel_rd_sync1 <= jtag_seg_sel;
            seg_sel_rd_sync2 <= seg_sel_rd_sync1;
            seg_start_ptr_rd <= seg_start_ptr(seg_sel_rd_sync2);

            case rd_phase is
                when RD_CAPTURE =>
                    rd_data_sample <= sample_mem_dout_a;
                    if TIMESTAMP_W > 0 and rd_is_ts = '1' then
                        ts_rd_data_sample <= ts_mem_dout_a;
                    else
                        ts_rd_data_sample <= (others => '0');
                    end if;
                    mem_rd_pending <= '0';
                    rd_phase <= RD_ACK;
                when RD_ACK =>
                    rd_ack_toggle_sample <= not rd_ack_toggle_sample;
                    rd_is_ts <= '0';
                    rd_phase <= RD_IDLE;
                when RD_WAIT_DATA =>
                    rd_phase <= RD_CAPTURE;
                when RD_WAIT_ADDR =>
                    rd_phase <= RD_WAIT_DATA;
                when RD_DECODE =>
                    addr := to_integer(unsigned(rd_addr_req));
                    rd_start := start_ptr;
                    if NUM_SEGMENTS > 1 then
                        rd_start := seg_start_ptr_rd;
                    end if;
                    rd_start_u := to_unsigned(rd_start, PTR_W);
                    rd_base_u := rd_start_u;
                    if NUM_SEGMENTS > 1 then
                        rd_base_u(SEG_PTR_W - 1 downto 0) := (others => '0');
                    else
                        rd_base_u := (others => '0');
                    end if;
                    wrap_mask := to_unsigned(SEG_DEPTH - 1, PTR_W);
                    if TIMESTAMP_W > 0 and addr >= ADDR_TS_DATA_BASE then
                        word_index := (addr - ADDR_TS_DATA_BASE) / 4;
                        sample_index := word_index / TS_WORDS;
                        if sample_index < capture_len then
                            mem_rd_idx <= std_logic_vector(rd_base_u + ((rd_start_u - rd_base_u + to_unsigned(sample_index, PTR_W)) and wrap_mask));
                            mem_rd_pending <= '1';
                            rd_is_ts <= '1';
                            rd_phase <= RD_WAIT_ADDR;
                        else
                            ts_rd_data_sample <= (others => '0');
                            rd_phase <= RD_ACK;
                        end if;
                    elsif addr >= ADDR_DATA_BASE and addr < ADDR_TS_DATA_BASE then
                        word_index := (addr - ADDR_DATA_BASE) / 4;
                        sample_index := word_index / WORDS_PER_SAMPLE;
                        if sample_index < capture_len then
                            mem_rd_idx <= std_logic_vector(rd_base_u + ((rd_start_u - rd_base_u + to_unsigned(sample_index, PTR_W)) and wrap_mask));
                            mem_rd_pending <= '1';
                            rd_is_ts <= '0';
                            rd_phase <= RD_WAIT_ADDR;
                        else
                            rd_data_sample <= (others => '0');
                            rd_phase <= RD_ACK;
                        end if;
                    else
                        rd_data_sample <= (others => '0');
                        ts_rd_data_sample <= (others => '0');
                        rd_phase <= RD_ACK;
                    end if;
                when others =>
                    if (rd_req_sync(1) xor rd_req_sync(2)) = '1' then
                        rd_addr_req <= rd_addr_sync2;
                        rd_phase <= RD_DECODE;
                    end if;
            end case;
        end if;
    end process;

    p_data_read_jtag : process(jtag_clk, jtag_rst)
        variable addr : natural;
    begin
        if jtag_rst = '1' then
            rd_ack_sync <= (others => '0');
            rd_data_sync1 <= (others => '0');
            rd_data_sync2 <= (others => '0');
            ts_rd_data_sync1 <= (others => '0');
            ts_rd_data_sync2 <= (others => '0');
            rd_addr_data_window <= '0';
            jtag_rdata_i <= (others => '0');
        elsif rising_edge(jtag_clk) then
            rd_ack_sync <= rd_ack_sync(0) & rd_ack_toggle_sample;
            rd_data_sync1 <= rd_data_sample;
            rd_data_sync2 <= rd_data_sync1;
            ts_rd_data_sync1 <= ts_rd_data_sample;
            ts_rd_data_sync2 <= ts_rd_data_sync1;

            if jtag_rd_en = '1' then
                addr := to_integer(unsigned(jtag_addr));
                if USER1_DATA_EN /= 0 and
                   (addr >= ADDR_DATA_BASE or (TIMESTAMP_W > 0 and addr >= ADDR_TS_DATA_BASE)) then
                    rd_addr_data_window <= '1';
                else
                    rd_addr_data_window <= '0';
                    jtag_rdata_i <= jtag_rdata_mux;
                end if;
            end if;

            if (rd_ack_sync(0) xor rd_ack_sync(1)) = '1' then
                addr := to_integer(unsigned(rd_addr_jtag));
                if rd_addr_data_window = '1' then
                    if TIMESTAMP_W > 0 and addr >= ADDR_TS_DATA_BASE then
                        jtag_rdata_i <= ts_word(addr, ts_rd_data_sync1);
                    else
                        jtag_rdata_i <= sample_word(addr, rd_data_sync1);
                    end if;
                end if;
            end if;
        end if;
    end process;

    p_read_mux : process(all)
        variable addr : natural;
        variable r : std_logic_vector(31 downto 0);
        variable word_index : natural;
        variable sample_index : natural;
        variable rd_start : natural;
        variable ts_read_word : std_logic_vector(31 downto 0);
        variable seq_stage : natural;
        variable seq_off : natural;
    begin
        addr := to_integer(unsigned(jtag_addr));
        r := (others => '0');
        rd_start := start_ptr;
        if NUM_SEGMENTS > 1 then
            rd_start := seg_start_ptr(jtag_seg_sel);
        end if;

        case addr is
            when ADDR_VERSION => r := FCAPZ_ELA_VERSION_REG;
            when ADDR_CTRL => r := jtag_ctrl;
            when ADDR_STATUS => r := x"0000000" & overflow & done & triggered & armed;
            when ADDR_SAMPLE_W => r := u32(SAMPLE_W);
            when ADDR_DEPTH => r := u32(DEPTH);
            when ADDR_PRETRIG => r := jtag_pretrig_len;
            when ADDR_POSTTRIG => r := jtag_posttrig_len;
            when ADDR_CAPTURE_LEN => r := u32(capture_len);
            when ADDR_TRIG_MODE => r := jtag_trig_mode;
            when ADDR_TRIG_VALUE => r := jtag_trig_value;
            when ADDR_TRIG_MASK => r := jtag_trig_mask;
            when ADDR_SQ_MODE => r := jtag_sq_mode when STOR_QUAL /= 0 else x"00000000";
            when ADDR_SQ_VALUE => r := jtag_sq_value when STOR_QUAL /= 0 else x"00000000";
            when ADDR_SQ_MASK => r := jtag_sq_mask when STOR_QUAL /= 0 else x"00000000";
            when ADDR_FEATURES => r := FEATURES;
            when ADDR_CHAN_SEL => r := u32(jtag_chan_sel);
            when ADDR_NUM_CHAN => r := u32(NUM_CHANNELS);
            when ADDR_DECIM => r := x"00" & jtag_decim;
            when ADDR_TRIG_EXT => r := u32(to_integer(unsigned(jtag_trig_ext)));
            when ADDR_NUM_SEGMENTS => r := u32(NUM_SEGMENTS);
            when ADDR_SEG_STATUS =>
                r := (others => '0');
                r(31) := all_seg_done when NUM_SEGMENTS > 1 else '1';
                r(SEG_IDX_W - 1 downto 0) := std_logic_vector(to_unsigned(seg_count mod (2 ** SEG_IDX_W), SEG_IDX_W));
            when ADDR_SEG_SEL => r := u32(jtag_seg_sel);
            when ADDR_TIMESTAMP_W => r := u32(TIMESTAMP_W);
            when ADDR_SEG_START => r := u32(rd_start);
            when ADDR_PROBE_SEL => r := u32(jtag_probe_sel);
            when ADDR_PROBE_MUX_W => r := u32(PROBE_MUX_W);
            when ADDR_TRIG_DELAY => r := x"0000" & jtag_trig_delay;
            when ADDR_STARTUP_ARM => r := (31 downto 1 => '0') & jtag_startup_arm;
            when ADDR_TRIG_HOLDOFF => r := x"0000" & jtag_trig_holdoff;
            when ADDR_COMPARE_CAPS =>
                r := x"000201FF" when REL_COMPARE /= 0 else x"000201C3";
                if DUAL_COMPARE /= 0 then
                    r(16) := '1';
                end if;
            when others =>
                if USER1_DATA_EN /= 0 and addr >= ADDR_DATA_BASE and addr < ADDR_TS_DATA_BASE then
                    word_index := (addr - ADDR_DATA_BASE) / 4;
                    sample_index := word_index / WORDS_PER_SAMPLE;
                    if sample_index < capture_len then
                        r := sample_word(addr, sample_mem_dout_b);
                    end if;
                elsif TIMESTAMP_W > 0 and addr >= ADDR_TS_DATA_BASE then
                    word_index := (addr - ADDR_TS_DATA_BASE) / 4;
                    sample_index := word_index / TS_WORDS;
                    if sample_index < capture_len then
                        ts_read_word := (others => '0');
                        for i in 0 to 31 loop
                            if i < TIMESTAMP_W then
                                ts_read_word(i) := ts_mem_dout_b(i);
                            end if;
                        end loop;
                        r := ts_read_word;
                    end if;
                elsif TRIG_STAGES > 1 and addr >= ADDR_SEQ_BASE and addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE then
                    seq_stage := (addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                    seq_off := (addr - ADDR_SEQ_BASE) mod SEQ_STRIDE;
                    case seq_off is
                        when 0 => r := jtag_seq_cfg(seq_stage);
                        when 4 => r := jtag_seq_value_a(seq_stage);
                        when 8 => r := jtag_seq_mask_a(seq_stage);
                        when 12 =>
                            if DUAL_COMPARE /= 0 then
                                r := jtag_seq_value_b(seq_stage);
                            end if;
                        when 16 =>
                            if DUAL_COMPARE /= 0 then
                                r := jtag_seq_mask_b(seq_stage);
                            else
                                r := x"FFFFFFFF";
                            end if;
                        when others => null;
                    end case;
                end if;
        end case;

        jtag_rdata_mux <= r;
    end process;
end architecture rtl;
