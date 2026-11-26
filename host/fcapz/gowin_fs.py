# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Reader for Gowin ``.fs`` bitstream files.

A ``.fs`` file is text: ``//`` comment lines (device, checksum, user code,
options), then one line of ``0`` / ``1`` characters per bitstream record,
most significant bit first.  The records, in order:

* all-ones preamble lines, then the sync word ``0xA5C3``;
* header records, each keyed by its first byte: ``0x06`` carries the
  device IDCODE in its low 32 bits, and ``0x3B`` the number of
  configuration frames in its low 16 bits (and is the last header record);
* that many frame lines, all the same length: leading pad bits, the frame's
  payload, a CRC-16 when CRC is on, then trailing pad bits;
* trailer records: ``0x0A`` carries the USERCODE in its low 32 bits (by
  default the frame checksum), then ``0x08``, with all-ones padding around
  them.

Bit 7 of a record's key byte marks a record the CRC does not cover; with
CRC off, every record has it.  With CRC on, the ``0x3B`` record's second
byte has bit 7 set, and each frame's CRC-16/ARC (stored low byte first)
covers the previous frame's trailing pad and this frame's leading pad and
payload; the first frame's covers the CRC'd header records instead of a
previous frame.  The frame checksum is the 16-bit sum of the payloads,
concatenated across frames and read as big-endian 16-bit words.

:func:`read_gowin_fs` checks all of that and returns each frame's payload
bits and the IDCODE, checksum and USERCODE.  Gowin documents the format in
UG290 ("Gowin FPGA Products Programming and Configuration Guide"); the CRC
rules above were derived from files Gowin's tools write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The sync word ending the preamble.
_SYNC = "1010010111000011"
_KEY_IDCODE = 0x06
_KEY_FRAMES = 0x3B
_KEY_USERCODE = 0x0A
_KEY_END = 0x08
_NO_CRC = 0x80  # key-byte flag: the CRC does not cover this record

#: Frame layout per IDCODE: ``(frames, leading pad bits, payload bits,
#: trailing pad bits)``.  A frame is those plus a 16-bit CRC when CRC is on.
FRAME_LAYOUTS: dict[int, tuple[int, int, int, int]] = {
    0x1100481B: (712, 4, 2836, 48),  # GW1NR-9C / GW1N-9C
}


@dataclass(frozen=True)
class GowinBitstream:
    """A parsed ``.fs`` file."""

    path: str
    idcode: int
    frames: int
    frame_bits: int
    #: The frame checksum (the 16-bit sum of the payloads).
    checksum: int
    #: The trailer's ``0x0A`` value: written through WRITE_CHECKSUM after
    #: the frames, and what the device then reports as its USERCODE.
    usercode: int
    #: Whether each frame carries a CRC (checked here; not sent).
    crc: bool
    #: Each frame's payload bits (pad and CRC dropped), first bit first, as
    #: Gowin's programmer loads them one DR scan per frame; empty when the
    #: IDCODE's frame layout is not known.
    frame_payloads: tuple[str, ...]
    #: The ``Device`` comment, e.g. ``"GW1NR-9"``.
    device: str | None
    #: Every ``//Key: value`` comment.
    options: dict[str, str]


class GowinFsError(ValueError):
    """The file is not a ``.fs`` bitstream this reader can use."""


def _byte(bits: str, pos: int = 0) -> int:
    return int(bits[pos:pos + 8], 2)


def _key(bits: str) -> int:
    return _byte(bits) & 0x7F


