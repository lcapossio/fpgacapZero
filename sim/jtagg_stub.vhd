-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

-- Simulation model of the Lattice ECP5 JTAGG primitive; see jtagg_stub.v.
-- A testbench drives tck_pin, tms_pin and tdi_pin and reads tdo_pin.

library ieee;
use ieee.std_logic_1164.all;

entity JTAGG is
    port (
        JTCK    : out std_logic;
        JTDI    : out std_logic;
        JTDO1   : in  std_logic;
        JTDO2   : in  std_logic;
        JSHIFT  : out std_logic;
        JUPDATE : out std_logic;
        JRSTN   : out std_logic;
        JCE1    : out std_logic;
        JCE2    : out std_logic;
        JRTI1   : out std_logic;
        JRTI2   : out std_logic
    );
end entity JTAGG;

architecture sim of JTAGG is

    type tap_state_t is (TLR, RTI, SEL_DR, CAP_DR, SH_DR, EX1_DR, PAU_DR, EX2_DR,
                         UPD_DR, SEL_IR, CAP_IR, SH_IR, EX1_IR, PAU_IR, EX2_IR, UPD_IR);

    constant IR_ER1    : std_logic_vector(7 downto 0) := x"32";
    constant IR_ER2    : std_logic_vector(7 downto 0) := x"38";
    constant IR_IDCODE : std_logic_vector(7 downto 0) := x"E0";

    signal tck_pin : std_logic := '0';
    signal tms_pin : std_logic := '1';
    signal tdi_pin : std_logic := '0';
    signal tdo_pin : std_logic := '0';

    signal state  : tap_state_t := TLR;
    signal ir     : std_logic_vector(7 downto 0) := IR_IDCODE;
    signal ir_sr  : std_logic_vector(7 downto 0) := (others => '0');
    signal bypass : std_logic := '0';
    signal jtdi_q : std_logic := '0';

begin

    p_rise : process(tck_pin)
        variable tms : boolean;
    begin
        if rising_edge(tck_pin) then
            jtdi_q <= tdi_pin;
            case state is
                when CAP_IR => ir_sr <= x"01";
                when SH_IR  => ir_sr <= tdi_pin & ir_sr(7 downto 1);
                when UPD_IR => ir <= ir_sr;
                when TLR    => ir <= IR_IDCODE;
                when CAP_DR => bypass <= '0';
                when SH_DR  => bypass <= tdi_pin;
                when others => null;
            end case;
            tms := tms_pin = '1';
            case state is
                when TLR    => if tms then state <= TLR;    else state <= RTI;    end if;
                when RTI    => if tms then state <= SEL_DR; else state <= RTI;    end if;
                when SEL_DR => if tms then state <= SEL_IR; else state <= CAP_DR; end if;
                when CAP_DR => if tms then state <= EX1_DR; else state <= SH_DR;  end if;
                when SH_DR  => if tms then state <= EX1_DR; else state <= SH_DR;  end if;
                when EX1_DR => if tms then state <= UPD_DR; else state <= PAU_DR; end if;
                when PAU_DR => if tms then state <= EX2_DR; else state <= PAU_DR; end if;
                when EX2_DR => if tms then state <= UPD_DR; else state <= SH_DR;  end if;
                when UPD_DR => if tms then state <= SEL_DR; else state <= RTI;    end if;
                when SEL_IR => if tms then state <= TLR;    else state <= CAP_IR; end if;
                when CAP_IR => if tms then state <= EX1_IR; else state <= SH_IR;  end if;
                when SH_IR  => if tms then state <= EX1_IR; else state <= SH_IR;  end if;
                when EX1_IR => if tms then state <= UPD_IR; else state <= PAU_IR; end if;
                when PAU_IR => if tms then state <= EX2_IR; else state <= PAU_IR; end if;
                when EX2_IR => if tms then state <= UPD_IR; else state <= SH_IR;  end if;
                when UPD_IR => if tms then state <= SEL_DR; else state <= RTI;    end if;
            end case;
        end if;
    end process;

    p_fall : process(tck_pin)
    begin
        if falling_edge(tck_pin) then
            if state = SH_DR then
                if ir = IR_ER1 then
                    tdo_pin <= JTDO1;
                elsif ir = IR_ER2 then
                    tdo_pin <= JTDO2;
                else
                    tdo_pin <= bypass;
                end if;
            elsif state = SH_IR then
                tdo_pin <= ir_sr(0);
            end if;
        end if;
    end process;

    JTCK    <= tck_pin;
    JTDI    <= jtdi_q;
    JSHIFT  <= '1' when state = SH_DR else '0';
    JUPDATE <= '1' when state = UPD_DR else '0';
    JRSTN   <= '0' when state = TLR else '1';
    JCE1    <= '1' when (state = CAP_DR or state = SH_DR) and ir = IR_ER1 else '0';
    JCE2    <= '1' when (state = CAP_DR or state = SH_DR) and ir = IR_ER2 else '0';
    JRTI1   <= '1' when state = RTI and ir = IR_ER1 else '0';
    JRTI2   <= '1' when state = RTI and ir = IR_ER2 else '0';

end architecture sim;
