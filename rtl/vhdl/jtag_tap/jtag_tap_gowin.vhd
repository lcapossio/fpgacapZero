-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
-- Copyright (c) 2026 Craig Haywood - BrisbaneSilicon - <support@brisbanesilicon.com.au>

library ieee;
use ieee.std_logic_1164.all;

entity jtag_tap_gowin is
    port (
        sysclk    : in  std_logic;
        activity  : out std_logic;
        tdi       : out std_logic;
        tdo       : in  std_logic_vector(1 downto 0);
        capture   : out std_logic_vector(1 downto 0);
        shift_in  : out std_logic_vector(1 downto 0);
        shift_out : out std_logic_vector(1 downto 0);
        update    : out std_logic_vector(1 downto 0);
        sel       : out std_logic_vector(1 downto 0);
        tms_pad_i : in  std_logic;
        tck_pad_i : in  std_logic;
        tdi_pad_i : in  std_logic;
        tdo_pad_o : out std_logic
    );
end entity jtag_tap_gowin;

architecture rtl of jtag_tap_gowin is
    signal jtck_jtck           : std_logic;
    signal jtdi_jtck           : std_logic;
    signal jshift_capture_jtck : std_logic;
    signal jupdate_jtck        : std_logic;
    signal jce_jtck            : std_logic_vector(1 downto 0);
    signal jtag_in_jtck        : std_logic_vector(5 downto 0);

    signal jtag_in             : std_logic_vector(5 downto 0);
    signal jtck                : std_logic;
    signal jtdi                : std_logic;
    signal jshift_capture      : std_logic;
    signal jupdate             : std_logic;
    signal jce                 : std_logic_vector(1 downto 0);
    signal jtck_d1             : std_logic := '0';
    signal jupdate_d1          : std_logic := '0';
    signal jshift_capture_d1   : std_logic := '0';
    signal jtck_en             : std_logic;

    signal jtag_in_reg         : std_logic_vector(4 downto 0) := (others => '0');
    signal jtdi_reg            : std_logic;
    signal jshift_capture_reg  : std_logic;
    signal jshift_capture_reg_d1 : std_logic := '0';
    signal jupdate_reg         : std_logic;
    signal jce_reg             : std_logic_vector(1 downto 0);
    signal s_reg               : std_logic := '0';
    signal jhold_reg           : std_logic := '0';
    signal out_en_reg          : std_logic := '0';
begin
    u_jtag : entity work.GW_JTAG
        port map (
            tck_pad_i => tck_pad_i,
            tms_pad_i => tms_pad_i,
            tdi_pad_i => tdi_pad_i,
            tdo_pad_o => tdo_pad_o,
            tck_o => jtck_jtck,
            tdi_o => jtdi_jtck,
            test_logic_reset_o => open,
            run_test_idle_er1_o => open,
            run_test_idle_er2_o => open,
            shift_dr_capture_dr_o => jshift_capture_jtck,
            pause_dr_o => open,
            update_dr_o => jupdate_jtck,
            enable_er1_o => jce_jtck(0),
            enable_er2_o => jce_jtck(1),
            tdo_er1_i => tdo(0),
            tdo_er2_i => tdo(1)
        );

    jtag_in_jtck <= jtck_jtck & jtdi_jtck & jshift_capture_jtck & jupdate_jtck & jce_jtck;

    u_jtag_in_sync : entity work.dff_reg_sync
        generic map (
            pREG_LEN => 6,
            pSYNC_STAGES => 2
        )
        port map (
            clk => sysclk,
            srst => '0',
            syncreg => jtag_in,
            asyncreg => jtag_in_jtck
        );

    jtck <= jtag_in(5);
    jtdi <= jtag_in(4);
    jshift_capture <= jtag_in(3);
    jupdate <= jtag_in(2);
    jce <= jtag_in(1 downto 0);
    jtck_en <= jtck_d1 and not jtck;

    jtdi_reg <= jtag_in_reg(4);
    jshift_capture_reg <= jtag_in_reg(3);
    jupdate_reg <= jtag_in_reg(2);
    jce_reg <= jtag_in_reg(1 downto 0);

    tdi <= jtdi_reg;
    activity <= jtck_en;

    p_jtck : process(sysclk)
    begin
        if rising_edge(sysclk) then
            jtck_d1 <= jtck;

            if jtck_en = '1' then
                jupdate_d1 <= jupdate;
                jshift_capture_d1 <= jshift_capture;

                if jshift_capture = '1' then
                    jhold_reg <= '1';
                elsif jupdate = '0' and jupdate_d1 = '1' then
                    jhold_reg <= '0';
                end if;

                if jshift_capture_d1 = '1' then
                    if jce(0) = '1' then
                        s_reg <= '0';
                    end if;
                    if jce(1) = '1' then
                        s_reg <= '1';
                    end if;
                end if;

                jtag_in_reg <= jtag_in(4 downto 0);
                jshift_capture_reg_d1 <= jshift_capture_reg;
            end if;

            out_en_reg <= jtck_en;
        end if;
    end process;

    p_outputs : process(all)
    begin
        capture <= (others => '0');
        shift_out <= (others => '0');
        shift_in <= (others => '0');
        update <= (others => '0');
        sel <= (others => '0');

        if out_en_reg = '1' then
            for i in 0 to 1 loop
                capture(i) <= jce_reg(i) and not jshift_capture_reg and not jhold_reg;
                shift_out(i) <= jce_reg(i) and jshift_capture_reg;
                shift_in(i) <= jce_reg(i) and jshift_capture_reg_d1;
            end loop;

            update(0) <= jupdate_reg and not s_reg;
            update(1) <= jupdate_reg and s_reg;
            sel <= jce_reg;
        end if;
    end process;
end architecture rtl;
