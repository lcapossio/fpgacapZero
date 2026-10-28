// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

`timescale 1ns/1ps
`include "fcapz_version.vh"

// Active-slot manager for mixed debug cores behind one JTAG USER chain.
//
// The manager owns 0xF000..0xF0FF.  All other addresses are routed to the
// active slot, which exposes its native register map at 0x0000.  Slots without
// burst support (for example EIO) simply return idle/zero burst controls.
//
// Resets.  jtag_rst is the hub's power-up reset; MGR_CTRL bit 0 adds a soft
// one.  Together they clear ACTIVE, DESC_INDEX, MGR_OWNER and the burst owner.
// proto_rst resets the burst start event, which must stay paired with the
// pipe's last-seen copy, so it is the pipe's own reset (power-up, or TAP
// Test-Logic-Reset).  Slots are reset only through their own domains
// (slot_rst_req); the epoch counters below survive every reset so the host can
// tell that one happened.  An epoch is {releases, held}: bit 0 is the reset's
// level, so an odd epoch means that reset is held now, and each release adds
// 2.  The LSB is the level rather than a count of edges, so the parity holds
// even where the flow drops initial values (PolarFire powers these up
// random); a reset still held when the host looked changes the epoch again
// on release.  MGR_TLR_COUNT counts the TAP's entries into Test-Logic-Reset
// that the manager sees happen: tlr_d powers up high, so a TAP already in
// Test-Logic-Reset at configuration is not counted.  MGR_SELECT_COUNT counts every
// MGR_ACTIVE write, accepted or not, from any controller: a host that counts
// its own writes tells from the difference that another controller selected a
// slot, even one that selected its slot back.

