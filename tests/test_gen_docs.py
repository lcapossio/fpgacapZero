# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""tools/gen_docs.py writes chapter 10's option tables and the Python API
reference from the code; these tests keep the committed docs in step with it
and pin the generator's own rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("fcapz_gen_docs", ROOT / "tools" / "gen_docs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen = _load()


def _parser():
    from fcapz.cli import build_parser

    return build_parser()


def test_generated_docs_are_current():
    stale = [
        path.relative_to(ROOT).as_posix()
        for path, text in gen.generate().items()
        if path.read_text(encoding="utf-8") != text
    ]
    assert not stale, f"run: python tools/gen_docs.py  (stale: {', '.join(stale)})"


def test_a_hand_edit_inside_a_block_is_reverted():
    text = gen.CLI_DOC.read_text(encoding="utf-8")
    row = "| `--pretrigger N` | `8` |"
    assert text.count(row) == 1
    edited = text.replace(row, "| `--pretrigger N` | `99` |")
    assert gen.render_cli_doc(edited, _parser()) == text


def test_every_subcommand_needs_a_block():
    text = gen.CLI_DOC.read_text(encoding="utf-8")
    start = text.index("<!-- BEGIN GENERATED cli:arm ")
    end = text.index("<!-- END GENERATED cli:arm -->") + len("<!-- END GENERATED cli:arm -->")
    with pytest.raises(SystemExit, match="no generated block for arm"):
        gen.render_cli_doc(text[:start] + text[end:], _parser())


def test_unknown_subcommand_block_is_an_error():
    text = "<!-- BEGIN GENERATED cli:nope (x) -->\n<!-- END GENERATED cli:nope -->\n"
    with pytest.raises(SystemExit, match="unknown subcommand"):
        gen.render_cli_doc(text, _parser())


def test_docstring_sections_become_lists_and_literal_blocks():
    def sample():
        """Summary with <tag> and `a<b`.

        Layout:
            bits[3:0] = x

        Args:
            timeout: seconds to wait,
                across all resets.
            count (int): words.

        Raises:
            ValueError: if bad.
        """

    assert gen._docstring(sample).split("\n") == [
        "Summary with &lt;tag&gt; and `a<b`.",
        "",
        "Layout:",
        "",
        "```text",
        "bits[3:0] = x",
        "```",
        "",
        "**Args:**",
        "",
        "- `timeout`: seconds to wait, across all resets.",
        "- `count` (int): words.",
        "",
        "**Raises:**",
        "",
        "- `ValueError`: if bad.",
    ]


def test_reprs_do_not_depend_on_hash_seed_or_addresses():
    assert gen._stable_repr(frozenset({"b", "a"})) == "frozenset({'a', 'b'})"
    assert gen._stable_repr(object()) == "<object>"
    assert gen._code_cell("int | None") == "<code>int &#124; None</code>"
