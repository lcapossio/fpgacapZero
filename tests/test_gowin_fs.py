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
from fcapz.gowin_fs import GowinFsError, crc16_arc, frame_checksum, read_gowin_fs

GW1NR9_IDCODE = 0x1100481B
#: A frame layout small enough to simulate bit by bit: 3 frames of 4 lead
#: pad bits, 36 payload bits (not whole bytes) and 8 tail pad bits, plus a
#: 16-bit CRC when CRC is on; a 64-bit padding line after them.
SMALL_LAYOUT = (3, 4, 36, 8, 64)


def _bits(value: int, width: int) -> str:
    return format(value, f"0{width}b")


def _bytes(bits: str) -> bytes:
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def _crc_bits(data: bytes) -> str:
    crc = crc16_arc(data)
    return _bits(((crc & 0xFF) << 8) | (crc >> 8), 16)  # low byte first


def random_payloads(count: int, width: int, seed: int = 1) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice("01") for _ in range(width)) for _ in range(count)]


def gowin_fs_text(
    payloads: list[str],
    idcode: int = GW1NR9_IDCODE,
    layout: tuple[int, int, int, int, int] = SMALL_LAYOUT,
    crc: bool = True,
    checksum: int | None = None,
    usercode: int | None = None,
    frames: int | None = None,
    options: dict[str, str] | None = None,
    sync: str = "1010010111000011",
) -> str:
    """A .fs file shaped like Gowin's: comments, preamble, sync, header
    records, one line per frame (CRC'd as Gowin's are when *crc*), the
    padding line, then the USERCODE and end records."""
    _rows, lead, _payload, tail, closing_bits = layout
    flag = "0" if crc else "1"  # key bit 7: not covered by the CRC

    def record(key: int, rest: str) -> str:
        return flag + _bits(key, 7) + rest

    header = [
        record(0x10, "0" * 56),  # an option record
        record(0x06, "0" * 24 + _bits(idcode, 32)),
        "11010010" + "0" * 8 + "1" * 16 + "0" * 32,  # 0xD2: never CRC'd
        record(0x3B, ("10000000" if crc else "0" * 8)
               + _bits(len(payloads) if frames is None else frames, 16)),
    ]
    previous = b"".join(_bytes(h) for h in header if h[0] == "0")
    lines = []
    for p in payloads:
        body = "1" * lead + p
        crc_field = _crc_bits(previous + _bytes(body)) if crc else ""
        lines.append(body + crc_field + "1" * tail)
        previous = _bytes("1" * tail)
    ones = "1" * (closing_bits - 16)
    closing = ones + (_crc_bits(previous + _bytes(ones)) if crc else "1" * 16)
    if checksum is None:
        checksum = frame_checksum(payloads)
    if usercode is None:
        usercode = checksum
    comments = {"Device": "GW1NR-9C", "CheckSum": f"0x{checksum:04X}",
                "UserCode": f"0x{usercode:08X}", "Compress": "OFF", "Encryption": "OFF"}
    comments.update(options or {})
    out = ["//Gowin FPGA bitstream (synthetic)"]
    out += [f"//{k}: {v}" for k, v in comments.items() if v is not None]
    out += ["1" * 16, "1" * 16, sync] + header + lines + [closing]
    out.append(record(0x0A, "0" * 24 + _bits(usercode, 32)))
    out.append("1" * 64)
    out.append(record(0x08, "0" * 24))
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

    def _frame_index(self, text: str) -> int:
        lines = text.splitlines()
        return next(k for k, ln in enumerate(lines) if ln[1:8] == _bits(0x3B, 7)) + 1

    def test_reads_a_good_file(self):
        image = read_gowin_fs(self._file(gowin_fs_text(self.payloads)))
        self.assertEqual(image.idcode, GW1NR9_IDCODE)
        self.assertEqual((image.frames, image.frame_bits, image.crc), (3, 64, True))
        self.assertEqual(image.frame_payloads, tuple(self.payloads))
        self.assertEqual(image.checksum, frame_checksum(self.payloads))
        self.assertEqual(image.usercode, image.checksum)
        self.assertEqual(image.device, "GW1NR-9C")
        self.assertEqual(image.options["Compress"], "OFF")

    def test_reads_a_file_built_with_crc_off(self):
        # Gowin marks every record with key bit 7 then (0x86, 0xBB, 0x8A...).
        image = read_gowin_fs(self._file(gowin_fs_text(self.payloads, crc=False)))
        self.assertEqual((image.frame_bits, image.crc), (48, False))
        self.assertEqual(image.frame_payloads, tuple(self.payloads))

    def test_custom_usercode_is_kept_whole(self):
        image = read_gowin_fs(self._file(gowin_fs_text(self.payloads, usercode=0x1234ABCD)))
        self.assertEqual(image.usercode, 0x1234ABCD)
        self.assertEqual(image.checksum, frame_checksum(self.payloads))

    def test_checksum_sums_big_endian_words_padding_the_last(self):
        # 0x0001, then 0x0000, then 0b1111 padded to 0xF000
        self.assertEqual(frame_checksum(["0" * 15 + "1" + "0" * 16 + "1111"]), 0xF001)

    def test_crc_catches_what_the_checksum_misses(self):
        text = gowin_fs_text(self.payloads)
        lines = text.splitlines()
        k = self._frame_index(text) + 1  # the second frame
        frame = list(lines[k])
        # Swap a bit with its twin one 16-bit word on: the sum is unchanged.
        p = next(p for p in range(4, 20) if frame[p] != frame[p + 16])
        frame[p], frame[p + 16] = frame[p + 16], frame[p]
        lines[k] = "".join(frame)
        self._refused("\n".join(lines), r":\d+: frame CRC mismatch; the file is corrupt")

    def test_corrupt_header_fails_the_first_frame_crc(self):
        text = gowin_fs_text(self.payloads)
        option = "0" + _bits(0x10, 7) + "0" * 56
        self._refused(text.replace(option, option[:-1] + "1"), "frame CRC mismatch")

    def test_checksum_catches_a_corrupt_file_without_crc(self):
        text = gowin_fs_text(self.payloads, crc=False)
        lines = text.splitlines()
        k = self._frame_index(text)
        lines[k] = lines[k][:4] + ("1" if lines[k][4] == "0" else "0") + lines[k][5:]
        self._refused("\n".join(lines), r"frame checksum 0x[0-9a-f]{4} does not match.*corrupt")

    def test_declared_checksum_falls_back_to_the_usercode(self):
        text = gowin_fs_text(self.payloads, options={"CheckSum": None})
        self.assertEqual(read_gowin_fs(self._file(text)).checksum, frame_checksum(self.payloads))

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

    def test_missing_header_records_are_refused(self):
        text = gowin_fs_text(self.payloads)
        idcode_line = "00000110" + "0" * 24 + _bits(GW1NR9_IDCODE, 32)
        self._refused(text.replace(idcode_line + "\n", ""), r"no IDCODE record \(0x06\)")
        self._refused(text.replace(idcode_line, idcode_line + "\n" + idcode_line),
                      "a second IDCODE record")
        self._refused(text.replace(idcode_line, idcode_line[:56]), "IDCODE record is 56 bits")
        frames_line = "00111011" + "10000000" + _bits(3, 16)
        self._refused(text.replace(frames_line + "\n", ""), r"no frame count record \(0x3B\)")

    def test_usercode_record_must_match_the_comment(self):
        text = gowin_fs_text(self.payloads)
        lines = text.splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.startswith("00001010"))
        lines[k] = lines[k][:-1] + ("1" if lines[k][-1] == "0" else "0")
        self._refused(
            "\n".join(lines), r"USERCODE record 0x[0-9a-f]{8} does not match.*corrupt"
        )

    def test_record_widths_after_the_frames_are_checked(self):
        text = gowin_fs_text(self.payloads)
        end = "00001000" + "0" * 24
        self._refused(text.replace(end, end[:8]), "end record is 8 bits, not 32")
        short = gowin_fs_text(self.payloads, layout=(3, 4, 36, 8, 48))
        self._refused(short, "padding line of 48 bits, not 64")

    def test_trailer_must_be_complete_and_in_order(self):
        text = gowin_fs_text(self.payloads)
        lines = text.splitlines()
        usercode = next(ln for ln in lines if ln.startswith("00001010"))
        end = next(ln for ln in lines if ln.startswith("00001000"))
        self._refused("\n".join(ln for ln in lines if ln != usercode),
                      r"no USERCODE/checksum record \(0x0A\)")
        self._refused("\n".join(lines[:lines.index(end)]), r"no end record \(0x08\).*truncated")
        self._refused(text.replace(end, end + "\n" + usercode), "unexpected record 0x0a")

    def test_a_short_frame_count_is_refused(self):
        # One frame too few: the last frame is where the padding line belongs.
        self._refused(gowin_fs_text(self.payloads, frames=2), "no CRC'd padding line after the 2")
        self._refused(gowin_fs_text(self.payloads, frames=2, crc=False),
                      "unexpected record 0x.. after the 2 frames")

    def test_frame_count_past_the_file_is_refused(self):
        self._refused(gowin_fs_text(self.payloads, frames=100), "frame lines, the header says 100")

    def test_frame_count_must_be_the_part_s(self):
        self._refused(gowin_fs_text(self.payloads[:2]),
                      "2 frames; IDCODE 0x1100481b has 3 .*initialized block RAM")

    def test_frames_must_be_one_length(self):
        text = gowin_fs_text(self.payloads)
        second = text.splitlines()[self._frame_index(text) + 1]
        self._refused(text.replace(second, second + "1" * 8), "frame of 72 bits, the first is 64")

    def test_frame_size_must_match_the_part(self):
        self._refused(gowin_fs_text(random_payloads(3, 44)),
                      "frames of 72 bits; IDCODE 0x1100481b has 64 with CRC on")

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
