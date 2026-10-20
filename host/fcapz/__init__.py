# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from ._version import __version__, _version_tuple
from .analyzer import (
    Analyzer,
    CaptureConfig,
    CaptureResult,
    ProbeSpec,
    SequencerStage,
    TriggerConfig,
    entry_start_clocks,
    expand_run_lengths,
)
from .axi_decode import AxiTransaction, decode_axi, looks_like_axi
from .axi_monitor import AxiGeometry, AxiMonitor, AxiMonitorError
from .discovery import discover_cores
from .eio import EioController
from .ejtagaxi import AXIError, EjtagAxiController
from .ejtaguart import EjtagUartController
from .events import (
    ProbeDefinition,
    find_bursts,
    find_edges,
    find_falling_edges,
    find_rising_edges,
    frequency_estimate,
    summarize,
)
from .ftdi_transport import FtdiMpsseTransport
from .probes import (
    PROBE_FILE_FORMAT,
    ProbeFile,
    load_probe_file,
    probe_file_dict,
    probes_to_arg,
    write_probe_file,
)
from .transport import (
    OpenOcdTransport,
    Transport,
    VendorStubTransport,
    XilinxHwServerTransport,
    connect_timing_logs_enabled,
)

__all__ = [
    "__version__",
    "_version_tuple",
    "Analyzer",
    "CaptureConfig",
    "CaptureResult",
    "ProbeSpec",
    "SequencerStage",
    "TriggerConfig",
    "entry_start_clocks",
    "expand_run_lengths",
    "Transport",
    "OpenOcdTransport",
    "XilinxHwServerTransport",
    "VendorStubTransport",
    "FtdiMpsseTransport",
    "connect_timing_logs_enabled",
    "find_edges",
    "find_rising_edges",
    "find_falling_edges",
    "find_bursts",
    "frequency_estimate",
    "summarize",
    "AxiTransaction",
    "decode_axi",
    "looks_like_axi",
    "ProbeDefinition",
    "AxiMonitor",
    "AxiGeometry",
    "AxiMonitorError",
    "discover_cores",
    "EioController",
    "EjtagAxiController",
    "AXIError",
    "EjtagUartController",
    "PROBE_FILE_FORMAT",
    "ProbeFile",
    "load_probe_file",
    "probe_file_dict",
    "probes_to_arg",
    "write_probe_file",
]
