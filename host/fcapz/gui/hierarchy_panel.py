# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtWidgets import QGroupBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..analyzer import CORE_MANAGER_CORE_ID, ELA_CORE_ID
from ..eio import EIO_CORE_ID


def _core_name(core_id: int) -> str:
    if core_id == CORE_MANAGER_CORE_ID:
        return "Core manager"
    if core_id == ELA_CORE_ID:
        return "ELA"
    if core_id == EIO_CORE_ID:
        return "EIO"
    if 0x2020 <= core_id <= 0x7E7E:
        hi = chr((core_id >> 8) & 0xFF)
        lo = chr(core_id & 0xFF)
        return f"0x{core_id:04X} ({hi}{lo})"
    return f"0x{core_id:04X}"


class HierarchyPanel(QGroupBox):
    """Read-only view of discovered JTAG USER chains and managed debug slots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("JTAG hierarchy", parent)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Node", "Details"])
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)

        lay = QVBoxLayout(self)
        lay.addWidget(self._tree)
        self.clear()

    def clear(self) -> None:
        self._tree.clear()
        item = QTreeWidgetItem(["Disconnected", ""])
        self._tree.addTopLevelItem(item)
        self._tree.expandAll()

    def set_topology(
        self,
        topology: Mapping[str, Any] | None,
        ela_info: Mapping[str, Any] | None,
    ) -> None:
        self._tree.clear()
        if topology and topology.get("manager"):
            manager = dict(topology.get("manager") or {})
            chain = int(topology.get("chain", 1))
            root = QTreeWidgetItem([f"USER{chain}", "BSCAN chain"])
            self._tree.addTopLevelItem(root)
            root.addChild(
                QTreeWidgetItem(
                    [
                        "Core manager",
                        (
                            f"v{int(manager.get('version_major', 0))}."
                            f"{int(manager.get('version_minor', 0))}, "
                            f"{int(manager.get('num_slots', 0))} slots, "
                            f"active {int(manager.get('active', 0))}"
                        ),
                    ],
                ),
            )
            for slot in topology.get("slots", []):
                if not isinstance(slot, Mapping):
                    continue
                idx = int(slot.get("instance", 0))
                core_id = int(slot.get("core_id", 0)) & 0xFFFF
                caps = int(slot.get("capabilities", 0))
                role = "Selectable ELA capture" if core_id == ELA_CORE_ID else ""
                if core_id == EIO_CORE_ID:
                    role = "Attach from EIO dock"
                detail = f"{_core_name(core_id)}, caps=0x{caps:X}"
                if role:
                    detail = f"{detail}, {role}"
                root.addChild(QTreeWidgetItem([f"slot {idx}", detail]))
        else:
            root = QTreeWidgetItem(["USER1", "BSCAN chain"])
            self._tree.addTopLevelItem(root)
            if ela_info is not None:
                root.addChild(QTreeWidgetItem(["ELA", "direct register map"]))
            else:
                root.addChild(QTreeWidgetItem(["No ELA detected", "USER1 probe failed"]))

        self._add_known_subsidiary_chains()
        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)

    def _add_known_subsidiary_chains(self) -> None:
        for chain, label in (
            (3, "Legacy/direct EIO candidates"),
            (4, "EJTAG-AXI / EJTAG-UART candidates"),
        ):
            self._tree.addTopLevelItem(QTreeWidgetItem([f"USER{chain}", label]))
