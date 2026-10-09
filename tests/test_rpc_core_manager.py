# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""RPC sessions on a core-manager chain (BUG-218).

A core manager puts several cores behind one USER chain and its MGR_ACTIVE
register picks which one the chain reaches. The fake below routes every
register access by that register, as the hardware does, so a session that
lets another transport -- or no one -- move it reads the wrong core.
"""

from __future__ import annotations

import unittest

from fcapz.analyzer import ELA_CORE_ID, expected_ela_version_reg
from fcapz.eio import EIO_CORE_ID
from fcapz.rpc import RpcServer
from fcapz.transport import Transport

_MGR_ACTIVE = 0xF008
_VERSION = expected_ela_version_reg() & 0xFFFF0000


class FakeManagedBoard:
    """Hardware state shared by every transport opened on the board."""

    def __init__(self, manager_chain=1):
        self.manager_chain = manager_chain
        self.direct = {}  # chain -> registers of a core with no manager
        self.absent = set()  # chains whose scans fail (no such instance)
        self.active = 0
        self.slots = [self._ela(0x11), self._ela(0xA5), self._eio(), self._eio(0x3C)]
        self.manager = {
            0xF000: _VERSION | 0x434D,  # "CM"
            0xF004: len(self.slots),
            0xF00C: 0,  # stride
            0xF010: 0x3,  # active-slot select + descriptors
            0xF014: 0,  # descriptor index
        }

    @staticmethod
    def _ela(tag):
        return {0x0000: _VERSION | ELA_CORE_ID, 0x000C: 8, 0x0010: 1024,
                0x00A4: 1, 0x0008: 0x4, 0x0014: tag}

    @staticmethod
    def _eio(value=0x5A):
        return {0x0000: _VERSION | EIO_CORE_ID, 0x0004: 8, 0x0008: 8, 0x0010: value}


class FakeManagedTransport(Transport):
    def __init__(self, board: FakeManagedBoard):
        self.board = board
        self.chain = 1
        self.closes = 0

    def connect(self) -> None:
        pass

    def close(self) -> None:
        self.closes += 1

    def select_chain(self, chain: int) -> None:
        self.chain = int(chain)

    def _space(self, addr):
        if self.chain in self.board.absent:
            raise OSError(f"no chain {self.chain}")
        if self.chain != self.board.manager_chain:
            return self.board.direct.get(self.chain, {})
        if addr >= 0xF000:
            return self.board.manager
        return self.board.slots[self.board.active]

    def read_reg(self, addr: int) -> int:
        self._space(addr)  # an absent chain fails every access
        managed = self.chain == self.board.manager_chain
        if managed and addr == _MGR_ACTIVE:
            return self.board.active
        if managed and addr == 0xF018:
            index = self.board.manager[0xF014]
            return self.board.slots[index][0x0000] & 0xFFFF
        return self._space(addr).get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        if self.chain == self.board.manager_chain and addr == _MGR_ACTIVE:
            self.board.active = int(value)
        else:
            self._space(addr)[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


def _plain_ela(tag):
    return FakeManagedBoard._ela(tag)  # noqa: SLF001


class Harness(RpcServer):
    """Every `_build_transport` opens a fresh transport on the same board."""

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.transports: list[FakeManagedTransport] = []

    def _build_transport(self, req):
        transport = FakeManagedTransport(self.board)
        self.transports.append(transport)
        return transport


class CoreManagerSessionTests(unittest.TestCase):
    def setUp(self):
        self.board = FakeManagedBoard()
        self.srv = Harness(self.board)

    def connect(self, **kw):
        return self.srv.handle({"cmd": "connect", "backend": "hw_server", **kw})

    def ela_tag(self):
        """PRETRIG_LEN of the ELA the session reaches -- the fake's slot tag."""
        self.srv.handle({"cmd": "probe"})  # the session selects its slot
        return self.srv._analyzer.transport.read_reg(0x0014)  # noqa: SLF001

    def test_connect_binds_the_lowest_ela_slot_explicitly(self):
        self.board.active = 2  # a prior session left the manager on the EIO
        r = self.connect()
        self.assertEqual((r["chain"], r["instance"]), (1, 0))
        self.assertEqual(self.srv.handle({"cmd": "probe"})["probe"]["core_id"], ELA_CORE_ID)

    def test_an_eio_slot_does_not_hijack_the_ela(self):
        self.connect()
        r = self.srv.handle(
            {"cmd": "eio_connect", "backend": "hw_server", "chain": 1, "instance": 2}
        )
        self.assertEqual((r["chain"], r["instance"], r["in_w"]), (1, 2, 8))
        self.assertEqual(self.srv.handle({"cmd": "eio_read"})["value"], 0x5A)
        # The ELA re-selects its slot: it reads the ELA, not the EIO.
        self.assertEqual(self.srv.handle({"cmd": "probe"})["probe"]["core_id"], ELA_CORE_ID)
        self.assertEqual(self.ela_tag(), 0x11)
        self.assertEqual(self.srv.handle({"cmd": "eio_read"})["value"], 0x5A)
        # One transport for the board, not one per core.
        self.assertEqual(len(self.srv.transports), 1)

    def test_closing_a_shared_eio_leaves_the_session_open(self):
        self.connect()
        # chain defaults to 1 with an instance, as EioController's does.
        self.assertEqual(self.srv.handle({"cmd": "eio_connect", "instance": 2})["chain"], 1)
        self.srv.handle({"cmd": "eio_close"})
        transport = self.srv.transports[0]
        self.assertEqual(transport.closes, 0)
        self.assertEqual(self.srv.handle({"cmd": "probe"})["probe"]["core_id"], ELA_CORE_ID)
        self.srv.handle({"cmd": "eio_connect", "instance": 2})
        self.srv.handle({"cmd": "close"})
        self.assertEqual(transport.closes, 1)

    def test_an_eio_instance_on_another_board_is_refused(self):
        self.connect(tap="xc7a100t")
        with self.assertRaisesRegex(ValueError, "session's board"):
            self.srv.handle({"cmd": "eio_connect", "tap": "xc7a35t", "instance": 2})

    def test_usb_blaster_auto_tap_spellings_name_one_board(self):
        self.connect(backend="usb_blaster", hardware="cable", tap="xc7a100t.tap")
        for tap in ("auto", ""):
            with self.subTest(tap=tap):
                r = self.srv.handle({
                    "cmd": "eio_connect", "backend": "usb_blaster",
                    "hardware": "cable", "tap": tap, "instance": 2,
                })
                self.assertEqual(r["instance"], 2)
        with self.assertRaisesRegex(ValueError, "session's board"):
            self.srv.handle({"cmd": "eio_connect", "backend": "usb_blaster",
                             "hardware": "other cable", "instance": 2})

    def test_eio_discover_finds_the_slot_on_the_session_transport(self):
        self.connect()
        r = self.srv.handle({"cmd": "eio_discover", "backend": "hw_server"})
        self.assertEqual((r["chain"], r["instance"]), (1, 2))
        self.assertEqual(len(self.srv.transports), 1)
        self.assertEqual(self.ela_tag(), 0x11)

    def test_eio_discover_after_slot_use_reaches_the_slot_it_reports(self):
        self.connect()
        self.srv.handle({"cmd": "eio_connect", "instance": 3})
        self.assertEqual(self.srv.handle({"cmd": "eio_read"})["value"], 0x3C)
        r = self.srv.handle({"cmd": "eio_discover", "backend": "hw_server"})
        self.assertEqual(r["instance"], 2)
        self.assertEqual(self.srv.handle({"cmd": "eio_read"})["value"], 0x5A)
        self.assertEqual(self.srv.handle({"cmd": "probe"})["probe"]["core_id"], ELA_CORE_ID)
        self.assertEqual(self.ela_tag(), 0x11)

    def test_rebind_switches_ela_slots_without_reconnecting(self):
        self.connect()
        r = self.srv.handle({"cmd": "rebind", "instance": 1})
        self.assertEqual((r["chain"], r["instance"]), (1, 1))
        self.assertEqual(self.ela_tag(), 0xA5)
        with self.assertRaisesRegex(ValueError, "not an ELA"):
            self.srv.handle({"cmd": "rebind", "instance": 2})

    def test_connect_to_a_slot_and_refusals(self):
        self.assertEqual(self.connect(instance=1)["instance"], 1)
        self.assertEqual(self.ela_tag(), 0xA5)
        with self.assertRaisesRegex(ValueError, "not an ELA"):
            self.connect(instance=2)
        # The refused connect closed the transport it opened.
        self.assertEqual(self.srv.transports[-1].closes, 1)
        with self.assertRaisesRegex(ValueError, "no core manager"):
            self.connect(chain=2, instance=0)

    def test_list_cores_marks_instances_and_lists_slots_on_request(self):
        self.connect()
        plain = self.srv.handle({"cmd": "list_cores"})["cores"]
        self.assertEqual([(c["type"], c["instance"]) for c in plain], [("ela", 0)])

        cores = self.srv.handle({"cmd": "list_cores", "slots": True})["cores"]
        self.assertEqual(
            [(c["type"], c["chain"], c["instance"]) for c in cores],
            [("ela", 1, 0), ("ela", 1, 1), ("eio", 1, 2), ("eio", 1, 3)],
        )
        self.assertEqual(cores[2]["info"], {"in_w": 8, "out_w": 8})
        self.assertEqual(self.ela_tag(), 0x11)

    def test_plain_list_cores_keeps_the_manager_ela_after_a_hop(self):
        self.board.direct[2] = _plain_ela(0x77)
        self.connect()
        self.srv.handle({"cmd": "eio_discover", "backend": "hw_server"})  # slot 2
        self.assertEqual(self.srv.handle({"cmd": "rebind", "chain": 2})["instance"], None)
        # The manager still points at the EIO: chain 1 is listed by its ELA.
        plain = self.srv.handle({"cmd": "list_cores"})["cores"]
        self.assertIn(("ela", 1, 0), [(c["type"], c["chain"], c["instance"]) for c in plain])
        self.assertEqual(self.ela_tag(), 0x77)

    def test_plain_list_cores_reports_no_unbound_eio_on_a_manager_chain(self):
        self.board.direct[2] = _plain_ela(0x77)
        self.connect()
        self.srv.handle({"cmd": "eio_discover", "backend": "hw_server"})  # slot 2
        self.srv.handle({"cmd": "eio_close"})
        self.srv.handle({"cmd": "rebind", "chain": 2})
        # The manager still points at the EIO; an unbound probe would list it
        # as a direct EIO with no instance.
        plain = self.srv.handle({"cmd": "list_cores"})["cores"]
        self.assertEqual(
            [(c["type"], c["chain"], c["instance"]) for c in plain],
            [("ela", 2, None), ("ela", 1, 0)],
        )

    def test_an_instance_less_eio_on_a_manager_chain_is_refused(self):
        self.connect()
        with self.assertRaisesRegex(ValueError, r"pass instance \(EIO slots: \[2, 3\]\)"):
            self.srv.handle({"cmd": "eio_connect", "chain": 1})
        self.assertEqual(len(self.srv.transports), 1)

    def test_eio_discover_finds_a_manager_on_another_chain(self):
        self.board.manager_chain = 2
        self.connect(chain=2)
        r = self.srv.handle({"cmd": "eio_discover", "backend": "hw_server"})
        self.assertEqual((r["chain"], r["instance"]), (2, 2))
        self.assertEqual(self.srv.handle({"cmd": "eio_read"})["value"], 0x5A)
        self.assertEqual(self.srv.handle({"cmd": "probe"})["probe"]["core_id"], ELA_CORE_ID)
        self.assertEqual(len(self.srv.transports), 1)

    def test_eio_discover_skips_chains_the_backend_cannot_reach(self):
        # No manager anywhere, and chain 1 cannot be selected (a usb_blaster
        # design without virtual-JTAG instance 1): the scan falls back to the
        # direct probe instead of failing.
        self.board.manager_chain = None
        self.board.direct[2] = _plain_ela(0x77)
        self.board.direct[3] = self.board._eio()  # noqa: SLF001
        self.board.absent.add(1)
        self.connect(chain=2)
        r = self.srv.handle({"cmd": "eio_discover", "backend": "hw_server", "chains": [3]})
        self.assertEqual((r["chain"], r["instance"]), (3, None))

    def test_rebind_to_the_current_chain_keeps_the_slot(self):
        self.connect(instance=1)
        r = self.srv.handle({"cmd": "rebind", "chain": 1})
        self.assertEqual((r["chain"], r["instance"]), (1, 1))
        self.assertEqual(self.ela_tag(), 0xA5)


if __name__ == "__main__":
    unittest.main()
