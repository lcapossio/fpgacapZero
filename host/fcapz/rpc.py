# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import base64
import json
import traceback
from typing import Any, Dict

from .analyzer import Analyzer, CaptureConfig, ProbeSpec, SequencerStage, TriggerConfig
from .eio import EioController, discover_eio
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .probes import load_probe_file
from .transport import (
    OpenOcdTransport,
    Transport,
    XilinxHwServerTransport,
    list_openocd_taps,
    list_xilinx_hw_server_targets,
)

_SCHEMA_VERSION = "1.1"


class RpcServer:
    def __init__(self):
        self._analyzer: Analyzer | None = None
        self._eio: EioController | None = None
        self._axi: EjtagAxiController | None = None
        self._axi_transport: Transport | None = None
        self._uart: EjtagUartController | None = None
        self._uart_transport: Transport | None = None

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

    def _build_transport(self, req: Dict[str, Any]):
        backend = req.get("backend", "hw_server")
        host = req.get("host", "127.0.0.1")
        ir = self._ir_table(req.get("ir_table"))
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
        return int(value, 0) if isinstance(value, str) else int(value)

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
            if self._analyzer is not None:
                self._analyzer.close()
            self._analyzer = Analyzer(
                self._build_transport(req), chain=int(req.get("chain", 1))
            )
            self._analyzer.connect()
            return self._ok()

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
                    timeout_sec=float(req.get("timeout", 5.0)),
                )
                return self._ok(backend="openocd", targets=taps)
            if backend == "hw_server":
                targets = list_xilinx_hw_server_targets(
                    host=host,
                    port=int(req.get("port", 3121)),
                    timeout_sec=float(req.get("timeout", 10.0)),
                )
                return self._ok(backend="hw_server", targets=targets)
            raise ValueError(f"unknown backend: {backend}")

        analyzer = self._ensure_analyzer()

        if cmd == "probe":
            return self._ok(probe=analyzer.probe())

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
            timeout = float(req.get("timeout", 10.0))
            if req.get("segments"):
                if not analyzer.wait_all_segments_done(timeout=timeout):
                    raise TimeoutError("segmented capture did not complete within timeout")
                probe_info = analyzer.probe()
                nseg = max(1, int(probe_info.get("num_segments", 1)))
                results = [analyzer.capture_segment(i, timeout=timeout) for i in range(nseg)]
                payload = self._ok(
                    format="json",
                    overflow=any(r.overflow for r in results),
                    sample_count=sum(len(r.samples) for r in results),
                    channel=cfg.channel,
                    result={"segments": [analyzer.export_json(r) for r in results]},
                    segments=[
                        self._serialize_capture(
                            analyzer,
                            cfg,
                            r,
                            fmt=str(req.get("format", "json")),
                            include_summary=bool(req.get("summarize", False)),
                        )
                        for r in results
                    ],
                )
                if req.get("include_vcd") and results:
                    payload["vcd"] = analyzer.export_vcd_text(results[0])
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
            return self._ok(value=self._eio.read_inputs())

        if cmd == "eio_write":
            if self._eio is None:
                raise RuntimeError("eio not connected")
            self._eio.write_outputs(int(req["value"]))
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
            timeout = float(req.get("timeout", 1.0))
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
