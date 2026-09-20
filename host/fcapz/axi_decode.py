# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Reconstruct AXI transactions from a flat ELA capture.

The AXI monitor captures one word per cycle and the probe map slices it into
named fields, but AXI is a multi-channel protocol: one write is an AW beat, a
W beat, and a B response, spread arbitrarily over time and interleaved with
other traffic. Per-cycle rows cannot answer "why is this write corrupt?"
without the reader reassembling that structure by hand.

This module does the reassembly once, on the host, and emits transactions with
their addresses, data, responses, latency, stall counts, and protocol
anomalies. It reads only the probe map, so it works on both ``DECODE_EN``
builds (which add the events word) and plain ones: a beat is ``VALID & READY``
on its channel either way.

Scope is AXI4-Lite, which is what ``fcapz_axi_mon`` implements (``proto_code``
1, ``id_w`` 0): no transaction IDs and no bursts, so requests and responses
pair up in order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# Channel handshake pairs; a beat is VALID & READY in the same cycle.
_CHANNELS = {
    "aw": ("awvalid", "awready"),
    "w": ("wvalid", "wready"),
    "b": ("bvalid", "bready"),
    "ar": ("arvalid", "arready"),
    "r": ("rvalid", "rready"),
}

# Fields a capture must carry before it can be read as AXI at all.
REQUIRED_FIELDS = frozenset(name for pair in _CHANNELS.values() for name in pair)

_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
_ERROR_RESPONSES = ("SLVERR", "DECERR")

# Flags that mean "the bus misbehaved". A finite capture window can only
# prove misbehaviour for what it saw whole: an error response is a fault
# wherever it lands, and a misaligned address is one on sight. Everything
# else this decoder reports is either legal AXI (partial strobes, data before
# address) or an artefact of the window's own edges -- see WINDOW_EDGE_FLAGS.
FAULT_FLAGS = frozenset({
    "error_response",
    "unaligned_address",
})

# Flags that describe the capture window rather than the bus. A response whose
# request handshook before the window, or a write whose second beat falls
# after it, is perfectly legal traffic seen through a keyhole. They are
# reported because they bound what the decode can claim -- counting them as
# faults would make "faults only" a list of boundary effects.
WINDOW_EDGE_FLAGS = frozenset({
    "request_not_observed",
    "no_response_in_window",
    "write_missing_address",
    "write_missing_data",
    "pairing_suspect",
})


def looks_like_axi(probe_names: Iterable[str]) -> bool:
    """True when a probe map carries every AXI4-Lite handshake signal."""
    return REQUIRED_FIELDS.issubset(set(probe_names))


@dataclass
class _Pending:
    """A request beat waiting for the rest of its transaction."""

    cycle: int
    fields: dict[str, int] = field(default_factory=dict)
    stall: int = 0


@dataclass
class AxiTransaction:
    """One reconstructed AXI4-Lite read or write."""

    index: int
    kind: str  # "write" | "read"
    addr: int | None = None
    prot: int | None = None
    data: int | None = None
    strb: int | None = None
    resp: str | None = None
    addr_cycle: int | None = None
    data_cycle: int | None = None
    resp_cycle: int | None = None
    addr_stall: int = 0
    data_stall: int = 0
    resp_stall: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def latency(self) -> int | None:
        """Cycles from the first request beat to the response."""
        starts = [c for c in (self.addr_cycle, self.data_cycle) if c is not None]
        if not starts or self.resp_cycle is None:
            return None
        return self.resp_cycle - min(starts)

    def to_json(self, addr_digits: int, data_digits: int) -> dict[str, Any]:
        """Compact, JSON-number-safe form (wide values as hex strings)."""
        out: dict[str, Any] = {"index": self.index, "kind": self.kind}
        if self.addr is not None:
            out["addr"] = f"0x{self.addr:0{addr_digits}x}"
        if self.data is not None:
            out["data"] = f"0x{self.data:0{data_digits}x}"
        if self.strb is not None:
            out["strb"] = f"0x{self.strb:x}"
        if self.prot is not None:
            out["prot"] = self.prot
        if self.resp is not None:
            out["resp"] = self.resp
        cycles = {
            "addr": self.addr_cycle,
            "data": self.data_cycle,
            "resp": self.resp_cycle,
        }
        out["cycles"] = {k: v for k, v in cycles.items() if v is not None}
        if self.latency is not None:
            out["latency"] = self.latency
        stalls = {
            "addr": self.addr_stall,
            "data": self.data_stall,
            "resp": self.resp_stall,
        }
        stalls = {k: v for k, v in stalls.items() if v}
        if stalls:
            out["stall_cycles"] = stalls
        if self.flags:
            out["flags"] = list(self.flags)
        return out


