-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- fpgacapZero AXI Monitor (VHDL) -- native-VHDL translation of the source-of-
-- truth Verilog rtl/fcapz_axi_mon.v.  The two are kept in lockstep by the
-- Verilog/VHDL parity checks (sim/run_hdl_parity.py static generics/constants +
-- sim/parity/fcapz_axi_mon.yml formal equivalence).
--
-- Passively taps an AXI4-Lite interface (it NEVER drives any *VALID/*READY --
-- every AXI port here is an input wired in parallel with the real bus),
-- flattens the five channels into one capture vector, and feeds that to an
-- embedded fcapz_ela capture/trigger engine.
--
-- Capture-vector layout (LSB-first; ADDR_W=DATA_W=32 -> SAMPLE_W=152):
--   AW : awaddr[ADDR_W] awprot[3] awvalid awready
--   W  : wdata[DATA_W]  wstrb[DATA_W/8] wvalid wready
--   B  : bresp[2] bvalid bready
--   AR : araddr[ADDR_W] arprot[3] arvalid arready
--   R  : rdata[DATA_W]  rresp[2] rvalid rready
-- The shipped probe map (host/fcapz/probes/axi4lite_32.prob) names every field
-- at these offsets; keep them in lockstep.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_axi_mon is
    generic (
        PROTO         : string   := "AXI4LITE";  -- P1 supports "AXI4LITE" only
        ADDR_W        : positive := 32;
        DATA_W        : positive := 32;
        -- pass-through fcapz_ela capture/trigger configuration
        DEPTH         : positive := 1024;
        TRIG_STAGES   : positive := 4;
        STOR_QUAL     : natural  := 1;
        NUM_SEGMENTS  : positive := 1;
        TIMESTAMP_W   : natural  := 32;
        INPUT_PIPE    : natural  := 1;
        DECIM_EN      : natural  := 0;
        EXT_TRIG_EN   : natural  := 0;
        STARTUP_ARM   : natural  := 0;
        REL_COMPARE   : natural  := 1;
        DUAL_COMPARE  : natural  := 1;
        USER1_DATA_EN : natural  := 1;
        -- Full-SAMPLE_W comparator A (trigger on any AXI field, not just low 32).
        WIDE_TRIG     : natural  := 1;
        -- Decode layer (P2): prepend an 8-bit transaction-events word at the LSB.
        DECODE_EN     : natural  := 0
    );
    port (
        -- ---- Passive AXI4-Lite monitor tap (inputs only) ----
        ACLK             : in  std_logic;
        ARESETN          : in  std_logic;
        AWADDR           : in  std_logic_vector(ADDR_W - 1 downto 0);
        AWPROT           : in  std_logic_vector(2 downto 0);
        AWVALID          : in  std_logic;
        AWREADY          : in  std_logic;
        WDATA            : in  std_logic_vector(DATA_W - 1 downto 0);
        WSTRB            : in  std_logic_vector(DATA_W / 8 - 1 downto 0);
        WVALID           : in  std_logic;
        WREADY           : in  std_logic;
        BRESP            : in  std_logic_vector(1 downto 0);
        BVALID           : in  std_logic;
        BREADY           : in  std_logic;
        ARADDR           : in  std_logic_vector(ADDR_W - 1 downto 0);
        ARPROT           : in  std_logic_vector(2 downto 0);
        ARVALID          : in  std_logic;
        ARREADY          : in  std_logic;
        RDATA            : in  std_logic_vector(DATA_W - 1 downto 0);
        RRESP            : in  std_logic_vector(1 downto 0);
        RVALID           : in  std_logic;
        RREADY           : in  std_logic;

        -- ---- External trigger I/O (forwarded to the ELA) ----
        trigger_in       : in  std_logic;
        trigger_out      : out std_logic;
        armed_out        : out std_logic;

        -- ---- JTAG register bus (identical to fcapz_ela) ----
        jtag_clk         : in  std_logic;
        jtag_rst         : in  std_logic;
        jtag_wr_en       : in  std_logic;
        jtag_rd_en       : in  std_logic;
        jtag_addr        : in  std_logic_vector(15 downto 0);
        jtag_wdata       : in  std_logic_vector(31 downto 0);
        jtag_rdata       : out std_logic_vector(31 downto 0);

        -- ---- Burst read port (jtag_clk domain, active when done=1) ----
        burst_rd_active  : in  std_logic;
        burst_rd_addr    : in  std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0);
        burst_rd_data    : out std_logic_vector(fcapz_axi_mon_sample_w(ADDR_W, DATA_W, DECODE_EN) - 1 downto 0);
        burst_rd_ts_data : out std_logic_vector(fcapz_nonzero_width(TIMESTAMP_W) - 1 downto 0);
        burst_start      : out std_logic;
        burst_timestamp  : out std_logic;
        burst_start_ptr  : out std_logic_vector(fcapz_clog2(DEPTH) - 1 downto 0)
    );
end entity fcapz_axi_mon;

architecture rtl of fcapz_axi_mon is
    constant CHANNELS_W : positive := fcapz_axi_mon_sample_w(ADDR_W, DATA_W, 0);
    constant SAMPLE_W   : positive := fcapz_axi_mon_sample_w(ADDR_W, DATA_W, DECODE_EN);

    -- AXI-monitor identity registers.  The embedded ELA owns config space
    -- 0x0000-0x00FF and exposes captured samples at 0x0100+, so the AM identity
    -- lives in the free gap above the ELA's last config register (0x00E0) and
    -- below the data window.  (Kept in parity with the Verilog localparams.)
    constant ADDR_AXI_MON_ID : natural := 16#00E8#;
    constant ADDR_AXI_GEOM   : natural := 16#00EC#;
    constant PROTO_CODE      : natural := 1;  -- 1 = AXI4-Lite
    constant GEOM_ID_W       : natural := 0;  -- AXI4-Lite has no AWID/ARID
    constant GEOM_CHANNELS   : natural := 5;  -- AW, W, B, AR, R

    -- CAP_FLAGS bit0 = DECODE_EN (mirrors the Verilog ternary).
    constant CAP_FLAGS : std_logic_vector(7 downto 0) :=
        std_logic_vector(to_unsigned(boolean'pos(DECODE_EN /= 0), 8));

    constant axi_mon_id : std_logic_vector(31 downto 0) :=
        FCAPZ_AXIMON_CORE_ID &
        std_logic_vector(to_unsigned(PROTO_CODE, 8)) &
        CAP_FLAGS;  -- "AM"
    -- Geometry telemetry: [7:0]=ADDR_W, [15:8]=DATA_W, [19:16]=ID_W,
    -- [24:20]=captured AXI channel count.
    constant axi_geom : std_logic_vector(31 downto 0) :=
        "0000000" &
        std_logic_vector(to_unsigned(GEOM_CHANNELS, 5)) &
        std_logic_vector(to_unsigned(GEOM_ID_W, 4)) &
        std_logic_vector(to_unsigned(DATA_W, 8)) &
        std_logic_vector(to_unsigned(ADDR_W, 8));

    signal channels   : std_logic_vector(CHANNELS_W - 1 downto 0);
    signal events     : std_logic_vector(7 downto 0);
    signal probe_vec  : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal b_err      : std_logic;
    signal r_err      : std_logic;
    signal sample_rst : std_logic;

    signal ela_rdata  : std_logic_vector(31 downto 0);
    signal am_rdata   : std_logic_vector(31 downto 0) := (others => '0');
    signal am_hit     : std_logic := '0';
begin
    -- ---- Flatten the AXI channels into the capture vector (LSB-first) -------
    -- Leftmost operand is the MSB end; assignment is by position, matching the
    -- Verilog concatenation bit-for-bit (all fields are `downto`, MSB first).
    channels <=
        RREADY & RVALID & RRESP & RDATA &        -- R channel  (MSB end)
        ARREADY & ARVALID & ARPROT & ARADDR &    -- AR channel
        BREADY & BVALID & BRESP &                -- B channel
        WREADY & WVALID & WSTRB & WDATA &        -- W channel
        AWREADY & AWVALID & AWPROT & AWADDR;     -- AW channel (awaddr at LSBs)

    -- ---- Derived transaction events (combinational; P2 decode layer) -------
    b_err <= BVALID and BRESP(1);   -- SLVERR(2)/DECERR(3) -> RESP[1]=1
    r_err <= RVALID and RRESP(1);
    events <=
        (b_err or r_err) &        -- [7] any_err
        r_err &                   -- [6] r_err
        b_err &                   -- [5] b_err
        (RVALID and RREADY) &     -- [4] r_hs
        (ARVALID and ARREADY) &   -- [3] ar_hs
        (BVALID and BREADY) &     -- [2] b_hs
        (WVALID and WREADY) &     -- [1] w_hs
        (AWVALID and AWREADY);    -- [0] aw_hs

    -- Events sit at the LSB (when enabled) so the low-32-bit trigger can match
    -- them; otherwise the raw channels start at bit 0 (P1 layout).
    g_decode : if DECODE_EN /= 0 generate
        probe_vec <= channels & events;
    end generate;
    g_raw : if DECODE_EN = 0 generate
        probe_vec <= channels;
    end generate;

    -- ---- AXI-monitor identity registers ------------------------------------
    -- Registered on jtag_clk so the read timing matches the ELA's registered
    -- jtag_rdata.
    process(jtag_clk)
    begin
        if rising_edge(jtag_clk) then
            if jtag_rst = '1' then
                am_hit   <= '0';
                am_rdata <= (others => '0');
            else
                if unsigned(jtag_addr) = ADDR_AXI_MON_ID
                   or unsigned(jtag_addr) = ADDR_AXI_GEOM then
                    am_hit <= '1';
                else
                    am_hit <= '0';
                end if;
                if unsigned(jtag_addr) = ADDR_AXI_GEOM then
                    am_rdata <= axi_geom;
                else
                    am_rdata <= axi_mon_id;
                end if;
            end if;
        end if;
    end process;

    jtag_rdata <= am_rdata when am_hit = '1' else ela_rdata;

    sample_rst <= not ARESETN;

    -- ---- Embedded ELA capture/trigger engine -------------------------------
    u_ela : entity work.fcapz_ela
        generic map (
            SAMPLE_W      => SAMPLE_W,
            DEPTH         => DEPTH,
            TRIG_STAGES   => TRIG_STAGES,
            STOR_QUAL     => STOR_QUAL,
            NUM_CHANNELS  => 1,
            INPUT_PIPE    => INPUT_PIPE,
            DECIM_EN      => DECIM_EN,
            EXT_TRIG_EN   => EXT_TRIG_EN,
            TIMESTAMP_W   => TIMESTAMP_W,
            NUM_SEGMENTS  => NUM_SEGMENTS,
            PROBE_MUX_W   => 0,
            STARTUP_ARM   => STARTUP_ARM,
            REL_COMPARE   => REL_COMPARE,
            DUAL_COMPARE  => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN,
            WIDE_TRIG     => WIDE_TRIG
        )
        port map (
            sample_clk       => ACLK,
            sample_rst       => sample_rst,
            probe_in         => probe_vec,
            trigger_in       => trigger_in,
            trigger_out      => trigger_out,
            armed_out        => armed_out,
            jtag_clk         => jtag_clk,
            jtag_rst         => jtag_rst,
            jtag_wr_en       => jtag_wr_en,
            jtag_rd_en       => jtag_rd_en,
            jtag_addr        => jtag_addr,
            jtag_wdata       => jtag_wdata,
            jtag_rdata       => ela_rdata,
            burst_rd_active  => burst_rd_active,
            burst_rd_addr    => burst_rd_addr,
            burst_rd_data    => burst_rd_data,
            burst_rd_ts_data => burst_rd_ts_data,
            burst_start      => burst_start,
            burst_timestamp  => burst_timestamp,
            burst_start_ptr  => burst_start_ptr
        );
end architecture rtl;
