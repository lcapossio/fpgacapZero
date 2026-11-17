# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""Keep the hand-written manual in step with the code.

tools/gen_docs.py regenerates the CLI tables and the API reference; these
tests cover the prose around them:

* Verilog snippets: every ``.PARAM(...)`` / ``.port(...)`` in an
  instantiation, and every ``parameter`` in a ``module`` declaration excerpt,
  must exist on that module in ``rtl/``.
* CLI examples: every ``fcapz ...`` command in a shell block must parse with
  the real argument parser (nothing is executed).
* Version strings: version-register values, ``version_minor`` fields and
  ``FCAPZ_VERSION_*`` excerpts must match ``VERSION``.

An example that is deliberately not current (a past measurement, an
illustration, an old-bitstream scenario) opts out with an HTML comment,
invisible in the rendered manual, on the line before it::

    <!-- docs-sync: skip (why) -->

It applies to the next fenced block, or to the next paragraph or table when
no fence follows.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]
SKIP_MARKER = re.compile(r"<!--\s*docs-sync:\s*skip\b")
FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")


@dataclass
class Block:
    path: Path
    line: int  # 1-based line of the first content line
    lang: str  # fence language ("" for a bare fence or prose)
    text: str
    fenced: bool

    def where(self, offset: int = 0) -> str:
        return f"{self.path.relative_to(ROOT).as_posix()}:{self.line + offset}"


