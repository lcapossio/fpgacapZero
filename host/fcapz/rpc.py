# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import base64
import json
import threading
import traceback
from typing import Any, Dict

from .analyzer import Analyzer, CaptureConfig, ProbeSpec, TriggerConfig
from .eio import EioController
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .probes import load_probe_file
from .transport import OpenOcdTransport, Transport, XilinxHwServerTransport

_SCHEMA_VERSION = "1.1"


class RpcServer:
    def __init__(self):
        self._analyzer: Analyzer | None = None
        self._eio: EioController | None = None
        self._eio_transport: Transport | None = None
        self._axi: EjtagAxiController | None = None
        self._axi_transport: Transport | None = None
        self._uart: EjtagUartController | None = None
        self._uart_transport: Transport | None = None
        self._state_lock = threading.RLock()
        self._cancel_generation = 0

    @staticmethod
    def _ok(**payload: Any) -> Dict[str, Any]:
        return {"ok": True, "schema_version": _SCHEMA_VERSION, **payload}

    def _ensure_analyzer(self) -> Analyzer:
        with self._state_lock:
            analyzer = self._analyzer
        if analyzer is None:
            raise RuntimeError("not connected")
        return analyzer

    @staticmethod
    def _cancel_transport(transport: Transport | None) -> None:
        if transport is None:
            return
        try:
            transport.cancel()
        except Exception:
            try:
                transport.close()
            except Exception:
                pass

    def cancel_active(self) -> None:
        """Best-effort abort of all active hardware backends.

        Called by the MCP layer when an RPC worker exceeds its response
        timeout. This tears down the blocking transport I/O underneath the
        worker, so the thread can unwind instead of leaving an orphaned xsdb
        process or OpenOCD socket behind.
        """
        with self._state_lock:
            self._cancel_generation += 1
            analyzer, self._analyzer = self._analyzer, None
            eio_transport, self._eio_transport = self._eio_transport, None
            axi_transport, self._axi_transport = self._axi_transport, None
            uart_transport, self._uart_transport = self._uart_transport, None
            self._eio = None
            self._axi = None
            self._uart = None

        if analyzer is not None:
            try:
                analyzer.close(fast=True)
            except Exception:
                self._cancel_transport(getattr(analyzer, "transport", None))
        self._cancel_transport(eio_transport)
        self._cancel_transport(axi_transport)
        self._cancel_transport(uart_transport)

    def _build_transport(self, req: Dict[str, Any]):
        backend = req.get("backend", "hw_server")
        host = req.get("host", "127.0.0.1")
        if backend == "openocd":
            return OpenOcdTransport(
                host=host,
                port=int(req.get("port", 6666)),
                tap=req.get("tap", "xc7a100t.tap"),
            )
        if backend == "hw_server":
            return XilinxHwServerTransport(
                host=host,
                port=int(req.get("port", 3121)),
                fpga_name=req.get("tap", "xc7a100t"),
                bitfile=req.get("program"),
                single_chain_burst=bool(req.get("single_chain_burst", True)),
            )
        raise ValueError(f"unknown backend: {backend}")

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
                value=int(req.get("trigger_value", 0)),
                mask=int(req.get("trigger_mask", 0xFF)),
            ),
            sample_width=int(req.get("sample_width", file_sample_width)),
            depth=int(req.get("depth", 1024)),
            sample_clock_hz=int(req.get("sample_clock_hz", file_sample_clock_hz)),
            probes=probes,
            channel=int(req.get("channel", 0)),
            decimation=int(req.get("decimation", 0)),
            ext_trigger_mode=int(req.get("ext_trigger_mode", 0)),
            stor_qual_mode=cls._validated_sq_mode(int(req.get("stor_qual_mode", 0))),
            stor_qual_value=int(req.get("stor_qual_value", 0)),
            stor_qual_mask=int(req.get("stor_qual_mask", 0)),
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
            with self._state_lock:
                old_analyzer, self._analyzer = self._analyzer, None
            if old_analyzer is not None:
                old_analyzer.close()
            with self._state_lock:
                generation = self._cancel_generation
            analyzer = Analyzer(self._build_transport(req))
            with self._state_lock:
                self._analyzer = analyzer
            try:
                analyzer.connect()
            except Exception:
                with self._state_lock:
                    if self._analyzer is analyzer:
                        self._analyzer = None
                raise
            with self._state_lock:
                if generation != self._cancel_generation:
                    if self._analyzer is analyzer:
                        self._analyzer = None
                    cancel_raced = True
                else:
                    cancel_raced = False
            if cancel_raced:
                analyzer.close(fast=True)
                raise RuntimeError("connect completed after cancellation")
            return self._ok()

        if cmd == "close":
            with self._state_lock:
                analyzer, self._analyzer = self._analyzer, None
            if analyzer is not None:
                analyzer.close()
            return self._ok()

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
            analyzer.configure(cfg)
            analyzer.arm()
            result = analyzer.capture(timeout=float(req.get("timeout", 10.0)))
            payload = self._serialize_capture(
                analyzer,
                cfg,
                result,
                fmt=str(req.get("format", "json")),
                include_summary=bool(req.get("summarize", False)),
            )
            return self._ok(**payload)

        if cmd == "eio_connect":
            with self._state_lock:
                old_eio, self._eio = self._eio, None
                old_transport, self._eio_transport = self._eio_transport, None
            if old_eio is not None:
                old_eio.close()
            elif old_transport is not None:
                old_transport.close()
            chain = int(req.get("chain", 3))
            with self._state_lock:
                generation = self._cancel_generation
            transport = self._build_transport(req)
            with self._state_lock:
                self._eio_transport = transport
            eio = EioController(transport, chain=chain)
            try:
                eio.connect()
            except Exception:
                try:
                    transport.close()
                except Exception:
                    pass
                with self._state_lock:
                    if self._eio_transport is transport:
                        self._eio_transport = None
                raise
            with self._state_lock:
                if generation != self._cancel_generation:
                    if self._eio_transport is transport:
                        self._eio_transport = None
                    cancel_raced = True
                else:
                    self._eio = eio
                    cancel_raced = False
            if cancel_raced:
                eio.close()
                raise RuntimeError("eio_connect completed after cancellation")
            return self._ok(in_w=eio.in_w, out_w=eio.out_w, chain=chain)

        if cmd == "eio_close":
            with self._state_lock:
                eio, self._eio = self._eio, None
                self._eio_transport = None
            if eio is not None:
                eio.close()
            return self._ok()

        if cmd == "eio_read":
            with self._state_lock:
                eio = self._eio
            if eio is None:
                raise RuntimeError("eio not connected")
            return self._ok(value=eio.read_inputs())

        if cmd == "eio_write":
            with self._state_lock:
                eio = self._eio
            if eio is None:
                raise RuntimeError("eio not connected")
            eio.write_outputs(int(req["value"]))
            return self._ok()

        if cmd == "axi_connect":
            with self._state_lock:
                old_axi, self._axi = self._axi, None
                old_transport, self._axi_transport = self._axi_transport, None
            if old_axi is not None:
                try:
                    old_axi.close()
                except Exception:
                    pass
            elif old_transport is not None:
                try:
                    old_transport.close()
                except Exception:
                    pass
            chain = int(req.get("chain", 4))
            with self._state_lock:
                generation = self._cancel_generation
            transport = self._build_transport(req)
            ctrl = EjtagAxiController(transport, chain=chain)
            with self._state_lock:
                self._axi_transport = transport
            try:
                info = ctrl.connect()  # opens transport + probes bridge
            except Exception:
                # Clean up on failure; don't leak the session.
                try:
                    transport.close()
                except Exception:
                    pass
                with self._state_lock:
                    if self._axi_transport is transport:
                        self._axi_transport = None
                raise
            with self._state_lock:
                if generation != self._cancel_generation:
                    if self._axi_transport is transport:
                        self._axi_transport = None
                    cancel_raced = True
                else:
                    self._axi = ctrl
                    cancel_raced = False
            if cancel_raced:
                ctrl.close()
                raise RuntimeError("axi_connect completed after cancellation")
            return self._ok(**info)

        if cmd == "axi_close":
            with self._state_lock:
                axi, self._axi = self._axi, None
                self._axi_transport = None
            if axi is not None:
                try:
                    axi.close()  # sends RESET + closes transport
                except Exception:
                    pass
            return self._ok()

        if cmd == "axi_read":
            with self._state_lock:
                axi = self._axi
            if axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            val = axi.axi_read(addr)
            return self._ok(value=f"0x{val:08X}")

        if cmd == "axi_write":
            with self._state_lock:
                axi = self._axi
            if axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            data = int(req["data"], 16) if isinstance(req["data"], str) else int(req["data"])
            wstrb_raw = req.get("wstrb", "0xF")
            wstrb = int(wstrb_raw, 16) if isinstance(wstrb_raw, str) else int(wstrb_raw)
            resp = axi.axi_write(addr, data, wstrb=wstrb)
            return self._ok(resp=resp)

        if cmd == "axi_write_block":
            with self._state_lock:
                axi = self._axi
            if axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            data_raw = req["data"]
            data = [int(d, 16) if isinstance(d, str) else int(d) for d in data_raw]
            burst = bool(req.get("burst", False))
            if burst:
                axi.burst_write(addr, data)
            else:
                axi.write_block(addr, data)
            return self._ok(count=len(data))

        if cmd == "axi_dump":
            with self._state_lock:
                axi = self._axi
            if axi is None:
                raise RuntimeError("axi not connected")
            addr = int(req["addr"], 16) if isinstance(req["addr"], str) else int(req["addr"])
            count = int(req["count"])
            burst = bool(req.get("burst", False))
            if burst:
                words = axi.burst_read(addr, count)
            else:
                words = axi.read_block(addr, count)
            return self._ok(words=[f"0x{w:08X}" for w in words])

        if cmd == "uart_connect":
            with self._state_lock:
                old_uart, self._uart = self._uart, None
                old_transport, self._uart_transport = self._uart_transport, None
            if old_uart is not None:
                try:
                    old_uart.close()
                except Exception:
                    pass
            elif old_transport is not None:
                try:
                    old_transport.close()
                except Exception:
                    pass
            chain = int(req.get("chain", 4))
            with self._state_lock:
                generation = self._cancel_generation
            transport = self._build_transport(req)
            ctrl = EjtagUartController(transport, chain=chain)
            with self._state_lock:
                self._uart_transport = transport
            try:
                info = ctrl.connect()
            except Exception:
                try:
                    transport.close()
                except Exception:
                    pass
                with self._state_lock:
                    if self._uart_transport is transport:
                        self._uart_transport = None
                raise
            with self._state_lock:
                if generation != self._cancel_generation:
                    if self._uart_transport is transport:
                        self._uart_transport = None
                    cancel_raced = True
                else:
                    self._uart = ctrl
                    cancel_raced = False
            if cancel_raced:
                ctrl.close()
                raise RuntimeError("uart_connect completed after cancellation")
            return self._ok(**info)

        if cmd == "uart_close":
            with self._state_lock:
                uart, self._uart = self._uart, None
                self._uart_transport = None
            if uart is not None:
                try:
                    uart.close()
                except Exception:
                    pass
            return self._ok()

        if cmd == "uart_send":
            with self._state_lock:
                uart = self._uart
            if uart is None:
                raise RuntimeError("uart not connected")
            raw = req.get("data", "")
            data = base64.b64decode(raw)
            uart.send(data)
            return self._ok(bytes_sent=len(data))

        if cmd == "uart_recv":
            with self._state_lock:
                uart = self._uart
            if uart is None:
                raise RuntimeError("uart not connected")
            count = int(req.get("count", 0))
            timeout = float(req.get("timeout", 1.0))
            data = uart.recv(count=count, timeout=timeout)
            return self._ok(data=base64.b64encode(data).decode("ascii"),
                            bytes_received=len(data))

        if cmd == "uart_status":
            with self._state_lock:
                uart = self._uart
            if uart is None:
                raise RuntimeError("uart not connected")
            return self._ok(**uart.status())

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
