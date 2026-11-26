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
* that many frame lines, all the same length;
* trailer records: ``0x0A`` carries the frame checksum in its low 16 bits,
  then ``0x08``, with all-ones padding around them.

:func:`read_gowin_fs` checks all of that and returns each frame's payload
bits and the IDCODE, checksum and user code the file was built with.  Gowin
documents the format in UG290 ("Gowin FPGA Products Programming and
Configuration Guide"), section 3.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The sync word ending the preamble.
_SYNC = "1010010111000011"
_KEY_IDCODE = 0x06
_KEY_FRAMES = 0x3B
_KEY_CHECKSUM = 0x0A

#: Frame layout per IDCODE, for the checksum: ``(frame bits, leading pad
#: bits, trailing CRC bits, trailing pad bits)``.  The checksum is the
#: 16-bit sum of the frames' payload bits, concatenated across frames and
#: read as big-endian 16-bit words.
FRAME_LAYOUTS: dict[int, tuple[int, int, int, int]] = {
    0x1100481B: (2904, 4, 16, 48),  # GW1NR-9C / GW1N-9C
}


@dataclass(frozen=True)
class GowinBitstream:
    """A parsed ``.fs`` file."""

    path: str
    idcode: int
    frames: int
    frame_bits: int
    #: The frame checksum the trailer declares.
    checksum: int | None
    #: The USERCODE the device reports once configured (the file's
    #: ``UserCode`` comment; Gowin defaults it to the checksum).
    usercode: int | None
    #: Each frame's payload bits (its leading pad, CRC and trailing pad
    #: dropped), first bit first, as Gowin's programmer loads them one DR
    #: scan per frame; empty when the IDCODE's frame layout is not known.
    frame_payloads: tuple[str, ...]
    #: The ``Device`` comment, e.g. ``"GW1NR-9"``.
    device: str | None
    #: Every ``//Key: value`` comment.
    options: dict[str, str]


class GowinFsError(ValueError):
    """The file is not a ``.fs`` bitstream this reader can use."""


def _byte(bits: str, pos: int = 0) -> int:
    return int(bits[pos:pos + 8], 2)


def frame_checksum(frame_lines: list[str], layout: tuple[int, int, int, int]) -> int:
    """The checksum of *frame_lines* (bit strings) for frame *layout*."""
    _bits, lead, crc, tail = layout
    payload = "".join(line[lead:len(line) - crc - tail] for line in frame_lines)
    total = 0
    for pos in range(0, len(payload), 16):
        total += int(payload[pos:pos + 16].ljust(16, "0"), 2)
    return total & 0xFFFF


def read_gowin_fs(path: str) -> GowinBitstream:
    """Parse and check the ``.fs`` file at *path*; see the module docstring.

    Raises :class:`GowinFsError` for a malformed file, a compressed or
    encrypted one (not supported), or a checksum that does not match.
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
    while i < len(records):
        number, bits = records[i]
        i += 1
        key = _byte(bits) & 0x7F
        if key == _KEY_IDCODE:
            if len(bits) != 64:
                raise GowinFsError(f"{path}:{number}: IDCODE record is {len(bits)} bits, not 64")
            if idcode is not None:
                raise GowinFsError(f"{path}:{number}: a second IDCODE record")
            idcode = int(bits[32:], 2)
        elif _byte(bits) == _KEY_FRAMES:
            frames = int(bits[-16:], 2)
            break
    if idcode is None:
        raise GowinFsError(f"{path}: no IDCODE record (0x06) in the header")
    if frames is None or frames == 0:
        raise GowinFsError(f"{path}: no frame count record (0x3B) in the header")
    frame_lines = [bits for _n, bits in records[i:i + frames]]
    if len(frame_lines) != frames:
        raise GowinFsError(f"{path}: {len(frame_lines)} frame lines, the header says {frames}")
    frame_bits = len(frame_lines[0])
    for number, bits in records[i:i + frames]:
        if len(bits) != frame_bits:
            raise GowinFsError(
                f"{path}:{number}: frame of {len(bits)} bits, the first is {frame_bits}"
            )
    trailer = records[i + frames:]
    checksum = None
    for number, bits in trailer:
        if set(bits) == {"1"}:
            continue
        if _byte(bits) == _KEY_CHECKSUM:
            checksum = int(bits[-16:], 2)
    if checksum is None:
        raise GowinFsError(f"{path}: no checksum record (0x0A) after the frames")

    layout = FRAME_LAYOUTS.get(idcode)
    payloads: tuple[str, ...] = ()
    if layout is not None:
        if frame_bits != layout[0]:
            raise GowinFsError(
                f"{path}: frames of {frame_bits} bits; IDCODE 0x{idcode:08x} has {layout[0]}"
            )
        _bits, lead, crc, tail = layout
        payloads = tuple(line[lead:len(line) - crc - tail] for line in frame_lines)
        got = frame_checksum(frame_lines, layout)
        if got != checksum:
            raise GowinFsError(
                f"{path}: frame checksum 0x{got:04x} does not match the declared "
                f"0x{checksum:04x}; the file is corrupt"
            )

    usercode = None
    if "UserCode" in options:
        try:
            usercode = int(options["UserCode"], 16)
        except ValueError:
            usercode = None
    return GowinBitstream(
        path=path,
        idcode=idcode,
        frames=frames,
        frame_bits=frame_bits,
        checksum=checksum,
        usercode=usercode,
        frame_payloads=payloads,
        device=options.get("Device"),
        options=options,
    )