def _blocks(path: Path) -> list[Block]:
    """Split a Markdown file into fenced blocks and prose paragraphs,
    dropping whatever a skip marker covers."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[Block] = []
    skip_next = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if SKIP_MARKER.search(line):
            skip_next = True
            i += 1
            continue
        fence = FENCE.match(line)
        if fence:
            marker, lang = fence.group(1), fence.group(2).lower()
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith(marker):
                j += 1
            if not skip_next:
                blocks.append(Block(path, i + 2, lang, "\n".join(lines[i + 1:j]), True))
            skip_next = False
            i = j + 1
            continue
        if not line.strip():
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].strip() and not FENCE.match(lines[j]) \
                and not SKIP_MARKER.search(lines[j]):
            j += 1
        if not skip_next:
            blocks.append(Block(path, i + 1, "", "\n".join(lines[i:j]), False))
        skip_next = False
        i = j
    return blocks


ALL_BLOCKS = [b for p in DOC_FILES for b in _blocks(p)]


# --------------------------------------------------------------------------
# Verilog snippets against rtl/
# --------------------------------------------------------------------------

def _strip_verilog_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _balanced(text: str, start: int) -> int:
    """Index just past the parenthesis group opening at text[start]."""
    depth = 0
    for k in range(start, len(text)):
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(text)


def _split_top(text: str) -> list[str]:
    items, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return items


def _decl_name(item: str) -> str | None:
    """Name declared by one header item (``parameter [7:0] W = 8`` -> W)."""
    item = item.split("=", 1)[0]
    item = re.sub(r"\[[^\]]*\]", " ", item)
    names = re.findall(r"[A-Za-z_]\w*", item)
    return names[-1] if names else None


@dataclass
class Module:
    params: set[str]
    ports: set[str]


def _parse_module(text: str, start: int) -> Module:
    """Parameters and ports of the module whose name ends at text[start]."""
    k = start
    params: set[str] = set()
    ports: set[str] = set()
    m = re.compile(r"\s*#\s*\(").match(text, k)
    if m:
        end = _balanced(text, m.end() - 1)
        for item in _split_top(text[m.end():end - 1]):
            if (name := _decl_name(item)) is not None:
                params.add(name)
        k = end
    m = re.compile(r"\s*\(").match(text, k)
    if m:
        end = _balanced(text, m.end() - 1)
        for item in _split_top(text[m.end():end - 1]):
            if (name := _decl_name(item)) is not None:
                ports.add(name)
        k = end
    body_end = text.find("endmodule", k)
    body = text[k:body_end if body_end >= 0 else len(text)]
    for stmt in re.findall(r"\bparameter\b([^;]*);", body):
        for item in _split_top(stmt):
            if (name := _decl_name(item)) is not None:
                params.add(name)
    for stmt in re.findall(r"\b(?:input|output|inout)\b([^;]*);", body):
        for item in _split_top(stmt):
            if (name := _decl_name(item)) is not None:
                ports.add(name)
    return Module(params, ports)


def _rtl_modules() -> dict[str, Module]:
    modules: dict[str, Module] = {}
    for path in sorted((ROOT / "rtl").rglob("*.v")) + sorted((ROOT / "rtl").rglob("*.sv")):
        text = _strip_verilog_comments(path.read_text(encoding="utf-8", errors="replace"))
        text = re.sub(r"^\s*`[^\n]*", "", text, flags=re.M)  # preprocessor lines
        for m in re.finditer(r"\bmodule\s+(\w+)", text):
            modules[m.group(1)] = _parse_module(text, m.end())
    return modules


RTL = _rtl_modules()


def _named_connections(text: str) -> set[str]:
    return set(re.findall(r"\.\s*([A-Za-z_]\w*)\s*\(", text))


def _verilog_problems(block: Block) -> list[str]:
    text = _strip_verilog_comments(block.text)
    problems: list[str] = []

    def at(pos: int) -> str:
        return block.where(text.count("\n", 0, pos))

    # Declaration excerpts: module NAME #( parameter ... )
    for m in re.finditer(r"\bmodule\s+(\w+)", text):
        real = RTL.get(m.group(1))
        if real is None:
            continue
        shown = _parse_module(text, m.end())
        for name in sorted(shown.params - real.params):
            problems.append(f"{at(m.start())}: {m.group(1)} has no parameter {name}")
        for name in sorted(shown.ports - real.ports - {"..."}):
            if re.fullmatch(r"[A-Za-z_]\w*", name):
                problems.append(f"{at(m.start())}: {m.group(1)} has no port {name}")
    # Instantiations: NAME [#(...)] inst (...);
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*(?=#|\s[A-Za-z_]\w*\s*\()", text):
        name = m.group(1)
        if name not in RTL or text[:m.start()].rstrip().endswith("module"):
            continue
        real = RTL[name]
        k = m.end()
        pm = re.compile(r"\s*#\s*\(").match(text, k)
        if pm:
            end = _balanced(text, pm.end() - 1)
            for p in sorted(_named_connections(text[pm.end():end - 1]) - real.params):
                problems.append(f"{at(m.start())}: {name} has no parameter {p}")
            k = end
        im = re.compile(r"\s*[A-Za-z_]\w*\s*\(").match(text, k)
        if im:
            end = _balanced(text, im.end() - 1)
            for p in sorted(_named_connections(text[im.end():end - 1]) - real.ports):
                problems.append(f"{at(m.start())}: {name} has no port {p}")
    return problems


def test_rtl_parser_sees_known_wrapper():
    ela = RTL["fcapz_ela_xilinx7"]
    assert {"SAMPLE_W", "DEPTH", "CTRL_CHAIN"} <= ela.params
    assert "WIDE_TRIG" not in ela.params
    assert {"sample_clk", "probe_in"} <= ela.ports


def test_verilog_snippets_match_rtl():
    problems = [p for b in ALL_BLOCKS if b.lang in ("verilog", "systemverilog", "v")
                for p in _verilog_problems(b)]
    assert not problems, "Verilog snippets disagree with rtl/:\n" + "\n".join(problems)


# --------------------------------------------------------------------------
# CLI examples against the argument parser
# --------------------------------------------------------------------------

SHELL_LANGS = {"bash", "sh", "shell", "console", "powershell", "ps1", ""}


def _tokens(line: str) -> list[str]:
    """Shell words of ``line``; pipes, redirects, ``;`` and ``&&`` come out
    as separate tokens and ``#`` comments are dropped, quoting respected.
    Raises ValueError on an unclosed quote."""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def _commands(block: Block):
    """(line offset, argv) for each ``fcapz`` command in a shell block, or
    (line offset, None) for one that cannot be tokenized."""
    lines = block.text.splitlines()
    k = 0
    while k < len(lines):
        start = k
        line = lines[k]
        k += 1
        line = re.sub(r"^\s*(\$|PS>|>)\s+", "", line).strip()
        line = re.sub(r"^(\w+=\S*\s+)+", "", line)  # VAR=value prefixes
        if not line.startswith("fcapz "):
            continue
        # Join backslash/backtick continuations and quoted strings that span
        # lines (e.g. inline JSON) until the command tokenizes.
        while True:
            if line.rstrip().endswith(("\\", "`")) and k < len(lines):
                line = line.rstrip()[:-1] + " " + lines[k]
                k += 1
                continue
            try:
                tokens = _tokens(line)
                break
            except ValueError:
                if k >= len(lines):
                    tokens = None
                    break
                line = line + "\n" + lines[k]
                k += 1
        if re.search(r"<[A-Za-z][^<>\s]*>|\.\.\.|…|\$\(", line):
            continue  # placeholder syntax, not a literal command
        if tokens is None:
            yield start, None
            continue
        for n, tok in enumerate(tokens):
            if tok and set(tok) <= set("();<>|&"):
                # stop at a pipe, redirect or separator (and the fd of 2>&1)
                if tok[0] in "<>" and n > 1 and tokens[n - 1].isdigit():
                    n -= 1
                tokens = tokens[:n]
                break
        yield start, tokens[1:]


@pytest.mark.parametrize("text, expected", [
    # inline JSON is checked, not mistaken for a placeholder
    ("fcapz capture --trigger-sequence '[{\"a\":1}]' --bad\n",
     [["capture", "--trigger-sequence", '[{"a":1}]', "--bad"]]),
    # a quoted string spanning lines joins with the continuations around it
    ("fcapz capture \\\n  --trigger-sequence '[\n  {\"a\":1}\n]' \\\n  --bad\n",
     [["capture", "--trigger-sequence", '[\n  {"a":1}\n]', "--bad"]]),
    # pipes inside quotes stay; a real pipe, redirect or comment ends it
    ("fcapz capture --probes 'a|b' --out x.json | tee log  # note\n",
     [["capture", "--probes", "a|b", "--out", "x.json"]]),
    ("fcapz probe 2>&1 | grep x\n", [["probe"]]),
    # usage lines with placeholders are skipped; an unclosed quote is reported
    ("fcapz [global options] <subcommand>\n", []),
    ("fcapz capture --trigger-sequence '[ --out x\n", [None]),
])
def test_command_extraction(text, expected):
    block = Block(ROOT / "docs" / "x.md", 1, "bash", text, True)
    assert [argv for _, argv in _commands(block)] == expected


def _parser_without_file_opening():
    """The CLI parser with FileType arguments read as plain strings, so
    example file names need not exist."""
    from fcapz.cli import build_parser

    parser = build_parser()
    pending = [parser]
    while pending:
        p = pending.pop()
        for action in p._actions:
            if isinstance(action.type, argparse.FileType):
                action.type = str
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return parser


def test_cli_examples_parse():
    parser = _parser_without_file_opening()
    failures: list[str] = []
    for block in ALL_BLOCKS:
        if not block.fenced or block.lang not in SHELL_LANGS or "fcapz " not in block.text:
            continue
        for offset, argv in _commands(block):
            if argv is None:
                failures.append(f"{block.where(offset)}: cannot tokenize (unclosed quote?)")
                continue
            if not argv:
                continue
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    parser.parse_args(argv)
            except SystemExit as exc:
                if exc.code not in (0, None):
                    reason = err.getvalue().strip().splitlines()[-1:] or ["?"]
                    failures.append(f"{block.where(offset)}: fcapz {' '.join(argv)}\n"
                                    f"    {reason[0]}")
    assert not failures, "CLI examples the parser rejects:\n" + "\n".join(failures)


# --------------------------------------------------------------------------
# Version strings against VERSION
# --------------------------------------------------------------------------

def _version() -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in (ROOT / "VERSION").read_text().strip().split("."))
    return major, minor, patch


def _core_ids() -> set[int]:
    vh = (ROOT / "rtl" / "fcapz_version.vh").read_text(encoding="utf-8")
    return {int(h, 16) for h in re.findall(r"CORE_ID\s+16'h([0-9A-Fa-f]{4})", vh)}


# {major, minor, core_id} identity word, e.g. 0x0005_4C41
VERSION_REG = re.compile(r"\b0x([0-9A-Fa-f]{2})_?([0-9A-Fa-f]{2})_?([0-9A-Fa-f]{4})\b")


def test_version_strings_are_current():
    major, minor, patch = _version()
    core_ids = _core_ids()
    current = f"{major}.{minor}.{patch}"
    problems: list[str] = []
    for block in ALL_BLOCKS:
        for offset, line in enumerate(block.text.splitlines()):
            where = block.where(offset)
            for field, want in (("major", major), ("minor", minor), ("patch", patch)):
                for m in re.finditer(rf"version_{field}\W{{1,4}}?(\d+)\b", line):
                    if int(m.group(1)) != want:
                        problems.append(f"{where}: {m.group(0)!r} ({field} is {want})")
                for m in re.finditer(rf"FCAPZ_VERSION_{field.upper()}\s+(?:8'h|\(=\s*0x)"
                                     r"([0-9A-Fa-f]+)", line):
                    if int(m.group(1), 16) != want:
                        problems.append(f"{where}: {m.group(0)!r} ({field} is {want})")
            for m in re.finditer(r"FCAPZ_VERSION_STRING\s+\"([^\"]+)\"", line):
                if m.group(1) != current:
                    problems.append(f"{where}: {m.group(0)!r} (VERSION is {current})")
            for m in VERSION_REG.finditer(line):
                if int(m.group(3), 16) in core_ids and \
                        (int(m.group(1), 16), int(m.group(2), 16)) != (major, minor):
                    problems.append(f"{where}: {m.group(0)} (expected major/minor "
                                    f"{major:02X}/{minor:02X})")
            for m in re.finditer(r"\"version\":\s*(\d+)\b", line):
                value = int(m.group(1))
                if value >= 0x10000 and value & 0xFFFF in core_ids and \
                        (value >> 24, (value >> 16) & 0xFF) != (major, minor):
                    problems.append(f"{where}: {m.group(0)} decodes to "
                                    f"{value >> 24}.{(value >> 16) & 0xFF}")
    assert not problems, (
        "Version strings that do not match VERSION (refresh them, or mark a "
        "deliberately old example with <!-- docs-sync: skip (why) -->):\n"
        + "\n".join(problems))


@pytest.mark.parametrize("text, kept", [
    ("a\n\n<!-- docs-sync: skip (old) -->\n```\nversion_minor: 3\n```\nb\n", ["a", "b"]),
    ("<!-- docs-sync: skip -->\n| t | 0x0003_4C41 |\n| u | v |\n\nc\n", ["c"]),
])
def test_skip_marker_covers_next_block(tmp_path, text, kept):
    path = tmp_path / "x.md"
    path.write_text(text, encoding="utf-8")
    assert [b.text for b in _blocks(path)] == kept
