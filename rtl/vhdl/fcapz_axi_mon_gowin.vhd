-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- fpgacapZero AXI Monitor wrapper for Gowin GW1N / GW2A (VHDL).
-- Native-VHDL translation of rtl/fcapz_axi_mon_gowin.v.
--
-- Single-instantiation wrapper: bundles fcapz_axi_mon (AXI4-Lite passive tap +
-- embedded ELA), the register interface and the GW_JTAG TAP. Register-only:
-- there is no burst engine, and the host reads captures word by word through
-- the register window (five reads per 152-bit sample), so keep DEPTH modest.
-- GW_JTAG is oversampled on clk (at least ~10x TCK), which is also the
-- register-bus clock. Gowin allows one GW_JTAG per device, so this is the only
-- fcapz core on the device. See docs/19_axi_monitor.md.

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_axi_mon_gowin is
    generic (
        PROTO         : string   := "AXI4LITE";
        ADDR_W        : positive := 32;
        DATA_W        : positive := 32;
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
        WIDE_TRIG     : natural  := 1;    -- full-width comparator A
        DECODE_EN     : natural  := 0;    -- P2 transaction-events word at the LSB
        CTRL_CHAIN    : positive := 1     -- GW_JTAG user chain: 1 = ER1, 2 = ER2
    );
    port (
        -- Oversampling clock for GW_JTAG; also the register-bus clock.
        clk           : in  std_logic;
        -- High while the GW_JTAG TAP is active (from jtag_tap_gowin).
        jtag_activity : out std_logic;

        -- ---- Passive AXI4-Lite monitor tap (inputs only) ----
        ACLK        : in  std_logic;
        ARESETN     : in  std_logic;
        AWADDR      : in  std_logic_vector(ADDR_W - 1 downto 0);
        AWPROT      : in  std_logic_vector(2 downto 0);
        AWVALID     : in  std_logic;
        AWREADY     : in  std_logic;
        WDATA       : in  std_logic_vector(DATA_W - 1 downto 0);
        WSTRB       : in  std_logic_vector(DATA_W / 8 - 1 downto 0);
        WVALID      : in  std_logic;
        WREADY      : in  std_logic;
        BRESP       : in  std_logic_vector(1 downto 0);
        BVALID      : in  std_logic;
        BREADY      : in  std_logic;
        ARADDR      : in  std_logic_vector(ADDR_W - 1 downto 0);
        ARPROT      : in  std_logic_vector(2 downto 0);
        ARVALID     : in  std_logic;
        ARREADY     : in  std_logic;
        RDATA       : in  std_logic_vector(DATA_W - 1 downto 0);
        RRESP       : in  std_logic_vector(1 downto 0);
        RVALID      : in  std_logic;
        RREADY      : in  std_logic;
        -- External trigger I/O
        trigger_in  : in  std_logic;
        trigger_out : out std_logic;
        armed_out   : out std_logic;

        -- GW_JTAG pads: wire straight to top-level ports.
        tms_pad_i   : in  std_logic;
        tck_pad_i   : in  std_logic;
        tdi_pad_i   : in  std_logic;
        tdo_pad_o   : out std_logic
    );
end entity fcapz_axi_mon_gowin;

architecture rtl of fcapz_axi_mon_gowin is
    constant PTR_W           : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE       : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant SAMPLE_W        : positive := fcapz_axi_mon_sample_w(ADDR_W, DATA_W, DECODE_EN);

    constant CHAIN_IDX       : natural := CTRL_CHAIN - 1;

    -- TAP (GW_JTAG, both user chains)
    signal tap_tdi : std_logic;
    signal tap_tdo, tap_capture, tap_update, tap_sel : std_logic_vector(1 downto 0);
    signal tap_shift_in, tap_shift_out : std_logic_vector(1 downto 0);

    -- Register bus
    signal jtag_clk   : std_logic;
    signal jtag_rst   : std_logic;
    signal jtag_wr_en : std_logic;
    signal jtag_rd_en : std_logic;
    signal jtag_addr  : std_logic_vector(15 downto 0);
    signal jtag_wdata : std_logic_vector(31 downto 0);
    signal jtag_rdata : std_logic_vector(31 downto 0);
    signal jtag_rst_ctrl : std_logic;

    -- No burst path: the monitor's burst bus is tied off.
    signal burst_rd_addr_zero      : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_data_unused    : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data_unused : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start_unused      : std_logic;
    signal burst_timestamp_unused  : std_logic;
    signal burst_start_ptr_unused  : std_logic_vector(PTR_W - 1 downto 0);

    signal aresetn_inv : std_logic;
