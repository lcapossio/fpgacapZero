-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Microchip PolarFire / PolarFire SoC JTAG TAP wrapper (see
-- rtl/jtag_tap/jtag_tap_polarfire.v).  UJTAG's TCK/TMS/TDI/TRSTB/TDO pins
-- must reach top-level ports; they are passed through on the *_pad_* ports.
-- USER1/USER2 default to 0x20/0x21: on PolarFire SoC the MSS debug module
-- answers at 0x10/0x11.
entity jtag_tap_polarfire is
    generic (
        IR_USER1 : std_logic_vector(7 downto 0) := x"20";
        IR_USER2 : std_logic_vector(7 downto 0) := x"21"
    );
    port (
        tck_pad_i   : in  std_logic;
        tms_pad_i   : in  std_logic;
        tdi_pad_i   : in  std_logic;
        trstb_pad_i : in  std_logic;
        tdo_pad_o   : out std_logic;
        ch1_tck     : out std_logic;
        ch1_tdi     : out std_logic;
        ch1_tdo     : in  std_logic;
        ch1_capture : out std_logic;
        ch1_shift   : out std_logic;
        ch1_update  : out std_logic;
        ch1_sel     : out std_logic;
        ch2_tck     : out std_logic;
        ch2_tdi     : out std_logic;
        ch2_tdo     : in  std_logic;
        ch2_capture : out std_logic;
        ch2_shift   : out std_logic;
        ch2_update  : out std_logic;
        ch2_sel     : out std_logic
    );
end entity jtag_tap_polarfire;

architecture rtl of jtag_tap_polarfire is
    component UJTAG is
        port (
            TCK    : in  std_logic;
            TMS    : in  std_logic;
            TDI    : in  std_logic;
            TRSTB  : in  std_logic;
            TDO    : out std_logic;
            UIREG  : out std_logic_vector(7 downto 0);
            UTDI   : out std_logic;
            UDRCK  : out std_logic;
            UDRCAP : out std_logic;
            UDRSH  : out std_logic;
            UDRUPD : out std_logic;
            URSTB  : out std_logic;
            UTDO   : in  std_logic
        );
    end component;

    signal uireg  : std_logic_vector(7 downto 0);
    signal utdi   : std_logic;
    signal udrck  : std_logic;
    signal udrcap : std_logic;
    signal udrsh  : std_logic;
    signal udrupd : std_logic;
    signal urstb_unused : std_logic;
    signal is_user1 : std_logic;
    signal is_user2 : std_logic;
    signal utdo     : std_logic;
begin
    is_user1 <= '1' when uireg = IR_USER1 else '0';
    is_user2 <= '1' when uireg = IR_USER2 else '0';
    utdo <= ch1_tdo when is_user1 = '1' else
            ch2_tdo when is_user2 = '1' else
            '0';

    u_ujtag : UJTAG
        port map (
            TCK    => tck_pad_i,
            TMS    => tms_pad_i,
            TDI    => tdi_pad_i,
            TRSTB  => trstb_pad_i,
            TDO    => tdo_pad_o,
            UIREG  => uireg,
            UTDI   => utdi,
            UDRCK  => udrck,
            UDRCAP => udrcap,
            UDRSH  => udrsh,
            UDRUPD => udrupd,
            URSTB  => urstb_unused,
            UTDO   => utdo
        );

    ch1_tck <= udrck;
    ch1_tdi <= utdi;
    ch1_capture <= udrcap and is_user1;
    ch1_shift <= udrsh and is_user1;
    ch1_update <= udrupd and is_user1;
    ch1_sel <= is_user1;

    ch2_tck <= udrck;
    ch2_tdi <= utdi;
    ch2_capture <= udrcap and is_user2;
    ch2_shift <= udrsh and is_user2;
    ch2_update <= udrupd and is_user2;
    ch2_sel <= is_user2;
end architecture rtl;
