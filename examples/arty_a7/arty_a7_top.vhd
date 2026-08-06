-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Arty A7-100T mixed-language VHDL-core hardware-validation top-level.
--
-- Topology intentionally mirrors arty_a7_top.v: two managed ELAs plus two
-- managed EIOs share USER1 through fcapz_debug_multi_xilinx7, a MicroBlaze
-- subsystem (mb_sys_wrapper, MDM on USER3) and the EJTAG-AXI bridge (USER4)
-- share one monitored AXI bus, and the AXI monitor observes it on USER2. The
-- VHDL build omits rtl/fcapz_ela.v and rtl/fcapz_eio.v, so the Verilog wrappers
-- bind those core instances to the translated VHDL entities in rtl/vhdl/core.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity arty_a7_top is
    port (
        clk : in  std_logic;
        btn : in  std_logic_vector(3 downto 0);
        led : out std_logic_vector(3 downto 0)
    );
end entity arty_a7_top;

architecture rtl of arty_a7_top is
    constant SAMPLE_W     : positive := 8;
    constant DEPTH        : positive := 1024;
    constant NUM_SEGMENTS : positive := 4;
    constant CLK150_HZ    : positive := 150_000_000;

    component MMCME2_BASE is
        generic (
            BANDWIDTH          : string := "OPTIMIZED";
            CLKFBOUT_MULT_F    : real := 5.0;
            CLKFBOUT_PHASE     : real := 0.0;
            CLKIN1_PERIOD      : real := 0.0;
            CLKOUT0_DIVIDE_F   : real := 1.0;
            CLKOUT0_DUTY_CYCLE : real := 0.5;
            CLKOUT0_PHASE      : real := 0.0;
            DIVCLK_DIVIDE      : integer := 1;
            REF_JITTER1        : real := 0.010;
            STARTUP_WAIT       : string := "FALSE"
        );
        port (
            CLKIN1    : in  std_logic;
            CLKFBIN   : in  std_logic;
            CLKFBOUT  : out std_logic;
            CLKFBOUTB : out std_logic;
            CLKOUT0   : out std_logic;
            CLKOUT0B  : out std_logic;
            CLKOUT1   : out std_logic;
            CLKOUT1B  : out std_logic;
            CLKOUT2   : out std_logic;
            CLKOUT2B  : out std_logic;
            CLKOUT3   : out std_logic;
            CLKOUT3B  : out std_logic;
            CLKOUT4   : out std_logic;
            CLKOUT5   : out std_logic;
            CLKOUT6   : out std_logic;
            LOCKED    : out std_logic;
            PWRDWN    : in  std_logic;
            RST       : in  std_logic
        );
    end component;

    component BUFG is
        port (
            I : in  std_logic;
            O : out std_logic
        );
    end component;

    component fcapz_debug_multi_xilinx7 is
        generic (
            NUM_ELAS         : integer := 2;
            EIO_EN           : integer := 1;
            NUM_EIOS         : integer := 2;
            SAMPLE_W         : integer := 8;
            DEPTH            : integer := 1024;
            INPUT_PIPE       : integer := 1;
            DECIM_EN         : integer := 1;
            EXT_TRIG_EN      : integer := 1;
            TIMESTAMP_W      : integer := 32;
            NUM_SEGMENTS     : integer := 4;
            STARTUP_ARM      : integer := 1;
            DEFAULT_TRIG_EXT : integer := 2;
            EIO_IN_W         : integer := 8;
            EIO_OUT_W        : integer := 8
        );
        port (
            ela_sample_clk  : in  std_logic_vector(NUM_ELAS - 1 downto 0);
            ela_sample_rst  : in  std_logic_vector(NUM_ELAS - 1 downto 0);
            ela_probe_in    : in  std_logic_vector(NUM_ELAS * SAMPLE_W - 1 downto 0);
            ela_trigger_in  : in  std_logic_vector(NUM_ELAS - 1 downto 0);
            ela_trigger_out : out std_logic_vector(NUM_ELAS - 1 downto 0);
            ela_armed_out   : out std_logic_vector(NUM_ELAS - 1 downto 0);
            eio_probe_in    : in  std_logic_vector(NUM_EIOS * EIO_IN_W - 1 downto 0);
            eio_probe_out   : out std_logic_vector(NUM_EIOS * EIO_OUT_W - 1 downto 0)
        );
    end component;

    component fcapz_ejtagaxi_xilinx7 is
        generic (
            ADDR_W               : integer := 32;
            DATA_W               : integer := 32;
            FIFO_DEPTH           : integer := 16;
            CMD_FIFO_DEPTH       : integer := 16;
            RESP_FIFO_DEPTH      : integer := 16;
            CMD_FIFO_MEMORY_TYPE : string := "distributed";
            TIMEOUT              : integer := 4096;
            DEBUG_EN             : integer := 0
        );
        port (
            axi_clk       : in  std_logic;
            axi_rst       : in  std_logic;
            m_axi_awaddr  : out std_logic_vector(ADDR_W - 1 downto 0);
            m_axi_awlen   : out std_logic_vector(7 downto 0);
            m_axi_awsize  : out std_logic_vector(2 downto 0);
            m_axi_awburst : out std_logic_vector(1 downto 0);
            m_axi_awvalid : out std_logic;
            m_axi_awready : in  std_logic;
            m_axi_awprot  : out std_logic_vector(2 downto 0);
            m_axi_wdata   : out std_logic_vector(DATA_W - 1 downto 0);
            m_axi_wstrb   : out std_logic_vector((DATA_W / 8) - 1 downto 0);
            m_axi_wvalid  : out std_logic;
            m_axi_wready  : in  std_logic;
            m_axi_wlast   : out std_logic;
            m_axi_bresp   : in  std_logic_vector(1 downto 0);
            m_axi_bvalid  : in  std_logic;
            m_axi_bready  : out std_logic;
            m_axi_araddr  : out std_logic_vector(ADDR_W - 1 downto 0);
            m_axi_arlen   : out std_logic_vector(7 downto 0);
            m_axi_arsize  : out std_logic_vector(2 downto 0);
            m_axi_arburst : out std_logic_vector(1 downto 0);
            m_axi_arvalid : out std_logic;
            m_axi_arready : in  std_logic;
            m_axi_arprot  : out std_logic_vector(2 downto 0);
            m_axi_rdata   : in  std_logic_vector(DATA_W - 1 downto 0);
            m_axi_rresp   : in  std_logic_vector(1 downto 0);
            m_axi_rvalid  : in  std_logic;
            m_axi_rready  : out std_logic;
            m_axi_rlast   : in  std_logic
        );
    end component;

    component fcapz_axi_mon_xilinx7 is
        generic (
            PROTO          : string := "AXI4LITE";
            ADDR_W         : integer := 32;
            DATA_W         : integer := 32;
            DEPTH          : integer := 1024;
            TRIG_STAGES    : integer := 4;
            STOR_QUAL      : integer := 1;
            NUM_SEGMENTS   : integer := 1;
            TIMESTAMP_W    : integer := 32;
            INPUT_PIPE     : integer := 1;
            DECIM_EN       : integer := 0;
            EXT_TRIG_EN    : integer := 0;
            STARTUP_ARM    : integer := 0;
            REL_COMPARE    : integer := 1;
            DUAL_COMPARE   : integer := 1;
            USER1_DATA_EN  : integer := 1;
            DECODE_EN      : integer := 0;
            BURST_W        : integer := 256;
            CTRL_CHAIN     : integer := 1
        );
        port (
            ACLK        : in  std_logic;
            ARESETN     : in  std_logic;
            AWADDR      : in  std_logic_vector(ADDR_W - 1 downto 0);
            AWPROT      : in  std_logic_vector(2 downto 0);
            AWVALID     : in  std_logic;
            AWREADY     : in  std_logic;
            WDATA       : in  std_logic_vector(DATA_W - 1 downto 0);
            WSTRB       : in  std_logic_vector((DATA_W / 8) - 1 downto 0);
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
            trigger_in  : in  std_logic;
            trigger_out : out std_logic;
            armed_out   : out std_logic
        );
    end component;

    component axi4_test_slave is
        generic (
            NUM_WORDS  : integer := 16;
            ERROR_ADDR : std_logic_vector(31 downto 0) := x"FFFF_FFFC"
        );
        port (
            clk           : in  std_logic;
            rst           : in  std_logic;
            s_axi_awaddr  : in  std_logic_vector(31 downto 0);
            s_axi_awlen   : in  std_logic_vector(7 downto 0);
            s_axi_awsize  : in  std_logic_vector(2 downto 0);
            s_axi_awburst : in  std_logic_vector(1 downto 0);
            s_axi_awvalid : in  std_logic;
            s_axi_awready : out std_logic;
            s_axi_wdata   : in  std_logic_vector(31 downto 0);
            s_axi_wstrb   : in  std_logic_vector(3 downto 0);
            s_axi_wvalid  : in  std_logic;
            s_axi_wready  : out std_logic;
            s_axi_wlast   : in  std_logic;
            s_axi_bresp   : out std_logic_vector(1 downto 0);
            s_axi_bvalid  : out std_logic;
            s_axi_bready  : in  std_logic;
            s_axi_araddr  : in  std_logic_vector(31 downto 0);
            s_axi_arlen   : in  std_logic_vector(7 downto 0);
            s_axi_arsize  : in  std_logic_vector(2 downto 0);
            s_axi_arburst : in  std_logic_vector(1 downto 0);
            s_axi_arvalid : in  std_logic;
            s_axi_arready : out std_logic;
            s_axi_rdata   : out std_logic_vector(31 downto 0);
            s_axi_rresp   : out std_logic_vector(1 downto 0);
            s_axi_rvalid  : out std_logic;
            s_axi_rready  : in  std_logic;
            s_axi_rlast   : out std_logic
        );
    end component;

    -- MicroBlaze subsystem block-design wrapper (Verilog, generated by
    -- make_wrapper from mb_sys.bd).  Ports mirror exactly what arty_a7_top.v
    -- connects: the M_EJTAG AXI4 slave (fed by the EJTAG bridge master) and the
    -- M_BUS AXI4 master (drives the test slave + AXI-mon tap).  Any interface
    -- ports the BD exposes but this design does not use (id/region) are left
    -- unconnected, exactly as in the Verilog top.
    component mb_sys_wrapper is
        port (
            Clk             : in  std_logic;
            reset           : in  std_logic;
            -- M_EJTAG slave (bridge master -> crossbar)
            M_EJTAG_awaddr  : in  std_logic_vector(31 downto 0);
            M_EJTAG_awlen   : in  std_logic_vector(7 downto 0);
            M_EJTAG_awsize  : in  std_logic_vector(2 downto 0);
            M_EJTAG_awburst : in  std_logic_vector(1 downto 0);
            M_EJTAG_awprot  : in  std_logic_vector(2 downto 0);
            M_EJTAG_awvalid : in  std_logic;
            M_EJTAG_awready : out std_logic;
            M_EJTAG_awcache : in  std_logic_vector(3 downto 0);
            M_EJTAG_awlock  : in  std_logic;
            M_EJTAG_awqos   : in  std_logic_vector(3 downto 0);
            M_EJTAG_wdata   : in  std_logic_vector(31 downto 0);
            M_EJTAG_wstrb   : in  std_logic_vector(3 downto 0);
            M_EJTAG_wlast   : in  std_logic;
            M_EJTAG_wvalid  : in  std_logic;
            M_EJTAG_wready  : out std_logic;
            M_EJTAG_bresp   : out std_logic_vector(1 downto 0);
            M_EJTAG_bvalid  : out std_logic;
            M_EJTAG_bready  : in  std_logic;
            M_EJTAG_araddr  : in  std_logic_vector(31 downto 0);
            M_EJTAG_arlen   : in  std_logic_vector(7 downto 0);
            M_EJTAG_arsize  : in  std_logic_vector(2 downto 0);
            M_EJTAG_arburst : in  std_logic_vector(1 downto 0);
            M_EJTAG_arprot  : in  std_logic_vector(2 downto 0);
            M_EJTAG_arvalid : in  std_logic;
            M_EJTAG_arready : out std_logic;
            M_EJTAG_arcache : in  std_logic_vector(3 downto 0);
            M_EJTAG_arlock  : in  std_logic;
            M_EJTAG_arqos   : in  std_logic_vector(3 downto 0);
            M_EJTAG_rdata   : out std_logic_vector(31 downto 0);
            M_EJTAG_rresp   : out std_logic_vector(1 downto 0);
            M_EJTAG_rlast   : out std_logic;
            M_EJTAG_rvalid  : out std_logic;
            M_EJTAG_rready  : in  std_logic;
            -- M_BUS master (-> test slave + AXI monitor tap)
            M_BUS_awaddr    : out std_logic_vector(31 downto 0);
            M_BUS_awlen     : out std_logic_vector(7 downto 0);
            M_BUS_awsize    : out std_logic_vector(2 downto 0);
            M_BUS_awburst   : out std_logic_vector(1 downto 0);
            M_BUS_awprot    : out std_logic_vector(2 downto 0);
            M_BUS_awvalid   : out std_logic;
            M_BUS_awready   : in  std_logic;
            M_BUS_awcache   : out std_logic_vector(3 downto 0);
            M_BUS_awlock    : out std_logic;
            M_BUS_awqos     : out std_logic_vector(3 downto 0);
            M_BUS_wdata     : out std_logic_vector(31 downto 0);
            M_BUS_wstrb     : out std_logic_vector(3 downto 0);
            M_BUS_wlast     : out std_logic;
            M_BUS_wvalid    : out std_logic;
            M_BUS_wready    : in  std_logic;
            M_BUS_bresp     : in  std_logic_vector(1 downto 0);
            M_BUS_bvalid    : in  std_logic;
            M_BUS_bready    : out std_logic;
            M_BUS_araddr    : out std_logic_vector(31 downto 0);
            M_BUS_arlen     : out std_logic_vector(7 downto 0);
            M_BUS_arsize    : out std_logic_vector(2 downto 0);
            M_BUS_arburst   : out std_logic_vector(1 downto 0);
            M_BUS_arprot    : out std_logic_vector(2 downto 0);
            M_BUS_arvalid   : out std_logic;
            M_BUS_arready   : in  std_logic;
            M_BUS_arcache   : out std_logic_vector(3 downto 0);
            M_BUS_arlock    : out std_logic;
            M_BUS_arqos     : out std_logic_vector(3 downto 0);
            M_BUS_rdata     : in  std_logic_vector(31 downto 0);
            M_BUS_rresp     : in  std_logic_vector(1 downto 0);
            M_BUS_rlast     : in  std_logic;
            M_BUS_rvalid    : in  std_logic;
            M_BUS_rready    : out std_logic
        );
    end component;

    signal clk_150        : std_logic;
    signal clk_130        : std_logic;
    signal clk_150_raw    : std_logic;
    signal clk_130_raw    : std_logic;
    signal clk150_fb      : std_logic;
    signal clk150_fb_buf  : std_logic;
    signal clk130_fb      : std_logic;
    signal clk130_fb_buf  : std_logic;
    signal clk150_locked  : std_logic;
    signal clk130_locked  : std_logic;
    signal rst_150_async  : std_logic;
    signal rst_130_async  : std_logic;
    signal rst_150        : std_logic;
    signal rst_130        : std_logic;
    signal rst150_pipe    : std_logic_vector(3 downto 0) := (others => '1');
    signal rst130_pipe    : std_logic_vector(3 downto 0) := (others => '1');

    -- 100 MHz AXI subsystem domain (MicroBlaze + shared bus + monitor), buffered
    -- straight off the 100 MHz board oscillator, mirroring arty_a7_top.v.
    signal clk_100        : std_logic;
    signal rst_100_async  : std_logic;
    signal rst_100        : std_logic;
    signal rst100_pipe    : std_logic_vector(3 downto 0) := (others => '1');

    signal counter_150       : unsigned(SAMPLE_W - 1 downto 0) := (others => '0');
    signal counter_130       : unsigned(SAMPLE_W - 1 downto 0) := (others => '0');
    signal slow_counter      : unsigned(3 downto 0) := (others => '0');
    signal sec_divider       : natural range 0 to CLK150_HZ - 1 := 0;
    signal trigger_in_w      : std_logic_vector(1 downto 0);
    signal trigger_out_w     : std_logic_vector(1 downto 0);
    signal ela_armed_w       : std_logic_vector(1 downto 0);
    signal eio0_probe_in     : std_logic_vector(7 downto 0);
    signal eio0_probe_out    : std_logic_vector(7 downto 0);
    signal eio1_probe_in     : std_logic_vector(7 downto 0);
    signal eio1_probe_out    : std_logic_vector(7 downto 0);
    signal eio_probe_out_all : std_logic_vector(15 downto 0);
    signal eio_out_sync1     : std_logic_vector(7 downto 0) := (others => '0');
    signal eio_out_sync2     : std_logic_vector(7 downto 0) := (others => '0');
    signal ela_pretrigger_d  : std_logic := '0';
    signal armed_test_count  : unsigned(3 downto 0) := (others => '0');
    signal armed_test_active : std_logic := '0';
    signal armed_test_pulse  : std_logic := '0';
    signal armed_test_gate   : std_logic := '0';
    signal led_sync1         : std_logic_vector(3 downto 0) := (others => '0');
    signal led_sync2         : std_logic_vector(3 downto 0) := (others => '0');

    signal bridge_awaddr  : std_logic_vector(31 downto 0);
    signal bridge_wdata   : std_logic_vector(31 downto 0);
    signal bridge_araddr  : std_logic_vector(31 downto 0);
    signal bridge_rdata   : std_logic_vector(31 downto 0);
    signal bridge_awlen   : std_logic_vector(7 downto 0);
    signal bridge_arlen   : std_logic_vector(7 downto 0);
    signal bridge_awsize  : std_logic_vector(2 downto 0);
    signal bridge_arsize  : std_logic_vector(2 downto 0);
    signal bridge_awprot  : std_logic_vector(2 downto 0);
    signal bridge_arprot  : std_logic_vector(2 downto 0);
    signal bridge_awburst : std_logic_vector(1 downto 0);
    signal bridge_arburst : std_logic_vector(1 downto 0);
    signal bridge_bresp   : std_logic_vector(1 downto 0);
    signal bridge_rresp   : std_logic_vector(1 downto 0);
    signal bridge_wstrb   : std_logic_vector(3 downto 0);
    signal bridge_awvalid : std_logic;
    signal bridge_awready : std_logic;
    signal bridge_wvalid  : std_logic;
    signal bridge_wready  : std_logic;
    signal bridge_wlast   : std_logic;
    signal bridge_bvalid  : std_logic;
    signal bridge_bready  : std_logic;
    signal bridge_arvalid : std_logic;
    signal bridge_arready : std_logic;
    signal bridge_rvalid  : std_logic;
    signal bridge_rready  : std_logic;
    signal bridge_rlast   : std_logic;

    -- Shared bus: MicroBlaze M_AXI_DP + EJTAG bridge merged by the in-BD
    -- SmartConnect; drives the test slave and is tapped by the AXI monitor.
    signal mbus_awaddr    : std_logic_vector(31 downto 0);
    signal mbus_wdata     : std_logic_vector(31 downto 0);
    signal mbus_araddr    : std_logic_vector(31 downto 0);
    signal mbus_rdata     : std_logic_vector(31 downto 0);
    signal mbus_awlen     : std_logic_vector(7 downto 0);
    signal mbus_arlen     : std_logic_vector(7 downto 0);
    signal mbus_awsize    : std_logic_vector(2 downto 0);
    signal mbus_arsize    : std_logic_vector(2 downto 0);
    signal mbus_awprot    : std_logic_vector(2 downto 0);
    signal mbus_arprot    : std_logic_vector(2 downto 0);
    signal mbus_awburst   : std_logic_vector(1 downto 0);
    signal mbus_arburst   : std_logic_vector(1 downto 0);
    signal mbus_bresp     : std_logic_vector(1 downto 0);
    signal mbus_rresp     : std_logic_vector(1 downto 0);
    signal mbus_wstrb     : std_logic_vector(3 downto 0);
    signal mbus_awvalid   : std_logic;
    signal mbus_awready   : std_logic;
    signal mbus_wvalid    : std_logic;
    signal mbus_wready    : std_logic;
    signal mbus_wlast     : std_logic;
    signal mbus_bvalid    : std_logic;
    signal mbus_bready    : std_logic;
    signal mbus_arvalid   : std_logic;
    signal mbus_arready   : std_logic;
    signal mbus_rvalid    : std_logic;
    signal mbus_rready    : std_logic;
    signal mbus_rlast     : std_logic;