begin
    assert CTRL_CHAIN = 1 or CTRL_CHAIN = 2
        report "fcapz_axi_mon_gowin: CTRL_CHAIN must be 1 (ER1) or 2 (ER2)"
        severity failure;

    aresetn_inv <= not ARESETN;

    -- The other user chain has no register interface; drive its TDO low.
    tap_tdo(1 - CHAIN_IDX) <= '0';
    burst_rd_addr_zero <= (others => '0');

    u_tap_ctrl : entity work.jtag_tap_gowin
        port map (
            sysclk => clk,
            activity => jtag_activity,
            tdi => tap_tdi, tdo => tap_tdo,
            capture => tap_capture,
            shift_in => tap_shift_in, shift_out => tap_shift_out,
            update => tap_update, sel => tap_sel,
            tms_pad_i => tms_pad_i, tck_pad_i => tck_pad_i,
            tdi_pad_i => tdi_pad_i, tdo_pad_o => tdo_pad_o
        );

    -- The TAP's events are oversampled onto clk, so the register interface
    -- runs there.
    u_rst_sync_ctrl : entity work.reset_sync
        port map (
            clk => clk,
            arst => aresetn_inv,
            srst => jtag_rst_ctrl
        );

    u_reg : entity work.jtag_reg_iface_gowin
        port map (
            arst => jtag_rst_ctrl,
            tck => clk,
            tdi => tap_tdi,
            tdo => tap_tdo(CHAIN_IDX),
            capture => tap_capture(CHAIN_IDX),
            shift_in_en => tap_shift_in(CHAIN_IDX),
            shift_out_en => tap_shift_out(CHAIN_IDX),
            update => tap_update(CHAIN_IDX),
            sel => tap_sel(CHAIN_IDX),
            reg_clk => jtag_clk,
            reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en,
            reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr,
            reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata
        );

    u_mon : entity work.fcapz_axi_mon
        generic map (
            PROTO => PROTO,
            ADDR_W => ADDR_W,
            DATA_W => DATA_W,
            DEPTH => DEPTH,
            TRIG_STAGES => TRIG_STAGES,
            STOR_QUAL => STOR_QUAL,
            NUM_SEGMENTS => NUM_SEGMENTS,
            TIMESTAMP_W => TIMESTAMP_W,
            INPUT_PIPE => INPUT_PIPE,
            DECIM_EN => DECIM_EN,
            EXT_TRIG_EN => EXT_TRIG_EN,
            STARTUP_ARM => STARTUP_ARM,
            REL_COMPARE => REL_COMPARE,
            DUAL_COMPARE => DUAL_COMPARE,
            USER1_DATA_EN => USER1_DATA_EN,
            WIDE_TRIG => WIDE_TRIG,
            DECODE_EN => DECODE_EN
        )
        port map (
            ACLK => ACLK,
            ARESETN => ARESETN,
            AWADDR => AWADDR,
            AWPROT => AWPROT,
            AWVALID => AWVALID,
            AWREADY => AWREADY,
            WDATA => WDATA,
            WSTRB => WSTRB,
            WVALID => WVALID,
            WREADY => WREADY,
            BRESP => BRESP,
            BVALID => BVALID,
            BREADY => BREADY,
            ARADDR => ARADDR,
            ARPROT => ARPROT,
            ARVALID => ARVALID,
            ARREADY => ARREADY,
            RDATA => RDATA,
            RRESP => RRESP,
            RVALID => RVALID,
            RREADY => RREADY,
            trigger_in => trigger_in,
            trigger_out => trigger_out,
            armed_out => armed_out,
            jtag_clk => jtag_clk,
            jtag_rst => jtag_rst,
            jtag_wr_en => jtag_wr_en,
            jtag_rd_en => jtag_rd_en,
            jtag_addr => jtag_addr,
            jtag_wdata => jtag_wdata,
            jtag_rdata => jtag_rdata,
            burst_rd_active => '0',
            burst_rd_addr => burst_rd_addr_zero,
            burst_rd_data => burst_rd_data_unused,
            burst_rd_ts_data => burst_rd_ts_data_unused,
            burst_start => burst_start_unused,
            burst_timestamp => burst_timestamp_unused,
            burst_start_ptr => burst_start_ptr_unused
        );
end architecture rtl;
