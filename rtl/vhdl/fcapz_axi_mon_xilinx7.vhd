-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- fpgacapZero AXI Monitor wrapper for Xilinx 7-series / UltraScale (VHDL).
-- Native-VHDL translation of rtl/fcapz_axi_mon_xilinx7.v.
--
-- Single-instantiation wrapper: bundles fcapz_axi_mon (AXI4-Lite passive tap +
-- embedded ELA), the single-chain register/burst pipe interface, and the
-- BSCANE2 TAP primitive. Drop it onto an AXI4-Lite interface to capture and
-- trigger on bus traffic over JTAG. See docs/specs/axi_monitor.md.

library ieee;
use ieee.std_logic_1164.all;

library work;
use work.fcapz_util_pkg.all;

entity fcapz_axi_mon_xilinx7 is
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
        BURST_W       : positive := 256;
        CTRL_CHAIN    : positive := 1     -- BSCANE2 USER chain for control + burst
    );
    port (
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
        armed_out   : out std_logic
    );
end entity fcapz_axi_mon_xilinx7;

architecture rtl of fcapz_axi_mon_xilinx7 is
    constant PTR_W           : positive := fcapz_clog2(DEPTH);
    constant TS_W_SAFE       : positive := fcapz_nonzero_width(TIMESTAMP_W);
    constant SAMPLE_W        : positive := fcapz_axi_mon_sample_w(ADDR_W, DATA_W, DECODE_EN);
    constant BURST_SEG_DEPTH : positive := DEPTH / NUM_SEGMENTS;

    -- TAP (USER chain)
    signal tap_tck     : std_logic;
    signal tap_tdi     : std_logic;
    signal tap_tdo     : std_logic;
    signal tap_capture : std_logic;
    signal tap_shift   : std_logic;
    signal tap_update  : std_logic;
    signal tap_sel     : std_logic;

    -- Register / burst bus
    signal jtag_clk   : std_logic;
    signal jtag_rst   : std_logic;
    signal jtag_wr_en : std_logic;
    signal jtag_rd_en : std_logic;
    signal jtag_addr  : std_logic_vector(15 downto 0);
    signal jtag_wdata : std_logic_vector(31 downto 0);
    signal jtag_rdata : std_logic_vector(31 downto 0);

    signal burst_rd_addr    : std_logic_vector(PTR_W - 1 downto 0);
    signal burst_rd_active  : std_logic := '0';
    signal burst_rd_data    : std_logic_vector(SAMPLE_W - 1 downto 0);
    signal burst_rd_ts_data : std_logic_vector(TS_W_SAFE - 1 downto 0);
    signal burst_start      : std_logic;
    signal burst_timestamp  : std_logic;
    signal burst_start_ptr  : std_logic_vector(PTR_W - 1 downto 0);
    signal jtag_rst_ctrl    : std_logic;

    signal aresetn_inv : std_logic;
begin
    aresetn_inv <= not ARESETN;

    u_tap_ctrl : entity work.jtag_tap_xilinx7
        generic map (
            CHAIN => CTRL_CHAIN
        )
        port map (
            tck => tap_tck,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift => tap_shift,
            update => tap_update,
            sel => tap_sel
        );

    u_rst_sync_ctrl : entity work.reset_sync
        port map (
            clk => tap_tck,
            arst => aresetn_inv,
            srst => jtag_rst_ctrl
        );

    u_pipe : entity work.jtag_pipe_iface
        generic map (
            SAMPLE_W => SAMPLE_W,
            TIMESTAMP_W => TIMESTAMP_W,
            DEPTH => DEPTH,
            BURST_W => BURST_W,
            SEG_DEPTH => BURST_SEG_DEPTH,
            BURST_PTR_ADDR => 16#002C#
        )
        port map (
            arst => jtag_rst_ctrl,
            tck => tap_tck,
            tdi => tap_tdi,
            tdo => tap_tdo,
            capture => tap_capture,
            shift_en => tap_shift,
            update => tap_update,
            sel => tap_sel,
            reg_clk => jtag_clk,
            reg_rst => jtag_rst,
            reg_wr_en => jtag_wr_en,
            reg_rd_en => jtag_rd_en,
            reg_addr => jtag_addr,
            reg_wdata => jtag_wdata,
            reg_rdata => jtag_rdata,
            mem_addr => burst_rd_addr,
            mem_active => burst_rd_active,
            sample_data => burst_rd_data,
            timestamp_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_ptr_in => burst_start_ptr
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
            burst_rd_active => burst_rd_active,
            burst_rd_addr => burst_rd_addr,
            burst_rd_data => burst_rd_data,
            burst_rd_ts_data => burst_rd_ts_data,
            burst_start => burst_start,
            burst_timestamp => burst_timestamp,
            burst_start_ptr => burst_start_ptr
        );
end architecture rtl;
