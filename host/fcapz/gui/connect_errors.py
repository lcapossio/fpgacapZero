# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""User-facing messages for connection failures (GUI and tests)."""

from __future__ import annotations

import errno
import sys

from .settings import ConnectionSettings


def format_connect_error(exc: BaseException, conn: ConnectionSettings) -> str:
    """Map exceptions from transport/analyzer into short, actionable text."""
    endpoint = _endpoint_label(conn)
    if isinstance(exc, TimeoutError):
        return (
            f"Timed out reaching {endpoint} (TCP/socket). "
            "The server did not accept a connection in time (firewall, wrong host/port, "
            "or OpenOCD not listening). "
            f'Raise "Connect timeout" in the Connection panel if needed '
            f"(now {conn.connect_timeout_sec:g}s)."
        )
    if isinstance(exc, ConnectionRefusedError):
        return (
            f"Connection refused at {endpoint}. "
            "Nothing is listening on that port (start hw_server/OpenOCD or fix the port)."
        )
    if isinstance(exc, ConnectionError):
        msg = str(exc).strip()
        if "FPGA did not become ready" in msg or "program()" in msg:
            return (
                f"{msg}\n\n"
                "If you programmed a bitstream: check the .bit path, TAP/target name, "
                f'and try increasing "HW ready timeout" (now {conn.hw_ready_timeout_sec:g}s) '
                f'or "Post-program delay" (now {conn.hw_post_program_delay_ms} ms).'
            )
        if "xsdb process exited" in msg.lower():
            return (
                f"{msg}\n\n"
                "hw_server may have dropped the session, or xsdb failed to start. "
                "Confirm Vivado hw_server is running and the port matches."
            )
        return f"{msg}\n\n(Target: {endpoint}.)"
    if isinstance(exc, OSError) and not isinstance(exc, (TimeoutError, ConnectionRefusedError)):
        return _format_os_error(exc, endpoint)
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        if "xsdb not found" in msg.lower():
            return f"{msg}\n\nAdd the Vivado bin directory to PATH so `xsdb` is available."
        if "no bit string" in msg.lower() or "xsdb:" in msg.lower():
            return (
                f"{msg}\n\n"
                "The JTAG target may be wrong (TAP name / fpga_name), the cable may not "
                "see the device, or the bitstream may not match this design."
            )
        return msg
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}\n\n(Context: {endpoint}.)"


def _endpoint_label(conn: ConnectionSettings) -> str:
    if conn.backend == "openocd":
        return f"{conn.host}:{conn.port} (OpenOCD)"
    port = conn.port
    if port == 6666:
        port = 3121
    return f"{conn.host}:{port} (hw_server)"


def _format_os_error(exc: OSError, endpoint: str) -> str:
    winerr = getattr(exc, "winerror", None)
    if sys.platform == "win32" and winerr == 10061:
        return (
            f"Could not connect to {endpoint} (connection refused). "
            "Start the server or use Cancel if a previous connect hung."
        )
    if sys.platform == "win32" and winerr == 10060:
        return (
            f"Timed out connecting to {endpoint}. "
            "The host may be unreachable or the port blocked; try a longer connect timeout "
            "or Cancel if the stack is stuck."
        )
    err = getattr(exc, "errno", None)
    if err in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        return f"Host unreachable ({endpoint}): check the IP/hostname and network."
    if err == errno.ECONNREFUSED:
        return (
            f"Connection refused at {endpoint}. "
            "No listener on that port, or the service rejected the connection."
        )
    if err == errno.ETIMEDOUT:
        return f"Network timed out ({endpoint}). Check VPN, firewall, and server status."
    return f"{exc}\n\n(Target: {endpoint}.)"
