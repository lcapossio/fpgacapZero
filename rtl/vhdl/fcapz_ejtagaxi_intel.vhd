-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ejtagaxi_intel is
    generic (
        ADDR_W                 : positive := 32;
        DATA_W                 : positive := 32;
        FIFO_DEPTH             : positive := 16;
        CMD_FIFO_DEPTH         : positive := 32;
        RESP_FIFO_DEPTH        : positive := 32;
        TIMEOUT                : natural := 4096;
        DEBUG_EN               : natural := 0;
        CMD_FIFO_MEMORY_TYPE   : string := "auto";
        RESP_FIFO_MEMORY_TYPE  : string := "auto";
        BURST_FIFO_MEMORY_TYPE : string := "auto";
        ASYNC_FIFO_IMPL        : natural := 0;
        CHAIN                  : positive := 4
    );
    port (
        axi_clk : in  std_logic;
        axi_rst : in  std_logic;
        m_axi_awaddr  : out std_logic_vector(ADDR_W - 1 downto 0);
        m_axi_awlen   : out std_logic_vector(7 downto 0);
        m_axi_awsize  : out std_logic_vector(2 downto 0);
        m_axi_awburst : out std_logic_vector(1 downto 0);
        m_axi_awvalid : out std_logic;
        m_axi_awready : in  std_logic;
        m_axi_awprot  : out std_logic_vector(2 downto 0);
        m_axi_wdata   : out std_logic_vector(DATA_W - 1 downto 0);
        m_axi_wstrb   : out std_logic_vector(DATA_W / 8 - 1 downto 0);
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
        m_axi_rlast   : in  std_logic;
        m_axi_rready  : out std_logic;
        debug_tck      : out std_logic_vector(255 downto 0);
        debug_tck_edge : out std_logic_vector(255 downto 0);
        debug_axi      : out std_logic_vector(255 downto 0);
        debug_axi_edge : out std_logic_vector(255 downto 0)
    );
end entity fcapz_ejtagaxi_intel;

architecture rtl of fcapz_ejtagaxi_intel is
    component fcapz_ejtagaxi_intel_v is
        generic (
            ADDR_W                 : positive;
            DATA_W                 : positive;
            FIFO_DEPTH             : positive;
            CMD_FIFO_DEPTH         : positive;
            RESP_FIFO_DEPTH        : positive;
            TIMEOUT                : natural;
            DEBUG_EN               : natural;
            CMD_FIFO_MEMORY_TYPE   : string;
            RESP_FIFO_MEMORY_TYPE  : string;
            BURST_FIFO_MEMORY_TYPE : string;
            ASYNC_FIFO_IMPL        : natural;
            CHAIN                  : positive
        );
        port (
            axi_clk : in  std_logic;
            axi_rst : in  std_logic;
            m_axi_awaddr  : out std_logic_vector(ADDR_W - 1 downto 0);
            m_axi_awlen   : out std_logic_vector(7 downto 0);
            m_axi_awsize  : out std_logic_vector(2 downto 0);
            m_axi_awburst : out std_logic_vector(1 downto 0);
            m_axi_awvalid : out std_logic;
            m_axi_awready : in  std_logic;
            m_axi_awprot  : out std_logic_vector(2 downto 0);
            m_axi_wdata   : out std_logic_vector(DATA_W - 1 downto 0);
            m_axi_wstrb   : out std_logic_vector(DATA_W / 8 - 1 downto 0);
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
            m_axi_rlast   : in  std_logic;
            m_axi_rready  : out std_logic;
            debug_tck      : out std_logic_vector(255 downto 0);
            debug_tck_edge : out std_logic_vector(255 downto 0);
            debug_axi      : out std_logic_vector(255 downto 0);
            debug_axi_edge : out std_logic_vector(255 downto 0)
        );
    end component;
begin
    u_impl : fcapz_ejtagaxi_intel_v
        generic map (
            ADDR_W => ADDR_W, DATA_W => DATA_W,
            FIFO_DEPTH => FIFO_DEPTH, CMD_FIFO_DEPTH => CMD_FIFO_DEPTH,
            RESP_FIFO_DEPTH => RESP_FIFO_DEPTH, TIMEOUT => TIMEOUT,
            DEBUG_EN => DEBUG_EN, CMD_FIFO_MEMORY_TYPE => CMD_FIFO_MEMORY_TYPE,
            RESP_FIFO_MEMORY_TYPE => RESP_FIFO_MEMORY_TYPE,
            BURST_FIFO_MEMORY_TYPE => BURST_FIFO_MEMORY_TYPE,
            ASYNC_FIFO_IMPL => ASYNC_FIFO_IMPL, CHAIN => CHAIN
        )
        port map (
            axi_clk => axi_clk, axi_rst => axi_rst,
            m_axi_awaddr => m_axi_awaddr, m_axi_awlen => m_axi_awlen,
            m_axi_awsize => m_axi_awsize, m_axi_awburst => m_axi_awburst,
            m_axi_awvalid => m_axi_awvalid, m_axi_awready => m_axi_awready,
            m_axi_awprot => m_axi_awprot,
            m_axi_wdata => m_axi_wdata, m_axi_wstrb => m_axi_wstrb,
            m_axi_wvalid => m_axi_wvalid, m_axi_wready => m_axi_wready,
            m_axi_wlast => m_axi_wlast,
            m_axi_bresp => m_axi_bresp, m_axi_bvalid => m_axi_bvalid,
            m_axi_bready => m_axi_bready,
            m_axi_araddr => m_axi_araddr, m_axi_arlen => m_axi_arlen,
            m_axi_arsize => m_axi_arsize, m_axi_arburst => m_axi_arburst,
            m_axi_arvalid => m_axi_arvalid, m_axi_arready => m_axi_arready,
            m_axi_arprot => m_axi_arprot,
            m_axi_rdata => m_axi_rdata, m_axi_rresp => m_axi_rresp,
            m_axi_rvalid => m_axi_rvalid, m_axi_rlast => m_axi_rlast,
            m_axi_rready => m_axi_rready,
            debug_tck => debug_tck, debug_tck_edge => debug_tck_edge,
            debug_axi => debug_axi, debug_axi_edge => debug_axi_edge
        );
end architecture rtl;
