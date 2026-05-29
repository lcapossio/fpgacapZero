-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- fpgacapZero ELA wrapper for Intel / Altera (VHDL).
--
-- Thin VHDL wrapper over the Verilog fcapz_ela_intel module.
-- Instantiate this entity in VHDL designs; the underlying Verilog
-- source files must still be included in the project.
--
-- Usage:
--   u_ela : entity work.fcapz_ela_intel
--       generic map (SAMPLE_W => 8, DEPTH => 1024)
--       port map (
--           sample_clk => clk, sample_rst => rst, probe_in => signals,
--           trigger_in => '0', trigger_out => open, armed_out => open
--       );

library ieee;
use ieee.std_logic_1164.all;

entity fcapz_ela_intel is
    generic (
        SAMPLE_W     : positive := 8;
        DEPTH        : positive := 1024;
        TRIG_STAGES  : positive := 1;
        STOR_QUAL    : natural  := 0;
        INPUT_PIPE   : natural  := 0;
        NUM_CHANNELS : positive := 1;
        DECIM_EN     : natural  := 0;
        EXT_TRIG_EN  : natural  := 0;
        TIMESTAMP_W  : natural  := 0;
        NUM_SEGMENTS : positive := 1;
        PROBE_MUX_W  : natural  := 0;
        STARTUP_ARM  : natural  := 0;
        DEFAULT_TRIG_EXT : natural := 0;
        BURST_W      : positive := 256;
        CTRL_CHAIN   : positive := 1;
        DATA_CHAIN   : positive := 2
    );
    port (
        sample_clk : in  std_logic;
        sample_rst : in  std_logic;
        probe_in   : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0);
        trigger_in : in  std_logic := '0';
        trigger_out : out std_logic;
        armed_out   : out std_logic
    );
end entity fcapz_ela_intel;

architecture rtl of fcapz_ela_intel is

    component fcapz_ela_intel_v is
        generic (
            SAMPLE_W     : positive;
            DEPTH        : positive;
            TRIG_STAGES  : positive;
            STOR_QUAL    : natural;
            INPUT_PIPE   : natural;
            NUM_CHANNELS : positive;
            DECIM_EN     : natural;
            EXT_TRIG_EN  : natural;
            TIMESTAMP_W  : natural;
            NUM_SEGMENTS : positive;
            PROBE_MUX_W  : natural;
            STARTUP_ARM  : natural;
            DEFAULT_TRIG_EXT : natural;
            BURST_W      : positive;
            CTRL_CHAIN   : positive;
            DATA_CHAIN   : positive
        );
        port (
            sample_clk : in  std_logic;
            sample_rst : in  std_logic;
            probe_in   : in  std_logic_vector(SAMPLE_W * NUM_CHANNELS - 1 downto 0);
            trigger_in : in  std_logic;
            trigger_out : out std_logic;
            armed_out   : out std_logic
        );
    end component;

    -- Note: The component name uses a "_v" suffix to disambiguate from
    -- this VHDL entity.  In your synthesis tool, map fcapz_ela_intel_v
    -- to the Verilog module fcapz_ela_intel (most tools do this
    -- automatically when both sources are added to the project).

begin

    u_impl : fcapz_ela_intel_v
        generic map (
            SAMPLE_W     => SAMPLE_W,
            DEPTH        => DEPTH,
            TRIG_STAGES  => TRIG_STAGES,
            STOR_QUAL    => STOR_QUAL,
            INPUT_PIPE   => INPUT_PIPE,
            NUM_CHANNELS => NUM_CHANNELS,
            DECIM_EN     => DECIM_EN,
            EXT_TRIG_EN  => EXT_TRIG_EN,
            TIMESTAMP_W  => TIMESTAMP_W,
            NUM_SEGMENTS => NUM_SEGMENTS,
            PROBE_MUX_W  => PROBE_MUX_W,
            STARTUP_ARM  => STARTUP_ARM,
            DEFAULT_TRIG_EXT => DEFAULT_TRIG_EXT,
            BURST_W      => BURST_W,
            CTRL_CHAIN   => CTRL_CHAIN,
            DATA_CHAIN   => DATA_CHAIN
        )
        port map (
            sample_clk => sample_clk,
            sample_rst => sample_rst,
            probe_in   => probe_in,
            trigger_in => trigger_in,
            trigger_out => trigger_out,
            armed_out   => armed_out
        );

end architecture rtl;
