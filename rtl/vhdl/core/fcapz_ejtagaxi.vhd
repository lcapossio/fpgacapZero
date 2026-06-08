-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

library work;
use work.fcapz_pkg.all;
use work.fcapz_util_pkg.all;

entity fcapz_ejtagaxi is
    generic (
        ADDR_W                 : positive := 32;
        DATA_W                 : positive := 32;
        FIFO_DEPTH             : positive := 16;
        CMD_FIFO_DEPTH         : positive := 32;
        RESP_FIFO_DEPTH        : positive := 32;
        TIMEOUT                : natural := 4096;
        DEBUG_EN               : natural := 0;
        USE_BEHAV_ASYNC_FIFO   : natural := 1;
        ASYNC_FIFO_IMPL        : integer := -1;
        CMD_FIFO_MEMORY_TYPE   : string := "auto";
        RESP_FIFO_MEMORY_TYPE  : string := "auto";
        BURST_FIFO_MEMORY_TYPE : string := "auto"
    );
    port (
        tck      : in  std_logic;
        tdi      : in  std_logic;
        tdo      : out std_logic;
        capture  : in  std_logic;
        shift_en : in  std_logic;
        update   : in  std_logic;
        sel      : in  std_logic;

        axi_clk : in  std_logic;
        axi_rst : in  std_logic;

        m_axi_awaddr  : out std_logic_vector(ADDR_W - 1 downto 0);
        m_axi_awlen   : out std_logic_vector(7 downto 0);
        m_axi_awsize  : out std_logic_vector(2 downto 0);
        m_axi_awburst : out std_logic_vector(1 downto 0);
        m_axi_awvalid : out std_logic;
        m_axi_awready : in  std_logic;
        m_axi_awprot  : out std_logic_vector(2 downto 0);

        m_axi_wdata  : out std_logic_vector(DATA_W - 1 downto 0);
        m_axi_wstrb  : out std_logic_vector(DATA_W / 8 - 1 downto 0);
        m_axi_wvalid : out std_logic;
        m_axi_wready : in  std_logic;
        m_axi_wlast  : out std_logic;

        m_axi_bresp  : in  std_logic_vector(1 downto 0);
        m_axi_bvalid : in  std_logic;
        m_axi_bready : out std_logic;

        m_axi_araddr  : out std_logic_vector(ADDR_W - 1 downto 0);
        m_axi_arlen   : out std_logic_vector(7 downto 0);
        m_axi_arsize  : out std_logic_vector(2 downto 0);
        m_axi_arburst : out std_logic_vector(1 downto 0);
        m_axi_arvalid : out std_logic;
        m_axi_arready : in  std_logic;
        m_axi_arprot  : out std_logic_vector(2 downto 0);

        m_axi_rdata  : in  std_logic_vector(DATA_W - 1 downto 0);
        m_axi_rresp  : in  std_logic_vector(1 downto 0);
        m_axi_rvalid : in  std_logic;
        m_axi_rlast  : in  std_logic;
        m_axi_rready : out std_logic;

        debug_tck      : out std_logic_vector(255 downto 0);
        debug_tck_edge : out std_logic_vector(255 downto 0);
        debug_axi      : out std_logic_vector(255 downto 0);
        debug_axi_edge : out std_logic_vector(255 downto 0)
    );
end entity fcapz_ejtagaxi;

