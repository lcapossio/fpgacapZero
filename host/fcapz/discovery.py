# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Find the fcapz cores on a JTAG session without knowing their chains.

Every chain is first asked for VERSION at ``0x0000`` and nothing else (see
:func:`~fcapz.transport.register_pipe_identity`): that read is a NOP on the
EJTAG-AXI and EJTAG-UART bridges, whose command field it lands in.  Only a
chain that answers ``"LA"`` or ``"IO"`` is then read further, for a core
manager at ``0xF000`` or an EIO behind the register mux at ``0x8000``.  A chain
that answers neither is offered the bridges' own identity reads, the UART's
first: a UART frame is 32 bits, shorter than any register command, and a
register core has already answered by then.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, List, Optional

from .analyzer import CORE_MANAGER_CORE_ID, ELA_CORE_ID, Analyzer, CoreManager
from .axi_monitor import AXI_MON_MAGIC, AxiMonitor
from .ejtagaxi import EjtagAxiController
from .ejtaguart import EjtagUartController
from .eio import EIO_CORE_ID, EioController
from .registers import ADDR_MGR_ACTIVE
from .transport import Transport, register_pipe_identity

#: Friendly name per VERSION[15:0] core ID.
CORE_NAMES = {
    ELA_CORE_ID: "Embedded Logic Analyzer",
    EIO_CORE_ID: "Embedded I/O",
    CORE_MANAGER_CORE_ID: "Core Manager",
    0x4A58: "EJTAG-AXI bridge",
    0x4A55: "EJTAG-UART",
    AXI_MON_MAGIC: "AXI Monitor",
}

# A regbus mux puts an EIO at this offset next to an ELA at 0x0000.
_EIO_MUX_BASE = 0x8000

# Errors that mean "nothing usable here" for one chain or one core; anything
# else (a lost connection, a timeout) propagates.
_SKIP = (RuntimeError, ValueError, NotImplementedError)


def _entry(kind: str, core_id: int, chain: int, *, major: int = 0,
           minor: int = 0, base_addr: int = 0, instance: Optional[int] = None,
           info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "type": kind,
        "name": CORE_NAMES.get(core_id, kind),
        "core_id": core_id,
        "chain": chain,
        "base_addr": base_addr,
        "instance": instance,
        "version_major": int(major),
        "version_minor": int(minor),
        "info": info or {},
    }


def _ela_entry(analyzer: Analyzer, ident: Dict[str, Any], chain: int,
               instance: Optional[int]) -> Dict[str, Any]:
    version = {"major": ident["version_major"], "minor": ident["version_minor"]}
    try:
        mon = AxiMonitor(analyzer)
        geo = mon.geometry() if mon.present else None
    except _SKIP:
        geo = None
    if geo is not None:
        return _entry("axi_mon", AXI_MON_MAGIC, chain, **version,
                      instance=instance, info={
                          "proto": geo.proto,
                          "addr_w": geo.addr_w,
                          "data_w": geo.data_w,
                          "decode": geo.decode,
                          "sample_width": geo.sample_width,
                      })
    return _entry("ela", ELA_CORE_ID, chain, **version,
                  instance=instance, info=ident)


def _eio_entry(eio: EioController, chain: int, base_addr: int,
               instance: Optional[int]) -> Dict[str, Any]:
    return _entry("eio", EIO_CORE_ID, chain, major=eio.version_major,
                  minor=eio.version_minor,
                  base_addr=base_addr, instance=instance,
                  info={"in_w": eio.in_w, "out_w": eio.out_w})


def _manager_entries(transport: Transport, chain: int) -> List[Dict[str, Any]]:
    """The manager and each of its slots; the active slot is put back."""
    manager = CoreManager(transport, chain=chain)
    info = manager.probe()
    entries = [_entry("manager", CORE_MANAGER_CORE_ID, chain,
                      major=info["version_major"], minor=info["version_minor"],
                      info=info)]
    core_ids = manager.slot_core_ids()
    try:
        for idx, core_id in enumerate(core_ids):
            if core_id == ELA_CORE_ID:
                analyzer = Analyzer(transport, chain=chain, instance=idx)
                try:
                    ident = analyzer.probe()
                except _SKIP:
                    continue
                entries.append(_ela_entry(analyzer, ident, chain, idx))
            elif core_id == EIO_CORE_ID:
                eio = EioController(transport, chain=chain, instance=idx)
                try:
                    eio.attach()
                except _SKIP:
                    continue
                entries.append(_eio_entry(eio, chain, 0, idx))
            else:
                entries.append(_entry("unknown", core_id, chain, instance=idx))
    finally:
        transport.select_chain(chain)
        transport.select_manager_instance_cached(
            chain, ADDR_MGR_ACTIVE, int(info["active"])
        )
    return entries


