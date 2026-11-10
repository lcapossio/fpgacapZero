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
    -- Internal only: the TCK side queues the first BURST_WDATA after a
    -- BURST_SETUP under this code, so the AXI side can tell a new burst from
    -- continuation data.  The DR never accepts x"B" (it decodes as a NOP).
    constant CMD_BURST_WFIRST : std_logic_vector(3 downto 0) := x"B";
    constant CMD_CONFIG       : std_logic_vector(3 downto 0) := x"E";
    constant CMD_RESET        : std_logic_vector(3 downto 0) := x"F";

    constant CFG_VERSION       : std_logic_vector(15 downto 0) := x"0000";
    constant CFG_VERSION_ALIAS : std_logic_vector(15 downto 0) := x"0004";
    constant CFG_FEATURES      : std_logic_vector(15 downto 0) := x"002C";
    constant CFG_AXI_STATUS    : std_logic_vector(15 downto 0) := x"0030";
    constant FIFO_DEPTH_ENC : std_logic_vector(7 downto 0) :=
        std_logic_vector(to_unsigned(FIFO_DEPTH - 1, 8));
    -- [25] = bus-safe writes (buffered bursts, held VALIDs, owned B, burst
    -- checks, CFG_AXI_STATUS); [24] = streaming read (Verilog only, 0 here).
    constant FEATURES : std_logic_vector(31 downto 0) :=
        x"02" & FIFO_DEPTH_ENC &
        std_logic_vector(to_unsigned(DATA_W, 8)) &
        std_logic_vector(to_unsigned(ADDR_W, 8));

    constant WB_W : positive := DATA_W + DATA_BYTES;

    -- Burst descriptor check, before any VALID goes up: transfer size within
    -- the bus, burst type not reserved, FIXED at most 16 beats, WRAP of 2, 4,
    -- 8 or 16 beats from a size-aligned address, INCR inside one 4 KB page
    -- counted from the size-aligned start.
    function burst_ok(addr  : std_logic_vector;
                      len   : std_logic_vector(7 downto 0);
                      size  : std_logic_vector(2 downto 0);
                      btype : std_logic_vector(1 downto 0)) return boolean is
        variable bytes : natural;
        variable l     : natural;
        variable a0    : natural;
        variable low   : natural;
    begin
        bytes := 2 ** to_integer(unsigned(size));
        l := to_integer(unsigned(len));
        if bytes > DATA_BYTES then
            return false;
        end if;
        low := to_integer(unsigned(addr(addr'right + 11 downto addr'right)));
        a0 := low - (low mod bytes);
        case btype is
            when "00" => return l <= 15;
            when "01" => return a0 + (l + 1) * bytes <= 4096;
            when "10" => return (l = 1 or l = 3 or l = 7 or l = 15) and (low mod bytes) = 0;
            when others => return false;
        end case;
    end function;

    type axi_state_t is (
        ST_IDLE,
        ST_W_WAIT,
        ST_AR,
        ST_WAIT_R,
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

    signal fifo_wr_en_i : std_logic;
    signal fifo_full : std_logic;
    signal fifo_rd_en_i : std_logic := '0';
    signal fifo_rdata : std_logic_vector(DATA_W - 1 downto 0);
    signal fifo_empty : std_logic;
    signal fifo_rd_count : std_logic_vector(FIFO_AW downto 0);
    signal fifo_rd_count8 : std_logic_vector(7 downto 0);
    signal fifo_rst_tck : std_logic := '0';
    signal fifo_rst_axi : std_logic := '0';

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
    signal m_axi_rready_o : std_logic;
    -- Discard the rest of a read cut off by RESET or an R timeout.
    signal r_drain : std_logic := '0';
    -- Cycles without a beat while draining (saturates at TIMEOUT - 1).
    signal drain_cnt : unsigned(31 downto 0) := (others => '0');
    -- A read the slave has accepted and not finished (see r_drain).
    signal r_inflight : std_logic;
    -- ARVALID left up by a timeout or RESET, held to its handshake.
    signal ar_orphan : std_logic := '0';
    signal ar_hs : std_logic;
    signal rd_busy : std_logic;
    signal chan_busy : std_logic;

    -- Write path.  A write reaches the bus only once all its beats are in
    -- wbuf: a burst is collected beat by beat (each acknowledged as it
    -- arrives) and an incomplete one is discarded with no bus activity.  The
    -- write engine then owns AW/W/B until the slave's B, whatever the host or
    -- CMD_RESET do meanwhile (we_detached: finish, report nothing).
    type wbuf_t is array (0 to FIFO_DEPTH - 1) of std_logic_vector(WB_W - 1 downto 0);
    signal wbuf : wbuf_t;
    signal wbuf_q : std_logic_vector(WB_W - 1 downto 0) := (others => '0');
    signal wb_we : std_logic := '0';
    signal wb_wa : unsigned(8 downto 0) := (others => '0');
    signal wb_wd : std_logic_vector(WB_W - 1 downto 0) := (others => '0');
    signal wb_collecting : std_logic := '0';
    signal wb_bad : std_logic := '0';
    signal wb_cnt : unsigned(8 downto 0) := (others => '0');
    signal wb_addr : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal wb_len : std_logic_vector(7 downto 0) := (others => '0');
    signal wb_size : std_logic_vector(2 downto 0) := "010";
    signal wb_type : std_logic_vector(1 downto 0) := "01";
    signal we_start : std_logic := '0';
    signal we_detach : std_logic := '0';
    signal we_d_addr : std_logic_vector(ADDR_W - 1 downto 0) := (others => '0');
    signal we_d_len : std_logic_vector(7 downto 0) := (others => '0');
    signal we_d_size : std_logic_vector(2 downto 0) := "010";
    signal we_d_type : std_logic_vector(1 downto 0) := "01";
    signal we_busy : std_logic := '0';
    signal we_detached : std_logic := '0';
    signal we_aw_done : std_logic := '0';
    signal we_w_idx : unsigned(8 downto 0) := (others => '0');
    signal we_w_done : unsigned(8 downto 0) := (others => '0');
    signal we_len : unsigned(7 downto 0) := (others => '0');
    signal we_rd_ok : std_logic := '0';
    signal we_done : std_logic := '0';
    signal we_bresp : std_logic_vector(1 downto 0) := "00";
    signal we_progress : std_logic := '0';
    signal axi_owed : std_logic := '0';  -- registered chan_busy (CFG_AXI_STATUS[5])
    signal axi_status_axi : std_logic_vector(5 downto 0);
    signal axi_status_sync1_tck : std_logic_vector(5 downto 0) := (others => '0');
    signal axi_status_sync2_tck : std_logic_vector(5 downto 0) := (others => '0');

    signal reset_req_toggle : std_logic := '0';
    signal reset_req_sync1_axi : std_logic := '0';
    signal reset_req_sync2_axi : std_logic := '0';
    signal reset_req_seen_axi : std_logic := '0';
    signal reset_ack_toggle_axi : std_logic := '0';
    signal reset_ack_sync1_tck : std_logic := '0';
    signal reset_ack_sync2_tck : std_logic := '0';
    signal reset_busy_tck : std_logic;

    -- TCK-domain reset: axi_rst asserts it at once, and it releases on the
    -- second TCK edge after axi_rst ends. It resets the TCK sides of the async
    -- FIFOs (so their release is synchronous to TCK) and the TCK command
    -- state, so no queued command outlives a reset. That includes power-up on
    -- devices that drop register initial values (PolarFire), where axi_rst
    -- comes from the device power-on reset.
    signal tck_rst_sync : std_logic_vector(1 downto 0) := "11";
    signal tck_rst : std_logic;
    attribute ASYNC_REG : string;
    attribute ASYNC_REG of tck_rst_sync : signal is "TRUE";
    attribute ASYNC_REG of reset_req_sync1_axi : signal is "TRUE";
    attribute ASYNC_REG of reset_req_sync2_axi : signal is "TRUE";
    attribute ASYNC_REG of reset_ack_sync1_tck : signal is "TRUE";
    attribute ASYNC_REG of reset_ack_sync2_tck : signal is "TRUE";
    attribute ASYNC_REG of axi_status_sync1_tck : signal is "TRUE";
    attribute ASYNC_REG of axi_status_sync2_tck : signal is "TRUE";

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
    -- Burst fill: ready is the FIFO's own not-full, and the write is the
    -- handshake itself, so every accepted beat is written exactly once.  A
    -- registered ready stayed high in the cycle the FIFO filled and dropped
    -- that beat; a registered write lagged the full flag by a cycle.
    m_axi_rready_o <= '1' when r_drain = '1' else
                      not fifo_full when axi_state = ST_BURST_R_FILL else
                      m_axi_rready_i;
    m_axi_rready <= m_axi_rready_o;
    ar_hs <= m_axi_arvalid_i and m_axi_arready;
    r_inflight <= '1' when axi_state = ST_WAIT_R or axi_state = ST_BURST_R_FILL or
                           ar_hs = '1' else '0';
    -- Read channel owes something: beats of an accepted read, or an AR held
    -- after a timeout/RESET.  Write channel owes something: we_busy.
    rd_busy <= r_drain or ar_orphan;
    chan_busy <= r_drain or ar_orphan or we_busy;
    -- CFG_AXI_STATUS bits: flags, each a flop, synced per bit.  Bits can pass
    -- the synchronizers a TCK apart (an AR handed from ar_orphan to r_drain
    -- may show neither for a moment), so "anything owed" is its own flop,
    -- axi_owed, which stays high across such hand-overs; hosts test it.
    axi_status_axi <= axi_owed & wb_collecting & r_drain & ar_orphan & we_detached & we_busy;

    p_owed : process(axi_clk, axi_rst)
    begin
        if axi_rst = '1' then
            axi_owed <= '0';
        elsif rising_edge(axi_clk) then
            axi_owed <= chan_busy;
        end if;
    end process;
    fifo_wr_en_i <= '1' when axi_state = ST_BURST_R_FILL and m_axi_rvalid = '1'
                             and fifo_full = '0' else '0';

    debug_tck <= (others => '0');
    debug_tck_edge <= (others => '0');
    debug_axi <= (others => '0');
    debug_axi_edge <= (others => '0');

    reset_busy_tck <= '1' when reset_req_toggle /= reset_ack_sync2_tck else '0';

    p_tck_rst : process(tck, axi_rst)
    begin
        if axi_rst = '1' then
            tck_rst_sync <= "11";
        elsif rising_edge(tck) then
            tck_rst_sync <= tck_rst_sync(0) & '0';
        end if;
    end process;
    tck_rst <= tck_rst_sync(1);
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
            wr_rst => tck_rst or cmdq_rst_tck,
            wr_en => cmdq_wr_en_i and not tck_rst,
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
            rd_rst => tck_rst or respq_rst_tck,
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
            wr_data => m_axi_rdata,
            wr_full => fifo_full,
            wr_rst_busy => open,
            rd_clk => tck,
            rd_rst => tck_rst or fifo_rst_tck,
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
            axi_status_sync1_tck <= axi_status_axi;
            axi_status_sync2_tck <= axi_status_sync1_tck;

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
                                if burst_w_beats_left = resize(unsigned(burst_awlen), 9) + 1 then
                                    -- First beat after BURST_SETUP.
                                    cmdq_wr_data(CMDQ_W - 1 downto CMDQ_W - 4) <= CMD_BURST_WFIRST;
                                else
                                    cmdq_wr_data(CMDQ_W - 1 downto CMDQ_W - 4) <= CMD_BURST_WDATA;
                                end if;
                                cmdq_wr_data(CMDQ_W - 5 downto 0) <= burst_addr &
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
                                -- [0] write engine busy, [1] it finishes a write
                                -- nobody waits for, [2] AR held after a timeout or
                                -- RESET, [3] read beats being drained, [4] burst
                                -- write being collected, [5] anything owed to the
                                -- slave ([0]|[2]|[3]).
                                when CFG_AXI_STATUS =>
                                    config_rdata <= x"000000" & "00" & axi_status_sync2_tck;
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

            -- tck_rst (axi_rst, synchronized to TCK) clears the same TCK
            -- state as CMD_RESET. Last in the process, so it overrides every
            -- assignment above. The FIFOs' TCK sides are held by tck_rst
            -- directly. The CMD_RESET request toggle is left alone: this
            -- process only runs on TCK edges, so clearing it here could flip
            -- it after the AXI side is out of reset and request a second
            -- reset; the AXI side rejoins the handshake from its own axi_rst.
            if tck_rst = '1' then
                cmdq_wr_en_i <= '0';
                respq_rd_en_i <= '0';
                fifo_rd_en_i <= '0';
                error_sticky <= '0';
                prev_valid <= '0';
                pending_count <= (others => '0');
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
            end if;
        end if;
    end process;

    -- ---- Write buffer -------------------------------------------------------
    -- Written one cycle after dispatch (wb_we), never while the engine may
    -- still read it.  wbuf_q is a registered read, so the buffer can map to
    -- block or distributed RAM.
    p_wbuf : process(axi_clk)
    begin
        if rising_edge(axi_clk) then
            if wb_we = '1' then
                wbuf(to_integer(wb_wa) mod FIFO_DEPTH) <= wb_wd;
            end if;
            wbuf_q <= wbuf(to_integer(we_w_idx) mod FIFO_DEPTH);
        end if;
    end process;

    -- ---- Write engine -------------------------------------------------------
    -- Owns AW, W and B for one write at a time.  AW and W are independent (W
    -- may complete first); each VALID and its payload stay unchanged until its
    -- handshake; exactly we_len + 1 beats go out, WLAST on the last; the B is
    -- always taken.  Only axi_rst stops it.  A detached write (host timeout or
    -- CMD_RESET) completes the same way and reports nothing.
    p_wengine : process(axi_clk, axi_rst)
        variable w_done_nxt : unsigned(8 downto 0);
    begin
        if axi_rst = '1' then
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
            we_busy <= '0';
            we_detached <= '0';
            we_aw_done <= '0';
            we_w_idx <= (others => '0');
            we_w_done <= (others => '0');
            we_len <= (others => '0');
            we_rd_ok <= '0';
            we_done <= '0';
            we_bresp <= "00";
            we_progress <= '0';
        elsif rising_edge(axi_clk) then
            we_done <= '0';
            we_progress <= '0';
            we_rd_ok <= '1';  -- we_w_idx held a cycle: wbuf_q is its beat
            if we_busy = '0' then
                if we_start = '1' then
                    m_axi_awaddr_i <= we_d_addr;
                    m_axi_awlen_i <= we_d_len;
                    m_axi_awsize_i <= we_d_size;
                    m_axi_awburst_i <= we_d_type;
                    m_axi_awvalid_i <= '1';
                    we_busy <= '1';
                    we_detached <= '0';
                    we_aw_done <= '0';
                    we_w_idx <= (others => '0');
                    we_w_done <= (others => '0');
                    we_len <= unsigned(we_d_len);
                    we_rd_ok <= '0';
                end if;
            else
                if we_detach = '1' then
                    we_detached <= '1';
                end if;
                if m_axi_awvalid_i = '1' and m_axi_awready = '1' then
                    m_axi_awvalid_i <= '0';
                    we_aw_done <= '1';
                    we_progress <= '1';
                end if;
                if m_axi_wvalid_i = '1' and m_axi_wready = '1' then
                    m_axi_wvalid_i <= '0';
                    m_axi_wlast_i <= '0';
                    we_w_done <= we_w_done + 1;
                    we_progress <= '1';
                elsif m_axi_wvalid_i = '0' and we_w_idx <= resize(we_len, 9) and
                      we_rd_ok = '1' then
                    m_axi_wdata_i <= wbuf_q(DATA_W - 1 downto 0);
                    m_axi_wstrb_i <= wbuf_q(WB_W - 1 downto DATA_W);
                    m_axi_wvalid_i <= '1';
                    if we_w_idx = resize(we_len, 9) then
                        m_axi_wlast_i <= '1';
                    else
                        m_axi_wlast_i <= '0';
                    end if;
                    we_w_idx <= we_w_idx + 1;
                    we_rd_ok <= '0';
                end if;
                -- B once AW and every beat are through.
                if we_aw_done = '1' and we_w_done = resize(we_len, 9) + 1 then
                    m_axi_bready_i <= '1';
                end if;
                if m_axi_bready_i = '1' and m_axi_bvalid = '1' then
                    m_axi_bready_i <= '0';
                    we_busy <= '0';
                    we_detached <= '0';
                    we_progress <= '1';
                    if we_detached = '0' and we_detach = '0' then
                        we_done <= '1';
                        we_bresp <= m_axi_bresp;
                    end if;
                end if;
            end if;
        end if;
    end process;

    -- ---- AXI master FSM -----------------------------------------------------
    p_axi : process(axi_clk, axi_rst)
        variable cmd_cmd : std_logic_vector(3 downto 0);
        variable cmd_addr : std_logic_vector(ADDR_W - 1 downto 0);
        variable cmd_wdata : std_logic_vector(DATA_W - 1 downto 0);
        variable cmd_wstrb : std_logic_vector(DATA_BYTES - 1 downto 0);
        variable cmd_len : std_logic_vector(7 downto 0);
        variable cmd_size : std_logic_vector(2 downto 0);
        variable cmd_burst : std_logic_vector(1 downto 0);
        variable wfirst_bad : boolean;
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
            m_axi_araddr_i <= (others => '0');
            m_axi_arlen_i <= (others => '0');
            m_axi_arsize_i <= "010";
            m_axi_arburst_i <= "01";
            m_axi_arvalid_i <= '0';
            m_axi_rready_i <= '0';
            r_drain <= '0';
            ar_orphan <= '0';
            drain_cnt <= (others => '0');
            cmdq_rd_en_i <= '0';
            respq_wr_en_i <= '0';
            cmdq_rst_axi <= '0';
            respq_rst_axi <= '0';
            fifo_rst_axi <= '0';
            reset_req_sync1_axi <= '0';
            reset_req_sync2_axi <= '0';
            reset_req_seen_axi <= '0';
            reset_ack_toggle_axi <= '0';
            wb_we <= '0';
            wb_wa <= (others => '0');
            wb_wd <= (others => '0');
            wb_collecting <= '0';
            wb_bad <= '0';
            wb_cnt <= (others => '0');
            wb_addr <= (others => '0');
            wb_len <= (others => '0');
            wb_size <= "010";
            wb_type <= "01";
            we_start <= '0';
            we_detach <= '0';
            we_d_addr <= (others => '0');
            we_d_len <= (others => '0');
            we_d_size <= "010";
            we_d_type <= "01";
        elsif rising_edge(axi_clk) then
            cmdq_rd_en_i <= '0';
            respq_wr_en_i <= '0';
            cmdq_rst_axi <= '0';
            respq_rst_axi <= '0';
            fifo_rst_axi <= '0';
            wb_we <= '0';
            we_start <= '0';
            we_detach <= '0';
            reset_req_sync1_axi <= reset_req_toggle;
            reset_req_sync2_axi <= reset_req_sync1_axi;
            -- The drain only ends at RLAST: a beat that arrives however late
            -- is still discarded.  While a channel is owed (drain, held AR,
            -- busy write engine) commands wait for it at most TIMEOUT cycles
            -- without progress (drain_cnt); after that they run, but a read
            -- answers SLVERR without an AR while the read channel is owed and
            -- a write answers SLVERR without an AW while the engine is busy
            -- (ST_IDLE), so a slave that never answers cannot wedge the
            -- bridge, and nothing owed to the slave is ever withdrawn.
            if r_drain = '1' and m_axi_rvalid = '1' and m_axi_rlast = '1' then
                r_drain <= '0';
            end if;
            if chan_busy = '0' or (r_drain = '1' and m_axi_rvalid = '1') or
               ar_hs = '1' or we_progress = '1' then
                drain_cnt <= (others => '0');
            elsif drain_cnt < to_unsigned(TIMEOUT - 1, drain_cnt'length) then
                drain_cnt <= drain_cnt + 1;
            end if;

            if reset_req_sync2_axi /= reset_req_seen_axi then
                -- CMD_RESET clears the host side only.  Whatever the slave
                -- is owed stays owed: a write in the engine is detached and
                -- finishes, an AR not yet accepted stays up (ar_orphan) and a
                -- read already accepted is drained (r_drain).
                reset_req_seen_axi <= reset_req_sync2_axi;
                reset_ack_toggle_axi <= reset_req_sync2_axi;
                axi_state <= ST_IDLE;
                timeout_cnt <= (others => '0');
                beat_count <= (others => '0');
                m_axi_rready_i <= '0';
                cmdq_rst_axi <= '1';
                respq_rst_axi <= '1';
                fifo_rst_axi <= '1';
                wb_collecting <= '0';
                wb_bad <= '0';
                we_detach <= '1';
                -- An AR the slave takes in this very cycle is done (its read
                -- is drained below); one it has not taken stays up.
                if ar_hs = '1' then
                    m_axi_arvalid_i <= '0';
                elsif m_axi_arvalid_i = '1' then
                    ar_orphan <= '1';
                end if;
                -- A read already accepted by the slave is drained, so its
                -- beats cannot land in the next command.
                if r_inflight = '1' and not (m_axi_rvalid = '1' and m_axi_rready_o = '1' and
                                             m_axi_rlast = '1') then
                    r_drain <= '1';
                end if;
            else
                case axi_state is
                    when ST_IDLE =>
                        m_axi_rready_i <= '0';
                        timeout_cnt <= (others => '0');
                        beat_count <= (others => '0');
                        if cmdq_empty = '0' and cmdq_rd_rst_busy = '0' and
                           (chan_busy = '0' or
                            drain_cnt >= to_unsigned(TIMEOUT - 1, drain_cnt'length)) then
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

                            -- Any command but continuation data ends a burst
                            -- being collected; its beats never reach the bus.
                            wb_collecting <= '0';
                            resp_rdata <= (others => '0');
                            -- Beat for wbuf (written next cycle, see p_wbuf):
                            -- a single write at 0, a burst beat at its index.
                            wb_wd <= cmd_wstrb & cmd_wdata;
                            if cmd_cmd = CMD_BURST_WDATA then
                                wb_wa <= wb_cnt;
                            else
                                wb_wa <= (others => '0');
                            end if;
                            wfirst_bad := we_busy = '1' or
                                          to_integer(unsigned(cmd_len)) >= FIFO_DEPTH or
                                          not burst_ok(cmd_addr, cmd_len, cmd_size, cmd_burst);

                            if cmd_cmd = CMD_WRITE then
                                if we_busy = '1' then
                                    resp_code <= "10";
                                    axi_state <= ST_DONE;
                                else
                                    wb_we <= '1';
                                    we_d_addr <= cmd_addr;
                                    we_d_len <= (others => '0');
                                    we_d_size <= "010";
                                    we_d_type <= "01";
                                    we_start <= '1';
                                    axi_state <= ST_W_WAIT;
                                end if;
                            elsif cmd_cmd = CMD_READ then
                                if rd_busy = '1' then
                                    -- Read channel still owed: no AR.
                                    axi_state <= ST_TIMEOUT_ERR;
                                else
                                    m_axi_araddr_i <= cmd_addr;
                                    m_axi_arlen_i <= (others => '0');
                                    m_axi_arsize_i <= "010";
                                    m_axi_arburst_i <= "01";
                                    m_axi_arvalid_i <= '1';
                                    axi_state <= ST_AR;
                                end if;
                            elsif cmd_cmd = CMD_BURST_WFIRST then
                                -- First beat of a burst: latch its descriptor.
                                -- A refused burst (bad descriptor, longer than
                                -- the buffer, engine busy) answers SLVERR for
                                -- every beat and never reaches the bus.
                                wb_addr <= cmd_addr;
                                wb_len <= cmd_len;
                                wb_size <= cmd_size;
                                wb_type <= cmd_burst;
                                wb_cnt <= to_unsigned(1, 9);
                                if we_busy = '0' and to_integer(unsigned(cmd_len)) < FIFO_DEPTH then
                                    wb_we <= '1';
                                end if;
                                if wfirst_bad then
                                    wb_bad <= '1';
                                    if unsigned(cmd_len) /= 0 then
                                        wb_collecting <= '1';
                                    end if;
                                    resp_code <= "10";
                                    axi_state <= ST_DONE;
                                elsif unsigned(cmd_len) = 0 then
                                    wb_bad <= '0';
                                    we_d_addr <= cmd_addr;
                                    we_d_len <= cmd_len;
                                    we_d_size <= cmd_size;
                                    we_d_type <= cmd_burst;
                                    we_start <= '1';
                                    axi_state <= ST_W_WAIT;
                                else
                                    wb_bad <= '0';
                                    wb_collecting <= '1';
                                    resp_code <= "00";
                                    axi_state <= ST_DONE;
                                end if;
                            elsif cmd_cmd = CMD_BURST_WDATA then
                                if wb_collecting = '1' and wb_bad = '0' and we_busy = '0' then
                                    wb_we <= '1';
                                end if;
                                if wb_collecting = '0' then
                                    -- Continuation data with no burst open.
                                    resp_code <= "10";
                                    axi_state <= ST_DONE;
                                elsif wb_cnt = resize(unsigned(wb_len), 9) then
                                    -- Last beat: the whole burst is buffered.
                                    if wb_bad = '1' then
                                        resp_code <= "10";
                                        axi_state <= ST_DONE;
                                    else
                                        we_d_addr <= wb_addr;
                                        we_d_len <= wb_len;
                                        we_d_size <= wb_size;
                                        we_d_type <= wb_type;
                                        we_start <= '1';
                                        axi_state <= ST_W_WAIT;
                                    end if;
                                else
                                    wb_collecting <= '1';
                                    wb_cnt <= wb_cnt + 1;
                                    if wb_bad = '1' then
                                        resp_code <= "10";
                                    else
                                        resp_code <= "00";
                                    end if;
                                    axi_state <= ST_DONE;
                                end if;
                            elsif cmd_cmd = CMD_BURST_RSTART then
                                if rd_busy = '1' then
                                    axi_state <= ST_TIMEOUT_ERR;
                                elsif not burst_ok(cmd_addr, cmd_len, cmd_size, cmd_burst) then
                                    resp_code <= "10";
                                    axi_state <= ST_DONE;
                                else
                                    m_axi_araddr_i <= cmd_addr;
                                    m_axi_arlen_i <= cmd_len;
                                    m_axi_arsize_i <= cmd_size;
                                    m_axi_arburst_i <= cmd_burst;
                                    m_axi_arvalid_i <= '1';
                                    axi_state <= ST_BURST_AR;
                                end if;
                            else
                                resp_code <= "00";
                                axi_state <= ST_DONE;
                            end if;
                        end if;

                    -- Write: wait for the engine's B.
                    when ST_W_WAIT =>
                        if we_done = '1' then
                            resp_code <= we_bresp;
                            resp_rdata <= (others => '0');
                            axi_state <= ST_DONE;
                        elsif we_progress = '1' then
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            -- No handshake for TIMEOUT cycles: answer SLVERR.
                            -- The engine keeps every VALID up and takes the B
                            -- whenever it comes, reporting nothing.
                            we_detach <= '1';
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
                            -- ARVALID stays up until the slave takes it.
                            ar_orphan <= '1';
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
                            -- The slave accepted the AR: drain the late
                            -- beat so it cannot land in a later read.
                            r_drain <= '1';
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_BURST_AR =>
                        if m_axi_arready = '1' then
                            m_axi_arvalid_i <= '0';
                            axi_state <= ST_BURST_R_FILL;
                            timeout_cnt <= (others => '0');
                        elsif timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                            ar_orphan <= '1';
                            axi_state <= ST_TIMEOUT_ERR;
                        else
                            timeout_cnt <= timeout_cnt + 1;
                        end if;

                    when ST_BURST_R_FILL =>
                        -- m_axi_rready and fifo_wr_en_i are concurrent here.
                        if m_axi_rvalid = '1' and fifo_full = '0' then
                            timeout_cnt <= (others => '0');
                            if m_axi_rlast = '1' then
                                resp_rdata <= m_axi_rdata;
                                resp_code <= m_axi_rresp;
                                axi_state <= ST_DONE;
                            end if;
                        elsif m_axi_rvalid = '0' then
                            if timeout_cnt >= to_unsigned(TIMEOUT - 1, timeout_cnt'length) then
                                -- Drain the rest of the burst: left on the R
                                -- channel it would become the first beats of
                                -- the next read with resp OKAY.
                                r_drain <= '1';
                                axi_state <= ST_TIMEOUT_ERR;
                            else
                                timeout_cnt <= timeout_cnt + 1;
                            end if;
                        end if;

                    when ST_DONE =>
                        m_axi_rready_i <= '0';
                        if respq_full = '0' and respq_wr_rst_busy = '0' then
                            respq_wr_data <= resp_code & resp_rdata;
                            respq_wr_en_i <= '1';
                            axi_state <= ST_IDLE;
                        end if;

                    when ST_TIMEOUT_ERR =>
                        m_axi_rready_i <= '0';
                        if respq_full = '0' and respq_wr_rst_busy = '0' then
                            respq_wr_data <= "10" & std_logic_vector(to_unsigned(0, DATA_W));
                            respq_wr_en_i <= '1';
                            axi_state <= ST_IDLE;
                        end if;
                end case;
            end if;

            -- An AR left up by a timeout or RESET: drop it at its handshake,
            -- whatever the FSM is doing, and drain the read it started.
            if ar_orphan = '1' and ar_hs = '1' then
                m_axi_arvalid_i <= '0';
                ar_orphan <= '0';
                r_drain <= '1';
            end if;
        end if;
    end process;
end architecture rtl;