architecture rtl of fcapz_ejtagaxi is
    function is_power_of_two(n : positive) return boolean is
        variable value : positive := n;
    begin
        while value > 1 loop
            if value mod 2 /= 0 then
                return false;
            end if;
            value := value / 2;
        end loop;
        return true;
    end function;

    function low32(value : std_logic_vector) return std_logic_vector is
        variable result : std_logic_vector(31 downto 0) := (others => '0');
        variable n : natural;
    begin
        if value'length < 32 then
            n := value'length;
        else
            n := 32;
        end if;
        result(n - 1 downto 0) := value(n - 1 downto 0);
        return result;
    end function;

    constant DR_W : positive := 72;
    constant DATA_BYTES : positive := DATA_W / 8;
    constant CMDQ_W : positive := 4 + ADDR_W + DATA_W + DATA_BYTES + 8 + 3 + 2;
    constant RESPQ_W : positive := DATA_W + 2;
    constant FIFO_AW : positive := fcapz_clog2(FIFO_DEPTH);
    constant CMD_FIFO_AW : positive := fcapz_clog2(CMD_FIFO_DEPTH);
    constant RESP_FIFO_AW : positive := fcapz_clog2(RESP_FIFO_DEPTH);
    constant ZERO_WSTRB : std_logic_vector(DATA_BYTES - 1 downto 0) := (others => '0');

    constant CMD_NOP          : std_logic_vector(3 downto 0) := x"0";
    constant CMD_WRITE        : std_logic_vector(3 downto 0) := x"1";
    constant CMD_READ         : std_logic_vector(3 downto 0) := x"2";
    constant CMD_WRITE_INC    : std_logic_vector(3 downto 0) := x"3";
    constant CMD_READ_INC     : std_logic_vector(3 downto 0) := x"4";
    constant CMD_SET_ADDR     : std_logic_vector(3 downto 0) := x"5";
    constant CMD_BURST_SETUP  : std_logic_vector(3 downto 0) := x"6";
    constant CMD_BURST_WDATA  : std_logic_vector(3 downto 0) := x"7";
    constant CMD_BURST_RDATA  : std_logic_vector(3 downto 0) := x"8";
    constant CMD_BURST_RSTART : std_logic_vector(3 downto 0) := x"9";
    constant CMD_CONFIG       : std_logic_vector(3 downto 0) := x"E";
    constant CMD_RESET        : std_logic_vector(3 downto 0) := x"F";

    constant CFG_VERSION       : std_logic_vector(15 downto 0) := x"0000";
    constant CFG_VERSION_ALIAS : std_logic_vector(15 downto 0) := x"0004";
    constant CFG_FEATURES      : std_logic_vector(15 downto 0) := x"002C";
    constant FIFO_DEPTH_ENC : std_logic_vector(7 downto 0) :=
        std_logic_vector(to_unsigned(FIFO_DEPTH - 1, 8));
    constant FEATURES : std_logic_vector(31 downto 0) :=
        x"00" & FIFO_DEPTH_ENC &
        std_logic_vector(to_unsigned(DATA_W, 8)) &
        std_logic_vector(to_unsigned(ADDR_W, 8));

    type axi_state_t is (
        ST_IDLE,
        ST_AW_W,
        ST_WAIT_B,
        ST_AR,
        ST_WAIT_R,
        ST_BURST_AW_W,
        ST_BURST_W_FETCH,
        ST_BURST_W_LOAD,
        ST_BURST_W,
        ST_BURST_AR,
        ST_BURST_R_FILL,
        ST_DONE,
        ST_TIMEOUT_ERR
    );

    signal sr : std_logic_vector(DR_W - 1 downto 0) := (others => '0');
    signal sr_addr : std_logic_vector(31 downto 0);
    signal sr_payload : std_logic_vector(31 downto 0);
    signal sr_wstrb : std_logic_vector(3 downto 0);
    signal sr_cmd : std_logic_vector(3 downto 0);

    signal auto_inc_addr : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal burst_awlen : std_logic_vector(7 downto 0) := (others => '0');
    signal burst_awsize : std_logic_vector(2 downto 0) := "010";
    signal burst_awburst : std_logic_vector(1 downto 0) := "01";
    signal burst_addr : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal burst_cfg_valid : std_logic := '0';
    signal burst_w_beats_left : unsigned(8 downto 0) := (others => '0');
    signal burst_rdata_ready : std_logic := '0';
    signal prev_valid : std_logic := '0';
    signal error_sticky : std_logic := '0';
    signal pending_count : unsigned(CMD_FIFO_AW downto 0) := (others => '0');
    signal last_cmd : std_logic_vector(3 downto 0) := CMD_NOP;
    signal config_rdata : std_logic_vector(31 downto 0) := (others => '0');

    signal cmdq_wr_en_i : std_logic := '0';
    signal cmdq_wr_data : std_logic_vector(CMDQ_W - 1 downto 0) := (others => '0');
    signal cmdq_full : std_logic;
    signal cmdq_wr_rst_busy : std_logic;
    signal cmdq_rd_en_i : std_logic := '0';
    signal cmdq_rd_data : std_logic_vector(CMDQ_W - 1 downto 0);
    signal cmdq_empty : std_logic;
    signal cmdq_rd_rst_busy : std_logic;
    signal cmdq_rd_count : std_logic_vector(CMD_FIFO_AW downto 0);
    signal cmdq_wr_count : std_logic_vector(CMD_FIFO_AW downto 0);
    signal cmdq_rst_tck : std_logic := '0';
    signal cmdq_rst_axi : std_logic := '0';

    signal respq_wr_en_i : std_logic := '0';
    signal respq_wr_data : std_logic_vector(RESPQ_W - 1 downto 0) := (others => '0');
    signal respq_full : std_logic;
    signal respq_wr_rst_busy : std_logic;
    signal respq_rd_en_i : std_logic := '0';
    signal respq_rd_data : std_logic_vector(RESPQ_W - 1 downto 0);
    signal respq_empty : std_logic;
    signal respq_rd_rst_busy : std_logic;
    signal respq_rd_count : std_logic_vector(RESP_FIFO_AW downto 0);
    signal respq_wr_count : std_logic_vector(RESP_FIFO_AW downto 0);
    signal respq_rst_tck : std_logic := '0';
    signal respq_rst_axi : std_logic := '0';

    signal fifo_wr_en_i : std_logic := '0';
    signal fifo_full : std_logic;
    signal fifo_rd_en_i : std_logic := '0';
    signal fifo_rdata : std_logic_vector(DATA_W - 1 downto 0);
    signal fifo_empty : std_logic;
    signal fifo_rd_count : std_logic_vector(FIFO_AW downto 0);
    signal fifo_rd_count8 : std_logic_vector(7 downto 0);
    signal fifo_rst_tck : std_logic := '0';
    signal fifo_rst_axi : std_logic := '0';
    signal fifo_wr_data_i : std_logic_vector(DATA_W - 1 downto 0) := (others => '0');

    signal axi_state : axi_state_t := ST_IDLE;
    signal timeout_cnt : unsigned(31 downto 0) := (others => '0');
    signal beat_count : unsigned(7 downto 0) := (others => '0');
    signal launch_cmd : std_logic_vector(3 downto 0) := CMD_NOP;
    signal launch_addr : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal launch_wdata : std_logic_vector(DATA_W - 1 downto 0) := (others => '0');
    signal launch_wstrb : std_logic_vector(DATA_BYTES - 1 downto 0) := (others => '0');
    signal launch_burst_len : std_logic_vector(7 downto 0) := (others => '0');
    signal launch_burst_size : std_logic_vector(2 downto 0) := "010";
    signal launch_burst_type : std_logic_vector(1 downto 0) := "01";
    signal resp_rdata : std_logic_vector(DATA_W - 1 downto 0) := (others => '0');
    signal resp_code : std_logic_vector(1 downto 0) := "00";

    signal m_axi_awaddr_i : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal m_axi_awlen_i : std_logic_vector(7 downto 0) := (others => '0');
    signal m_axi_awsize_i : std_logic_vector(2 downto 0) := "010";
    signal m_axi_awburst_i : std_logic_vector(1 downto 0) := "01";
    signal m_axi_awvalid_i : std_logic := '0';
    signal m_axi_wdata_i : std_logic_vector(DATA_W - 1 downto 0) := (others => '0');
    signal m_axi_wstrb_i : std_logic_vector(DATA_BYTES - 1 downto 0) := (others => '0');
    signal m_axi_wvalid_i : std_logic := '0';
    signal m_axi_wlast_i : std_logic := '0';
    signal m_axi_bready_i : std_logic := '0';
    signal m_axi_araddr_i : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal m_axi_arlen_i : std_logic_vector(7 downto 0) := (others => '0');
    signal m_axi_arsize_i : std_logic_vector(2 downto 0) := "010";
    signal m_axi_arburst_i : std_logic_vector(1 downto 0) := "01";
    signal m_axi_arvalid_i : std_logic := '0';
    signal m_axi_rready_i : std_logic := '0';

    signal reset_req_toggle : std_logic := '0';
    signal reset_req_sync1_axi : std_logic := '0';
    signal reset_req_sync2_axi : std_logic := '0';
    signal reset_req_seen_axi : std_logic := '0';
    signal reset_ack_toggle_axi : std_logic := '0';
    signal reset_ack_sync1_tck : std_logic := '0';
    signal reset_ack_sync2_tck : std_logic := '0';
    signal reset_busy_tck : std_logic;

