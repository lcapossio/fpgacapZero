# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Build a :class:`~fcapz.transport.Transport` from :class:`ConnectionSettings`."""

from __future__ import annotations

from ..transport import OpenOcdTransport, Transport, XilinxHwServerTransport
from .settings import ConnectionSettings, ir_table_preset


def transport_from_connection(conn: ConnectionSettings) -> Transport:
    """Mirror CLI transport selection, including hw_server default port remap."""
    ir = ir_table_preset(conn.ir_table)
    if conn.backend == "openocd":
        return OpenOcdTransport(
            host=conn.host,
            port=conn.port,
            tap=conn.tap,
            ir_table=ir,
            connect_timeout_sec=conn.connect_timeout_sec,
        )
    if conn.backend == "hw_server":
        fpga = conn.tap
        if fpga.endswith(".tap"):
            fpga = fpga.removesuffix(".tap")
        port = conn.port
        if port == 6666:
            port = 3121
        ready_to = conn.hw_ready_timeout_sec if conn.program else 2.0
        return XilinxHwServerTransport(
            host=conn.host,
            port=port,
            fpga_name=fpga,
            bitfile=conn.program,
            ir_table=ir,
            ready_probe_timeout=ready_to,
        )
    raise ValueError(f"unknown backend {conn.backend!r}")