def _bytes(bits: str) -> bytes:
    return int(bits, 2).to_bytes(len(bits) // 8, "big") if bits else b""


def crc16_arc(data: bytes, crc: int = 0) -> int:
    """CRC-16/ARC (polynomial 0x8005, reflected, initial value 0)."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame_checksum(payloads: list[str] | tuple[str, ...]) -> int:
    """The checksum of *payloads* (bit strings): the 16-bit sum of their
    concatenation read as big-endian 16-bit words, the last zero-padded."""
    payload = "".join(payloads)
    total = 0
    for pos in range(0, len(payload), 16):
        total += int(payload[pos:pos + 16].ljust(16, "0"), 2)
    return total & 0xFFFF


def _hex_option(options: dict[str, str], key: str) -> int | None:
    try:
        return int(options[key], 16)
    except (KeyError, ValueError):
        return None


def read_gowin_fs(path: str) -> GowinBitstream:
    """Parse and check the ``.fs`` file at *path*; see the module docstring.

    Raises :class:`GowinFsError` for a malformed file, a compressed or
    encrypted one (not supported), a frame CRC or checksum that does not
    match, or, for a part whose layout is known, a frame count or size other
    than that part's (BSRAM-initialized images are not supported yet).
    """
    options: dict[str, str] = {}
    records: list[tuple[int, str]] = []  # (line number, bits)
    try:
        with open(path, encoding="ascii") as f:
            text = f.read()
    except UnicodeDecodeError as exc:
        raise GowinFsError(f"{path}: not a Gowin .fs file (binary content)") from exc
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//"):
            key, sep, value = line[2:].partition(":")
            if sep:
                options[key.strip()] = value.strip()
            continue
        if re.fullmatch(r"[01]+", line) is None:
            raise GowinFsError(f"{path}:{number}: not a line of 0s and 1s")
        if len(line) % 8:
            raise GowinFsError(f"{path}:{number}: {len(line)} bits, not whole bytes")
        records.append((number, line))
    if not records:
        raise GowinFsError(f"{path}: no bitstream data (not a Gowin .fs file?)")
    for key in ("Compress", "Encryption"):
        if options.get(key, "OFF").upper() != "OFF":
            raise GowinFsError(
                f"{path}: built with {key}: {options[key]}; only uncompressed, "
                "unencrypted bitstreams are supported"
            )

    i = 0
    while i < len(records) and set(records[i][1]) == {"1"}:
        i += 1
    if i == 0 or i >= len(records) or records[i][1] != _SYNC:
        raise GowinFsError(f"{path}: no all-ones preamble and 0xA5C3 sync word")
    i += 1

    idcode: int | None = None
    frames: int | None = None
    crc_on = False
    crc_header = bytearray()  # the header records the first frame's CRC covers
    while i < len(records):
        number, bits = records[i]
        i += 1
        if not _byte(bits) & _NO_CRC:
            crc_header += _bytes(bits)
        key = _key(bits)
        if key == _KEY_IDCODE:
            if len(bits) != 64:
                raise GowinFsError(f"{path}:{number}: IDCODE record is {len(bits)} bits, not 64")
            if idcode is not None:
                raise GowinFsError(f"{path}:{number}: a second IDCODE record")
            idcode = int(bits[32:], 2)
        elif key == _KEY_FRAMES:
            if len(bits) != 32:
                raise GowinFsError(f"{path}:{number}: frame count record is {len(bits)} bits")
            frames = int(bits[-16:], 2)
            crc_on = bool(_byte(bits, 8) & 0x80)
            break
    if idcode is None:
        raise GowinFsError(f"{path}: no IDCODE record (0x06) in the header")
    if frames is None or frames == 0:
        raise GowinFsError(f"{path}: no frame count record (0x3B) in the header")
    frame_records = records[i:i + frames]
    if len(frame_records) != frames:
        raise GowinFsError(f"{path}: {len(frame_records)} frame lines, the header says {frames}")
    frame_bits = len(frame_records[0][1])
    for number, bits in frame_records:
        if len(bits) != frame_bits:
            raise GowinFsError(
                f"{path}:{number}: frame of {len(bits)} bits, the first is {frame_bits}"
            )

    # With CRC on, a line of ones ends with the CRC continuing the frames'.
    trailer = records[i + frames:]
    if crc_on:
        if not trailer or set(trailer[0][1][:-16]) != {"1"}:
            raise GowinFsError(f"{path}: no CRC'd padding line after the {frames} frames")
        closing = trailer[0]
        trailer = trailer[1:]
    # The trailer, in order: the 0x0A record, then 0x08, padded with ones.
    usercode: int | None = None
    ended = False
    for number, bits in trailer:
        if set(bits) == {"1"}:
            continue
        key = _key(bits)
        if key == _KEY_USERCODE and usercode is None and not ended:
            if len(bits) != 64:
                raise GowinFsError(f"{path}:{number}: 0x0A record is {len(bits)} bits, not 64")
            usercode = int(bits[32:], 2)
        elif key == _KEY_END and usercode is not None and not ended:
            ended = True
        elif key == _KEY_END and usercode is None:
            raise GowinFsError(f"{path}:{number}: no USERCODE/checksum record (0x0A) "
                               "before the end record")
        else:
            raise GowinFsError(
                f"{path}:{number}: unexpected record 0x{_byte(bits):02x} after the "
                f"{frames} frames (is the frame count right?)"
            )
    if usercode is None:
        raise GowinFsError(f"{path}: no USERCODE/checksum record (0x0A) after the frames")
    if not ended:
        raise GowinFsError(f"{path}: no end record (0x08) after 0x0A; the file is truncated")

    declared = _hex_option(options, "CheckSum")
    if declared is None:
        declared = usercode & 0xFFFF  # Gowin's default USERCODE is the checksum
    payloads: tuple[str, ...] = ()
    checksum = declared
    layout = FRAME_LAYOUTS.get(idcode)
    if layout is not None:
        rows, lead, payload_bits, tail = layout
        if frames != rows:
            raise GowinFsError(
                f"{path}: {frames} frames; IDCODE 0x{idcode:08x} has {rows} (images "
                "with initialized block RAM are not supported yet)"
            )
        want = lead + payload_bits + (16 if crc_on else 0) + tail
        if frame_bits != want:
            raise GowinFsError(
                f"{path}: frames of {frame_bits} bits; IDCODE 0x{idcode:08x} has {want} "
                f"with CRC {'on' if crc_on else 'off'}"
            )
        body = lead + payload_bits
        if crc_on:
            previous = bytes(crc_header)
            for number, bits in frame_records + [closing]:
                at = body if number != closing[0] else len(bits) - 16
                stored = int(bits[at:at + 16], 2)
                stored = ((stored & 0xFF) << 8) | (stored >> 8)  # low byte first
                if crc16_arc(previous + _bytes(bits[:at])) != stored:
                    raise GowinFsError(f"{path}:{number}: frame CRC mismatch; the file is corrupt")
                previous = _bytes(bits[at + 16:])
        payloads = tuple(bits[lead:body] for _n, bits in frame_records)
        checksum = frame_checksum(payloads)
        if checksum != declared:
            raise GowinFsError(
                f"{path}: frame checksum 0x{checksum:04x} does not match the declared "
                f"0x{declared:04x}; the file is corrupt"
            )

    return GowinBitstream(
        path=path,
        idcode=idcode,
        frames=frames,
        frame_bits=frame_bits,
        checksum=checksum,
        usercode=usercode,
        crc=crc_on,
        frame_payloads=payloads,
        device=options.get("Device"),
        options=options,
    )
