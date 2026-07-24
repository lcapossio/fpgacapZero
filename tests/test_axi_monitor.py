# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Host tests for the AxiMonitor helper, against a fake transport that presents
the AM identity/geometry registers and a flattened capture word."""

from __future__ import annotations

import pytest

from fcapz.analyzer import Analyzer
from fcapz.axi_monitor import AxiMonitor, AxiMonitorError
from fcapz.transport import Transport

AM_ID = (0x414D << 16) | (1 << 8) | 0  # "AM", PROTO=AXI4LITE, flags=0
GEOM = (5 << 20) | (0 << 16) | (32 << 8) | 32  # cap=5 channels, id_w=0, data_w=32, addr_w=32


class FakeMon(Transport):
    def __init__(self, regs: dict[int, int]) -> None:
        self.regs = dict(regs)
        self.active_chain = 1

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self.active_chain = chain

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


AM_ID_DECODE = (0x414D << 16) | (1 << 8) | 0x01  # CAP_FLAGS bit0 = DECODE_EN


def _mon(extra: dict[int, int] | None = None) -> AxiMonitor:
    regs = {0x00E8: AM_ID, 0x00EC: GEOM}
    if extra:
        regs.update(extra)
    return AxiMonitor(Analyzer(FakeMon(regs)))


def _mon_decode() -> AxiMonitor:
    return AxiMonitor(Analyzer(FakeMon({0x00E8: AM_ID_DECODE, 0x00EC: GEOM})))


def test_detects_axi_monitor():
    m = _mon()
    assert m.present
    assert m.identity() == AM_ID


def test_reads_select_the_monitor_chain():
    # Another core (e.g. an AXI bridge on a different USER chain) may have left
    # the transport selected elsewhere; the monitor must reselect its chain.
    fm = FakeMon({0x00E8: AM_ID, 0x00EC: GEOM})
    fm.select_chain(4)
    mon = AxiMonitor(Analyzer(fm, chain=2))
    assert mon.present
    assert fm.active_chain == 2


def test_absent_when_magic_missing():
    m = AxiMonitor(Analyzer(FakeMon({0x00E8: 0x4C41, 0x00EC: 0})))  # plain ELA "LA"
    assert not m.present
    assert m.identity() is None
    with pytest.raises(AxiMonitorError):
        m.geometry()


def test_geometry_decode():
    g = _mon().geometry()
    assert (g.addr_w, g.data_w, g.id_w, g.cap_channels) == (32, 32, 0, 5)
    assert g.proto == "AXI4LITE"
    assert g.sample_width == 152  # must match fcapz_axi_mon SAMPLE_W


def test_probe_map_matches_rtl_layout():
    pm = _mon().probe_map()
    fields = {p.name: (p.lsb, p.width) for p in pm.probes}
    assert fields["awaddr"] == (0, 32)
    assert fields["awvalid"] == (35, 1)
    assert fields["bresp"] == (75, 2)
    assert fields["rready"] == (151, 1)
    assert pm.sample_width == 152


def test_decode_sample():
    m = _mon()
    value = 0x4000_0000 | (1 << 35)  # awaddr=0x40000000, awvalid=1
    fields = m.decode_sample(value)
    assert fields["awaddr"] == 0x4000_0000
    assert fields["awvalid"] == 1
    assert fields["wvalid"] == 0


def test_write_addr_capture_config():
    # Raw build: awaddr at bit 0. Unqualified -> plain low-32 value/mask.
    cfg = _mon().write_addr_capture_config(
        0x4000_0000, pretrigger=4, posttrigger=10, qualify_valid=False
    )
    assert cfg.trigger.mode == "value_match"
    assert cfg.trigger.value == 0x4000_0000
    assert cfg.trigger.mask == 0xFFFF_FFFF
    assert cfg.sample_width == 152
    assert cfg.pretrigger == 4 and cfg.posttrigger == 10
    assert any(p.name == "awaddr" for p in cfg.probes)


def test_write_addr_capture_config_valid_qualified():
    # Default qualifies by awvalid (bit 35 on a raw build) -> a wide trigger.
    cfg = _mon().write_addr_capture_config(0x4000_0000)
    assert cfg.trigger.value == 0x4000_0000 | (1 << 35)
    assert cfg.trigger.mask == 0xFFFF_FFFF | (1 << 35)


def test_write_addr_capture_config_decode_build():
    # Decode build: awaddr at bit 8, awvalid at bit 43 — both need the wide path.
    cfg = _mon_decode().write_addr_capture_config(0xDEAD_BEEF)
    assert cfg.trigger.value == (0xDEAD_BEEF << 8) | (1 << 43)
    assert cfg.trigger.mask == (0xFFFF_FFFF << 8) | (1 << 43)
    assert cfg.sample_width == 160


def test_decode_geometry_and_probe_map():
    g = _mon_decode().geometry()
    assert g.decode is True
    assert g.sample_width == 160  # +8 events word
    fields = {p.name: (p.lsb, p.width) for p in _mon_decode().probe_map().probes}
    assert fields["any_err"] == (7, 1)
    assert fields["awaddr"] == (8, 32)  # shifted up by the events word


def test_event_capture_config_triggers_on_event():
    cfg = _mon_decode().event_capture_config("any_err")
    assert cfg.trigger.mode == "value_match"
    assert cfg.trigger.value == 0x80 and cfg.trigger.mask == 0x80  # events bit 7
    assert cfg.sample_width == 160
    assert any(p.name == "any_err" for p in cfg.probes)


def test_beat_storage_qual_masks_handshakes():
    mode, value, mask = _mon_decode().beat_storage_qual()
    # NEQ (mode 1) vs 0 over aw_hs|w_hs|b_hs|ar_hs|r_hs = bits 0..4 = 0x1F.
    assert (mode, value, mask) == (1, 0, 0x1F)


def test_beat_storage_qual_requires_decode():
    with pytest.raises(AxiMonitorError):
        _mon().beat_storage_qual()  # no handshake bits without the decode layer


def test_event_capture_config_store_on_beats():
    cfg = _mon_decode().event_capture_config("aw_hs", store_on_beats=True)
    assert cfg.stor_qual_mode == 1
    assert cfg.stor_qual_value == 0
    assert cfg.stor_qual_mask == 0x1F
    # default (no beat filtering) leaves storage qualification disabled
    plain = _mon_decode().event_capture_config("aw_hs")
    assert plain.stor_qual_mode == 0


def test_mode_guards():
    with pytest.raises(AxiMonitorError):
        _mon().event_capture_config("any_err")  # needs a decode build
    with pytest.raises(AxiMonitorError):
        _mon_decode().event_capture_config("bogus_event")


# ── wide-trigger programming (Analyzer.configure) ────────────────────────


class RecordingTransport(Transport):
    """Fake that answers the config reads and records every register write."""

    def __init__(self, regs: dict[int, int]) -> None:
        self.regs = dict(regs)
        self.writes: list[tuple[int, int]] = []
        self.active_chain = 1

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def select_chain(self, chain: int) -> None:
        self.active_chain = chain

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def read_reg_stable(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        self.writes.append((addr, value))
        self.regs[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


def _wide_regs(caps_wide: bool = True) -> dict[int, int]:
    return {
        0x0C: 160, 0x10: 1024, 0xA4: 1, 0x3C: 0, 0xB8: 1,       # sample_w/depth/chan/features/segs
        0xE0: 0x1FF | ((1 << 18) if caps_wide else 0),          # COMPARE_CAPS (+wide bit)
    }


def test_configure_programs_wide_words():
    from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

    t = RecordingTransport(_wide_regs())
    value = (0xDEAD_BEEF << 8) | (1 << 43)   # decode awaddr + awvalid
    mask = (0xFFFF_FFFF << 8) | (1 << 43)
    Analyzer(t).configure(
        CaptureConfig(
            pretrigger=2, posttrigger=3,
            trigger=TriggerConfig(mode="value_match", value=value, mask=mask),
            sample_width=160, depth=1024,
        )
    )
    assert (0x24, value & 0xFFFF_FFFF) in t.writes  # low word -> TRIG_VALUE
    assert (0x28, mask & 0xFFFF_FFFF) in t.writes    # low word -> TRIG_MASK

    # Reconstruct what the WIDE_SEL/WIDE_DATA pairs programmed.
    prog_v = {0: value & 0xFFFF_FFFF}
    prog_m = {0: mask & 0xFFFF_FFFF}
    sel = 0
    for addr, v in t.writes:
        if addr == 0xE4:
            sel = v
        elif addr == 0xF0:
            (prog_m if sel & 1 else prog_v)[sel >> 4] = v
    words = (160 + 31) // 32
    assert sum(prog_v.get(k, 0) << (32 * k) for k in range(words)) == value
    assert sum(prog_m.get(k, 0) << (32 * k) for k in range(words)) == mask


def test_configure_zeroes_wide_words_for_immediate():
    """An always-true trigger (value=0, mask=0) on a WIDE_TRIG core must still
    write the upper comparator words to 0.  Otherwise the low 32-bit mask is
    cleared but the high mask words keep their stale/reset value, so the trigger
    is not actually always-true and the capture never completes (the AXI-monitor
    immediate-trigger hang)."""
    from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

    t = RecordingTransport(_wide_regs())
    Analyzer(t).configure(
        CaptureConfig(
            pretrigger=0, posttrigger=7,
            trigger=TriggerConfig(mode="value_match", value=0, mask=0),
            sample_width=160, depth=1024,
        )
    )
    # Reconstruct the (word, is_mask) -> value the wide window programmed.
    prog: dict[tuple[int, int], int] = {}
    sel = 0
    for addr, v in t.writes:
        if addr == 0xE4:
            sel = v
        elif addr == 0xF0:
            prog[(sel >> 4, sel & 1)] = v
    words = (160 + 31) // 32  # 5
    for k in range(1, words):
        assert prog.get((k, 0)) == 0, f"value word {k} not zeroed"
        assert prog.get((k, 1)) == 0, f"mask word {k} not zeroed"


def test_configure_wide_without_support_raises():
    from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig

    t = RecordingTransport(_wide_regs(caps_wide=False))
    with pytest.raises(ValueError):
        Analyzer(t).configure(
            CaptureConfig(
                pretrigger=2, posttrigger=3,
                trigger=TriggerConfig(mode="value_match", value=1 << 40, mask=1 << 40),
                sample_width=160, depth=1024,
            )
        )


# ── single-source layout (fcapz.axi_layout) ──────────────────────────────


def _rtl_sample_w(addr_w: int, data_w: int, decode: bool) -> int:
    """The SAMPLE_W formula as written in the RTL localparams (the thing the
    single source must reproduce): 2*ADDR + 2*DATA + STRB + 20 (+8 events)."""
    return 2 * addr_w + 2 * data_w + data_w // 8 + 20 + (8 if decode else 0)


@pytest.mark.parametrize("addr_w,data_w", [(32, 32), (16, 32), (32, 64), (64, 32)])
@pytest.mark.parametrize("decode", [False, True])
def test_layout_width_matches_rtl_formula(addr_w, data_w, decode):
    from fcapz import axi_layout

    assert axi_layout.sample_width(addr_w, data_w, decode) == _rtl_sample_w(
        addr_w, data_w, decode
    )


@pytest.mark.parametrize("decode", [False, True])
def test_layout_is_contiguous_and_gapless(decode):
    from fcapz import axi_layout

    probes = axi_layout.axi_probes(32, 32, decode)
    lsb = 0
    for p in probes:
        assert p.lsb == lsb, f"gap/overlap at {p.name}"
        lsb += p.width
    assert lsb == axi_layout.sample_width(32, 32, decode)


def test_bundled_probe_files_are_in_sync():
    """The shipped .prob sidecars must match what the single source generates."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "tools" / "gen_axi_probes.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"stale bundled .prob files:\n{r.stdout}{r.stderr}"