begin
    assert DATA_W = 32 and ADDR_W = 32
        report "fcapz_ejtagaxi VHDL translation currently supports ADDR_W=32 DATA_W=32"
        severity failure;
    assert FIFO_DEPTH >= 1 and FIFO_DEPTH <= 256 and is_power_of_two(FIFO_DEPTH)
        report "fcapz_ejtagaxi: FIFO_DEPTH must be a power of two from 1..256"
        severity failure;
    assert CMD_FIFO_DEPTH >= 2 and is_power_of_two(CMD_FIFO_DEPTH)
        report "fcapz_ejtagaxi: CMD_FIFO_DEPTH must be a power of two >= 2"
        severity failure;
    assert RESP_FIFO_DEPTH >= 2 and is_power_of_two(RESP_FIFO_DEPTH)
        report "fcapz_ejtagaxi: RESP_FIFO_DEPTH must be a power of two >= 2"
        severity failure;

    sr_addr <= sr(31 downto 0);
    sr_payload <= sr(63 downto 32);
    sr_wstrb <= sr(67 downto 64);
    sr_cmd <= sr(71 downto 68);
    tdo <= sr(0);

    m_axi_awaddr <= m_axi_awaddr_i;
    m_axi_awlen <= m_axi_awlen_i;
    m_axi_awsize <= m_axi_awsize_i;
    m_axi_awburst <= m_axi_awburst_i;
    m_axi_awvalid <= m_axi_awvalid_i;
    m_axi_awprot <= "000";
    m_axi_wdata <= m_axi_wdata_i;
    m_axi_wstrb <= m_axi_wstrb_i;
    m_axi_wvalid <= m_axi_wvalid_i;
    m_axi_wlast <= m_axi_wlast_i;
    m_axi_bready <= m_axi_bready_i;
    m_axi_araddr <= m_axi_araddr_i;
    m_axi_arlen <= m_axi_arlen_i;
    m_axi_arsize <= m_axi_arsize_i;
    m_axi_arburst <= m_axi_arburst_i;
    m_axi_arvalid <= m_axi_arvalid_i;
    m_axi_arprot <= "000";
    m_axi_rready <= m_axi_rready_i;

    debug_tck <= (others => '0');
    debug_tck_edge <= (others => '0');
    debug_axi <= (others => '0');
    debug_axi_edge <= (others => '0');

    reset_busy_tck <= '1' when reset_req_toggle /= reset_ack_sync2_tck else '0';
    fifo_rd_count8 <= std_logic_vector(resize(unsigned(fifo_rd_count), 8));

    u_cmd_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => CMDQ_W,
            DEPTH => CMD_FIFO_DEPTH,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO,
            ASYNC_FIFO_IMPL => ASYNC_FIFO_IMPL,
            XPM_FIFO_MEMORY_TYPE => CMD_FIFO_MEMORY_TYPE
        )
        port map (
            wr_clk => tck,
            wr_rst => axi_rst or cmdq_rst_tck,
            wr_en => cmdq_wr_en_i,
            wr_data => cmdq_wr_data,
            wr_full => cmdq_full,
            wr_rst_busy => cmdq_wr_rst_busy,
            rd_clk => axi_clk,
            rd_rst => axi_rst or cmdq_rst_axi,
            rd_en => cmdq_rd_en_i,
            rd_data => cmdq_rd_data,
            rd_empty => cmdq_empty,
            rd_rst_busy => cmdq_rd_rst_busy,
            rd_count => cmdq_rd_count,
            wr_count => cmdq_wr_count
        );

    u_resp_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => RESPQ_W,
            DEPTH => RESP_FIFO_DEPTH,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO,
            ASYNC_FIFO_IMPL => ASYNC_FIFO_IMPL,
            XPM_FIFO_MEMORY_TYPE => RESP_FIFO_MEMORY_TYPE
        )
        port map (
            wr_clk => axi_clk,
            wr_rst => axi_rst or respq_rst_axi,
            wr_en => respq_wr_en_i,
            wr_data => respq_wr_data,
            wr_full => respq_full,
            wr_rst_busy => respq_wr_rst_busy,
            rd_clk => tck,
            rd_rst => axi_rst or respq_rst_tck,
            rd_en => respq_rd_en_i,
            rd_data => respq_rd_data,
            rd_empty => respq_empty,
            rd_rst_busy => respq_rd_rst_busy,
            rd_count => respq_rd_count,
            wr_count => respq_wr_count
        );

    u_burst_fifo : entity work.fcapz_async_fifo
        generic map (
            DATA_W => DATA_W,
            DEPTH => FIFO_DEPTH,
            USE_BEHAV_ASYNC_FIFO => USE_BEHAV_ASYNC_FIFO,
            ASYNC_FIFO_IMPL => ASYNC_FIFO_IMPL,
            XPM_FIFO_MEMORY_TYPE => BURST_FIFO_MEMORY_TYPE
        )
        port map (
            wr_clk => axi_clk,
            wr_rst => axi_rst or fifo_rst_axi,
            wr_en => fifo_wr_en_i,
            wr_data => fifo_wr_data_i,
            wr_full => fifo_full,
            wr_rst_busy => open,
            rd_clk => tck,
            rd_rst => axi_rst or fifo_rst_tck,
            rd_en => fifo_rd_en_i,
            rd_data => fifo_rdata,
            rd_empty => fifo_empty,
            rd_rst_busy => open,
            rd_count => fifo_rd_count,
            wr_count => open
        );

    p_tck : process(tck)
        variable capture_rdata : std_logic_vector(31 downto 0);
        variable capture_resp : std_logic_vector(1 downto 0);
        variable capture_valid : std_logic;
        variable status_bits : std_logic_vector(3 downto 0);
        variable busy_status : std_logic;
        variable enqueue_data : std_logic_vector(CMDQ_W - 1 downto 0);
        variable cmd_addr : std_logic_vector(ADDR_W - 1 downto 0);
    begin
        if rising_edge(tck) then
            cmdq_wr_en_i <= '0';
            respq_rd_en_i <= '0';
            fifo_rd_en_i <= '0';
            cmdq_rst_tck <= '0';
            respq_rst_tck <= '0';
            fifo_rst_tck <= '0';
            reset_ack_sync1_tck <= reset_ack_toggle_axi;
            reset_ack_sync2_tck <= reset_ack_sync1_tck;

            if sel = '1' then
                if capture = '1' then
                    capture_rdata := (others => '0');
                    capture_resp := "00";
                    capture_valid := '0';

                    if last_cmd = CMD_CONFIG then
                        capture_rdata := config_rdata;
                        capture_valid := '1';
                    elsif last_cmd = CMD_BURST_RDATA and burst_rdata_ready = '1' and fifo_empty = '0' then
                        capture_rdata := low32(fifo_rdata);
                        capture_valid := '1';
                    elsif respq_empty = '0' and respq_rd_rst_busy = '0' then
                        capture_rdata := low32(respq_rd_data(DATA_W - 1 downto 0));
                        capture_resp := respq_rd_data(DATA_W + 1 downto DATA_W);
                        capture_valid := '1';
                        respq_rd_en_i <= '1';
                        if pending_count /= 0 then
                            pending_count <= pending_count - 1;
                        end if;
                        if respq_rd_data(DATA_W + 1 downto DATA_W) /= "00" then
                            error_sticky <= '1';
                        end if;
                    end if;

                    if capture_valid = '1' then
                        prev_valid <= '1';
                    end if;

                    busy_status := reset_busy_tck or
                        (cmdq_full or cmdq_wr_rst_busy or cmdq_rd_rst_busy) or
                        (respq_wr_rst_busy or respq_rd_rst_busy);
                    if pending_count /= 0 and capture_valid = '0' then
                        busy_status := '1';
                    end if;

                    status_bits := (not fifo_empty) &
                        (error_sticky or (capture_valid and capture_resp(1))) &
                        busy_status &
                        capture_valid;
                    sr <= status_bits & "00" & capture_resp &
                        x"00" & fifo_rd_count8 & auto_inc_addr(15 downto 0) &
                        capture_rdata;
                elsif shift_en = '1' then
                    sr <= tdi & sr(DR_W - 1 downto 1);
                elsif update = '1' then
                    prev_valid <= '0';

                    cmd_addr := sr_addr(ADDR_W - 1 downto 0);
                    enqueue_data := sr_cmd & cmd_addr &
                        sr_payload(DATA_W - 1 downto 0) &
                        sr_wstrb(DATA_BYTES - 1 downto 0) &
                        burst_awlen & burst_awsize & burst_awburst;

                    case sr_cmd is
                        when CMD_NOP =>
                            null;
                        when CMD_SET_ADDR =>
                            auto_inc_addr <= cmd_addr;
                            last_cmd <= sr_cmd;
                        when CMD_WRITE =>
                            if sr_wstrb(DATA_BYTES - 1 downto 0) /= ZERO_WSTRB and
                               cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_WRITE & cmd_addr &
                                    sr_payload(DATA_W - 1 downto 0) &
                                    sr_wstrb(DATA_BYTES - 1 downto 0) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                last_cmd <= sr_cmd;
                            end if;
                            burst_cfg_valid <= '0';
                            burst_w_beats_left <= (others => '0');
                            burst_rdata_ready <= '0';
                        when CMD_READ =>
                            if cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_READ & cmd_addr &
                                    std_logic_vector(to_unsigned(0, DATA_W)) &
                                    std_logic_vector(to_unsigned(0, DATA_BYTES)) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                last_cmd <= sr_cmd;
                            end if;
                            burst_cfg_valid <= '0';
                            burst_w_beats_left <= (others => '0');
                            burst_rdata_ready <= '0';
                        when CMD_WRITE_INC =>
                            if sr_wstrb(DATA_BYTES - 1 downto 0) /= ZERO_WSTRB and
                               cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_WRITE & auto_inc_addr &
                                    sr_payload(DATA_W - 1 downto 0) &
                                    sr_wstrb(DATA_BYTES - 1 downto 0) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                auto_inc_addr <= std_logic_vector(unsigned(auto_inc_addr) + to_unsigned(4, ADDR_W));
                                last_cmd <= sr_cmd;
                            end if;
                            burst_cfg_valid <= '0';
                            burst_w_beats_left <= (others => '0');
                        when CMD_READ_INC =>
                            if cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_READ & auto_inc_addr &
                                    std_logic_vector(to_unsigned(0, DATA_W)) &
                                    std_logic_vector(to_unsigned(0, DATA_BYTES)) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                auto_inc_addr <= std_logic_vector(unsigned(auto_inc_addr) + to_unsigned(4, ADDR_W));
                                last_cmd <= sr_cmd;
                            end if;
                            burst_cfg_valid <= '0';
                            burst_w_beats_left <= (others => '0');
                        when CMD_BURST_SETUP =>
                            burst_addr <= cmd_addr;
                            burst_awlen <= sr_payload(7 downto 0);
                            burst_awsize <= sr_payload(10 downto 8);
                            burst_awburst <= sr_payload(13 downto 12);
                            burst_cfg_valid <= '1';
                            burst_w_beats_left <= resize(unsigned(sr_payload(7 downto 0)), 9) + 1;
                            burst_rdata_ready <= '0';
                            last_cmd <= sr_cmd;
                        when CMD_BURST_WDATA =>
                            if burst_cfg_valid = '1' and burst_w_beats_left /= 0 and
                               sr_wstrb(DATA_BYTES - 1 downto 0) /= ZERO_WSTRB and
                               cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_BURST_WDATA & burst_addr &
                                    sr_payload(DATA_W - 1 downto 0) &
                                    sr_wstrb(DATA_BYTES - 1 downto 0) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                if burst_w_beats_left = 1 then
                                    burst_cfg_valid <= '0';
                                    burst_w_beats_left <= (others => '0');
                                else
                                    burst_w_beats_left <= burst_w_beats_left - 1;
                                end if;
                                last_cmd <= sr_cmd;
                            end if;
                        when CMD_BURST_RSTART =>
                            if burst_cfg_valid = '1' and cmdq_full = '0' and cmdq_wr_rst_busy = '0' then
                                cmdq_wr_data <= CMD_BURST_RSTART & burst_addr &
                                    std_logic_vector(to_unsigned(0, DATA_W)) &
                                    std_logic_vector(to_unsigned(0, DATA_BYTES)) &
                                    burst_awlen & burst_awsize & burst_awburst;
                                cmdq_wr_en_i <= '1';
                                pending_count <= pending_count + 1;
                                burst_rdata_ready <= '0';
                                burst_cfg_valid <= '0';
                                burst_w_beats_left <= (others => '0');
                                last_cmd <= sr_cmd;
                            end if;
                        when CMD_BURST_RDATA =>
                            if burst_rdata_ready = '1' and fifo_empty = '0' and last_cmd = CMD_BURST_RDATA then
                                fifo_rd_en_i <= '1';
                            end if;
                            burst_rdata_ready <= '1';
                            last_cmd <= sr_cmd;
                        when CMD_CONFIG =>
                            case sr_addr(15 downto 0) is
                                when CFG_VERSION => config_rdata <= FCAPZ_EJTAGAXI_VERSION_REG;
                                when CFG_VERSION_ALIAS => config_rdata <= FCAPZ_EJTAGAXI_VERSION_REG;
                                when CFG_FEATURES => config_rdata <= FEATURES;
                                when others => config_rdata <= (others => '0');
                            end case;
                            last_cmd <= sr_cmd;
                        when CMD_RESET =>
                            error_sticky <= '0';
                            prev_valid <= '0';
                            pending_count <= (others => '0');
                            cmdq_rst_tck <= '1';
                            respq_rst_tck <= '1';
                            fifo_rst_tck <= '1';
                            auto_inc_addr <= (others => '0');
                            burst_awlen <= (others => '0');
                            burst_awsize <= "010";
                            burst_awburst <= "01";
                            burst_addr <= (others => '0');
                            burst_cfg_valid <= '0';
                            burst_w_beats_left <= (others => '0');
                            burst_rdata_ready <= '0';
                            config_rdata <= (others => '0');
                            last_cmd <= CMD_NOP;
                            reset_req_toggle <= not reset_req_toggle;
                        when others =>
                            null;
                    end case;
                end if;
            end if;
        end if;
    end process;

    p_axi : process(axi_clk, axi_rst)
        variable cmd_cmd : std_logic_vector(3 downto 0);
        variable cmd_addr : std_logic_vector(ADDR_W - 1 downto 0);
        variable cmd_wdata : std_logic_vector(DATA_W - 1 downto 0);
        variable cmd_wstrb : std_logic_vector(DATA_BYTES - 1 downto 0);
        variable cmd_len : std_logic_vector(7 downto 0);
        variable cmd_size : std_logic_vector(2 downto 0);
        variable cmd_burst : std_logic_vector(1 downto 0);
    begin
        if axi_rst = '1' then
            axi_state <= ST_IDLE;
            timeout_cnt <= (others => '0');
            beat_count <= (others => '0');
            launch_cmd <= CMD_NOP;
            launch_addr <= (others => '0');
            launch_wdata <= (others => '0');
            launch_wstrb <= (others => '0');
            launch_burst_len <= (others => '0');
            launch_burst_size <= "010";
            launch_burst_type <= "01";
            resp_rdata <= (others => '0');
            resp_code <= "00";
            m_axi_awaddr_i <= (others => '0');
            m_axi_awlen_i <= (others => '0');
            m_axi_awsize_i <= "010";
            m_axi_awburst_i <= "01";
            m_axi_awvalid_i <= '0';
            m_axi_wdata_i <= (others => '0');
            m_axi_wstrb_i <= (others => '0');
            m_axi_wvalid_i <= '0';
            m_axi_wlast_i <= '0';
            m_axi_bready_i <= '0';
            m_axi_araddr_i <= (others => '0');
            m_axi_arlen_i <= (others => '0');
            m_axi_arsize_i <= "010";
            m_axi_arburst_i <= "01";
            m_axi_arvalid_i <= '0';
            m_axi_rready_i <= '0';
            cmdq_rd_en_i <= '0';
            respq_wr_en_i <= '0';
            fifo_wr_en_i <= '0';
            fifo_wr_data_i <= (others => '0');
            cmdq_rst_axi <= '0';
            respq_rst_axi <= '0';
            fifo_rst_axi <= '0';
            reset_req_sync1_axi <= '0';
            reset_req_sync2_axi <= '0';
            reset_req_seen_axi <= '0';
            reset_ack_toggle_axi <= '0';
        elsif rising_edge(axi_clk) then
            cmdq_rd_en_i <= '0';
            respq_wr_en_i <= '0';
            fifo_wr_en_i <= '0';
            cmdq_rst_axi <= '0';
            respq_rst_axi <= '0';
            fifo_rst_axi <= '0';
            reset_req_sync1_axi <= reset_req_toggle;
            reset_req_sync2_axi <= reset_req_sync1_axi;

            if reset_req_sync2_axi /= reset_req_seen_axi then
                reset_req_seen_axi <= reset_req_sync2_axi;
                reset_ack_toggle_axi <= reset_req_sync2_axi;
                axi_state <= ST_IDLE;
                beat_count <= (others => '0');
                m_axi_awvalid_i <= '0';
                m_axi_wvalid_i <= '0';
                m_axi_wlast_i <= '0';
                m_axi_bready_i <= '0';
                m_axi_arvalid_i <= '0';
                m_axi_rready_i <= '0';
                cmdq_rst_axi <= '1';
                respq_rst_axi <= '1';
                fifo_rst_axi <= '1';
            else
                case axi_state is
                    when ST_IDLE =>
                        m_axi_awvalid_i <= '0';
                        m_axi_wvalid_i <= '0';
                        m_axi_wlast_i <= '0';
                        m_axi_bready_i <= '0';
                        m_axi_arvalid_i <= '0';
                        m_axi_rready_i <= '0';
                        timeout_cnt <= (others => '0');
                        beat_count <= (others => '0');
                        if cmdq_empty = '0' and cmdq_rd_rst_busy = '0' then
                            cmd_cmd := cmdq_rd_data(CMDQ_W - 1 downto CMDQ_W - 4);
                            cmd_addr := cmdq_rd_data(CMDQ_W - 5 downto CMDQ_W - 4 - ADDR_W);
                            cmd_wdata := cmdq_rd_data(12 + DATA_BYTES + DATA_W downto 13 + DATA_BYTES);
                            cmd_wstrb := cmdq_rd_data(12 + DATA_BYTES downto 13);
                            cmd_len := cmdq_rd_data(12 downto 5);
                            cmd_size := cmdq_rd_data(4 downto 2);
                            cmd_burst := cmdq_rd_data(1 downto 0);

                            launch_cmd <= cmd_cmd;
                            launch_addr <= cmd_addr;
                            launch_wdata <= cmd_wdata;
                            launch_wstrb <= cmd_wstrb;
                            launch_burst_len <= cmd_len;
                            launch_burst_size <= cmd_size;
                            launch_burst_type <= cmd_burst;
                            cmdq_rd_en_i <= '1';

                            if cmd_cmd = CMD_WRITE then
                                m_axi_awaddr_i <= cmd_addr;
                                m_axi_awlen_i <= (others => '0');
                                m_axi_awsize_i <= "010";
                                m_axi_awburst_i <= "01";
                                m_axi_awvalid_i <= '1';
                                m_axi_wdata_i <= cmd_wdata;
                                m_axi_wstrb_i <= cmd_wstrb;
                                m_axi_wvalid_i <= '1';
                                m_axi_wlast_i <= '1';
                                axi_state <= ST_AW_W;
                            elsif cmd_cmd = CMD_BURST_WDATA then
                                m_axi_awaddr_i <= cmd_addr;
                                m_axi_awlen_i <= cmd_len;
                                m_axi_awsize_i <= cmd_size;
                                m_axi_awburst_i <= cmd_burst;
                                m_axi_awvalid_i <= '1';
                                m_axi_wdata_i <= cmd_wdata;
                                m_axi_wstrb_i <= cmd_wstrb;
                                m_axi_wvalid_i <= '1';
                                m_axi_wlast_i <= '1' when unsigned(cmd_len) = 0 else '0';
                                beat_count <= (others => '0');
                                axi_state <= ST_BURST_AW_W;
                            elsif cmd_cmd = CMD_READ then
                                m_axi_araddr_i <= cmd_addr;
                                m_axi_arlen_i <= (others => '0');
                                m_axi_arsize_i <= "010";
                                m_axi_arburst_i <= "01";
                                m_axi_arvalid_i <= '1';
                                axi_state <= ST_AR;
                            elsif cmd_cmd = CMD_BURST_RSTART then
                                m_axi_araddr_i <= cmd_addr;
                                m_axi_arlen_i <= cmd_len;
                                m_axi_arsize_i <= cmd_size;
                                m_axi_arburst_i <= cmd_burst;
                                m_axi_arvalid_i <= '1';
                                axi_state <= ST_BURST_AR;
                            else
                                resp_rdata <= (others => '0');
                                resp_code <= "00";
                                axi_state <= ST_DONE;
                            end if;
                        end if;

                    when ST_AW_W =>
                        if m_axi_awvalid_i = '1' and m_axi_awready = '1' then
                            m_axi_awvalid_i <= '0';
                        end if;
                        if m_axi_wvalid_i = '1' and m_axi_wready = '1' then
                            m_axi_wvalid_i <= '0';
                            m_axi_wlast_i <= '0';
                        end if;
                        if (m_axi_awvalid_i = '0' or m_axi_awready = '1') and
                           (m_axi_wvalid_i = '0' or m_axi_wready = '1') then
                            m_axi_awvalid_i <= '0';
                            m_axi_wvalid_i <= '0';
                            m_axi_wlast_i <= '0';
                            m_axi_bready_i <= '1';
                            axi_state <= ST_WAIT_B;
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_WAIT_B =>
                        if m_axi_bvalid = '1' then
                            resp_code <= m_axi_bresp;
                            resp_rdata <= (others => '0');
                            m_axi_bready_i <= '0';
                            axi_state <= ST_DONE;
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_AR =>
                        if m_axi_arready = '1' then
                            m_axi_arvalid_i <= '0';
                            m_axi_rready_i <= '1';
                            axi_state <= ST_WAIT_R;
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_WAIT_R =>
                        if m_axi_rvalid = '1' then
                            resp_rdata <= m_axi_rdata;
                            resp_code <= m_axi_rresp;
                            m_axi_rready_i <= '0';
                            axi_state <= ST_DONE;
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_BURST_AW_W =>
                        if m_axi_awvalid_i = '1' and m_axi_awready = '1' then
                            m_axi_awvalid_i <= '0';
                        end if;
                        if m_axi_wvalid_i = '1' and m_axi_wready = '1' then
                            m_axi_wvalid_i <= '0';
                            if m_axi_wlast_i = '1' then
                                m_axi_wlast_i <= '0';
                            else
                                beat_count <= beat_count + 1;
                            end if;
                        end if;
                        if (m_axi_awvalid_i = '0' or m_axi_awready = '1') and
                           (m_axi_wvalid_i = '0' or m_axi_wready = '1') then
                            m_axi_awvalid_i <= '0';
                            m_axi_wvalid_i <= '0';
                            if m_axi_wlast_i = '1' then
                                m_axi_wlast_i <= '0';
                                m_axi_bready_i <= '1';
                                axi_state <= ST_WAIT_B;
                            else
                                axi_state <= ST_BURST_W_FETCH;
                            end if;
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_BURST_W_FETCH =>
                        m_axi_wvalid_i <= '0';
                        m_axi_wlast_i <= '0';
                        if cmdq_empty = '0' and cmdq_rd_rst_busy = '0' then
                            launch_cmd <= cmdq_rd_data(CMDQ_W - 1 downto CMDQ_W - 4);
                            launch_addr <= cmdq_rd_data(CMDQ_W - 5 downto CMDQ_W - 4 - ADDR_W);
                            launch_wdata <= cmdq_rd_data(12 + DATA_BYTES + DATA_W downto 13 + DATA_BYTES);
                            launch_wstrb <= cmdq_rd_data(12 + DATA_BYTES downto 13);
                            launch_burst_len <= cmdq_rd_data(12 downto 5);
                            launch_burst_size <= cmdq_rd_data(4 downto 2);
                            launch_burst_type <= cmdq_rd_data(1 downto 0);
                            cmdq_rd_en_i <= '1';
                            axi_state <= ST_BURST_W_LOAD;
                        end if;

                    when ST_BURST_W_LOAD =>
                        if launch_cmd = CMD_BURST_WDATA then
                            m_axi_wdata_i <= launch_wdata;
                            m_axi_wstrb_i <= launch_wstrb;
                            m_axi_wvalid_i <= '1';
                            m_axi_wlast_i <= '1' when beat_count = unsigned(launch_burst_len) else '0';
                            axi_state <= ST_BURST_W;
                        else
                            m_axi_wvalid_i <= '0';
                            m_axi_wlast_i <= '0';
                            resp_rdata <= (others => '0');
                            resp_code <= "10";
                            axi_state <= ST_DONE;
                        end if;

                    when ST_BURST_W =>
                        if m_axi_wvalid_i = '1' and m_axi_wready = '1' then
                            m_axi_wvalid_i <= '0';
                            if m_axi_wlast_i = '1' then
                                m_axi_wlast_i <= '0';
                                m_axi_bready_i <= '1';
                                axi_state <= ST_WAIT_B;
                            else
                                beat_count <= beat_count + 1;
                                axi_state <= ST_BURST_W_FETCH;
                            end if;
                        end if;

                    when ST_BURST_AR =>
                        if m_axi_arready = '1' then
                            m_axi_arvalid_i <= '0';
                            m_axi_rready_i <= '1';
                            axi_state <= ST_BURST_R_FILL;
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_BURST_R_FILL =>
                        m_axi_rready_i <= not fifo_full;
                        if m_axi_rvalid = '1' and fifo_full = '0' then
                            fifo_wr_data_i <= m_axi_rdata;
                            fifo_wr_en_i <= '1';
                            timeout_cnt <= (others => '0');
                            if m_axi_rlast = '1' then
                                resp_rdata <= m_axi_rdata;
                                resp_code <= m_axi_rresp;
                                m_axi_rready_i <= '0';
                                axi_state <= ST_DONE;
                            end if;
                        elsif m_axi_rvalid = '0' then
                            if timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                                axi_state <= ST_TIMEOUT_ERR;
                            else
                                timeout_cnt <= timeout_cnt + 1;
                            end if;
                        end if;

                    when ST_DONE =>
                        m_axi_awvalid_i <= '0';
                        m_axi_wvalid_i <= '0';
                        m_axi_wlast_i <= '0';
                        m_axi_bready_i <= '0';
                        m_axi_arvalid_i <= '0';
                        m_axi_rready_i <= '0';
                        if respq_full = '0' and respq_wr_rst_busy = '0' then
                            respq_wr_data <= resp_code & resp_rdata;
                            respq_wr_en_i <= '1';
                            axi_state <= ST_IDLE;
                        end if;

                    when ST_TIMEOUT_ERR =>
                        m_axi_awvalid_i <= '0';
                        m_axi_wvalid_i <= '0';
                        m_axi_wlast_i <= '0';
                        m_axi_bready_i <= '0';
                        m_axi_arvalid_i <= '0';
                        m_axi_rready_i <= '0';
                        if respq_full = '0' and respq_wr_rst_busy = '0' then
                            respq_wr_data <= "10" & std_logic_vector(to_unsigned(0, DATA_W));
                            respq_wr_en_i <= '1';
                            axi_state <= ST_IDLE;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture rtl;
