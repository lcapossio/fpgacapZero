# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import base64
import json
import traceback
from typing import Any, Dict

from .analyzer import (
    ELA_CORE_ID,
    Analyzer,
    CaptureConfig,
    CoreManager,
    ProbeSpec,
    SequencerStage,
    TriggerConfig,
    _infer_ir_table_name,
    discover_boards,
)
from .axi_monitor import AXI_MON_MAGIC, AxiMonitor
from .eio import EIO_CORE_ID, EioController, discover_eio
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .openocd_launcher import OpenOcdLauncher
from .probes import load_probe_file
from .transport import (
    OpenOcdTransport,
    QuartusStpTransport,
    Transport,
    XilinxHwServerTransport,
    list_openocd_taps,
    list_xilinx_hw_server_targets,
)

_SCHEMA_VERSION = "1.1"

# Upper bound on how many TCL ports discover_boards will sweep in one request,
# so an over-large port_span / ports list can't trigger a huge scan.
_MAX_DISCOVERY_PORTS = 64

# Hard ceiling on caller-supplied waits (capture timeouts, scans, OpenOCD
# start). In the web gateway each request holds a threadpool worker for its
# full wait, so a handful of huge timeouts would pin every worker and hang the
# server for all clients. 300 s is far above any legitimate interactive wait.
_MAX_WAIT_SEC = 300.0

# Request fields that name the board a transport opens (see _build_transport).
_TARGET_FIELDS = ("backend", "host", "port", "tap", "hardware")


def _wait_sec(req: Dict[str, Any], key: str, default: float) -> float:
    return min(max(0.0, float(req.get(key, default))), _MAX_WAIT_SEC)


def _valid_port(value: Any) -> int:
    p = int(value)
    if not (1 <= p <= 65535):
        raise ValueError(f"port out of range (1-65535): {p}")
    return p


# fcapz debug-core magic (VERSION[15:0], ASCII) -> friendly name, for list_cores.
_CORE_NAMES = {
    0x4C41: "Embedded Logic Analyzer",
    0x494F: "Embedded I/O",
    0x434D: "Core Manager",
    0x4A58: "EJTAG-AXI bridge",
    0x4A55: "EJTAG-UART",
    0x414D: "AXI Monitor",
}

# Auto-discovery sweep for ELA / AXI-monitor cores. USER1/2 carry the ELA
# control/data; some reference designs place an AXI monitor on a higher
# sld_virtual_jtag instance (the DE25-Nano monitor is on instance 5). All of
# these speak the ELA register DR protocol, so probing them is a read-only
# identity check -- a chain with no such core, or no such instance, simply
# reports no identity and is skipped. The EJTAG-AXI bridge (canonically chain 4)
# speaks a different DR protocol and is deliberately excluded so it never sees a
# stray ELA read frame.
_ELA_SCAN_CHAINS = (1, 2, 5)


