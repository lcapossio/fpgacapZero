-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
--
-- WIDE_TRIG PARITY: this VHDL core mirrors the Verilog fcapz_ela.v WIDE_TRIG
-- parameter (WIDE_SEL/WIDE_DATA indexed-word window) that makes comparator A
-- programmable across the full SAMPLE_W instead of just the low 32 bits.  With
-- the default WIDE_TRIG=0 the wide path is dead (upper trigger bits are constant
-- 0, synthesised away) so the legacy 32-bit behaviour is bit-identical.  Parity
-- is checked by the shared cocotb suite (run_cocotb_ela.py) which runs the same
-- stimulus against both the Verilog and VHDL ELA -- including the new
-- 'wide_trigger_upper_bit' test that programs the WIDE window and triggers on a
-- bit above 31 -- plus the static/interface parity gates (run_hdl_parity.py,
-- run_formal_hdl_parity.py --interface-only).

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
        USER1_DATA_EN    : natural  := 1;
        RLE_W            : natural  := 0;   -- 0 = no run-length capture, 1..16 = run-count width
        WIDE_TRIG        : natural  := 0
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
        burst_rd_active  : in  std_logic;
        burst_rd_data    : out std_logic_vector(SAMPLE_W - 1 downto 0);
        -- Timestamps, or run counts when the burst asks for them (BURST_PTR[30]).
        burst_rd_ts_data : out std_logic_vector(fcapz_nonzero_width(fcapz_ela_aux_w(TIMESTAMP_W, RLE_W)) - 1 downto 0);
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

    function u32(v : unsigned) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable n : natural := v'length;
    begin
        if n > 32 then
            n := 32;
        end if;
        r(n - 1 downto 0) := std_logic_vector(v(n - 1 downto 0));
        return r;
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

    function is_power_of_two(n : positive) return boolean is
        variable value : natural := n;
    begin
        while (value mod 2) = 0 loop
            value := value / 2;
        end loop;
        return value = 1;
    end function;

    constant PTR_W            : positive := fcapz_clog2(DEPTH);
    -- Capture lengths are counts, not pointers, and a length may legally
    -- equal DEPTH, so they need one bit more than an address.  Mirrors
    -- LEN_W in rtl/fcapz_ela.v.
    constant LEN_W            : positive := fcapz_clog2(DEPTH + 1);
    constant WORDS_PER_SAMPLE : positive := (SAMPLE_W + 31) / 32;
    constant SEG_DEPTH        : positive := DEPTH / NUM_SEGMENTS;
    constant SEG_PTR_W        : positive := fcapz_clog2(SEG_DEPTH);
    constant SEG_IDX_W        : positive := fcapz_clog2(NUM_SEGMENTS);
    constant SEQ_STATE_W      : positive := fcapz_clog2(TRIG_STAGES);
    constant TS_WIDTH         : positive := fcapz_nonzero_width(TIMESTAMP_W);
    -- Probe pipeline stages actually built.  The external trigger needs a
    -- 2-FF synchronizer, so a core with EXT_TRIG_EN and INPUT_PIPE = 0 is
    -- built with one input stage: with the registered compare the probe path
    -- is then as long as the synchronizer (see rtl/fcapz_ela.v PROBE_PIPE).
    constant PROBE_PIPE       : natural := bool_to_nat(EXT_TRIG_EN /= 0 and INPUT_PIPE = 0) + INPUT_PIPE;
    -- PROBE_PIPE probe register stages; the array keeps one when PROBE_PIPE = 0
    -- so its bounds stay legal, and that stage is then unused.
    constant PIPE_STAGES      : positive := fcapz_nonzero_width(PROBE_PIPE);
    -- Extra trigger_in stages beyond the 2-FF synchronizer, so an external
    -- trigger reaches the capture decision with the same latency as the probe
    -- sample it marks (PROBE_PIPE plus the registered compare, at least 2
    -- with EXT_TRIG_EN), as in rtl/fcapz_ela.v.
    constant EXT_ALIGN        : natural := bool_to_nat(PROBE_PIPE >= 2) * (PROBE_PIPE - 1);
    -- Sample clocks after an arm that switches channel or probe slice before
    -- the stored sample and both compare operands come from the new one, as
    -- in rtl/fcapz_ela.v.
    constant SEL_FLUSH_LEN    : positive := PROBE_PIPE + bool_to_nat(PROBE_PIPE > 0) + 1;
    constant HAS_RLE          : boolean := RLE_W > 0;
    -- A clock limit can end a segment short, so segmented RLE builds keep
    -- each segment's entry count for CAPTURE_LEN.
    constant HAS_RLE_SEG_LEN  : boolean := HAS_RLE and NUM_SEGMENTS > 1;
    constant RLE_DATA_W       : positive := fcapz_nonzero_width(RLE_W);
    constant RLE_COUNT_MAX    : unsigned(RLE_DATA_W - 1 downto 0) := (others => '1');
    -- Aux lane (timestamp burst lane and DATA window): timestamps, or run
    -- counts on a core without timestamps.
    constant AUX_W            : natural := fcapz_ela_aux_w(TIMESTAMP_W, RLE_W);
    constant AUX_DATA_W       : positive := fcapz_nonzero_width(AUX_W);
    constant AUX_WORDS        : natural := (AUX_W + 31) / 32;
    -- RLE_POST_CLKS width: the most clocks a post-trigger window of entries
    -- can span ((DEPTH - 1) * 2^RLE_W < 2^(LEN_W + RLE_W)), capped at 32.
    -- Mirrors POST_CLK_W in rtl/fcapz_ela.v.
    constant POST_CLK_W       : positive :=
        bool_to_nat(not HAS_RLE) +
        bool_to_nat(HAS_RLE and LEN_W + RLE_W > 32) * 32 +
        bool_to_nat(HAS_RLE and LEN_W + RLE_W <= 32) * (LEN_W + RLE_W);

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
    constant ADDR_WIDE_SEL     : natural := 16#00E4#;
    constant ADDR_WIDE_DATA    : natural := 16#00F0#;
    -- RW (USER1_DATA_EN): word offset added to every DATA / timestamp window
    -- read, so a host can page through windows the 16-bit address cannot reach.
    constant ADDR_DATA_OFFSET  : natural := 16#00F4#;
    -- RO: [15:0] capture generation (COMPARE_CAPS bit 21); see p_capture_gen.
    constant ADDR_CAPTURE_GEN  : natural := 16#00F8#;
    -- Run-length capture (RLE_W > 0).  RLE_CTRL[0] enables it (taken on
    -- arm); RLE_CTRL[1] makes the timestamp DATA window return run counts.
    constant ADDR_RLE_CTRL     : natural := 16#00A8#;  -- RW
    constant ADDR_RLE_W        : natural := 16#00CC#;  -- RO: RLE_W (0 = no RLE)
    -- RLE only: also end the post-trigger window this many sample clocks
    -- after the trigger commit (0 = entries only).  Taken on arm.
    constant ADDR_RLE_POST_CLKS : natural := 16#0090#;  -- RW
    constant ADDR_DATA_BASE    : natural := 16#0100#;

    -- Full-width comparator A programmability (mirrors the Verilog WIDE_TRIG).
    constant HAS_WIDE_TRIG : boolean := (WIDE_TRIG /= 0) and (SAMPLE_W > 32);
    constant ADDR_TS_DATA_BASE : natural := ADDR_DATA_BASE + DEPTH * WORDS_PER_SAMPLE * 4;
    -- Words in the DATA window and the auxiliary (timestamp / run count)
    -- window after it.
    constant DATA_WINDOW_WORDS : natural := DEPTH * WORDS_PER_SAMPLE
                                          + DEPTH * AUX_WORDS;
    constant DATA_OFFSET_W     : positive := fcapz_clog2(DATA_WINDOW_WORDS + 1);

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
    type seg_len_t is array (0 to NUM_SEGMENTS - 1) of unsigned(PTR_W downto 0);
    type reg32_array_t is array (natural range <>) of std_logic_vector(31 downto 0);
    type sample_array_t is array (natural range <>) of std_logic_vector(SAMPLE_W - 1 downto 0);
    type seq_mode_array_t is array (natural range <>) of std_logic_vector(3 downto 0);
    type seq_combine_array_t is array (natural range <>) of std_logic_vector(1 downto 0);
    type seq_count_array_t is array (natural range <>) of unsigned(15 downto 0);
    type seq_next_array_t is array (natural range <>) of std_logic_vector(SEQ_STATE_W - 1 downto 0);
    type seq_flag_array_t is array (natural range <>) of std_logic;

    -- seq_count_reached in rtl/fcapz_ela.v.  17-bit compare: seq_counter
    -- saturates at x"FFFF", and a 16-bit x"FFFF" + 1 would wrap to 0 and miss
    -- the hit (BUG-255).  A target of 0 bypasses the count.
    function seq_count_reached(counter : unsigned(15 downto 0);
                               target  : unsigned(15 downto 0)) return boolean is
    begin
        return target = 0 or resize(counter, 17) + 1 >= resize(target, 17);
    end function;

    signal jtag_ctrl         : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_pretrig_len  : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_posttrig_len : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_trig_mode    : std_logic_vector(31 downto 0) := x"00000001";
    signal jtag_trig_value   : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_trig_mask    : std_logic_vector(31 downto 0) := x"FFFFFFFF";
    -- Wide comparator-A words (WIDE_TRIG).  Word 0 mirrors the 32-bit
    -- TRIG_VALUE/MASK registers; higher words come from the WIDE_SEL/WIDE_DATA
    -- window.  jtag_trig_value_w/mask_w assemble the full-width value/mask fed
    -- across the CDC.
    signal jtag_wide_sel     : std_logic_vector(7 downto 0) := (others => '0');
    signal wide_va           : reg32_array_t(0 to WORDS_PER_SAMPLE - 1) := (others => (others => '0'));
    signal wide_ma           : reg32_array_t(0 to WORDS_PER_SAMPLE - 1) := (others => (others => '0'));
    signal jtag_trig_value_w : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal jtag_trig_mask_w  : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal jtag_sq_mode      : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_sq_value     : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_sq_mask      : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_seq_cfg      : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_value_a  : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_mask_a   : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal jtag_seq_value_b  : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal jtag_seq_mask_b   : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal jtag_decim        : std_logic_vector(23 downto 0) := (others => '0');
    signal jtag_trig_ext     : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal jtag_probe_sel    : natural range 0 to 255 := 0;
    signal jtag_chan_sel     : natural range 0 to 255 := 0;
    signal jtag_seg_sel      : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal jtag_startup_arm  : std_logic := bool_to_sl(STARTUP_ARM /= 0);
    signal jtag_trig_delay   : std_logic_vector(15 downto 0) := (others => '0');
    signal jtag_trig_holdoff : std_logic_vector(15 downto 0) := (others => '0');

    -- Settings snapshot on ARM / RESET (*_hold, jtag_clk) and its sample_clk
    -- copy (*_stage), as in rtl/fcapz_ela.v.
    signal pretrig_len_hold      : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal pretrig_len_stage      : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal posttrig_len_hold     : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal posttrig_len_stage     : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal trig_mode_hold        : std_logic_vector(31 downto 0) := (others => '0');
    signal trig_mode_stage        : std_logic_vector(31 downto 0) := (others => '0');
    -- Widened to SAMPLE_W so the full comparator-A value/mask can cross the CDC
    -- (WIDE_TRIG).  For WIDE_TRIG=0 the upper bits are constant 0 and optimize
    -- away, leaving the legacy 32-bit behaviour bit-identical.
    signal trig_value_hold       : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trig_value_stage       : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trig_mask_hold        : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trig_mask_stage        : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal pretrig_len            : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal posttrig_len           : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal cap_trig_mode          : std_logic_vector(31 downto 0) := x"00000001";
    signal cap_trig_value         : std_logic_vector(31 downto 0) := (others => '0');
    signal cap_trig_mask          : std_logic_vector(31 downto 0) := x"FFFFFFFF";
    signal trig_delay             : unsigned(15 downto 0) := (others => '0');
    signal trig_cmp_mode_a        : std_logic_vector(3 downto 0) := (others => '0');
    signal trig_cmp_mode_b        : std_logic_vector(3 downto 0) := (others => '0');
    signal trig_combine           : std_logic_vector(1 downto 0) := (others => '0');
    signal trig_value             : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trig_mask              : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '1');
    signal trig_value_b           : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal trig_mask_b            : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '1');
    signal chan_sel               : natural range 0 to 255 := 0;
    signal probe_sel              : natural range 0 to 255 := 0;
    signal decim_ratio            : unsigned(23 downto 0) := (others => '0');
    signal ext_trig_mode          : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal sq_enable              : std_logic := '0';
    signal sq_cmp_mode            : std_logic_vector(3 downto 0) := (others => '0');
    signal sq_value               : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal sq_mask                : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal seq_mode_a             : seq_mode_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mode_b             : seq_mode_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_combine            : seq_combine_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_a            : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_a             : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal seq_value_b            : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_b             : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '1'));
    signal seq_count_target       : seq_count_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_next_state         : seq_next_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_is_final           : seq_flag_array_t(0 to TRIG_STAGES - 1) := (others => '0');
    signal decim_hold            : unsigned(23 downto 0) := (others => '0');
    signal decim_stage            : unsigned(23 downto 0) := (others => '0');
    signal trig_ext_hold         : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal trig_ext_stage         : std_logic_vector(1 downto 0) := std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
    signal probe_sel_hold        : natural range 0 to 255 := 0;
    signal probe_sel_stage        : natural range 0 to 255 := 0;
    signal chan_sel_hold         : natural range 0 to 255 := 0;
    signal chan_sel_stage         : natural range 0 to 255 := 0;
    signal startup_arm_hold      : std_logic := '0';
    signal startup_arm_stage      : std_logic := '0';
    signal trig_delay_hold       : unsigned(15 downto 0) := (others => '0');
    signal trig_delay_stage       : unsigned(15 downto 0) := (others => '0');
    signal trig_holdoff_hold     : unsigned(15 downto 0) := (others => '0');
    signal trig_holdoff_stage     : unsigned(15 downto 0) := (others => '0');
    signal sq_mode_hold          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mode_stage          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_value_hold         : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_value_stage         : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mask_hold          : std_logic_vector(31 downto 0) := (others => '0');
    signal sq_mask_stage          : std_logic_vector(31 downto 0) := (others => '0');
    signal seq_cfg_hold          : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_cfg_stage          : reg32_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_a_hold      : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_a_stage      : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_a_hold       : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_a_stage       : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_b_hold      : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_value_b_stage      : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_b_hold       : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));
    signal seq_mask_b_stage       : sample_array_t(0 to TRIG_STAGES - 1) := (others => (others => '0'));

    signal arm_toggle_jtag   : std_logic := '0';
    signal reset_toggle_jtag : std_logic := '0';
    -- sync1 -> sync2 synchronize the toggles.  A toggle reaching sync2 stages
    -- the settings (cfg_stage_en); sync3 xor sync4 then pulses with them in
    -- place.
    signal arm_toggle_sync1  : std_logic := '0';
    signal arm_toggle_sync2  : std_logic := '0';
    signal arm_toggle_sync3  : std_logic := '0';
    signal arm_toggle_sync4  : std_logic := '0';
    signal reset_toggle_sync1 : std_logic := '0';
    signal reset_toggle_sync2 : std_logic := '0';
    signal reset_toggle_sync3 : std_logic := '0';
    signal reset_toggle_sync4 : std_logic := '0';
    signal arm_sync_pulse    : std_logic := '0';  -- an ARM reaches the capture
    signal reset_sync_pulse  : std_logic := '0';  -- a soft reset reaches it
    signal cfg_stage_en      : std_logic := '0';  -- copy *_hold into *_stage

    signal armed             : std_logic := '0';
    signal triggered         : std_logic := '0';
    signal done              : std_logic := '0';
    signal overflow          : std_logic := '0';
    signal trigger_out_i     : std_logic := '0';
    signal trigger_in_sync1  : std_logic := '0';
    signal trigger_in_sync2  : std_logic := '0';
    signal trigger_in_aligned : std_logic := '0';
    signal wr_ptr            : natural range 0 to DEPTH - 1 := 0;
    signal start_ptr         : natural range 0 to DEPTH - 1 := 0;
    signal trig_ptr          : natural range 0 to DEPTH - 1 := 0;
    signal pre_count         : unsigned(PTR_W downto 0) := (others => '0');
    -- Post-trigger samples still to store, loaded with posttrig_len at the
    -- trigger commit and counted down.  LEN_W wide, like the Verilog core's:
    -- posttrig_len may legally hold DEPTH.  post_left_zero / post_left_one are
    -- registered (post_left = 0) / (post_left = 1), so the segment-complete
    -- decision starts at a flop, not a counter compare.
    signal post_left         : unsigned(LEN_W - 1 downto 0) := (others => '0');
    signal post_left_zero    : std_logic := '1';
    signal post_left_one     : std_logic := '0';
    signal capture_len       : unsigned(PTR_W downto 0) := (others => '0');
    -- RLE clock limit on the post-trigger window, latched on arm.  The
    -- trigger commit is clock 0; post_clk_left counts the clocks still
    -- allowed after it, and post_clk_last is registered
    -- (post_clk_left = 1), so the stop starts at a flop.
    signal rle_post_clks     : unsigned(POST_CLK_W - 1 downto 0) := (others => '0');
    signal post_clk_en       : std_logic := '0';  -- RLE on and a limit set
    signal post_clk_one      : std_logic := '0';  -- the limit is 1
    signal post_clk_left     : unsigned(POST_CLK_W - 1 downto 0) := (others => '0');
    signal post_clk_last     : std_logic := '0';
    signal clk_stop_now      : std_logic := '0';
    signal post_done_now     : std_logic := '0';
    signal capture_len_done  : unsigned(PTR_W downto 0) := (others => '0');
    -- Entries in each completed segment (HAS_RLE_SEG_LEN only); cleared on
    -- arm.  Read back only for captures with a clock limit.
    signal seg_len           : seg_len_t := (others => (others => '0'));
    signal probe_prev        : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal decim_count       : unsigned(23 downto 0) := (others => '0');
    signal timestamp_counter : unsigned(TS_WIDTH - 1 downto 0) := (others => '0');
    signal cur_segment       : natural range 0 to NUM_SEGMENTS - 1 := 0;
    signal seg_count         : natural range 0 to NUM_SEGMENTS := 0;
    signal all_seg_done      : std_logic := '0';
    signal seg_start_ptr     : seg_ptr_t := (others => 0);
    signal segment_wrapped   : std_logic := '0';
    signal seq_state         : natural range 0 to TRIG_STAGES - 1 := 0;
    signal seq_counter       : unsigned(15 downto 0) := (others => '0');
    signal trig_delay_pending: std_logic := '0';
    signal trig_delay_count  : unsigned(15 downto 0) := (others => '0');
    signal trig_holdoff      : unsigned(15 downto 0) := (others => '0');
    signal trig_holdoff_count: unsigned(15 downto 0) := (others => '0');
    signal trig_holdoff_active : std_logic := '0';
    signal startup_arm_pending : std_logic := bool_to_sl(STARTUP_ARM /= 0);
    signal pipe_probe        : sample_array_t(0 to PIPE_STAGES - 1) := (others => (others => '0'));
    signal hit_a_pipe        : std_logic := '0';
    signal hit_b_pipe        : std_logic := '0';
    -- Per-stage registered sequencer hits (PROBE_PIPE > 0, TRIG_STAGES > 1).
    signal seq_pipe_a        : std_logic_vector(TRIG_STAGES - 1 downto 0) := (others => '0');
    signal seq_pipe_b        : std_logic_vector(TRIG_STAGES - 1 downto 0) := (others => '0');
    signal sq_pipe           : std_logic := '0';
    signal chan_sel_next     : natural range 0 to 255 := 0;
    signal probe_sel_next    : natural range 0 to 255 := 0;
    signal arm_sel_change    : std_logic := '0';
    signal sel_flush_start   : std_logic := '0';
    signal arm_sq_bubble     : std_logic := '0';
    signal sq_mode_on        : std_logic := '0';
    signal arm_voids_history : std_logic := '0';
    signal sel_flush_active  : std_logic := '0';
    signal capture_restart   : std_logic := '0';
    -- Run-length capture: [0]=enable, [1]=DATA window reads counts
    signal jtag_rle_ctrl     : std_logic_vector(1 downto 0) := "00";
    signal burst_rle         : std_logic := '0';  -- this burst reads run counts
    signal jtag_rle_post_clks : std_logic_vector(POST_CLK_W - 1 downto 0) := (others => '0');  -- 0 = no clock limit
    signal rle_post_clks_hold : unsigned(POST_CLK_W - 1 downto 0) := (others => '0');
    signal rle_post_clks_stage : unsigned(POST_CLK_W - 1 downto 0) := (others => '0');
    signal rle_en_hold      : std_logic := '0';
    signal rle_en_stage      : std_logic := '0';
    signal rle_active_next   : std_logic := '0';
    signal arm_rle_change    : std_logic := '0';
    signal rle_active        : std_logic := '0';  -- latched on arm
    signal rle_open          : std_logic := '0';  -- the newest entry can still be extended
    signal rle_value         : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal rle_count         : unsigned(RLE_DATA_W - 1 downto 0) := (others => '0');  -- run length - 1
    signal rle_addr          : natural range 0 to DEPTH - 1 := 0;
    signal comb_store_base   : std_logic := '0';
    signal comb_rle_repeat   : std_logic := '0';
    signal rle_extend        : std_logic := '0';
    signal rle_seg_end       : std_logic := '0';
    signal rle_we_q          : std_logic := '0';
    signal rle_wr_addr_q     : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal rle_wr_count_q    : std_logic_vector(RLE_DATA_W - 1 downto 0) := (others => '0');
    signal rle_dout_b        : std_logic_vector(RLE_DATA_W - 1 downto 0);
    signal aux_ts_b          : std_logic_vector(AUX_DATA_W - 1 downto 0);
    signal aux_rle_b         : std_logic_vector(AUX_DATA_W - 1 downto 0);
    signal sel_flush_count   : natural range 0 to SEL_FLUSH_LEN - 1 := 0;
    signal jtag_rdata_mux    : std_logic_vector(31 downto 0) := (others => '0');
    signal jtag_rdata_i      : std_logic_vector(31 downto 0) := (others => '0');
    signal mem_we_a          : std_logic := '0';
    signal mem_we_a_q        : std_logic := '0';
    signal mem_we_a_ram      : std_logic := '0';
    signal comb_hit_a        : std_logic := '0';
    signal comb_hit_b        : std_logic := '0';
    signal comb_seq_a        : std_logic_vector(TRIG_STAGES - 1 downto 0) := (others => '0');
    signal comb_seq_b        : std_logic_vector(TRIG_STAGES - 1 downto 0) := (others => '0');
    signal comb_hit_eff      : std_logic := '0';
    signal comb_sq_ok        : std_logic := '1';
    signal comb_store_ok     : std_logic := '0';
    signal comb_trigger_commit_now : std_logic := '0';
    signal comb_seq_stage_hit : std_logic := '0';
    signal mem_addr_a        : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_addr_b        : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_wr_addr       : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal mem_wr_addr_q     : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal sample_mem_din    : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal sample_mem_din_ram : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal mem_wr_data_q     : std_logic_vector(SAMPLE_W - 1 downto 0) := (others => '0');
    signal sample_mem_dout_b : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal ts_mem_din        : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_mem_din_ram    : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal mem_wr_ts_q       : std_logic_vector(TS_WIDTH - 1 downto 0) := (others => '0');
    signal ts_mem_dout_b     : std_logic_vector(TS_WIDTH - 1 downto 0);

    signal burst_start_ptr_i  : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');

    signal rb_done_d              : std_logic := '0';
    signal rb_seg_count_d         : natural range 0 to NUM_SEGMENTS := 0;
    signal rb_meta_toggle_sample  : std_logic := '0';
    signal rb_capture_len_sample  : unsigned(PTR_W downto 0) := (others => '0');
    signal rb_start_ptr_sample    : natural range 0 to DEPTH - 1 := 0;
    signal rb_seg_start_ptr_sample : seg_ptr_t := (others => 0);
    signal rb_seg_len_sample      : seg_len_t := (others => (others => '0'));
    signal rb_meta_toggle_sync1   : std_logic := '0';
    signal rb_meta_toggle_sync2   : std_logic := '0';
    signal rb_meta_toggle_sync3   : std_logic := '0';
    signal rb_meta_ack_toggle_jtag : std_logic := '0';
    signal rb_meta_ack_sync1      : std_logic := '0';
    signal rb_meta_ack_sync2      : std_logic := '0';
    signal rb_meta_pending_sample : std_logic := '0';
    signal rb_done_sample         : std_logic := '0';
    -- {arm, reset} toggles the sample domain had processed when the snapshot
    -- was taken; see p_rb_meta_jtag.
    signal rb_gen_sample          : std_logic_vector(1 downto 0) := "00";
    signal rb_capture_len_jtag    : unsigned(PTR_W downto 0) := (others => '0');
    signal rb_start_ptr_jtag      : natural range 0 to DEPTH - 1 := 0;
    signal rb_seg_start_ptr_jtag  : seg_ptr_t := (others => 0);
    signal rb_seg_len_jtag        : seg_len_t := (others => (others => '0'));
    -- Entries the DATA window and CAPTURE_LEN cover: on segmented RLE builds
    -- the selected segment's, since a clock limit can end segments short
    -- (the capture length for every segment without a limit).
    signal rb_window_len_jtag     : unsigned(PTR_W downto 0) := (others => '0');
    signal rb_done_jtag           : std_logic := '0';
    signal rb_meta_sample_busy    : std_logic := '0';
    signal rb_meta_event_sample   : std_logic := '0';

    signal jtag_rd_data_window    : std_logic := '0';
    signal datawin_req_now        : std_logic := '0';
    signal datawin_is_ts_comb     : std_logic := '0';
    signal datawin_oob_comb       : std_logic := '0';
    signal datawin_mem_addr_comb  : std_logic_vector(PTR_W - 1 downto 0) := (others => '0');
    signal datawin_chunk_comb     : natural := 0;
    signal datawin_reply_q        : std_logic := '0';
    signal datawin_oob_q          : std_logic := '0';
    signal datawin_is_ts_q        : std_logic := '0';
    signal datawin_chunk_q        : natural := 0;
    signal jtag_data_offset       : std_logic_vector(31 downto 0) := (others => '0');
    -- Never reset; power-up value only (p_capture_gen).
    signal capture_gen            : unsigned(15 downto 0) := (others => '0');
    signal capture_gen_rst_d      : std_logic := '0';

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

    -- Assemble a SAMPLE_W value from its per-word registers (WIDE_TRIG).
    function wide_assemble(words : reg32_array_t) return std_logic_vector is
        variable full : std_logic_vector(WORDS_PER_SAMPLE * 32 - 1 downto 0) := (others => '0');
    begin
        for i in 0 to WORDS_PER_SAMPLE - 1 loop
            full(i * 32 + 31 downto i * 32) := words(i);
        end loop;
        return full(SAMPLE_W - 1 downto 0);
    end function;

    function ptr_u(n : natural) return unsigned is
    begin
        return to_unsigned(n, PTR_W);
    end function;

    function count_u(n : natural) return unsigned is
    begin
        return to_unsigned(n, PTR_W + 1);
    end function;

    function count_u(v : unsigned) return unsigned is
    begin
        return resize(v, PTR_W + 1);
    end function;

    -- One bit wider than a length, for the overflow comparison only.  Mirrors
    -- the Verilog core's config_capture_len, which is [LEN_W:0]: summing two
    -- lengths and a 1 can carry out of LEN_W, and wrapping there would clear
    -- the very overflow being tested for.
    function len_sum_u(n : natural) return unsigned is
    begin
        return to_unsigned(n, LEN_W + 1);
    end function;

    function len_sum_u(v : unsigned) return unsigned is
    begin
        return resize(v, LEN_W + 1);
    end function;

    function sample_chunk_word(sample : std_logic_vector(SAMPLE_W - 1 downto 0); chunk : natural) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable bit_base : natural;
    begin
        bit_base := chunk * 32;
        for i in 0 to 31 loop
            if bit_base + i < SAMPLE_W then
                r(i) := sample(bit_base + i);
            end if;
        end loop;
        return r;
    end function;

    function aux_chunk_word(aux : std_logic_vector(AUX_DATA_W - 1 downto 0); chunk : natural) return std_logic_vector is
        variable r : std_logic_vector(31 downto 0) := (others => '0');
        variable bit_base : natural;
    begin
        if AUX_W > 0 then
            bit_base := chunk * 32;
            for i in 0 to 31 loop
                if bit_base + i < AUX_W then
                    r(i) := aux(bit_base + i);
                end if;
            end loop;
        end if;
        return r;
    end function;

    function cfg_len(v : std_logic_vector(31 downto 0)) return unsigned is
    begin
        -- Match the Verilog core: capture lengths consume only the length
        -- field, while JTAG register readback preserves the full 32-bit write.
        -- This is LEN_W, not PTR_W: a length may equal DEPTH, and narrowing to
        -- PTR_W silently turned a written DEPTH into 0.
        return unsigned(v(LEN_W - 1 downto 0));
    end function;

    function next_ptr(ptr : natural; base : natural) return natural is
    begin
        if ptr < base or ptr >= base + SEG_DEPTH - 1 then
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
        off := trig - base;
        if NUM_SEGMENTS > 1 and wrapped = '0' and off < pre_len then
            return base;
        end if;
        return base + ((off + SEG_DEPTH - (pre_len mod SEG_DEPTH)) mod SEG_DEPTH);
    end function;

    function seq_next(cfg : std_logic_vector(31 downto 0)) return natural is
        variable nxt : natural;
    begin
        nxt := to_integer(unsigned(cfg(10 + SEQ_STATE_W - 1 downto 10)));
        if nxt >= TRIG_STAGES then
            return 0;
        end if;
        return nxt;
    end function;
