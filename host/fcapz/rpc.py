# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import base64
import json
import traceback
from typing import Any, Dict

from .analyzer import Analyzer, CaptureConfig, ProbeSpec, TriggerConfig
from .eio import EioController
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .transport import OpenOcdTransport, Transport, XilinxHwServerTransport

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

    def _build_transport(self, req: Dict[str, Any]):
        backend = req.get("backend", "openocd")
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

    @classmethod
    def _build_config(cls, req: Dict[str, Any]) -> CaptureConfig:
        return CaptureConfig(
            pretrigger=int(req.get("pretrigger", 8)),
            posttrigger=int(req.get("posttrigger", 16)),
            trigger=TriggerConfig(
                mode=req.get("trigger_mode", "value_match"),
                value=int(req.get("trigger_value", 0)),
                mask=int(req.get("trigger_mask", 0xFF)),
            ),
            sample_width=int(req.get("sample_width", 8)),
            depth=int(req.get("depth", 1024)),
            sample_clock_hz=int(req.get("sample_clock_hz", 100_000_000)),
            probes=cls._parse_probes(req.get("probes")),
            channel=int(req.get("channel", 0)),
            decimation=int(req.get("decimation", 0)),
            ext_trigger_mode=int(req.get("ext_trigger_mode", 0)),
            stor_qual_mode=cls._validated_sq_mode(int(req.get("stor_qual_mode", 0))),
            stor_qual_value=int(req.get("stor_qual_value", 0)),
            stor_qual_mask=int(req.get("stor_qual_mask", 0)),
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
            self._analyzer = Analyzer(self._build_transport(req))
            self._analyzer.connect()
            return self._ok()

        if cmd == "close":
            if self._analyzer is not None:
                self._analyzer.close()
                self._analyzer = None
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
            if self._eio is not None:
                self._eio.close()
            chain = int(req.get("chain", 3))
            self._eio = EioController(self._build_transport(req), chain=chain)
            self._eio.connect()
            return self._ok(in_w=self._eio.in_w, out_w=self._eio.out_w, chain=chain)

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