def _register_core_entries(transport: Transport, chain: int,
                           version: int) -> List[Dict[str, Any]]:
    """Cores on a chain whose ``0x0000`` answered ``"LA"`` or ``"IO"``."""
    # A deep standalone ELA can return sample data at 0xF000, so the manager
    # ID alone is not enough; the analyzer's check confirms the block.
    if Analyzer(transport, chain=chain)._behind_manager():  # noqa: SLF001
        return _manager_entries(transport, chain)
    if (version & 0xFFFF) == EIO_CORE_ID:
        eio = EioController(transport, chain=chain)
        eio.attach()
        return [_eio_entry(eio, chain, 0, None)]
    analyzer = Analyzer(transport, chain=chain)
    entries = [_ela_entry(analyzer, analyzer.probe(), chain, None)]
    eio = EioController(transport, chain=chain, base_addr=_EIO_MUX_BASE)
    try:
        eio.attach()
    except _SKIP:
        pass
    else:
        entries.append(_eio_entry(eio, chain, _EIO_MUX_BASE, None))
    return entries


def _bridge_entry(transport: Transport, chain: int) -> Optional[Dict[str, Any]]:
    """The EJTAG-UART or EJTAG-AXI bridge on *chain*, or ``None``."""
    try:
        info = EjtagUartController(transport, chain=chain).attach()
    except _SKIP:
        pass
    else:
        return _entry("ejtag_uart", 0x4A55, chain,
                      major=info.get("version_major", 0),
                      minor=info.get("version_minor", 0), info=info)
    try:
        info = EjtagAxiController(transport, chain=chain).attach()
    except _SKIP:
        return None
    return _entry("ejtag_axi", 0x4A58, chain,
                  major=info.get("version_major", 0),
                  minor=info.get("version_minor", 0), info=info)


def discover_cores(
    transport: Transport,
    *,
    chains: Optional[Iterable[int]] = None,
    bridges: bool = True,
) -> List[Dict[str, Any]]:
    """List every fcapz core reachable on an open *transport*.

    *chains* defaults to :meth:`~fcapz.transport.Transport.discovery_chains`.
    Each entry is ``{type, name, core_id, chain, base_addr, instance,
    version_major, version_minor, info}``, where ``type`` is ``"ela"``,
    ``"axi_mon"``, ``"eio"``, ``"manager"``, ``"ejtag_uart"``,
    ``"ejtag_axi"`` or ``"unknown"`` (a manager slot of another core type),
    and ``instance`` is the manager slot or ``None``.  A manager's active slot
    is left as it was found.  Set *bridges* to ``False`` to skip the bridge
    identity reads on chains no register core answered.  Chains the transport
    cannot select, such as a missing ``sld_virtual_jtag`` instance, are
    skipped, and so are its ``unprobeable_chains`` (a TAP bridge's burst
    data chain), even when named in *chains*; connection errors propagate.
    Chain 1 is selected on return.
    """
    if chains is None:
        chains = transport.discovery_chains()
    blocked = getattr(transport, "unprobeable_chains", ())
    chains = [c for c in chains if int(c) not in blocked]
    found: List[Dict[str, Any]] = []
    unanswered: List[int] = []
    # Unselected: a caller's slot must not prefix the probes of other chains'
    # cores, and a fallback backend gets the caller's slot back after.
    with transport.slot_scope(None):
        try:
            for chain in dict.fromkeys(int(c) for c in chains):
                try:
                    version = register_pipe_identity(transport, chain)
                except _SKIP:
                    continue
                if version is None:
                    unanswered.append(chain)
                    continue
                try:
                    found.extend(_register_core_entries(transport, chain, version))
                except _SKIP:
                    continue
            if bridges:
                for chain in unanswered:
                    entry = _bridge_entry(transport, chain)
                    if entry is not None:
                        found.append(entry)
        finally:
            try:
                transport.select_chain(1)
            except (NotImplementedError, ValueError):
                pass
    return found