module fcapz_core_manager #(
    parameter NUM_SLOTS = 2,
    parameter SAMPLE_W = 8,
    parameter TIMESTAMP_W = 0,
    parameter DEPTH = 1024,
    parameter [NUM_SLOTS*16-1:0] SLOT_CORE_IDS = {NUM_SLOTS{16'h0000}},
    parameter [NUM_SLOTS-1:0] SLOT_HAS_BURST = {NUM_SLOTS{1'b0}},
    // The burst adapter loads burst_header into the priming scan (MGR_CAPS
    // bit 4).
    parameter HEADER_EN = 0,
    // Test-Logic-Reset drives proto_rst (MGR_CAPS bit 6).  Only reported here:
    // the adapter builds proto_rst.
    parameter TLR_RESET_EN = 0
) (
    input  wire                       jtag_clk,
    input  wire                       jtag_rst,
    input  wire                       proto_rst,
    // TAP in Test-Logic-Reset, synchronised to jtag_clk; counted only.
    input  wire                       tlr,

    input  wire                       jtag_wr_en,
    input  wire                       jtag_rd_en,
    input  wire [15:0]                jtag_addr,
    input  wire [31:0]                jtag_wdata,
    output wire [31:0]                jtag_rdata,

    output wire [NUM_SLOTS-1:0]       slot_wr_en,
    output wire [NUM_SLOTS-1:0]       slot_rd_en,
    output wire [NUM_SLOTS*16-1:0]    slot_addr,
    output wire [NUM_SLOTS*32-1:0]    slot_wdata,
    input  wire [NUM_SLOTS*32-1:0]    slot_rdata,
    // Each slot's register-side reset (jtag_clk domain), counted per slot.
    input  wire [NUM_SLOTS-1:0]       slot_rst,
    // One-jtag_clk reset requests from MGR_CTRL bits 1-2.
    output wire [NUM_SLOTS-1:0]       slot_rst_req,

    input  wire [$clog2(DEPTH)-1:0]   burst_rd_addr,
    input  wire                       burst_rd_active,
    output wire [NUM_SLOTS*$clog2(DEPTH)-1:0] slot_burst_rd_addr,
    output wire [NUM_SLOTS-1:0]       slot_burst_rd_active,
    input  wire [NUM_SLOTS*SAMPLE_W-1:0] slot_burst_rd_data,
    input  wire [NUM_SLOTS*((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] slot_burst_rd_ts_data,
    // Not used: the manager raises the start event itself (burst_start_r).
    // Kept so every wrapper still connects the slots' flags unchanged.
    input  wire [NUM_SLOTS-1:0]       slot_burst_start,
    input  wire [NUM_SLOTS-1:0]       slot_burst_timestamp,
    input  wire [NUM_SLOTS*$clog2(DEPTH)-1:0] slot_burst_start_ptr,
    output wire [SAMPLE_W-1:0]        burst_rd_data,
    output wire [((TIMESTAMP_W > 0) ? TIMESTAMP_W : 1)-1:0] burst_rd_ts_data,
    output wire                       burst_start,
    output wire                       burst_timestamp,
    output wire [$clog2(DEPTH)-1:0]   burst_start_ptr,
    // Describes the burst the pipe is about to send; see docs/specs.
    output wire [159:0]               burst_header
);

    localparam IDX_W = (NUM_SLOTS <= 2) ? 1 : $clog2(NUM_SLOTS);
    localparam PTR_W = $clog2(DEPTH);
    localparam TS_W_SAFE = (TIMESTAMP_W > 0) ? TIMESTAMP_W : 1;
    localparam [15:0] MANAGER_CORE_ID = 16'h434D; // ASCII "CM"
    localparam [31:0] MANAGER_VERSION =
        {`FCAPZ_VERSION_MAJOR, `FCAPZ_VERSION_MINOR, MANAGER_CORE_ID};
    localparam [15:0] HEADER_MAGIC = 16'h4248;    // ASCII "BH"
    localparam [15:0] HEADER_SAMPLE_W = SAMPLE_W;
    // bit0 active-slot, bit1 descriptors, bit2 the manager raises the burst
    // start on every BURST_PTR write (safe across slot switches), bit3 epochs
    // and MGR_OWNER, bit4 burst header, bit5 MGR_CTRL and per-slot resets,
    // bit6 Test-Logic-Reset resets the burst protocol, bit7 MGR_SELECT_COUNT
    localparam [31:0] MANAGER_CAPS = 32'h0000_00AF
        | ((HEADER_EN != 0) ? 32'h10 : 32'h0)
        | ((TLR_RESET_EN != 0) ? 32'h40 : 32'h0);

    localparam ADDR_MGR_VERSION = 16'hF000;
    localparam ADDR_MGR_COUNT   = 16'hF004;
    localparam ADDR_MGR_ACTIVE  = 16'hF008;
    localparam ADDR_MGR_STRIDE  = 16'hF00C;
    localparam ADDR_MGR_CAPS    = 16'hF010;
    localparam ADDR_MGR_DESC_INDEX = 16'hF014;
    localparam ADDR_MGR_DESC_CORE  = 16'hF018;
    localparam ADDR_MGR_DESC_CAPS  = 16'hF01C;
    localparam ADDR_MGR_EPOCH      = 16'hF020;
    localparam ADDR_MGR_OWNER      = 16'hF024;
    localparam ADDR_MGR_CTRL       = 16'hF028;
    localparam ADDR_MGR_SLOT_EPOCH = 16'hF02C;
    localparam ADDR_MGR_TLR_COUNT  = 16'hF030;
    localparam ADDR_MGR_SELECT_COUNT = 16'hF034;
    localparam ADDR_BURST_PTR   = 16'h002C;

    reg [IDX_W-1:0] active_idx;
    reg [IDX_W-1:0] desc_idx;
    reg [31:0]      owner;
    reg [IDX_W-1:0] burst_owner_idx;
    reg             burst_owner_valid;
    reg             burst_rd_active_d;
    // The burst start event the pipe sees. The manager owns it rather than
    // passing on the owner slot's own toggle: the pipe keeps ONE last-seen
    // copy, so after the owner changes, the new slot's toggle can equal the
    // old slot's and the start is missed -- the pipe then reads the new
    // slot's memory from the previous burst's pointer, silently.
    reg             burst_start_r;

    // Not reset by anything they drive or count; power-up values only.
    reg                 mgr_rst_req;
    reg [NUM_SLOTS-1:0] slot_rst_req_r;
    reg                 mgr_rst_d;
    reg [14:0]          mgr_releases;
    reg [NUM_SLOTS-1:0] slot_rst_d;
    reg [NUM_SLOTS*15-1:0] slot_releases;
    reg                 tlr_d;
    reg [15:0]          tlr_count;
    reg [15:0]          select_count;

    initial begin
        mgr_rst_req = 1'b0;
        slot_rst_req_r = {NUM_SLOTS{1'b0}};
        mgr_rst_d = 1'b0;
        mgr_releases = 15'h0;
        slot_rst_d = {NUM_SLOTS{1'b0}};
        slot_releases = {NUM_SLOTS{15'h0}};
        tlr_d = 1'b1;
        tlr_count = 16'h0;
        select_count = 16'h0;
    end

    wire [15:0] mgr_epoch = {mgr_releases, mgr_rst_d};
    wire [NUM_SLOTS*16-1:0] slot_epoch;
    genvar e;
    generate
        for (e = 0; e < NUM_SLOTS; e = e + 1) begin : g_epochs
            assign slot_epoch[e*16 +: 16] = {slot_releases[e*15 +: 15], slot_rst_d[e]};
        end
    endgenerate

    wire mgr_rst = jtag_rst | mgr_rst_req;
    wire burst_rst = mgr_rst | proto_rst;

    wire manager_hit = (jtag_addr[15:8] == 8'hF0);
    wire requested_idx_valid = (jtag_wdata < NUM_SLOTS);
    wire [NUM_SLOTS-1:0] active_onehot = {{(NUM_SLOTS-1){1'b0}}, 1'b1} << active_idx;
    wire [IDX_W-1:0] burst_mux_idx = burst_owner_valid ? burst_owner_idx : active_idx;
    wire burst_ptr_wr = jtag_wr_en && !manager_hit && jtag_addr == ADDR_BURST_PTR
                        && SLOT_HAS_BURST[active_idx];
    wire ctrl_wr = jtag_wr_en && jtag_addr == ADDR_MGR_CTRL;

    always @(posedge jtag_clk or posedge mgr_rst) begin
        if (mgr_rst) begin
            active_idx <= {IDX_W{1'b0}};
            desc_idx <= {IDX_W{1'b0}};
            owner <= 32'h0;
        end else if (jtag_wr_en) begin
            if (jtag_addr == ADDR_MGR_ACTIVE) begin
                // Once an owner is bound the burst mux follows it, not
                // ACTIVE, so a switch during a preload is safe to take.
                if (requested_idx_valid && (burst_owner_valid || !burst_rd_active))
                    active_idx <= jtag_wdata[IDX_W-1:0];
            end else if (jtag_addr == ADDR_MGR_DESC_INDEX) begin
                if (requested_idx_valid)
                    desc_idx <= jtag_wdata[IDX_W-1:0];
            end else if (jtag_addr == ADDR_MGR_OWNER) begin
                owner <= jtag_wdata;
            end
        end
    end

    always @(posedge jtag_clk or posedge burst_rst) begin
        if (burst_rst) begin
            burst_owner_idx <= {IDX_W{1'b0}};
            burst_owner_valid <= 1'b0;
            burst_rd_active_d <= 1'b0;
        end else begin
            burst_rd_active_d <= burst_rd_active;
            if (burst_ptr_wr) begin
                burst_owner_idx <= active_idx;
                burst_owner_valid <= 1'b1;
            end else if (burst_rd_active && !burst_rd_active_d && !burst_owner_valid) begin
                // A burst with no BURST_PTR write since reset binds the active
                // slot once.  Later preloads keep the bound owner: an ACTIVE
                // write between bursts must not move the burst to another slot.
                burst_owner_idx <= active_idx;
                burst_owner_valid <= 1'b1;
            end
        end
    end

    always @(posedge jtag_clk or posedge proto_rst) begin
        if (proto_rst)
            burst_start_r <= 1'b0;
        else if (burst_ptr_wr)
            // Same edge the slot latches its start pointer and toggles
            // its own flag, so pointer and event reach the pipe together.
            burst_start_r <= ~burst_start_r;
    end

    // One-cycle reset requests; the epochs count the releases of each reset.
    always @(posedge jtag_clk) begin : reset_events
        integer i;  // block-local: a shared one gets a driver per block
        mgr_rst_req <= ctrl_wr && jtag_wdata[0];
        for (i = 0; i < NUM_SLOTS; i = i + 1)
            slot_rst_req_r[i] <= ctrl_wr
                && (jtag_wdata[2] || (jtag_wdata[1] && desc_idx == i[IDX_W-1:0]));

        mgr_rst_d <= mgr_rst;
        if (mgr_rst_d && !mgr_rst)
            mgr_releases <= mgr_releases + 15'd1;
        slot_rst_d <= slot_rst;
        for (i = 0; i < NUM_SLOTS; i = i + 1)
            if (slot_rst_d[i] && !slot_rst[i])
                slot_releases[i*15 +: 15] <= slot_releases[i*15 +: 15] + 15'd1;
        tlr_d <= tlr;
        if (tlr && !tlr_d)
            tlr_count <= tlr_count + 16'd1;
        if (jtag_wr_en && jtag_addr == ADDR_MGR_ACTIVE)
            select_count <= select_count + 16'd1;
    end

    genvar g;
    generate
        for (g = 0; g < NUM_SLOTS; g = g + 1) begin : g_slots
            assign slot_wr_en[g] = jtag_wr_en & ~manager_hit & active_onehot[g];
            assign slot_rd_en[g] = jtag_rd_en & ~manager_hit & active_onehot[g];
            assign slot_addr[g*16 +: 16] = jtag_addr;
            assign slot_wdata[g*32 +: 32] = jtag_wdata;
            assign slot_burst_rd_addr[g*PTR_W +: PTR_W] = burst_rd_addr;
            assign slot_burst_rd_active[g] = burst_rd_active
                                             & (burst_mux_idx == g[IDX_W-1:0])
                                             & SLOT_HAS_BURST[g];
        end
    endgenerate
    assign slot_rst_req = slot_rst_req_r;

    reg [31:0] active_rdata;
    reg [SAMPLE_W-1:0] active_burst_data;
    reg [TS_W_SAFE-1:0] active_burst_ts_data;
    reg active_burst_timestamp;
    reg [PTR_W-1:0] active_burst_start_ptr;
    reg [15:0] burst_slot_epoch;

    always @(*) begin : active_mux
        integer i;
        active_rdata = 32'h0;
        active_burst_data = {SAMPLE_W{1'b0}};
        active_burst_ts_data = {TS_W_SAFE{1'b0}};
        active_burst_timestamp = 1'b0;
        active_burst_start_ptr = {PTR_W{1'b0}};
        burst_slot_epoch = 16'h0;
        for (i = 0; i < NUM_SLOTS; i = i + 1) begin
            if (active_idx == i[IDX_W-1:0]) begin
                active_rdata = slot_rdata[i*32 +: 32];
            end
            if (burst_mux_idx == i[IDX_W-1:0]) begin
                burst_slot_epoch = slot_epoch[i*16 +: 16];
                if (SLOT_HAS_BURST[i]) begin
                    active_burst_data = slot_burst_rd_data[i*SAMPLE_W +: SAMPLE_W];
                    active_burst_ts_data = slot_burst_rd_ts_data[i*TS_W_SAFE +: TS_W_SAFE];
                    active_burst_timestamp = slot_burst_timestamp[i];
                    active_burst_start_ptr = slot_burst_start_ptr[i*PTR_W +: PTR_W];
                end
            end
        end
    end

    reg [15:0] desc_core_id;
    reg desc_has_burst;
    reg [15:0] desc_epoch;
    always @(*) begin : desc_mux
        integer i;
        desc_core_id = 16'h0000;
        desc_has_burst = 1'b0;
        desc_epoch = 16'h0;
        for (i = 0; i < NUM_SLOTS; i = i + 1) begin
            if (desc_idx == i[IDX_W-1:0]) begin
                desc_core_id = SLOT_CORE_IDS[i*16 +: 16];
                desc_has_burst = SLOT_HAS_BURST[i];
                desc_epoch = slot_epoch[i*16 +: 16];
            end
        end
    end

    reg [31:0] manager_rdata;
    always @(*) begin
        case (jtag_addr)
            ADDR_MGR_VERSION: manager_rdata = MANAGER_VERSION;
            ADDR_MGR_COUNT:   manager_rdata = NUM_SLOTS;
            ADDR_MGR_ACTIVE:  manager_rdata = {{(32-IDX_W){1'b0}}, active_idx};
            ADDR_MGR_STRIDE:  manager_rdata = 32'h0;
            ADDR_MGR_CAPS:    manager_rdata = MANAGER_CAPS;
            ADDR_MGR_DESC_INDEX: manager_rdata = {{(32-IDX_W){1'b0}}, desc_idx};
            ADDR_MGR_DESC_CORE:  manager_rdata = {16'h0, desc_core_id};
            ADDR_MGR_DESC_CAPS:  manager_rdata = {31'h0, desc_has_burst};
            ADDR_MGR_EPOCH:      manager_rdata = {16'h0, mgr_epoch};
            ADDR_MGR_OWNER:      manager_rdata = owner;
            ADDR_MGR_SLOT_EPOCH: manager_rdata = {16'h0, desc_epoch};
            ADDR_MGR_TLR_COUNT:  manager_rdata = {16'h0, tlr_count};
            ADDR_MGR_SELECT_COUNT: manager_rdata = {16'h0, select_count};
            default:          manager_rdata = 32'h0;
        endcase
    end

    assign jtag_rdata = manager_hit ? manager_rdata : active_rdata;
    assign burst_rd_data = active_burst_data;
    assign burst_rd_ts_data = active_burst_ts_data;
    assign burst_start = burst_start_r;
    assign burst_timestamp = active_burst_timestamp;
    assign burst_start_ptr = active_burst_start_ptr;
    assign burst_header = {
        HEADER_SAMPLE_W,                                    // [159:144]
        owner,                                              // [143:112]
        burst_slot_epoch,                                   // [111:96]
        mgr_epoch,                                          // [95:80]
        15'h0, active_burst_timestamp,                      // [79:64]
        {{(32-PTR_W){1'b0}}, active_burst_start_ptr},       // [63:32]
        {{(16-IDX_W){1'b0}}, burst_mux_idx},                // [31:16]
        HEADER_MAGIC                                        // [15:0]
    };

endmodule
