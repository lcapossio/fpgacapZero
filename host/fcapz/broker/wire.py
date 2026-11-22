# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""JSON codec between broker clients and the runtime.

Only plain JSON crosses the pipe (never pickle): capture configurations and
results go as dicts, and errors as ``{"type", "message"}`` mapped back to a
whitelist of exception classes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Any

from ..analyzer import (
    CaptureChangedError,
    CaptureConfig,
    CaptureNotReady,
    CaptureResult,
    CommandPendingError,
    ProbeSpec,
    SequencerStage,
    TriggerConfig,
)
from ..transport import ManagerResetError

PROTOCOL = 1


class BrokerError(RuntimeError):
    """Base class of the broker's own errors."""


class BrokerStartError(BrokerError):
    """The runtime could not be started or reached; nothing ran."""


class BrokerConnectionLost(BrokerError):
    """The runtime went away during a request: its job is lost, and nothing
    was re-armed or retried."""


class BrokerRemoteError(BrokerError):
    """An error raised in the runtime whose type has no local class."""


class CoreBusy(BrokerError):
    """The job did not reach the head of its core's queue before its queue
    deadline: another client's job still owns the core."""


class ImageChanged(BrokerError):
    """The target was reconnected (its image generation changed) since the
    caller looked at it: the core may hold another bitstream."""


class JobCancelled(BrokerError):
    """The job was cancelled before it finished."""


class TargetMismatch(BrokerError):
    """The runtime already holds this cable with other transport settings."""


# Exceptions a reply may carry, by name.  Anything else arrives as
# BrokerRemoteError with the original type name in its message.
_ERRORS: dict[str, type[BaseException]] = {
    cls.__name__: cls
    for cls in (
        BrokerError,
        BrokerStartError,
        BrokerConnectionLost,
        CoreBusy,
        ImageChanged,
        JobCancelled,
        TargetMismatch,
        CaptureNotReady,
        CaptureChangedError,
        CommandPendingError,
        ManagerResetError,
        TimeoutError,
        ValueError,
        KeyError,
        RuntimeError,
        OSError,
        ConnectionError,
        NotImplementedError,
    )
}


def encode(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode(raw: bytes) -> dict[str, Any]:
    msg = json.loads(raw.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ValueError("broker message is not a JSON object")
    return msg


def error_dict(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def error_from_dict(err: dict[str, Any]) -> BaseException:
    name = str(err.get("type", "BrokerRemoteError"))
    message = str(err.get("message", ""))
    cls = _ERRORS.get(name)
    if cls is None:
        return BrokerRemoteError(f"{name}: {message}")
    return cls(message)


def config_to_dict(cfg: CaptureConfig) -> dict[str, Any]:
    return asdict(cfg)


def config_from_dict(data: dict[str, Any]) -> CaptureConfig:
    known = {f.name for f in fields(CaptureConfig)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"capture config: unknown fields {sorted(unknown)}")
    kw = dict(data)
    kw["trigger"] = TriggerConfig(**kw["trigger"])
    kw["probes"] = [ProbeSpec(**p) for p in kw.get("probes") or []]
    seq = kw.get("sequence")
    kw["sequence"] = None if seq is None else [SequencerStage(**s) for s in seq]
    return CaptureConfig(**kw)


def result_to_dict(result: CaptureResult) -> dict[str, Any]:
    d = asdict(result)
    d["config"] = config_to_dict(result.config)
    return d


def result_from_dict(data: dict[str, Any]) -> CaptureResult:
    kw = dict(data)
    kw["config"] = config_from_dict(kw["config"])
    known = {f.name for f in fields(CaptureResult)}
    unknown = set(kw) - known
    if unknown:
        raise ValueError(f"capture result: unknown fields {sorted(unknown)}")
    return CaptureResult(**kw)
