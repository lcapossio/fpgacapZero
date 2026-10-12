# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Shared host-side register constants."""

ADDR_MGR_ACTIVE = 0xF008

# Core-manager reset and ownership registers (MGR_CAPS bits 3, 5).
ADDR_MGR_EPOCH = 0xF020        # RO: hub reset edges (odd while held)
ADDR_MGR_OWNER = 0xF024        # RW: host owner token, advisory
ADDR_MGR_CTRL = 0xF028         # WO: bit 0 hub, bit 1 DESC_INDEX slot, bit 2 all slots
ADDR_MGR_SLOT_EPOCH = 0xF02C   # RO: DESC_INDEX slot reset edges (odd while held)
ADDR_MGR_TLR_COUNT = 0xF030    # RO: TAP Test-Logic-Reset entries
ADDR_MGR_SELECT_COUNT = 0xF034  # RO: MGR_ACTIVE writes, accepted or not

MGR_CAP_EPOCH_OWNER = 0x08     # MGR_EPOCH, MGR_OWNER, MGR_SLOT_EPOCH
MGR_CAP_BURST_HEADER = 0x10    # the priming scan of a burst carries a header
MGR_CAP_CTRL = 0x20            # MGR_CTRL, MGR_TLR_COUNT
MGR_CAP_TLR_RESET = 0x40       # Test-Logic-Reset resets the burst protocol
MGR_CAP_SELECT_COUNT = 0x80    # MGR_SELECT_COUNT
