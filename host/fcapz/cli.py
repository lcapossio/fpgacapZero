# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyzer import Analyzer, CaptureConfig, ProbeSpec, SequencerStage, TriggerConfig
from .eio import EioController
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import ProbeDefinition, summarize
from .transport import OpenOcdTransport, XilinxHwServerTransport


def _positive_int(value: str) -> int:
    """argparse type: strictly positive integer."""
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
    return n


def _non_negative_int(value: str) -> int:
    """argparse type: non-negative integer (>=0)."""
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _positive_float(value: str) -> float:
    """argparse type: strictly positive float."""
    f = float(value)
    if f <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {f}")
    return f


def _tcp_port(value: str) -> int:
    """argparse type: valid TCP port (1-65535)."""
    n = int(value)
    if not (1 <= n <= 65535):
        raise argparse.ArgumentTypeError(f"port must be 1-65535, got {n}")
    return n


def _uint16(value: str) -> int:
    """argparse type: 16-bit unsigned integer (0..65535)."""
    n = int(value, 0)  # accept decimal or hex
    if not (0 <= n <= 0xFFFF):
        raise argparse.ArgumentTypeError(f"must be 0..65535, got {n}")
    return n


def _parse_probes(spec: str) -> list[ProbeSpec]:
    """Parse ``name:width:lsb,name:width:lsb,...`` into ProbeSpec list."""
    probes = []
    for part in spec.split(","):
        fields = part.strip().split(":")
        if len(fields) != 3:
            raise argparse.ArgumentTypeError(
                f"invalid probe spec '{part}', expected name:width:lsb"
            )
        probes.append(ProbeSpec(name=fields[0], width=int(fields[1]), lsb=int(fields[2])))
    return probes