begin
    assert is_power_of_two(DEPTH)
        report "fcapz_ela: DEPTH must be a power of 2"
        severity failure;
    assert (DEPTH mod NUM_SEGMENTS) = 0
        report "fcapz_ela: DEPTH must be divisible by NUM_SEGMENTS"
        severity failure;
    assert is_power_of_two(SEG_DEPTH)
        report "fcapz_ela: SEG_DEPTH must be a power of 2"
        severity failure;
    assert TRIG_STAGES >= 1 and TRIG_STAGES <= 4
        report "fcapz_ela: TRIG_STAGES must be 1-4"
        severity failure;
    assert SAMPLE_W <= 256
        report "fcapz_ela: SAMPLE_W must be <= 256"
        severity failure;
    assert DEFAULT_TRIG_EXT >= 0 and DEFAULT_TRIG_EXT <= 3
        report "fcapz_ela: DEFAULT_TRIG_EXT must be 0-3"
        severity failure;
    assert RLE_W <= 16
        report "fcapz_ela: RLE_W must be 0-16"
        severity failure;
    -- Counts share the timestamp lane of a core that has one, so they must
    -- fit it.
    assert TIMESTAMP_W = 0 or RLE_W <= TIMESTAMP_W
        report "fcapz_ela: RLE_W must not exceed TIMESTAMP_W"
        severity failure;

    trigger_out <= trigger_out_i when EXT_TRIG_EN /= 0 else '0';
    armed_out <= armed;
    -- Full-width comparator-A value/mask fed across the CDC.  With WIDE_TRIG the
    -- words come from the WIDE_SEL/WIDE_DATA window (word 0 mirrors TRIG_VALUE/
    -- MASK); otherwise only the low 32 bits are programmable and the upper bits
    -- are zero-extended, matching the legacy behaviour bit-for-bit.
    jtag_trig_value_w <= wide_assemble(wide_va) when HAS_WIDE_TRIG
                         else expand32(jtag_trig_value);
    jtag_trig_mask_w  <= wide_assemble(wide_ma) when HAS_WIDE_TRIG
                         else expand32(jtag_trig_mask);
    jtag_rdata <= jtag_rdata_i;
    burst_start_ptr <= burst_start_ptr_i;
    burst_rd_data <= sample_mem_dout_b;
    burst_rd_ts_data <= aux_rle_b when burst_rle = '1' else aux_ts_b;
    mem_we_a_ram <= mem_we_a_q when PROBE_PIPE > 0 else mem_we_a;
    sample_mem_din_ram <= mem_wr_data_q when PROBE_PIPE > 0 else sample_mem_din;
    ts_mem_din_ram <= mem_wr_ts_q when PROBE_PIPE > 0 else ts_mem_din;
    mem_addr_a <= mem_wr_addr_q when PROBE_PIPE > 0 and mem_we_a_q = '1' else mem_wr_addr;
    mem_addr_b <= burst_rd_addr when burst_rd_active = '1' else
                  datawin_mem_addr_comb when datawin_req_now = '1' and datawin_oob_comb = '0' else
                  (others => '0');
    jtag_rd_data_window <= '1' when USER1_DATA_EN /= 0 and
                           (to_integer(unsigned(jtag_addr)) >= ADDR_DATA_BASE or
                            (AUX_W > 0 and to_integer(unsigned(jtag_addr)) >= ADDR_TS_DATA_BASE)) else '0';
    datawin_req_now <= jtag_rd_en and jtag_rd_data_window;
    rb_meta_sample_busy <= rb_meta_toggle_sample xor rb_meta_ack_sync2;
    rb_meta_event_sample <= '1' when (done = '1' and rb_done_d = '0') or
                                     (NUM_SEGMENTS > 1 and seg_count /= rb_seg_count_d) else '0';
    mem_we_a <= '1' when (done = '0' and triggered = '0' and
                         (comb_store_ok = '1' or comb_trigger_commit_now = '1')) or
                         (armed = '1' and done = '0' and triggered = '1' and
                          comb_store_ok = '1' and post_left_zero = '0') else '0';

    -- Selection flush, as in rtl/fcapz_ela.v: chan_sel / probe_sel change only
    -- on arm, and the probe pipe, probe_prev and the registered hits still
    -- hold the old selection's samples for SEL_FLUSH_LEN sample clocks after
    -- it.  While sel_flush_active the capture neither stores nor evaluates the
    -- trigger.  Arms that keep the selection pay nothing.
    chan_sel_next <= chan_sel_stage when NUM_CHANNELS > 1 and chan_sel_stage < NUM_CHANNELS else 0;
    probe_sel_next <= probe_sel_stage
                      when PROBE_MUX_W > 0 and probe_sel_stage < (PROBE_MUX_W / SAMPLE_W) else 0;
    arm_sel_change <= '1' when (PROBE_MUX_W > 0 and probe_sel_next /= probe_sel) or
                               (PROBE_MUX_W = 0 and NUM_CHANNELS > 1 and chan_sel_next /= chan_sel)
                      else '0';
    sel_flush_start <= arm_sel_change and
                       (arm_sync_pulse or startup_arm_pending);
    -- Arming clears the registered storage-qualification hit, so with the
    -- registered compare and qualification on, the sample right after the
    -- arm is not stored and the rolling history gets a hole.
    -- SQ_MODE 0 turns qualification off; 1..9 select compare mode 0..8
    -- (EQ..CHANGED).  Other values turn it off too.
    sq_mode_on <= '1' when STOR_QUAL /= 0 and
                           unsigned(sq_mode_stage(3 downto 0)) /= 0 and
                           unsigned(sq_mode_stage(3 downto 0)) <= 9 else '0';
    arm_sq_bubble <= '1' when PROBE_PIPE > 0 and sq_mode_on = '1' else '0';
    -- Run-length capture is on only without decimation and qualification,
    -- so a count always means consecutive sample clocks.  Turning it on or
    -- off on an arm changes what the history entries mean.
    rle_active_next <= '1' when HAS_RLE and rle_en_stage = '1' and decim_stage = 0 and
                                sq_mode_on = '0' else '0';
    arm_rle_change <= '1' when HAS_RLE and rle_active_next /= rle_active else '0';
    -- Arms after which the rolling pre-arm history cannot be trusted.
    arm_voids_history <= arm_sel_change or arm_sq_bubble or arm_rle_change;
    -- An arm or soft reset restarts the capture on this edge.
    capture_restart <= arm_sync_pulse or startup_arm_pending or
                       reset_sync_pulse;

    p_sel_flush : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            sel_flush_active <= '0';
            sel_flush_count <= 0;
        elsif rising_edge(sample_clk) then
            if sel_flush_start = '1' then
                sel_flush_active <= '1';
                sel_flush_count <= SEL_FLUSH_LEN - 1;
            elsif sel_flush_active = '1' then
                if sel_flush_count = 0 then
                    sel_flush_active <= '0';
                else
                    sel_flush_count <= sel_flush_count - 1;
                end if;
            end if;
        end if;
    end process;

    u_samplebuf : entity work.fcapz_dpram
        generic map (
            WIDTH => SAMPLE_W,
            DEPTH => DEPTH
        )
        port map (
            clk_a  => sample_clk,
            we_a   => mem_we_a_ram,
            addr_a => mem_addr_a,
            din_a  => sample_mem_din_ram,
            dout_a => open,
            clk_b  => jtag_clk,
            addr_b => mem_addr_b,
            dout_b => sample_mem_dout_b
        );

    g_ts_mem : if TIMESTAMP_W > 0 generate
        u_tsbuf : entity work.fcapz_dpram
            generic map (
                WIDTH => TS_WIDTH,
                DEPTH => DEPTH
            )
            port map (
                clk_a  => sample_clk,
                we_a   => mem_we_a_ram,
                addr_a => mem_addr_a,
                din_a  => ts_mem_din_ram,
                dout_a => open,
                clk_b  => jtag_clk,
                addr_b => mem_addr_b,
                dout_b => ts_mem_dout_b
            );
    end generate;

    g_no_ts_mem : if TIMESTAMP_W = 0 generate
        ts_mem_dout_b <= (others => '0');
    end generate;

    -- Run-length capture: count RAM, as in rtl/fcapz_ela.v.  A store opens
    -- an entry with count 0.  A repeat of the newest entry's sample in a
    -- cycle that would have stored extends it instead: the count goes up
    -- and is rewritten at the entry's address.  The count write is
    -- registered so a new entry and the next cycle's extend of it reach the
    -- RAM in order whatever PROBE_PIPE is.
    rle_extend <= '1' when comb_rle_repeat = '1' and comb_store_base = '1' and
                           comb_trigger_commit_now = '0' and
                           ((done = '0' and triggered = '0') or
                            (armed = '1' and done = '0' and triggered = '1' and post_left_zero = '0'))
                  else '0';
    -- RLE clock limit: this clock is the last the post-trigger window covers.
    clk_stop_now <= '1' when HAS_RLE and post_clk_en = '1' and post_clk_last = '1' else '0';
    -- The post-trigger window (segment or capture) completes on this clock.
    post_done_now <= '1' when post_left_zero = '1' or (comb_store_ok = '1' and post_left_one = '1') or
                              clk_stop_now = '1' else '0';
    -- Entries in the window when it completes.  A clock stop ends it short:
    -- post_left entries are still missing, less this clock's if it opens one.
    capture_len_done <= capture_len when clk_stop_now = '0' else
                        capture_len - resize(post_left, PTR_W + 1) +
                        unsigned'(0 => comb_store_ok and not post_left_zero);
    -- This cycle completes the segment (or the capture); the next segment's
    -- first sample must open its own entry.
    rle_seg_end <= '1' when armed = '1' and done = '0' and capture_restart = '0' and triggered = '1' and
                            post_done_now = '1'
                   else '0';

    p_rle : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            rle_open <= '0';
            rle_value <= (others => '0');
            rle_count <= (others => '0');
            rle_addr <= 0;
            rle_we_q <= '0';
            rle_wr_addr_q <= (others => '0');
            rle_wr_count_q <= (others => '0');
        elsif rising_edge(sample_clk) then
            rle_we_q <= bool_to_sl(HAS_RLE) and (mem_we_a or rle_extend);
            if mem_we_a = '1' then
                rle_wr_addr_q <= mem_wr_addr;
                rle_wr_count_q <= (others => '0');
            else
                rle_wr_addr_q <= std_logic_vector(to_unsigned(rle_addr, PTR_W));
                rle_wr_count_q <= std_logic_vector(rle_count + 1);
            end if;
            if not HAS_RLE or capture_restart = '1' or sel_flush_active = '1' or rle_seg_end = '1' then
                rle_open <= '0';
            elsif mem_we_a = '1' then
                rle_open <= rle_active;
                rle_value <= sample_mem_din;
                rle_count <= (others => '0');
                rle_addr <= wr_ptr;
            elsif rle_extend = '1' then
                rle_count <= rle_count + 1;
            end if;
        end if;
    end process;

    g_rle_mem : if HAS_RLE generate
        u_rlebuf : entity work.fcapz_dpram
            generic map (
                WIDTH => RLE_DATA_W,
                DEPTH => DEPTH
            )
            port map (
                clk_a  => sample_clk,
                we_a   => rle_we_q,
                addr_a => rle_wr_addr_q,
                din_a  => rle_wr_count_q,
                dout_a => open,
                clk_b  => jtag_clk,
                addr_b => mem_addr_b,
                dout_b => rle_dout_b
            );
    end generate;

    g_no_rle_mem : if not HAS_RLE generate
        rle_dout_b <= (others => '0');
    end generate;

    -- Aux lane: timestamps, or run counts.
    g_aux_ts : if TIMESTAMP_W > 0 generate
        aux_ts_b <= ts_mem_dout_b;  -- AUX_W = TIMESTAMP_W
    end generate;
    g_aux_no_ts : if TIMESTAMP_W = 0 generate
        aux_ts_b <= (others => '0');
    end generate;
    aux_rle_b <= std_logic_vector(resize(unsigned(rle_dout_b), AUX_DATA_W));

    p_mem_write_cmd : process(all)
        variable active_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable compare_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable hit_internal : std_logic;
        variable hit_a : std_logic;
        variable hit_b : std_logic;
        variable seq_bank_a : std_logic_vector(TRIG_STAGES - 1 downto 0);
        variable seq_bank_b : std_logic_vector(TRIG_STAGES - 1 downto 0);
        variable seq_stage_hit : std_logic;
        variable hit_eff : std_logic;
        variable sq_ok : boolean;
        variable sq_eff : boolean;
        variable store_tick : boolean;
        variable store_ok : boolean;
        variable store_base : boolean;
        variable rle_sample : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable rle_repeat : boolean;
        variable trigger_commit_now : boolean;
        variable probe_idx : natural;
    begin
        active_probe := (others => '0');
        if PROBE_MUX_W > 0 then
            probe_idx := probe_sel * SAMPLE_W;
            active_probe := probe_in(probe_idx + SAMPLE_W - 1 downto probe_idx);
        elsif NUM_CHANNELS > 1 then
            probe_idx := chan_sel * SAMPLE_W;
            active_probe := probe_in(probe_idx + SAMPLE_W - 1 downto probe_idx);
        else
            active_probe := probe_in(SAMPLE_W - 1 downto 0);
        end if;

        if PROBE_PIPE > 0 then
            compare_probe := pipe_probe(PIPE_STAGES - 1);
        else
            compare_probe := active_probe;
        end if;

        if DECIM_EN = 0 then
            store_tick := true;
        else
            store_tick := decim_count = 0;
        end if;

        seq_bank_a := (others => '0');
        seq_bank_b := (others => '0');
        if TRIG_STAGES > 1 and PROBE_PIPE > 0 then
            -- Every stage's A/B compare on this sample; the decision selects
            -- the registered hits of the stage active when they are consumed
            -- (see rtl/fcapz_ela.v g_seq_cmp_bank).
            for s in 0 to TRIG_STAGES - 1 loop
                seq_bank_a(s) := cmp_hit(
                    compare_probe, probe_prev, seq_value_a(s), seq_mask_a(s), seq_mode_a(s)
                );
                if DUAL_COMPARE /= 0 then
                    seq_bank_b(s) := cmp_hit(
                        compare_probe, probe_prev, seq_value_b(s), seq_mask_b(s), seq_mode_b(s)
                    );
                end if;
            end loop;
            hit_a := '0';
            hit_b := '0';
        elsif TRIG_STAGES > 1 then
            hit_a := cmp_hit(
                compare_probe,
                probe_prev,
                seq_value_a(seq_state),
                seq_mask_a(seq_state),
                seq_mode_a(seq_state)
            );
            hit_b := '0';
            if DUAL_COMPARE /= 0 then
                hit_b := cmp_hit(
                    compare_probe,
                    probe_prev,
                    seq_value_b(seq_state),
                    seq_mask_b(seq_state),
                    seq_mode_b(seq_state)
                );
            end if;
        else
            hit_a := cmp_hit(compare_probe, probe_prev, trig_value, trig_mask, trig_cmp_mode_a);
            hit_b := '0';
            if DUAL_COMPARE /= 0 then
                hit_b := cmp_hit(compare_probe, probe_prev, trig_value_b, trig_mask_b, trig_cmp_mode_b);
            end if;
        end if;
        comb_hit_a <= hit_a;
        comb_hit_b <= hit_b;
        comb_seq_a <= seq_bank_a;
        comb_seq_b <= seq_bank_b;

        -- With PROBE_PIPE > 0 only the raw A/B compares are registered, as in
        -- rtl/fcapz_ela.v.  Stage combine, final and count qualification then
        -- use the current seq_state and seq_counter, so the trigger, the
        -- stage advance and the hit count all see the same registered hit.
        -- The sequencer selects the active stage's entry from the per-stage
        -- registered hits, all of which describe the same sample.
        if PROBE_PIPE > 0 and TRIG_STAGES > 1 then
            hit_a := seq_pipe_a(seq_state);
            hit_b := seq_pipe_b(seq_state);
        elsif PROBE_PIPE > 0 then
            hit_a := hit_a_pipe;
            hit_b := hit_b_pipe;
        end if;

        hit_internal := '0';
        seq_stage_hit := '0';
        if TRIG_STAGES > 1 then
            case seq_combine(seq_state) is
                when "01" => seq_stage_hit := hit_b;
                when "10" => seq_stage_hit := hit_a and hit_b;
                when "11" => seq_stage_hit := hit_a or hit_b;
                when others => seq_stage_hit := hit_a;
            end case;
            if seq_stage_hit = '1' and seq_is_final(seq_state) = '1' then
                if seq_count_reached(seq_counter, seq_count_target(seq_state)) then
                    hit_internal := '1';
                end if;
            end if;
        else
            if DUAL_COMPARE = 0 then
                hit_internal := hit_a;
            else
                case trig_combine is
                    when "01" => hit_internal := hit_b;
                    when "10" => hit_internal := hit_a and hit_b;
                    when "11" => hit_internal := hit_a or hit_b;
                    when others => hit_internal := hit_a;
                end case;
            end if;
        end if;

        case ext_trig_mode is
            when "01" => hit_eff := hit_internal or trigger_in_aligned;
            when "10" => hit_eff := hit_internal and trigger_in_aligned;
            when others => hit_eff := hit_internal;
        end case;

        sq_ok := true;
        if STOR_QUAL /= 0 and sq_enable = '1' then
            sq_ok := cmp_hit(
                compare_probe,
                probe_prev,
                sq_value,
                sq_mask,
                sq_cmp_mode
            ) = '1';
        end if;

        if PROBE_PIPE > 0 then
            sq_eff := (STOR_QUAL = 0) or (sq_enable = '0') or (sq_pipe = '1');
        else
            sq_eff := sq_ok;
        end if;
        store_base := store_tick and sq_eff and sel_flush_active = '0';
        -- Run-length capture: the sample the RAM would store, and whether it
        -- only extends the newest entry instead of opening a new one.
        if PROBE_PIPE > 0 then
            rle_sample := probe_prev;
        else
            rle_sample := active_probe;
        end if;
        rle_repeat := rle_active = '1' and rle_open = '1' and rle_sample = rle_value and
                      rle_count /= RLE_COUNT_MAX;
        store_ok := store_base and not rle_repeat;
        -- An arm or soft reset on this edge takes priority (see p_capture).
        trigger_commit_now := armed = '1' and done = '0' and triggered = '0' and
                              arm_sync_pulse = '0' and
                              startup_arm_pending = '0' and
                              reset_sync_pulse = '0' and
                              pre_count >= count_u(pretrig_len) and
                              trig_holdoff_active = '0' and sel_flush_active = '0' and
                              ((trig_delay_pending = '1' and trig_delay_count = 0) or
                               (trig_delay_pending = '0' and hit_eff = '1' and trig_delay = 0));
        comb_hit_eff <= hit_eff;
        comb_sq_ok <= bool_to_sl(sq_ok);
        comb_store_ok <= bool_to_sl(store_ok);
        comb_store_base <= bool_to_sl(store_base);
        comb_rle_repeat <= bool_to_sl(rle_repeat);
        comb_trigger_commit_now <= bool_to_sl(trigger_commit_now);
        comb_seq_stage_hit <= seq_stage_hit;

        mem_wr_addr <= std_logic_vector(to_unsigned(wr_ptr, PTR_W));
        -- The registered compare and storage-qualification hits describe
        -- the previous sample, so that is the one stored.
        if PROBE_PIPE > 0 then
            sample_mem_din <= probe_prev;
        else
            sample_mem_din <= active_probe;
        end if;
        ts_mem_din <= std_logic_vector(timestamp_counter);
    end process;

    g_ext_trig_align : if EXT_TRIG_EN /= 0 and EXT_ALIGN > 0 generate
        signal trigger_in_dly : std_logic_vector(EXT_ALIGN - 1 downto 0) := (others => '0');
    begin
        p_ext_trig_align : process(sample_clk, sample_rst)
        begin
            if sample_rst = '1' then
                trigger_in_dly <= (others => '0');
            elsif rising_edge(sample_clk) then
                trigger_in_dly(0) <= trigger_in_sync2;
                for i in 1 to EXT_ALIGN - 1 loop
                    trigger_in_dly(i) <= trigger_in_dly(i - 1);
                end loop;
            end if;
        end process;
        trigger_in_aligned <= trigger_in_dly(EXT_ALIGN - 1);
    end generate;

    g_no_ext_trig_align : if EXT_TRIG_EN = 0 or EXT_ALIGN = 0 generate
        trigger_in_aligned <= trigger_in_sync2;
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
                mem_wr_addr_q <= mem_wr_addr;
                mem_wr_data_q <= sample_mem_din;
                mem_wr_ts_q <= ts_mem_din;
            end if;
        end if;
    end process;

    arm_sync_pulse <= arm_toggle_sync3 xor arm_toggle_sync4;
    reset_sync_pulse <= reset_toggle_sync3 xor reset_toggle_sync4;
    cfg_stage_en <= (arm_toggle_sync2 xor arm_toggle_sync3) or
                    (reset_toggle_sync2 xor reset_toggle_sync3);

    p_toggle_sync : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            arm_toggle_sync1 <= '0';
            arm_toggle_sync2 <= '0';
            arm_toggle_sync3 <= '0';
            arm_toggle_sync4 <= '0';
            reset_toggle_sync1 <= '0';
            reset_toggle_sync2 <= '0';
            reset_toggle_sync3 <= '0';
            reset_toggle_sync4 <= '0';
            startup_arm_pending <= bool_to_sl(STARTUP_ARM /= 0);
        elsif rising_edge(sample_clk) then
            arm_toggle_sync1 <= arm_toggle_jtag;
            arm_toggle_sync2 <= arm_toggle_sync1;
            arm_toggle_sync3 <= arm_toggle_sync2;
            arm_toggle_sync4 <= arm_toggle_sync3;
            reset_toggle_sync1 <= reset_toggle_jtag;
            reset_toggle_sync2 <= reset_toggle_sync1;
            reset_toggle_sync3 <= reset_toggle_sync2;
            reset_toggle_sync4 <= reset_toggle_sync3;
            if reset_sync_pulse = '1' then
                startup_arm_pending <= startup_arm_stage;
            elsif startup_arm_pending = '1' then
                startup_arm_pending <= '0';
            end if;
        end if;
    end process;

    p_config_latch : process(sample_clk, sample_rst)
        variable arm_now : boolean;
    begin
        if sample_rst = '1' then
            pretrig_len <= (others => '0');
            posttrig_len <= (others => '0');
            cap_trig_mode <= x"00000001";
            cap_trig_value <= (others => '0');
            cap_trig_mask <= x"FFFFFFFF";
            trig_delay <= (others => '0');
            trig_cmp_mode_a <= (others => '0');
            trig_cmp_mode_b <= (others => '0');
            trig_combine <= (others => '0');
            trig_value <= (others => '0');
            trig_mask <= (others => '1');
            trig_value_b <= (others => '0');
            trig_mask_b <= (others => '1');
            rle_active <= '0';
            rle_post_clks <= (others => '0');
            post_clk_en <= '0';
            post_clk_one <= '0';
            chan_sel <= 0;
            probe_sel <= 0;
            decim_ratio <= (others => '0');
            ext_trig_mode <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            sq_enable <= '0';
            sq_cmp_mode <= (others => '0');
            sq_value <= (others => '0');
            sq_mask <= (others => '0');
            seq_mode_a <= (others => (others => '0'));
            seq_mode_b <= (others => (others => '0'));
            seq_combine <= (others => (others => '0'));
            seq_value_a <= (others => (others => '0'));
            seq_mask_a <= (others => (others => '1'));
            seq_value_b <= (others => (others => '0'));
            seq_mask_b <= (others => (others => '1'));
            seq_count_target <= (others => (others => '0'));
            seq_next_state <= (others => (others => '0'));
            seq_is_final <= (others => '0');
        elsif rising_edge(sample_clk) then
            arm_now := (arm_sync_pulse = '1') or startup_arm_pending = '1';
            if arm_now then
                pretrig_len <= pretrig_len_stage;
                posttrig_len <= posttrig_len_stage;
                cap_trig_mode <= trig_mode_stage;
                cap_trig_value <= low_u32(trig_value_stage);
                cap_trig_mask <= low_u32(trig_mask_stage);
                trig_delay <= trig_delay_stage;
                -- trig_value/mask are already SAMPLE_W-wide (WIDE_TRIG); the
                -- sync words carry the full comparator-A value/mask directly.
                trig_value <= trig_value_stage;
                trig_mask <= trig_mask_stage;
                if TRIG_STAGES > 1 and seq_cfg_stage(0)(9 downto 0) /= "0000000000" then
                    trig_cmp_mode_a <= seq_cfg_stage(0)(3 downto 0);
                    if DUAL_COMPARE /= 0 then
                        trig_cmp_mode_b <= seq_cfg_stage(0)(7 downto 4);
                        trig_combine <= seq_cfg_stage(0)(9 downto 8);
                    else
                        trig_cmp_mode_b <= (others => '0');
                        trig_combine <= (others => '0');
                    end if;
                else
                    if trig_mode_stage(1) = '1' then
                        trig_cmp_mode_a <= x"8";
                    else
                        trig_cmp_mode_a <= x"0";
                    end if;
                    if DUAL_COMPARE /= 0 and trig_mode_stage(1 downto 0) = "11" then
                        trig_cmp_mode_b <= x"8";
                        trig_combine <= "11";
                    else
                        trig_cmp_mode_b <= (others => '0');
                        trig_combine <= (others => '0');
                    end if;
                end if;
                if TRIG_STAGES > 1 and DUAL_COMPARE /= 0 then
                    trig_value_b <= seq_value_b_stage(0);
                    trig_mask_b <= seq_mask_b_stage(0);
                else
                    trig_value_b <= (others => '0');
                    trig_mask_b <= (others => '1');
                end if;
                rle_active <= rle_active_next;
                rle_post_clks <= rle_post_clks_stage;
                post_clk_en <= rle_active_next and bool_to_sl(rle_post_clks_stage /= 0);
                post_clk_one <= bool_to_sl(rle_post_clks_stage = 1);
                chan_sel <= chan_sel_next;
                probe_sel <= probe_sel_next;
                -- From the synchronisers, like every other field latched
                -- here: jtag_decim / jtag_trig_ext belong to the JTAG clock
                -- domain.  Mirrors rtl/fcapz_ela.v.
                if DECIM_EN /= 0 then
                    decim_ratio <= decim_stage;
                else
                    decim_ratio <= (others => '0');
                end if;
                if EXT_TRIG_EN /= 0 then
                    ext_trig_mode <= trig_ext_stage;
                else
                    ext_trig_mode <= (others => '0');
                end if;
                if STOR_QUAL /= 0 then
                    sq_enable <= sq_mode_on;
                    if sq_mode_on = '1' then
                        sq_cmp_mode <= std_logic_vector(unsigned(sq_mode_stage(3 downto 0)) - 1);
                    else
                        sq_cmp_mode <= (others => '0');
                    end if;
                    sq_value <= expand32(sq_value_stage);
                    sq_mask <= expand32(sq_mask_stage);
                else
                    sq_enable <= '0';
                    sq_cmp_mode <= (others => '0');
                    sq_value <= (others => '0');
                    sq_mask <= (others => '0');
                end if;
                for i in 0 to TRIG_STAGES - 1 loop
                    if TRIG_STAGES > 1 then
                        seq_mode_a(i) <= seq_cfg_stage(i)(3 downto 0);
                        seq_next_state(i) <= seq_cfg_stage(i)(10 + SEQ_STATE_W - 1 downto 10);
                        seq_is_final(i) <= seq_cfg_stage(i)(12);
                        seq_count_target(i) <= unsigned(seq_cfg_stage(i)(31 downto 16));
                        seq_value_a(i) <= seq_value_a_stage(i);
                        seq_mask_a(i) <= seq_mask_a_stage(i);
                    else
                        seq_mode_a(i) <= (others => '0');
                        seq_next_state(i) <= (others => '0');
                        seq_is_final(i) <= '0';
                        seq_count_target(i) <= (others => '0');
                        seq_value_a(i) <= (others => '0');
                        seq_mask_a(i) <= (others => '1');
                    end if;
                    if TRIG_STAGES > 1 and DUAL_COMPARE /= 0 then
                        seq_mode_b(i) <= seq_cfg_stage(i)(7 downto 4);
                        seq_combine(i) <= seq_cfg_stage(i)(9 downto 8);
                        seq_value_b(i) <= seq_value_b_stage(i);
                        seq_mask_b(i) <= seq_mask_b_stage(i);
                    else
                        seq_mode_b(i) <= (others => '0');
                        seq_combine(i) <= (others => '0');
                        seq_value_b(i) <= (others => '0');
                        seq_mask_b(i) <= (others => '1');
                    end if;
                end loop;
            end if;
        end if;
    end process;

    -- Capture generation: counts every CTRL write that arms or resets the
    -- core and every release of the register-side reset: each one can start
    -- a capture that overwrites the buffer.  A host reads it before and after
    -- a readout, and after its own arm, to tell that the samples it read are
    -- the capture it armed.  STARTUP_ARM arms and segment re-arms are not
    -- counted: the first follows a counted reset, and the second fill the
    -- segments of one capture.  A release and a write in the same cycle
    -- count two.
    p_capture_gen : process(jtag_clk)
        variable next_gen : unsigned(15 downto 0);
    begin
        if rising_edge(jtag_clk) then
            capture_gen_rst_d <= jtag_rst;
            next_gen := capture_gen;
            if capture_gen_rst_d = '1' and jtag_rst = '0' then
                next_gen := next_gen + 1;
            end if;
            if jtag_wr_en = '1' and jtag_rst = '0'
                    and to_integer(unsigned(jtag_addr)) = ADDR_CTRL
                    and (jtag_wdata(0) = '1' or jtag_wdata(1) = '1') then
                next_gen := next_gen + 1;
            end if;
            capture_gen <= next_gen;
        end if;
    end process;

    p_jtag_regs : process(jtag_clk, jtag_rst)
        variable addr : natural;
        variable seq_stage : natural;
        variable seq_off : natural;
        variable wide_word : natural;
    begin
        if jtag_rst = '1' then
            jtag_ctrl <= (others => '0');
            jtag_pretrig_len <= (others => '0');
            jtag_posttrig_len <= (others => '0');
            jtag_trig_mode <= x"00000001";
            jtag_trig_value <= (others => '0');
            jtag_trig_mask <= x"FFFFFFFF";
            -- Wide comparator-A words (WIDE_TRIG): value words 0, mask word 0
            -- all-ones (match nothing masked out), higher mask words 0.
            jtag_wide_sel <= (others => '0');
            jtag_data_offset <= (others => '0');
            for s in 0 to WORDS_PER_SAMPLE - 1 loop
                wide_va(s) <= (others => '0');
                if s = 0 then
                    wide_ma(s) <= x"FFFFFFFF";
                else
                    wide_ma(s) <= (others => '0');
                end if;
            end loop;
            jtag_sq_mode <= (others => '0');
            jtag_sq_value <= (others => '0');
            jtag_sq_mask <= (others => '0');
            jtag_seq_value_a <= (others => (others => '0'));
            jtag_seq_value_b <= (others => (others => '0'));
            for i in 0 to TRIG_STAGES - 1 loop
                if i = 0 then
                    jtag_seq_cfg(i) <= x"00001000";
                else
                    jtag_seq_cfg(i) <= (others => '0');
                end if;
                jtag_seq_mask_a(i) <= x"FFFFFFFF";
                jtag_seq_mask_b(i) <= x"FFFFFFFF";
            end loop;
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
            burst_start <= '0';
            burst_timestamp <= '0';
            burst_rle <= '0';
            jtag_rle_ctrl <= "00";
            jtag_rle_post_clks <= (others => '0');
            burst_start_ptr_i <= (others => '0');
        elsif rising_edge(jtag_clk) then
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
                        -- Every host arms or resets before a capture, so a
                        -- DATA_OFFSET left by a session that died while
                        -- paging cannot shift the next one's reads.
                        -- Arm and reset also return the DATA window to
                        -- timestamps.
                        if jtag_wdata(0) = '1' or jtag_wdata(1) = '1' then
                            jtag_data_offset <= (others => '0');
                            jtag_rle_ctrl(1) <= '0';
                        end if;
                    when ADDR_PRETRIG =>
                        jtag_pretrig_len <= jtag_wdata;
                    when ADDR_POSTTRIG =>
                        jtag_posttrig_len <= jtag_wdata;
                    when ADDR_TRIG_MODE =>
                        jtag_trig_mode <= jtag_wdata;
                    when ADDR_TRIG_VALUE =>
                        jtag_trig_value <= jtag_wdata;
                        if HAS_WIDE_TRIG then
                            wide_va(0) <= jtag_wdata;  -- mirror word 0
                        end if;
                    when ADDR_TRIG_MASK =>
                        jtag_trig_mask <= jtag_wdata;
                        if HAS_WIDE_TRIG then
                            wide_ma(0) <= jtag_wdata;
                        end if;
                    when ADDR_WIDE_SEL =>
                        if HAS_WIDE_TRIG then
                            jtag_wide_sel <= jtag_wdata(7 downto 0);
                        end if;
                    when ADDR_WIDE_DATA =>
                        -- [0]=mask/value, [7:4]=word index into the wide slots.
                        wide_word := to_integer(unsigned(jtag_wide_sel(7 downto 4)));
                        if HAS_WIDE_TRIG and wide_word < WORDS_PER_SAMPLE then
                            if jtag_wide_sel(0) = '1' then
                                wide_ma(wide_word) <= jtag_wdata;
                            else
                                wide_va(wide_word) <= jtag_wdata;
                            end if;
                        end if;
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
                    when ADDR_RLE_CTRL =>
                        if HAS_RLE then
                            jtag_rle_ctrl <= jtag_wdata(1 downto 0);
                        end if;
                    when ADDR_RLE_POST_CLKS =>
                        if HAS_RLE then
                            jtag_rle_post_clks <= jtag_wdata(POST_CLK_W - 1 downto 0);
                        end if;
                    when ADDR_STARTUP_ARM =>
                        jtag_startup_arm <= jtag_wdata(0);
                    when ADDR_DATA_OFFSET =>
                        if USER1_DATA_EN /= 0 then
                            jtag_data_offset <= jtag_wdata;
                        end if;
                    when ADDR_TRIG_DELAY =>
                        jtag_trig_delay <= jtag_wdata(15 downto 0);
                    when ADDR_TRIG_HOLDOFF =>
                        jtag_trig_holdoff <= jtag_wdata(15 downto 0);
                    when ADDR_BURST_PTR =>
                        burst_start <= not burst_start;
                        burst_timestamp <= jtag_wdata(31);
                        burst_rle <= bool_to_sl(HAS_RLE) and jtag_wdata(31) and jtag_wdata(30);
                        if NUM_SEGMENTS > 1 then
                            burst_start_ptr_i <= std_logic_vector(to_unsigned(rb_seg_start_ptr_jtag(jtag_seg_sel), PTR_W));
                        else
                            burst_start_ptr_i <= std_logic_vector(to_unsigned(rb_start_ptr_jtag, PTR_W));
                        end if;
                    when others =>
                        if TRIG_STAGES > 1 and addr >= ADDR_SEQ_BASE and addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE then
                            seq_stage := (addr - ADDR_SEQ_BASE) / SEQ_STRIDE;
                            seq_off := (addr - ADDR_SEQ_BASE) mod SEQ_STRIDE;
                            case seq_off is
                                when 0 =>
                                    if DUAL_COMPARE /= 0 then
                                        jtag_seq_cfg(seq_stage) <= jtag_wdata;
                                    else
                                        jtag_seq_cfg(seq_stage) <= jtag_wdata and x"FFFFFC0F";
                                    end if;
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
        end if;
    end process;

    p_datawin_decode : process(all)
        variable addr : natural;
        variable offset_v : natural;
        variable word_index : natural;
        variable sample_index : natural;
        variable start_ptr_v : natural;
        variable seg_base_v : natural;
        variable mem_addr_v : natural;
    begin
        -- The window address DATA_OFFSET moves a read to.  An offset past the
        -- windows moves it to the word just past them, which reads 0.
        addr := to_integer(unsigned(jtag_addr));
        if addr >= ADDR_DATA_BASE then
            if unsigned(jtag_data_offset) >= DATA_WINDOW_WORDS then
                offset_v := DATA_WINDOW_WORDS;
            else
                offset_v := to_integer(unsigned(jtag_data_offset(DATA_OFFSET_W - 1 downto 0)));
            end if;
            addr := ADDR_DATA_BASE + ((addr - ADDR_DATA_BASE) / 4 + offset_v) * 4;
        end if;
        word_index := 0;
        sample_index := 0;
        start_ptr_v := rb_start_ptr_jtag;
        if NUM_SEGMENTS > 1 then
            start_ptr_v := rb_seg_start_ptr_jtag(jtag_seg_sel);
        end if;
        if NUM_SEGMENTS > 1 then
            seg_base_v := (start_ptr_v / SEG_DEPTH) * SEG_DEPTH;
        else
            seg_base_v := 0;
        end if;

        datawin_is_ts_comb <= '0';
        datawin_oob_comb <= '0';
        datawin_mem_addr_comb <= (others => '0');
        datawin_chunk_comb <= 0;
        -- Default the index OUT of range.  An address below ADDR_DATA_BASE
        -- matches neither branch below, and the entry default of 0 is in range,
        -- so such a read used to be treated as sample 0 of the window.  The
        -- Verilog core's if/else is unconditional and its 32-bit subtract
        -- underflows to a far out-of-range index, giving oob = 1 and
        -- mem_addr = 0; this makes the VHDL agree.  Note the chunk index still
        -- differs from the Verilog's underflowed value when
        -- WORDS_PER_SAMPLE > 1; it is unused on an under-base read.
        sample_index := integer'high;

        if AUX_W > 0 and addr >= ADDR_TS_DATA_BASE then
            datawin_is_ts_comb <= '1';
            word_index := (addr - ADDR_TS_DATA_BASE) / 4;
            sample_index := word_index / AUX_WORDS;
            datawin_chunk_comb <= word_index mod AUX_WORDS;
        elsif addr >= ADDR_DATA_BASE then
            word_index := (addr - ADDR_DATA_BASE) / 4;
            sample_index := word_index / WORDS_PER_SAMPLE;
            datawin_chunk_comb <= word_index mod WORDS_PER_SAMPLE;
        end if;

        if sample_index >= to_integer(rb_window_len_jtag) then
            datawin_oob_comb <= '1';
        else
            mem_addr_v := seg_base_v + ((start_ptr_v - seg_base_v + sample_index) mod SEG_DEPTH);
            datawin_mem_addr_comb <= std_logic_vector(to_unsigned(mem_addr_v, PTR_W));
        end if;
    end process;

    p_rb_meta_sample : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            rb_done_d <= '0';
            rb_seg_count_d <= 0;
            rb_meta_toggle_sample <= '0';
            rb_meta_ack_sync1 <= '0';
            rb_meta_ack_sync2 <= '0';
            rb_meta_pending_sample <= '0';
            rb_done_sample <= '0';
            rb_gen_sample <= "00";
            rb_capture_len_sample <= (others => '0');
            rb_start_ptr_sample <= 0;
            rb_seg_start_ptr_sample <= (others => 0);
            rb_seg_len_sample <= (others => (others => '0'));
        elsif rising_edge(sample_clk) then
            rb_done_d <= done;
            rb_seg_count_d <= seg_count;
            rb_meta_ack_sync1 <= rb_meta_ack_toggle_jtag;
            rb_meta_ack_sync2 <= rb_meta_ack_sync1;

            if rb_meta_event_sample = '1' then
                rb_meta_pending_sample <= '1';
            end if;

            if rb_meta_sample_busy = '0' and (rb_meta_pending_sample = '1' or rb_meta_event_sample = '1') then
                rb_done_sample <= done;
                rb_gen_sample <= arm_toggle_sync4 & reset_toggle_sync4;
                rb_capture_len_sample <= capture_len;
                rb_start_ptr_sample <= start_ptr;
                rb_seg_start_ptr_sample <= seg_start_ptr;
                -- Without a clock limit every segment reads the capture
                -- length, as on a core without seg_len.
                if HAS_RLE_SEG_LEN and post_clk_en = '1' then
                    rb_seg_len_sample <= seg_len;
                elsif HAS_RLE_SEG_LEN then
                    rb_seg_len_sample <= (others => capture_len);
                else
                    rb_seg_len_sample <= (others => (others => '0'));
                end if;
                rb_meta_toggle_sample <= not rb_meta_toggle_sample;
                rb_meta_pending_sample <= '0';
            end if;
        end if;
    end process;

    rb_window_len_jtag <= rb_seg_len_jtag(jtag_seg_sel) when HAS_RLE_SEG_LEN else rb_capture_len_jtag;

    p_rb_meta_jtag : process(jtag_clk, jtag_rst)
    begin
        if jtag_rst = '1' then
            rb_meta_toggle_sync1 <= '0';
            rb_meta_toggle_sync2 <= '0';
            rb_meta_toggle_sync3 <= '0';
            rb_meta_ack_toggle_jtag <= '0';
            rb_capture_len_jtag <= (others => '0');
            rb_start_ptr_jtag <= 0;
            rb_seg_start_ptr_jtag <= (others => 0);
            rb_seg_len_jtag <= (others => (others => '0'));
            rb_done_jtag <= '0';
        elsif rising_edge(jtag_clk) then
            rb_meta_toggle_sync1 <= rb_meta_toggle_sample;
            rb_meta_toggle_sync2 <= rb_meta_toggle_sync1;
            rb_meta_toggle_sync3 <= rb_meta_toggle_sync2;

            -- Every snapshot is copied and acknowledged; a dropped ack would
            -- leave the sample side busy and stop all later snapshots.
            if (rb_meta_toggle_sync2 xor rb_meta_toggle_sync3) = '1' then
                rb_capture_len_jtag <= rb_capture_len_sample;
                rb_start_ptr_jtag <= rb_start_ptr_sample;
                rb_seg_start_ptr_jtag <= rb_seg_start_ptr_sample;
                rb_seg_len_jtag <= rb_seg_len_sample;
                rb_meta_ack_toggle_jtag <= rb_meta_toggle_sync2;
                -- Done counts only for the latest ARM / reset (see
                -- rtl/fcapz_ela.v).
                if rb_gen_sample = (arm_toggle_jtag & reset_toggle_jtag) then
                    rb_done_jtag <= rb_done_sample;
                else
                    rb_done_jtag <= '0';
                end if;
            end if;
            if jtag_wr_en = '1' and to_integer(unsigned(jtag_addr)) = ADDR_CTRL and
               (jtag_wdata(0) = '1' or jtag_wdata(1) = '1') then
                rb_done_jtag <= '0';
            end if;
        end if;
    end process;

    -- A CTRL write that arms or soft-resets snapshots the settings into
    -- *_hold (jtag_clk); the toggle reaching sync2 copies them into *_stage
    -- (sample_clk) one clock before the arm / reset pulse, as in
    -- rtl/fcapz_ela.v.
    p_config_hold : process(jtag_clk, jtag_rst)
    begin
        if jtag_rst = '1' then
            pretrig_len_hold <= (others => '0');
            posttrig_len_hold <= (others => '0');
            trig_mode_hold <= (others => '0');
            trig_value_hold <= (others => '0');
            trig_mask_hold <= (others => '0');
            decim_hold <= (others => '0');
            trig_ext_hold <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            probe_sel_hold <= 0;
            chan_sel_hold <= 0;
            startup_arm_hold <= bool_to_sl(STARTUP_ARM /= 0);
            trig_delay_hold <= (others => '0');
            trig_holdoff_hold <= (others => '0');
            rle_en_hold <= '0';
            rle_post_clks_hold <= (others => '0');
            sq_mode_hold <= (others => '0');
            sq_value_hold <= (others => '0');
            sq_mask_hold <= (others => '0');
            seq_cfg_hold <= (others => (others => '0'));
            seq_value_a_hold <= (others => (others => '0'));
            seq_mask_a_hold <= (others => (others => '0'));
            seq_value_b_hold <= (others => (others => '0'));
            seq_mask_b_hold <= (others => (others => '0'));
        elsif rising_edge(jtag_clk) then
            if jtag_wr_en = '1' and to_integer(unsigned(jtag_addr)) = ADDR_CTRL and
               (jtag_wdata(0) = '1' or jtag_wdata(1) = '1') then
                pretrig_len_hold <= cfg_len(jtag_pretrig_len);
                posttrig_len_hold <= cfg_len(jtag_posttrig_len);
                trig_mode_hold <= jtag_trig_mode;
                trig_value_hold <= jtag_trig_value_w;
                trig_mask_hold <= jtag_trig_mask_w;
                decim_hold <= unsigned(jtag_decim);
                trig_ext_hold <= jtag_trig_ext;
                probe_sel_hold <= jtag_probe_sel;
                chan_sel_hold <= jtag_chan_sel;
                startup_arm_hold <= jtag_startup_arm;
                trig_delay_hold <= unsigned(jtag_trig_delay);
                trig_holdoff_hold <= unsigned(jtag_trig_holdoff);
                rle_en_hold <= bool_to_sl(HAS_RLE) and jtag_rle_ctrl(0);
                if HAS_RLE then
                    rle_post_clks_hold <= unsigned(jtag_rle_post_clks);
                else
                    rle_post_clks_hold <= (others => '0');
                end if;
                sq_mode_hold <= jtag_sq_mode;
                sq_value_hold <= jtag_sq_value;
                sq_mask_hold <= jtag_sq_mask;
                seq_cfg_hold <= jtag_seq_cfg;
                for i in 0 to TRIG_STAGES - 1 loop
                    if TRIG_STAGES > 1 then
                        seq_value_a_hold(i) <= expand32(jtag_seq_value_a(i));
                        seq_mask_a_hold(i) <= expand32(jtag_seq_mask_a(i));
                    else
                        seq_value_a_hold(i) <= (others => '0');
                        seq_mask_a_hold(i) <= (others => '1');
                    end if;
                    if TRIG_STAGES > 1 and DUAL_COMPARE /= 0 then
                        seq_value_b_hold(i) <= expand32(jtag_seq_value_b(i));
                        seq_mask_b_hold(i) <= expand32(jtag_seq_mask_b(i));
                    else
                        seq_value_b_hold(i) <= (others => '0');
                        seq_mask_b_hold(i) <= (others => '1');
                    end if;
                end loop;
            end if;
        end if;
    end process;

    p_config_stage : process(sample_clk, sample_rst)
    begin
        if sample_rst = '1' then
            pretrig_len_stage <= (others => '0');
            posttrig_len_stage <= (others => '0');
            trig_mode_stage <= (others => '0');
            trig_value_stage <= (others => '0');
            trig_mask_stage <= (others => '0');
            decim_stage <= (others => '0');
            trig_ext_stage <= std_logic_vector(to_unsigned(DEFAULT_TRIG_EXT mod 4, 2));
            probe_sel_stage <= 0;
            chan_sel_stage <= 0;
            startup_arm_stage <= bool_to_sl(STARTUP_ARM /= 0);
            trig_delay_stage <= (others => '0');
            trig_holdoff_stage <= (others => '0');
            rle_en_stage <= '0';
            rle_post_clks_stage <= (others => '0');
            sq_mode_stage <= (others => '0');
            sq_value_stage <= (others => '0');
            sq_mask_stage <= (others => '0');
            seq_cfg_stage <= (others => (others => '0'));
            seq_value_a_stage <= (others => (others => '0'));
            seq_mask_a_stage <= (others => (others => '0'));
            seq_value_b_stage <= (others => (others => '0'));
            seq_mask_b_stage <= (others => (others => '0'));
        elsif rising_edge(sample_clk) then
            if cfg_stage_en = '1' then
                pretrig_len_stage <= pretrig_len_hold;
                posttrig_len_stage <= posttrig_len_hold;
                trig_mode_stage <= trig_mode_hold;
                trig_value_stage <= trig_value_hold;
                trig_mask_stage <= trig_mask_hold;
                decim_stage <= decim_hold;
                trig_ext_stage <= trig_ext_hold;
                probe_sel_stage <= probe_sel_hold;
                chan_sel_stage <= chan_sel_hold;
                startup_arm_stage <= startup_arm_hold;
                trig_delay_stage <= trig_delay_hold;
                trig_holdoff_stage <= trig_holdoff_hold;
                rle_en_stage <= rle_en_hold;
                rle_post_clks_stage <= rle_post_clks_hold;
                sq_mode_stage <= sq_mode_hold;
                sq_value_stage <= sq_value_hold;
                sq_mask_stage <= sq_mask_hold;
                seq_cfg_stage <= seq_cfg_hold;
                seq_value_a_stage <= seq_value_a_hold;
                seq_mask_a_stage <= seq_mask_a_hold;
                seq_value_b_stage <= seq_value_b_hold;
                seq_mask_b_stage <= seq_mask_b_hold;
            end if;
        end if;
    end process;

    p_capture : process(sample_clk, sample_rst)
        variable active_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable compare_probe : std_logic_vector(SAMPLE_W - 1 downto 0);
        variable hit_eff : std_logic;
        variable sq_eff : boolean;
        variable store_ok : boolean;
        variable base : natural;
        variable start_calc : natural;
        variable next_segment : natural;
        variable trigger_commit_now : boolean;
        variable force_store_now : boolean;
        variable store_now : boolean;
        variable seg_start_next : seg_ptr_t;
        variable reset_pulse_now : boolean;
        variable arm_pulse_now : boolean;
        variable any_arm_pulse_now : boolean;
        variable probe_idx : natural;
    begin
        if sample_rst = '1' then
            armed <= '0';
            triggered <= '0';
            done <= '0';
            overflow <= '0';
            trigger_out_i <= '0';
            wr_ptr <= 0;
            start_ptr <= 0;
            trig_ptr <= 0;
            pre_count <= (others => '0');
            post_left <= (others => '0');
            post_left_zero <= '1';
            post_left_one <= '0';
            capture_len <= (others => '0');
            post_clk_left <= (others => '0');
            post_clk_last <= '0';
            seg_len <= (others => (others => '0'));
            probe_prev <= (others => '0');
            decim_count <= (others => '0');
            timestamp_counter <= (others => '0');
            cur_segment <= 0;
            seg_count <= 0;
            all_seg_done <= '0';
            seg_start_ptr <= (others => 0);
            segment_wrapped <= '0';
            seq_state <= 0;
            seq_counter <= (others => '0');
            trig_delay_pending <= '0';
            trig_delay_count <= (others => '0');
            trig_holdoff <= (others => '0');
            trig_holdoff_count <= (others => '0');
            trig_holdoff_active <= '0';
            trigger_in_sync1 <= '0';
            trigger_in_sync2 <= '0';
            pipe_probe <= (others => (others => '0'));
            hit_a_pipe <= '0';
            hit_b_pipe <= '0';
            seq_pipe_a <= (others => '0');
            seq_pipe_b <= (others => '0');
            sq_pipe <= '0';
        elsif rising_edge(sample_clk) then
            if EXT_TRIG_EN /= 0 then
                trigger_in_sync1 <= trigger_in;
                trigger_in_sync2 <= trigger_in_sync1;
            else
                trigger_in_sync1 <= '0';
                trigger_in_sync2 <= '0';
            end if;

            if TIMESTAMP_W > 0 then
                timestamp_counter <= timestamp_counter + 1;
            end if;

            active_probe := (others => '0');
            if PROBE_MUX_W > 0 then
                probe_idx := probe_sel * SAMPLE_W;
                active_probe := probe_in(probe_idx + SAMPLE_W - 1 downto probe_idx);
            elsif NUM_CHANNELS > 1 then
                probe_idx := chan_sel * SAMPLE_W;
                active_probe := probe_in(probe_idx + SAMPLE_W - 1 downto probe_idx);
            else
                active_probe := probe_in(SAMPLE_W - 1 downto 0);
            end if;
            if PROBE_PIPE > 0 then
                -- PROBE_PIPE stages, as rtl/fcapz_ela.v builds them.
                compare_probe := pipe_probe(PIPE_STAGES - 1);
                pipe_probe(0) <= active_probe;
                for i in 1 to PIPE_STAGES - 1 loop
                    pipe_probe(i) <= pipe_probe(i - 1);
                end loop;
            else
                compare_probe := active_probe;
            end if;

            hit_eff := comb_hit_eff;
            sq_eff := comb_sq_ok = '1';
            store_ok := comb_store_ok = '1';
            seg_start_next := seg_start_ptr;
            hit_a_pipe <= comb_hit_a;
            hit_b_pipe <= comb_hit_b;
            seq_pipe_a <= comb_seq_a;
            seq_pipe_b <= comb_seq_b;
            sq_pipe <= comb_sq_ok;
            reset_pulse_now := reset_sync_pulse = '1';
            arm_pulse_now := arm_sync_pulse = '1';
            any_arm_pulse_now := arm_pulse_now or startup_arm_pending = '1';

            -- One pulse per trigger: hits during the trigger-delay countdown
            -- are not evaluated, so they must not extend or repeat it.
            if armed = '1' and triggered = '0' and not any_arm_pulse_now and not reset_pulse_now and
               trig_delay_pending = '0' and
               pre_count >= count_u(pretrig_len) and trig_holdoff_active = '0' and
               sel_flush_active = '0' and hit_eff = '1' then
                trigger_out_i <= '1';
            else
                trigger_out_i <= '0';
            end if;

            if DECIM_EN = 0 then
                decim_count <= (others => '0');
            elsif any_arm_pulse_now or reset_pulse_now then
                -- A soft reset must not leave the count mid-ratio: idle
                -- prefill stores only on a decimation tick, and idle holds it.
                decim_count <= (others => '0');
            elsif armed = '1' and done = '0' then
                if decim_count >= decim_ratio then
                    decim_count <= (others => '0');
                else
                    decim_count <= decim_count + 1;
                end if;
            end if;

            if reset_pulse_now then
                armed <= '0';
                triggered <= '0';
                done <= '0';
                overflow <= '0';
                wr_ptr <= 0;
                pre_count <= (others => '0');
                post_left <= (others => '0');
                post_left_zero <= '1';
                post_left_one <= '0';
                capture_len <= (others => '0');
                cur_segment <= 0;
                seg_count <= 0;
                all_seg_done <= '0';
                segment_wrapped <= '0';
                seg_start_ptr <= (others => 0);
                seg_len <= (others => (others => '0'));
                trig_delay_pending <= '0';
                trig_delay_count <= (others => '0');
                trig_holdoff_active <= '0';
                trig_holdoff_count <= (others => '0');
                seq_state <= 0;
                seq_counter <= (others => '0');
                hit_a_pipe <= '0';
                hit_b_pipe <= '0';
                seq_pipe_a <= (others => '0');
                seq_pipe_b <= (others => '0');
                sq_pipe <= '0';
            end if;

            if done = '1' then
                armed <= '0';
                post_left <= (others => '0');
                post_left_zero <= '1';
                post_left_one <= '0';
                trig_delay_pending <= '0';
                trig_delay_count <= (others => '0');
                -- Sample writes are frozen while done is held (the host is
                -- reading the buffer out), so the rolling pre-arm history now
                -- has a hole in it.  pre_count must stop vouching for it, or
                -- the next arm lets a trigger commit immediately and
                -- start_ptr reaches back across the freeze into the previous
                -- capture -- a window spliced from two moments with nothing
                -- marking the join.  Segmented builds already clear pre_count
                -- on arm and on segment auto-rearm, so this is single-segment
                -- only.  Mirrors rtl/fcapz_ela.v.
                if NUM_SEGMENTS = 1 then
                    pre_count <= (others => '0');
                end if;
            end if;

            if any_arm_pulse_now then
                armed <= '1';
                triggered <= '0';
                done <= '0';
                if HAS_RLE_SEG_LEN then
                    seg_len <= (others => (others => '0'));
                end if;
                overflow <= '1' when len_sum_u(pretrig_len_stage) + len_sum_u(posttrig_len_stage) + 1 >
                                     len_sum_u(SEG_DEPTH) else '0';
                if NUM_SEGMENTS > 1 then
                    wr_ptr <= 0;
                    pre_count <= (others => '0');
                end if;
                -- A switched selection voids the rolling pre-arm history (it
                -- holds the old selection's samples), as does the
                -- qualification bubble (arm_sq_bubble).  So does a restart of
                -- a capture that had triggered: once its post-trigger samples
                -- are in, it stops writing, leaving a hole.
                if arm_voids_history = '1' or triggered = '1' then
                    pre_count <= (others => '0');
                end if;
                post_left <= (others => '0');
                post_left_zero <= '1';
                post_left_one <= '0';
                cur_segment <= 0;
                seg_count <= 0;
                all_seg_done <= '0';
                segment_wrapped <= '0';
                if not reset_pulse_now then
                    seg_start_ptr <= seg_start_ptr;
                end if;
                trig_delay_pending <= '0';
                trig_delay_count <= (others => '0');
                trig_holdoff <= trig_holdoff_stage;
                trig_holdoff_active <= '1' when trig_holdoff_stage > 0 else '0';
                trig_holdoff_count <= trig_holdoff_stage - 1 when trig_holdoff_stage > 0 else (others => '0');
                seq_state <= 0;
                seq_counter <= (others => '0');
                hit_a_pipe <= '0';
                hit_b_pipe <= '0';
                seq_pipe_a <= (others => '0');
                seq_pipe_b <= (others => '0');
                sq_pipe <= '0';
            end if;

            -- Idle prefill is single-segment only, as in rtl/fcapz_ela.v: a
            -- segmented capture restarts at address 0 on arm, and this block
            -- runs after the arm block on the arm edge (armed is still '0'),
            -- so an unguarded wr_ptr update here would override that reset
            -- and start segment 0 on stale pre-arm samples.
            -- A soft reset restarts the ring; prefill must not override it.
            if armed = '0' and done = '0' and not reset_pulse_now then
                trig_delay_pending <= '0';
                trig_delay_count <= (others => '0');
                if NUM_SEGMENTS = 1 and store_ok then
                    if pre_count < count_u(pretrig_len) and
                       not (any_arm_pulse_now and arm_voids_history = '1') then
                        pre_count <= pre_count + 1;
                    end if;
                    if triggered = '0' then
                        if wr_ptr = DEPTH - 1 then
                            wr_ptr <= 0;
                        else
                            wr_ptr <= wr_ptr + 1;
                        end if;
                    end if;
                end if;
            end if;

            -- An arm or soft reset on this edge restarts the capture, so the
            -- running capture's decisions below must not override it (as in
            -- rtl/fcapz_ela.v).  Only the single-segment ring still advances
            -- past the sample stored on this edge, which keeps the rolling
            -- history contiguous.
            if armed = '1' and done = '0' and (any_arm_pulse_now or reset_pulse_now) then
                if NUM_SEGMENTS = 1 and not reset_pulse_now and mem_we_a = '1' then
                    wr_ptr <= next_ptr(wr_ptr, 0);
                end if;
            elsif armed = '1' and done = '0' then
                base := seg_base(cur_segment);
                trigger_commit_now := false;
                force_store_now := comb_trigger_commit_now = '1';

                if trig_holdoff_active = '1' then
                    if trig_holdoff_count = 0 then
                        trig_holdoff_active <= '0';
                    else
                        trig_holdoff_count <= trig_holdoff_count - 1;
                    end if;
                end if;

                if triggered = '0' then
                    if trig_holdoff_active = '1' or sel_flush_active = '1' then
                        if trig_delay_pending = '0' then
                            trig_delay_count <= (others => '0');
                        end if;
                        null;
                    elsif trig_delay_pending = '1' then
                        if trig_delay_count = 0 then
                            trigger_commit_now := true;
                            trig_delay_pending <= '0';
                        else
                            trig_delay_count <= trig_delay_count - 1;
                        end if;
                    elsif pre_count >= count_u(pretrig_len) and trig_holdoff_active = '0' and hit_eff = '1' then
                        if trig_delay = 0 then
                            trigger_commit_now := true;
                        else
                            trig_delay_pending <= '1';
                            trig_delay_count <= trig_delay - 1;
                        end if;
                    elsif pre_count >= count_u(pretrig_len) and trig_holdoff_active = '0' and
                          TRIG_STAGES > 1 and comb_seq_stage_hit = '1' then
                        -- Mirrors seq_advance in rtl/fcapz_ela.v: a final
                        -- stage never advances, but its hits still count, or
                        -- a final stage with count target > 1 never triggers.
                        -- Its terminal hit is taken by the trigger branch
                        -- above; reaching here with the count met means the
                        -- external-trigger combine held it back.
                        if seq_is_final(seq_state) = '0' and
                           seq_count_reached(seq_counter, seq_count_target(seq_state)) then
                            seq_state <= to_integer(unsigned(seq_next_state(seq_state)));
                            seq_counter <= (others => '0');
                        elsif seq_counter /= x"FFFF" then
                            -- Saturate, as rtl/fcapz_ela.v: held-back hits
                            -- keep counting and must not wrap to 0 (BUG-255).
                            seq_counter <= seq_counter + 1;
                        end if;
                        trig_delay_count <= (others => '0');
                    else
                        trig_delay_count <= (others => '0');
                    end if;

                    store_now := store_ok or force_store_now;

                    if store_ok and not force_store_now then
                        if pre_count < count_u(pretrig_len) then
                            pre_count <= pre_count + 1;
                        end if;
                    end if;
                    -- segment_wrapped only matters with segments (as in
                    -- rtl/fcapz_ela.v); capture_start_ptr ignores it otherwise.
                    if NUM_SEGMENTS > 1 and store_now then
                        if wr_ptr = base + SEG_DEPTH - 1 then
                            segment_wrapped <= '1';
                        end if;
                    end if;

                    if trigger_commit_now then
                        triggered <= '1';
                        trig_ptr <= wr_ptr;
                        capture_len <= count_u(pretrig_len) + count_u(posttrig_len) + 1;
                        post_left <= posttrig_len;
                        post_left_zero <= bool_to_sl(posttrig_len = 0);
                        post_left_one <= bool_to_sl(posttrig_len = 1);
                        post_clk_left <= rle_post_clks;
                        post_clk_last <= post_clk_one;
                    end if;

                    if store_now then
                        wr_ptr <= next_ptr(wr_ptr, base);
                    end if;
                else
                    trig_delay_pending <= '0';
                    trig_delay_count <= (others => '0');
                    -- Post-trigger countdown (counts stored samples only).
                    -- With RLE a clock limit can end the window first.
                    if store_ok and post_left_zero = '0' then
                        if NUM_SEGMENTS > 1 then
                            if wr_ptr = base + SEG_DEPTH - 1 then
                                segment_wrapped <= '1';
                            end if;
                        end if;
                        wr_ptr <= next_ptr(wr_ptr, base);
                    end if;
                    if post_done_now = '1' then
                        -- Segment complete
                        capture_len <= capture_len_done;
                        start_calc := capture_start_ptr(trig_ptr, to_integer(pretrig_len), to_integer(posttrig_len), base, segment_wrapped);
                        if NUM_SEGMENTS = 1 then
                            done <= '1';
                            armed <= '0';
                            start_ptr <= start_calc;
                        else
                            for seg_i in 0 to NUM_SEGMENTS - 1 loop
                                if seg_i = cur_segment then
                                    seg_start_next(seg_i) := start_calc;
                                    if HAS_RLE_SEG_LEN then
                                        seg_len(seg_i) <= capture_len_done;
                                    end if;
                                else
                                    seg_start_next(seg_i) := seg_start_ptr(seg_i);
                                end if;
                            end loop;
                            seg_start_ptr <= seg_start_next;
                            if cur_segment = NUM_SEGMENTS - 1 then
                                done <= '1';
                                armed <= '0';
                                all_seg_done <= '1';
                                start_ptr <= seg_start_ptr(0);
                                seg_count <= NUM_SEGMENTS;
                            else
                                next_segment := cur_segment + 1;
                                cur_segment <= next_segment;
                                seg_count <= seg_count + 1;
                                triggered <= '0';
                                pre_count <= (others => '0');
                                post_left <= (others => '0');
                                post_left_zero <= '1';
                                post_left_one <= '0';
                                wr_ptr <= seg_base(next_segment);
                                segment_wrapped <= '0';
                                trig_delay_pending <= '0';
                                trig_delay_count <= (others => '0');
                                trig_holdoff_active <= '1' when trig_holdoff > 0 else '0';
                                trig_holdoff_count <= trig_holdoff - 1 when trig_holdoff > 0 else (others => '0');
                                seq_state <= 0;
                                seq_counter <= (others => '0');
                            end if;
                        end if;
                    else
                        if store_ok then
                            post_left <= post_left - 1;
                            post_left_zero <= '0';
                            post_left_one <= bool_to_sl(post_left = 2);
                        end if;
                        if HAS_RLE then
                            post_clk_left <= post_clk_left - 1;
                            post_clk_last <= bool_to_sl(post_clk_left = 2);
                        end if;
                    end if;
                end if;
            end if;

            probe_prev <= compare_probe;
        end if;
    end process;

    p_data_read_jtag : process(jtag_clk, jtag_rst)
    begin
        if jtag_rst = '1' then
            jtag_rdata_i <= (others => '0');
            datawin_reply_q <= '0';
            datawin_oob_q <= '0';
            datawin_is_ts_q <= '0';
            datawin_chunk_q <= 0;
        elsif rising_edge(jtag_clk) then
            datawin_reply_q <= datawin_req_now;
            datawin_oob_q <= datawin_oob_comb or burst_rd_active;
            datawin_is_ts_q <= datawin_is_ts_comb;
            datawin_chunk_q <= datawin_chunk_comb;

            if jtag_rd_en = '1' and jtag_rd_data_window = '0' then
                jtag_rdata_i <= jtag_rdata_mux;
            end if;

            if datawin_reply_q = '1' then
                if datawin_oob_q = '1' then
                    jtag_rdata_i <= (others => '0');
                elsif datawin_is_ts_q = '1' then
                    if jtag_rle_ctrl(1) = '1' then
                        jtag_rdata_i <= aux_chunk_word(aux_rle_b, datawin_chunk_q);
                    else
                        jtag_rdata_i <= aux_chunk_word(aux_ts_b, datawin_chunk_q);
                    end if;
                else
                    jtag_rdata_i <= sample_chunk_word(sample_mem_dout_b, datawin_chunk_q);
                end if;
            end if;
        end if;
    end process;

    p_read_mux : process(all)
        variable addr : natural;
        variable r : std_logic_vector(31 downto 0);
        variable rd_start : natural;
        variable seq_stage : natural;
        variable seq_off : natural;
    begin
        addr := to_integer(unsigned(jtag_addr));
        r := (others => '0');
        rd_start := rb_start_ptr_jtag;
        if NUM_SEGMENTS > 1 then
            rd_start := rb_seg_start_ptr_jtag(jtag_seg_sel);
        end if;

        case addr is
            when ADDR_VERSION => r := FCAPZ_ELA_VERSION_REG;
            when ADDR_CTRL => r := jtag_ctrl;
            when ADDR_STATUS => r := x"0000000" & overflow & rb_done_jtag & triggered & armed;
            when ADDR_SAMPLE_W => r := u32(SAMPLE_W);
            when ADDR_DEPTH => r := u32(DEPTH);
            when ADDR_PRETRIG => r := jtag_pretrig_len;
            when ADDR_POSTTRIG => r := jtag_posttrig_len;
            when ADDR_CAPTURE_LEN => r := u32(rb_window_len_jtag);
            when ADDR_TRIG_MODE => r := jtag_trig_mode;
            when ADDR_TRIG_VALUE => r := jtag_trig_value;
            when ADDR_TRIG_MASK => r := jtag_trig_mask;
            when ADDR_SQ_MODE => r := jtag_sq_mode when STOR_QUAL /= 0 else x"00000000";
            when ADDR_SQ_VALUE => r := jtag_sq_value when STOR_QUAL /= 0 else x"00000000";
            when ADDR_SQ_MASK => r := jtag_sq_mask when STOR_QUAL /= 0 else x"00000000";
            when ADDR_FEATURES => r := FEATURES;
            when ADDR_CHAN_SEL => r := u32(jtag_chan_sel) when NUM_CHANNELS > 1 else x"00000000";
            when ADDR_NUM_CHAN => r := u32(NUM_CHANNELS);
            when ADDR_DECIM => r := x"00" & jtag_decim when DECIM_EN /= 0 else x"00000000";
            when ADDR_TRIG_EXT => r := u32(to_integer(unsigned(jtag_trig_ext))) when EXT_TRIG_EN /= 0 else x"00000000";
            when ADDR_NUM_SEGMENTS => r := u32(NUM_SEGMENTS);
            when ADDR_SEG_STATUS =>
                r := (others => '0');
                if NUM_SEGMENTS > 1 then
                    r(31) := all_seg_done;
                    r(SEG_IDX_W - 1 downto 0) := std_logic_vector(to_unsigned(seg_count mod (2 ** SEG_IDX_W), SEG_IDX_W));
                else
                    r := x"80000000";
                end if;
            when ADDR_SEG_SEL => r := u32(jtag_seg_sel) when NUM_SEGMENTS > 1 else x"00000000";
            when ADDR_TIMESTAMP_W => r := u32(TIMESTAMP_W);
            when ADDR_SEG_START => r := u32(rd_start);
            when ADDR_PROBE_SEL => r := u32(jtag_probe_sel) when PROBE_MUX_W > 0 else x"00000000";
            when ADDR_PROBE_MUX_W => r := u32(PROBE_MUX_W);
            when ADDR_TRIG_DELAY => r := x"0000" & jtag_trig_delay;
            when ADDR_STARTUP_ARM => r := (31 downto 1 => '0') & jtag_startup_arm;
            when ADDR_TRIG_HOLDOFF => r := x"0000" & jtag_trig_holdoff;
            when ADDR_COMPARE_CAPS =>
                r := x"000201FF" when REL_COMPARE /= 0 else x"000201C3";
                if DUAL_COMPARE /= 0 then
                    r(16) := '1';
                end if;
                if HAS_WIDE_TRIG then
                    r(18) := '1';  -- full-width comparator A programmable
                end if;
                r(19) := '1';  -- timestamp window base decoded at full width
                if USER1_DATA_EN /= 0 then
                    r(20) := '1';  -- DATA_OFFSET
                end if;
                r(21) := '1';  -- CAPTURE_GEN
                r(22) := '1';  -- SQ_MODE is compare mode + 1
            when ADDR_WIDE_SEL =>
                r := (others => '0');
                if HAS_WIDE_TRIG then
                    r(7 downto 0) := jtag_wide_sel;
                end if;
            when ADDR_DATA_OFFSET =>
                r := jtag_data_offset;
            when ADDR_CAPTURE_GEN =>
                r := x"0000" & std_logic_vector(capture_gen);
            when ADDR_RLE_CTRL =>
                r := (others => '0');
                if HAS_RLE then
                    r(1 downto 0) := jtag_rle_ctrl;
                end if;
            when ADDR_RLE_W => r := u32(RLE_W);
            when ADDR_RLE_POST_CLKS =>
                r := (others => '0');
                if HAS_RLE then
                    r(POST_CLK_W - 1 downto 0) := jtag_rle_post_clks;
                end if;
            when others =>
                if TRIG_STAGES > 1 and addr >= ADDR_SEQ_BASE and addr < ADDR_SEQ_BASE + TRIG_STAGES * SEQ_STRIDE then
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
