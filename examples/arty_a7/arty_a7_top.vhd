-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Arty A7-100T mixed-language VHDL-core hardware-validation top-level.
--
-- Topology intentionally mirrors arty_a7_top.v: two managed ELAs plus two
-- managed EIOs share USER1 through fcapz_debug_multi_xilinx7, while EJTAG-AXI
-- remains on USER4. The VHDL build omits rtl/fcapz_ela.v and rtl/fcapz_eio.v,
-- so the Verilog manager binds those core instances to the translated VHDL
-- entities in rtl/vhdl/core.

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

    attribute ASYNC_REG : string;
    attribute ASYNC_REG of led_sync1 : signal is "TRUE";
    attribute ASYNC_REG of led_sync2 : signal is "TRUE";

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
            axi_clk => clk_150,
            axi_rst => rst_150,
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

    u_axi_slave : axi4_test_slave
        generic map (
            NUM_WORDS => 16,
            ERROR_ADDR => x"FFFF_FFFC"
        )
        port map (
            clk => clk_150,
            rst => rst_150,
            s_axi_awaddr => bridge_awaddr,
            s_axi_awlen => bridge_awlen,
            s_axi_awsize => bridge_awsize,
            s_axi_awburst => bridge_awburst,
            s_axi_awvalid => bridge_awvalid,
            s_axi_awready => bridge_awready,
            s_axi_wdata => bridge_wdata,
            s_axi_wstrb => bridge_wstrb,
            s_axi_wvalid => bridge_wvalid,
            s_axi_wready => bridge_wready,
            s_axi_wlast => bridge_wlast,
            s_axi_bresp => bridge_bresp,
            s_axi_bvalid => bridge_bvalid,
            s_axi_bready => bridge_bready,
            s_axi_araddr => bridge_araddr,
            s_axi_arlen => bridge_arlen,
            s_axi_arsize => bridge_arsize,
            s_axi_arburst => bridge_arburst,
            s_axi_arvalid => bridge_arvalid,
            s_axi_arready => bridge_arready,
            s_axi_rdata => bridge_rdata,
            s_axi_rresp => bridge_rresp,
            s_axi_rvalid => bridge_rvalid,
            s_axi_rready => bridge_rready,
            s_axi_rlast => bridge_rlast
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
