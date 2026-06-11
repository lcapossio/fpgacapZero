-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;

entity GW_JTAG is
    port (
        tck_pad_i              : in  std_logic;
        tms_pad_i              : in  std_logic;
        tdi_pad_i              : in  std_logic;
        tdo_pad_o              : out std_logic;
        tck_o                  : out std_logic;
        tdi_o                  : out std_logic;
        test_logic_reset_o     : out std_logic;
        run_test_idle_er1_o    : out std_logic;
        run_test_idle_er2_o    : out std_logic;
        shift_dr_capture_dr_o  : out std_logic;
        pause_dr_o             : out std_logic;
        update_dr_o            : out std_logic;
        enable_er1_o           : out std_logic;
        enable_er2_o           : out std_logic;
        tdo_er1_i              : in  std_logic;
        tdo_er2_i              : in  std_logic
    );
end entity GW_JTAG;

architecture black_box of GW_JTAG is
    attribute syn_black_box : boolean;
    attribute syn_black_box of black_box : architecture is true;
begin
end architecture black_box;