class _Decoder:
    def __init__(self, probes: Sequence[Any]) -> None:
        self._specs = {p.name: (p.lsb, (1 << p.width) - 1) for p in probes}
        widths = {p.name: p.width for p in probes}
        self.data_w = widths.get("wdata") or widths.get("rdata") or 32
        self.addr_w = widths.get("awaddr") or widths.get("araddr") or 32
        self._bytes_per_beat = max(1, self.data_w // 8)

    def field(self, sample: int, name: str) -> int | None:
        spec = self._specs.get(name)
        if spec is None:
            return None
        lsb, mask = spec
        return (sample >> lsb) & mask

    def _hs(self, sample: int, channel: str) -> bool:
        valid, ready = _CHANNELS[channel]
        return bool(self.field(sample, valid)) and bool(self.field(sample, ready))

    def _stalled(self, sample: int, channel: str) -> bool:
        valid, ready = _CHANNELS[channel]
        return bool(self.field(sample, valid)) and not self.field(sample, ready)

    def decode(self, samples: Sequence[int]) -> list[AxiTransaction]:
        # Set when a response arrived with nothing queued to match it, which
        # proves the window opened with transactions already outstanding --
        # and therefore that every in-order pairing in that direction may be
        # shifted onto the wrong request.
        self.pre_window = {"write": False, "read": False}
        aw: list[_Pending] = []
        w: list[_Pending] = []
        ar: list[_Pending] = []
        stalls = {name: 0 for name in _CHANNELS}
        transactions: list[AxiTransaction] = []

        for cycle, sample in enumerate(samples):
            for channel in _CHANNELS:
                if self._stalled(sample, channel):
                    stalls[channel] += 1

            # Responses are matched *before* this cycle's requests are queued.
            # AXI forbids a combinational VALID-to-VALID path, so a response
            # sampled on the same edge as a request can never belong to it;
            # popping first keeps a same-cycle request out of reach and lets
            # an empty queue report the truth (the request was not observed)
            # instead of inventing a zero-latency pairing.
            if self._hs(sample, "b"):
                transactions.append(
                    self._write(
                        len(transactions),
                        aw.pop(0) if aw else None,
                        w.pop(0) if w else None,
                        cycle,
                        self.field(sample, "bresp"),
                        stalls["b"],
                    )
                )
                stalls["b"] = 0
            if self._hs(sample, "r"):
                transactions.append(
                    self._read(
                        len(transactions),
                        ar.pop(0) if ar else None,
                        cycle,
                        self.field(sample, "rdata"),
                        self.field(sample, "rresp"),
                        stalls["r"],
                    )
                )
                stalls["r"] = 0

            if self._hs(sample, "aw"):
                aw.append(
                    _Pending(
                        cycle,
                        {
                            "addr": self.field(sample, "awaddr"),
                            "prot": self.field(sample, "awprot"),
                        },
                        stalls["aw"],
                    )
                )
                stalls["aw"] = 0
            if self._hs(sample, "w"):
                w.append(
                    _Pending(
                        cycle,
                        {
                            "data": self.field(sample, "wdata"),
                            "strb": self.field(sample, "wstrb"),
                        },
                        stalls["w"],
                    )
                )
                stalls["w"] = 0
            if self._hs(sample, "ar"):
                ar.append(
                    _Pending(
                        cycle,
                        {
                            "addr": self.field(sample, "araddr"),
                            "prot": self.field(sample, "arprot"),
                        },
                        stalls["ar"],
                    )
                )
                stalls["ar"] = 0

        transactions.extend(self._unfinished(len(transactions), aw, w, ar))
        for tx in transactions:
            if "request_not_observed" in tx.flags:
                self.pre_window[tx.kind] = True
        for tx in transactions:
            if self.pre_window[tx.kind] and "request_not_observed" not in tx.flags:
                tx.flags.append("pairing_suspect")
        return transactions

    def _write(
        self,
        index: int,
        addr_beat: _Pending | None,
        data_beat: _Pending | None,
        resp_cycle: int,
        resp: int | None,
        resp_stall: int,
    ) -> AxiTransaction:
        tx = AxiTransaction(index=index, kind="write", resp_cycle=resp_cycle)
        tx.resp = _RESP_NAMES.get(resp if resp is not None else -1)
        tx.resp_stall = resp_stall
        if addr_beat is not None:
            tx.addr = addr_beat.fields["addr"]
            tx.prot = addr_beat.fields["prot"]
            tx.addr_cycle = addr_beat.cycle
            tx.addr_stall = addr_beat.stall
        if data_beat is not None:
            tx.data = data_beat.fields["data"]
            tx.strb = data_beat.fields["strb"]
            tx.data_cycle = data_beat.cycle
            tx.data_stall = data_beat.stall
        self._flag(tx, missing_request=addr_beat is None or data_beat is None)
        return tx

    def _read(
        self,
        index: int,
        addr_beat: _Pending | None,
        resp_cycle: int,
        data: int | None,
        resp: int | None,
        resp_stall: int,
    ) -> AxiTransaction:
        tx = AxiTransaction(index=index, kind="read", resp_cycle=resp_cycle)
        tx.data = data
        tx.resp = _RESP_NAMES.get(resp if resp is not None else -1)
        tx.resp_stall = resp_stall
        if addr_beat is not None:
            tx.addr = addr_beat.fields["addr"]
            tx.prot = addr_beat.fields["prot"]
            tx.addr_cycle = addr_beat.cycle
            tx.addr_stall = addr_beat.stall
        self._flag(tx, missing_request=addr_beat is None)
        return tx

    def _unfinished(
        self,
        next_index: int,
        aw: list[_Pending],
        w: list[_Pending],
        ar: list[_Pending],
    ) -> list[AxiTransaction]:
        """Requests with no response inside the capture window."""
        out: list[AxiTransaction] = []

        def _emit(tx: AxiTransaction) -> None:
            out.append(tx)

        def _first_cycle(tx: AxiTransaction) -> int:
            cycles = [c for c in (tx.addr_cycle, tx.data_cycle) if c is not None]
            return min(cycles) if cycles else 0

        for addr_beat, data_beat in zip(aw, w):
            tx = AxiTransaction(
                index=next_index + len(out),
                kind="write",
                addr=addr_beat.fields["addr"],
                prot=addr_beat.fields["prot"],
                addr_cycle=addr_beat.cycle,
                addr_stall=addr_beat.stall,
                data=data_beat.fields["data"],
                strb=data_beat.fields["strb"],
                data_cycle=data_beat.cycle,
                data_stall=data_beat.stall,
            )
            self._flag(tx, no_response=True)
            _emit(tx)

        # An AW with no W (or vice versa) is a half-formed write, which is
        # exactly the shape a dropped or scrambled command leaves behind.
        for beat in aw[len(w):]:
            tx = AxiTransaction(
                index=next_index + len(out),
                kind="write",
                addr=beat.fields["addr"],
                prot=beat.fields["prot"],
                addr_cycle=beat.cycle,
                addr_stall=beat.stall,
            )
            self._flag(tx, no_response=True, half_write=True)
            _emit(tx)
        for beat in w[len(aw):]:
            tx = AxiTransaction(
                index=next_index + len(out),
                kind="write",
                data=beat.fields["data"],
                strb=beat.fields["strb"],
                data_cycle=beat.cycle,
                data_stall=beat.stall,
            )
            self._flag(tx, no_response=True, half_write=True)
            _emit(tx)
        for beat in ar:
            tx = AxiTransaction(
                index=next_index + len(out),
                kind="read",
                addr=beat.fields["addr"],
                prot=beat.fields["prot"],
                addr_cycle=beat.cycle,
                addr_stall=beat.stall,
            )
            self._flag(tx, no_response=True)
            _emit(tx)
        # Emitted per channel above; renumber so indexes still follow the
        # trace rather than the order the leftover queues were drained in.
        out.sort(key=_first_cycle)
        for offset, tx in enumerate(out):
            tx.index = next_index + offset
        return out

    def _flag(
        self,
        tx: AxiTransaction,
        *,
        missing_request: bool = False,
        no_response: bool = False,
        half_write: bool = False,
    ) -> None:
        """Attach protocol observations.

        Careful to separate real faults from artefacts of watching the bus
        through a finite capture window: a transaction straddling either edge
        is expected, not a violation, and crying wolf about it would make the
        anomaly list useless.
        """
        if tx.resp in _ERROR_RESPONSES:
            tx.flags.append("error_response")
        if missing_request:
            # Deliberately says only what was observed. Whether the request
            # predates the window or was genuinely dropped cannot be told
            # apart from a finite trace, and guessing from the cycle number
            # produced both false alarms and false reassurance.
            tx.flags.append("request_not_observed")
        if no_response:
            tx.flags.append("no_response_in_window")
        if half_write:
            tx.flags.append(
                "write_missing_data" if tx.addr is not None else "write_missing_address"
            )
        if (
            tx.addr_cycle is not None
            and tx.data_cycle is not None
            and tx.data_cycle < tx.addr_cycle
        ):
            # Legal in AXI, but a common symptom when a bridge enqueues a
            # command before its payload has settled.
            tx.flags.append("data_before_address")
        if tx.kind == "write" and tx.strb is not None:
            full = (1 << self._bytes_per_beat) - 1
            if tx.strb == 0:
                tx.flags.append("write_strobe_zero")
            elif tx.strb != full:
                tx.flags.append("partial_write")
        if tx.addr is not None and tx.addr % self._bytes_per_beat:
            tx.flags.append("unaligned_address")


# The one thing an in-order decode cannot check for itself. Stated on every
# result, and on every page of transactions, because a reader who never sees
# it will read a wrong address as a right one.
PAIRING_ASSUMPTION = (
    "no AXI4-Lite transaction was outstanding when the capture window opened. "
    "AXI4-Lite has no transaction IDs, so responses are matched to requests "
    "first-in-first-out; if the window opened mid-transaction, every pairing "
    "in that direction is shifted onto the wrong request. A finite trace "
    "cannot disprove this -- check the addresses against what you expect."
)


def _pairing_block(pre_window: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "method": "in-order",
        "assumes": PAIRING_ASSUMPTION,
        "pre_window_traffic_observed": list(pre_window),
        # True only when the trace itself proved the assumption false. False
        # is *not* proof that it holds.
        "pre_window_traffic_proven": bool(pre_window),
    }


def _sampling_block(decimation: int, storage_qualified: bool) -> dict[str, Any]:
    return {
        "decimation": int(decimation),
        "storage_qualified": bool(storage_qualified),
        "contiguous": not decimation and not storage_qualified,
    }


def _undecodable(
    addr_w: int, data_w: int, reason: str, sampling: dict[str, Any]
) -> dict[str, Any]:
    """The full result shape with nothing decoded, and why."""
    return {
        "protocol": "axi4lite",
        "addr_width": addr_w,
        "data_width": data_w,
        "decoded": False,
        "unavailable_reason": reason,
        "sampling": sampling,
        "transaction_count": 0,
        "write_count": 0,
        "read_count": 0,
        "error_count": 0,
        "anomaly_count": 0,
        "flagged_count": 0,
        "pairing": _pairing_block(),
        "max_latency": None,
        "transactions": [],
    }


def decode_axi(
    samples: Sequence[int],
    probes: Sequence[Any],
    *,
    decimation: int = 0,
    storage_qualified: bool = False,
) -> dict[str, Any]:
    """Reconstruct AXI4-Lite transactions from a capture's samples.

    ``probes`` is the monitor's probe map (objects with ``name``/``width``/
    ``lsb``). Raises :class:`ValueError` if the map is not an AXI one.

    ``decimation`` and ``storage_qualified`` describe how the capture was
    taken. Reassembly reads the sample stream as consecutive bus cycles: a
    beat's position *is* its cycle, and a response pairs with the oldest
    request still queued. Decimation and storage qualification both break
    that -- a handshake that was never stored cannot be distinguished from
    one that never happened, so a dropped response silently shifts every
    later pairing onto the wrong address, and "latency" becomes a count of
    stored samples. There is no way to recover the missing beats after the
    fact, so such a capture is refused rather than misread.
    """
    names = [p.name for p in probes]
    if not looks_like_axi(names):
        missing = sorted(REQUIRED_FIELDS - set(names))
        raise ValueError(
            "capture does not carry an AXI4-Lite probe map; missing: "
            + ", ".join(missing)
        )
    decoder = _Decoder(probes)
    sampling = _sampling_block(decimation, storage_qualified)
    if not sampling["contiguous"]:
        how = " and ".join(
            part
            for part in (
                f"decimation={int(decimation)}" if decimation else "",
                "storage qualification" if storage_qualified else "",
            )
            if part
        )
        return _undecodable(
            decoder.addr_w,
            decoder.data_w,
            f"the capture stored only selected cycles ({how}), so handshakes "
            "are missing from the trace; AXI reassembly needs every cycle. "
            "Re-capture with decimation 0 and storage qualification off.",
            sampling,
        )
    transactions = decoder.decode(samples)
    addr_digits = max(1, (decoder.addr_w + 3) // 4)
    data_digits = max(1, (decoder.data_w + 3) // 4)
    latencies = [tx.latency for tx in transactions if tx.latency is not None]
    return {
        "protocol": "axi4lite",
        "addr_width": decoder.addr_w,
        "data_width": decoder.data_w,
        "decoded": True,
        "unavailable_reason": None,
        "sampling": sampling,
        "transaction_count": len(transactions),
        "write_count": sum(1 for tx in transactions if tx.kind == "write"),
        "read_count": sum(1 for tx in transactions if tx.kind == "read"),
        "error_count": sum(1 for tx in transactions if "error_response" in tx.flags),
        "anomaly_count": sum(
            1 for tx in transactions if FAULT_FLAGS.intersection(tx.flags)
        ),
        "flagged_count": sum(1 for tx in transactions if tx.flags),
        "pairing": _pairing_block(
            sorted(kind for kind, seen in decoder.pre_window.items() if seen)
        ),
        "max_latency": max(latencies) if latencies else None,
        "transactions": [tx.to_json(addr_digits, data_digits) for tx in transactions],
    }
