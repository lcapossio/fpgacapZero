# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import base64
import json
import traceback
from typing import Any, Dict

from .analyzer import (
    Analyzer,
    CaptureConfig,
    ProbeSpec,
    SequencerStage,
    TriggerConfig,
    _infer_ir_table_name,
    discover_boards,
)
from .axi_monitor import ADDR_AXI_MON_ID, AXI_MON_MAGIC, AxiMonitor
from .eio import EioController, discover_eio
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .openocd_launcher import OpenOcdLauncher
from .probes import load_probe_file
from .transport import (
    OpenOcdTransport,
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


class RpcServer:
    def __init__(self, openocd_launcher: OpenOcdLauncher | None = None):
        self._analyzer: Analyzer | None = None
        self._eio: EioController | None = None
        self._axi: EjtagAxiController | None = None
        self._axi_transport: Transport | None = None
        self._uart: EjtagUartController | None = None
        self._uart_transport: Transport | None = None
        # Optional server-managed OpenOCD (None = the openocd_* commands are
        # disabled and report so). Configured only by the web server launch.
        self._openocd_launcher = openocd_launcher

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
        _shut(self._eio)
        _shut(self._axi if self._axi is not None else self._axi_transport)
        _shut(self._uart if self._uart is not None else self._uart_transport)
        self._analyzer = None
        self._eio = None
        self._axi = None
        self._axi_transport = None
        self._uart = None
        self._uart_transport = None

    def _list_cores(self, analyzer: Analyzer) -> list[Dict[str, Any]]:
        """Enumerate the fcapz cores reachable on the connected session.

        Always reports the connected ELA; adds the EIO if one is discoverable
        (reusing an already-attached controller, else a read-only probe that
        restores chain 1). Other core types (AXI/UART/core-manager) are not yet
        auto-scanned here. Each entry: ``{type, name, core_id, chain, base_addr,
        version_major, version_minor, info}``.
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
                "base_addr": eio._base_addr,  # noqa: SLF001 - report discovered offset
                "version_major": eio.version_major,
                "version_minor": eio.version_minor,
                "info": {"in_w": eio.in_w, "out_w": eio.out_w},
            })

        # The AXI monitor is the connected ELA plus an identity/geometry pair —
        # report it so clients can label the session as a bus monitor.
        try:
            mon = AxiMonitor(analyzer)
            geo = mon.geometry() if mon.present else None
        except Exception:
            geo = None
        if geo is not None and ela is not None:
            cores.append({
                "type": "axi_mon",
                "name": _CORE_NAMES[AXI_MON_MAGIC],
                "core_id": AXI_MON_MAGIC,
                "chain": analyzer.bscan_chain,
                "base_addr": 0,
                "version_major": ela["version_major"],
                "version_minor": ela["version_minor"],
                "info": {
                    "proto": geo.proto,
                    "addr_w": geo.addr_w,
                    "data_w": geo.data_w,
                    "decode": geo.decode,
                    "sample_width": geo.sample_width,
                },
            })
        return cores

    # ir_table preset name -> table (None = transport default, Xilinx 7-series).
    _IR_TABLES = {
        "": None,
        "xilinx7": None,
        "7series": None,
        "series7": None,
        "ultrascale": OpenOcdTransport.IR_TABLE_US,
        "us": OpenOcdTransport.IR_TABLE_US,
        "gowin": OpenOcdTransport.IR_TABLE_GOWIN,
        "gw": OpenOcdTransport.IR_TABLE_GOWIN,
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
        if name is None or not str(name).strip():
            return _infer_ir_table_name(str(req.get("tap", "")))
        return str(name)

    @staticmethod
    def _scan_axi_mon_chains(analyzer: Analyzer) -> list[int]:
        """USER chains (other than the connected one) with an AXI monitor.

        Conservative sweep of chains 1-2 only — the same set discover_eio
        probes — so cores speaking a different DR protocol (EJTAG bridges on
        3/4) never see stray shifts. Restores the analyzer's chain afterwards.
        """
        found: list[int] = []
        t = analyzer.transport
        with t.transaction_lock():
            for chain in (1, 2):
                if chain == analyzer.bscan_chain:
                    continue
                try:
                    t.select_chain(chain)
                    raw = t.read_reg(ADDR_AXI_MON_ID)
                except (NotImplementedError, OSError, RuntimeError):
                    continue
                if (raw >> 16) == AXI_MON_MAGIC:
                    found.append(chain)
            try:
                t.select_chain(analyzer.bscan_chain)
            except NotImplementedError:
                pass
        try:
            t.invalidate_manager_instance_cache()
        except Exception:
            pass
        return found

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
                ir_table=ir,
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
            self._analyzer = Analyzer(
                self._build_transport(req), chain=int(req.get("chain", 1))
            )
            self._analyzer.connect()
            # Echo the resolved preset so a client that omitted ir_table can
            # label the session and reuse it for eio/axi side connects.
            return self._ok(ir_table=self._resolved_ir_name(req))

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
            return self._ok(cores=self._list_cores(analyzer))

        if cmd == "axi_mon_probe":
            # Detect an AXI monitor and return its geometry +
            # the bundled probe map so the client can capture with named AXI
            # fields. The monitor captures like an ELA; this just adds the
            # AXI-aware glue. Absent -> {present: False} (not an error), with
            # a scan of the other USER chains so a client connected to the
            # wrong chain learns where the monitor actually lives.
            mon = AxiMonitor(analyzer)
            geo = mon.geometry() if mon.present else None
            if geo is None:
                return self._ok(
                    present=False,
                    found_on_chains=self._scan_axi_mon_chains(analyzer),
                )
            probes = mon.probe_map(geo).probes
            return self._ok(
                present=True,
                proto=geo.proto,
                addr_w=geo.addr_w,
                data_w=geo.data_w,
                decode=geo.decode,
                sample_width=geo.sample_width,
                probes=[{"name": p.name, "width": p.width, "lsb": p.lsb} for p in probes],
            )

        if cmd == "configure":
            analyzer.configure(self._build_config(req))
            return self._ok()

        if cmd == "arm":
            analyzer.arm()
            return self._ok()

        if cmd == "capture":
            cfg = self._build_config(req)
            # "Trigger Immediate": rewrite the config to an always-true trigger
            # so the capture fires now instead of waiting (matches the GUI).
            if req.get("immediate"):
                cfg = analyzer.immediate_variant(cfg)
            analyzer.configure(cfg)
            analyzer.arm()
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

        if cmd == "eio_connect":
            if self._eio is not None:
                self._eio.close()
            chain = int(req.get("chain", 3))
            base_addr = int(req.get("base_addr", 0))
            instance = req.get("instance")
            self._eio = EioController(
                self._build_transport(req),
                chain=chain,
                base_addr=base_addr,
                instance=None if instance is None else int(instance),
            )
            self._eio.connect()
            return self._ok(
                in_w=self._eio.in_w,
                out_w=self._eio.out_w,
                chain=chain,
                base_addr=base_addr,
            )

        if cmd == "eio_discover":
            if self._eio is not None:
                self._eio.close()
                self._eio = None
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
                )
            except Exception:
                try:
                    transport.close()
                except Exception:
                    pass
                raise

        if cmd == "eio_close":
            if self._eio is not None:
                self._eio.close()
                self._eio = None
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
