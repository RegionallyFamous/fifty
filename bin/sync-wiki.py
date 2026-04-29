#!/usr/bin/env python3
"""Mirror ``docs/*.md`` into the GitHub wiki (``fifty.wiki.git``).

The monorepo's prose operator docs live under ``docs/`` and are the
source of truth. Browsers looking at the repo see them rendered by GitHub
directly; but the project also keeps a proper wiki (the sidebar-navigable
kind at ``github.com/RegionallyFamous/fifty/wiki``) whose pages were
hand-written when Obel was a single-theme repo and have drifted since.

Running this script:

    python3 bin/sync-wiki.py           # dry-run, prints the plan
    python3 bin/sync-wiki.py --apply   # clones the wiki, writes pages,
                                       # commits, pushes

…takes each ``docs/*.md``, rewrites inline ``./other-doc.md`` references
to wiki-style ``[Title](Wiki-Page)`` links, fixes ``../AGENTS.md`` style
relative references to absolute GitHub URLs, drops the file into the
wiki as a Title-Case page, and refreshes the wiki's ``Home.md`` +
``_Sidebar.md`` so the new pages are surfaced in the navigation.

Re-running is idempotent: pages that didn't change produce no diff.

Why a script rather than "edit the wiki by hand":
    The wiki was last synced 2026-04-21. Adding 7 new tier-infra docs +
    the how-it-works explainer by hand (and keeping them in lockstep as
    docs evolve) is drift waiting to happen. The source of truth is
    ``docs/*.md``; the wiki is the mirror. Run the script whenever docs
    change.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
WIKI_REMOTE = "https://github.com/RegionallyFamous/fifty.wiki.git"
REPO_URL = "https://github.com/RegionallyFamous/fifty"

# docs/<slug>.md -> (Wiki-Page-Name, sidebar label).
#
# The ordering here drives the sidebar section below. Adding a new doc is
# a one-line addition.
DOC_PAGES: list[tuple[str, str, str]] = [
    ("how-it-works.md", "How-It-Works", "How it works"),
    ("shipping-a-theme.md", "Shipping-a-Theme", "Shipping one theme"),
    ("batch-playbook.md", "Batch-Playbook", "Shipping a batch"),
    ("blindspot-decisions.md", "Blindspot-Decisions", "Blindspot decisions"),
    ("day-0-smoke.md", "Day-0-Smoke", "Day-0 smoke batch"),
    ("tier-3-deferrals.md", "Tier-3-Deferrals", "Tier-3 deferrals"),
    ("ci-pat-setup.md", "CI-PAT-Setup", "FIFTY_AUTO_PAT setup"),
]

# docs/foo.md references for ./bar.md style links within docs/ get
# rewritten to wiki page links using this map.
DOC_TO_WIKI = {slug: page for slug, page, _label in DOC_PAGES}

# Links to root-relative files in the repo rewrite to absolute GitHub URLs
# so they resolve correctly from the wiki's own DOM.
REPO_FILE_URL = f"{REPO_URL}/blob/main/"


def transform_links(body: str, *, source_slug: str) -> str:
    """Rewrite relative markdown links for wiki consumption.

    Four patterns handled:

      * ``./<doc>.md`` or ``<doc>.md``      -> ``[text](Wiki-Page)``
      * ``./<doc>.md#anchor``               -> ``[text](Wiki-Page#anchor)``
      * ``../AGENTS.md`` / ``../README.md`` -> absolute ``github.com`` link
      * ``../<path>`` (any other)           -> absolute ``github.com`` link

    Anchors within the current page (``#foo``) are left alone.
    """

    def sub(match: re.Match[str]) -> str:
        text = match.group(1)
        target = match.group(2)
        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        # docs/<other>.md links -> wiki links
        if target.startswith("./"):
            target = target[2:]
        if target in DOC_TO_WIKI:
            return f"[{text}]({DOC_TO_WIKI[target]}{anchor})"

        # ../<anything> -> absolute GitHub URL
        if target.startswith("../"):
            rel = target[len("../") :]
            return f"[{text}]({REPO_FILE_URL}{rel}{anchor})"

        # Leave fully-qualified URLs, anchor-only links, and siblings
        # we don't recognise alone.
        return match.group(0)

    # Match only markdown link syntax; skip reference-style links and
    # the Mermaid code block (which doesn't contain link syntax anyway).
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    return link_re.sub(sub, body)


WIKI_HEADER = (
    "> _This page is mirrored from [`docs/{doc}`]({url}). Edit the "
    "docs file and re-run `python3 bin/sync-wiki.py --apply` to "
    "refresh the wiki copy._\n\n"
)


def make_wiki_body(doc_path: Path) -> str:
    """Read a docs/<slug>.md and produce the wiki page body."""
    raw = doc_path.read_text(encoding="utf-8")
    body = transform_links(raw, source_slug=doc_path.name)
    header = WIKI_HEADER.format(
        doc=doc_path.name,
        url=f"{REPO_URL}/blob/main/docs/{doc_path.name}",
    )
    # Insert the mirror notice just after the first h1 so the page still
    # reads natively when someone lands on it from a search result.
    m = re.match(r"(#[^\n]+\n\n?)", body)
    if m:
        return body[: m.end()] + header + body[m.end() :]
    return header + body


SIDEBAR_TEMPLATE = """### Fifty

- [Home](Home)

### Overview

- [How it works](How-It-Works)

### Pipeline (operator docs)

- [Shipping one theme](Shipping-a-Theme)
- [Shipping a batch](Batch-Playbook)
- [Blindspot decisions](Blindspot-Decisions)
- [Day-0 smoke batch](Day-0-Smoke)
- [Tier-3 deferrals](Tier-3-Deferrals)
- [FIFTY_AUTO_PAT setup](CI-PAT-Setup)

### Get going

- [Getting Started](Getting-Started)
- [Project Structure](Project-Structure)
- [Architecture](Architecture)
- [FAQ](FAQ)

### Build a theme

- [Adding a Theme](Adding-a-Theme)
- [Design Tokens](Design-Tokens)
- [Templates](Templates)
- [Block Reference](Block-Reference)
- [Style Variations](Style-Variations)
- [Recipes](Recipes)

### WooCommerce

- [WooCommerce Integration](WooCommerce-Integration)

### Working in the repo

- [Working in the Repo](Working-in-the-Repo)
- [Working with LLMs](Working-with-LLMs)
- [Tooling](Tooling)
- [Visual Snapshots](Visual-Snapshots)
- [Anti-Patterns](Anti-Patterns)
- [Contributing](Contributing)
"""

HOME_TEMPLATE = """# Fifty — Wiki

The technical reference for the [Fifty monorepo]({repo_url}). The repo's [README]({repo_url}#readme) covers the elevator pitch and the live demos; this wiki is the working manual.

## Overview

| Page | What's in it |
|---|---|
| [How it works](How-It-Works) | The five-stage theme factory (Ideate → Design → Verify → Self-heal → Ship), end-to-end, plain language + a mermaid diagram. Start here if you're new to the project. |

## Pipeline — operator docs

These pages are mirrored from `docs/` in the repo. They describe the end-to-end flow for shipping one, or many, themes.

| Page | When to read |
|---|---|
| [Shipping one theme](Shipping-a-Theme) | Per-theme operator checklist — concept pick → spec → `bin/design.py` → boot smoke → manual passes → `check.py` → visual baseline → vision review → promote to `shipping` → open PR. |
| [Shipping a batch](Batch-Playbook) | N-themes-at-once wrapper around the same checklist, driven by `bin/design-batch.py --from-concepts`. Read this when shipping 5+ themes in one pass. |
| [Blindspot decisions](Blindspot-Decisions) | Landed-on decisions for the six pre-100-themes blind spots (retirement flow, image sourcing, microcopy voice bank, baseline decay, uniqueness cache invalidation, vision-review spend). |
| [Day-0 smoke batch](Day-0-Smoke) | Honest per-phase timings from hand-shipping 3-5 themes through the pipeline. Calibration baseline for every batch overrun. |
| [Tier-3 deferrals](Tier-3-Deferrals) | What was intentionally NOT shipped yet and under what trigger to build it. "Infrastructure without evidence is waste." |
| [FIFTY_AUTO_PAT setup](CI-PAT-Setup) | Maintainer-only — one-time PAT setup for the auto-baseline workflows. |

## Start here (per-theme reference)

| If you want to... | Read |
|---|---|
| Try a theme in WordPress Playground (one click, no install) | [Getting Started](Getting-Started) |
| Install a theme into a real WordPress instance | [Getting Started → Local install](Getting-Started#loading-themes-into-wordpress) |
| See every directory and what it does | [Project Structure](Project-Structure) |
| Run validators, linters, snap-gated builds | [Tooling](Tooling) |
| Drive the visual snapshot framework | [Visual Snapshots](Visual-Snapshots) |
| Scaffold a brand-new theme variant | [Adding a Theme](Adding-a-Theme) |
| Understand how to work in this repo as an agent | [Working in the Repo](Working-in-the-Repo) |

## Theme-specific deep dives

These pages were written when Obel was a single-theme repo. They are still accurate for Obel-the-base-theme and remain useful as a deep dive into any single theme's mental model — every variant in the monorepo (Chonk, Selvedge, Lysholm, Foundry, Ember, Basalt, Aero, …) is a clone of Obel and inherits the same architecture.

| Page | What's in it |
|---|---|
| [Architecture](Architecture) | Why one `theme.json`, no JS, no build step. The philosophy behind the structure. |
| [Design Tokens](Design-Tokens) | Every color, spacing, font, and layout token, plus how to read and modify them. |
| [Block Reference](Block-Reference) | Which core/WC block to use for which job, with the gotchas. |
| [Templates](Templates) | The full template + part inventory and what each one renders. |
| [Style Variations](Style-Variations) | How to ship a `theme.json` variant from a base theme. |
| [WooCommerce Integration](WooCommerce-Integration) | How the themes paint over WC's default chrome. |
| [Recipes](Recipes) | Common tasks (change a color, add a pattern, etc.). |
| [Anti-Patterns](Anti-Patterns) | The common mistakes that break the no-CSS / no-JS contract. |
| [Working with LLMs](Working-with-LLMs) | How to drive Cursor / Claude / ChatGPT against this codebase. |
| [Tooling](Tooling) | CLI reference for everything in `bin/`. |
| [FAQ](FAQ) | Quick answers to common questions. |
| [Contributing](Contributing) | How to send a PR upstream. |
"""


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    """Run a subprocess, returning stdout."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sync(*, apply: bool) -> int:
    if not DOCS_DIR.is_dir():
        print(f"error: {DOCS_DIR} not found", file=sys.stderr)
        return 1

    work = Path(tempfile.mkdtemp(prefix="fifty-wiki-"))
    wiki_dir = work / "wiki"
    print(f"Cloning wiki into {wiki_dir}…")
    run(["git", "clone", "--depth", "1", WIKI_REMOTE, str(wiki_dir)])

    changes: list[str] = []

    # 1. Write each mirrored doc page.
    for slug, page, _label in DOC_PAGES:
        src = DOCS_DIR / slug
        if not src.is_file():
            print(f"  skip: docs/{slug} not found on disk")
            continue
        body = make_wiki_body(src)
        dst = wiki_dir / f"{page}.md"
        old = dst.read_text(encoding="utf-8") if dst.exists() else ""
        if old == body:
            print(f"  unchanged: {page}.md")
            continue
        dst.write_text(body, encoding="utf-8")
        action = "update" if old else "create"
        print(f"  {action:>8}: {page}.md ({len(body)} chars)")
        changes.append(f"{action}: {page}.md")

    # 2. Refresh Home.md + _Sidebar.md.
    for name, content in (
        ("Home.md", HOME_TEMPLATE.format(repo_url=REPO_URL)),
        ("_Sidebar.md", SIDEBAR_TEMPLATE),
    ):
        dst = wiki_dir / name
        old = dst.read_text(encoding="utf-8") if dst.exists() else ""
        if old == content:
            print(f"  unchanged: {name}")
            continue
        dst.write_text(content, encoding="utf-8")
        action = "update" if old else "create"
        print(f"  {action:>8}: {name}")
        changes.append(f"{action}: {name}")

    if not changes:
        print("\nNo wiki updates needed; everything already in sync.")
        shutil.rmtree(work)
        return 0

    if not apply:
        print(
            "\nDry-run: "
            f"{len(changes)} wiki change(s) pending. "
            "Re-run with --apply to commit + push."
        )
        shutil.rmtree(work)
        return 0

    # 3. Commit + push.
    status = run(["git", "status", "--short"], cwd=wiki_dir)
    if not status:
        print("\nNothing staged (files identical after normalization).")
        shutil.rmtree(work)
        return 0
    print(f"\nGit status:\n{status}\n")
    run(["git", "add", "-A"], cwd=wiki_dir)
    message = (
        "Sync wiki with docs/ (how-it-works + tier docs)\n\n"
        "Mirrored from docs/*.md by bin/sync-wiki.py. "
        "Source of truth lives in the main repo under docs/; "
        "this wiki is the rendered mirror for browsers landing via "
        "the Wiki tab."
    )
    run(["git", "commit", "-m", message], cwd=wiki_dir)
    print("Pushing to origin…")
    run(["git", "push", "origin", "HEAD"], cwd=wiki_dir)
    print("\nDone.")
    shutil.rmtree(work)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually clone the wiki, write pages, and push. "
        "Without this flag the script runs as a dry-run.",
    )
    args = parser.parse_args()
    return sync(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
