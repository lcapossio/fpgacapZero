-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Efinix Trion / Titanium JTAG User TAP adapter (VHDL parity of
-- jtag_tap_efinix.v). The Efinix JTAG User TAP is configured in the Efinity
-- Interface Designer and surfaces as top-level ports, so this is a thin
-- name-mapping adapter rather than a primitive wrapper. See the Verilog module
-- header for the full signal mapping and hardware-validation note.

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_efinix is
    port (
        -- Efinix JTAG User TAP block signals (from the Interface Designer)
        user_tck     : in  std_logic;
        user_drck    : in  std_logic;   -- gated DR clock -- unused
        user_tdi     : in  std_logic;
        user_tdo     : out std_logic;
        user_capture : in  std_logic;
        user_shift   : in  std_logic;
        user_update  : in  std_logic;
        user_sel     : in  std_logic;

        -- fpgacapZero TAP interface
        tck     : out std_logic;
        tdi     : out std_logic;
        tdo     : in  std_logic;
        capture : out std_logic;
        shift   : out std_logic;
        update  : out std_logic;
        sel     : out std_logic
    );
end entity jtag_tap_efinix;

architecture rtl of jtag_tap_efinix is
    signal unused_drck : std_logic;
begin
    unused_drck <= user_drck;  -- accepted but unused (fcapz clocks on user_tck)

    tck      <= user_tck;
    tdi      <= user_tdi;
    capture  <= user_capture;
    shift    <= user_shift;
    update   <= user_update;
    sel      <= user_sel;

    user_tdo <= tdo;
end architecture rtl;
