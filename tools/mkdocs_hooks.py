# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
"""MkDocs hooks for the HTML manual (see mkdocs.yml).

The manual is written to be read on GitHub, so it links into the rest of the
repository with relative paths such as ``../rtl/fcapz_ela.v`` or
``../CHANGELOG.md``, links folders such as ``specs/``, and embeds a few
images with raw ``<img src="assets/...">``.  None of those survive the site
build unchanged, so this hook adjusts them in each page's Markdown:

* a link out of docs/, or to a docs/ folder without a README.md, points at
  the target's page in the repository on GitHub;
* a link to a docs/ folder with a README.md points at that page;
* a raw ``<img src>`` is made relative to the page's URL, which is one level
  deeper than its source file.

A target that does not exist in the checkout is logged as a warning, which
``mkdocs build --strict`` turns into a failure, so dead links and images are
still caught.  Fenced code blocks are left alone.
"""

from __future__ import annotations

import logging
import posixpath
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.fcapz")

# Branch the rewritten repository links point at.
REPO_BRANCH = "main"

_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"(\]\()([^)\s]+)(\))")
_IMG_SRC = re.compile(r"(<img\b[^>]*?\bsrc=\")([^\"]+)(\")", re.I)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def _is_local(target):
    return not (_SCHEME.match(target) or target.startswith(("#", "/")))


def rewrite_line(line, *, repo_root, repo_url, src_uri, page_url):
    """Return ``line`` with its repository links and raw image paths fixed.

    ``src_uri`` is the page's path under docs/ (``specs/register_map.md``) and
    ``page_url`` its URL in the site (``specs/register_map/``).
    """
    page_dir = posixpath.dirname(src_uri)

    def link(match):
        target = match.group(2)
        if not _is_local(target):
            return match.group(0)
        path, sep, anchor = target.partition("#")
        repo_rel = posixpath.normpath(posixpath.join("docs", page_dir, path))
        local = repo_root / repo_rel
        inside = repo_rel == "docs" or repo_rel.startswith("docs/")
        if inside and not local.is_dir():
            return match.group(0)  # a page or asset: MkDocs checks it
        if inside and (local / "README.md").is_file():
            page = posixpath.join(path, "README.md")
            return f"{match.group(1)}{page}{sep}{anchor}{match.group(3)}"
        if repo_rel.startswith("../"):
            log.warning("%s: link %r points outside the repository", src_uri, target)
            return match.group(0)
        if not local.exists():
            log.warning("%s: link %r targets missing file %s", src_uri, target, repo_rel)
            return match.group(0)
        kind = "tree" if local.is_dir() else "blob"
        url = f"{repo_url}/{kind}/{REPO_BRANCH}/{repo_rel}"
        return f"{match.group(1)}{url}{sep}{anchor}{match.group(3)}"

    def image(match):
        src = match.group(2)
        if not _is_local(src):
            return match.group(0)
        docs_rel = posixpath.normpath(posixpath.join(page_dir, src))
        if docs_rel.startswith("../") or not (repo_root / "docs" / docs_rel).is_file():
            log.warning("%s: image %r not found under docs/", src_uri, src)
            return match.group(0)
        rel = posixpath.relpath(docs_rel, page_url.rstrip("/") or ".")
        return f"{match.group(1)}{rel}{match.group(3)}"

    return _IMG_SRC.sub(image, _LINK.sub(link, line))


def on_page_markdown(markdown, page, config, files):
    kwargs = {
        "repo_root": Path(config["config_file_path"]).resolve().parent,
        "repo_url": config["repo_url"].rstrip("/"),
        "src_uri": page.file.src_uri,
        "page_url": page.url,
    }
    out = []
    in_fence = None
    for line in markdown.splitlines(keepends=True):
        fence = _FENCE.match(line)
        if fence:
            if in_fence is None:
                in_fence = fence.group(1)
            elif fence.group(1) == in_fence:
                in_fence = None
        elif in_fence is None:
            line = rewrite_line(line, **kwargs)
        out.append(line)
    return "".join(out)
