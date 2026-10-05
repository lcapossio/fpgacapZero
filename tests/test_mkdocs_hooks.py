# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

"""The HTML-manual hook (tools/mkdocs_hooks.py) rewrites the GitHub-relative
links in docs/ for the site, and warns (failing ``mkdocs build --strict``) on
any target that does not exist.  It imports nothing from MkDocs, so it is
tested here without it."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/owner/repo"


def _load_hooks():
    spec = importlib.util.spec_from_file_location(
        "fcapz_mkdocs_hooks", ROOT / "tools" / "mkdocs_hooks.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hooks = _load_hooks()


@pytest.fixture
def repo(tmp_path):
    for rel in (
        "rtl/core.v",
        "CHANGELOG.md",
        "docs/README.md",
        "docs/01_intro.md",
        "docs/specs/map.md",
        "docs/guide/README.md",
        "docs/assets/shot.png",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return tmp_path


def _rewrite(repo, line, src_uri="01_intro.md", page_url="01_intro/"):
    return hooks.rewrite_line(
        line, repo_root=repo, repo_url=REPO_URL, src_uri=src_uri, page_url=page_url
    )


def test_links_out_of_docs_point_at_the_repository(repo):
    assert _rewrite(repo, "[v](../rtl/core.v#L3)") == f"[v]({REPO_URL}/blob/main/rtl/core.v#L3)"
    assert _rewrite(repo, "[r](../rtl/)") == f"[r]({REPO_URL}/tree/main/rtl)"
    assert (
        _rewrite(repo, "[m](../../CHANGELOG.md)", src_uri="specs/map.md", page_url="specs/map/")
        == f"[m]({REPO_URL}/blob/main/CHANGELOG.md)"
    )


def test_links_inside_docs_are_left_to_mkdocs_or_mapped(repo):
    for line in ("[p](specs/map.md#a)", "[s](#local)", "[w](https://example.com/x)"):
        assert _rewrite(repo, line) == line
    # Folders: a README.md becomes the page, otherwise the repository listing.
    assert _rewrite(repo, "[g](guide/)") == "[g](guide/README.md)"
    assert _rewrite(repo, "[h](.)") == "[h](./README.md)"
    assert _rewrite(repo, "[s](specs/)") == f"[s]({REPO_URL}/tree/main/docs/specs)"


@pytest.mark.parametrize("line", ["[x](../rtl/missing.v)", "[x](../../../etc/passwd)"])
def test_dead_links_out_of_docs_warn(repo, line, caplog):
    with caplog.at_level(logging.WARNING, logger="mkdocs.hooks.fcapz"):
        assert _rewrite(repo, line) == line
    assert len(caplog.records) == 1


def test_raw_images_follow_the_page_url(repo, caplog):
    line = '<img src="assets/shot.png" width="10">'
    assert _rewrite(repo, line) == '<img src="../assets/shot.png" width="10">'
    assert _rewrite(repo, line, src_uri="README.md", page_url="") == line
    with caplog.at_level(logging.WARNING, logger="mkdocs.hooks.fcapz"):
        _rewrite(repo, '<img src="assets/missing.png">')
    assert len(caplog.records) == 1


def _page(markdown, src_uri="01_intro.md", page_url="01_intro/"):
    return SimpleNamespace(
        file=SimpleNamespace(src_uri=src_uri, content_string=markdown),
        url=page_url,
        edit_url="https://example.com/edit",
    )


def _config(repo):
    return {"config_file_path": str(repo / "mkdocs.yml"), "repo_url": REPO_URL + "/"}


def test_fenced_code_is_not_rewritten(repo):
    markdown = "[a](../CHANGELOG.md)\n```md\n[b](../CHANGELOG.md)\n```\n[c](../CHANGELOG.md)\n"
    page = _page(markdown)
    out = hooks.on_page_markdown(markdown, page, _config(repo), files=None).splitlines()
    url = f"{REPO_URL}/blob/main/CHANGELOG.md"
    assert out == [f"[a]({url})", "```md", "[b](../CHANGELOG.md)", "```", f"[c]({url})"]
    assert page.edit_url == "https://example.com/edit"


@pytest.mark.parametrize(
    "line",
    [
        '!!! note "Title"',
        "??? tip",
        '=== "Python"',
        "![shot](assets/shot.png){ width=300 }",
        "{: .center }",
        '<div class="grid" markdown>',
        "> [!DANGER]",
    ],
)
def test_site_only_syntax_is_flagged(line):
    assert hooks.site_only_syntax(line)


@pytest.mark.parametrize(
    "line",
    [
        *(f"> [!{kind}]" for kind in hooks.ALERT_TYPES),
        "> **Goal**: read this",
        "Use `{x}` and [link](a.md) {not attr}",
        "| `--depth N` | `1024` |",
    ],
)
def test_github_markdown_is_not_flagged(line):
    assert hooks.site_only_syntax(line) is None


def test_site_only_syntax_and_front_matter_warn_outside_fences(repo, caplog):
    markdown = "---\ntitle: x\n---\n!!! note\n```md\n!!! note\n```\n"
    with caplog.at_level(logging.WARNING, logger="mkdocs.hooks.fcapz"):
        hooks.on_page_markdown(markdown, _page(markdown), _config(repo), files=None)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2, messages
    assert "front matter" in messages[0] and "admonition" in messages[1]


def test_generated_pages_have_no_edit_button(repo):
    markdown = hooks.GENERATED_PAGE_MARK + " -->\n# API\n"
    page = _page(markdown)
    hooks.on_page_markdown(markdown, page, _config(repo), files=None)
    assert page.edit_url is None


def test_site_name_carries_the_version(repo):
    (repo / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    config = {"config_file_path": str(repo / "mkdocs.yml"), "site_name": "Manual"}
    assert hooks.on_config(config)["site_name"] == "Manual v1.2.3"
