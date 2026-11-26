# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""read_gowin_fs() on small synthetic .fs files.  No hardware."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fcapz import gowin_fs
from fcapz.gowin_fs import GowinFsError, frame_checksum, read_gowin_fs

GW1NR9_IDCODE = 0x1100481B
#: A frame layout small enough to simulate bit by bit: 4 lead pad bits,
#: 36 payload bits (not whole bytes), 16 CRC bits, 8 tail pad bits.
SMALL_LAYOUT = (64, 4, 16, 8)


def _bits(value: int, width: int) -> str:
    return format(value, f"0{width}b")


def random_payloads(count: int, width: int, seed: int = 1) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice("01") for _ in range(width)) for _ in range(count)]


def gowin_fs_text(
    payloads: list[str],
    idcode: int = GW1NR9_IDCODE,
    layout: tuple[int, int, int, int] = SMALL_LAYOUT,
    checksum: int | None = None,
    frames: int | None = None,
    options: dict[str, str] | None = None,
    sync: str = "1010010111000011",
) -> str:
    """A .fs file shaped like Gowin's: comments, preamble, sync, header
    records, one line per frame, then the checksum trailer."""
    _width, lead, crc, tail = layout
    lines = [
        "1" * lead + p + _bits((0x5A5A * (i + 1)) & ((1 << crc) - 1), crc) + "1" * tail
        for i, p in enumerate(payloads)
    ]
    if checksum is None:
        checksum = frame_checksum(lines, layout)
    comments = {"Device": "GW1NR-9C", "CheckSum": f"0x{checksum:04X}",
                "UserCode": f"0x{checksum:08X}", "Compress": "OFF", "Encryption": "OFF"}
    comments.update(options or {})
    count = len(payloads) if frames is None else frames
    out = ["//Gowin FPGA bitstream (synthetic)"]
    out += [f"//{k}: {v}" for k, v in comments.items()]
    out += ["1" * 16, "1" * 16, sync]
    out.append("00010000" + "0" * 24)  # an option record
    out.append("00000110" + "0" * 24 + _bits(idcode, 32))
    out.append("00111011" + "10000000" + _bits(count, 16))
    out += lines
    out.append("00001010" + "0" * 8 + _bits(checksum, 16))
    out.append("00001000" + "0" * 24)
    out.append("1" * 16)
    return "\n".join(out) + "\n"


class ReadGowinFsTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(gowin_fs.FRAME_LAYOUTS, {GW1NR9_IDCODE: SMALL_LAYOUT})
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.payloads = random_payloads(3, 36)

    def _file(self, text: str, name: str = "design.fs") -> str:
        path = self.dir / name
        path.write_text(text, encoding="ascii")
        return str(path)

    def _refused(self, text: str, pattern: str) -> None:
        with self.assertRaisesRegex(GowinFsError, pattern):
            read_gowin_fs(self._file(text))

    def test_reads_a_good_file(self):
        image = read_gowin_fs(self._file(gowin_fs_text(self.payloads)))
        self.assertEqual(image.idcode, GW1NR9_IDCODE)
        self.assertEqual((image.frames, image.frame_bits), (3, 64))
        self.assertEqual(image.frame_payloads, tuple(self.payloads))
        self.assertEqual(image.usercode, image.checksum)
        self.assertEqual(image.device, "GW1NR-9C")
        self.assertEqual(image.options["Compress"], "OFF")

    def test_checksum_sums_big_endian_words_padding_the_last(self):
        lines = ["1111" + "0" * 15 + "1" + "0" * 16 + "1" * 4 + "0" * 16 + "1" * 8]
        # payload = 0x0001, then 16 zeros, then 0b1111 padded to 0xF000
        self.assertEqual(frame_checksum(lines, SMALL_LAYOUT), 0xF001)

    def test_corrupt_frame_is_refused(self):
        good = gowin_fs_text(self.payloads)
        checksum = read_gowin_fs(self._file(good)).checksum
        flipped = ["1" + p[1:] if p[0] == "0" else "0" + p[1:] for p in self.payloads[:1]]
        self._refused(
            gowin_fs_text(flipped + self.payloads[1:], checksum=checksum),
            r"frame checksum 0x[0-9a-f]{4} does not match.*corrupt",
        )

    def test_compressed_and_encrypted_files_are_refused(self):
        self._refused(gowin_fs_text(self.payloads, options={"Compress": "ON"}),
                      "Compress: ON; only uncompressed")
        self._refused(gowin_fs_text(self.payloads, options={"Encryption": "AES"}),
                      "Encryption: AES")

    def test_malformed_lines_are_refused(self):
        text = gowin_fs_text(self.payloads)
        self._refused(text.replace("1" * 16, "1" * 15 + "x", 1), r":\d+: not a line of 0s and 1s")
        self._refused(text.replace("1" * 16, "1" * 12, 1), r"12 bits, not whole bytes")
        self._refused("//Device: GW1NR-9C\n", "no bitstream data")

    def test_missing_sync_is_refused(self):
        self._refused(gowin_fs_text(self.payloads, sync="1010010111000010"),
                      "no all-ones preamble and 0xA5C3 sync word")

    def test_missing_records_are_refused(self):
        text = gowin_fs_text(self.payloads)
        idcode_line = "00000110" + "0" * 24 + _bits(GW1NR9_IDCODE, 32)
        self._refused(text.replace(idcode_line + "\n", ""), r"no IDCODE record \(0x06\)")
        self._refused(text.replace(idcode_line, idcode_line + "\n" + idcode_line),
                      "a second IDCODE record")
        self._refused(text.replace(idcode_line, idcode_line[:56]), "IDCODE record is 56 bits")
        frames_line = "00111011" + "10000000" + _bits(3, 16)
        self._refused(text.replace(frames_line + "\n", ""), r"no frame count record \(0x3B\)")
        trailer = "00001010" + "0" * 8
        self._refused("\n".join(ln for ln in text.splitlines() if not ln.startswith(trailer)),
                      r"no checksum record \(0x0A\)")

    def test_frame_count_must_match(self):
        self._refused(gowin_fs_text(self.payloads, frames=100), "frame lines, the header says 100")

    def test_frames_must_be_one_length(self):
        text = gowin_fs_text(self.payloads)
        lines = text.splitlines()
        second = lines[lines.index("00111011" + "10000000" + _bits(3, 16)) + 2]
        self._refused(text.replace(second, second + "1" * 8), "frame of 72 bits, the first is 64")

    def test_frame_size_must_match_a_known_part(self):
        layout = (72, 4, 16, 8)
        self._refused(gowin_fs_text(random_payloads(2, 44), layout=layout),
                      "frames of 72 bits; IDCODE 0x1100481b has 64")

    def test_unknown_part_parses_without_payloads(self):
        image = read_gowin_fs(self._file(gowin_fs_text(self.payloads, idcode=0x0000081B)))
        self.assertEqual(image.idcode, 0x0000081B)
        self.assertEqual(image.frame_payloads, ())

    def test_binary_file_is_refused(self):
        path = self.dir / "design.bit"
        path.write_bytes(b"\x00\x09\x0f\xf0\xff\xfe")
        with self.assertRaisesRegex(GowinFsError, "binary content"):
            read_gowin_fs(str(path))


if __name__ == "__main__":
    unittest.main()
