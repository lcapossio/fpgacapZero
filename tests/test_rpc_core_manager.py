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

    def __init__(self):
        self.active = 0
        self.slots = [self._ela(0x00), self._ela(0xA5), self._eio()]
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
    def _eio():
        return {0x0000: _VERSION | EIO_CORE_ID, 0x0004: 8, 0x0008: 8, 0x0010: 0x5A}


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
        if self.chain != 1:
            return {}  # nothing on the other chains
        if addr >= 0xF000:
            return self.board.manager
        return self.board.slots[self.board.active]

    def read_reg(self, addr: int) -> int:
        if self.chain == 1 and addr == _MGR_ACTIVE:
            return self.board.active
        if self.chain == 1 and addr == 0xF018:
            index = self.board.manager[0xF014]
            return self.board.slots[index][0x0000] & 0xFFFF
        return self._space(addr).get(addr, 0)

    def write_reg(self, addr: int, value: int) -> None:
        if self.chain == 1 and addr == _MGR_ACTIVE:
            self.board.active = int(value)
        else:
            self._space(addr)[addr] = value

    def read_block(self, addr: int, words: int):
        return [0] * words


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
        self.assertEqual(self.ela_tag(), 0x00)
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
        self.assertEqual(self.ela_tag(), 0x00)

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
            [("ela", 1, 0), ("ela", 1, 1), ("eio", 1, 2)],
        )
        self.assertEqual(cores[2]["info"], {"in_w": 8, "out_w": 8})
        self.assertEqual(self.ela_tag(), 0x00)


if __name__ == "__main__":
    unittest.main()
