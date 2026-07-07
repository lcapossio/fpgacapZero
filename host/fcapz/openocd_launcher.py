# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Server-side OpenOCD process manager for the web gateway.

Lets the web UI (re)start OpenOCD running next to the board, so a user does
not have to drop to a shell.  Security model:

* Only an **allow-listed** set of configs (name -> path, fixed at server
  launch) may be started, with a **preconfigured** ``openocd`` binary — never a
  path taken from a web request.
* It only ever stops processes **it started itself**; a foreign OpenOCD (one a
  user launched by hand) is never touched.
* The web layer additionally restricts these commands to loopback clients.

The child's output goes to a temp logfile (not a PIPE) so a long-running
OpenOCD can never deadlock on a full stdout buffer; the log tail is surfaced
only when a start fails.
"""

from __future__ import annotations

import atexit
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class _Managed:
    proc: subprocess.Popen
    log_path: str
    config: str


class OpenOcdLauncher:
    """Starts/stops allow-listed OpenOCD instances on behalf of the web UI."""

    def __init__(
        self,
        *,
        openocd: str,
        configs: Dict[str, str],
        host: str = "127.0.0.1",
    ) -> None:
        # ``configs`` maps a short name (the UI picks by name) to an absolute
        # config path.  Resolved once here so later starts can't be redirected.
        self._openocd = openocd
        self._configs: Dict[str, str] = {
            name: str(Path(path).expanduser().resolve())
            for name, path in configs.items()
        }
        self._host = host
        self._managed: Dict[int, _Managed] = {}  # tcl port -> what we started
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    @property
    def config_names(self) -> List[str]:
        return sorted(self._configs)

    # -- helpers ---------------------------------------------------------

    def _port_open(self, port: int, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection((self._host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _resolve_config(self, name: Optional[str]) -> tuple[str, str]:
        if not self._configs:
            raise ValueError("no OpenOCD configs are configured on this server")
        if name is None:
            if len(self._configs) == 1:
                only = next(iter(self._configs))
                return only, self._configs[only]
            raise ValueError(
                f"multiple OpenOCD configs available {self.config_names}; specify 'name'"
            )
        if name not in self._configs:
            raise ValueError(
                f"unknown OpenOCD config {name!r}; available: {self.config_names}"
            )
        return name, self._configs[name]

    def _reap_dead(self) -> None:
        for port in [p for p, m in self._managed.items() if m.proc.poll() is not None]:
            self._managed.pop(port, None)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _log_tail(path: str, limit: int = 1500) -> str:
        try:
            return Path(path).read_text(errors="replace").strip()[-limit:]
        except OSError:
            return ""

    # -- API -------------------------------------------------------------

    def start(
        self, *, name: Optional[str] = None, port: int = 6666, wait_sec: float = 10.0
    ) -> Dict:
        """Start OpenOCD on ``port`` from the named config; wait for the TCL port.

        Idempotent: if the port already accepts connections nothing is spawned.
        Raises ``RuntimeError`` if OpenOCD exits early or never opens the port
        (with the OpenOCD log tail), and ``ValueError`` for an unknown config.
        """
        cfg_name, cfg_path = self._resolve_config(name)
        with self._lock:
            self._reap_dead()
            if self._port_open(port):
                # Something already serves this TCL port — discovery/connect can
                # proceed as-is. Report whether it was one of ours.
                return {
                    "started": False,
                    "already_running": True,
                    "mine": port in self._managed,
                    "port": port,
                }
            log = tempfile.NamedTemporaryFile(
                prefix=f"fcapz-openocd-{port}-", suffix=".log", delete=False
            )
            log_path = log.name
            proc = subprocess.Popen(
                [
                    self._openocd,
                    "-c", f"tcl_port {port}",
                    "-c", "gdb_port disabled",
                    "-c", "telnet_port disabled",
                    "-f", cfg_path,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            log.close()  # the child holds its own handle; we read the file by path
            self._managed[port] = _Managed(proc=proc, log_path=log_path, config=cfg_name)

        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                with self._lock:
                    self._managed.pop(port, None)
                raise RuntimeError(
                    f"openocd exited early (code {proc.returncode}). "
                    f"Output:\n{self._log_tail(log_path)}"
                )
            if self._port_open(port):
                return {
                    "started": True,
                    "already_running": False,
                    "port": port,
                    "pid": proc.pid,
                    "config": cfg_name,
                }
            time.sleep(0.15)

        self._terminate(proc)
        with self._lock:
            self._managed.pop(port, None)
        raise RuntimeError(
            f"openocd did not open TCL port {port} within {wait_sec:.0f}s. "
            f"Output:\n{self._log_tail(log_path)}"
        )

    def stop(self, *, port: int = 6666) -> Dict:
        """Terminate the OpenOCD *we* started on ``port``; never touch a foreign one."""
        with self._lock:
            managed = self._managed.pop(port, None)
        if managed is None:
            return {
                "stopped": False,
                "note": "no OpenOCD started by this server on that port",
                "port": port,
            }
        self._terminate(managed.proc)
        return {"stopped": True, "port": port}

    def status(self) -> Dict:
        with self._lock:
            self._reap_dead()
            running = [
                {"port": port, "pid": m.proc.pid, "config": m.config,
                 "listening": self._port_open(port)}
                for port, m in self._managed.items()
            ]
        return {"enabled": True, "configs": self.config_names, "running": running}

    def shutdown(self) -> None:
        """Terminate every OpenOCD we started (registered with ``atexit``)."""
        with self._lock:
            procs = [m.proc for m in self._managed.values()]
            self._managed.clear()
        for proc in procs:
            self._terminate(proc)