def _parse_trigger_sequence(raw: str) -> list[SequencerStage]:
    """Parse a JSON file path or inline JSON string into SequencerStage list."""
    import os

    try:
        if os.path.isfile(raw):
            with open(raw, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        raise argparse.ArgumentTypeError(f"--trigger-sequence: {exc}") from exc

    if not isinstance(data, list):
        raise argparse.ArgumentTypeError("--trigger-sequence must be a JSON array")

    stages: list[SequencerStage] = []
    for entry in data:
        stages.append(SequencerStage(
            cmp_mode_a=int(entry.get("cmp_a", 0)),
            cmp_mode_b=int(entry.get("cmp_b", 0)),
            combine=int(entry.get("combine", 0)),
            next_state=int(entry.get("next_state", 0)),
            is_final=bool(entry.get("is_final", False)),
            count_target=int(entry.get("count", 1)),
            value_a=int(str(entry.get("value_a", 0)), 0),
            mask_a=int(str(entry.get("mask_a", "0xFFFFFFFF")), 0),
            value_b=int(str(entry.get("value_b", 0)), 0),
            mask_b=int(str(entry.get("mask_b", "0xFFFFFFFF")), 0),
        ))
    return stages


def _build_config(args: argparse.Namespace) -> CaptureConfig:
    probes = []
    probe_str = getattr(args, "probes", None)
    if probe_str:
        probes = _parse_probes(probe_str)
    # Parse trigger sequence if provided
    sequence = None
    seq_raw = getattr(args, "trigger_sequence", None)
    if seq_raw:
        sequence = _parse_trigger_sequence(seq_raw)

    return CaptureConfig(
        pretrigger=args.pretrigger,
        posttrigger=args.posttrigger,
        trigger=TriggerConfig(
            mode=args.trigger_mode,
            value=args.trigger_value,
            mask=args.trigger_mask,
        ),
        sample_width=args.sample_width,
        depth=args.depth,
        sample_clock_hz=args.sample_clock_hz,
        probes=probes,
        channel=args.channel,
        decimation=getattr(args, "decimation", 0),
        ext_trigger_mode={"disabled": 0, "or": 1, "and": 2}.get(
            getattr(args, "ext_trigger_mode", "disabled"), 0),
        sequence=sequence,
        probe_sel=getattr(args, "probe_sel", 0),
        stor_qual_mode=getattr(args, "stor_qual_mode", 0),
        stor_qual_value=getattr(args, "stor_qual_value", 0),
        stor_qual_mask=getattr(args, "stor_qual_mask", 0),
        trigger_delay=getattr(args, "trigger_delay", 0),
    )


def _make_transport(args: argparse.Namespace):
    if args.backend == "openocd":
        return OpenOcdTransport(host=args.host, port=args.port, tap=args.tap)
    fpga_name = args.tap.removesuffix(".tap") if hasattr(args, "tap") else "xc7a100t"
    port = args.port if args.port != 6666 else 3121
    bitfile = getattr(args, "program", None)
    return XilinxHwServerTransport(
        host=args.host, port=port, fpga_name=fpga_name, bitfile=bitfile,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fcapz", description="fpgacapZero host CLI")
    p.add_argument(
        "--gui-config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to gui.toml (default: per-user fpgacapzero config directory)",
    )
    p.add_argument("--backend", choices=["openocd", "hw_server"], default="hw_server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=_tcp_port, default=6666)
    p.add_argument("--tap", default="xc7a100t.tap", help="OpenOCD TAP name / hw_server FPGA target")
    p.add_argument(
        "--program",
        metavar="BITFILE",
        default=None,
        help=(
            "hw_server only: run fpga -file on this .bit before the command (slow). "
            "Omit to attach to the FPGA without reprogramming (already-loaded bitstream)."
        ),
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="Read core identity registers")
    sub.add_parser("arm", help="Arm capture")

    cfg = sub.add_parser("configure", help="Write capture configuration")
    cap = sub.add_parser("capture", help="Configure, arm, capture, export")

    for parser in [cfg, cap]:
        parser.add_argument("--pretrigger", type=int, default=8)
        parser.add_argument("--posttrigger", type=int, default=16)
        parser.add_argument(
            "--trigger-mode",
            choices=["value_match", "edge_detect", "both"],
            default="value_match",
        )
        parser.add_argument("--trigger-value", type=int, default=0)
        parser.add_argument("--trigger-mask", type=lambda x: int(x, 0), default=0xFF)
        parser.add_argument("--sample-width", type=int, default=8)
        parser.add_argument("--depth", type=int, default=1024)
        parser.add_argument("--sample-clock-hz", type=int, default=100_000_000)
        parser.add_argument("--channel", type=int, default=0, help="Probe mux channel index")
        parser.add_argument(
            "--decimation", type=int, default=0,
            help="Sample decimation ratio (0=every cycle, N=every N+1)",
        )
        parser.add_argument(
            "--ext-trigger-mode", default="disabled",
            choices=["disabled", "or", "and"],
            help="Ext trigger: disabled, or, and",
        )
        parser.add_argument(
            "--probes",
            default=None,
            help="Signal definitions: name:width:lsb,... (e.g. bus0:4:0,bus1:4:4)",
        )
        parser.add_argument(
            "--trigger-sequence",
            default=None,
            help="JSON file path or inline JSON array of sequencer stages",
        )
        parser.add_argument(
            "--probe-sel",
            type=int,
            default=0,
            help="Runtime probe mux slice index (default 0)",
        )
        parser.add_argument(
            "--stor-qual-mode",
            type=int,
            default=0,
            help="Storage qualification mode: 0=disabled, "
            "1=store-when-match, 2=store-when-no-match",
        )
        parser.add_argument(
            "--stor-qual-value",
            type=lambda x: int(x, 0),
            default=0,
            help="Storage qualification comparison value (hex or decimal)",
        )
        parser.add_argument(
            "--stor-qual-mask",
            type=lambda x: int(x, 0),
            default=0,
            help="Storage qualification mask (hex or decimal)",
        )
        parser.add_argument(
            "--trigger-delay",
            type=_uint16,
            default=0,
            help=(
                "Post-trigger delay in sample-clock cycles (0..65535). "
                "Shifts the committed trigger sample N cycles after the "
                "trigger event to compensate for upstream pipeline latency."
            ),
        )
        parser.add_argument(
            "--profile",
            default=None,
            metavar="NAME",
            help="Use named probe list from gui.toml section [probe_profiles.NAME]",
        )

    cap.add_argument("--timeout", type=_positive_float, default=10.0)
    cap.add_argument("--out", required=True)
    cap.add_argument("--format", choices=["json", "csv", "vcd"], default="json")
    cap.add_argument(
        "--summarize",
        action="store_true",
        help="Print LLM-friendly capture summary to stdout",
    )
    cap.add_argument(
        "--open-in",
        default=None,
        metavar="VIEWER",
        help=(
            "After capture, open the dump in a waveform viewer (requires "
            "--format vcd). Names: gtkwave, surfer, wavetrace, custom (needs "
            "gui.toml custom_argv)."
        ),
    )

    # -- EIO subcommands ---------------------------------------------------
    eio_probe = sub.add_parser("eio-probe", help="Read EIO core identity and widths")
    eio_probe.add_argument("--chain", type=int, default=3, help="BSCANE2 USER chain (default 3)")

    eio_read = sub.add_parser("eio-read", help="Read EIO input probes")
    eio_read.add_argument("--chain", type=int, default=3, help="BSCANE2 USER chain (default 3)")

    eio_write = sub.add_parser("eio-write", help="Write EIO output probes")
    eio_write.add_argument("--chain", type=int, default=3, help="BSCANE2 USER chain (default 3)")
    eio_write.add_argument("value", type=lambda x: int(x, 0), help="Output value (hex or decimal)")

    # -- AXI subcommands ---------------------------------------------------
    axi_read = sub.add_parser("axi-read", help="Single AXI read via JTAG-to-AXI bridge")
    axi_read.add_argument(
        "--addr", type=lambda x: int(x, 0), required=True,
        help="AXI address (hex)",
    )
    axi_read.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")

    axi_write = sub.add_parser("axi-write", help="Single AXI write via JTAG-to-AXI bridge")
    axi_write.add_argument(
        "--addr", type=lambda x: int(x, 0), required=True,
        help="AXI address (hex)",
    )
    axi_write.add_argument(
        "--data", type=lambda x: int(x, 0), required=True,
        help="Write data (hex)",
    )
    axi_write.add_argument(
        "--wstrb", type=lambda x: int(x, 0), default=0xF,
        help="Write strobe (hex, default 0xf)",
    )
    axi_write.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")

    axi_dump = sub.add_parser("axi-dump", help="Read block of AXI words")
    axi_dump.add_argument(
        "--addr", type=lambda x: int(x, 0), required=True,
        help="Start address (hex)",
    )
    axi_dump.add_argument(
        "--count", type=_positive_int, required=True,
        help="Number of 32-bit words to read",
    )
    axi_dump.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    axi_dump.add_argument("--burst", action="store_true", help="Use AXI4 burst transfers")

    axi_fill = sub.add_parser("axi-fill", help="Fill AXI memory with a pattern")
    axi_fill.add_argument(
        "--addr", type=lambda x: int(x, 0), required=True,
        help="Start address (hex)",
    )
    axi_fill.add_argument(
        "--count", type=_positive_int, required=True,
        help="Number of 32-bit words to fill",
    )
    axi_fill.add_argument(
        "--pattern", type=lambda x: int(x, 0), required=True,
        help="Fill pattern (hex)",
    )
    axi_fill.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    axi_fill.add_argument("--burst", action="store_true", help="Use AXI4 burst transfers")

    axi_load = sub.add_parser("axi-load", help="Load binary file into AXI memory")
    axi_load.add_argument(
        "--addr", type=lambda x: int(x, 0), required=True,
        help="Start address (hex)",
    )
    axi_load.add_argument(
        "--file", type=argparse.FileType("rb"), required=True,
        help="Binary file to load",
    )
    axi_load.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    axi_load.add_argument("--burst", action="store_true", help="Use AXI4 burst transfers")

    # -- UART subcommands -------------------------------------------------
    uart_send = sub.add_parser("uart-send", help="Send data to UART TX via JTAG-to-UART bridge")
    uart_send.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    uart_send_src = uart_send.add_mutually_exclusive_group(required=True)
    uart_send_src.add_argument("--data", type=str, help="String data to send")
    uart_send_src.add_argument("--file", type=argparse.FileType("rb"), help="Binary file to send")
    uart_send_src.add_argument(
        "--hex", type=str,
        help="Hex-encoded bytes to send (e.g. 48656C6C6F)",
    )

    uart_recv = sub.add_parser(
        "uart-recv",
        help="Receive data from UART RX via JTAG-to-UART bridge",
    )
    uart_recv.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    uart_recv.add_argument(
        "--count", type=_non_negative_int, default=0,
        help="Number of bytes to receive (0=all available)",
    )
    uart_recv.add_argument(
        "--timeout", type=_positive_float, default=1.0,
        help="Receive timeout in seconds",
    )
    uart_recv.add_argument("--line", action="store_true", help="Receive until newline")

    uart_monitor = sub.add_parser("uart-monitor", help="Continuous UART receive (Ctrl+C to stop)")
    uart_monitor.add_argument("--chain", type=int, default=4, help="BSCANE2 USER chain (default 4)")
    uart_monitor.add_argument(
        "--timeout", type=_positive_float, default=0.5,
        help="Per-poll timeout in seconds",
    )

    return p


def main() -> int:
    args = build_parser().parse_args()
    transport = _make_transport(args)

    # -- EIO commands ------------------------------------------------------
    if args.cmd in ("eio-probe", "eio-read", "eio-write"):
        eio = EioController(transport, chain=args.chain)
        try:
            eio.connect()
            if args.cmd == "eio-probe":
                print(json.dumps({
                    "in_w": eio.in_w,
                    "out_w": eio.out_w,
                    "chain": args.chain,
                }, indent=2))
            elif args.cmd == "eio-read":
                print(f"0x{eio.read_inputs():X}")
            elif args.cmd == "eio-write":
                eio.write_outputs(args.value)
                print(f"wrote 0x{args.value:X}")
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            eio.close()

    # -- AXI commands ------------------------------------------------------
    if args.cmd in ("axi-read", "axi-write", "axi-dump",
                     "axi-fill", "axi-load"):
        axi = EjtagAxiController(transport, chain=args.chain)
        connected = False
        try:
            axi.connect()  # opens transport + selects chain
            connected = True
            if args.cmd == "axi-read":
                val = axi.axi_read(args.addr)
                print(f"0x{val:08X}")
            elif args.cmd == "axi-write":
                resp = axi.axi_write(args.addr, args.data, wstrb=args.wstrb)
                print(f"wrote 0x{args.data:08X} -> 0x{args.addr:08X} (resp={resp})")
            elif args.cmd == "axi-dump":
                if args.burst:
                    words = axi.burst_read(args.addr, args.count)
                else:
                    words = axi.read_block(args.addr, args.count)
                for i, w in enumerate(words):
                    print(f"0x{args.addr + i * 4:08X}: 0x{w:08X}")
            elif args.cmd == "axi-fill":
                data = [args.pattern] * args.count
                if args.burst:
                    axi.burst_write(args.addr, data)
                else:
                    axi.write_block(args.addr, data)
                print(f"filled {args.count} words @ 0x{args.addr:08X}")
            elif args.cmd == "axi-load":
                raw = args.file.read()
                if len(raw) % 4 != 0:
                    raw += b'\x00' * (4 - len(raw) % 4)
                words = [int.from_bytes(raw[i:i+4], 'little')
                         for i in range(0, len(raw), 4)]
                if args.burst:
                    axi.burst_write(args.addr, words)
                else:
                    axi.write_block(args.addr, words)
                print(f"loaded {len(words)} words @ 0x{args.addr:08X}")
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            if connected:
                try:
                    axi.close()  # sends RESET + closes transport
                except Exception:
                    pass  # don't mask the original error

    # -- UART commands -----------------------------------------------------
    if args.cmd in ("uart-send", "uart-recv", "uart-monitor"):
        uart = EjtagUartController(transport, chain=args.chain)
        connected = False
        try:
            uart.connect()
            connected = True
            if args.cmd == "uart-send":
                if args.data is not None:
                    payload = args.data.encode("utf-8")
                elif args.file is not None:
                    payload = args.file.read()
                else:
                    payload = bytes.fromhex(args.hex)
                uart.send(payload)
                print(f"sent {len(payload)} bytes")
            elif args.cmd == "uart-recv":
                if args.line:
                    data = uart.recv_line(timeout=args.timeout)
                    sys.stdout.write(data)
                else:
                    data = uart.recv(count=args.count, timeout=args.timeout)
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            elif args.cmd == "uart-monitor":
                try:
                    while True:
                        data = uart.recv(count=0, timeout=args.timeout)
                        if data:
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                except KeyboardInterrupt:
                    print("\nmonitor stopped")
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            if connected:
                try:
                    uart.close()
                except Exception:
                    pass

    # -- Analyzer commands -------------------------------------------------
    analyzer = Analyzer(transport)

    try:
        analyzer.connect()
        if args.cmd == "probe":
            print(json.dumps(analyzer.probe(), indent=2))
            return 0

        if args.cmd == "arm":
            analyzer.arm()
            print("armed")
            return 0

        if args.cmd in ("configure", "capture"):
            profile_name = getattr(args, "profile", None)
            if profile_name:
                from .gui.settings import (
                    apply_probe_profile,
                    default_gui_config_path,
                    load_gui_settings,
                )

                gpath = (
                    args.gui_config
                    if args.gui_config is not None
                    else default_gui_config_path()
                )
                err = apply_probe_profile(
                    args,
                    profile_name=profile_name,
                    settings=load_gui_settings(gpath),
                )
                if err:
                    print(f"error: {err}", file=sys.stderr)
                    return 2

        cfg = _build_config(args)
        analyzer.configure(cfg)

        if args.cmd == "configure":
            print("configured")
            return 0

        analyzer.arm()
        result = analyzer.capture(timeout=args.timeout)
        if args.format == "json":
            analyzer.write_json(result, args.out)
        elif args.format == "csv":
            analyzer.write_csv(result, args.out)
        else:
            analyzer.write_vcd(result, args.out)

        print(f"captured {len(result.samples)} samples from channel {cfg.channel} -> {args.out}")
        if result.overflow:
            print("warning: overflow flag set", file=sys.stderr)

        if getattr(args, "summarize", False):
            probe_defs = None
            if cfg.probes:
                probe_defs = [
                    ProbeDefinition(name=probe.name, width=probe.width, lsb=probe.lsb)
                    for probe in cfg.probes
                ]
            print(json.dumps(summarize(result, probe_defs), indent=2))

        open_in = getattr(args, "open_in", None)
        if open_in:
            if args.format != "vcd":
                print("error: --open-in requires --format vcd", file=sys.stderr)
                return 2
            from pathlib import Path as _Path

            from .gui.gtkw_writer import write_gtkw_for_capture
            from .gui.surfer_command_writer import write_surfer_command_file_for_capture
            from .gui.settings import (
                default_gui_config_path,
                load_gui_settings,
                viewer_executable_override,
            )
            from .gui.viewers import GtkWaveViewer, SurferViewer, viewer_by_name

            vcd = _Path(args.out)
            gpath = args.gui_config if args.gui_config is not None else default_gui_config_path()
            st_gui = load_gui_settings(gpath)
            custom_argv = None
            if open_in.strip().lower() in ("custom", "customcommand"):
                custom_argv = list(st_gui.viewers.custom_argv)
                if not custom_argv:
                    print(
                        "error: custom viewer requires viewers.custom_argv in gui.toml",
                        file=sys.stderr,
                    )
                    return 2
            try:
                viewer = viewer_by_name(open_in, custom_argv=custom_argv)
            except (KeyError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if isinstance(viewer, GtkWaveViewer):
                ovr = viewer_executable_override(st_gui, "gtkwave")
                if ovr is not None:
                    viewer = GtkWaveViewer(executable=ovr)
            if isinstance(viewer, GtkWaveViewer):
                gtkw = vcd.with_suffix(".gtkw")
                try:
                    write_gtkw_for_capture(result, vcd, gtkw)
                except OSError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1
                try:
                    viewer.open(vcd, save_file=gtkw)
                except (OSError, ValueError) as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1
            elif isinstance(viewer, SurferViewer):
                ovr = viewer_executable_override(st_gui, "surfer")
                if ovr is not None:
                    viewer = SurferViewer(executable=ovr)
                scmd = vcd.with_suffix(".surfer.txt")
                try:
                    write_surfer_command_file_for_capture(result, scmd)
                except OSError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1
                try:
                    viewer.open(vcd, save_file=scmd)
                except (OSError, ValueError) as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1
            else:
                try:
                    viewer.open(vcd)
                except (OSError, ValueError) as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1

        return 0

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        analyzer.close()


if __name__ == "__main__":
    raise SystemExit(main())