begin
    u_mmcm_150 : MMCME2_BASE
        generic map (
            BANDWIDTH => "OPTIMIZED",
            CLKFBOUT_MULT_F => 9.0,
            CLKFBOUT_PHASE => 0.0,
            CLKIN1_PERIOD => 10.000,
            CLKOUT0_DIVIDE_F => 6.0,
            CLKOUT0_DUTY_CYCLE => 0.5,
            CLKOUT0_PHASE => 0.0,
            DIVCLK_DIVIDE => 1,
            REF_JITTER1 => 0.010,
            STARTUP_WAIT => "FALSE"
        )
        port map (
            CLKIN1 => clk,
            CLKFBIN => clk150_fb_buf,
            CLKFBOUT => clk150_fb,
            CLKFBOUTB => open,
            CLKOUT0 => clk_150_raw,
            CLKOUT0B => open,
            CLKOUT1 => open,
            CLKOUT1B => open,
            CLKOUT2 => open,
            CLKOUT2B => open,
            CLKOUT3 => open,
            CLKOUT3B => open,
            CLKOUT4 => open,
            CLKOUT5 => open,
            CLKOUT6 => open,
            LOCKED => clk150_locked,
            PWRDWN => '0',
            RST => btn(0)
        );

    u_mmcm_130 : MMCME2_BASE
        generic map (
            BANDWIDTH => "OPTIMIZED",
            CLKFBOUT_MULT_F => 6.5,
            CLKFBOUT_PHASE => 0.0,
            CLKIN1_PERIOD => 10.000,
            CLKOUT0_DIVIDE_F => 5.0,
            CLKOUT0_DUTY_CYCLE => 0.5,
            CLKOUT0_PHASE => 0.0,
            DIVCLK_DIVIDE => 1,
            REF_JITTER1 => 0.010,
            STARTUP_WAIT => "FALSE"
        )
        port map (
            CLKIN1 => clk,
            CLKFBIN => clk130_fb_buf,
            CLKFBOUT => clk130_fb,
            CLKFBOUTB => open,
            CLKOUT0 => clk_130_raw,
            CLKOUT0B => open,
            CLKOUT1 => open,
            CLKOUT1B => open,
            CLKOUT2 => open,
            CLKOUT2B => open,
            CLKOUT3 => open,
            CLKOUT3B => open,
            CLKOUT4 => open,
            CLKOUT5 => open,
            CLKOUT6 => open,
            LOCKED => clk130_locked,
            PWRDWN => '0',
            RST => btn(0)
        );

    u_clk150_fb_buf : BUFG port map (I => clk150_fb, O => clk150_fb_buf);
    u_clk150_buf    : BUFG port map (I => clk_150_raw, O => clk_150);
    u_clk130_fb_buf : BUFG port map (I => clk130_fb, O => clk130_fb_buf);
    u_clk130_buf    : BUFG port map (I => clk_130_raw, O => clk_130);

    -- 100 MHz AXI subsystem clock: the Arty oscillator is already 100 MHz, so
    -- buffer it directly.  Reset uses the 150 MHz MMCM lock as a power-up-done
    -- proxy plus btn(0) as a manual reset (mirrors arty_a7_top.v).
    u_clk100_buf : BUFG port map (I => clk, O => clk_100);
    rst_100_async <= btn(0) or not clk150_locked;
    p_reset_100 : process(clk_100, rst_100_async)
    begin
        if rst_100_async = '1' then
            rst100_pipe <= (others => '1');
        elsif rising_edge(clk_100) then
            rst100_pipe <= rst100_pipe(2 downto 0) & '0';
        end if;
    end process;
    rst_100 <= rst100_pipe(3);

    eio0_probe_in <= btn & std_logic_vector(slow_counter);
    eio1_probe_in <= std_logic_vector(counter_130(3 downto 0)) & btn;
    rst_150_async <= btn(0) or not clk150_locked;
    rst_130_async <= btn(0) or not clk130_locked;

    p_reset_150 : process(clk_150, rst_150_async)
    begin
        if rst_150_async = '1' then
            rst150_pipe <= (others => '1');
        elsif rising_edge(clk_150) then
            rst150_pipe <= rst150_pipe(2 downto 0) & '0';
        end if;
    end process;
    rst_150 <= rst150_pipe(3);

    p_reset_130 : process(clk_130, rst_130_async)
    begin
        if rst_130_async = '1' then
            rst130_pipe <= (others => '1');
        elsif rising_edge(clk_130) then
            rst130_pipe <= rst130_pipe(2 downto 0) & '0';
        end if;
    end process;
    rst_130 <= rst130_pipe(3);

    p_counter_150 : process(clk_150)
    begin
        if rising_edge(clk_150) then
            if rst_150 = '1' then
                counter_150 <= (others => '0');
            else
                counter_150 <= counter_150 + 1;
            end if;
        end if;
    end process;

    p_counter_130 : process(clk_130)
    begin
        if rising_edge(clk_130) then
            if rst_130 = '1' then
                counter_130 <= (others => '0');
            else
                counter_130 <= counter_130 + 1;
            end if;
        end if;
    end process;

    p_slow_counter : process(clk_150)
    begin
        if rising_edge(clk_150) then
            if rst_150 = '1' then
                sec_divider <= 0;
                slow_counter <= (others => '0');
            elsif sec_divider = CLK150_HZ - 1 then
                sec_divider <= 0;
                slow_counter <= slow_counter + 1;
            else
                sec_divider <= sec_divider + 1;
            end if;
        end if;
    end process;

    p_eio_sync : process(clk_150)
    begin
        if rising_edge(clk_150) then
            if rst_150 = '1' then
                eio_out_sync1 <= (others => '0');
                eio_out_sync2 <= (others => '0');
            else
                eio_out_sync1 <= eio0_probe_out;
                eio_out_sync2 <= eio_out_sync1;
            end if;
        end if;
    end process;

    p_trigger_helper : process(clk_150)
    begin
        if rising_edge(clk_150) then
            if rst_150 = '1' then
                ela_pretrigger_d <= '0';
                armed_test_count <= (others => '0');
                armed_test_active <= '0';
                armed_test_pulse <= '0';
                armed_test_gate <= '0';
            else
                ela_pretrigger_d <= ela_armed_w(0);
                armed_test_pulse <= '0';

                if ela_armed_w(0) = '1' and ela_pretrigger_d = '0' then
                    armed_test_count <= (others => '0');
                    armed_test_active <= eio_out_sync2(6);
                    if eio_out_sync2(5) = '1' then
                        armed_test_pulse <= '1';
                    end if;
                    armed_test_gate <= '0';
                elsif ela_armed_w(0) = '0' then
                    armed_test_count <= (others => '0');
                    armed_test_active <= '0';
                    armed_test_gate <= '0';
                elsif armed_test_active = '1' then
                    armed_test_count <= armed_test_count + 1;
                    if eio_out_sync2(6) = '1' and armed_test_count = to_unsigned(7, armed_test_count'length) then
                        armed_test_gate <= '1';
                    end if;
                    if armed_test_count = to_unsigned(7, armed_test_count'length) then
                        armed_test_active <= '0';
                    end if;
                end if;
            end if;
        end if;
    end process;

    trigger_in_w <= '0' & (eio_out_sync2(4) or armed_test_pulse or armed_test_gate);

    u_debug : fcapz_debug_multi_xilinx7
        generic map (
            NUM_ELAS => 2,
            EIO_EN => 1,
            NUM_EIOS => 2,
            SAMPLE_W => SAMPLE_W,
            DEPTH => DEPTH,
            INPUT_PIPE => 1,
            DECIM_EN => 1,
            EXT_TRIG_EN => 1,
            TIMESTAMP_W => 32,
            NUM_SEGMENTS => NUM_SEGMENTS,
            STARTUP_ARM => 1,
            DEFAULT_TRIG_EXT => 2,
            EIO_IN_W => 8,
            EIO_OUT_W => 8
        )
        port map (
            ela_sample_clk => clk_130 & clk_150,
            ela_sample_rst => rst_130 & rst_150,
            ela_probe_in => (std_logic_vector(counter_130) xor x"A5") & std_logic_vector(counter_150),
            ela_trigger_in => trigger_in_w,
            ela_trigger_out => trigger_out_w,
            ela_armed_out => ela_armed_w,
            eio_probe_in => eio1_probe_in & eio0_probe_in,
            eio_probe_out => eio_probe_out_all
        );

    eio1_probe_out <= eio_probe_out_all(15 downto 8);
    eio0_probe_out <= eio_probe_out_all(7 downto 0);

    u_ejtagaxi : fcapz_ejtagaxi_xilinx7
        generic map (
            ADDR_W => 32,
            DATA_W => 32,
            FIFO_DEPTH => 16,
            CMD_FIFO_DEPTH => 16,
            RESP_FIFO_DEPTH => 16,
            CMD_FIFO_MEMORY_TYPE => "distributed",
            TIMEOUT => 4096,
            DEBUG_EN => 0
        )
        port map (
            axi_clk => clk_100,
            axi_rst => rst_100,
            m_axi_awaddr => bridge_awaddr,
            m_axi_awlen => bridge_awlen,
            m_axi_awsize => bridge_awsize,
            m_axi_awburst => bridge_awburst,
            m_axi_awvalid => bridge_awvalid,
            m_axi_awready => bridge_awready,
            m_axi_awprot => bridge_awprot,
            m_axi_wdata => bridge_wdata,
            m_axi_wstrb => bridge_wstrb,
            m_axi_wvalid => bridge_wvalid,
            m_axi_wready => bridge_wready,
            m_axi_wlast => bridge_wlast,
            m_axi_bresp => bridge_bresp,
            m_axi_bvalid => bridge_bvalid,
            m_axi_bready => bridge_bready,
            m_axi_araddr => bridge_araddr,
            m_axi_arlen => bridge_arlen,
            m_axi_arsize => bridge_arsize,
            m_axi_arburst => bridge_arburst,
            m_axi_arvalid => bridge_arvalid,
            m_axi_arready => bridge_arready,
            m_axi_arprot => bridge_arprot,
            m_axi_rdata => bridge_rdata,
            m_axi_rresp => bridge_rresp,
            m_axi_rvalid => bridge_rvalid,
            m_axi_rready => bridge_rready,
            m_axi_rlast => bridge_rlast
        );

    -- MicroBlaze subsystem: microblaze_0's M_AXI_DP data master and the EJTAG
    -- bridge master (above) are merged by an in-BD SmartConnect onto the shared
    -- bus M_BUS, which drives the test slave and is passively tapped by the AXI
    -- monitor.  The MicroBlaze Debug Module sits on the free USER3 BSCAN tap.
    -- Firmware baked into the LMB BRAM writes a known pattern to the shared
    -- slave when the host raises a go-flag, giving the monitor real CPU traffic.
    -- Unused master qualifier outputs (awcache/awlock/awqos/...) are left open;
    -- the bridge-side qualifiers the EJTAG master does not drive are tied off.
    u_mb_sys : mb_sys_wrapper
        port map (
            Clk   => clk_100,
            reset => rst_100,
            M_EJTAG_awaddr  => bridge_awaddr,
            M_EJTAG_awlen   => bridge_awlen,
            M_EJTAG_awsize  => bridge_awsize,
            M_EJTAG_awburst => bridge_awburst,
            M_EJTAG_awprot  => bridge_awprot,
            M_EJTAG_awvalid => bridge_awvalid,
            M_EJTAG_awready => bridge_awready,
            M_EJTAG_awcache => "0011",
            M_EJTAG_awlock  => '0',
            M_EJTAG_awqos   => "0000",
            M_EJTAG_wdata   => bridge_wdata,
            M_EJTAG_wstrb   => bridge_wstrb,
            M_EJTAG_wlast   => bridge_wlast,
            M_EJTAG_wvalid  => bridge_wvalid,
            M_EJTAG_wready  => bridge_wready,
            M_EJTAG_bresp   => bridge_bresp,
            M_EJTAG_bvalid  => bridge_bvalid,
            M_EJTAG_bready  => bridge_bready,
            M_EJTAG_araddr  => bridge_araddr,
            M_EJTAG_arlen   => bridge_arlen,
            M_EJTAG_arsize  => bridge_arsize,
            M_EJTAG_arburst => bridge_arburst,
            M_EJTAG_arprot  => bridge_arprot,
            M_EJTAG_arvalid => bridge_arvalid,
            M_EJTAG_arready => bridge_arready,
            M_EJTAG_arcache => "0011",
            M_EJTAG_arlock  => '0',
            M_EJTAG_arqos   => "0000",
            M_EJTAG_rdata   => bridge_rdata,
            M_EJTAG_rresp   => bridge_rresp,
            M_EJTAG_rlast   => bridge_rlast,
            M_EJTAG_rvalid  => bridge_rvalid,
            M_EJTAG_rready  => bridge_rready,
            M_BUS_awaddr    => mbus_awaddr,
            M_BUS_awlen     => mbus_awlen,
            M_BUS_awsize    => mbus_awsize,
            M_BUS_awburst   => mbus_awburst,
            M_BUS_awprot    => mbus_awprot,
            M_BUS_awvalid   => mbus_awvalid,
            M_BUS_awready   => mbus_awready,
            M_BUS_awcache   => open,
            M_BUS_awlock    => open,
            M_BUS_awqos     => open,
            M_BUS_wdata     => mbus_wdata,
            M_BUS_wstrb     => mbus_wstrb,
            M_BUS_wlast     => mbus_wlast,
            M_BUS_wvalid    => mbus_wvalid,
            M_BUS_wready    => mbus_wready,
            M_BUS_bresp     => mbus_bresp,
            M_BUS_bvalid    => mbus_bvalid,
            M_BUS_bready    => mbus_bready,
            M_BUS_araddr    => mbus_araddr,
            M_BUS_arlen     => mbus_arlen,
            M_BUS_arsize    => mbus_arsize,
            M_BUS_arburst   => mbus_arburst,
            M_BUS_arprot    => mbus_arprot,
            M_BUS_arvalid   => mbus_arvalid,
            M_BUS_arready   => mbus_arready,
            M_BUS_arcache   => open,
            M_BUS_arlock    => open,
            M_BUS_arqos     => open,
            M_BUS_rdata     => mbus_rdata,
            M_BUS_rresp     => mbus_rresp,
            M_BUS_rlast     => mbus_rlast,
            M_BUS_rvalid    => mbus_rvalid,
            M_BUS_rready    => mbus_rready
        );

    -- Test slave on the shared bus.  32 words so the CPU firmware (words 16+)
    -- never collides with EJTAG host tests (words 0..15).
    u_axi_slave : axi4_test_slave
        generic map (
            NUM_WORDS => 32,
            ERROR_ADDR => x"FFFF_FFFC"
        )
        port map (
            clk => clk_100,
            rst => rst_100,
            s_axi_awaddr => mbus_awaddr,
            s_axi_awlen => mbus_awlen,
            s_axi_awsize => mbus_awsize,
            s_axi_awburst => mbus_awburst,
            s_axi_awvalid => mbus_awvalid,
            s_axi_awready => mbus_awready,
            s_axi_wdata => mbus_wdata,
            s_axi_wstrb => mbus_wstrb,
            s_axi_wvalid => mbus_wvalid,
            s_axi_wready => mbus_wready,
            s_axi_wlast => mbus_wlast,
            s_axi_bresp => mbus_bresp,
            s_axi_bvalid => mbus_bvalid,
            s_axi_bready => mbus_bready,
            s_axi_araddr => mbus_araddr,
            s_axi_arlen => mbus_arlen,
            s_axi_arsize => mbus_arsize,
            s_axi_arburst => mbus_arburst,
            s_axi_arvalid => mbus_arvalid,
            s_axi_arready => mbus_arready,
            s_axi_rdata => mbus_rdata,
            s_axi_rresp => mbus_rresp,
            s_axi_rvalid => mbus_rvalid,
            s_axi_rready => mbus_rready,
            s_axi_rlast => mbus_rlast
        );

    u_axi_mon : fcapz_axi_mon_xilinx7
        generic map (
            ADDR_W => 32,
            DATA_W => 32,
            DEPTH => 256,
            TRIG_STAGES => 1,
            STOR_QUAL => 0,
            TIMESTAMP_W => 0,
            INPUT_PIPE => 1,
            REL_COMPARE => 0,
            DECODE_EN => 1,
            CTRL_CHAIN => 2
        )
        port map (
            ACLK => clk_100,
            ARESETN => not rst_100,
            AWADDR => mbus_awaddr,
            AWPROT => mbus_awprot,
            AWVALID => mbus_awvalid,
            AWREADY => mbus_awready,
            WDATA => mbus_wdata,
            WSTRB => mbus_wstrb,
            WVALID => mbus_wvalid,
            WREADY => mbus_wready,
            BRESP => mbus_bresp,
            BVALID => mbus_bvalid,
            BREADY => mbus_bready,
            ARADDR => mbus_araddr,
            ARPROT => mbus_arprot,
            ARVALID => mbus_arvalid,
            ARREADY => mbus_arready,
            RDATA => mbus_rdata,
            RRESP => mbus_rresp,
            RVALID => mbus_rvalid,
            RREADY => mbus_rready,
            trigger_in => '0',
            trigger_out => open,
            armed_out => open
        );

    p_led_sync : process(clk_150)
    begin
        if rising_edge(clk_150) then
            if rst_150 = '1' then
                led_sync1 <= (others => '0');
                led_sync2 <= (others => '0');
            else
                led_sync1 <= eio_out_sync2(3 downto 0);
                led_sync2 <= led_sync1;
            end if;
        end if;
    end process;
    led <= led_sync2;
end architecture rtl;