class RpcServer:
    def __init__(
        self,
        openocd_launcher: OpenOcdLauncher | None = None,
        quartus_stp_path: str | None = None,
    ):
        self._analyzer: Analyzer | None = None
        self._eio: EioController | None = None
        # True when the EIO controller rides on the ELA session's transport (a
        # core-manager slot); closing the EIO must then leave the transport.
        self._eio_shared = False
        # The board the ELA session opened: the fields the connect request
        # gave, and the same fields with _build_transport's defaults filled in.
        self._target_fields: Dict[str, Any] = {}
        self._target: Dict[str, Any] | None = None
        self._axi: EjtagAxiController | None = None
        self._axi_transport: Transport | None = None
        self._uart: EjtagUartController | None = None
        self._uart_transport: Transport | None = None
        # Optional server-managed OpenOCD (None = the openocd_* commands are
        # disabled and report so). Configured only by the web server launch.
        self._openocd_launcher = openocd_launcher
        # Optional quartus_stp override for USB-Blaster connects. When a request
        # omits "quartus_stp", this server default is used; when both are None
        # the transport auto-detects (PATH / $QUARTUS_ROOTDIR / install roots).
        self._quartus_stp_path = quartus_stp_path

    @staticmethod
    def _ok(**payload: Any) -> Dict[str, Any]:
        return {"ok": True, "schema_version": _SCHEMA_VERSION, **payload}

    def _ensure_analyzer(self) -> Analyzer:
        if self._analyzer is None:
            raise RuntimeError("not connected")
        return self._analyzer

    def _close_all(self) -> None:
        """Full session teardown: analyzer plus any EIO/AXI/UART transports.

        The ``close`` command (web/GUI "Disconnect") must release every
        hardware session, not just the analyzer, so no transport is left open
        on the board/hw_server. A controller owns and closes its own transport;
        a bare transport from a partial connect is closed directly. Each close
        is guarded so one failure cannot leak the others.
        """

        def _shut(obj: Any) -> None:
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

        _shut(self._analyzer)
        _shut(None if self._eio_shared else self._eio)
        _shut(self._axi if self._axi is not None else self._axi_transport)
        _shut(self._uart if self._uart is not None else self._uart_transport)
        self._analyzer = None
        self._eio = None
        self._eio_shared = False
        self._target_fields = {}
        self._target = None
        self._axi = None
        self._axi_transport = None
        self._uart = None
        self._uart_transport = None

    def _drop_eio(self) -> None:
        """Forget the EIO controller, closing its transport only if it owns one."""
        if self._eio is not None and not self._eio_shared:
            self._eio.close()
        self._eio = None
        self._eio_shared = False

    # ---- core-manager slots ------------------------------------------------
    # A core manager puts several cores (ELAs, EIOs) behind one USER chain, and
    # its MGR_ACTIVE register picks which one the chain's register window
    # reaches. That register is shared hardware, but the "slot already
    # selected" cache lives on the transport object. So every controller that
    # selects a slot rides on the ELA session's transport: a second transport
    # would move MGR_ACTIVE behind the session's back, and the ELA would then
    # read -- or configure -- another core.

    @staticmethod
    def _manager_slots(transport: Transport, chain: int) -> list[tuple[int, int]] | None:
        """``[(slot, VERSION), ...]`` for the core manager on *chain*, or None."""
        if not Analyzer(transport, chain=chain)._behind_manager():  # noqa: SLF001
            return None
        manager = CoreManager(transport, chain=chain)
        slots = []
        for slot in range(int(manager.probe()["num_slots"])):
            # VERSION at 0x0000 carries every fcapz core's identity, so this
            # needs no descriptor table.
            with transport.transaction_lock():
                manager.select_raw(slot)
                slots.append((slot, int(transport.read_reg_stable(0x0000))))
        return slots

    def _bind_ela(self, transport: Transport, chain: int, instance: Any) -> Analyzer:
        """An Analyzer on *chain*, bound to an explicit slot behind a manager.

        An unbound Analyzer never writes MGR_ACTIVE, so it drives whichever
        core the manager last pointed at. ``instance`` None picks the lowest
        ELA slot.
        """
        slots = self._manager_slots(transport, chain)
        if slots is None:
            if instance is not None:
                raise ValueError(f"chain {chain} has no core manager; omit instance")
            return Analyzer(transport, chain=chain)
        ela_slots = [slot for slot, version in slots if version & 0xFFFF == ELA_CORE_ID]
        if instance is None:
            if not ela_slots:
                raise RuntimeError(f"the core manager on chain {chain} has no ELA slot")
            instance = ela_slots[0]
        elif int(instance) not in ela_slots:
            raise ValueError(
                f"slot {instance} on chain {chain} is not an ELA; ELA slots: {ela_slots}"
            )
        analyzer = Analyzer(transport, chain=chain, instance=int(instance), manager=True)
        analyzer.select_instance(int(instance))
        return analyzer

    def _connect_ela(self, transport: Transport, requested: Any, instance: Any) -> Analyzer:
        if requested is not None or instance is not None:
            return self._bind_ela(
                transport, int(requested) if requested is not None else 1, instance
            )
        # No chain given: the default chain, else autodetect on the
        # conservative scan set (USER1/2 -- bridges on 3/4 speak a different DR
        # protocol and must not see stray shifts). The slot is bound before
        # the probe: a manager left pointing at an EIO slot would otherwise
        # read as "no ELA here".
        for chain in (1, 2):
            try:
                analyzer = self._bind_ela(transport, chain, None)
            except RuntimeError:  # a manager with no ELA slot
                continue
            if analyzer.probe_optional() is not None:
                return analyzer
        # Nothing ELA-like: stay on chain 1 for the side cores.
        return Analyzer(transport, chain=1)

    @staticmethod
    def _resolved_target(fields: Dict[str, Any]) -> Dict[str, Any]:
        """The board *fields* name, with _build_transport's defaults filled in."""
        backend = fields.get("backend", "hw_server")
        if backend == "usb_blaster":
            tap = str(fields.get("tap", "auto"))
            return {
                "backend": backend,
                "hardware": fields.get("hardware"),
                # The spellings _build_transport treats as "pick the device".
                "tap": "auto" if tap in ("", "auto", "xc7a100t.tap") else tap,
            }
        openocd = backend == "openocd"
        return {
            "backend": backend,
            "host": fields.get("host", "127.0.0.1"),
            "port": int(fields.get("port", 6666 if openocd else 3121)),
            "tap": fields.get("tap", "xc7a100t.tap" if openocd else "xc7a100t"),
        }

    @staticmethod
    def _given_target_fields(req: Dict[str, Any]) -> Dict[str, Any]:
        return {k: req[k] for k in _TARGET_FIELDS if req.get(k) is not None}

    def _on_session_board(self, req: Dict[str, Any]) -> bool:
        """Whether *req* names the ELA session's board; fields it omits match."""
        if self._target is None:
            return False
        fields = {**self._target_fields, **self._given_target_fields(req)}
        return self._resolved_target(fields) == self._target

    def _slot_entry(self, transport: Transport, chain: int, slot: int, version: int):
        """list_cores entry for one manager slot."""
        core_id = version & 0xFFFF
        entry: Dict[str, Any] = {
            "type": "unknown",
            "name": _CORE_NAMES.get(core_id, f"core 0x{core_id:04X}"),
            "core_id": core_id,
            "chain": chain,
            "instance": slot,
            "base_addr": 0,
            "version_major": (version >> 24) & 0xFF,
            "version_minor": (version >> 16) & 0xFF,
            "info": {},
        }
        if core_id == ELA_CORE_ID:
            ela = Analyzer(transport, chain=chain, instance=slot, manager=True)
            entry.update(type="ela", info=ela.probe())
        elif core_id == EIO_CORE_ID:
            eio = EioController(transport, chain=chain, instance=slot)
            eio.attach()
            entry.update(type="eio", info={"in_w": eio.in_w, "out_w": eio.out_w})
        return entry

    def _list_cores(
        self, analyzer: Analyzer, *, slots: bool = False
    ) -> list[Dict[str, Any]]:
        """Enumerate the fcapz cores reachable on the connected session.

        Always reports the connected ELA; adds the EIO if one is discoverable
        (reusing an already-attached controller, else a read-only probe that
        restores chain 1). Other core types (AXI/UART) are not yet auto-scanned
        here. Each entry: ``{type, name, core_id, chain, instance, base_addr,
        version_major, version_minor, info}``; ``instance`` is the core-manager
        slot, None for a core reached directly. With ``slots``, every slot of
        a core manager on a scanned chain is listed in place of that chain's
        entries -- opt-in, because a client that switches cores by chain alone
        would mistake ELA slot 1 for the ELA it already has.
        """
        cores: list[Dict[str, Any]] = []
        try:
            ela = analyzer.probe()
        except RuntimeError:
            ela = None
        if ela is not None:
            cores.append({
                "type": "ela",
                "name": _CORE_NAMES.get(ela["core_id"], "Logic Analyzer"),
                "core_id": ela["core_id"],
                "chain": analyzer.bscan_chain,
                "instance": analyzer.instance,
                "base_addr": 0,
                "version_major": ela["version_major"],
                "version_minor": ela["version_minor"],
                "info": ela,
            })

        eio = self._eio
        if eio is None:
            transport = analyzer.transport
            try:
                eio = discover_eio(transport, chains=(1, 2))
            except Exception:
                eio = None
            try:
                transport.invalidate_manager_instance_cache()
            except Exception:
                pass
        if eio is not None:
            cores.append({
                "type": "eio",
                "name": _CORE_NAMES.get(eio.core_id, "Embedded I/O"),
                "core_id": eio.core_id,
                "chain": eio.bscan_chain,
                "instance": eio.instance,
                "base_addr": eio._base_addr,  # noqa: SLF001 - report discovered offset
                "version_major": eio.version_major,
                "version_minor": eio.version_minor,
                "info": {"in_w": eio.in_w, "out_w": eio.out_w},
            })

        # The AXI monitor is an ELA plus an identity/geometry pair — report it
        # so clients can label the session as a bus monitor.
        mon_entry = self._axi_mon_entry(analyzer, ela)
        if mon_entry is not None:
            cores.append(mon_entry)

        # Other ELA-protocol chains (see _ELA_SCAN_CHAINS): a plain or monitor
        # ELA the client can switch the session to — chains are an
        # implementation detail the UI resolves with a "use this core" action.
        for chain in _ELA_SCAN_CHAINS:
            if chain == analyzer.bscan_chain:
                continue
            try:
                other = Analyzer(analyzer.transport, chain=chain)
                ident = other.probe_optional()
            except Exception:
                ident = None
            if ident is None:
                continue
            entry = self._axi_mon_entry(other, ident)
            if entry is None:
                entry = {
                    "type": "ela",
                    "name": _CORE_NAMES.get(ident["core_id"], "Logic Analyzer"),
                    "core_id": ident["core_id"],
                    "chain": chain,
                    "instance": None,
                    "base_addr": 0,
                    "version_major": ident["version_major"],
                    "version_minor": ident["version_minor"],
                    "info": ident,
                }
            cores.append(entry)
        if slots:
            managed: Dict[int, list[tuple[int, int]]] = {}
            for chain in dict.fromkeys((analyzer.bscan_chain, *_ELA_SCAN_CHAINS)):
                try:
                    found = self._manager_slots(analyzer.transport, chain)
                except Exception:
                    found = None
                if found is not None:
                    managed[chain] = found
            if managed:
                cores = [
                    self._slot_entry(analyzer.transport, chain, slot, version)
                    for chain, found in managed.items()
                    for slot, version in found
                ] + [core for core in cores if core["chain"] not in managed]
        try:
            analyzer.transport.select_chain(analyzer.bscan_chain)
        except NotImplementedError:
            pass
        try:
            analyzer.transport.invalidate_manager_instance_cache()
        except Exception:
            pass
        return cores

    @staticmethod
    def _axi_mon_entry(analyzer: Analyzer, ela_ident) -> Dict[str, Any] | None:
        """Core-list entry for the AXI monitor on ``analyzer``'s chain, or None."""
        if ela_ident is None:
            return None
        try:
            mon = AxiMonitor(analyzer)
            geo = mon.geometry() if mon.present else None
        except Exception:
            geo = None
        if geo is None:
            return None
        return {
            "type": "axi_mon",
            "name": _CORE_NAMES[AXI_MON_MAGIC],
            "core_id": AXI_MON_MAGIC,
            "chain": analyzer.bscan_chain,
            "instance": None,
            "base_addr": 0,
            "version_major": ela_ident["version_major"],
            "version_minor": ela_ident["version_minor"],
            "info": {
                "proto": geo.proto,
                "addr_w": geo.addr_w,
                "data_w": geo.data_w,
                "decode": geo.decode,
                "sample_width": geo.sample_width,
            },
        }

    def _capture_readout(self, analyzer: Analyzer, cfg, req: Dict[str, Any]):
        """Wait for the armed capture to complete and serialize it as requested
        (shared by `capture`, which arms first, and `capture_wait`, which polls
        an existing arm)."""
        timeout = _wait_sec(req, "timeout", 10.0)
        if req.get("segments"):
            if not analyzer.wait_all_segments_done(timeout=timeout):
                raise TimeoutError("segmented capture did not complete within timeout")
            probe_info = analyzer.probe()
            nseg = max(1, int(probe_info.get("num_segments", 1)))
            results = [analyzer.capture_segment(i, timeout=timeout) for i in range(nseg)]
            fmt = str(req.get("format", "json"))
            payload = self._ok(
                format=fmt,
                overflow=any(r.overflow for r in results),
                sample_count=sum(len(r.samples) for r in results),
                channel=cfg.channel,
                segments=[
                    self._serialize_capture(
                        analyzer,
                        cfg,
                        r,
                        fmt=fmt,
                        include_summary=bool(req.get("summarize", False)),
                    )
                    for r in results
                ],
            )
            # Wide captures request a non-json format precisely because JSON
            # numbers round above 53 bits — only attach the JSON-number
            # result when the caller asked for it (mirrors _serialize_capture).
            if fmt == "json":
                payload["result"] = {
                    "segments": [analyzer.export_json(r) for r in results]
                }
            if req.get("include_vcd") and results:
                # All segments in one waveform — not just segment 0.
                payload["vcd"] = analyzer.export_vcd_text_segments(results)
            if req.get("include_csv"):
                lines = ["segment,index,value"]
                for r in results:
                    for idx, value in enumerate(r.samples):
                        lines.append(f"{r.segment},{idx},{value}")
                payload["csv"] = "\n".join(lines) + "\n"
            return payload

        result = analyzer.capture(timeout=timeout)
        payload = self._serialize_capture(
            analyzer,
            cfg,
            result,
            fmt=str(req.get("format", "json")),
            include_summary=bool(req.get("summarize", False)),
        )
        # Optional VCD text for embedded viewers (e.g. the web Surfer iframe),
        # produced by the same exporter the CLI/GUI use.
        if req.get("include_vcd"):
            payload["vcd"] = analyzer.export_vcd_text(result)
        if req.get("include_csv"):
            payload["csv"] = analyzer.export_csv_text(result)
        return self._ok(**payload)

    # ir_table preset name -> table (None = transport default, Xilinx 7-series).
    # "intel"/"altera" are vendor labels for the USB-Blaster (sld_virtual_jtag)
    # transport, which uses no IR preset; they map to None so echoing one back
    # is a harmless no-op on the shared build path.
    _IR_TABLES = {
        "": None,
        "xilinx7": None,
        "7series": None,
        "series7": None,
        "ultrascale": OpenOcdTransport.IR_TABLE_US,
        "us": OpenOcdTransport.IR_TABLE_US,
        "gowin": OpenOcdTransport.IR_TABLE_GOWIN,
        "gw": OpenOcdTransport.IR_TABLE_GOWIN,
        "intel": None,
        "altera": None,
    }

    @classmethod
    def _ir_table(cls, name):
        key = (name or "").strip().lower().replace("-", "_")
        if key not in cls._IR_TABLES:
            raise ValueError(f"unknown ir_table: {name!r}")
        table = cls._IR_TABLES[key]
        return dict(table) if table is not None else None

    @staticmethod
    def _resolved_ir_name(req: Dict[str, Any]) -> str:
        # No explicit ir_table: infer the preset from the tap name so every
        # client (CLI, GUI, web) gets the same default from one place.
        name = req.get("ir_table")
        if name is not None and str(name).strip():
            return str(name)
        # USB-Blaster is Intel/Altera sld_virtual_jtag -- it has no Xilinx IR
        # preset, so label the session by vendor instead of defaulting to the
        # Xilinx-7 preset (which mislabeled Agilex/Cyclone boards in the GUI).
        if req.get("backend") == "usb_blaster":
            return "intel"
        return _infer_ir_table_name(str(req.get("tap", "")))

    @staticmethod
    def _probe_ejtag_axi(analyzer: Analyzer, chains):
        """``(chain, identity)`` of an EJTAG-AXI bridge on one of ``chains``, or
        ``None``.

        The bridge sits on its own USER chain (canonically USER4) and speaks a
        different DR protocol than the ELA, so this probes with the bridge's own
        read-only CONFIG identity scan (``EjtagAxiController.attach`` on the
        shared transport, which restores chain 1). A chain whose identity magic
        doesn't match just falls through. Restores the analyzer's chain
        afterwards so the ELA/monitor session is untouched wherever the bridge
        was (or wasn't) found.
        """
        found = None
        for chain in chains:
            try:
                info = EjtagAxiController(analyzer.transport, chain=chain).attach()
            except Exception:
                info = None
            if info is not None:
                found = (chain, info)
                break
        try:
            analyzer.transport.select_chain(analyzer.bscan_chain)
        except NotImplementedError:
            pass
        try:
            analyzer.transport.invalidate_manager_instance_cache()
        except Exception:
            pass
        return found

    @staticmethod
    def _probe_axi_mon(analyzer: Analyzer):
        """``(chain, geometry, probes)`` of the AXI monitor, or None.

        The connected chain is answered directly; otherwise an ELA-protocol
        sweep (see _ELA_SCAN_CHAINS: USER1/2 plus the monitor instance 5 the
        DE25-Nano uses) so cores speaking a different DR protocol (the EJTAG
        bridge on chain 4) never see stray shifts. Restores the analyzer's chain
        afterwards, so the caller's session is untouched wherever the monitor
        was found.
        """
        mon = AxiMonitor(analyzer)
        geo = mon.geometry() if mon.present else None
        if geo is not None:
            return analyzer.bscan_chain, geo, mon.probe_map(geo).probes
        result = None
        for chain in _ELA_SCAN_CHAINS:
            if chain == analyzer.bscan_chain:
                continue
            try:
                alt = AxiMonitor(Analyzer(analyzer.transport, chain=chain))
                alt_geo = alt.geometry() if alt.present else None
            except Exception:
                alt_geo = None
            if alt_geo is not None:
                result = (chain, alt_geo, alt.probe_map(alt_geo).probes)
                break
        try:
            analyzer.transport.select_chain(analyzer.bscan_chain)
        except NotImplementedError:
            pass
        try:
            analyzer.transport.invalidate_manager_instance_cache()
        except Exception:
            pass
        return result

    def _build_transport(self, req: Dict[str, Any]):
        backend = req.get("backend", "hw_server")
        host = req.get("host", "127.0.0.1")
        ir = self._ir_table(self._resolved_ir_name(req))
        if backend == "openocd":
            return OpenOcdTransport(
                host=host,
                port=int(req.get("port", 6666)),
                tap=req.get("tap", "xc7a100t.tap"),
                ir_table=ir,
            )
        if backend == "hw_server":
            return XilinxHwServerTransport(
                host=host,
                port=int(req.get("port", 3121)),
                fpga_name=req.get("tap", "xc7a100t"),
                bitfile=req.get("program"),
                single_chain_burst=bool(req.get("single_chain_burst", True)),
                burst=bool(req.get("burst", True)),
                ir_table=ir,
            )
        if backend == "usb_blaster":
            tap = str(req.get("tap", "auto"))
            return QuartusStpTransport(
                hardware_name=req.get("hardware"),
                device_name=None if tap in ("", "auto", "xc7a100t.tap") else tap,
                quartus_stp_path=req.get("quartus_stp") or self._quartus_stp_path,
                burst=bool(req.get("burst", True)),
            )
        raise ValueError(f"unknown backend: {backend}")

    @staticmethod
    def _parse_int(value: Any) -> int:
        if not isinstance(value, str):
            return int(value)
        s = value.strip()
        # ``int(s, 0)`` honours the 0x/0o/0b/plain-decimal convention but rejects
        # two forms users type by hand: decimals with a leading zero ("08") and
        # bare hex without the 0x prefix ("FF"). Fall back to each explicitly so
        # a capture doesn't fail with a cryptic ValueError.
        for base in (0, 10, 16):
            try:
                return int(s, base)
            except ValueError:
                continue
        raise ValueError(
            f"could not parse integer from {value!r}; use decimal (e.g. 255) "
            f"or 0x-prefixed hex (e.g. 0xFF)"
        )

    @staticmethod
    def _parse_probes(raw: Any) -> list[ProbeSpec]:
        if raw is None:
            return []
        if isinstance(raw, str):
            probes = []
            for part in raw.split(","):
                name, width_s, lsb_s = part.strip().split(":")
                width = int(width_s)
                lsb = int(lsb_s)
                if width <= 0:
                    raise ValueError(f"probe '{name}' width must be > 0, got {width}")
                if lsb < 0:
                    raise ValueError(f"probe '{name}' lsb must be >= 0, got {lsb}")
                probes.append(ProbeSpec(name=name, width=width, lsb=lsb))
            return probes
        if isinstance(raw, list):
            probes = []
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("probe entries must be objects")
                name = str(item["name"])
                width = int(item["width"])
                lsb = int(item.get("lsb", 0))
                if width <= 0:
                    raise ValueError(f"probe '{name}' width must be > 0, got {width}")
                if lsb < 0:
                    raise ValueError(f"probe '{name}' lsb must be >= 0, got {lsb}")
                probes.append(ProbeSpec(name=name, width=width, lsb=lsb))
            return probes
        raise ValueError("probes must be a string or a list of objects")

    @classmethod
    def _parse_sequence(cls, raw: Any) -> list[SequencerStage] | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, list):
            raise ValueError("sequence must be a JSON array")
        stages = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("sequence entries must be objects")
            stages.append(
                SequencerStage(
                    cmp_mode_a=int(item.get("cmp_mode_a", 0)),
                    cmp_mode_b=int(item.get("cmp_mode_b", 0)),
                    combine=int(item.get("combine", 0)),
                    next_state=int(item.get("next_state", 0)),
                    is_final=cls._validated_bool(
                        item.get("is_final", False), field="is_final"
                    ),
                    count_target=int(item.get("count_target", 1)),
                    value_a=cls._parse_int(item.get("value_a", 0)),
                    mask_a=cls._parse_int(item.get("mask_a", 0xFFFFFFFF)),
                    value_b=cls._parse_int(item.get("value_b", 0)),
                    mask_b=cls._parse_int(item.get("mask_b", 0xFFFFFFFF)),
                )
            )
        return stages

    @staticmethod
    def _validated_sq_mode(mode: int) -> int:
        if mode not in (0, 1, 2):
            raise ValueError(f"stor_qual_mode must be 0, 1, or 2, got {mode}")
        return mode

    @staticmethod
    def _validated_trigger_delay(delay: int) -> int:
        if not (0 <= delay <= 0xFFFF):
            raise ValueError(f"trigger_delay must be 0..65535, got {delay}")
        return delay

    @staticmethod
    def _validated_trigger_holdoff(delay: int) -> int:
        if not (0 <= delay <= 0xFFFF):
            raise ValueError(f"trigger_holdoff must be 0..65535, got {delay}")
        return delay

    @staticmethod
    def _validated_bool(value: Any, *, field: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value in (0, 1):
                return bool(value)
            raise ValueError(f"{field} must be a boolean, got {value}")
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("0", "false", "no", "off"):
                return False
            if lowered in ("1", "true", "yes", "on"):
                return True
            raise ValueError(f"{field} must be a boolean, got {value!r}")
        raise ValueError(f"{field} must be a boolean, got {value!r}")

    @classmethod
    def _build_config(cls, req: Dict[str, Any]) -> CaptureConfig:
        probe_file = load_probe_file(req["probe_file"]) if req.get("probe_file") else None
        if probe_file is not None and req.get("probes") is not None:
            raise ValueError("probes and probe_file are mutually exclusive")
        probes = (
            probe_file.probes
            if probe_file is not None
            else cls._parse_probes(req.get("probes"))
        )
        file_sample_width = (
            probe_file.sample_width
            if probe_file is not None and probe_file.sample_width is not None
            else 8
        )
        file_sample_clock_hz = (
            probe_file.sample_clock_hz
            if probe_file is not None and probe_file.sample_clock_hz is not None
            else 100_000_000
        )

        return CaptureConfig(
            pretrigger=int(req.get("pretrigger", 8)),
            posttrigger=int(req.get("posttrigger", 16)),
            trigger=TriggerConfig(
                mode=req.get("trigger_mode", "value_match"),
                # Bit vectors: accept base-prefixed strings so values wider than
                # a JS-safe integer (53 bits) survive JSON transport unrounded.
                value=cls._parse_int(req.get("trigger_value", 0)),
                mask=cls._parse_int(req.get("trigger_mask", 0xFF)),
            ),
            sample_width=int(req.get("sample_width", file_sample_width)),
            depth=int(req.get("depth", 1024)),
            sample_clock_hz=int(req.get("sample_clock_hz", file_sample_clock_hz)),
            probes=probes,
            channel=int(req.get("channel", 0)),
            decimation=int(req.get("decimation", 0)),
            ext_trigger_mode=int(req.get("ext_trigger_mode", 0)),
            sequence=cls._parse_sequence(
                req.get("sequence", req.get("trigger_sequence"))
            ),
            stor_qual_mode=cls._validated_sq_mode(int(req.get("stor_qual_mode", 0))),
            stor_qual_value=cls._parse_int(req.get("stor_qual_value", 0)),
            stor_qual_mask=cls._parse_int(req.get("stor_qual_mask", 0)),
            startup_arm=cls._validated_bool(
                req.get("startup_arm", False), field="startup_arm"
            ),
            trigger_holdoff=cls._validated_trigger_holdoff(
                int(req.get("trigger_holdoff", 0))
            ),
            trigger_delay=cls._validated_trigger_delay(int(req.get("trigger_delay", 0))),
        )

    @staticmethod
    def _probe_defs(config: CaptureConfig) -> list[ProbeDefinition] | None:
        if not config.probes:
            return None
        return [
            ProbeDefinition(name=probe.name, width=probe.width, lsb=probe.lsb)
            for probe in config.probes
        ]

    def _serialize_capture(
        self,
        analyzer: Analyzer,
        config: CaptureConfig,
        result,
        fmt: str,
        include_summary: bool,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "format": fmt,
            "overflow": result.overflow,
            "sample_count": len(result.samples),
            "channel": config.channel,
        }
        if fmt == "json":
            payload["result"] = analyzer.export_json(result)
        elif fmt == "csv":
            payload["content"] = analyzer.export_csv_text(result)
        elif fmt == "vcd":
            payload["content"] = analyzer.export_vcd_text(result)
        else:
            raise ValueError(f"unsupported rpc format: {fmt}")

        if include_summary:
            payload["summary"] = summarize(result, self._probe_defs(config))
        return payload

    def handle(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("cmd")

        if cmd == "connect":
            # Reconnecting must start from a clean slate: release any prior
            # session (ELA + EIO/AXI/UART transports), not just the analyzer, so
            # stale side sessions can't survive still pointing at the old board.
            self._close_all()
            requested = req.get("chain")
            transport = self._build_transport(req)
            Analyzer(
                transport, chain=int(requested) if requested is not None else 1
            ).connect()
            try:
                analyzer = self._connect_ela(transport, requested, req.get("instance"))
            except Exception:
                # A refused instance must not leak the transport just opened.
                try:
                    transport.close()
                except Exception:
                    pass
                raise
            self._analyzer = analyzer
            self._target_fields = self._given_target_fields(req)
            self._target = self._resolved_target(self._target_fields)
            # Echo the resolved preset/chain so a client that omitted them can
            # label the session and reuse them for eio/axi side connects, plus
            # the actual FPGA the backend opened (when it can name it) so the UI
            # shows the connected device, not just the vendor.
            return self._ok(
                ir_table=self._resolved_ir_name(req),
                chain=analyzer.bscan_chain,
                instance=analyzer.instance,
                device=getattr(analyzer.transport, "opened_device", None),
            )

        if cmd == "rebind":
            # Re-bind the session to a core on another BSCAN chain WITHOUT
            # reconnecting. Both cores share one JTAG transport; hopping taps is
            # just a chain select + re-probe (probe() selects its own chain), so
            # this skips the connect() teardown/reopen. Used for the seamless
            # ELA <-> AXI monitor switch. Side sessions (EIO/AXI/UART) are left
            # untouched — a chain hop on the ELA control interface is unrelated.
            analyzer = self._ensure_analyzer()
            requested = req.get("chain")
            new_instance = req.get("instance")
            if requested is None and new_instance is None:
                raise ValueError("rebind requires a chain or an instance")
            new_chain = analyzer.bscan_chain if requested is None else int(requested)
            if new_chain != analyzer.bscan_chain or (
                new_instance is not None and int(new_instance) != analyzer.instance
            ):
                # Keep the SAME transport; point a fresh Analyzer at the new
                # tap -- or, behind a core manager, the new ELA slot.
                self._analyzer = self._bind_ela(analyzer.transport, new_chain, new_instance)
            return self._ok(
                chain=self._analyzer.bscan_chain,
                instance=self._analyzer.instance,
                probe=self._analyzer.probe(),
            )

        if cmd == "close":
            self._close_all()
            return self._ok()

        if cmd == "scan_targets":
            backend = req.get("backend", "hw_server")
            host = req.get("host", "127.0.0.1")
            if backend == "openocd":
                taps = list_openocd_taps(
                    host=host,
                    port=int(req.get("port", 6666)),
                    timeout_sec=_wait_sec(req, "timeout", 5.0),
                )
                return self._ok(backend="openocd", targets=taps)
            if backend == "hw_server":
                targets = list_xilinx_hw_server_targets(
                    host=host,
                    port=int(req.get("port", 3121)),
                    timeout_sec=_wait_sec(req, "timeout", 10.0),
                )
                return self._ok(backend="hw_server", targets=targets)
            raise ValueError(f"unknown backend: {backend}")

        if cmd == "discover_boards":
            # Find fpgacapZero-compatible boards across running OpenOCD
            # instances. Probes each tap for the ELA identity and returns only
            # compatible boards, so the GUI fails only when none are found.
            host = req.get("host", "127.0.0.1")
            raw_ports = req.get("ports")
            if raw_ports:
                ports = [_valid_port(p) for p in raw_ports][:_MAX_DISCOVERY_PORTS]
            else:
                base = _valid_port(req.get("port", 6666))
                span = min(max(1, int(req.get("port_span", 1))), _MAX_DISCOVERY_PORTS)
                ports = [base + i for i in range(span) if base + i <= 65535]
            boards = discover_boards(
                host=host,
                ports=ports,
                timeout_sec=_wait_sec(req, "timeout", 5.0),
                budget_sec=None if req.get("budget") is None else _wait_sec(req, "budget", 0.0),
            )
            return self._ok(backend="openocd", boards=boards)

        if cmd == "openocd_discover":
            # Auto-discover compatible boards without the user picking a config:
            # filter the allow-listed configs by which USB JTAG adapters are
            # actually plugged in, then start OpenOCD per surviving config and
            # probe for an fpgacapZero core. Confirmed boards come back with the
            # config that reached them and a running TCL port to connect to.
            # Spawns processes, so it is loopback-gated by the web layer.
            if self._openocd_launcher is None:
                raise RuntimeError(
                    "OpenOCD launching is not enabled on this server; start "
                    "fcapz-web with --openocd <exe> and --openocd-cfg/-cfg-dir"
                )
            from .board_autodiscover import auto_discover_boards

            boards = auto_discover_boards(
                self._openocd_launcher,
                port_base=_valid_port(req.get("port", 6666)),
                chain=int(req.get("chain", 1)),
                wait_sec=_wait_sec(req, "wait", 10.0),
                timeout_sec=_wait_sec(req, "timeout", 5.0),
            )
            return self._ok(backend="openocd", boards=boards)

        if cmd in ("openocd_start", "openocd_stop", "openocd_status"):
            # Server-managed OpenOCD (web only, loopback-gated by the web layer).
            # Disabled unless fcapz-web was launched with --openocd/--openocd-cfg.
            if self._openocd_launcher is None:
                if cmd == "openocd_status":
                    return self._ok(enabled=False, configs=[], running=[])
                raise RuntimeError(
                    "OpenOCD launching is not enabled on this server; start "
                    "fcapz-web with --openocd <exe> and --openocd-cfg <cfg>"
                )
            if cmd == "openocd_status":
                return self._ok(**self._openocd_launcher.status())
            if cmd == "openocd_start":
                return self._ok(
                    **self._openocd_launcher.start(
                        name=req.get("name"),
                        port=int(req.get("port", 6666)),
                        wait_sec=_wait_sec(req, "wait", 10.0),
                    )
                )
            return self._ok(
                **self._openocd_launcher.stop(port=int(req.get("port", 6666)))
            )

        analyzer = self._ensure_analyzer()

        if cmd == "probe":
            return self._ok(probe=analyzer.probe())

        if cmd == "list_cores":
            slots = self._validated_bool(req.get("slots", False), field="slots")
            return self._ok(cores=self._list_cores(analyzer, slots=slots))

        if cmd == "axi_mon_probe":
            # Detect an AXI monitor and return its geometry + the bundled
            # probe map so the client can capture with named AXI fields. The
            # monitor captures like an ELA; this just adds the AXI-aware glue.
            # The scan covers the other conservative USER chains too, so a
            # session bound to a plain ELA still gets the monitor's full
            # identity — `chain` says where it lives (== the session's chain
            # when the monitor is the connected core), letting clients offer
            # a seamless switch. Absent everywhere -> {present: False}.
            found = self._probe_axi_mon(analyzer)
            if found is None:
                return self._ok(present=False)
            chain, geo, probes = found
            return self._ok(
                present=True,
                chain=chain,
                proto=geo.proto,
                addr_w=geo.addr_w,
                data_w=geo.data_w,
                decode=geo.decode,
                sample_width=geo.sample_width,
                probes=[{"name": p.name, "width": p.width, "lsb": p.lsb} for p in probes],
            )

        if cmd == "ejtag_axi_probe":
            # Auto-detect an EJTAG-AXI bridge on its own USER chain (default
            # USER4). Bridges speak a different DR protocol than the ELA, so
            # this uses the bridge's read-only CONFIG identity scan on the
            # shared transport and restores the session's chain. `chains` may
            # override the candidate set. Absent -> {present: False}.
            raw = req.get("chains")
            chains = tuple(int(c) for c in raw) if raw else (4,)
            found = self._probe_ejtag_axi(analyzer, chains)
            if found is None:
                return self._ok(present=False)
            chain, info = found
            return self._ok(present=True, chain=chain, **info)

        if cmd == "configure":
            analyzer.configure(self._build_config(req))
            return self._ok()

        if cmd == "arm":
            analyzer.arm()
            return self._ok()

        if cmd == "disarm":
            # Soft-reset the capture FSM to a verified idle (discards any
            # in-flight capture) — the web UI's Stop while armed.
            analyzer.force_idle()
            return self._ok()

        if cmd == "capture":
            cfg = self._build_config(req)
            # "Trigger Immediate": rewrite the config to an always-true trigger
            # so the capture fires now instead of waiting (matches the GUI).
            if req.get("immediate"):
                cfg = analyzer.immediate_variant(cfg)
            analyzer.configure(cfg)
            analyzer.arm()
            return self._capture_readout(analyzer, cfg, req)

        if cmd == "capture_wait":
            # Wait on the already-armed capture (`configure` + `arm`) and read
            # it out. Clients hold one hardware arm across many short polls, so
            # an armed wait has no deadline and no re-arm blind gaps; a timeout
            # here just means "still waiting" and leaves the core armed.
            cfg = analyzer._config  # noqa: SLF001 - the session's active config
            if cfg is None:
                raise RuntimeError("not configured - send `configure` and `arm` first")
            return self._capture_readout(analyzer, cfg, req)

        if cmd == "capture_status":
            # Cheap status poll (no sample transfer): lets a client show the
            # real "waiting for trigger" phase, then switch to "reading back"
            # once the trigger has fired -- instead of one opaque blocking wait.
            return self._ok(**analyzer.status())

        if cmd == "eio_connect":
            self._drop_eio()
            base_addr = int(req.get("base_addr", 0))
            instance = req.get("instance")
            if instance is not None:
                # A core-manager slot: attach on the session's transport (see
                # _manager_slots), which only names the session's own board.
                if not self._on_session_board(req):
                    raise ValueError(
                        "an EIO instance must be on the connected ELA session's board"
                    )
                chain = int(req.get("chain", 1))
                eio = EioController(
                    analyzer.transport,
                    chain=chain,
                    base_addr=base_addr,
                    instance=int(instance),
                )
                eio.attach()
                self._eio, self._eio_shared = eio, True
            else:
                chain = int(req.get("chain", 3))
                self._eio = EioController(
                    self._build_transport(req), chain=chain, base_addr=base_addr
                )
                self._eio.connect()
            return self._ok(
                in_w=self._eio.in_w,
                out_w=self._eio.out_w,
                chain=chain,
                base_addr=base_addr,
                instance=self._eio.instance,
            )

        if cmd == "eio_discover":
            self._drop_eio()
            if self._on_session_board(req):
                # EIO slots behind the session's core manager first, on the
                # session's transport (see _manager_slots).
                found = self._manager_slots(analyzer.transport, 1) or []
                eio_slots = [s for s, version in found if version & 0xFFFF == EIO_CORE_ID]
                eio = (
                    discover_eio(analyzer.transport, chains=(), instances=eio_slots)
                    if eio_slots
                    else None
                )
                if eio is not None:
                    self._eio, self._eio_shared = eio, True
                    return self._ok(
                        discovered=True,
                        in_w=eio.in_w,
                        out_w=eio.out_w,
                        chain=eio.bscan_chain,
                        base_addr=eio._base_addr,  # noqa: SLF001
                        instance=eio.instance,
                    )
            transport = self._build_transport(req)
            transport.connect()
            try:
                chains = req.get("chains")
                chains = (
                    [int(c) for c in chains]
                    if chains
                    else sorted(getattr(transport, "ir_table", {}).keys()) or [1]
                )
                eio = discover_eio(transport, chains=chains)
                if eio is None:
                    raise RuntimeError("no EIO core found on the target")
                self._eio = eio
                return self._ok(
                    discovered=True,
                    in_w=eio.in_w,
                    out_w=eio.out_w,
                    chain=eio.bscan_chain,
                    base_addr=eio._base_addr,  # noqa: SLF001 - report discovered offset
                    instance=None,
                )
            except Exception:
                try:
                    transport.close()
                except Exception:
                    pass
                raise

        if cmd == "eio_close":
            self._drop_eio()
            return self._ok()

        if cmd == "eio_read":
            if self._eio is None:
                raise RuntimeError("eio not connected")
            v = self._eio.read_inputs()
            # value stays a JSON number for back-compat; value_hex carries the
            # full width so wide (multiword) EIO survives a 53-bit JS client.
            return self._ok(value=v, value_hex=hex(v))

        if cmd == "eio_write":
            if self._eio is None:
                raise RuntimeError("eio not connected")
            # Accept a base-prefixed string so wide output words don't round.
            self._eio.write_outputs(self._parse_int(req["value"]))
            return self._ok()

        if cmd == "axi_connect":
            if self._axi is not None:
                try:
                    self._axi.close()
                except Exception:
                    pass
                self._axi = None
                self._axi_transport = None
            elif self._axi_transport is not None:
                try:
                    self._axi_transport.close()
                except Exception:
                    pass
                self._axi_transport = None
            chain = int(req.get("chain", 4))
            transport = self._build_transport(req)
            ctrl = EjtagAxiController(transport, chain=chain)
            try:
                info = ctrl.connect()  # opens transport + probes bridge
            except Exception:
                # Clean up on failure — don't leak the session
                try:
                    transport.close()
                except Exception:
                    pass
                raise
            self._axi = ctrl
            self._axi_transport = transport
            return self._ok(**info)

        if cmd == "axi_close":
            if self._axi is not None:
                try:
                    self._axi.close()  # sends RESET + closes transport
                except Exception:
                    pass
                self._axi = None
                self._axi_transport = None
            return self._ok()

        if cmd == "axi_read":
            if self._axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            val = self._axi.axi_read(addr)
            return self._ok(value=f"0x{val:08X}")

        if cmd == "axi_write":
            if self._axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            data = int(req["data"], 16) if isinstance(req["data"], str) else int(req["data"])
            wstrb_raw = req.get("wstrb", "0xF")
            wstrb = int(wstrb_raw, 16) if isinstance(wstrb_raw, str) else int(wstrb_raw)
            resp = self._axi.axi_write(addr, data, wstrb=wstrb)
            return self._ok(resp=resp)

        if cmd == "axi_write_block":
            if self._axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            data_raw = req["data"]
            data = [int(d, 16) if isinstance(d, str) else int(d) for d in data_raw]
            burst = bool(req.get("burst", False))
            if burst:
                self._axi.burst_write(addr, data)
            else:
                self._axi.write_block(addr, data)
            return self._ok(count=len(data))

        if cmd == "axi_dump":
            if self._axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            count = int(req["count"])
            burst = bool(req.get("burst", False))
            if burst:
                words = self._axi.burst_read(addr, count)
            else:
                words = self._axi.read_block(addr, count)
            return self._ok(words=[f"0x{w:08X}" for w in words])

        if cmd == "uart_connect":
            if self._uart is not None:
                try:
                    self._uart.close()
                except Exception:
                    pass
                self._uart = None
                self._uart_transport = None
            elif self._uart_transport is not None:
                try:
                    self._uart_transport.close()
                except Exception:
                    pass
                self._uart_transport = None
            chain = int(req.get("chain", 4))
            transport = self._build_transport(req)
            ctrl = EjtagUartController(transport, chain=chain)
            try:
                info = ctrl.connect()
            except Exception:
                try:
                    transport.close()
                except Exception:
                    pass
                raise
            self._uart = ctrl
            self._uart_transport = transport
            return self._ok(**info)

        if cmd == "uart_close":
            if self._uart is not None:
                try:
                    self._uart.close()
                except Exception:
                    pass
                self._uart = None
                self._uart_transport = None
            return self._ok()

        if cmd == "uart_send":
            if self._uart is None:
                raise RuntimeError("uart not connected")
            raw = req.get("data", "")
            data = base64.b64decode(raw)
            self._uart.send(data)
            return self._ok(bytes_sent=len(data))

        if cmd == "uart_recv":
            if self._uart is None:
                raise RuntimeError("uart not connected")
            count = int(req.get("count", 0))
            timeout = _wait_sec(req, "timeout", 1.0)
            data = self._uart.recv(count=count, timeout=timeout)
            return self._ok(data=base64.b64encode(data).decode("ascii"),
                            bytes_received=len(data))

        if cmd == "uart_status":
            if self._uart is None:
                raise RuntimeError("uart not connected")
            return self._ok(**self._uart.status())

        raise ValueError(f"unknown cmd: {cmd}")


def main() -> int:
    server = RpcServer()
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            resp = server.handle(req)
        except Exception as exc:
            resp = {
                "ok": False,
                "schema_version": _SCHEMA_VERSION,
                "error": str(exc),
                "type": exc.__class__.__name__,
                "trace": traceback.format_exc(limit=1).strip(),
            }
        print(json.dumps(resp), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
