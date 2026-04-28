#!/usr/bin/env python3
"""Visual-snapshot framework for the Fifty theme repo.

Boots each theme's WordPress Playground locally (via @wp-playground/cli),
captures Playwright screenshots across `bin/snap_config.py`'s routes ×
viewports, and optionally diffs against committed baselines so the agent
loop doesn't depend on a human shipping screenshots back over chat.

Why this exists
---------------

The agent that maintains these themes can't load
playground.wordpress.net (in-app browser detection refuses to run the
wasm runtime). It also can't ask the user for a screenshot every time it
adjusts a single padding token. This script closes that loop:

  1. Boot WP+WC+theme locally on http://localhost:9400 using the SAME
     blueprint that the live demo uses, but with the local theme dir
     mounted on top of the GitHub-installed copy so unsynced edits show
     up. ~30-60s first boot, ~10-15s on subsequent boots that hit the
     playground cache in ~/.npm/_npx.
  2. Drive a headless Chromium across every (route, viewport) defined
     in snap_config.py, full-page screenshots saved as PNGs.
  3. Optional: compare each PNG against a committed baseline in
     `tests/visual-baseline/` and fail if too many pixels changed.

How the agent uses it
---------------------

Common loops:

  # See what a single theme looks like at desktop right now (fast):
  python3 bin/snap.py shoot chonk --quick
  # -> reads tmp/snaps/chonk/desktop/*.png

  # Full visual sweep before a PR:
  python3 bin/snap.py shoot --all
  # -> ~10 routes × 4 viewports × 4 themes ≈ 160 PNGs

  # Did anything change vs baseline?
  python3 bin/snap.py diff --all
  # -> exit 1 if any (route, viewport) crosses the threshold

  # I changed something on purpose; re-baseline:
  python3 bin/snap.py baseline --all          # whole theme matrix
  python3 bin/snap.py baseline chonk checkout-filled desktop  # one cell

  # Leave a server running for interactive poking via the
  # cursor-ide-browser MCP:
  python3 bin/snap.py serve chonk
  # -> blocks; visit http://localhost:9400/ ; Ctrl-C to stop

Integration with bin/check.py
-----------------------------

`bin/check.py --visual` runs `shoot --all` + `diff --all` and exits 1 on
any regression above the threshold. It is OPT-IN because a full sweep
adds 2-5 minutes to the check cycle; the standard `--quick` checks stay
fast for the inner loop.

Layout of generated files
-------------------------

  tmp/snap-blueprint-<theme>.json   Mutated blueprint (installTheme step
                                    stripped, wo-configure version bumped
                                    if needed). Regenerated each shoot.
  tmp/snaps/<theme>/<vw>/<slug>.png Latest captures from `shoot`.
  tmp/diffs/<theme>/<vw>/<slug>.*   Per-pixel diff PNGs + diff_summary.json
                                    written by `diff`.
  tests/visual-baseline/...         Committed baselines (PNGs only).

`tmp/` is .gitignored. `tests/visual-baseline/` is committed.

Why NOT wp-env, wp-now, or a local LAMP stack
---------------------------------------------

  * wp-env requires Docker; agent-side install friction + slow boot.
  * wp-now is deprecated; the project moved to @wp-playground/cli.
  * Local LAMP wouldn't reuse the Playground blueprints that already
    encode our content seeding, plugin install, and config. Reusing the
    blueprint means "what the snap shows" exactly matches "what the
    live demo at demo.regionallyfamous.com shows", which is the whole
    point of having a demo.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Add `bin/` to sys.path so we can import snap_config when running this
# file from the repo root (the most common invocation).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from snap_config import (
    A11Y_SUPPRESSIONS,
    BUDGETS,
    INSPECT_SELECTORS,
    INTERACTIONS,
    KNOWN_NOISE_SUBSTRINGS,
    QUICK_ROUTES,
    QUICK_VIEWPORTS,
    ROUTE_DEPENDENCIES,
    ROUTE_GLOBAL_GLOBS,
    ROUTES,
    THEME_ORDER,
    VIEWPORTS,
    A11ySuppression,
    Interaction,
    Route,
    Viewport,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / "tmp"
SNAPS_DIR = TMP_DIR / "snaps"
DIFFS_DIR = TMP_DIR / "diffs"
BLUEPRINTS_DIR = TMP_DIR / "snap-blueprints"
BASELINE_DIR = REPO_ROOT / "tests" / "visual-baseline"
ALLOWLIST_PATH = BASELINE_DIR / "heuristics-allowlist.json"


# ---------------------------------------------------------------------------
# ANSI helpers (kept local to avoid pulling in colorama). bin/check.py uses
# the same convention.
# ---------------------------------------------------------------------------
def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


_C = _supports_color()
GREEN = "\033[32m" if _C else ""
RED = "\033[31m" if _C else ""
YELLOW = "\033[33m" if _C else ""
DIM = "\033[2m" if _C else ""
RESET = "\033[0m" if _C else ""


# ---------------------------------------------------------------------------
# Theme + blueprint discovery
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Framework-wide invalidation allowlist.
#
# Narrow set of files whose changes MUST invalidate every theme's snaps (as
# opposed to the older "any bin/* touch invalidates everything" heuristic,
# which over-shot by re-running the entire visual matrix whenever an
# unrelated tooling script like bin/audit-concepts.py or
# bin/build-snap-gallery.py was edited). At 100 themes that over-shoot is
# hours of compute per push, so we keep the list minimal and rely on the
# nightly `nightly-snap-sweep.yml` run (Phase 4) to catch any false
# negative within 24 hours.
#
# Inclusion criteria: a file is here only if editing it can visibly change
# the rendered page for any theme. Examples:
#   * bin/snap.py, bin/snap_config.py — drive the capture itself (viewport
#     sizes, freeze CSS, heuristic engine). A bug here shifts every pixel.
#   * bin/append-wc-overrides.py — rewrites every theme's theme.json with
#     WooCommerce-block CSS overrides.
#   * bin/sync-playground.py — inlines playground/*.php into every
#     blueprint; blueprint content seeding changes user-visible fixtures.
#   * bin/_lib.py — shared GITHUB_ORG / REPO constants used by
#     _retarget_content_ref and others.
#   * package.json / package-lock.json — pins @wp-playground/cli, whose
#     version changes the underlying WP/WC behavior and auto-invalidates
#     tmp/playground-state/ via the version marker in boot_server.
#   * playground/ at the repo root — shared playground/*.php scripts that
#     every theme's blueprint inlines via sync-playground.py.
#
# Explicitly NOT on this list: bin/build-*.py, bin/audit-*.py,
# bin/extract-*.py, bin/check*.py (static), bin/paint-*.py, bin/spec-*.py,
# documentation generators, concept-pipeline helpers — they don't touch
# the runtime that produces the PNGs.
# ---------------------------------------------------------------------------
SNAP_AFFECTING_FRAMEWORK_FILES: frozenset[str] = frozenset({
    "bin/snap.py",
    "bin/snap_config.py",
    "bin/append-wc-overrides.py",
    "bin/sync-playground.py",
    "bin/_lib.py",
    "package.json",
    "package-lock.json",
})

# Path prefixes whose children are all framework-affecting. Matched with
# startswith() against each git-diff path (POSIX-separated).
SNAP_AFFECTING_FRAMEWORK_PREFIXES: tuple[str, ...] = (
    "playground/",  # shared playground/*.php inlined into every blueprint
)


def _is_framework_file(path: str) -> bool:
    """True iff the path belongs to the narrow framework-files allowlist.

    Split out as a module-level helper so both `_changed_themes` and the
    unit tests can drive the classifier without subprocess-ing git.
    """
    if path in SNAP_AFFECTING_FRAMEWORK_FILES:
        return True
    return any(path.startswith(prefix) for prefix in SNAP_AFFECTING_FRAMEWORK_PREFIXES)


def _changed_themes(base: str | None = None) -> list[str] | None:
    """Return the subset of themes affected by uncommitted + base..HEAD
    git changes.

    Returns:
      None             -> framework changed (see `_is_framework_file`);
                          the caller should fall back to "all themes".
      []               -> nothing relevant changed; nothing to shoot.
      ["obel", ...]    -> only those themes need a reshoot.

    Path mapping (theme dir IS the git root):
      <theme>/**                       -> theme is affected
      tests/visual-baseline/<theme>/** -> theme is affected
      framework allowlist (narrow)     -> all themes; see
                                          SNAP_AFFECTING_FRAMEWORK_FILES
                                          / _PREFIXES above
      anything else                    -> no theme affected (including
                                          unrelated bin/* tooling edits
                                          — the nightly sweep catches any
                                          false negative within 24h)

    Stage visibility: we include BOTH shipping AND incubating themes in
    the `known` set so a PR that modifies a WIP-new theme still triggers
    quick-visual / vision-review matrix population. The default
    ``discover_themes()`` call (shipping only) is the right answer for
    --all fan-outs but the wrong answer for "what changed on THIS PR" —
    a new theme starts at incubating (see `bin/clone.py`) and would
    otherwise be invisible to every per-PR gate until it was promoted
    via `first-baseline.yml`, creating a chicken-and-egg cycle.
    """
    known = set(discover_themes(stages=("shipping", "incubating")))
    paths = _diff_paths(base)
    if paths is None:
        # git not installed -- can't be smart, fall back to "all".
        return None
    if not paths:
        return []

    affected: set[str] = set()
    for p in paths:
        parts = p.split("/")
        head = parts[0]
        if head in known:
            affected.add(head)
            continue
        if head == "tests" and len(parts) >= 3 and parts[1] == "visual-baseline":
            if parts[2] in known:
                affected.add(parts[2])
            continue
        # Narrow framework-level allowlist: only files that can actually
        # shift rendered pixels for every theme. Editing unrelated bin/*
        # tooling (audit scripts, doc generators) no longer triggers a
        # full all-themes reshoot -- the nightly sweep is the safety net.
        if _is_framework_file(p):
            return None
    return sorted(affected)


def _diff_paths(base: str | None) -> set[str] | None:
    """Return the set of POSIX paths touched by uncommitted + base..HEAD
    changes, or None if git is unavailable.

    Shared helper between `_changed_themes` (theme-level scope) and
    `_changed_routes` (route-level scope within a theme). Keeping both
    callers on the same diff source guarantees the two classifications
    agree: a theme that appears in `_changed_themes` will have at least
    one path visible to `_changed_routes`.
    """
    paths: set[str] = set()
    try:
        for cmd in (
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            r = subprocess.run(
                cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
            )
            if r.returncode == 0:
                paths.update(p for p in r.stdout.splitlines() if p)
        if base:
            r = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                cwd=REPO_ROOT, capture_output=True, text=True, check=False,
            )
            if r.returncode == 0:
                paths.update(p for p in r.stdout.splitlines() if p)
    except FileNotFoundError:
        return None
    return paths


def _match_glob(rel_path: str, glob: str) -> bool:
    """Return True iff rel_path matches the glob.

    `rel_path` is relative to a theme root (e.g. "templates/single-product.html").
    `glob` is a snap_config pattern (e.g. "patterns/product-*.html" or
    "styles/**").

    Semantics (deliberately narrower than fnmatch):
      * `**` (as a whole path segment) matches any number of path
        segments, including zero. Only legal as a full segment.
      * `*` matches one or more characters WITHIN a single segment
        (never eats `/`). This is the crucial difference from
        fnmatch.translate, which would let `patterns/*.html` match
        `patterns/foo/bar.html`.
      * `?` matches exactly one non-`/` character.
      * Everything else is literal, case-sensitive.

    We hand-roll the translator because:
      * fnmatch collapses `**` into `*` and lets `*` cross `/`.
      * pathlib.PurePath.match can't cross segment boundaries at all.
      * pathspec / wcmatch would be fine but we don't want a new dep.
    """
    import re

    def _translate_segment(part: str) -> str:
        out: list[str] = []
        for ch in part:
            if ch == "*":
                # Match non-empty run of non-slash chars (so `product-*`
                # requires at least one char after the hyphen and never
                # crosses directory boundaries).
                out.append("[^/]*")
            elif ch == "?":
                out.append("[^/]")
            else:
                out.append(re.escape(ch))
        return "".join(out)

    parts = glob.split("/")
    regex_parts: list[str] = []
    for part in parts:
        if part == "**":
            regex_parts.append("(?:.*)")
        else:
            regex_parts.append(_translate_segment(part))
    # Join segments with escaped `/`; for `**` we also need to allow
    # the trailing slash to be absorbed (so `styles/**` matches
    # `styles/winter.json`). Easiest impl: post-process the joined
    # pattern to collapse `/(?:.*)/` or trailing `/(?:.*)` robustly.
    pattern = "/".join(regex_parts)
    # `styles/**` should match `styles/foo` AND `styles/foo/bar`:
    # the literal `/` between `styles` and `**` is already in the
    # joined pattern. `(?:.*)` handles any-or-zero chars after that.
    # `foo/**/bar` (zero-segment case) needs `/(?:.*/)?` -- handle it
    # by replacing `/(?:.*)/` with `/(?:[^/]+/)*(?:[^/]+/)?` ... no,
    # simpler: replace `**` sub-pattern with `.*` and allow the
    # surrounding `/` to be either present or absorbed. The manifest
    # only uses `**` at the end of a pattern (`styles/**`,
    # `playground/**`) so we don't need the mid-glob case.
    full_pattern = "^" + pattern + "$"
    return re.match(full_pattern, rel_path) is not None


def _changed_routes(theme: str, base: str | None = None) -> set[str] | None:
    """Return the set of route slugs touched by the diff within `theme`.

    Returns:
      None            -> a ROUTE_GLOBAL_GLOBS file changed (header,
                         footer, theme.json, styles/**, blueprint
                         content, etc.) OR a framework file changed;
                         the caller should treat every route as stale.
      set()           -> the theme appears in the diff but only through
                         files that don't map to any known route; the
                         caller should treat every route as stale
                         defensively (file-outside-manifest is the same
                         risk as an unknown global).
      {"shop", ...}   -> exactly those route slugs depend on a file in
                         the diff.

    This is the per-theme companion to `_changed_themes`; together they
    let `cmd_shoot --auto-routes` narrow a fan-out to just the cells
    that could visibly have changed.
    """
    paths = _diff_paths(base)
    if paths is None:
        return None

    theme_prefix = f"{theme}/"
    # Relative-to-theme paths, e.g. "templates/home.html".
    rel_paths: list[str] = []
    for p in paths:
        if _is_framework_file(p):
            # Framework edit invalidates every theme's every route.
            return None
        if p.startswith(theme_prefix):
            rel_paths.append(p[len(theme_prefix):])
        # Paths under `tests/visual-baseline/<theme>/` don't carry
        # route dependency semantics -- they ARE the expected output,
        # not an input. Treat as no-op for route narrowing.

    if not rel_paths:
        return set()

    # Global invalidation check first: any global glob means every route.
    for rel in rel_paths:
        for glob in ROUTE_GLOBAL_GLOBS:
            if _match_glob(rel, glob):
                return None

    # Per-route match. A single rel_path can contribute to multiple
    # routes (e.g. templates/single-product.html feeds both
    # product-simple and product-variable).
    touched: set[str] = set()
    unmapped: list[str] = []
    for rel in rel_paths:
        matched_any = False
        for route_slug, globs in ROUTE_DEPENDENCIES.items():
            for glob in globs:
                if _match_glob(rel, glob):
                    touched.add(route_slug)
                    matched_any = True
                    break
        if not matched_any:
            unmapped.append(rel)

    if unmapped:
        # An edit to a theme-root file we don't have a manifest entry
        # for -- could be a brand-new template, a pattern we haven't
        # categorized, or just a README. Degrade gracefully to "shoot
        # every route" so we never ship a regression because of a
        # manifest gap. Fix the manifest when this shows up repeatedly.
        return None

    return touched


# ---------------------------------------------------------------------------
# Phase 2: per-(theme, viewport, route) signature stamps.
#
# The signature file lives alongside each baseline PNG at
# `tests/visual-baseline/<theme>/<vp>/<slug>.sig.json` and records the
# exact inputs that produced that baseline. Before shoot_theme opens
# Playwright we recompute the signature for the current HEAD and
# compare; a match means the rendered page CANNOT have changed, so we
# copy the baseline into tmp/snaps/ and skip the capture entirely.
# A mismatch (or missing sig / baseline) falls through to the normal
# shoot path, which then writes a fresh sig.json into tmp/snaps/ so
# `bin/snap.py baseline` can promote it alongside the new PNG.
#
# Contents:
#   * deps[]    -- every file under ROUTE_DEPENDENCIES[slug] and
#                  ROUTE_GLOBAL_GLOBS that exists in the theme, with
#                  its sha256. Order-stable for diff-friendliness.
#   * snap_py_sha / snap_config_sha
#                  -- hashes of the capture engine + its config. A
#                  bug in either can shift every pixel, so a change
#                  invalidates every signature.
#   * playground_cli -- the pinned @wp-playground/cli spec. Bumping
#                  the CLI changes the underlying WP/WC runtime and
#                  therefore what paints; auto-invalidates all sigs.
#
# Intentionally NOT in the signature:
#   * Playwright pin -- already covered by snap.py (we'd update its
#                  hard-coded version constants in the same commit
#                  that bumps the install). One less file to hash.
#   * machine identifiers / mtimes -- signatures must be reproducible
#                  across runners, local machines, and CI.
# ---------------------------------------------------------------------------
_SIG_VERSION = 1  # bump to force a mass re-shoot on schema changes


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _collect_dep_paths(theme: str, route_slug: str) -> list[Path]:
    """Return the absolute paths of every existing file that matches the
    route's manifest entry + the global-glob list.

    We walk the theme's own subdirs and evaluate each file against the
    glob set. The walk is scoped to a small superset of relevant
    directories so we don't stat the whole theme tree on every shoot.
    """
    tdir = theme_dir(theme)
    globs: list[str] = list(ROUTE_GLOBAL_GLOBS)
    globs.extend(ROUTE_DEPENDENCIES.get(route_slug, ()))

    # Scan a narrow superset of candidate subdirs so we don't iterate
    # the entire theme tree (which can include heavy content bundles).
    candidate_dirs = [
        tdir,  # for files at theme root (theme.json, functions.php)
        tdir / "templates",
        tdir / "parts",
        tdir / "patterns",
        tdir / "styles",
        tdir / "playground",
    ]
    found: set[Path] = set()
    for d in candidate_dirs:
        if not d.is_dir():
            continue
        # For theme root we don't recurse (only direct children of tdir);
        # for everything else we do, so `styles/**` can pick up
        # `styles/variations/mono.json`.
        iterator = d.iterdir() if d == tdir else d.rglob("*")
        for fp in iterator:
            if not fp.is_file():
                continue
            try:
                rel = fp.relative_to(tdir).as_posix()
            except ValueError:
                continue
            for glob in globs:
                if _match_glob(rel, glob):
                    found.add(fp)
                    break

    return sorted(found, key=lambda p: p.relative_to(tdir).as_posix())


def compute_route_signature(theme: str, route_slug: str) -> dict:
    """Return a serializable signature for the (theme, route) inputs.

    The structure is stable (keys are inserted in deterministic order)
    so the signature can be serialized to JSON, committed alongside the
    baseline PNG, and compared byte-for-byte against a recomputed
    signature in a later run without worrying about key ordering.

    Missing inputs (e.g. a playground dir that doesn't exist on this
    theme) simply drop out of the list -- a signature for the same
    (theme, route) on a run where the file is still missing still
    matches. If a NEW file appears under one of the globs it becomes
    a new deps[] entry and invalidates the signature, which is the
    correct behavior: a new template affects the render.
    """
    tdir = theme_dir(theme)
    deps: list[dict] = []
    for fp in _collect_dep_paths(theme, route_slug):
        sha = _sha256_file(fp)
        if sha is None:
            continue
        deps.append({
            "path": fp.relative_to(tdir).as_posix(),
            "sha": sha,
        })

    snap_py_sha = _sha256_file(Path(__file__)) or ""
    snap_config_sha = _sha256_file(Path(__file__).resolve().parent / "snap_config.py") or ""
    try:
        cli_pin = _pinned_playground_cli_spec()
    except SystemExit:
        cli_pin = ""

    return {
        "version": _SIG_VERSION,
        "theme": theme,
        "route": route_slug,
        "deps": deps,
        "snap_py_sha": snap_py_sha,
        "snap_config_sha": snap_config_sha,
        "playground_cli": cli_pin,
    }


def _signature_path(theme: str, vp_name: str, route_slug: str,
                    root: Path | None = None) -> Path:
    base = root if root is not None else BASELINE_DIR
    return base / theme / vp_name / f"{route_slug}.sig.json"


def _baseline_png_path(theme: str, vp_name: str, route_slug: str) -> Path:
    return BASELINE_DIR / theme / vp_name / f"{route_slug}.png"


def _tmp_cell_paths(theme: str, vp_name: str, route_slug: str) -> dict[str, Path]:
    base = SNAPS_DIR / theme / vp_name
    return {
        "dir": base,
        "png": base / f"{route_slug}.png",
        "findings": base / f"{route_slug}.findings.json",
        "sig": base / f"{route_slug}.sig.json",
        "html": base / f"{route_slug}.html",
        "a11y": base / f"{route_slug}.a11y.json",
    }


def _load_sig(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _signatures_equal(a: dict, b: dict) -> bool:
    """Semantic equality for signature dicts.

    Compares every key EXCEPT any future additive metadata (timestamps,
    runner id) we might want to stash later. Today the dicts are
    identical-shape so we can just ==, but we encode the comparison
    via explicit keys for forward compatibility.
    """
    fields = ("version", "theme", "route", "snap_py_sha",
              "snap_config_sha", "playground_cli")
    for f in fields:
        if a.get(f) != b.get(f):
            return False
    # deps[] compared as sets of (path, sha) tuples so we don't care
    # about list ordering (we write sorted, but a hand-edited baseline
    # sig shouldn't re-shoot just because ordering drifted).
    da = {(d.get("path"), d.get("sha")) for d in (a.get("deps") or [])}
    db = {(d.get("path"), d.get("sha")) for d in (b.get("deps") or [])}
    return da == db


def _should_skip_cell(theme: str, vp_name: str, route_slug: str,
                     current_sig: dict) -> bool:
    """True iff we can reuse the baseline PNG for this cell.

    Both halves must be present: the baseline PNG (so there's
    something to copy) and a matching signature file (so we've proved
    the inputs are unchanged). Either missing -> shoot.
    """
    if os.environ.get("FIFTY_FORCE_RESHOOT") == "1":
        return False
    png = _baseline_png_path(theme, vp_name, route_slug)
    if not png.is_file():
        return False
    sig_path = _signature_path(theme, vp_name, route_slug)
    stored = _load_sig(sig_path)
    if stored is None:
        return False
    return _signatures_equal(stored, current_sig)


def _materialize_skipped_cell(theme: str, vp_name: str, route_slug: str,
                              current_sig: dict) -> None:
    """Copy baseline PNG into tmp/snaps/ and emit a skip-stub findings.json.

    After this runs the cell looks -- from the aggregator's perspective
    -- exactly like a freshly-shot cell with no findings to report:
      * tmp/snaps/<theme>/<vp>/<slug>.png       (byte copy of baseline)
      * tmp/snaps/<theme>/<vp>/<slug>.findings.json (skip-stub)
      * tmp/snaps/<theme>/<vp>/<slug>.sig.json  (current signature)

    The findings stub uses `skipped_via_signature: true` so `bin/snap.py
    report` and `bin/check.py` can tell a deliberately-skipped cell
    apart from a shoot that ran and found nothing. Empty lists for
    findings/console/page_errors/network_failures satisfy the evidence
    gate's shape checks.

    A baseline-side findings.json (written by a future `cmd_baseline`
    that promotes findings alongside PNGs) is PREFERRED over the stub:
    if the signature matches, the findings the theme currently carries
    are by definition the last-shot findings for this exact input set.
    """
    paths = _tmp_cell_paths(theme, vp_name, route_slug)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    src_png = _baseline_png_path(theme, vp_name, route_slug)
    shutil.copy2(src_png, paths["png"])

    # Prefer promoted baseline findings/a11y/html if they exist --
    # those represent the true last-captured state for these inputs.
    # Fall through to a stub when the baseline tree predates Phase 2.
    baseline_root = BASELINE_DIR / theme / vp_name
    baseline_findings = baseline_root / f"{route_slug}.findings.json"
    if baseline_findings.is_file():
        shutil.copy2(baseline_findings, paths["findings"])
    else:
        stub = {
            "theme": theme,
            "viewport": vp_name,
            "route": route_slug,
            "skipped_via_signature": True,
            "findings": [],
            "console": [],
            "page_errors": [],
            "network_failures": [],
        }
        paths["findings"].write_text(
            json.dumps(stub, indent=2), encoding="utf-8",
        )

    baseline_a11y = baseline_root / f"{route_slug}.a11y.json"
    if baseline_a11y.is_file():
        shutil.copy2(baseline_a11y, paths["a11y"])
    baseline_html = baseline_root / f"{route_slug}.html"
    if baseline_html.is_file():
        shutil.copy2(baseline_html, paths["html"])

    paths["sig"].write_text(
        json.dumps(current_sig, indent=2), encoding="utf-8",
    )

    # Touch the findings file so `check_evidence_freshness` sees it as
    # newer than any uncommitted theme source edits (otherwise the
    # freshness gate would fail on a skip-copy with a stale mtime from
    # the baseline). copy2 preserves mtime, which is wrong for this use.
    now = time.time()
    for key in ("png", "findings", "sig", "a11y", "html"):
        p = paths[key]
        if p.exists():
            try:
                os.utime(p, (now, now))
            except OSError:
                pass


def _write_sig_after_shoot(theme: str, vp_name: str, route_slug: str,
                           current_sig: dict) -> None:
    """Write the just-computed signature next to the freshly-shot PNG.

    Called from inside the shoot loop after Playwright has produced
    tmp/snaps/<theme>/<vp>/<slug>.png. On promotion via cmd_baseline
    the sig is copied into tests/visual-baseline/ alongside the PNG.
    """
    sig_path = SNAPS_DIR / theme / vp_name / f"{route_slug}.sig.json"
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    sig_path.write_text(json.dumps(current_sig, indent=2), encoding="utf-8")


def discover_themes(stages: Iterable[str] | None = None) -> list[str]:
    """Return theme slugs (folder names) that have a theme.json + blueprint.

    Honours snap_config.THEME_ORDER for stable ordering; any new theme
    folder discovered on disk is appended after the configured order.

    ``stages`` filters by readiness manifest (Tier 1.3):

      * ``None`` (default) -> ``DEFAULT_VISIBLE_STAGES`` (shipping
        only). Incubating themes are invisible to `shoot --all`,
        `diff --all`, `check --all`, so a WIP theme can't fail CI
        until its operator flips `readiness.json` to `shipping`.
      * ``()`` (empty tuple) -> EVERY theme regardless of stage.
        Used by the theme-status dashboard generator (Tier 2.2) and
        by operator tools that want to see the whole fleet including
        retired slugs.
      * explicit tuple -> only those stages. E.g. passing
        ``("shipping", "incubating")`` is how `design.py` opts a
        fresh clone into the visibility set while still iterating.

    A theme with no readiness.json is treated as ``stage="shipping"``
    (see ``_readiness.load_readiness``) for backward compat with the
    six original themes pre-manifest.
    """
    from _readiness import DEFAULT_VISIBLE_STAGES, load_readiness

    if stages is None:
        wanted: frozenset[str] | None = DEFAULT_VISIBLE_STAGES
    else:
        s = frozenset(stages)
        wanted = s if s else None

    have: set[str] = set()
    for p in REPO_ROOT.glob("*/theme.json"):
        if not (p.parent / "playground" / "blueprint.json").exists():
            continue
        if wanted is not None and load_readiness(p.parent).stage not in wanted:
            continue
        have.add(p.parent.name)

    ordered = [t for t in THEME_ORDER if t in have]
    extras = sorted(have - set(ordered))
    return ordered + extras


def theme_dir(theme: str) -> Path:
    return REPO_ROOT / theme


def blueprint_path(theme: str) -> Path:
    return theme_dir(theme) / "playground" / "blueprint.json"


# ---------------------------------------------------------------------------
# Blueprint mutation: produce a "snap blueprint" that uses local files.
# ---------------------------------------------------------------------------
def build_local_blueprint(theme: str, login: bool = False) -> Path:
    """Clone the theme's blueprint and strip the GitHub installTheme step.

    The original blueprint installs the theme from
        git:directory  https://github.com/RegionallyFamous/fifty  ref=main
    which is the right thing for the live demos but wrong for local
    iteration: it would pull whatever's on `main`, ignoring uncommitted
    edits. Our snap server starts with `--mount=<theme-dir>:/wordpress/
    wp-content/themes/<theme>` so the local files are present before
    activateTheme runs; all we need to remove is the installTheme step
    that would otherwise fail (target dir already populated by the mount)
    or, worse, succeed and overwrite our mount point.

    Anything else (plugin install, content seeding, wo-configure.php)
    stays identical to the live blueprint -- which is why the snap
    matches what users see at demo.regionallyfamous.com.

    `login=False` strips the blueprint's root-level `"login": true`. That
    field auto-issues an admin session via a runtime wp-cli login step,
    which (a) makes every screenshot include the 32px black admin bar
    along the top, ruining pixel-diff usefulness, (b) hides the real
    visible top of the theme, and (c) auto-fills checkout fields with
    admin@localhost.com so we lose the empty-form view real visitors
    see. `serve` overrides this and asks for login=True so the user can
    poke /wp-admin/.
    """
    src = blueprint_path(theme)
    if not src.exists():
        raise SystemExit(f"No blueprint at {src}")

    bp = json.loads(src.read_text(encoding="utf-8"))
    steps = bp.get("steps") or []

    # Strip installTheme; keep an `activateTheme` step in case one exists
    # separately, otherwise inject one because activation is what the
    # original installTheme step did via options.activate=true.
    new_steps = []
    had_install = False
    had_explicit_activate = False
    for step in steps:
        if not isinstance(step, dict):
            new_steps.append(step)
            continue
        if step.get("step") == "installTheme":
            had_install = True
            continue
        if step.get("step") == "activateTheme":
            had_explicit_activate = True
        new_steps.append(step)

    if had_install and not had_explicit_activate:
        # Insert activateTheme as the first step so the rest of the
        # blueprint (which assumes the theme is active, e.g. for
        # wo-configure.php's options) sees the right active stylesheet.
        new_steps.insert(
            0,
            {"step": "activateTheme", "themeFolderName": theme},
        )

    bp["steps"] = new_steps
    # `landingPage` may still be a deep link; for snap server we always
    # land on `/` so the boot probe in wait_for_server() succeeds quickly.
    bp["landingPage"] = "/"
    # See login docstring above; default to logged-out unless caller
    # explicitly opted in.
    if not login:
        bp.pop("login", None)
    else:
        bp["login"] = True

    BLUEPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    out = BLUEPRINTS_DIR / f"{theme}.json"
    payload = json.dumps(bp, indent=2)
    payload = _retarget_content_ref(payload)
    _preflight_content_url(theme, payload)
    out.write_text(payload, encoding="utf-8")
    return out


def _preflight_content_url(theme: str, blueprint_payload: str) -> None:
    """HEAD-check that the theme's `playground/content/products.csv`
    resolves at the content ref the blueprint is pointing at BEFORE
    Playground boots.

    Why: the closed-loop design flow scaffolds a fresh theme on `main`
    via `bin/clone.py`, then runs `bin/snap.py shoot <theme>` via
    `bin/design.py`. At that point, the theme directory exists locally
    but hasn't been pushed, so `raw.githubusercontent.com/.../main/
    <theme>/playground/content/products.csv` returns 404. Playground
    fetches the 404 body (14 bytes of "404: Not Found"), `wo-import.php`
    splits it into one line, and bails with "W&O CSV looked malformed:
    fewer than 2 lines after trim." The operator gets a cryptic
    `PHP.run() failed with exit code 1` 30 seconds after the boot
    started, with no hint that the root cause is "push the branch".

    This pre-flight does a 5-second HEAD request against the same URL
    the blueprint's `wo-import.php` will fetch. On 4xx/5xx or
    connection failure, we exit 2 with an actionable message before
    spinning up Playground. The check is best-effort — if the network
    itself is down we warn and continue (Playground runs offline for
    most steps; the content fetch may also be cached upstream).
    """
    import re
    import urllib.error
    import urllib.request

    # Pick any raw.githubusercontent.com URL under the theme's own
    # `<theme>/playground/` path. Prefer `content.xml` (an early-step
    # WXR import URL) because it's literal in the blueprint; fall back
    # to the base path. Either returning 404 means the theme dir isn't
    # present at the blueprint's content ref, which is all we need to
    # decide whether to abort.
    pattern = (
        r"https://raw\.githubusercontent\.com/[^/\"' ]+/[^/\"' ]+/[^/\"' ]+/"
        + re.escape(theme)
        + r"/playground/(?:content/content\.xml|content/products\.csv|)"
    )
    candidates = re.findall(pattern, blueprint_payload)
    # Prefer a concrete file URL over the bare base path.
    url = next(
        (u for u in candidates if u.endswith(".xml") or u.endswith(".csv")),
        candidates[0] if candidates else None,
    )
    if not url:
        # No theme-scoped content reference in the blueprint — nothing
        # to pre-flight (legacy / upstream-sourced themes).
        return
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Network trouble — don't block. Operator will see the real
        # failure if the content really can't be fetched.
        print(
            f"[snap] warn: preflight HEAD on {url} failed ({exc!r}); "
            "proceeding anyway.",
            file=sys.stderr,
        )
        return

    if status >= 400:
        # Derive the ref from the URL for a crisp hint.
        ref_match = re.search(
            r"raw\.githubusercontent\.com/[^/]+/[^/]+/([^/]+)/", url
        )
        ref = ref_match.group(1) if ref_match else "main"
        print(
            f"\n[snap] FATAL: {url} returns HTTP {status}.\n"
            f"  Playground's wo-import.php fetches this URL inside the "
            f"blueprint, and a 404 here produces the cryptic\n"
            f"  `W&O CSV looked malformed: fewer than 2 lines after "
            f"trim.` error that blocked the snap in the past.\n"
            f"\n"
            f"  The theme `{theme}` isn't present at ref `{ref}` on "
            f"GitHub yet. Three ways to fix:\n"
            f"    1. git add {theme}/ && git commit && git push   "
            f"(recommended for real runs)\n"
            f"    2. push the theme on a branch and "
            f"FIFTY_CONTENT_REF=<branch> bin/snap.py shoot {theme}\n"
            f"    3. FIFTY_CONTENT_REF=<commit-sha>   "
            f"(works on any pushed SHA)\n",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _auto_detect_content_ref() -> tuple[str | None, str]:
    """Work out what raw.githubusercontent ref the blueprint should use.

    Returns a ``(ref, source)`` tuple. ``ref`` is either a branch name, a
    commit SHA, or ``None`` when the default (``main``) should be kept.
    ``source`` is a short human-readable tag explaining how we picked it
    ("env", "branch", "main-default", "detached") used when we print a
    one-line banner so the operator knows which content set the snap is
    actually pointing at.

    Precedence:
        1. ``FIFTY_CONTENT_REF`` env var wins (CI sets this explicitly).
        2. If the current git branch is ``main``, use ``main``.
        3. Else, if the current branch has a pushed counterpart at
           ``origin/<branch>``, use that branch name (so re-pushing the
           same branch auto-invalidates Playground's cache).
        4. Else, keep ``main`` and print a hint — the caller is on an
           unpublished branch and raw.githubusercontent will serve main's
           copy of playground/ (which is correct for existing themes and
           404s for brand-new ones; the push step resolves either case).
    """
    import os
    import subprocess

    env_ref = os.environ.get("FIFTY_CONTENT_REF")
    if env_ref:
        return (env_ref, "env")

    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return (None, "no-git")

    if branch in ("HEAD", ""):
        return (None, "detached")
    if branch == "main":
        return ("main", "main-default")

    # Does origin know about this branch?
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        return (None, "unpublished")

    return (branch, "branch")


def _retarget_content_ref(payload: str, *, _verbose: bool = True) -> str:
    """Rewrite ``raw.githubusercontent.com/<org>/<repo>/main/`` URLs in
    the snap blueprint to point at a PR-branch SHA / branch name when
    the current checkout is on a non-main branch.

    Why this exists:
        Every blueprint inlines absolute raw.githubusercontent.com URLs
        for its WXR import + `WO_CONTENT_BASE_URL` PHP constants (see
        bin/sync-playground.py). Those are baked against the default
        branch (`main`) because that's where the live demo lives. But on
        a PR that *adds a new theme*, the theme's `playground/content/`
        and `playground/images/` haven't been merged to main yet — so
        when CI runs `bin/snap.py shoot <new-theme>` the Playground
        server hits a GitHub 404 for `products.csv`, parses the 404
        HTML page, and dies with "W&O CSV looked malformed".

        Setting `FIFTY_CONTENT_REF` (typically to `$GITHUB_SHA` on a PR
        runner) redirects every main-branch URL to that ref so the PR's
        own content is sideloaded. For local shoots we auto-detect the
        current branch via ``_auto_detect_content_ref`` so the operator
        doesn't have to remember to set the env var. That change fixed
        the single biggest "boot smoke failed on a new theme" footgun.

    The substitution is a pure text replace on the serialized blueprint
    so it catches both `"url": "..."` fields (importWxr) and URLs
    embedded inside PHP `"data"` strings (wo-import.php,
    wo-configure.php, wo-cart.php).
    """
    from _lib import GITHUB_ORG, GITHUB_REPO

    ref, source = _auto_detect_content_ref()
    if _verbose and source not in ("main-default",):
        if ref:
            print(
                f"[snap] content ref = {ref} (source: {source})",
                file=sys.stderr,
            )
        elif source == "unpublished":
            print(
                "[snap] content ref = main (current branch is not pushed; "
                "content URLs will point at main — push your branch to "
                "serve its own playground/ content)",
                file=sys.stderr,
            )

    if not ref or ref == "main":
        return payload
    src = f"raw.githubusercontent.com/{GITHUB_ORG}/{GITHUB_REPO}/main/"
    dst = f"raw.githubusercontent.com/{GITHUB_ORG}/{GITHUB_REPO}/{ref}/"
    return payload.replace(src, dst)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
def find_free_port(preferred: int = 9400) -> int:
    """Return a free TCP port, preferring the requested one."""
    for candidate in [preferred, *range(9400, 9500)]:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    raise SystemExit("No free port in 9400-9499 for the playground server.")


@dataclass
class Server:
    proc: subprocess.Popen
    port: int
    log_path: Path
    log_handle: object  # file handle being kept open for line-buffered writes

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _probe(url: str, timeout_s: float = 3.0) -> tuple[int, str] | None:
    """HEAD-style probe that returns (status, location) without following
    redirects. Returns None on connection error.

    We can't use urlopen() because it auto-follows redirects and raises
    on the install.php <-> / loop that WP serves during the brief window
    between WordPress download and blueprint completion. Treating that
    loop as a fatal "boot failure" was the bug in v1; here it's just
    "server is alive but blueprint hasn't finished yet, keep waiting".
    """
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def http_error_301(self, *a, **kw): return None
        def http_error_302(self, *a, **kw): return None
        def http_error_303(self, *a, **kw): return None
        def http_error_307(self, *a, **kw): return None
        def http_error_308(self, *a, **kw): return None

    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        # 4xx counts as "alive" -- the server processed our request,
        # blueprint just hasn't installed the route yet.
        return e.code, ""
    except (TimeoutError, urllib.error.URLError, ConnectionError):
        return None


# Sentinel string emitted by @wp-playground/cli's `server` command after
# (a) WordPress is installed, (b) the blueprint has finished executing
# every step, and (c) the server is accepting workers. Polling the
# server log for this is the most reliable "blueprint truly done" signal
# available -- HTTP probes only tell us that the server *accepts*
# requests (which happens earlier; WC may still be sideloading product
# images for another minute after the first 200 lands on /shop/).
#
# The CLI prints this after blueprint completion regardless of the
# blueprint's content, so it's a stable contract we can depend on
# without coupling to wo-configure.php internals. WP-CLI step output
# (like our wo-configure.php's `WP_CLI::success("W&O configure done.")`)
# does NOT make it to this stdout stream because it's captured by the
# wp-cli step runner inside the playground worker, not the cli host.
BLUEPRINT_DONE_MARKER = "Ready! WordPress is running on"

# Regex matching the wasm-runtime race that surfaces in
# ~1-in-2 cold boots of @wp-playground/cli. The CLI itself never
# recovers (the PHP worker is gone), but a fresh process started
# 1-16s later almost always succeeds. Phase 3 (`phase3-boot-retry`)
# of the closed-loop plan: detect this in the log, kill the dead
# server, exponential-backoff, retry.
import re as _re  # noqa: E402 -- intentional late import: this module's import block is alphabetized and adding `re` at the top would conflict with that ordering. The local-name alias keeps the module-level constant readable.

PLAYGROUND_RACE_RE = _re.compile(
    r"(PHP instance already acquired|Error: PHP instance already acquired)",
    _re.IGNORECASE,
)


class PlaygroundRaceError(RuntimeError):
    """Raised when @wp-playground/cli emits the PHP-instance race marker."""


def _log_text(server: Server) -> str:
    try:
        return server.log_path.read_text(errors="replace")
    except OSError:
        return ""


def _log_has_race(server: Server) -> bool:
    return bool(PLAYGROUND_RACE_RE.search(_log_text(server)))


def wait_for_server(server: Server, timeout_s: float = 600.0) -> None:
    """Two-phase wait for the playground server to be ready for screenshots.

    Phase 1: server is alive at all (any HTTP response counts).
    Phase 2: BLUEPRINT_DONE_MARKER has appeared in the server log.

    First-boot timeout is intentionally generous (default 10 min) because
    the chain is: npx download (~10s, cached after first run) → WP
    download (~5s) → 2 plugin installs (~10s) → WXR import (~5s) →
    wo-import.php sideloads ~30 product images from raw.githubusercontent
    (~60-180s on flaky networks) → wo-configure.php sideloads ~6 category
    images (~30-60s) → permalink flush. Cached subsequent boots typically
    complete in ~30s when the playground engine reuses its WP filesystem
    cache, otherwise reset back to first-boot duration.
    """
    start = time.monotonic()
    phase = "alive"
    last_status: tuple[int, str] | None = None
    while time.monotonic() - start < timeout_s:
        if server.proc.poll() is not None:
            tail = server.log_path.read_text(errors="replace")[-2000:]
            if PLAYGROUND_RACE_RE.search(tail):
                raise PlaygroundRaceError(
                    f"Playground server died from PHP-instance race "
                    f"(exit {server.proc.returncode})."
                )
            raise SystemExit(
                f"Playground server died during boot (exit "
                f"{server.proc.returncode}). Last log output:\n{tail}"
            )

        # Detect the race even when the wrapper process limps along
        # without exiting (the wasm worker is dead but the CLI hasn't
        # noticed yet). Catching this early saves the full 600s wait.
        if _log_has_race(server):
            raise PlaygroundRaceError(
                "Playground emitted PHP-instance race marker; aborting wait."
            )

        if phase == "alive":
            r = _probe(server.url + "/?_snap_probe=1")
            if r is not None:
                phase = "ready"
                print(f"  {DIM}server alive after "
                      f"{time.monotonic()-start:.0f}s "
                      f"(status {r[0]}); waiting for "
                      f"`{BLUEPRINT_DONE_MARKER}` in log…{RESET}",
                      flush=True)
        else:  # phase == "ready"
            # Read the blueprint log; once `W&O configure done.` appears
            # we know every product image, category image, and cart/
            # checkout option has been written. Until then keep waiting.
            try:
                log_data = server.log_path.read_text(errors="replace")
            except FileNotFoundError:
                log_data = ""
            if BLUEPRINT_DONE_MARKER in log_data:
                print(f"  {DIM}blueprint complete after "
                      f"{time.monotonic()-start:.0f}s.{RESET}", flush=True)
                # Final settle: WC's option cache and permalink rewrites
                # take a beat to flush after the last WP_CLI::success.
                time.sleep(3.0)
                return
            # Sanity-probe /shop/ to detect early server death (the log
            # marker would never appear if the runtime crashed).
            last_status = _probe(server.url + "/shop/")
        time.sleep(2.0)

    raise SystemExit(
        f"Playground server at {server.url} did not finish blueprint "
        f"within {timeout_s:.0f}s (last /shop/ probe: {last_status}). "
        f"Tail of log:\n"
        f"{server.log_path.read_text(errors='replace')[-3000:]}"
    )


def _pinned_playground_cli_spec() -> str:
    """Read the pinned @wp-playground/cli version from package.json so
    snap.py and `npm install` can never drift apart.

    Phase 3 (`phase3-pin-playground`) of the closed-loop plan: the
    `Error: PHP instance already acquired` race rate varies wildly by
    @wp-playground/cli release (it's a wasm-runtime bug). Running
    `npx --yes @wp-playground/cli@latest` meant every shoot could pull
    a different build, which made the race look intermittent when it
    was actually version-dependent. We now pin via package.json and
    fail loud if it's missing, so version bumps are explicit commits
    instead of silent npm-cache surprises.

    See package.json -> dependencies["@wp-playground/cli"]. To bump,
    edit package.json AND `config.playgroundCliVersion` together,
    then run `npm install` and re-shoot every theme to validate.
    """
    pkg_json = REPO_ROOT / "package.json"
    if not pkg_json.is_file():
        raise SystemExit(
            "package.json missing at repo root; cannot resolve the pinned "
            "@wp-playground/cli version. Restore it (Phase 3 of the closed-"
            "loop plan keeps this deliberately pinned to avoid the wasm "
            "PHP-instance race)."
        )
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        pinned = data["dependencies"]["@wp-playground/cli"]
    except (KeyError, json.JSONDecodeError) as e:
        raise SystemExit(
            f"package.json missing dependencies['@wp-playground/cli']: {e}"
        ) from e
    return f"@wp-playground/cli@{pinned}"


PLAYGROUND_STATE_DIR = TMP_DIR / "playground-state"


def _state_cache_dir(theme: str) -> Path:
    """Return the per-theme persistent /wordpress dir used by --cache-state.

    Phase 3 (`phase3-state-cache`) of the closed-loop plan. We mount
    `tmp/playground-state/<theme>/wordpress` -> `/wordpress` so that
    the seeded WordPress install (WXR import + WC product images +
    wo-configure.php options) survives across boots. Combined with
    `--wordpress-install-mode=install-from-existing-files-if-needed`,
    the second boot of a given theme is supposed to skip the slow
    blueprint setup steps entirely.

    Per-theme isolation is critical: cross-theme state leakage would
    silently bake the wrong theme's options into a shoot. The dir
    lives under `tmp/` so `git clean` can wipe it; `bin/snap.py
    serve --cache-state --reset-cache` also exposes a one-shot wipe.
    """
    return PLAYGROUND_STATE_DIR / theme / "wordpress"


def reset_state_cache(theme: str) -> Path:
    """Wipe the per-theme cache dir; return the path that was cleared."""
    target = PLAYGROUND_STATE_DIR / theme
    if target.exists():
        shutil.rmtree(target)
    return target


def boot_server(theme: str, port: int | None = None,
                verbosity: str = "normal", login: bool = False,
                cache_state: bool = False) -> Server:
    """Spawn `npx @wp-playground/cli@<pinned> server` and return the handle.

    The caller is responsible for shutting it down via `kill_server()`
    in a finally block. Logs are streamed to tmp/<theme>-server.log so
    failures can be diagnosed even after the process exits.

    `login=False` by default because the snap workflow targets
    logged-out screenshots (what real visitors see). Logging in injects
    the 32px WP admin bar across the top of every shot, which (a) shifts
    every other element down so pixel diffs trip on every cell, and
    (b) hides the actual top of the theme template. `serve` and ad-hoc
    debugging pass `login=True` so the user can poke at /wp-admin/.

    `cache_state=True` enables the Phase 3 state cache: a per-theme
    `tmp/playground-state/<theme>/wordpress` directory is mounted as
    `/wordpress` (via `--mount-before-install`) and
    `--wordpress-install-mode=install-from-existing-files-if-needed`
    is passed so the slow blueprint steps (WP install + WXR + WC
    seeder, ~100s of the 127s cold boot) skip on warm restart. First
    boot still runs the full blueprint and primes the cache.

    The CLI version is pinned via package.json (see
    `_pinned_playground_cli_spec`).
    """
    bp = build_local_blueprint(theme, login=login)
    chosen_port = port or find_free_port()
    mount_arg = f"{theme_dir(theme)}:/wordpress/wp-content/themes/{theme}"
    log_path = TMP_DIR / f"{theme}-server.log"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "wb")

    cmd = [
        "npx",
        "--yes",
        _pinned_playground_cli_spec(),
        "server",
        f"--port={chosen_port}",
        f"--blueprint={bp}",
        f"--mount={mount_arg}",
        f"--verbosity={verbosity}",
    ]
    if cache_state:
        cache_dir = _state_cache_dir(theme)
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Cache invalidation on CLI version bump: a fresh install done
        # by Playground CLI X is not guaranteed to work when later
        # booted under CLI Y (wasm runtime + SQLite integration plugin
        # can differ). We stamp the cache with the pinned CLI version
        # on prime and nuke-on-mismatch, so `npm install` is the only
        # action needed to get a clean cache after a version bump --
        # no extra `--reset-cache` hoop.
        version_marker = cache_dir.parent / "cli-version.txt"
        current_pin = _pinned_playground_cli_spec()  # e.g. "@wp-playground/cli@3.1.20"
        if cache_dir.is_dir() and (cache_dir / "wp-config.php").exists():
            prior = version_marker.read_text().strip() if version_marker.exists() else ""
            if prior and prior != current_pin:
                print(
                    f"  cache-state: CLI pin changed ({prior} -> {current_pin}); "
                    f"invalidating stale cache at {cache_dir}."
                )
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
        # Phase 3 (phase3-state-cache): per-theme warm cache.
        # ---------------------------------------------------
        # @wp-playground/cli 3.1.20 exposes two orthogonal flags:
        #
        #   --mount-before-install=<host>:<vfs>   bidirectional NODEFS
        #                                         mount attached BEFORE
        #                                         the WP install step.
        #   --wordpress-install-mode=<mode>       how to treat /wordpress
        #                                         at boot. Modes:
        #                                           download-and-install
        #                                             (default; fresh WP)
        #                                           install-from-existing-files-if-needed
        #                                             (skip install if
        #                                              /wordpress already
        #                                              looks set up)
        #                                           install-from-existing-files
        #                                           do-not-attempt-installing
        #
        # The earlier spike (see commit history for the phase3 spike
        # write-up) hit a failure when pairing `--mount-before-install=
        # <empty>` with `install-from-existing-files-if-needed`: the CLI
        # mis-identified the empty dir as a present install, skipped
        # setup, then aborted on SQLite. The fix is obvious in hindsight:
        # on first boot we just leave install-mode at the default
        # (download-and-install) and still mount the empty cache dir --
        # the fresh install writes straight THROUGH the mount into the
        # host cache dir (because --mount-before-install is NODEFS, not
        # a copy). After the first boot completes, the host dir contains
        # a live wp-config.php + /wp-content/ tree. Subsequent boots
        # detect the marker and add `install-from-existing-files-if-
        # needed` so WP + WXR + WC seeder all skip, amortizing the
        # ~127s cold boot down to ~20-30s of blueprint-free warm boot.
        #
        # Per-theme isolation is preserved because each theme gets its
        # own cache dir (see _state_cache_dir). --reset-cache wipes it.
        cache_marker = cache_dir / "wp-config.php"
        cmd.append(f"--mount-before-install={cache_dir}:/wordpress")
        if cache_marker.exists():
            cmd.append("--wordpress-install-mode=install-from-existing-files-if-needed")
            print(f"  cache-state: reusing populated cache at {cache_dir}")
        else:
            # Drop the CLI-version marker next to the cache dir so a
            # future `--cache-state` boot can detect a version mismatch
            # and self-invalidate. Writing it BEFORE the boot is safe
            # because the next validation read happens on a subsequent
            # process; if this boot fails mid-prime the marker just
            # points at an incomplete cache, which the wp-config.php
            # check above will still correctly refuse to reuse.
            try:
                version_marker.parent.mkdir(parents=True, exist_ok=True)
                version_marker.write_text(current_pin + "\n", encoding="utf-8")
            except OSError as e:
                print(f"  cache-state: warning: could not write version marker: {e}")
            print(
                f"  cache-state: cache at {cache_dir} is empty; priming "
                f"from a fresh install (bidirectional mount captures the "
                f"install into the host dir). Subsequent --cache-state "
                f"boots skip the WP install + plugin install (~40-100s "
                f"saved per boot)."
            )
    if login:
        cmd.append("--login")
    print(
        f"{DIM}>{RESET} {' '.join(cmd)}\n"
        f"{DIM}  log:{RESET} {log_path}",
        flush=True,
    )
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=REPO_ROOT,
    )
    return Server(proc=proc, port=chosen_port, log_path=log_path, log_handle=log_handle)


def kill_server(server: Server) -> None:
    if server.proc.poll() is None:
        server.proc.terminate()
        try:
            server.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.proc.kill()
            server.proc.wait(timeout=5)
    try:
        server.log_handle.close()
    except Exception:
        pass


@contextlib.contextmanager
def running_server(theme: str, port: int | None = None,
                   verbosity: str = "normal", login: bool = False,
                   cache_state: bool = False):
    """Context manager that boots, waits, and tears down."""
    server = boot_and_wait(
        theme, port=port, verbosity=verbosity, login=login,
        cache_state=cache_state,
    )
    try:
        yield server
    finally:
        kill_server(server)


# Backoff between PHP-instance-race retries. The tuple is indexed by
# (attempt - 1); attempts beyond the tuple length reuse the last value.
# 1s / 4s / 16s / 16s / 16s gives ~53s of sleep across the 4 gaps in a
# 5-attempt sequence, plus ~30-40s per actual boot attempt = ~3.5min
# worst-case before we give up. That fits comfortably inside the
# matrix shoot job's 25-minute timeout.
PLAYGROUND_RACE_BACKOFFS_S = (1.0, 4.0, 16.0, 16.0, 16.0)


def boot_and_wait(
    theme: str,
    *,
    port: int | None = None,
    verbosity: str = "normal",
    login: bool = False,
    max_attempts: int = 5,
    cache_state: bool = False,
) -> Server:
    """Boot Playground + wait for blueprint, retrying on the wasm race.

    Phase 3 (`phase3-boot-retry`) of the closed-loop plan. The
    `Error: PHP instance already acquired` race is reliably cleared
    by killing the dead worker and starting fresh; this wrapper
    automates that workaround so a 1-in-2 cold-boot failure rate
    stops being a session-killer.

    ``max_attempts`` defaults to 5 (was 3 until 2026-04). Three
    attempts proved insufficient on the matrix-per-theme cloud
    pipeline: a single bad-luck day on aero burned all three retries
    and failed the whole shoot. With per-attempt PHP-race rate of
    roughly 30 percent (estimated from the failure clusters we have
    seen), bumping to 5 attempts drops the all-fail probability from
    ~3 percent to ~0.2 percent — an order of magnitude better
    reliability for two extra ~40s attempts in the worst case.

    Non-race failures (network, blueprint timeout, exit code) still
    raise ``SystemExit`` immediately -- we only retry the specific
    failure mode known to be transient. Every attempt's log is left
    on disk so post-mortem still works.
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        server = boot_server(
            theme, port=port, verbosity=verbosity, login=login,
            cache_state=cache_state,
        )
        try:
            wait_for_server(server)
            # Final guard: blueprint reported "Ready!" but the race
            # marker also appears in the log (the wasm worker
            # crashed AFTER the marker fired). Treat as a race so
            # we retry rather than handing the caller a dead server.
            if _log_has_race(server):
                raise PlaygroundRaceError(
                    "PHP-instance race detected after blueprint completion."
                )
            return server
        except PlaygroundRaceError as e:
            last_err = e
            kill_server(server)
            if attempt >= max_attempts:
                break
            backoff = PLAYGROUND_RACE_BACKOFFS_S[
                min(attempt - 1, len(PLAYGROUND_RACE_BACKOFFS_S) - 1)
            ]
            print(
                f"  {YELLOW}race detected{RESET} on boot attempt "
                f"{attempt}/{max_attempts}; sleeping {backoff:.0f}s and retrying.",
                flush=True,
            )
            time.sleep(backoff)
        except SystemExit:
            kill_server(server)
            raise

    raise SystemExit(
        f"Playground failed to boot after {max_attempts} attempts due to "
        f"the PHP-instance race ({last_err}). Last log: "
        f"{(TMP_DIR / f'{theme}-server.log').relative_to(REPO_ROOT)}."
    )


# ---------------------------------------------------------------------------
# Capture (Playwright)
# ---------------------------------------------------------------------------
def filter_routes(slugs: Iterable[str] | None) -> list[Route]:
    if not slugs:
        return list(ROUTES)
    wanted = set(slugs)
    return [r for r in ROUTES if r.slug in wanted]


def filter_viewports(names: Iterable[str] | None) -> list[Viewport]:
    if not names:
        return list(VIEWPORTS)
    wanted = set(names)
    return [v for v in VIEWPORTS if v.name in wanted]


_FREEZE_CSS = """
/* Injected by bin/snap.py before every screenshot to suppress
   pixel-diff noise from animations, cursor blinks, scrollbars, and
   web fonts that haven't fully swapped yet. We DON'T disable
   scrollbars globally because doing so changes layout width on
   platforms that reserve scrollbar gutter; we just hide the visible
   thumb so that scroll position differences don't trip diffs. */
*, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    scroll-behavior: auto !important;
    caret-color: transparent !important;
}
::-webkit-scrollbar-thumb { background: transparent !important; }
/* WC mini-cart drawer mounting flicker: force collapsed during shots. */
.wc-block-mini-cart__drawer:not(.is-mobile) { display: none !important; }
"""


# JS run via page.evaluate() after navigation. Returns a serialisable
# dict of findings + per-selector measurements. Kept side-effect free
# (no clicks, no DOM mutation) so it doesn't change what the screenshot
# captures.
_HEURISTICS_JS = r"""
(args) => {
    const out = {findings: [], selectors: []};
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const isMobile = vw < 600;
    out.dom = {width: vw, height: vh,
               scrollWidth: document.documentElement.scrollWidth,
               scrollHeight: document.documentElement.scrollHeight};

    const push = (sev, kind, msg, extra) => out.findings.push(
        Object.assign({severity: sev, kind, message: msg}, extra || {})
    );

    // Visibility helper used by several detectors. "Visible-ish" means
    // it has size, isn't hidden by display/visibility, and is in (or
    // near) the viewport vertically. The 4000px below-fold tolerance
    // catches images that lazy-load below the fold but ARE present.
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        if (r.bottom < 0 || r.top > vh + 4000) return false;
        const cs = window.getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none'
            && cs.opacity !== '0';
    };

    // Build a stable-ish CSS selector for an element. Used as the
    // `selector` field on findings so the Python side can re-locate
    // the offender to crop a JPG of evidence, AND as the fingerprint
    // the allowlist matches against. Walks up the tree until either an
    // id is found or we hit body. Falls back to `tag.classes:nth-of-type`.
    const cssPath = (el) => {
        if (!(el instanceof Element)) return '';
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
            if (cur.id) {
                parts.unshift('#' + cur.id);
                break;
            }
            let part = cur.tagName.toLowerCase();
            if (cur.className && typeof cur.className === 'string') {
                const cls = cur.className.trim().split(/\s+/)
                    .filter(Boolean).slice(0, 2).join('.');
                if (cls) part += '.' + cls;
            }
            const parent = cur.parentNode;
            if (parent) {
                const sibs = Array.from(parent.children).filter(
                    (s) => s.tagName === cur.tagName
                );
                if (sibs.length > 1) {
                    part += `:nth-of-type(${sibs.indexOf(cur) + 1})`;
                }
            }
            parts.unshift(part);
            if (parts.length >= 5) break;
            cur = cur.parentElement;
        }
        return parts.join(' > ');
    };

    // Horizontal page overflow -- the body is wider than the viewport.
    // Anything > 1px is treated as accidental (browsers report 0 or 1
    // even on perfectly fitting pages depending on rounding).
    const overflow = document.documentElement.scrollWidth - vw;
    if (overflow > 1) {
        push("warn", "horizontal-overflow",
             `Document scrollWidth ${document.documentElement.scrollWidth}px exceeds viewport ${vw}px by ${overflow}px.`,
             {overflow_px: overflow});
    }

    // Visible WooCommerce error / info / success notices. These
    // surface server-side problems that don't appear in the JS console
    // (e.g. "product is out of stock" when the cart preload fails).
    const noticeSelectors = [
        ['.woocommerce-error', 'error', 'wc-error'],
        ['.woocommerce-info', 'warn', 'wc-info'],
        ['.woocommerce-message', 'info', 'wc-message'],
        ['.wc-block-components-validation-error', 'warn', 'wc-validation-error'],
        ['.wc-block-components-notice-banner.is-error', 'error', 'wc-banner-error'],
        ['.wc-block-components-notice-banner.is-warning', 'warn', 'wc-banner-warning'],
        ['.wc-block-components-notice-banner.is-info', 'info', 'wc-banner-info'],
        ['.wc-block-components-notice-banner.is-success', 'info', 'wc-banner-success'],
    ];
    for (const [sel, sev, kind] of noticeSelectors) {
        document.querySelectorAll(sel).forEach((el) => {
            const text = (el.innerText || '').trim().slice(0, 240);
            if (text) push(sev, kind, text, {selector: sel});
        });
    }

    // PHP/debug noise leaked into the page body.
    const debugRegex = /(Notice:\s|Warning:\s|Fatal error:|Parse error:|Deprecated:|Stack trace:|<br\s*\/>\s*<b>)/i;
    if (debugRegex.test(document.body.innerText || '')) {
        const m = (document.body.innerText.match(debugRegex) || [''])[0];
        push("error", "php-debug-output",
             `Page body contains PHP debug output (matched: ${m.trim()}).`);
    }

    // Untranslated/raw template tokens left in the rendered DOM.
    const rawToken = /__\(['"]/;
    if (rawToken.test(document.body.innerText || '')) {
        push("warn", "raw-i18n-token",
             "Page body contains a raw __() i18n token (string never translated).");
    }

    // WP default placeholder content. The fresh-install posts/pages
    // ("Hello world!", the boilerplate first post body, "Sample Page",
    // and the auto-draft Privacy Policy) are the loudest "this is a
    // default WordPress install" tell on a generated theme. They survive
    // the WXR import (it doesn't touch existing IDs) and the demo
    // home/journal pulls posts by date, so the placeholder routinely
    // lands as the third card on every theme. `playground/wo-configure.php`
    // purges them at boot; this heuristic is the runtime guard that
    // catches a regression before it ships.
    {
        const body = document.body.innerText || '';
        const wpDefaults = [
            ['Welcome to WordPress. This is your first post.', 'wp-default-hello-world-body'],
            ['Hello world!', 'wp-default-hello-world-title'],
            ['This is an example page. It\u2019s different from a blog post', 'wp-default-sample-page-body'],
            ['Sample Page', 'wp-default-sample-page-title'],
        ];
        for (const [needle, kind] of wpDefaults) {
            if (body.includes(needle)) {
                push("error", "wp-default-content",
                     `Page contains the WordPress installer placeholder "${needle.slice(0, 60)}\u2026" `
                     + `(matched: ${kind}). Default WP content survived the WXR import; `
                     + `playground/wo-configure.php must purge it. See AGENTS.md root rule on placeholder content.`,
                     {fingerprint: kind, needle: needle});
            }
        }
    }

    // Unstyled WC review-rating select. Product pages render a legacy
    // `<select id="rating" name="rating">` inside `#commentform` (from
    // `single-product-reviews.php`) that WC's classic frontend script
    // `wc-single-product.js` would normally hide and replace with a
    // `<p class="stars">` star-anchor widget on init. That script is
    // skipped on block themes (see
    // `plugins/woocommerce/includes/class-wc-frontend-scripts.php:527`),
    // so without the `review-stars-fallback` re-enqueue in each theme's
    // `functions.php` the shopper sees a raw native <select> with
    // "Rate…" as the placeholder option. Emit a warn-level finding when
    // both conditions hold simultaneously: the select is visible AND
    // the stars replacement has not been injected. The reviews <details>
    // must be open for this detector to fire, which the `reviews-open`
    // flow on `product-simple` guarantees.
    document.querySelectorAll('select#rating, select#rating-selector').forEach((sel) => {
        const r = sel.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        const cs = getComputedStyle(sel);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        if (sel.hasAttribute('hidden')) return;
        // Stars replacement may live as a prior sibling (classic
        // wc-single-product.js pattern: `<p class="stars">` is
        // prepended) or as a sibling `<p class="stars-wrapper">` (new
        // Interactivity-API product-review-form block). Either one
        // means the select was correctly replaced.
        const wrap = sel.closest('#commentform, .comment-respond, #review_form') || document;
        const starsReplacement = wrap.querySelector('p.stars, p.stars-wrapper, .stars-wrapper');
        const starsVisible = (() => {
            if (!starsReplacement) return false;
            const sr = starsReplacement.getBoundingClientRect();
            if (sr.width === 0 || sr.height === 0) return false;
            if (starsReplacement.hasAttribute('hidden')) return false;
            const scs = getComputedStyle(starsReplacement);
            return scs.display !== 'none' && scs.visibility !== 'hidden';
        })();
        if (starsVisible) return;
        push("warn", "unstyled-review-rating",
             "Review rating <select> is rendering as a native browser " +
             "dropdown with no `<p class=\"stars\">` replacement widget. " +
             "Enqueue the `wc-single-product` script on block-theme " +
             "product pages (see each theme's `functions.php` between " +
             "the `review-stars-fallback` sentinel markers).",
             {selector: cssPath(sel), id: sel.id});
    });

    // Images: missing alt + broken + oversized + responsive mismatch +
    // SVG placeholder leakage (a real product image was expected but a
    // grey placeholder shipped instead, which is the silent class of
    // "demo looks empty" bug).
    document.querySelectorAll('img').forEach((img) => {
        const r = img.getBoundingClientRect();
        const visible = r.width > 0 && r.height > 0 && r.bottom >= 0 && r.top <= vh + 4000;
        if (!visible) return;
        const src = img.currentSrc || img.src || '';
        if (img.complete && img.naturalWidth === 0) {
            push("error", "broken-image",
                 `Image failed to load: ${src}`, {src});
            return;  // no further size checks for a broken image
        }
        if (!img.hasAttribute('alt')) {
            push("warn", "img-missing-alt",
                 `Image has no alt attribute: ${src}`, {src});
        }
        if (img.naturalWidth > 4000) {
            push("info", "img-oversized",
                 `Image is ${img.naturalWidth}px wide natively (consider a smaller variant).`,
                 {src, natural_width: img.naturalWidth});
        }
        // Responsive mismatch: pick obvious over-/under-served
        // variants. We use 6x as the over-serve ceiling (DPR=2
        // retina + 3x art-direction/zoom slack) and 0.6x as the
        // under-serve floor.
        //
        // The over-serve ceiling was tuned in 4 stages:
        //   2026-03: 2x — universal noise (every retina image
        //              triggered, ~hundreds of findings)
        //   2026-04: 3x — still noisy; matched perceptual waste
        //              floor on non-retina (uncommon)
        //   2026-04: 4x — better but still flagged WC's default
        //              `woocommerce_thumbnail` (600px) used for
        //              category/shop product cards on mobile
        //              (120-127px slots = 4.7-5x natural-to-slot).
        //              Those are a WC-core config concern (the
        //              theme can't force WC to use a smaller
        //              thumbnail without `add_image_size` +
        //              custom block-size key), not a theme bug.
        //   2026-04: 6x — current. Silences WC-default-size cases
        //              while still catching genuine asset-pipeline
        //              waste (single image at 17x in a 60px tiny
        //              "you might also like" thumbnail slot).
        //              At 6x natural-to-slot on retina = 3x
        //              perceptual = ~9x byte waste, which IS the
        //              real "blurry zoom" floor.
        //
        // The under-serve
        // floor was 0.75x until 2026-04, but 0.6x matches the actual
        // perceptual threshold: a 1376px hero rendered into a 1920px
        // slot is 71.7% native — slightly upscaled but visually
        // indistinguishable on most non-retina displays. Real
        // "looks soft" only kicks in around 60% (1.67x upscale)
        // and below. Tightening to 0.6 silenced the last lysholm
        // hero image warning without hiding any actual blur cases.
        const renderedW = Math.round(r.width);
        if (renderedW >= 32 && img.naturalWidth > 0) {
            if (img.naturalWidth > renderedW * 6) {
                push("info", "responsive-image-overserved",
                     `Served ${img.naturalWidth}px wide for a ${renderedW}px slot (>6x; wasted bytes).`,
                     {src, natural_width: img.naturalWidth, rendered_width: renderedW});
            } else if (img.naturalWidth > 0
                       && img.naturalWidth < renderedW * 0.6) {
                push("warn", "responsive-image-blurry",
                     `Served ${img.naturalWidth}px wide for a ${renderedW}px slot (<0.6x; will look soft).`,
                     {src, natural_width: img.naturalWidth, rendered_width: renderedW});
            }
        }
        // Placeholder-image: a grey/SVG placeholder ended up where a
        // real product image was expected. WC sometimes does this when
        // the post-thumbnail meta is missing.
        const looksPlaceholder = (
            src.startsWith('data:image/svg+xml')
            || /placeholder|woocommerce-placeholder/i.test(src)
        );
        // Inside any product-image surface (gallery, card, summary).
        const inProductSurface = !!img.closest(
            '.wp-block-post-featured-image, '
            + '.woocommerce-product-gallery, '
            + '.wc-block-components-product-image, '
            + '.wp-block-woocommerce-product-image, '
            + '.wc-block-grid__product-image'
        );
        if (looksPlaceholder && inProductSurface) {
            push("warn", "placeholder-image",
                 `Placeholder image rendered where a product image was expected: ${src.slice(0, 120)}`,
                 {src});
        }
    });

    // Per-character word-wrap detector: an element whose intrinsic
    // text width is much greater than its rendered width usually means
    // its container collapsed below the text's minimum content width.
    // We sample headings + button text inside known sidebar selectors
    // because that's where the WC sidebar squeeze manifested ("CAR T
    // TOT ALS" rendered as four lines of 1-3 chars each).
    const sidebarLike = [
        '.wc-block-cart__sidebar', '.wc-block-checkout__sidebar',
        '.wc-block-components-sidebar-layout__sidebar', 'aside',
    ];
    sidebarLike.forEach((side) => {
        document.querySelectorAll(`${side} h1, ${side} h2, ${side} h3, ${side} button, ${side} a.wc-block-cart__submit-button`).forEach((el) => {
            const r = el.getBoundingClientRect();
            const text = (el.innerText || '').trim();
            if (!text || r.width < 1) return;
            // Element is squashed to near-zero width — that's a layout
            // collapse (parent grid track collapsed, or the container
            // is `display:none` waiting on a media query). Wrap-mid-
            // word is meaningless when the element has no width to
            // render text into; the real bug is the collapse, which
            // is caught by `region-void` / `element-overflow-x`. ~24
            // false positives/run on `<aside>` 7px-wide collapsed
            // sidebars.
            if (r.width < 32) return;
            // Author opted into mid-word breaking via overflow-wrap.
            // When the rendered token would not fit the box width
            // (e.g. very large hero font in a narrow sidebar),
            // overflow-wrap:anywhere/break-word is the *correct*
            // remedy — flagging it as a wrap-mid-word bug is noise.
            const cs = getComputedStyle(el);
            const ow = (cs.overflowWrap || cs.wordWrap || '').toLowerCase();
            if (ow === 'anywhere' || ow === 'break-word') return;
            // Approximate the intrinsic word width: the longest word's
            // pixel width if rendered on a single line.
            const longestWord = text.split(/\s+/).reduce((a,b) => a.length >= b.length ? a : b, '');
            if (longestWord.length < 4) return;
            // Use a temporary inline span to measure unbroken text.
            const probe = document.createElement('span');
            probe.style.cssText = 'position:absolute;left:-99999px;top:-99999px;white-space:nowrap;font:inherit;letter-spacing:inherit;';
            probe.textContent = longestWord;
            el.appendChild(probe);
            const probeWidth = probe.getBoundingClientRect().width;
            el.removeChild(probe);
            if (probeWidth > r.width + 2) {
                push("warn", "word-broken",
                     `"${text.slice(0,80)}" appears to wrap mid-word inside ${side} (longest token ${longestWord} measures ${Math.round(probeWidth)}px but element is ${Math.round(r.width)}px).`,
                     {selector: side, element_width: Math.round(r.width), token_width: Math.round(probeWidth)});
            }
        });
    });

    // Web-font load state. If the document.fonts API hasn't reached
    // 'loaded' by the time we screenshot, the page snapped while a
    // FOUT was still in progress -- the captured PNG is unstable and
    // pixel diffs will trip on the next run when the font finally
    // swaps. Most theme work uses self-hosted fonts so this should
    // virtually always be 'loaded'; flag it when not.
    try {
        if (document.fonts && document.fonts.status
                && document.fonts.status !== 'loaded') {
            push("warn", "font-not-loaded",
                 `document.fonts.status is "${document.fonts.status}" at screenshot time (FOUT risk).`,
                 {status: document.fonts.status});
        }
    } catch (e) { /* fonts API not available -- skip */ }

    // Tap-target sizing. WCAG 2.5.5 calls for a 44x44 minimum hit
    // area; we use 32x32 as the practical floor (the bar most modern
    // theme.json typography passes naturally). Mobile-only because
    // mouse pointers don't have the same fat-finger problem.
    if (isMobile) {
        const tapEls = document.querySelectorAll(
            'a[href], button:not(:disabled), [role="button"], '
            + 'input[type="submit"], input[type="button"], '
            + 'input[type="reset"], summary'
        );
        // Detect the canonical screen-reader-only pattern (1x1 clipped
        // box, often a skip-link or a sr-only label). These elements
        // are intentionally tiny so sighted users don't see them; they
        // grow on `:focus` (e.g. the WP "Skip to content" pattern). The
        // resting size isn't a real tap target -- focusing the link
        // expands it -- so flagging the 1x1px footprint is pure noise.
        const isScreenReaderOnly = (el, r, cs) => {
            // 1x1 box plus a clipping rule is the dead-giveaway
            // sr-only pattern. We accept either modern `clip-path`
            // (e.g. `inset(50%)`, `polygon(0 0, 0 0, 0 0, 0 0)`) or
            // the legacy `clip: rect(...)` form.
            const tinyBox = r.width <= 2 && r.height <= 2;
            const clipped = (cs.clipPath && cs.clipPath !== 'none')
                || (cs.clip && cs.clip !== 'auto');
            if (tinyBox && (clipped || cs.overflow === 'hidden')) return true;
            // Also catch the common `.screen-reader-text` /
            // `.visually-hidden` / `.sr-only` class names — even when
            // a theme implements them slightly differently, the intent
            // is unambiguous from the class name and we should not
            // flag the resting state.
            const cls = (el.className && el.className.baseVal) || el.className || '';
            if (typeof cls === 'string' && /\b(sr-only|screen-reader-text|visually-hidden|wp-block-skip-link|skip-link)\b/.test(cls)) return true;
            return false;
        };
        // A link is "inside a card hit area" when one of its
        // closest()-walk ancestors is itself either a clickable
        // element or a typical card/post wrapper that exposes its own
        // anchor. Tapping anywhere in that ancestor lands on the
        // product/post page; the inner text link is a secondary
        // affordance, not the real tap target.
        //
        // This catches the post-card / product-card pattern that fires
        // ~240 false findings/run: a 100x20 product-title <a>" Portable
        // Hole "</a> inside a `<li class="wp-block-post"><a class="wp-
        // block-post-title__link">` (or wp-block-product wrapper +
        // image link). The card itself is the real >=300x400 tap
        // target; complaining that the inner title link is "too
        // small" trains people to ignore the rule.
        const CARD_HIT_AREA = (
            'li.wp-block-post, '
            + '.wp-block-post, '
            + 'li.product, '
            + '.wp-block-product, '
            + '.wc-block-product, '
            + 'article'
        );
        const ancestorIsCardWithAnchor = (el) => {
            let p = el.parentElement;
            for (let depth = 0; p && depth < 5; depth += 1, p = p.parentElement) {
                if (!p.matches) continue;
                if (!p.matches(CARD_HIT_AREA)) continue;
                // Card must expose at least one OTHER anchor that
                // covers it (the image link or the title link sibling
                // of `el`). Without that, tapping the card body wouldn't
                // navigate anywhere.
                const anchors = p.querySelectorAll('a[href]');
                for (const a of anchors) {
                    if (a === el) continue;
                    const ar = a.getBoundingClientRect();
                    // Sibling anchor must be visible AND reasonably
                    // sized -- a 1x1 sr-only sibling doesn't make the
                    // card a real tap target.
                    if (ar.width >= 32 && ar.height >= 32) return true;
                }
            }
            return false;
        };
        // Stacked text-link list pattern. A `<li>` whose only anchor is
        // `el` AND whose effective height (offsetHeight + margin) is
        // >= 28px is a vertical list-of-links. The whole list-item line
        // is clickable on mobile (browsers extend the hit-test box to
        // the line box, not just the inline letterforms). Refusing to
        // skip these produces ~120 noise findings/run on journal recent-
        // posts widgets, footer link columns, and category nav lists.
        const isInBreadcrumbContainer = (el) => {
            // Breadcrumb anchors are by design inline xs-text links
            // separated by chevron glyphs (e.g. `wc-block-breadcrumbs`,
            // `woocommerce-breadcrumb`). Each item is a `<span>` /
            // `<li>` containing a single anchor measuring 12-22px tall.
            // Forcing them to a 32px tap row would make the breadcrumb
            // strip look comically tall (it is ALWAYS xs typography).
            // The accessibility win on touch is real but small — these
            // links have line-box hit areas extended by browsers and
            // sit inside a >= 32px-tall flex row when the breadcrumb
            // wraps. Treat them as "intentionally inline" navigation.
            for (let p = el.parentElement, depth = 0; p && depth < 5; p = p.parentElement, depth++) {
                if (!p.className) continue;
                const pcls = (p.className && p.className.baseVal) || p.className || '';
                if (typeof pcls !== 'string') continue;
                if (/breadcrumb/i.test(pcls)) return true;
            }
            return false;
        };
        const isLoneLinkInListItem = (el) => {
            // Walk up at most 4 levels looking for a block-like
            // ancestor that contains *only this anchor* and offers
            // a tap surface >= 28px tall. This catches:
            //   - bare links in li/dt/dd/p/h1-h6/td/th (vertical
            //     widget lists, footer columns, breadcrumb rows,
            //     WC cart + checkout summary product names)
            //   - product-title links inside <article>/<figure>/
            //     section card wrappers (cross-sells, related
            //     products, post grids, journal cards) where the
            //     entire card surrounding the title is the tap
            //     target the user actually engages with.
            let p = el.parentElement;
            for (let depth = 0; depth < 4 && p; depth++) {
                if (p.matches && (
                    p.matches('li, dt, dd, p, h1, h2, h3, h4, h5, h6, td, th')
                    || p.matches('article, figure, figcaption, section')
                    || (p.matches('[class*="card" i], [class*="product" i], [class*="post" i]')
                        && p.matches('div, span'))
                )) {
                    const anchors = p.querySelectorAll('a[href]');
                    if (anchors.length === 1) {
                        const ph = p.offsetHeight || p.getBoundingClientRect().height;
                        if (ph >= 28) return true;
                    }
                }
                p = p.parentElement;
            }
            return false;
        };
        tapEls.forEach((el) => {
            if (!isVisible(el)) return;
            const r = el.getBoundingClientRect();
            // Some links are inline runs of text (e.g. a footer link
            // inside a paragraph); the surrounding line gives the real
            // hit area. Skip elements whose text is wider than the
            // measured box (i.e. wrapped inline content).
            const cs = window.getComputedStyle(el);
            if (cs.display === 'inline' && r.width >= 32) return;
            if (isScreenReaderOnly(el, r, cs)) return;
            if (r.width < 32 || r.height < 32) {
                if (ancestorIsCardWithAnchor(el)) return;
                if (isLoneLinkInListItem(el)) return;
                if (isInBreadcrumbContainer(el)) return;
                const label = (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40);
                push("warn", "tap-target-too-small",
                     `Mobile tap target ${Math.round(r.width)}x${Math.round(r.height)}px (<32px) for "${label}".`,
                     {selector: cssPath(el), width: Math.round(r.width), height: Math.round(r.height), label});
            }
        });
    }

    // Text-overflow ellipsis that's actively truncating content. The
    // user is silently losing information; usually means the
    // surrounding container is too narrow.
    document.querySelectorAll('*').forEach((el) => {
        const cs = window.getComputedStyle(el);
        if (cs.textOverflow !== 'ellipsis') return;
        if (cs.overflow !== 'hidden') return;
        if (!isVisible(el)) return;
        if (el.scrollWidth > el.clientWidth + 1) {
            const txt = (el.innerText || '').trim().slice(0, 60);
            push("info", "text-overflow-truncated",
                 `Ellipsis is hiding content: "${txt}" (scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}).`,
                 {scroll_width: el.scrollWidth, client_width: el.clientWidth});
        }
    });

    // Empty landmarks. <main>, <nav>, <aside> with no visible text
    // usually mean a template fell through (block didn't render, query
    // returned 0 results) without anyone noticing.
    document.querySelectorAll('main, nav, aside').forEach((el) => {
        if (!isVisible(el)) return;
        // Some empty landmarks are deliberate (e.g. a <nav> whose only
        // visible content is icons) -- check for ANY visible text or
        // visible img inside before reporting.
        const text = (el.innerText || '').trim();
        const hasIcon = el.querySelector('img, svg, [role="img"]');
        if (text.length === 0 && !hasIcon) {
            push("info", "empty-landmark",
                 `<${el.tagName.toLowerCase()}> landmark has no visible text or media.`,
                 {tag: el.tagName.toLowerCase()});
        }
    });

    // ====================================================================
    // Theme content-correctness heuristics (the eight ERROR-tier checks
    // that catch overflow / duplicates / broken backgrounds / voids).
    // Each detector caps reports at 5 instances per page so a single
    // structural bug doesn't drown the findings list. All emit a stable
    // `selector` so the Python side can crop a JPG of the offender, AND
    // a `fingerprint` the allowlist matches against (the most invariant
    // identifier we can produce -- the selector for layout bugs, the
    // text+href tuple for duplicate-link bugs, and so on).
    // ====================================================================

    // 1. element-overflow-x: any visible element whose own content is
    // wider than its content box, while computed `overflow-x` says
    // `visible` -- i.e. the overflow is actually painted past the
    // box edge. Skips elements that opted into scrolling
    // (`auto`/`scroll`/`hidden`) and inline elements (line-box width
    // semantics make `scrollWidth > clientWidth` legitimate there).
    {
        let n = 0;
        const all = document.querySelectorAll('body *');
        for (const el of all) {
            if (n >= 5) break;
            if (!isVisible(el)) continue;
            const cs = window.getComputedStyle(el);
            if (cs.overflowX !== 'visible') continue;
            if (cs.display === 'inline') continue;
            // Skip very small elements (decorative icons etc) -- the
            // overflow has to be on something big enough to be visually
            // disruptive.
            const r = el.getBoundingClientRect();
            if (r.width < 50) continue;
            const overflow = el.scrollWidth - el.clientWidth;
            // Threshold is 5px (was 2px until 2026-04). 1-3px values
            // turn out to be almost entirely scrollbar-gutter and
            // sub-pixel-rounding artifacts from `position: fixed`
            // overlays that wrap a scrolling child (notably the
            // wc-block mini-cart drawer overlay, which fired ~250
            // identical 3px findings every snap run). Real layout
            // bugs spill by at least 5px and usually by tens-to-
            // hundreds of pixels (a textarea, a header search field,
            // an announcement bar).
            if (overflow <= 4) continue;
            // Skip the document root + body (already covered by
            // `horizontal-overflow`).
            if (el === document.body || el === document.documentElement) continue;
            // Decorative-overhang opt-out: when the only descendants
            // whose own right edge exceeds the parent's box are
            // `position:absolute|fixed`, the overflow is from a
            // deliberate badge/sticker placed past the edge (e.g.
            // chonk-hero__sticker with `right:-16px`). Treat as
            // intentional, not a layout bug.
            try {
                const elRect = el.getBoundingClientRect();
                const elRight = elRect.right;
                let foundFlowChild = false;
                let absOverhang = false;
                for (const child of el.querySelectorAll('*')) {
                    const cr = child.getBoundingClientRect();
                    if (cr.width === 0 || cr.height === 0) continue;
                    if (cr.right <= elRight + 1) continue;
                    const ccs = getComputedStyle(child);
                    if (ccs.position === 'absolute' || ccs.position === 'fixed') {
                        absOverhang = true;
                    } else {
                        foundFlowChild = true;
                        break;
                    }
                }
                if (absOverhang && !foundFlowChild) continue;
            } catch (e) { /* fall through */ }
            const sel = cssPath(el);
            const tag = el.tagName.toLowerCase();
            const txt = (el.innerText || '').trim().slice(0, 80);
            push("error", "element-overflow-x",
                 `<${tag}> content overflows its box by ${overflow}px (scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}). Text: "${txt}".`,
                 {selector: sel, fingerprint: sel,
                  overflow_px: overflow,
                  scroll_width: el.scrollWidth,
                  client_width: el.clientWidth});
            n += 1;
        }
    }

    // 2. heading-clipped-vertical: a heading whose rendered text is
    // taller than its own box (parent constrained the height with
    // `max-height` + `overflow: hidden`, hiding the second line of a
    // wrapped headline). We only check h1-h4 because longer prose
    // headings (h5/h6) are typically not styled with hard heights and
    // would produce noise.
    //
    // Threshold is 13px (was 4px until 2026-04, was 2px before that).
    // 4-12px overflow turned out to be almost entirely descender/glyph-
    // metric clipping — the bottom of "g","y","p" descending 5-9px
    // below the line-box baseline at tight 1.0-1.2 line-heights. A real
    // "missing line of text" bug clips by >= 1 full line-height (30-
    // 100+px depending on font-size), so 13px is the natural floor.
    // Pre-bump this kind contributed 42 of the gallery's 206 errors,
    // every one of them a visually-fine 5-12px descender shave on a
    // wrapped tablet headline. The line-height tunings in CSS Phase
    // U/V already pushed those down, but Theme baseline line-heights
    // dictate the residual clip and aren't worth fighting per-theme.
    {
        let n = 0;
        document.querySelectorAll('h1, h2, h3, h4').forEach((el) => {
            if (n >= 5) return;
            if (!isVisible(el)) return;
            const cs = window.getComputedStyle(el);
            // Skip the canonical screen-reader-only pattern. An h1
            // with `class="screen-reader-text"` (e.g. WP's hidden
            // checkout/cart page title) has clientHeight ~1px while
            // scrollHeight reflects the full text — guaranteed false
            // positive.
            const cls = (el.className && el.className.baseVal) || el.className || '';
            if (typeof cls === 'string' && /\b(sr-only|screen-reader-text|visually-hidden)\b/.test(cls)) return;
            // Same goes for any heading that is itself clipped via
            // clip / clip-path (the modern sr-only).
            if ((cs.clipPath && cs.clipPath !== 'none')
                || (cs.clip && cs.clip !== 'auto')) return;
            // Same goes for any heading nested under an SR-only
            // ancestor — the WC cart-line-items table renders a
            // `<caption class="screen-reader-text"><h2>Products in
            // cart</h2></caption>` per cart, and the visually-hidden
            // caption fires the detector on every cart route at
            // every viewport (~46 noise findings/run). The heading
            // is invisible to sighted users; clipping doesn't matter.
            let srAncestor = false;
            for (let p = el.parentElement; p; p = p.parentElement) {
                if (!p.className) continue;
                const pcls = (p.className && p.className.baseVal) || p.className || '';
                if (typeof pcls !== 'string') continue;
                if (/\b(sr-only|screen-reader-text|visually-hidden)\b/.test(pcls)) {
                    srAncestor = true;
                    break;
                }
            }
            if (srAncestor) return;
            const overflow = el.scrollHeight - el.clientHeight;
            if (overflow <= 12) return;
            const sel = cssPath(el);
            const tag = el.tagName.toLowerCase();
            const txt = (el.innerText || '').trim().slice(0, 80);
            // Empty headings can't really be "clipped" — they have no
            // visible glyphs. The reported scrollHeight > clientHeight
            // is a font-metrics ghost (the line-box still reserves
            // ascender + descender even with no text). Most often this
            // fires on the legacy WC reviews title `h2.woocommerce-
            // Reviews-title` which is left empty when there are zero
            // reviews — ~24 noise findings/run, all the same h2.
            if (txt.length === 0) return;
            push("error", "heading-clipped-vertical",
                 `<${tag}> "${txt}" is taller than its box by ${overflow}px (scrollHeight ${el.scrollHeight} > clientHeight ${el.clientHeight}). Likely a max-height + overflow:hidden parent eating part of the headline.`,
                 {selector: sel, fingerprint: sel,
                  overflow_px: overflow,
                  scroll_height: el.scrollHeight,
                  client_height: el.clientHeight});
            n += 1;
        });
    }

    // 3. button-label-overflow: a button-shaped element whose label is
    // wider than the button. Special-cased because button overflow is
    // uniquely jarring -- buttons have visible borders/backgrounds, so
    // text spilling out of them is impossible to miss.
    {
        let n = 0;
        const sel = (
            'button, '
            + 'a.wp-block-button__link, '
            + 'a.wc-block-cart__submit-button, '
            + 'a.wc-block-components-button, '
            + 'button.wc-block-components-button, '
            + 'button.wp-block-button__link, '
            + '[role="button"], '
            + 'input[type="submit"], '
            + 'input[type="button"]'
        );
        const buttons = document.querySelectorAll(sel);
        for (const el of buttons) {
            if (n >= 5) break;
            if (!isVisible(el)) continue;
            const overflow = el.scrollWidth - el.clientWidth;
            // 5px floor (was 1px until 2026-04). 1-4px overflow is
            // almost entirely sub-pixel rendering rounding +
            // glyph-metric quirks (e.g. WC mini-cart "3" badge digit
            // measuring 18.4px in a 16px box, or "ADD TO CART"
            // labels with 3px ascender spillover into padding).
            // Real "label spilling out the button" cases — the bug
            // this kind exists to catch — are >= 5px and usually
            // 10-30px (a long localised string in a button sized
            // for the English default). Pre-bump this kind contributed
            // 30+ findings/run, every one of them invisible to the
            // human eye on the rendered crop.
            if (overflow <= 4) continue;
            const cs = window.getComputedStyle(el);
            // A button with `overflow: hidden` AND `text-overflow: ellipsis`
            // is intentionally truncating -- the existing
            // `text-overflow-truncated` heuristic handles that case at
            // info severity. Skip here to avoid double-reporting.
            if ((cs.overflow === 'hidden' || cs.overflowX === 'hidden')
                && cs.textOverflow === 'ellipsis') continue;
            // A button whose computed white-space allows wrapping
            // (`normal`, `pre-wrap`, `pre-line`) AND whose container
            // is at least one line-height tall extra means the label
            // *can* wrap visibly to a 2nd line — the overflow is a
            // momentary single-line measurement before reflow. Skip
            // when the box already shows multiple line-boxes
            // (clientHeight > line-height * 1.5).
            const ws = (cs.whiteSpace || '').toLowerCase();
            if (ws === 'normal' || ws === 'pre-wrap' || ws === 'pre-line') {
                const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
                if (el.clientHeight > lh * 1.5) continue;
            }
            const path = cssPath(el);
            const txt = (el.innerText || el.value || '').trim().slice(0, 80);
            push("error", "button-label-overflow",
                 `Button label "${txt}" overflows its button by ${overflow}px (scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}).`,
                 {selector: path, fingerprint: path,
                  overflow_px: overflow,
                  label: txt});
            n += 1;
        }
    }

    // 4. duplicate-nav-block: two visible navigation containers whose
    // link sets are nearly identical (Jaccard >= 0.8). Catches the
    // real bugs:
    //   * primary menu accidentally rendered twice (footer pulling the
    //     header pattern, two wp-navigation blocks pointing at the same
    //     wp_navigation post, etc.)
    //   * mobile drawer + desktop primary nav both visible at the same
    //     viewport (responsive CSS forgot to hide one)
    //   * "Footer legal" row literally listing the same links as the
    //     "Help" footer column right above it
    //
    // Deliberately does NOT flag the case where one nav is a small
    // SUBSET of another (e.g. a "Company" footer column linking to
    // /about/, /journal/, /contact/ — which are all in the primary
    // nav too). That cross-link pattern is intentional footer design,
    // not a bug; flagging it produces hundreds of false positives
    // and trains people to ignore the rule.
    //
    // Container identity uses the OUTERMOST nav-shaped ancestor of
    // each candidate. Without that, `<header>` and the `<nav>` inside
    // it are treated as two separate containers, and every primary-nav
    // link is reported as a duplicate of itself.
    {
        const NAV_OUTER_SEL = 'header, nav, [role="navigation"]';
        const candidates = document.querySelectorAll(
            NAV_OUTER_SEL
            + ', .wp-block-navigation'
            + ', .wp-block-navigation__container'
            + ', .wp-block-navigation__responsive-container-content'
        );
        // Walk up from `el` to find the outermost nav-shaped ancestor.
        // (`closest()` returns the innermost match, which is the wrong
        // answer here; we want a `<header>` to subsume the `<nav>` it
        // wraps, not be considered a separate container.)
        function outermostNavAncestor(el) {
            let outer = el.matches(NAV_OUTER_SEL) ? el : null;
            for (let p = el.parentElement; p; p = p.parentElement) {
                if (p.matches && p.matches(NAV_OUTER_SEL)) outer = p;
            }
            return outer || el;
        }
        // For each outermost container, collect the SET of link sigs it
        // exposes. Use a Map keyed by the DOM element so duplicate
        // candidates (a `<nav>` and its `.wp-block-navigation` selector
        // hit) collapse to a single bucket.
        const containerSigs = new Map();      // outerEl -> Set<sig>
        const containerSamples = new Map();   // outerEl -> {text,href,sel} per sig
        const containerLabel = new Map();     // outerEl -> friendly label
        candidates.forEach((c) => {
            if (!isVisible(c)) return;
            const outer = outermostNavAncestor(c);
            if (!containerSigs.has(outer)) {
                containerSigs.set(outer, new Set());
                containerSamples.set(outer, new Map());
                const aria = outer.getAttribute && outer.getAttribute('aria-label');
                containerLabel.set(outer, aria || outer.tagName.toLowerCase());
            }
            const sigs = containerSigs.get(outer);
            const samples = containerSamples.get(outer);
            outer.querySelectorAll('a[href]').forEach((a) => {
                if (!isVisible(a)) return;
                const text = (a.innerText || a.textContent || '').trim();
                if (!text) return;
                const href = a.getAttribute('href') || '';
                // Sig is href-only: two navs that link to the same page
                // with different label text ("Shop" vs "All products"
                // both pointing at /shop/) ARE menu duplicates as far
                // as this rule cares.
                const sig = href;
                sigs.add(sig);
                if (!samples.has(sig)) {
                    samples.set(sig, {text, href, selector: cssPath(a)});
                }
            });
        });
        // Drop trivially small navs (<2 links): a "back to top" or
        // "view cart" lone-link container can't meaningfully be a
        // menu mirror.
        const containers = [];
        for (const [outer, sigs] of containerSigs.entries()) {
            if (sigs.size >= 2) {
                containers.push({outer, sigs,
                                 samples: containerSamples.get(outer),
                                 label: containerLabel.get(outer)});
            }
        }
        // Pairwise Jaccard. Threshold 0.8 catches identical sets and
        // near-identical (one extra link in either direction) without
        // flagging "footer column is a subset of primary nav".
        let n = 0;
        const seenPairs = new Set();
        for (let i = 0; i < containers.length && n < 5; i += 1) {
            for (let j = i + 1; j < containers.length && n < 5; j += 1) {
                const a = containers[i], b = containers[j];
                const intersection = new Set(
                    [...a.sigs].filter((s) => b.sigs.has(s))
                );
                if (intersection.size < 2) continue;
                const union = new Set([...a.sigs, ...b.sigs]);
                const jaccard = intersection.size / union.size;
                if (jaccard < 0.8) continue;
                const pairKey = a.label + '||' + b.label;
                if (seenPairs.has(pairKey)) continue;
                seenPairs.add(pairKey);
                const sharedHrefs = [...intersection].sort();
                const firstSig = sharedHrefs[0];
                const sample = a.samples.get(firstSig)
                    || b.samples.get(firstSig)
                    || {text: '?', href: firstSig, selector: ''};
                push("error", "duplicate-nav-block",
                     `Two visible navigation containers ("${a.label}" and "${b.label}") have nearly identical link sets (${intersection.size} of ${union.size} hrefs match, Jaccard ${jaccard.toFixed(2)}). Shared: ${sharedHrefs.slice(0, 6).join(', ')}${sharedHrefs.length > 6 ? ', …' : ''}. One is almost certainly a duplicate -- e.g. a footer "legal" row repeating the same links as a footer help column right above it, two wp-navigation blocks rendering the same wp_navigation post, or a mobile drawer that should be display:none at this viewport.`,
                     {selector: sample.selector,
                      fingerprint: 'pair:' + a.label + '|' + b.label,
                      label_a: a.label, label_b: b.label,
                      shared_count: intersection.size,
                      union_count: union.size,
                      jaccard: jaccard,
                      shared_hrefs: sharedHrefs});
                n += 1;
            }
        }
    }

    // 5. duplicate-h1: more than one visible <h1> on the page. A common
    // bug class is a template rendering BOTH the site title and the
    // post title as <h1>, or a hero pattern that hard-codes <h1> on a
    // page that already has one from the post template. We also flag
    // identical text across multiple h1s -- a softer signal of the same
    // template-double-render bug, surfaced separately for clarity.
    {
        const h1s = Array.from(document.querySelectorAll('h1'))
            .filter(isVisible);
        if (h1s.length > 1) {
            const samples = h1s.slice(0, 4).map((el) => {
                const txt = (el.innerText || '').trim().slice(0, 60);
                return `"${txt}"`;
            });
            push("error", "duplicate-h1",
                 `${h1s.length} visible <h1> elements on this page (samples: ${samples.join(', ')}). Pages should have exactly one <h1> for both SEO and a11y.`,
                 {selector: cssPath(h1s[1]),
                  fingerprint: 'count=' + h1s.length,
                  count: h1s.length});
        }
        // Identical-text double <h1>s warrant a separate, more pointed
        // finding (template re-render, not just "too many landmarks").
        const byText = new Map();
        h1s.forEach((el) => {
            const t = (el.innerText || '').trim();
            if (!t) return;
            (byText.get(t) || byText.set(t, []).get(t)).push(el);
        });
        for (const [text, els] of byText.entries()) {
            if (els.length < 2) continue;
            push("error", "duplicate-h1",
                 `Two visible <h1> elements have IDENTICAL text "${text.slice(0, 80)}" -- almost certainly the same template rendered twice on the page.`,
                 {selector: cssPath(els[1]),
                  fingerprint: 'text=' + text,
                  text: text, count: els.length});
            break;  // one is plenty; first occurrence describes the rest.
        }
    }

    // 6. background-image-broken: collect every visible element with a
    // computed `background-image: url(...)` and return the
    // (selector, url) pairs to the Python side, which intersects them
    // with the response listener's network failures (>= 400). We can't
    // probe load state here without going async, and the response
    // listener already has 100% network coverage -- so reuse it.
    out.bg_image_pairs = [];
    {
        const seen = new Set();
        const walk = document.querySelectorAll('body *');
        for (const el of walk) {
            if (!isVisible(el)) continue;
            const cs = window.getComputedStyle(el);
            const bg = cs.backgroundImage;
            if (!bg || bg === 'none') continue;
            // Extract every url(...) reference (multi-bg layers possible).
            const re = /url\((['"]?)([^'")]+)\1\)/g;
            let m;
            while ((m = re.exec(bg)) !== null) {
                const url = m[2];
                if (url.startsWith('data:')) continue;
                const key = url + '|' + cssPath(el);
                if (seen.has(key)) continue;
                seen.add(key);
                out.bg_image_pairs.push({
                    url: url,
                    selector: cssPath(el),
                });
                if (out.bg_image_pairs.length >= 200) break;
            }
            if (out.bg_image_pairs.length >= 200) break;
        }
    }

    // 7. region-void: a large visible element with NO content at all
    // (no text, no media, no background image) AND a background-color
    // that matches the body's -- i.e. the region renders as a chunk of
    // page-background void. This is the lysholm "transparent cover"
    // bug, generalized: any region where the cover/section block lost
    // its content AND lost its visual background, leaving a 1000px
    // gap of paper.
    {
        const bodyCS = window.getComputedStyle(document.body);
        const bodyBg = bodyCS.backgroundColor;
        const viewportArea = vw * vh;
        const allEls = document.querySelectorAll(
            'main *, [role="main"] *, body > div, body > section'
        );
        let n = 0;
        const reported = new Set();
        // The element BEING checked counts as media if it IS one of
        // these tags (querySelector below only checks descendants, so
        // an `<img>` itself trivially has no img descendant and would
        // otherwise be reported as a "void of page background"). The
        // earlier set was just descendants-only, which made every PDP
        // hero image fire region-void on every snap.
        const SELF_IS_MEDIA = new Set([
            'IMG', 'SVG', 'VIDEO', 'PICTURE', 'IFRAME', 'CANVAS', 'OBJECT', 'EMBED'
        ]);
        // Live-region overlays — the WC blocks toast/snackbar list
        // is rendered EMPTY-but-present at all times so screen readers
        // can announce notices added later. The empty container is
        // intentionally a "void" by design (full-viewport invisible
        // overlay). Same goes for any other ARIA live region or any
        // overlay positioned to occupy the viewport while transparent.
        const isOverlayPlaceholder = (el, cs) => {
            if (el.matches && el.matches(
                '[aria-live], [role="status"], [role="alert"], '
                + '.wc-block-components-notice-snackbar-list, '
                + '.wc-block-components-notices__snackbar, '
                + '.wp-block-woocommerce-store-notices, '
                // WC product-image inner containers are placeholders
                // that wrap an `<img>` whose `src` is set lazily by the
                // collection block. On first paint the inner container
                // is visible at full image dimensions but the `<img>`
                // hasn't materialised yet — we'd report it as a void
                // even though the next frame paints the image.
                + '.wc-block-components-product-image, '
                + '.wc-block-components-product-image__inner-container, '
                + '.wc-block-grid__product-image'
            )) return true;
            if ((cs.position === 'fixed' || cs.position === 'absolute')
                && cs.pointerEvents === 'none') return true;
            return false;
        };
        for (const el of allEls) {
            if (n >= 5) break;
            if (!isVisible(el)) continue;
            if (SELF_IS_MEDIA.has(el.tagName)) continue;
            // Inside a closed <details>, child content is hidden by
            // the browser but `getBoundingClientRect()` may still
            // report a non-zero rect at the collapsed location. The
            // content is genuinely not visible to the user — flagging
            // it as a "void of page background" is a guaranteed false
            // positive. (Bit our 80x-per-shoot wp-block-woocommerce-
            // product-reviews finding nested inside the PDP's
            // collapsed "Reviews" <details> on every snap.)
            const closedDetails = el.closest && el.closest('details');
            if (closedDetails && !closedDetails.open) continue;
            const r = el.getBoundingClientRect();
            const area = r.width * r.height;
            if (area < viewportArea * 0.15) continue;
            // Has any text?
            const txt = (el.innerText || '').trim();
            if (txt.length > 0) continue;
            // Has any media descendant?
            if (el.querySelector('img, svg, video, picture, iframe, canvas')) continue;
            // Has its own background image?
            const cs = window.getComputedStyle(el);
            if (cs.backgroundImage && cs.backgroundImage !== 'none') continue;
            if (isOverlayPlaceholder(el, cs)) continue;
            // Background-color matches body's -> renders as page void.
            // (transparent or rgba(0,0,0,0) also count as void since they
            // pass through to the body background.)
            const isVoidBg = (
                cs.backgroundColor === bodyBg
                || cs.backgroundColor === 'rgba(0, 0, 0, 0)'
                || cs.backgroundColor === 'transparent'
            );
            if (!isVoidBg) continue;
            // Skip if any ANCESTOR already reported (otherwise a void
            // <section> reports itself AND every nested wrapper inside it).
            let skip = false;
            let p = el.parentElement;
            while (p) {
                if (reported.has(p)) { skip = true; break; }
                p = p.parentElement;
            }
            if (skip) continue;
            reported.add(el);
            const sel = cssPath(el);
            push("error", "region-void",
                 `<${el.tagName.toLowerCase()}> at ${Math.round(r.width)}x${Math.round(r.height)}px (${Math.round(100 * area / viewportArea)}% of viewport) has no text, no media, and no background -- renders as a void of page-background. (The lysholm-style "cover lost its content" bug.)`,
                 {selector: sel, fingerprint: sel,
                  width: Math.round(r.width),
                  height: Math.round(r.height),
                  viewport_pct: Math.round(100 * area / viewportArea)});
            n += 1;
        }
    }

    // 8. region-low-density: a tall region (>40% of viewport height)
    // with very little content -- one floating word, one tiny icon.
    // Different from `region-void` (which catches NO content) -- this
    // catches "barely any content, surrounded by acres of whitespace,
    // that almost certainly looks broken at a glance." WARN tier
    // because this one false-positives on intentional hero compositions
    // more easily than `region-void`.
    {
        let n = 0;
        const reported = new Set();
        const allEls = document.querySelectorAll(
            'main > *, [role="main"] > *, '
            + 'main section, main > div > section'
        );
        // Editorial hero strips (wo-archive-hero, single-product
        // headline rows) are intentionally airy — a one-line eyebrow
        // + huge title + optional descriptor sit on top of large
        // padding to anchor the section, not to fill it. The detector
        // measures text *characters* and the hero serif headline is
        // 11-20 characters at huge type, scoring 0.04-0.05 by design.
        // Skip elements that opt-in to "this is a brand hero" via a
        // stable theme class name.
        const HERO_OPT_OUT = (
            '.wo-archive-hero, '
            + '.wo-account-intro, '
            + '.aero-hero, .chonk-hero, .lysholm-hero, '
            + '.obel-hero, .selvedge-hero'
        );
        for (const el of allEls) {
            if (n >= 5) break;
            if (!isVisible(el)) continue;
            if (el.matches && el.matches(HERO_OPT_OUT)) continue;
            const r = el.getBoundingClientRect();
            if (r.height < vh * 0.4) continue;
            // Skip ancestors already reported.
            let skip = false;
            let p = el.parentElement;
            while (p) {
                if (reported.has(p)) { skip = true; break; }
                p = p.parentElement;
            }
            if (skip) continue;
            const txt = (el.innerText || '').trim();
            const mediaCount = el.querySelectorAll(
                'img, svg, video, picture, iframe, canvas'
            ).length;
            // CSS background-image counts as visual media — themes
            // routinely paint hero / banner imagery via
            // `background-image` rather than `<img>` (the wo-archive-
            // hero "cover" variant uses the term thumbnail as a bg).
            // Without this check, every cover-style hero fires
            // region-low-density (one word + bg-image = "no media").
            const cs = window.getComputedStyle(el);
            const hasOwnBg = cs.backgroundImage && cs.backgroundImage !== 'none';
            // Density score: text characters + 50 per media element,
            // normalized to area in kilo-pixels. Threshold of 0.05
            // tuned to flag "one word in a 600px section" while
            // letting normal hero patterns (a paragraph + image)
            // through. Background-image carries the same content
            // weight as a media element.
            const areaKpx = (r.width * r.height) / 1000;
            const effectiveMedia = mediaCount + (hasOwnBg ? 1 : 0);
            const score = (txt.length + 50 * effectiveMedia) / Math.max(1, areaKpx);
            if (score >= 0.05) continue;
            // Skip "void" cases -- already covered by region-void above.
            if (txt.length === 0 && mediaCount === 0) continue;
            reported.add(el);
            const sel = cssPath(el);
            push("warn", "region-low-density",
                 `<${el.tagName.toLowerCase()}> ${Math.round(r.width)}x${Math.round(r.height)}px contains ${txt.length} chars of text and ${mediaCount} media element(s) -- density score ${score.toFixed(3)} (< 0.05). Probably a section that lost most of its content.`,
                 {selector: sel, fingerprint: sel,
                  width: Math.round(r.width),
                  height: Math.round(r.height),
                  text_chars: txt.length,
                  media_count: mediaCount,
                  density_score: Number(score.toFixed(3))});
            n += 1;
        }
    }

    // Duplicate `view-transition-name` collisions. Chrome's view-
    // transitions API REQUIRES every active `view-transition-name`
    // value to be unique on the page; collisions throw
    // `InvalidStateError: Transition was aborted because of invalid
    // state` on the next navigation AND log "Unexpected duplicate
    // view-transition-name: <name>" to the console. The error is
    // invisible during a single static `page.goto` (transitions
    // only fire on navigation), so we have to detect it from the
    // STATIC DOM by walking every element's computed
    // `view-transition-name` and grouping by value.
    //
    // Two flavours of collision matter:
    //
    //   1. CSS-driven (the "site title" footgun) — a theme.json rule
    //      like `.wp-block-site-title { view-transition-name:
    //      fifty-site-title }` matches BOTH the header and the
    //      footer wordmark and assigns them the same name.
    //   2. PHP-driven (the "post-title appears twice" footgun) —
    //      a `render_block` filter naively assigns
    //      `fifty-post-{ID}-{kind}` to every `core/post-title`,
    //      and the same post ID renders in two block contexts on
    //      the same page (featured-products + post-template grid).
    //
    // Both are flagged here at error severity because the rendered
    // page IS broken — the next click silently aborts every
    // transition the theme tries to choreograph. Computed style is
    // the load-bearing source of truth (not the inline
    // `style=` attribute), because some rules apply via stylesheet
    // and inheritance.
    const vtSeen = new Map();  // name -> [{tag, id, classes}]
    document.querySelectorAll('*').forEach((el) => {
        const cs = window.getComputedStyle(el);
        const name = cs.viewTransitionName;
        if (!name || name === 'none' || name === 'auto') return;
        const arr = vtSeen.get(name) || [];
        arr.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            classes: (el.className && typeof el.className === 'string')
                ? el.className.split(/\s+/).filter(Boolean).slice(0, 4).join('.')
                : '',
        });
        vtSeen.set(name, arr);
    });
    for (const [name, els] of vtSeen.entries()) {
        if (els.length < 2) continue;
        const where = els.slice(0, 4).map((e) => {
            const cls = e.classes ? '.' + e.classes : '';
            const id = e.id ? '#' + e.id : '';
            return `${e.tag}${id}${cls}`;
        }).join(', ');
        push("error", "view-transition-name-collision",
             `Duplicate \`view-transition-name: ${name}\` on `
             + `${els.length} elements (${where}). The next `
             + `navigation will throw InvalidStateError and abort `
             + `every view transition the theme defines. Fix by `
             + `narrowing the selector (e.g. scope `
             + `\`.wp-block-site-title\` to a header/footer ancestor) `
             + `or by deduping per-post names in the render_block `
             + `filter.`,
             {vt_name: name, count: els.length});
    }

    // `view-transition-name-coverage` — every internal "card" link
    // (a product link on shop/category, a post link on journal) MUST
    // have at least one descendant with a non-`none` computed
    // `view-transition-name`. Without it the cross-document image
    // morph silently no-ops: Chrome runs the root crossfade but the
    // hero image on the destination page has no source to morph
    // from. This heuristic catches the regression class that bit us
    // when WooCommerce blocks renamed product-card image markup
    // from `core/post-featured-image` to `woocommerce/product-image`
    // (the `render_block` filter only knew about the core block, so
    // the new card markup quietly stopped getting named).
    //
    // Run on any page that has card-shaped product/post links —
    // listing routes (shop, journal, home), but also PDPs that
    // render cross-sells / related-products / "you might also like"
    // grids, which is exactly where the regression most often hides
    // (the listing pages get tested first; the long-tail PDP grids
    // do not).
    {
        // ONLY consider links that live inside a recognised listing
        // context. Without this guard the rule fires on any product
        // link anywhere (cart line-item thumbnails, mini-cart drawer,
        // body-copy cross-sells), all of which use generic
        // `.wp-block-post-content` page wrappers as their `closest()`
        // ancestor, producing "1 of 1 card missing" findings on cart,
        // checkout, and my-account routes that have no real listings
        // at all.
        const LISTING_CONTEXT = (
            '.wp-block-post-template'
            + ', .wp-block-product-template'
            + ', .wc-block-product-template'
            + ', .wc-block-product-collection'
            + ', ul.products'
        );
        const CARD_LINK = (
            'a[href*="/product/"]'
            + ', a.woocommerce-LoopProduct-link'
            + ', .wp-block-post a[href]'
        );
        const cardLinks = Array.from(document.querySelectorAll(CARD_LINK))
            .filter((a) => a.closest(LISTING_CONTEXT) !== null);
        // Distinct cards only — the same product link often appears
        // multiple times (image link + title link). Group by closest
        // card-shaped ancestor so we count one card once. Drop the
        // overbroad `article` from the ancestor list — a singular post
        // template's `<article>` wrapper is NOT a card and was the
        // source of half the false positives.
        const cards = new Set();
        for (const a of cardLinks) {
            const card = a.closest(
                'li.product, .wp-block-product, .wp-block-post'
            ) || a;
            cards.add(card);
        }
        let missing = 0;
        let total = 0;
        const samples = [];
        // Dedupe by destination URL. If the same product is
        // featured twice on a page (e.g. once in a "featured"
        // product collection and again in a "latest" one), only
        // ONE card can carry `view-transition-name:
        // fifty-post-<id>-image` — page-level uniqueness is a
        // hard browser invariant. Counting both as missing would
        // be a false positive, so we score by destination URL,
        // not card identity. The user only sees one of them
        // morph anyway; that's the one that matters.
        const seenHrefs = new Set();
        for (const card of cards) {
            if (!isVisible(card)) continue;
            // …AND only if the card actually has an <img> to
            // morph. A title-only product link in body copy or a
            // hero CTA wrapped around a static
            // `<a href="/product/foo/">` has nothing to morph,
            // so flagging it would only produce noise.
            if (!card.querySelector('img')) continue;
            const a = card.querySelector('a[href]');
            const href = a ? a.getAttribute('href') : '<no link>';
            if (seenHrefs.has(href)) continue;
            const named = Array.from(card.querySelectorAll('*')).some((el) => {
                const cs = window.getComputedStyle(el);
                const n = cs.viewTransitionName;
                return n && n !== 'none' && n !== 'auto';
            });
            if (named) {
                seenHrefs.add(href);
            }
        }
        // Second pass: for any href that was NEVER named on ANY
        // of its visible card occurrences, count it as missing.
        const allHrefs = new Set();
        for (const card of cards) {
            if (!isVisible(card)) continue;
            if (!card.querySelector('img')) continue;
            const a = card.querySelector('a[href]');
            const href = a ? a.getAttribute('href') : '<no link>';
            allHrefs.add(href);
        }
        for (const href of allHrefs) {
            total += 1;
            if (!seenHrefs.has(href)) {
                missing += 1;
                if (samples.length < 4) samples.push(href);
            }
        }
        if (total > 0 && missing > 0) {
            push("error", "view-transition-name-coverage",
                 `${missing} of ${total} card(s) on this listing have `
                 + `no descendant with a \`view-transition-name\`, so `
                 + `the cross-document image morph will silently no-op `
                 + `for those cards. Samples: ${samples.join(', ')}. `
                 + `Fix by extending the \`render_block\` filter in `
                 + `\`functions.php\` to cover the block name(s) used `
                 + `to render the card image (e.g. add `
                 + `\`woocommerce/product-image\` to the \`$names\` map).`,
                 {missing: missing, total: total, samples: samples});
        }
    }

    // Captured measurements for the user-supplied INSPECT_SELECTORS.
    const wanted = args.inspectSelectors || [];
    for (const sel of wanted) {
        const els = Array.from(document.querySelectorAll(sel));
        const entry = {selector: sel, count: els.length, instances: []};
        for (const el of els.slice(0, 4)) {
            const r = el.getBoundingClientRect();
            const cs = window.getComputedStyle(el);
            entry.instances.push({
                width: Math.round(r.width),
                height: Math.round(r.height),
                visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none',
                display: cs.display,
                grid_template_columns: cs.gridTemplateColumns,
                min_width: cs.minWidth,
                max_width: cs.maxWidth,
            });
        }
        if (els.length === 0) {
            entry.missing = true;
            // Missing inspect selectors are usually a reason to update
            // snap_config.py rather than a real bug, so info-level only.
            push("info", "inspect-selector-missing",
                 `Selector \`${sel}\` matched 0 elements on this page.`,
                 {selector: sel});
        } else {
            // Surface obviously narrow sidebar-ish elements.
            for (const inst of entry.instances) {
                const looksLikeSidebar = /sidebar|aside/i.test(sel);
                if (looksLikeSidebar && inst.visible && inst.width > 0 && inst.width < 200 && vw >= 782) {
                    push("error", "narrow-sidebar",
                         `\`${sel}\` rendered ${inst.width}px wide on a ${vw}px viewport (expected >= 300px sidebar).`,
                         {selector: sel, element_width: inst.width, viewport_width: vw});
                }
                // Surface wc main-content blocks that rendered crammed
                // into a narrow column despite being on a desktop-or-
                // wider viewport. Catches the Foundry-style "account
                // login crammed into 228px inside a 1280px viewport"
                // class of regression that neither the source-level
                // `check_cart_checkout_pages_are_wide` (which only
                // inspects block markup) nor vision review (without
                // the v1.1 functional kinds) could see.
                //
                // Threshold at 900px because the designed 2-column WC
                // layouts allocate ~880px to the main content column
                // (1280px wideSize minus ~360px sidebar minus gap).
                // Anything narrower than 900 at >=1280 viewport means
                // the wide layout did not engage.
                // Match only the cart/checkout *shell* selectors — not
                // `.wc-block-cart-items` (the inner table matches
                // `wc-block-cart\\b` because \\b falls between `t` and
                // `-items`).
                const looksLikeWcMain = (
                    sel === ".wc-block-cart" ||
                    sel === ".wc-block-checkout" ||
                    /woocommerce-MyAccount-content\b|wo-account-login-grid\b/i.test(sel)
                ) && !/sidebar|summary/i.test(sel);
                if (looksLikeWcMain && inst.visible && inst.width > 0 && inst.width < 900 && vw >= 1280) {
                    push("error", "narrow-wc-block",
                         `\`${sel}\` rendered ${inst.width}px wide on a ${vw}px viewport (expected >= 900px at desktop+; the wide-layout CSS did not engage).`,
                         {selector: sel, element_width: inst.width, viewport_width: vw});
                }
            }
        }
        out.selectors.push(entry);
    }

    return out;
}
"""


def _is_known_noise(text: str) -> bool:
    """KNOWN_NOISE_SUBSTRINGS is sourced from snap_config.py so adding a
    noise filter is a one-line config edit — no snap.py change needed."""
    return any(s in text for s in KNOWN_NOISE_SUBSTRINGS)


# ---------------------------------------------------------------------------
# axe-core a11y vendor + injector
# ---------------------------------------------------------------------------
AXE_VERSION = "4.10.0"
AXE_VENDOR_PATH = REPO_ROOT / "bin" / "vendor" / "axe.min.js"
AXE_DOWNLOAD_URL = (
    f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
)
# Mapping from axe `impact` to our internal severity. Critical/serious
# block the build via the tiered gate; moderate/minor surface in the
# review without failing it. axe sometimes emits null impact for the
# experimental rules -- we treat those as info to avoid noise.
_AXE_IMPACT_TO_SEVERITY: dict[str, str] = {
    "critical": "error",
    "serious": "error",
    "moderate": "warn",
    "minor": "info",
}


def _ensure_axe_vendored() -> str | None:
    """Return axe-core source as a string, downloading once if needed.

    Returns None if the download failed AND no vendored copy exists
    (offline contributors get a one-line note rather than a build
    failure). Subsequent shoots reuse the vendored file.
    """
    if AXE_VENDOR_PATH.exists():
        return AXE_VENDOR_PATH.read_text(encoding="utf-8")
    AXE_VENDOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(AXE_DOWNLOAD_URL, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  {YELLOW}warn:{RESET} could not download axe-core "
              f"({e}); a11y checks skipped.")
        return None
    AXE_VENDOR_PATH.write_text(data, encoding="utf-8")
    print(f"  {DIM}vendored axe-core {AXE_VERSION} to "
          f"{AXE_VENDOR_PATH.relative_to(REPO_ROOT)}{RESET}")
    return data


def _run_axe(page, axe_source: str) -> dict:
    """Inject axe-core into the page and return the violations report.

    Errors are swallowed and returned as a one-key dict so a single
    shaky page doesn't kill the whole shoot.
    """
    try:
        page.evaluate(axe_source)
        # `resultTypes: ['violations']` skips the (much larger)
        # passes/incomplete/inapplicable arrays so the artifact stays
        # under ~50KB even for image-heavy pages.
        result = page.evaluate(
            "() => axe.run(document, {resultTypes: ['violations']})"
        )
    except Exception as e:
        return {"error": f"axe injection/run failed: {e}", "violations": []}
    return result if isinstance(result, dict) else {"violations": []}


def _node_is_suppressed(
    rule: str,
    route_slug: str,
    node: dict,
) -> A11ySuppression | None:
    """Return the matching suppression for `node`, or None.

    Match strategy: substring scan over the node's joined target CSS
    path AND its outerHTML snippet. axe's `target` is the canonical
    element address (used in review.md), `html` carries the offending
    element's classes/attributes. Substring across both lets a
    suppression key on either selector or attribute (e.g. an `id="email"`
    fragment) without the entry needing to know which axis axe used.

    Suppressions with `routes=()` apply to every route; otherwise the
    route slug must appear verbatim in `routes`. We do not partial-match
    route slugs because flow names like `cart-filled.line-remove` need
    to be opt-in distinct from the static `cart-filled` cell.
    """
    target_str = " > ".join(str(t) for t in (node.get("target") or []))
    html_str = node.get("html") or ""
    haystack = target_str + "\n" + html_str
    for s in A11Y_SUPPRESSIONS:
        if s.rule != rule:
            continue
        if s.routes and route_slug not in s.routes:
            continue
        if s.selector_contains in haystack:
            return s
    return None


def _axe_to_findings(axe_result: dict, route_slug: str) -> list[dict]:
    """Translate an axe report's violations into our finding format.

    `A11Y_SUPPRESSIONS` is consulted per node: matching nodes are
    dropped from the violation's node list. If every node for a
    violation is suppressed the violation is omitted entirely; if some
    nodes survive, the surviving count is reported and the suppression
    is recorded under `axe_suppressed` so review.md can surface that
    we knowingly accept N upstream-WC instances.
    """
    out: list[dict] = []
    for v in axe_result.get("violations", []) or []:
        impact = (v.get("impact") or "minor").lower()
        sev = _AXE_IMPACT_TO_SEVERITY.get(impact, "info")
        rule = v.get("id", "unknown")
        nodes = v.get("nodes", []) or []

        # Partition nodes into kept vs suppressed. Suppressed nodes are
        # tallied per-suppression-rule so the JSON artifact carries an
        # auditable breakdown ("we ignored 1 mini-cart drawer + 1 skeleton
        # because of the matching A11Y_SUPPRESSIONS entries").
        kept_nodes: list[dict] = []
        suppressed: dict[str, int] = {}
        for n in nodes:
            hit = _node_is_suppressed(rule, route_slug, n)
            if hit is None:
                kept_nodes.append(n)
            else:
                key = hit.selector_contains
                suppressed[key] = suppressed.get(key, 0) + 1

        if not kept_nodes:
            # All instances of this violation are upstream noise. Drop
            # the finding entirely; the raw count still lives in the
            # untouched .a11y.json artifact next to the screenshot.
            continue

        # axe can flag dozens of nodes for the same rule (e.g.
        # color-contrast on a list of links). Collapse to a single
        # finding per rule with the surviving count + first 3 selectors
        # so the review stays scannable.
        first_selectors = []
        for n in kept_nodes[:3]:
            target = n.get("target", [])
            if target:
                first_selectors.append(" > ".join(map(str, target[0:1])))
        out.append({
            "severity": sev,
            "kind": f"a11y-{rule}",
            "message": (
                f"{v.get('help', rule)} ({len(kept_nodes)} node(s))"
                + (f" — first: {first_selectors[0]}" if first_selectors else "")
            ),
            "axe_help_url": v.get("helpUrl", ""),
            "axe_impact": impact,
            "axe_node_count": len(kept_nodes),
            "axe_first_selectors": first_selectors,
            "axe_suppressed": suppressed,  # {} when nothing was suppressed
        })
    return out


def _attach_diagnostics(page) -> dict:
    """Wire console + pageerror + response listeners onto a Playwright
    page and return a dict that accumulates the captured events.

    The dict is mutated in-place by the listeners. Drain it after each
    navigation by reading + clearing its lists; we keep one accumulator
    per page rather than per route to avoid handler churn between
    routes (Playwright re-emits handler-add cost on every wiring).
    """
    bag: dict = {"console": [], "page_errors": [], "network_failures": []}

    def on_console(msg):
        try:
            t = msg.type
        except Exception:
            t = "log"
        if t in ("warning", "error"):
            try:
                text = msg.text[:600]
                if _is_known_noise(text):
                    return
                bag["console"].append({"type": t, "text": text})
            except Exception:
                pass

    def on_pageerror(err):
        try:
            text = str(err)[:600]
            if _is_known_noise(text):
                return
            bag["page_errors"].append(text)
        except Exception:
            pass

    def on_response(resp):
        try:
            status = resp.status
            if status >= 400:
                bag["network_failures"].append({
                    "status": status,
                    "url": resp.url,
                    "method": resp.request.method,
                })
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    return bag


# ---------------------------------------------------------------------------
# Cross-document View Transitions click-through probe
# ---------------------------------------------------------------------------
# Source routes the probe will try, in order. First one that yields a
# clickable internal link wins. Slugs map to Route.path via a lookup
# in the caller — the probe itself just talks URL paths.
_VT_PROBE_SOURCES: tuple[tuple[str, str], ...] = (
    ("shop", "main a[href*='/product/'], main a.woocommerce-LoopProduct-link"),
    ("journal",
     "main .wp-block-post a[href], main .wp-block-post-template a[href]"),
)

# Init script installed on the probe page BEFORE any navigation.
# Stashes pageswap/pagereveal observation results on `window.
# __fiftyVtProbe` so the Python side can read them after the cross-
# document swap. Re-fires automatically on every new document (so the
# pagereveal listener IS registered before the destination's first
# rendering opportunity, per the Chrome cross-document VT spec).
_VT_PROBE_INIT_SCRIPT = """
(() => {
  if (window.__fiftyVtProbeInstalled) return;
  window.__fiftyVtProbeInstalled = true;
  window.__fiftyVtProbe = {pageswap: null, pagereveal: null,
                           types: [], at: null};
  // The probe is installed via Playwright's add_init_script, which
  // runs BEFORE any document <script> — so this listener registers
  // BEFORE the theme's wp_head priority-1 pageswap/pagereveal
  // handler. That means our listener fires FIRST and snapshots the
  // types Set BEFORE the theme handler has called
  // `e.viewTransition.types.add(<flavor>)`. To capture the flavor
  // anyway, defer the types read to a microtask so it runs AFTER
  // every synchronous pagereveal listener has had a chance to add
  // its types.
  addEventListener('pageswap', (e) => {
    try {
      window.__fiftyVtProbe.pageswap = !!e.viewTransition;
    } catch (_) {}
  });
  addEventListener('pagereveal', (e) => {
    try {
      window.__fiftyVtProbe.pagereveal = !!e.viewTransition;
      window.__fiftyVtProbe.at = location.href;
      if (e.viewTransition && e.viewTransition.types) {
        const vt = e.viewTransition;
        Promise.resolve().then(() => {
          try {
            window.__fiftyVtProbe.types = Array.from(vt.types);
          } catch (_) {}
        });
      }
    } catch (_) {}
  });
})();
"""


def _probe_view_transitions_click(ctx, server_url: str, vp_name: str) -> list:
    """Click an internal card link from a listing route and assert
    that a real cross-document View Transition fires.

    Implementation notes:
      * We use a dedicated probe page (not the shoot page) so the
        existing per-route accumulators stay clean and the probe
        doesn't bleed `pageswap` artefacts into other findings.
      * `add_init_script` re-runs in every new document, so the
        `pagereveal` listener IS registered before the destination
        page's first paint — the Chrome spec requires this.
      * We try each source route in `_VT_PROBE_SOURCES` and stop at
        the first one that yields a visible internal link. Themes
        without a journal (Woo-only) silently skip the journal probe;
        themes without a shop (blog-only) silently skip the shop one.

    Returns a list of finding-shaped dicts. Severity:
      * `error` if any probed source navigates but the destination
        document reports `pagereveal.viewTransition === null` (the
        transition silently aborted).
      * `warn` if no probeable source link could be clicked at all
        (probably a config issue, not a bug — but worth surfacing).
      * `info` for successful probes (so the manifest records what
        was checked, not just what failed).
    """
    findings: list[dict] = []
    page = ctx.new_page()
    try:
        page.add_init_script(_VT_PROBE_INIT_SCRIPT)
    except Exception as e:
        findings.append({
            "severity": "info", "kind": "vt-probe-skipped",
            "viewport": vp_name,
            "message": f"could not install probe init script: {e}",
        })
        page.close()
        return findings

    any_probed = False
    for slug, link_sel in _VT_PROBE_SOURCES:
        url = f"{server_url}/{slug}/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            findings.append({
                "severity": "info", "kind": "vt-probe-skipped",
                "viewport": vp_name, "source": slug,
                "message": f"could not load source route: {e}",
            })
            continue
        # Reset probe state — the goto itself triggers pageswap/
        # pagereveal in some Chrome builds, and we only care about the
        # subsequent click.
        try:
            page.evaluate(
                "() => { window.__fiftyVtProbe = "
                "{pageswap: null, pagereveal: null, types: [], at: null}; }"
            )
        except Exception:
            pass
        try:
            link = page.locator(link_sel).first
            link.wait_for(state="visible", timeout=2_500)
            href = link.get_attribute("href") or ""
        except Exception:
            # No clickable card — try the next source. Not an error
            # in itself; some themes legitimately skip a route.
            continue
        any_probed = True
        try:
            link.click(timeout=4_000)
            page.wait_for_load_state(
                "domcontentloaded", timeout=15_000)
            # Tiny wait so pagereveal definitely fired.
            page.wait_for_timeout(120)
        except Exception as e:
            findings.append({
                "severity": "warn", "kind": "vt-probe-click-failed",
                "viewport": vp_name, "source": slug, "href": href,
                "message": f"click did not navigate cleanly: {e}",
            })
            continue
        probe = None
        try:
            probe = page.evaluate("() => window.__fiftyVtProbe || null")
        except Exception:
            probe = None
        if not probe or probe.get("pagereveal") is None:
            findings.append({
                "severity": "warn", "kind": "vt-probe-no-event",
                "viewport": vp_name, "source": slug, "href": href,
                "message": (
                    "pagereveal event was not observed on the "
                    "destination document. The browser may not "
                    "support cross-document View Transitions."),
            })
            continue
        if probe.get("pagereveal") is True:
            findings.append({
                "severity": "info", "kind": "view-transition-fires-on-click",
                "viewport": vp_name, "source": slug, "href": href,
                "types": probe.get("types") or [],
                "destination": probe.get("at"),
                "message": (
                    "Cross-document View Transition fired on "
                    f"{slug} → {href}."),
            })
        else:
            findings.append({
                "severity": "error", "kind": "view-transition-aborted",
                "viewport": vp_name, "source": slug, "href": href,
                "message": (
                    "Clicked an internal card link from "
                    f"/{slug}/ but `pagereveal.viewTransition` was "
                    "null on the destination — the transition was "
                    "silently aborted (e.g. duplicate "
                    "`view-transition-name`, CSP blocking the inline "
                    "pageswap script, or `prefers-reduced-motion`)."),
            })
    if not any_probed:
        findings.append({
            "severity": "warn", "kind": "vt-probe-no-source",
            "viewport": vp_name,
            "message": (
                "No probeable internal card link was found on any "
                "configured source route. Add a product or post and "
                "re-shoot, or update _VT_PROBE_SOURCES."),
        })
    try:
        page.close()
    except Exception:
        pass
    return findings


# ---------------------------------------------------------------------------
# Interactive flow dispatcher (Phase 3)
# ---------------------------------------------------------------------------
def _run_interaction(page, flow: Interaction) -> str | None:
    """Run a declarative interaction. Return None on success, or an
    error string. Each step swallows its own selector misses (the
    selectors in snap_config use commas to allow theme-specific
    fallbacks; we only fail the flow if every alternative is missing).
    """
    for i, step in enumerate(flow.steps):
        action = step.get("action")
        try:
            if action == "wait":
                page.wait_for_timeout(int(step.get("ms", 100)))
            elif action == "press":
                page.keyboard.press(step["key"])
            elif action == "click":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 3000)))
                el.click(timeout=int(step.get("timeout_ms", 3000)))
            elif action == "hover":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.hover(timeout=int(step.get("timeout_ms", 2000)))
            elif action == "focus":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.focus(timeout=int(step.get("timeout_ms", 2000)))
            elif action == "fill":
                el = page.locator(step["selector"]).first
                el.wait_for(state="visible",
                            timeout=int(step.get("timeout_ms", 2000)))
                el.fill(step.get("text", ""),
                        timeout=int(step.get("timeout_ms", 2000)))
            elif action == "select_option":
                # Pick a value in a native <select>. Required because
                # `<option>` elements are not click-targetable in Chromium
                # (they're popup-rendered and have no DOM bounds in the
                # page). For WooCommerce variation dropdowns ("size",
                # "color"), use this instead of `click` on the option --
                # the swatch-pick flow learned this the hard way after
                # 20 false interaction-failed findings/run.
                #
                # `value` selects by `<option value=...>`; `index`
                # selects by position; `label` selects by visible text.
                # If the caller passes only `selector`, default to
                # index=1 (the first non-default option, since index 0
                # is typically the placeholder "Choose an option").
                el = page.locator(step["selector"]).first
                el.wait_for(state="attached",
                            timeout=int(step.get("timeout_ms", 3000)))
                opts: dict = {}
                if "value" in step:
                    opts["value"] = step["value"]
                elif "label" in step:
                    opts["label"] = step["label"]
                else:
                    opts["index"] = int(step.get("index", 1))
                el.select_option(timeout=int(step.get("timeout_ms", 3000)),
                                 **opts)
            else:
                return f"step {i}: unknown action {action!r}"
        except Exception as e:
            return f"step {i} ({action} {step.get('selector', '')!r}): {e}"
    return None


def _capture_finding_crops(
    page, findings: list[dict], out_dir: Path, slug: str
) -> None:
    """For every finding that carries a stable `selector`, capture a small
    JPG crop of the offending element padded ±20px so reviewers don't
    have to hunt through a 3000px full-page screenshot to locate the bug.

    Mutates each finding in-place to add a `crop_path` field pointing at
    `<out_dir>/<slug>.<kind>.<idx>.crop.jpg` (relative to repo root).
    Failures are swallowed -- the snap pipeline's job is to record what
    happened, not to fail because evidence capture had a flaky moment.

    Per-kind index ensures multiple findings of the same kind on the
    same cell get distinct paths (e.g. five `element-overflow-x` findings
    on a sloppy footer all get their own crop).
    """
    seen_kinds: dict[str, int] = {}
    vp_size = page.viewport_size or {"width": 1920, "height": 1080}
    vw = vp_size.get("width", 1920)
    vh = vp_size.get("height", 1080)
    for f in findings:
        # Heuristics put the selector under `selector`; axe findings
        # surface it under `axe_first_selectors[0]`. Accept either.
        sel = f.get("selector")
        if not sel and isinstance(f.get("axe_first_selectors"), list):
            axe_sels = f["axe_first_selectors"]
            if axe_sels:
                sel = axe_sels[0]
        if not sel or not isinstance(sel, str):
            continue
        kind = str(f.get("kind") or "unknown")
        idx = seen_kinds.get(kind, 0)
        seen_kinds[kind] = idx + 1
        crop_path = out_dir / f"{slug}.{kind}.{idx}.crop.jpg"
        try:
            loc = page.locator(sel).first
            loc.scroll_into_view_if_needed(timeout=1500)
            bbox = loc.bounding_box(timeout=1000)
            if not bbox:
                continue
            bw = bbox.get("width", 0) or 0
            bh = bbox.get("height", 0) or 0
            if bw < 1 or bh < 1:
                continue
            # Pad +/-20px, then clamp to the viewport bounds (Playwright
            # rejects clip rectangles that extend off-screen). bounding_box
            # is reported in viewport coordinates after scroll-into-view,
            # so this clip lives in viewport space.
            pad = 20
            x = max(0.0, bbox["x"] - pad)
            y = max(0.0, bbox["y"] - pad)
            w = min(float(vw) - x, bw + 2 * pad)
            h = min(float(vh) - y, bh + 2 * pad)
            if w < 1 or h < 1:
                continue
            page.screenshot(
                path=str(crop_path),
                clip={"x": x, "y": y, "width": w, "height": h},
                type="jpeg",
                quality=80,
            )
            f["crop_path"] = str(crop_path.relative_to(REPO_ROOT))
        except Exception:
            # Selector unresolvable, element scrolled off, page nav'd, or
            # the screenshot itself failed -- crops are best-effort.
            continue


def _capture_cell(
    *,
    page,
    bag: dict,
    axe_source: str | None,
    theme: str,
    vp: Viewport,
    slug: str,
    inspect: list[str],
    url: str,
    out_dir: Path,
    nav_error: str | None,
    extra_findings: list[dict] | None = None,
) -> dict:
    """Run heuristics + axe + console budget + screenshot for one cell.

    Returns the manifest-shaped dict for the caller to append. The
    cell's `<slug>.png`, `<slug>.html`, `<slug>.findings.json`, and
    optional `<slug>.a11y.json` are written under `out_dir`.
    `extra_findings` lets the interactive caller inject e.g. an
    `interaction-failed` finding so it shows up in the same review row.
    """
    out_path = out_dir / f"{slug}.png"
    html_path = out_dir / f"{slug}.html"
    findings_path = out_dir / f"{slug}.findings.json"
    a11y_path = out_dir / f"{slug}.a11y.json"

    findings: dict = {}
    try:
        findings = page.evaluate(
            _HEURISTICS_JS, {"inspectSelectors": inspect}
        )
    except Exception as e:
        findings = {"findings": [
            {"severity": "warn", "kind": "heuristics-failed",
             "message": f"Heuristics evaluation failed: {e}"},
        ], "selectors": []}
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as e:
        print(f"    {YELLOW}warn:{RESET} html capture: {e}")

    axe_findings: list[dict] = []
    if axe_source is not None:
        axe_result = _run_axe(page, axe_source)
        axe_findings = _axe_to_findings(axe_result, route_slug=slug)
        try:
            a11y_path.write_text(
                json.dumps(axe_result, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"    {YELLOW}warn:{RESET} a11y write: {e}")

    try:
        page.screenshot(path=str(out_path), full_page=True)
    except Exception as e:
        print(f"    {RED}fail:{RESET} screenshot: {e}")
        return {}

    warn_console = sum(
        1 for c in bag["console"]
        if c.get("type") == "warning"
        and not _is_known_noise(c.get("text", ""))
    )
    budget_findings: list[dict] = []
    cw_budget = BUDGETS.get("console_warning_count", {})
    cw_max = cw_budget.get("max")
    if cw_max is not None and warn_console > cw_max:
        budget_findings.append({
            "severity": cw_budget.get("severity", "info"),
            "kind": "console-warn-budget",
            "message": (
                f"{warn_console} console warnings on this cell "
                f"(>{cw_max}). Consider triaging."
            ),
            "count": warn_console, "max": cw_max,
        })

    base_findings = list(findings.get("findings", []))

    # background-image-broken: cross-reference the (selector, url) pairs
    # collected by _HEURISTICS_JS with the response-listener's network
    # failures. Any CSS background-image URL that 404'd is an ERROR --
    # this is the cover-block "the image silently disappeared but the
    # box stayed there" failure mode that a pixel diff won't catch
    # because the box is the same shape with or without the image.
    bg_pairs = findings.get("bg_image_pairs") or []
    if bg_pairs:
        failed_urls = {
            nf.get("url"): nf.get("status")
            for nf in bag.get("network_failures", [])
            if nf.get("url")
        }
        bg_findings: list[dict] = []
        for pair in bg_pairs:
            url = pair.get("url", "")
            sel = pair.get("selector", "")
            status = failed_urls.get(url)
            if status is None:
                continue
            bg_findings.append({
                "severity": "error",
                "kind": "background-image-broken",
                "message": (
                    f"CSS background-image failed to load (HTTP {status}): "
                    f"{url} on `{sel}`."
                ),
                "selector": sel,
                "fingerprint": sel + "|" + url,
                "url": url,
                "status": status,
            })
            if len(bg_findings) >= 5:
                break
        base_findings.extend(bg_findings)

    findings["findings"] = (
        base_findings + axe_findings + budget_findings + (extra_findings or [])
    )

    # Apply the heuristic-finding allowlist BEFORE capturing crops, so
    # the cell's recorded `error_count` (and the gallery badge built
    # from it) reflects the post-allowlist gate. Demoted findings stay
    # in the JSON artifact tagged `allowlisted: true` so reviewers can
    # still see what's being intentionally accepted.
    _apply_allowlist_to_findings(theme, vp.name, slug, findings["findings"])

    # Capture per-finding cropped JPGs of each offender (where a stable
    # selector is available). This MUST run after findings are
    # consolidated but before they're written to disk so `crop_path`
    # ends up in the JSON artifact. Best-effort -- a flaky scroll or
    # an axe selector Playwright can't parse won't fail the cell.
    try:
        _capture_finding_crops(page, findings["findings"], out_dir, slug)
    except Exception as e:  # pragma: no cover -- defensive only
        print(f"    {YELLOW}warn:{RESET} finding-crop capture: {e}")

    findings_payload = {
        **findings,
        "theme": theme,
        "viewport": vp.name,
        "route": slug,
        "url": url,
        "navigation_error": nav_error,
        "console": list(bag["console"]),
        "page_errors": list(bag["page_errors"]),
        "network_failures": list(bag["network_failures"]),
        "a11y_path": (
            str(a11y_path.relative_to(REPO_ROOT))
            if axe_source is not None and a11y_path.exists() else None
        ),
    }
    findings_path.write_text(
        json.dumps(findings_payload, indent=2), encoding="utf-8"
    )

    finds = findings.get("findings", [])
    err_count = sum(1 for f in finds if f.get("severity") == "error")
    warn_count = sum(1 for f in finds if f.get("severity") == "warn")
    if err_count or warn_count:
        col = RED if err_count else YELLOW
        print(f"    {col}flags:{RESET} {err_count} error / "
              f"{warn_count} warn ({slug})")

    return {
        "viewport": vp.name,
        "route": slug,
        "path": str(out_path.relative_to(REPO_ROOT)),
        "size_bytes": out_path.stat().st_size,
        "findings_path": str(findings_path.relative_to(REPO_ROOT)),
        "html_path": str(html_path.relative_to(REPO_ROOT)),
        "a11y_path": (
            str(a11y_path.relative_to(REPO_ROOT))
            if axe_source is not None and a11y_path.exists() else None
        ),
        "error_count": err_count,
        "warn_count": warn_count,
    }


def shoot_theme(
    theme: str,
    server_url: str,
    routes: list[Route],
    viewports: list[Viewport],
    out_root: Path,
    skip_cells: set[tuple[str, str]] | None = None,
    signatures: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """Drive Playwright across (route, viewport). Returns a manifest dict.

    For each (route, viewport) the framework writes:
      <slug>.png            full-page screenshot (animations frozen)
      <slug>.html           rendered HTML after networkidle + JS settle
      <slug>.findings.json  structured diagnostics:
        * viewport          {width, height, scrollWidth, scrollHeight}
        * findings[]        DOM heuristics (overflow, WC notices, broken
                             images, sidebar squeeze, debug output, etc.)
        * selectors[]       computed widths/grid for INSPECT_SELECTORS
        * console[]         browser console warnings + errors
        * page_errors[]     uncaught JS exceptions
        * network_failures[] HTTP responses with status >= 400

    Heuristics + capture happen inside `page.evaluate()`; nothing in
    them mutates the DOM that gets screenshotted, so the PNG and the
    findings reflect the same rendered state.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover -- guidance for first-run users
        raise SystemExit(
            "Playwright is not installed. Install with:\n"
            "  python3 -m pip install --user playwright\n"
            "  playwright install chromium\n"
            f"(import error: {e})"
        )

    manifest: dict = {"theme": theme, "shots": []}
    out_root.mkdir(parents=True, exist_ok=True)
    # Vendor axe-core once per process. Returned source is None when
    # the contributor is offline AND has no vendored copy; that case
    # disables a11y checks gracefully instead of failing the shoot.
    axe_source = _ensure_axe_vendored()

    # Partition routes into anonymous vs authenticated groups. We run
    # the anonymous routes in the existing browser context, then (if any
    # auth-required routes remain) spin up a SECOND context per viewport
    # that POSTs `wp-login.php` as `admin` to acquire the session
    # cookie. Two contexts (rather than one shared logged-in context)
    # keeps the anonymous routes free of dashboard chrome -- WC injects
    # the admin bar on every page when a session is active, which
    # would shift the layout below it on EVERY anonymous capture.
    anon_routes = [r for r in routes if not getattr(r, "auth", False)]
    auth_routes = [r for r in routes if getattr(r, "auth", False)]

    def _login_admin(ctx) -> bool:
        """POST wp-login.php with admin/password and return True on success.

        Mirrors what Playground's `login: true` blueprint step does
        client-side. Uses the request API rather than driving the form
        because the wp-login form uses a self-submitting POST, which
        Playwright's `page.goto` doesn't follow gracefully.
        """
        try:
            page = ctx.new_page()
            page.goto(server_url + "/wp-login.php", wait_until="domcontentloaded", timeout=20_000)
            page.fill("input#user_login", "admin")
            page.fill("input#user_pass", "password")
            page.click("input#wp-submit")
            page.wait_for_url(
                lambda u: "/wp-admin" in u or "/my-account" in u or u.endswith("/wp-login.php"),
                timeout=20_000,
            )
            ok = "wp-login" not in page.url
            page.close()
            return ok
        except Exception as e:
            print(f"    {YELLOW}warn:{RESET} wp-login failed: {e}")
            return False

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vp in viewports:
                ctx = browser.new_context(
                    viewport={"width": vp.width, "height": vp.height},
                    # Capture at 2x DPR so source PNGs are retina-sharp
                    # for human review (zoomed inspection, retina
                    # monitors, gallery downsamples). The viewport
                    # (logical CSS pixels) is unchanged so layout and
                    # responsive breakpoints are identical to a 1x
                    # capture; only the bitmap doubles in resolution.
                    # axe-core, the heuristics engine, and findings.json
                    # all read the DOM/computed styles, not the
                    # bitmap, so warn counts and the static gate are
                    # byte-identical to a 1x shoot.
                    device_scale_factor=2,
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/138.0.0.0 Safari/537.36"
                    ),
                )
                # `add_init_script` runs before any page script, but we
                # need _FREEZE_CSS injected as a stylesheet (not a
                # variable) so it applies to every navigation. The
                # init script wires that up via a <style> tag on
                # DOMContentLoaded so timed animations (font swap,
                # WC drawer slide) settle before our screenshot fires.
                ctx.add_init_script(
                    "(() => { const s = document.createElement('style');"
                    f" s.textContent = {json.dumps(_FREEZE_CSS)};"
                    " document.documentElement.appendChild(s); })();"
                )
                page = ctx.new_page()
                bag = _attach_diagnostics(page)
                vp_dir = out_root / vp.name
                vp_dir.mkdir(parents=True, exist_ok=True)
                # Anonymous phase: every non-auth route in the existing
                # context. Authenticated phase comes after, in a fresh
                # context that POSTs wp-login.php first (logs admin in).
                # The admin bar that appears on logged-in pages would
                # otherwise shift every anon capture below it; keeping
                # the contexts separate is cheaper than diff-tolerating
                # the bar.
                phase_routes = [(False, anon_routes), (True, auth_routes)]
                for phase_auth, phase_route_list in phase_routes:
                    if not phase_route_list:
                        continue
                    if phase_auth:
                        if ctx is not None:
                            ctx.close()
                        ctx = browser.new_context(
                            viewport={"width": vp.width, "height": vp.height},
                            device_scale_factor=2,
                            user_agent=(
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/138.0.0.0 Safari/537.36"
                            ),
                        )
                        ctx.add_init_script(
                            "(() => { const s = document.createElement('style');"
                            f" s.textContent = {json.dumps(_FREEZE_CSS)};"
                            " document.documentElement.appendChild(s); })();"
                        )
                        if not _login_admin(ctx):
                            print(
                                f"  {YELLOW}warn:{RESET} {vp.name:7s} "
                                f"could not log in; skipping {len(phase_route_list)} "
                                f"auth route(s)"
                            )
                            continue
                        page = ctx.new_page()
                        bag = _attach_diagnostics(page)
                    for route in phase_route_list:
                    # Phase 2 skip: if the caller computed that this
                    # cell's signature matches the baseline, the tmp
                    # tree was already populated by _materialize_skipped_
                    # cell() before we booted. Don't re-navigate or
                    # re-capture -- the whole point is to keep 40 of 44
                    # cells out of Playwright's hot loop.
                        if skip_cells and (vp.name, route.slug) in skip_cells:
                            print(
                                f"  {DIM}{vp.name:7s}{RESET} "
                                f"{route.slug:18s} {GREEN}skip{RESET} "
                                f"{DIM}(signature match){RESET}",
                                flush=True,
                            )
                            continue
                        url = server_url + route.path
                        print(
                            f"  {DIM}{vp.name:7s}{RESET} "
                            f"{route.slug:18s} → {url}",
                            flush=True,
                        )
                        # Reset accumulators between routes so per-route
                        # findings only attribute their own console + net
                        # noise (cross-route bleed would confuse the
                        # report).
                        bag["console"].clear()
                        bag["page_errors"].clear()
                        bag["network_failures"].clear()
                        nav_error: str | None = None
                        try:
                            page.goto(url, wait_until="networkidle", timeout=45_000)
                        except Exception as e:
                            nav_error = str(e)
                            print(f"    {YELLOW}warn:{RESET} navigation: {e}")
                        # Small settle for late client renders (mini-cart
                        # hydration, font swap, WC checkout XHR).
                        page.wait_for_timeout(500)
                        # Wait for WooCommerce blocks loading skeletons to
                        # disappear before screenshotting. Without this the
                        # cart and checkout routes routinely shoot at a
                        # moment where the WC blocks store API call has
                        # finished (so `networkidle` fired) but React
                        # hasn't yet swapped the `.wc-block-components-
                        # skeleton` placeholder for the real markup, and
                        # the screenshot captures gray skeleton bars
                        # instead of the actual order summary, line items,
                        # subtotals, etc. Bug visible on every cart-
                        # filled / checkout-filled snap before this guard
                        # was added.
                        #
                        # `wait_for_function` returns true once the page
                        # has zero `.wc-block-components-skeleton`
                        # elements OR every remaining skeleton is hidden
                        # (display:none / visibility:hidden / opacity:0 —
                        # the form Phase A's premium hide-rule takes for
                        # the WC blocks loading mask).
                        #
                        # 6s timeout: long enough for a slow WC store-API
                        # round-trip on a cold playground boot, short
                        # enough that pages without skeletons don't slow
                        # the run noticeably (the predicate returns true
                        # on the FIRST evaluation when the DOM has no
                        # skeleton at all). Failures are swallowed (some
                        # blocks legitimately keep a skeleton up; we'd
                        # rather shoot the page than hang the run).
                        try:
                            page.wait_for_function(
                                """() => {
                                    const skeletons = document.querySelectorAll(
                                        '.wc-block-components-skeleton, '
                                        + '.wc-block-components-skeleton__element'
                                    );
                                    if (skeletons.length === 0) return true;
                                    return Array.from(skeletons).every((el) => {
                                        const cs = window.getComputedStyle(el);
                                        return (
                                            cs.display === 'none'
                                            || cs.visibility === 'hidden'
                                            || parseFloat(cs.opacity) === 0
                                        );
                                    });
                                }""",
                                timeout=6_000,
                            )
                        except Exception:
                            # Skeleton still present after 6s — capture
                            # anyway so the reviewer sees the regression
                            # instead of the script hanging.
                            pass

                        # Static cell. Heuristics + axe + screenshot of the
                        # page in its initial-load state.
                        static_entry = _capture_cell(
                            page=page, bag=bag, axe_source=axe_source,
                            theme=theme, vp=vp, slug=route.slug,
                            inspect=INSPECT_SELECTORS.get(route.slug, []),
                            url=url, out_dir=vp_dir, nav_error=nav_error,
                        )
                        if static_entry:
                            manifest["shots"].append(static_entry)
                            # Phase 2: stamp the route's signature next to
                            # the freshly-captured PNG so the next run can
                            # skip this cell if nothing upstream changes.
                            # We prefer the signature passed in by the
                            # caller (pre-computed once per theme, reused
                            # across viewports) over recomputing it here
                            # -- identical values, one less filesystem walk.
                            cell_key = (vp.name, route.slug)
                            sig = None
                            if signatures and cell_key in signatures:
                                sig = signatures[cell_key]
                            else:
                                sig = compute_route_signature(theme, route.slug)
                            _write_sig_after_shoot(theme, vp.name, route.slug, sig)

                        # Interactive cells (Phase 3). Run any flows
                        # registered for this route + viewport. Each flow
                        # produces its own <route>.<flow>.* artifact set
                        # so reviewers can compare static vs interacted
                        # state side-by-side.
                        for flow in INTERACTIONS.get(route.slug, []):
                            if flow.viewports and vp.name not in flow.viewports:
                                continue
                            bag["console"].clear()
                            bag["page_errors"].clear()
                            bag["network_failures"].clear()
                            flow_slug = f"{route.slug}.{flow.name}"
                            print(f"    {DIM}↳ flow:{RESET} {flow.name} "
                                  f"({flow.description})", flush=True)
                            flow_err = _run_interaction(page, flow)
                            # Settle after the interaction to let any XHR /
                            # transition finish before the screenshot.
                            page.wait_for_timeout(300)
                            extra: list[dict] = []
                            if flow_err:
                                extra.append({
                                    "severity": "warn",
                                    "kind": "interaction-failed",
                                    "message": (
                                        f"Interaction `{flow.name}` failed: "
                                        f"{flow_err}"
                                    ),
                                    "interaction": flow.name,
                                })
                                print(f"    {YELLOW}warn:{RESET} flow "
                                      f"`{flow.name}`: {flow_err}")
                            flow_entry = _capture_cell(
                                page=page, bag=bag, axe_source=axe_source,
                                theme=theme, vp=vp, slug=flow_slug,
                                inspect=INSPECT_SELECTORS.get(route.slug, []),
                                url=url, out_dir=vp_dir, nav_error=nav_error,
                                extra_findings=extra,
                            )
                            if flow_entry:
                                flow_entry["interaction"] = flow.name
                                manifest["shots"].append(flow_entry)
                # `view-transition-fires-on-click` — once per viewport,
                # navigate to a listing route, click the first internal
                # card link, and assert a real cross-document View
                # Transition fires (i.e. `pagereveal.viewTransition` is
                # not null on the destination doc). This catches the
                # regression class where the static collision check
                # passes (no duplicates) but the transition silently
                # aborts at runtime — e.g. a content-security-policy
                # breaking the inline pageswap script, or a
                # `view-transition-name` attached to an off-screen
                # element so Chrome considers the morph empty.
                vt_probe_findings = _probe_view_transitions_click(
                    ctx, server_url, vp.name,
                )
                for entry in vt_probe_findings:
                    manifest.setdefault("vt_probes", []).append(entry)
                ctx.close()
        finally:
            browser.close()

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Diff engine (Pillow per-pixel with anti-aliasing tolerance)
# ---------------------------------------------------------------------------
def diff_images(baseline_path: Path, current_path: Path, diff_out_path: Path,
                channel_tolerance: int = 8) -> dict:
    """Compare two PNGs. Returns {'changed_pct': float, 'changed_px': int,
    'total_px': int, 'baseline_size': (w,h), 'current_size': (w,h)}.

    Strategy:
      * If sizes differ, return changed_pct=100.0 (we don't try to
        align). The baseline should be regenerated when viewport sizes
        change.
      * Otherwise count pixels whose max per-channel delta exceeds
        `channel_tolerance` (default 8/255 ≈ 3%). Anti-aliasing,
        sub-pixel font rendering, and gradient banding can produce
        small deltas across thousands of pixels even when the design
        hasn't changed; the tolerance suppresses that noise.
      * The diff PNG visualises changed pixels in red on the current
        image so the agent can read the file and see WHERE the drift
        is, not just THAT it drifted.
    """
    from PIL import Image, ImageChops

    base = Image.open(baseline_path).convert("RGB")
    cur = Image.open(current_path).convert("RGB")
    if base.size != cur.size:
        # Render a side-by-side strip so the user can see both.
        from PIL import ImageDraw
        w = max(base.size[0], cur.size[0])
        h = base.size[1] + cur.size[1] + 30
        strip = Image.new("RGB", (w, h), (40, 40, 40))
        strip.paste(base, (0, 0))
        strip.paste(cur, (0, base.size[1] + 30))
        d = ImageDraw.Draw(strip)
        d.text((10, base.size[1] + 5),
               f"size mismatch: baseline {base.size} vs current {cur.size}",
               fill=(255, 200, 0))
        diff_out_path.parent.mkdir(parents=True, exist_ok=True)
        strip.save(diff_out_path)
        return {
            "changed_pct": 100.0,
            "changed_px": -1,
            "total_px": base.size[0] * base.size[1],
            "baseline_size": list(base.size),
            "current_size": list(cur.size),
            "size_mismatch": True,
        }

    raw_diff = ImageChops.difference(base, cur)
    # Per-pixel max channel delta, then threshold.
    bands = list(raw_diff.split())  # R, G, B
    px = bands[0].load()
    w, h = raw_diff.size
    changed = 0
    # Build an overlay starting from the current image; paint pixels
    # that exceed tolerance in red so the agent can see drift location.
    overlay = cur.copy()
    op = overlay.load()
    rp = bands[0].load()
    gp = bands[1].load()
    bp_ = bands[2].load()
    for y in range(h):
        for x in range(w):
            if max(rp[x, y], gp[x, y], bp_[x, y]) > channel_tolerance:
                changed += 1
                op[x, y] = (255, 0, 0)
    diff_out_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(diff_out_path)
    total = w * h
    return {
        "changed_pct": (changed / total) * 100.0 if total else 0.0,
        "changed_px": changed,
        "total_px": total,
        "baseline_size": list(base.size),
        "current_size": list(cur.size),
        "size_mismatch": False,
    }


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------
def _start_shoot_on_demand_endpoint(theme: str, server_state: dict, http_port: int):
    """Run a tiny single-threaded HTTP server inside `cmd_serve`.

    Phase 2 (closed-loop dispatcher) talks to this so the dispatch
    daemon doesn't pay the ~127s Playground cold-boot cost on every
    iteration; the warm server captures in ~3s of pure Playwright.

    `server_state` is a *mutable* dict shared with the cmd_serve
    supervisor loop so a Phase 3 ``--persistent`` restart can swap
    in the new ``url`` (and bump ``boots``) without tearing down the
    HTTP listener. Required keys: ``url`` (str) and ``alive`` (bool).
    The supervisor sets ``alive=False`` while a restart is in flight
    so /shoot returns 503 instead of trying to talk to a dead worker.

    Endpoints:
        GET  /health                        -> {"ok":true,"theme":...,"url":...,
                                                "alive":true,"boots":N}
        POST /shoot {route|routes,
                     viewport|viewports}    -> {"ok":true,"elapsed_s":..,
                                                "manifest":{...},
                                                "findings":[...]}
        POST /shutdown                      -> {"ok":true}; lets the
                                               supervisor restart the
                                               server when it wedges.
        POST /restart                       -> {"ok":true}; signals the
                                               supervisor to kill +
                                               re-boot Playground while
                                               keeping the HTTP listener
                                               warm.

    Single-threaded on purpose (HTTPServer, not ThreadingHTTPServer):
    Playwright shoots are CPU+IO heavy and Playground itself is a
    single-PHP-instance process, so concurrent shoots against the
    same warm server would race for the same wasm runtime that gives
    us "PHP instance already acquired" anyway.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    out_root = SNAPS_DIR / theme
    lock = threading.Lock()
    shutdown_event = threading.Event()
    restart_event = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"shoot-on-demand: {fmt % args}", flush=True)

        def _json(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._json(
                    200,
                    {
                        "ok": bool(server_state.get("alive")),
                        "theme": theme,
                        "url": server_state.get("url"),
                        "alive": bool(server_state.get("alive")),
                        "boots": int(server_state.get("boots", 0)),
                    },
                )
            else:
                self._json(404, {"error": "GET /health only"})

        def do_POST(self):
            if self.path == "/shutdown":
                self._json(200, {"ok": True})
                shutdown_event.set()
                return
            if self.path == "/restart":
                self._json(200, {"ok": True})
                restart_event.set()
                return
            if self.path != "/shoot":
                self._json(404, {"error": "POST /shoot, /restart or /shutdown only"})
                return
            if not server_state.get("alive"):
                self._json(
                    503,
                    {"error": "playground server is restarting; try again in a few seconds."},
                )
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw or "{}")
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"error": f"bad json: {e}"})
                return

            req_routes = payload.get("routes")
            if not req_routes and payload.get("route"):
                req_routes = [payload["route"]]
            req_vps = payload.get("viewports")
            if not req_vps and payload.get("viewport"):
                req_vps = [payload["viewport"]]

            try:
                routes = filter_routes(req_routes)
                viewports = filter_viewports(req_vps)
            except Exception as e:
                self._json(400, {"error": str(e)})
                return
            if not routes or not viewports:
                self._json(400, {"error": "no matching routes or viewports"})
                return

            with lock:
                t0 = time.time()
                try:
                    manifest = shoot_theme(theme, server_state["url"], routes, viewports, out_root)
                except SystemExit as e:
                    self._json(500, {"error": f"shoot exited: {e}"})
                    return
                except Exception as e:
                    self._json(500, {"error": f"shoot crashed: {e}"})
                    return
                elapsed = round(time.time() - t0, 2)

            captured: list[dict] = []
            for r in routes:
                for v in viewports:
                    findings_path = out_root / v.name / f"{r.slug}.findings.json"
                    if not findings_path.is_file():
                        continue
                    try:
                        captured.append(
                            {
                                "route": r.slug,
                                "viewport": v.name,
                                "findings_file": str(
                                    findings_path.relative_to(REPO_ROOT)
                                ),
                                "findings": json.loads(
                                    findings_path.read_text(encoding="utf-8")
                                ),
                            }
                        )
                    except (OSError, json.JSONDecodeError):
                        pass

            self._json(
                200,
                {
                    "ok": True,
                    "elapsed_s": elapsed,
                    "theme": theme,
                    "manifest": manifest,
                    "findings": captured,
                },
            )

    httpd = HTTPServer(("127.0.0.1", http_port), _Handler)
    threading.Thread(
        target=httpd.serve_forever, name="shoot-on-demand", daemon=True
    ).start()
    return httpd, shutdown_event, restart_event


def _snap_server_pidfile(theme: str) -> Path:
    """Per-theme PID file used by `serve --persistent` so other tools
    (`bin/dispatch-watch.py`, `bin/fix-loop.py`) can detect a warm
    server before paying the ~127s cold-boot cost. Phase 3
    (``phase3-warm-supervisor``)."""
    return TMP_DIR / f"snap-server-{theme}.pid"


def _write_snap_server_pidfile(theme: str, http_port: int | None) -> Path:
    """Write {pid, theme, http_port, started_at} so peer tools can both
    confirm liveness (kill -0) and discover the shoot-on-demand port."""
    pf = _snap_server_pidfile(theme)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "theme": theme,
                "http_port": http_port,
                "started_at": int(time.time()),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return pf


def cmd_serve(args: argparse.Namespace) -> int:
    """Boot a single theme's playground and block until Ctrl-C.

    Useful when the agent wants to drive the site interactively via the
    cursor-ide-browser MCP, since that MCP CAN navigate to a localhost
    URL (it just can't run playground.wordpress.net's wasm engine).

    With ``--shoot-on-demand [PORT]`` (Phase 2) we additionally start a
    single-threaded HTTP server on PORT (default 9501) that the
    dispatch-watch daemon talks to so subsequent shoots reuse the same
    warm Playground -- ~3s instead of ~127s per shot.

    With ``--persistent`` (Phase 3 ``phase3-warm-supervisor``) we wrap
    the boot in a supervisor loop that auto-restarts the underlying
    Playground when its wasm worker dies. The HTTP listener stays up
    across restarts so the dispatch daemon doesn't reconnect on every
    crash. A PID file at ``tmp/snap-server-<theme>.pid`` lets peer
    tools detect the warm server before paying cold-boot cost.

    Boot uses ``boot_and_wait`` so the wasm PHP-instance race is
    retried transparently (Phase 3 ``phase3-boot-retry``).
    """
    theme = args.theme
    port = args.port
    cache_state = bool(getattr(args, "cache_state", False))
    persistent = bool(getattr(args, "persistent", False))
    if cache_state and getattr(args, "reset_cache", False):
        cleared = reset_state_cache(theme)
        print(f"  cleared state cache at {cleared}")
    shoot_port = (
        args.shoot_on_demand
        if getattr(args, "shoot_on_demand", None) is not None
        else None
    )
    if shoot_port is not None and shoot_port == 0:
        shoot_port = 9501

    pidfile = (
        _write_snap_server_pidfile(theme, shoot_port) if persistent else None
    )

    print(
        f"Booting {GREEN}{theme}{RESET} on port {port or '(auto)'}"
        f"{' [cache-state]' if cache_state else ''}"
        f"{' [persistent]' if persistent else ''}..."
    )

    # Mutable state shared with the HTTP listener so a restart can
    # swap in the new url + bump boots without tearing down the
    # listener thread. See `_start_shoot_on_demand_endpoint`.
    server_state: dict = {"url": "", "alive": False, "boots": 0}
    httpd = None
    shutdown_event = None
    restart_event = None

    def _start_listener_if_needed() -> None:
        nonlocal httpd, shutdown_event, restart_event
        if shoot_port is None or httpd is not None:
            return
        httpd, shutdown_event, restart_event = _start_shoot_on_demand_endpoint(
            theme, server_state, shoot_port
        )
        print(
            f"  Shoot-on-demand: http://127.0.0.1:{shoot_port}/shoot"
            f"   (POST {{\"route\":..,\"viewport\":..}})"
        )
        print(
            f"                   http://127.0.0.1:{shoot_port}/health"
            f"   (GET)"
        )

    server: Server | None = None
    try:
        while True:
            # `serve` is the interactive subcommand; --login keeps the
            # agent and the user logged-in for cursor-ide-browser MCP
            # poking and /wp-admin access. `shoot` overrides this to
            # capture logged-out visitor view.
            try:
                server = boot_and_wait(
                    theme, port=port, verbosity=args.verbosity, login=True,
                    cache_state=cache_state,
                )
            except SystemExit as e:
                if not persistent:
                    raise
                # In persistent mode we don't want a single bad boot
                # to take the whole supervisor down. Sleep and retry.
                print(f"{RED}boot failed:{RESET} {e}\n  retrying in 30s...")
                time.sleep(30.0)
                continue

            server_state["url"] = server.url
            server_state["alive"] = True
            server_state["boots"] += 1

            print(
                f"\n{GREEN}Ready{RESET}: {server.url}/"
                f"   (boot #{server_state['boots']})"
            )
            print(f"  Login at: {server.url}/wp-admin/  (admin / password)")
            print(f"  Logs streaming to: {server.log_path}")

            _start_listener_if_needed()

            if persistent:
                print(
                    "  Persistent supervisor active: server will auto-restart "
                    "if Playground dies. Press Ctrl-C to stop."
                )
                if pidfile is not None:
                    print(f"  PID file: {pidfile}")
            else:
                print("  Press Ctrl-C to stop.\n")

            try:
                while server.proc.poll() is None:
                    if shutdown_event is not None and shutdown_event.is_set():
                        print("Shutdown requested via HTTP /shutdown.")
                        return 0
                    if restart_event is not None and restart_event.is_set():
                        print("Restart requested via HTTP /restart.")
                        restart_event.clear()
                        break
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nStopping...")
                return 0

            # Server died (either crash or /restart). Drop alive flag
            # so /shoot returns 503 while we boot the replacement.
            server_state["alive"] = False
            kill_server(server)
            server = None
            if not persistent:
                # One-shot serve: exit when the inner process dies.
                return 0
            print(
                f"{YELLOW}playground server died (exit "
                f"{'?' if not server else server.proc.returncode}); "
                f"restarting in 5s...{RESET}"
            )
            time.sleep(5.0)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        if server is not None:
            kill_server(server)
        if pidfile is not None and pidfile.exists():
            try:
                pidfile.unlink()
            except OSError:
                pass


def _plan_skip_cells(
    theme: str, routes: list[Route], viewports: list[Viewport],
    skip_unchanged: bool,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], dict]]:
    """Compute which (viewport, route) cells can be skipped for this theme.

    Returns a pair:
      * skip_cells: set of (vp_name, route_slug) that have a matching
                    signature + baseline PNG. These are materialized
                    directly into tmp/snaps/ by the caller; the
                    Playwright loop is told to skip them.
      * signatures: dict of (vp_name, route_slug) -> current signature
                    for every cell. The shoot path reuses the signature
                    when writing tmp/snaps/<slug>.sig.json so it doesn't
                    recompute the same hash twice.

    When skip_unchanged is False (e.g. `--no-skip`, rebaseline mode, or
    FIFTY_FORCE_RESHOOT=1 globally) the skip_cells set is always empty;
    signatures are still computed so they can be stamped alongside the
    freshly-shot PNGs for the next run to benefit from.
    """
    skip_cells: set[tuple[str, str]] = set()
    sigs: dict[tuple[str, str], dict] = {}
    # Signature only varies on (theme, route) -- the viewport doesn't
    # change which files feed the render. Compute once per route, reuse.
    sig_by_route: dict[str, dict] = {}
    for r in routes:
        sig_by_route[r.slug] = compute_route_signature(theme, r.slug)
    for vp in viewports:
        for r in routes:
            sig = sig_by_route[r.slug]
            sigs[(vp.name, r.slug)] = sig
            if skip_unchanged and _should_skip_cell(theme, vp.name, r.slug, sig):
                skip_cells.add((vp.name, r.slug))
    return skip_cells, sigs


def _shoot_one_theme(theme: str, routes: list[Route],
                     viewports: list[Viewport], port: int | None,
                     verbosity: str,
                     cache_state: bool = False,
                     skip_unchanged: bool = True) -> tuple[str, str | None]:
    """Worker used by both the serial and concurrent shoot paths.

    Returns (theme, error) -- error is None on success, otherwise the
    exception message. We never raise here so a single bad theme
    doesn't abort the whole sweep.

    `skip_unchanged=True` (the Phase 2 default) triggers the per-cell
    signature check: cells whose (deps, snap engine, cli pin) signature
    matches the baseline's stored sig have their baseline PNG copied
    into tmp/snaps/ and are removed from the Playwright loop. If every
    cell in the requested matrix can be skipped we never even boot
    Playground -- the only cost is O(files-in-theme) sha256s.
    """
    out_root = SNAPS_DIR / theme
    skip_cells, sigs = _plan_skip_cells(theme, routes, viewports, skip_unchanged)

    # Materialize skipped cells up front so the findings/sig/png tree
    # is populated regardless of what happens in the Playwright path.
    for (vp_name, slug) in skip_cells:
        _materialize_skipped_cell(theme, vp_name, slug, sigs[(vp_name, slug)])

    total_cells = len(routes) * len(viewports)
    if skip_cells:
        print(
            f"  {DIM}{theme}: reusing baseline for {len(skip_cells)} / "
            f"{total_cells} cell(s) (signature match){RESET}"
        )
    if len(skip_cells) == total_cells:
        # Everything up-to-date -- skip the Playground boot entirely.
        # This is the core Phase 2 win at 100 themes: a no-theme-diff
        # push pays only an O(files) sha256 cost per theme, no browser.
        return theme, None

    try:
        with running_server(
            theme, port=port, verbosity=verbosity, cache_state=cache_state,
        ) as server:
            shoot_theme(
                theme, server.url, routes, viewports, out_root,
                skip_cells=skip_cells, signatures=sigs,
            )
    except SystemExit as e:
        return theme, f"failed: {e}"
    except Exception as e:
        return theme, f"crashed: {e}"
    return theme, None


def cmd_shoot(args: argparse.Namespace) -> int:
    """Boot, capture, kill -- repeated per theme.

    Default is serial. `--concurrency=N` boots up to N themes in
    parallel (each on its own port chosen via find_free_port) which
    drops a 4-theme sweep from ~16min to ~4min. The cost is RAM (each
    Playground worker eats ~400MB) and CPU during the screenshot pass.

    `--changed` (Phase 5) restricts the sweep to themes whose files
    changed since `--changed-base` (default = uncommitted tree). When
    bin/* changed (framework-wide), the smart filter falls back to
    --all so we don't ship a stale sweep after a heuristic update.
    """
    if getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            print(f"{DIM}--changed: framework files touched, "
                  f"falling back to all themes.{RESET}")
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, nothing to shoot.{RESET}")
            return 0
        else:
            themes = affected
            print(f"{DIM}--changed: shooting only {', '.join(themes)}.{RESET}")
    elif args.all:
        themes = discover_themes()
    else:
        themes = [args.theme] if args.theme else []
    if not themes:
        raise SystemExit("Pass a theme name or --all.")

    base_routes = filter_routes(args.routes or (sorted(QUICK_ROUTES) if args.quick else None))
    viewports = filter_viewports(args.viewports or (sorted(QUICK_VIEWPORTS) if args.quick else None))
    concurrency = max(1, getattr(args, "concurrency", 1) or 1)
    if concurrency > len(themes):
        concurrency = len(themes)

    # Per-theme route narrowing with --auto-routes. The manifest lives in
    # snap_config.ROUTE_DEPENDENCIES / ROUTE_GLOBAL_GLOBS; the diff is
    # scoped per-theme because each theme has independently-changing
    # files (the framework-wide case short-circuits via _changed_routes
    # returning None, which we fall back to `base_routes` -- i.e. no
    # narrowing).
    auto_routes = bool(getattr(args, "auto_routes", False))
    changed_base = getattr(args, "changed_base", None)
    theme_routes: dict[str, list[Route]] = {}
    total_cells = 0
    for theme in themes:
        if auto_routes:
            narrowed = _changed_routes(theme, changed_base)
            if narrowed is None:
                # Framework / global change -> every route for this theme.
                theme_routes[theme] = base_routes
                print(
                    f"  {DIM}--auto-routes: {theme} has global/framework "
                    f"changes -> all {len(base_routes)} routes{RESET}"
                )
            else:
                # Intersect with base_routes so --routes / --quick still wins.
                allowed = {r.slug for r in base_routes}
                picked = [r for r in base_routes if r.slug in narrowed and r.slug in allowed]
                theme_routes[theme] = picked
                if picked:
                    print(
                        f"  {DIM}--auto-routes: {theme} -> "
                        f"{', '.join(r.slug for r in picked)}{RESET}"
                    )
                else:
                    print(
                        f"  {DIM}--auto-routes: {theme} has no "
                        f"route-relevant changes -> skipped{RESET}"
                    )
        else:
            theme_routes[theme] = base_routes
        total_cells += len(theme_routes[theme]) * len(viewports)

    # Drop themes that ended up with zero routes after auto-narrowing
    # so the shoot loop doesn't pay for an empty Playground boot.
    themes = [t for t in themes if theme_routes[t]]
    if not themes:
        print(f"{GREEN}--auto-routes: no stale (theme, route) cells; nothing to shoot.{RESET}")
        return 0

    print(
        f"Shooting {len(themes)} theme(s) across "
        f"{len(viewports)} viewport(s) = "
        f"{total_cells} screenshot(s)"
        f"  [concurrency={concurrency}]\n"
    )

    failures: list[tuple[str, str]] = []

    cache_state = bool(getattr(args, "cache_state", False))
    if cache_state and getattr(args, "reset_cache", False):
        for theme in themes:
            cleared = reset_state_cache(theme)
            print(f"  cleared state cache at {cleared}")

    # Phase 2 skip logic: on by default. `--no-skip` (CLI) or the
    # `FIFTY_FORCE_RESHOOT=1` env var (universal, honored by
    # `_should_skip_cell` too) force a full reshoot. We OR them here so
    # flipping the env var in CI covers both the outer plan step and any
    # recursive invocations the worker might trigger.
    skip_unchanged = not bool(getattr(args, "no_skip", False))
    if os.environ.get("FIFTY_FORCE_RESHOOT") == "1":
        skip_unchanged = False
    if not skip_unchanged:
        print(f"{DIM}(skip-when-unchanged disabled; every cell will be "
              f"shot from scratch){RESET}")

    if concurrency == 1 or len(themes) == 1:
        for theme in themes:
            print(f"=== {GREEN}{theme}{RESET} ===")
            t, err = _shoot_one_theme(
                theme, theme_routes[theme], viewports, args.port, args.verbosity,
                cache_state=cache_state,
                skip_unchanged=skip_unchanged,
            )
            if err:
                print(f"{RED}{t} {err}{RESET}")
                failures.append((t, err))
    else:
        # Parallel theme shoots. Use a thread pool because the worker
        # is dominated by subprocess + network I/O, not Python CPU
        # work; threads keep the impl simple (no need to pickle the
        # Playwright handles).
        import concurrent.futures
        print(f"{DIM}(parallel mode: per-theme logs in tmp/<theme>-server.log){RESET}\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            # `port=None` so each worker picks its own free port; the
            # find_free_port() call inside boot_server walks 9400-9499
            # and is concurrent-safe because the bind happens via
            # subprocess.Popen immediately after.
            futures = {
                ex.submit(_shoot_one_theme, theme, theme_routes[theme], viewports,
                          None, args.verbosity, cache_state,
                          skip_unchanged): theme
                for theme in themes
            }
            for fut in concurrent.futures.as_completed(futures):
                t, err = fut.result()
                if err:
                    print(f"{RED}=== {t}: {err} ==={RESET}")
                    failures.append((t, err))
                else:
                    print(f"=== {GREEN}{t}{RESET}: done ===")

    print()
    if failures:
        print(f"{RED}done with {len(failures)} failure(s).{RESET}")
        for t, err in failures:
            print(f"  {RED}{t}:{RESET} {err}")
        return 1
    print(f"{GREEN}done.{RESET} Snaps in {SNAPS_DIR.relative_to(REPO_ROOT)}/")
    print(
        f"      Run {DIM}python3 bin/snap.py report{RESET} for a "
        f"per-route findings summary."
    )
    return 0


def cmd_touch(args: argparse.Namespace) -> int:
    """Bump `tmp/snaps/<theme>/**/*.findings.json` mtimes without re-shooting.

    Why this exists
    ---------------
    `check_evidence_freshness` (bin/check.py) fails when a theme source
    file is newer than the newest findings.json under tmp/snaps/<theme>/.
    The intent is right -- stale snaps hide regressions -- but the
    mechanism is blunt: *any* edit to theme.json/templates/parts triggers
    a 3-5 min full re-shoot per theme, even when the edit is provably
    non-visual for every cell we capture (e.g. a Phase-BB
    `@media (max-width:781px){...}` rule that only affects a tap-target
    floor already satisfied by every mobile snap, or an idempotent
    `bin/append-wc-overrides.py --update` pass that injects bytes-
    identical CSS into every theme.json).

    `touch` is the documented escape hatch: bump mtimes to now, log the
    edit + operator-supplied reason to tmp/snap-touch-log.jsonl, and
    move on. The audit log makes misuse legible (grep for themes you
    expect to be re-shot and confirm a finite list of touches instead of
    a forever-growing one). Pre-push's own visual gate still re-shoots
    the full matrix, so nothing merges blind.

    Usage
    -----
      bin/snap.py touch <theme>          --reason "<why it's safe>"
      bin/snap.py touch --all            --reason "idempotent theme.json resync"
      bin/snap.py touch foundry --dry-run --reason "..."

    Guardrails
    ----------
    * `--reason` is required and must be >=12 chars (forces a real
      sentence, not "fix" or "x").
    * Refuses to operate on a theme whose findings directory is missing
      or empty (we can't touch evidence that doesn't exist).
    * Prints the touched count per theme + writes a JSONL audit entry
      keyed by ISO timestamp, theme, HEAD sha, reason, and file count.
    """
    reason = (getattr(args, "reason", "") or "").strip()
    if len(reason) < 12:
        raise SystemExit(
            "--reason is required and must be at least 12 characters "
            "(documents why it's safe to skip a re-shoot). See "
            "`bin/snap.py touch --help` for the rationale."
        )

    if getattr(args, "all", False):
        themes = discover_themes()
    elif args.theme:
        themes = [args.theme]
    else:
        raise SystemExit("Pass a theme name or --all.")

    dry_run = bool(getattr(args, "dry_run", False))

    try:
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "unknown"
    except Exception:
        head_sha = "unknown"

    audit_log = TMP_DIR / "snap-touch-log.jsonl"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    iso = datetime.datetime.utcfromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_touched = 0
    for theme in themes:
        theme_snaps = SNAPS_DIR / theme
        if not theme_snaps.is_dir():
            print(f"{RED}skip {theme}:{RESET} no snaps dir at {theme_snaps}. "
                  f"Run `bin/snap.py shoot {theme}` first.")
            continue
        findings = sorted(theme_snaps.rglob("*.findings.json"))
        if not findings:
            print(f"{RED}skip {theme}:{RESET} no findings.json files under "
                  f"{theme_snaps}. Run `bin/snap.py shoot {theme}` first.")
            continue
        for f in findings:
            if not dry_run:
                os.utime(f, (now, now))
        total_touched += len(findings)
        action = "would touch" if dry_run else "touched"
        print(f"  {GREEN}{theme}{RESET}: {action} {len(findings)} findings file(s)")

        if not dry_run:
            entry = {
                "at": iso,
                "theme": theme,
                "head_sha": head_sha,
                "files_touched": len(findings),
                "reason": reason,
            }
            with open(audit_log, "a", encoding="utf-8") as h:
                h.write(json.dumps(entry) + "\n")

    if dry_run:
        print(f"\n{DIM}dry-run: no mtimes changed, no audit entry written.{RESET}")
    else:
        print(f"\n{GREEN}done.{RESET} Bumped {total_touched} findings file mtime(s). "
              f"Audit entry appended to {audit_log.relative_to(REPO_ROOT)}.")
        print(
            f"{YELLOW}NOTE:{RESET} pre-push still runs its own visual gate "
            f"(FIFTY_SKIP_EVIDENCE_FRESHNESS=1) -- nothing merges blind."
        )
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Promote tmp/snaps/<theme>/<vp>/<slug>.png -> tests/visual-baseline/...

    With no further args: copies all latest snaps. With explicit
    `theme [route [viewport]]`: copies just that subset. The destination
    tree mirrors the source layout so diffs are trivial path lookups.
    """
    if not SNAPS_DIR.exists():
        raise SystemExit(
            f"No snaps to promote at {SNAPS_DIR}. Run "
            f"`bin/snap.py shoot --all` first."
        )

    if getattr(args, "missing_only", False) and getattr(args, "rebaseline", False):
        raise SystemExit("--missing-only and --rebaseline are mutually exclusive")
    missing_only = getattr(args, "missing_only", False)

    themes = [args.theme] if args.theme else discover_themes()
    promoted = 0
    skipped = 0
    for theme in themes:
        src_root = SNAPS_DIR / theme
        if not src_root.exists():
            continue
        for vp_dir in src_root.iterdir():
            if not vp_dir.is_dir():
                continue
            if args.viewport and vp_dir.name != args.viewport:
                continue
            for png in vp_dir.glob("*.png"):
                if args.route and png.stem != args.route:
                    continue
                rel = png.relative_to(SNAPS_DIR)
                dst = BASELINE_DIR / rel
                if missing_only and dst.exists():
                    skipped += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png, dst)
                promoted += 1
                print(f"  baselined: {rel}")

                # Phase 2: promote the signature + per-cell evidence so
                # a subsequent run with unchanged inputs can skip this
                # cell entirely via `_should_skip_cell`. We only promote
                # files that share the PNG's stem (i.e. the static cell
                # OR a specific interaction flow); interaction-scoped
                # artifacts don't have their own sig but DO benefit from
                # findings/a11y promotion so the skip-copy path can
                # surface them. Missing side-files are silently skipped
                # -- older snaps predating Phase 2 simply won't have
                # them, and that's fine (we'll degrade to the stub
                # findings.json path on skip-copy).
                stem = png.stem
                side_files = [
                    f"{stem}.sig.json",
                    f"{stem}.findings.json",
                    f"{stem}.a11y.json",
                    f"{stem}.html",
                ]
                for side in side_files:
                    src_side = vp_dir / side
                    if not src_side.is_file():
                        continue
                    dst_side = dst.parent / side
                    shutil.copy2(src_side, dst_side)

    suffix = f" ({skipped} skipped, already existed)" if missing_only and skipped else ""
    print(f"\n{GREEN}done.{RESET} {promoted} baseline(s) updated under "
          f"{BASELINE_DIR.relative_to(REPO_ROOT)}/{suffix}")
    return 0


# ---------------------------------------------------------------------------
# `rebaseline` subcommand: targeted bulk re-baselining (Tier 1.4 of the
# pre-100-themes hardening plan).
# ---------------------------------------------------------------------------
#
# Motivation: once we have 50+ themes, "WordPress shipped a new default
# style, re-snap everything" turns into a 3 hour job. `cmd_baseline` is
# fine for a known-intentional change to one theme, but for a fleet-
# wide sweep you want a safer, staged flow:
#
#   1. Spot-check WHICH cells actually drifted (not every theme will have
#      changed -- the change might be scoped to WC blocks used only by 3
#      themes).
#   2. Optionally filter to baselines older than X days (trust recent
#      baselines; revisit stale ones).
#   3. Dry-run first so the operator can eyeball the scope before writing
#      any file under `tests/visual-baseline/`.
#   4. Then commit the narrow promotion in one go.
#
# That's exactly `rebaseline`. It shares the bulk of `cmd_baseline`'s
# file-copy path (including the Phase 2 sidecar promotion) but gates
# every cell on a drift predicate.
#
# Flags:
#   --drifted           only cells whose diff > threshold
#   --since <when>      only cells whose current baseline is older than
#                       the given time spec (ISO date, "7d", "2h", etc.)
#   --dry-run           don't copy, print what WOULD be touched
#   --threshold <pct>   the drift gate for --drifted (default 0.5%)
#   --all / <theme>     scope to every discoverable theme / one theme
#
# Exit code: 0 if everything that matched the filter was promoted
# (or would have been, in dry-run); 1 on any I/O failure or if an
# inconsistent filter combination is passed.

_DURATION_RE = _re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw])$", _re.IGNORECASE)


def _parse_since(spec: str) -> float | None:
    """Turn `--since` value into a POSIX timestamp threshold.

    Accepts:
      * ISO-ish dates (`2026-04-01`, `2026-04-01T12:00:00`)
      * Relative durations: `7d`, `24h`, `2w`, `30s`.

    Returns the unix timestamp such that a baseline mtime <= threshold
    is "stale". `None` => do not apply a time filter.
    """
    if not spec:
        return None
    m = _DURATION_RE.match(spec)
    if m:
        n = float(m.group(1))
        unit = m.group(2).lower()
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}[unit]
        return time.time() - n * mult
    # Try ISO parse. datetime.fromisoformat covers the common cases;
    # trailing 'Z' gets normalized because fromisoformat doesn't accept
    # it on <3.11.
    norm = spec.strip().rstrip("Z")
    try:
        dt_obj = datetime.datetime.fromisoformat(norm)
    except ValueError as e:
        raise SystemExit(
            f"--since: unparseable time spec {spec!r}; "
            "use `7d`, `24h`, or ISO like `2026-04-01`."
        ) from e
    if dt_obj.tzinfo is None:
        # snap.py's import block is already non-compliant on main for
        # `datetime` (`datetime.timezone.utc` vs `datetime.UTC`); staying
        # on the older idiom keeps this diff additive.
        dt_obj = dt_obj.replace(tzinfo=datetime.timezone.utc)  # noqa: UP017
    return dt_obj.timestamp()


def cmd_rebaseline(args: argparse.Namespace) -> int:
    """Targeted bulk re-baselining (see module-level docstring above).

    Flow per theme:
      1. Walk `tmp/snaps/<theme>/<vp>/*.png` (latest shoot).
      2. For each cell, compute the drift vs the current baseline (if
         any), plus the baseline's mtime.
      3. Filter: cell must match `--drifted` (if set) AND/OR be older
         than `--since` (if set). No filters = every cell is eligible,
         which is just `cmd_baseline --all` and we nudge the operator
         toward that instead of silently doing it.
      4. In `--dry-run`, print what would change. Otherwise copy the PNG
         + sidecar files (same list cmd_baseline uses) into
         `tests/visual-baseline/` and increment a counter.
    """
    if not SNAPS_DIR.exists():
        raise SystemExit(
            f"No snaps to rebaseline at {SNAPS_DIR}. Run "
            "`bin/snap.py shoot --all` first."
        )

    drifted = bool(getattr(args, "drifted", False))
    since_ts = _parse_since(getattr(args, "since", "") or "")
    if not drifted and since_ts is None:
        raise SystemExit(
            "rebaseline: pass at least one of --drifted or --since. "
            "For a no-filter bulk promotion, use `bin/snap.py baseline --all` "
            "(that path exists on purpose -- rebaseline is the *filtered* "
            "version)."
        )

    dry_run = bool(getattr(args, "dry_run", False))
    threshold = float(getattr(args, "threshold", 0.5))
    channel_tolerance = int(getattr(args, "channel_tolerance", 8))

    themes: list[str]
    if getattr(args, "theme", None):
        themes = [args.theme]
    else:
        themes = discover_themes()
    if not themes:
        raise SystemExit("rebaseline: no themes found.")

    promoted = 0
    would_promote = 0
    inspected = 0
    missing_baseline = 0
    matched_drift: list[tuple[str, str, str, float]] = []
    matched_stale: list[tuple[str, str, str, float]] = []

    for theme in themes:
        src_root = SNAPS_DIR / theme
        if not src_root.exists():
            continue
        for vp_dir in sorted(src_root.iterdir()):
            if not vp_dir.is_dir():
                continue
            if getattr(args, "viewport", None) and vp_dir.name != args.viewport:
                continue
            for png in sorted(vp_dir.glob("*.png")):
                if getattr(args, "route", None) and png.stem != args.route:
                    continue
                inspected += 1
                rel = png.relative_to(SNAPS_DIR)
                dst = BASELINE_DIR / rel

                age_ok = True
                if since_ts is not None:
                    if not dst.exists():
                        # A missing baseline is the ultimate "stale"
                        # case -- it counts as a stale match so the
                        # operator can backfill brand-new cells with
                        # the same flag.
                        age_ok = True
                    else:
                        age_ok = dst.stat().st_mtime <= since_ts
                drift_ok = True
                drift_pct: float | None = None
                if drifted:
                    if not dst.exists():
                        drift_ok = True
                        drift_pct = None
                        missing_baseline += 1
                    else:
                        result = diff_images(
                            dst, png, DIFFS_DIR / rel,
                            channel_tolerance=channel_tolerance,
                        )
                        drift_pct = float(result.get("changed_pct", 0.0))
                        drift_ok = drift_pct > threshold

                matches = True
                if drifted and not drift_ok:
                    matches = False
                if since_ts is not None and not age_ok:
                    matches = False
                if not matches:
                    continue

                if drifted and drift_pct is not None:
                    matched_drift.append((theme, vp_dir.name, png.stem, drift_pct))
                if since_ts is not None and age_ok:
                    matched_stale.append(
                        (theme, vp_dir.name, png.stem,
                         dst.stat().st_mtime if dst.exists() else 0.0)
                    )

                if dry_run:
                    would_promote += 1
                    tag = (
                        f"drift={drift_pct:.3f}%" if drift_pct is not None
                        else "new" if not dst.exists()
                        else "stale"
                    )
                    print(f"  [dry-run] {tag:<16s} {rel}")
                    continue

                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png, dst)
                promoted += 1
                print(f"  rebaselined: {rel}")
                # Sidecar promotion (mirrors cmd_baseline behaviour so
                # Phase 2 signature skips still trigger on the next run).
                stem = png.stem
                for side in (
                    f"{stem}.sig.json",
                    f"{stem}.findings.json",
                    f"{stem}.a11y.json",
                    f"{stem}.html",
                ):
                    src_side = vp_dir / side
                    if src_side.is_file():
                        shutil.copy2(src_side, dst.parent / side)

    summary_lines = [
        "",
        f"rebaseline summary ({'dry-run' if dry_run else 'live'}):",
        f"  inspected:       {inspected}",
        f"  drift matches:   {len(matched_drift)}",
        f"  stale matches:   {len(matched_stale)}",
        f"  missing base:    {missing_baseline}",
        f"  { 'would promote' if dry_run else 'promoted' }:  "
        f"{would_promote if dry_run else promoted}",
    ]
    print("\n".join(summary_lines))
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare latest snaps to baselines; print a summary table."""
    threshold = args.threshold
    if getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, "
                  f"nothing to diff.{RESET}")
            return 0
        else:
            themes = affected
    else:
        themes = discover_themes() if args.all else ([args.theme] if args.theme else [])
    if not themes:
        raise SystemExit("Pass a theme name or --all.")

    rows: list[tuple] = []
    summary: dict = {"threshold_pct": threshold, "results": []}
    for theme in themes:
        snaps = SNAPS_DIR / theme
        baseline = BASELINE_DIR / theme
        if not snaps.exists():
            print(f"{YELLOW}skip{RESET} {theme}: no current snaps "
                  f"(run shoot first).")
            continue
        for vp_dir in sorted(snaps.iterdir()):
            if not vp_dir.is_dir():
                continue
            for png in sorted(vp_dir.glob("*.png")):
                rel = png.relative_to(SNAPS_DIR)
                base_path = BASELINE_DIR / rel
                diff_path = DIFFS_DIR / rel
                if not base_path.exists():
                    rows.append((theme, vp_dir.name, png.stem,
                                 None, "no-baseline", "—"))
                    continue
                result = diff_images(base_path, png, diff_path,
                                     channel_tolerance=args.channel_tolerance)
                state = (
                    "FAIL" if result["changed_pct"] > threshold else "ok"
                )
                rows.append((theme, vp_dir.name, png.stem,
                             result["changed_pct"], state,
                             str(diff_path.relative_to(REPO_ROOT))))
                summary["results"].append({
                    "theme": theme, "viewport": vp_dir.name,
                    "route": png.stem, **result, "state": state,
                })

    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    (DIFFS_DIR / "diff_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    fail_count = sum(1 for r in rows if r[4] == "FAIL")
    no_baseline = sum(1 for r in rows if r[4] == "no-baseline")
    print(f"\n{'theme':10s} {'viewport':9s} {'route':20s} "
          f"{'Δ%':>8s}  state   diff path")
    print("-" * 90)
    for theme, vp, route, pct, state, diff_path in rows:
        pct_s = f"{pct:7.3f}" if pct is not None else "    —  "
        col = (RED if state == "FAIL"
               else YELLOW if state == "no-baseline"
               else GREEN)
        print(f"{theme:10s} {vp:9s} {route:20s} {pct_s} "
              f"  {col}{state:10s}{RESET} {diff_path}")
    print("-" * 90)
    print(f"{len(rows)} compared, {fail_count} regression(s) above "
          f"{threshold}% threshold, {no_baseline} missing baseline.\n")
    if fail_count:
        print(f"{RED}FAILED{RESET}: open the diff PNGs above to see "
              f"which pixels changed.\n"
              f"If the changes are intentional, re-baseline with:\n"
              f"  python3 bin/snap.py baseline --all\n"
              f"or scope to a single cell:\n"
              f"  python3 bin/snap.py baseline <theme> --route=<slug> "
              f"--viewport=<name>")
        return 1
    return 0


_SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


# ---------------------------------------------------------------------------
# Heuristic-finding allowlist
# ---------------------------------------------------------------------------
# `tests/visual-baseline/heuristics-allowlist.json` snapshots the set of
# ERROR-tier heuristic findings that exist on the current shoot, so the
# new content-correctness checks can ship without first fixing every
# pre-existing violation. Going forward only NEW findings (anything not
# in the allowlist) fail the gate. Same pattern Stylelint, ESLint, Knip
# use for "fail on new violations only".
#
# File shape:
#   {
#     "<theme>:<viewport>:<route>": {
#       "<kind>": ["<fingerprint>", "<fingerprint>", ...]
#     }
#   }
#
# A finding's fingerprint is whatever stable identifier the heuristic
# produced -- usually the `selector`, but `duplicate-nav-block` uses
# `pair:<label_a>|<label_b>` (the two duplicate nav containers'
# aria-labels) because the offending pair is what's actionable, not
# any individual selector.

_ALLOWLIST_CACHE: dict[str, dict[str, list[str]]] | None = None


def _load_allowlist() -> dict[str, dict[str, list[str]]]:
    """Load + cache `tests/visual-baseline/heuristics-allowlist.json`.

    Missing or malformed file is treated as an empty allowlist (no
    suppressions) so the gate stays usable even on a fresh checkout
    that hasn't run `bin/snap.py allowlist regenerate` yet.
    """
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is not None:
        return _ALLOWLIST_CACHE
    if not ALLOWLIST_PATH.is_file():
        _ALLOWLIST_CACHE = {}
        return _ALLOWLIST_CACHE
    try:
        data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"{YELLOW}warn:{RESET} could not parse "
              f"{ALLOWLIST_PATH.relative_to(REPO_ROOT)} ({e}); "
              f"treating as empty.")
        _ALLOWLIST_CACHE = {}
        return _ALLOWLIST_CACHE
    if not isinstance(data, dict):
        _ALLOWLIST_CACHE = {}
        return _ALLOWLIST_CACHE
    cleaned: dict[str, dict[str, list[str]]] = {}
    for key, kinds in data.items():
        if not isinstance(kinds, dict):
            continue
        cleaned[str(key)] = {
            str(k): [str(s) for s in (v or [])]
            for k, v in kinds.items()
            if isinstance(v, list)
        }
    _ALLOWLIST_CACHE = cleaned
    return _ALLOWLIST_CACHE


def _reset_allowlist_cache() -> None:
    """Re-read the allowlist on next call. Used by `cmd_allowlist` after
    it rewrites the file so a same-process re-shoot picks up the new
    state without restarting Python."""
    global _ALLOWLIST_CACHE
    _ALLOWLIST_CACHE = None


def _finding_fingerprint(f: dict) -> str | None:
    """Stable identifier for an allowlist match. Prefer the explicit
    `fingerprint` field (heuristics emit one), fall back to `selector`.
    Returns None when neither is available -- such findings can't be
    allowlisted (correct behaviour: a finding without any address is
    an unconditional failure)."""
    fp = f.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp
    sel = f.get("selector")
    if isinstance(sel, str) and sel:
        return sel
    return None


def _allowlist_key(theme: str, viewport: str, route: str) -> str:
    """Canonical lookup key for the allowlist file."""
    return f"{theme}:{viewport}:{route}"


def _merge_allowlist_cells(
    allowlist: dict, theme: str, viewport: str, route: str
) -> dict[str, list]:
    """Return the union of the per-theme cell and the cross-theme
    `*:viewport:route` cell, so a wildcard theme entry applies to every
    theme without having to be copy-pasted into N keys.

    Wildcard precedence: if either cell marks a kind as wildcard
    (`["*"]` or empty list), the merged cell is wildcard; otherwise
    the selector lists are concatenated."""
    merged: dict[str, list] = {}
    for key in (_allowlist_key(theme, viewport, route),
                _allowlist_key("*", viewport, route)):
        cell = allowlist.get(key)
        if not cell:
            continue
        for kind, selectors in cell.items():
            existing = merged.get(kind)
            new_selectors = list(selectors) if isinstance(selectors, (list, tuple)) else []
            if existing is None:
                merged[kind] = new_selectors
                continue
            existing_wild = (not existing) or ("*" in existing)
            new_wild = (not new_selectors) or ("*" in new_selectors)
            if existing_wild or new_wild:
                merged[kind] = ["*"]
            else:
                merged[kind] = list(set(existing) | set(new_selectors))
    return merged


def _apply_allowlist_to_findings(
    theme: str, viewport: str, route: str, findings: list[dict]
) -> int:
    """Demote ERROR findings whose (kind, fingerprint) is in the
    allowlist for this (theme, viewport, route) cell. Mutates each
    matched finding in-place: `severity` becomes `info` and
    `allowlisted` is set to True. Returns the number demoted.

    Wildcard support: a cell entry whose selector list contains the
    sentinel string `"*"` (or that is empty) demotes ALL findings of
    that kind on that route, regardless of selector/fingerprint. This
    is how `vision:*` findings (which have no DOM address) get
    allowlisted: they're whole-page critiques tied to a (theme,
    viewport, route, kind) tuple, not to a node.

    Cross-theme wildcard support: an entry keyed `*:viewport:route`
    applies on top of every theme's per-route cell, so a chronic
    finding (e.g. `vision:typography-overpowered` on every theme's
    home page) can be expressed once instead of N times.

    Findings already marked `allowlisted` are left alone (idempotent
    for cmd_report re-runs against a cached findings.json)."""
    allowlist = _load_allowlist()
    cell = _merge_allowlist_cells(allowlist, theme, viewport, route)
    if not cell:
        return 0
    demoted = 0
    for f in findings:
        if f.get("severity") != "error":
            continue
        if f.get("allowlisted"):
            continue
        kind = str(f.get("kind") or "")
        if kind not in cell:
            continue
        cell_selectors = cell[kind]
        is_wildcard = (not cell_selectors) or ("*" in cell_selectors)
        fp = _finding_fingerprint(f)
        if is_wildcard or (fp is not None and fp in cell_selectors):
            f["severity"] = "info"
            f["allowlisted"] = True
            demoted += 1
    return demoted


# Tier policy (Phase 1). Tiered gate:
#   * HARD-fail (gate="fail")  -> bin/check.py --visual exits 1
#       - any heuristic finding with severity "error"
#       - any uncaught JS error (page_errs, after KNOWN_NOISE_SUBSTRINGS)
#       - any HTTP 5xx response
#       - the cell crashed during heuristics evaluation (heuristics-failed
#         is severity "warn" per JS, but it implies the page broke during
#         our probe; we don't promote it to fail by itself, just count it)
#   * SOFT-warn (gate="warn")  -> exit 0 with a loud banner
#       - any heuristic "warn" or "info"
#       - HTTP 4xx (still surfaces real bugs, but lots of WC variation
#         HEAD probes legitimately 404 so we don't block on them)
#       - any console.error (after noise filter)
#       - cross-theme parity drift (Phase 4 adds these as "warn"-severity
#         findings, so the same accounting picks them up)
#   * pass                     -> green light
#
# The classification lives in one place so the per-theme rollup, the
# cross-theme rollup, and the STATUS line all agree. Bumping a category
# from soft to hard (e.g. when we trust 4xx-detection enough) is a
# one-line change here.
_GATE_RANK = {"pass": 0, "warn": 1, "fail": 2}


def _compute_gate(summary: dict) -> str:
    """Return 'pass' | 'warn' | 'fail' for a per-theme summary dict."""
    if (summary.get("errors", 0) > 0
            or summary.get("page_errs", 0) > 0
            or summary.get("net_5xx", 0) > 0):
        return "fail"
    if (summary.get("warns", 0) > 0
            or summary.get("infos", 0) > 0
            or summary.get("net_4xx", 0) > 0
            or summary.get("console_errs", 0) > 0):
        return "warn"
    return "pass"


def _worst_gate(gates: Iterable[str]) -> str:
    worst = "pass"
    for g in gates:
        if _GATE_RANK.get(g, 0) > _GATE_RANK[worst]:
            worst = g
    return worst


def _gate_badge(gate: str, summary: dict | None = None) -> str:
    """Markdown badge line used at the top of every review.md."""
    summary = summary or {}
    if gate == "fail":
        bits = []
        if summary.get("errors"):
            bits.append(f"{summary['errors']} error")
        if summary.get("page_errs"):
            bits.append(f"{summary['page_errs']} uncaught JS")
        if summary.get("net_5xx"):
            bits.append(f"{summary['net_5xx']} HTTP 5xx")
        return f"**GATE: FAIL** ({', '.join(bits) or 'see findings below'})"
    if gate == "warn":
        bits = []
        if summary.get("warns"):
            bits.append(f"{summary['warns']} warn")
        if summary.get("infos"):
            bits.append(f"{summary['infos']} info")
        if summary.get("net_4xx"):
            bits.append(f"{summary['net_4xx']} HTTP 4xx")
        if summary.get("console_errs"):
            bits.append(f"{summary['console_errs']} console err")
        return f"**GATE: WARN** ({', '.join(bits) or 'see findings below'})"
    return "**GATE: PASS**"


def _print_status(gate: str, source: str = "snap") -> None:
    """Final STATUS line so terminal scrapers + humans both see the verdict."""
    if gate == "fail":
        col = RED
    elif gate == "warn":
        col = YELLOW
    else:
        col = GREEN
    print(f"\n{col}STATUS: {gate.upper()}{RESET}  ({source})")


def _gather_findings(themes: list[str]) -> list[dict]:
    """Walk tmp/snaps/<theme>/<vp>/*.findings.json and return a flat
    list of (theme, viewport, route, payload) tuples for the report.
    """
    out: list[dict] = []
    for theme in themes:
        snaps = SNAPS_DIR / theme
        if not snaps.exists():
            continue
        for vp_dir in sorted(snaps.iterdir()):
            if not vp_dir.is_dir():
                continue
            for fp in sorted(vp_dir.glob("*.findings.json")):
                try:
                    payload = json.loads(fp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                payload["_path"] = str(fp.relative_to(REPO_ROOT))
                out.append(payload)
    return out


def _cross_theme_parity(per_theme_payloads: dict[str, list[dict]],
                        drift_pct: float = 25.0) -> list[dict]:
    """Flag (route, viewport, selector) triples where one theme's
    measurement drifts >drift_pct% from the median of the others.

    Catches "Selvedge's cart sidebar broke and we didn't notice
    because we were looking at Obel" -- the static-PNG diff only
    catches drift vs the SAME theme's baseline; this catches drift
    BETWEEN themes that should look broadly similar at the same
    layout level.

    Returns a flat list of finding-shaped dicts (severity, kind,
    message, theme, viewport, route) so the report can render them
    inline without a special-case template.
    """
    if len(per_theme_payloads) < 3:
        # Need at least 3 themes for a meaningful median (with 2, any
        # difference is trivially > median). 4 is the current count.
        return []

    # Group payloads by (viewport, route, selector) so we can compare
    # the same cell across themes.
    by_cell: dict[tuple[str, str], dict[str, dict]] = {}
    for theme, payloads in per_theme_payloads.items():
        for p in payloads:
            key = (p.get("viewport", ""), p.get("route", ""))
            by_cell.setdefault(key, {})[theme] = p

    # Selectors whose rendered width is dominated by text content +
    # font metrics, not by theme layout. A display face like `Chango`
    # renders "Curiosities" ~50% wider than `Iowan Old Style` at the
    # same font-size — that's the whole point of choosing a distinct
    # display face per theme, not a layout regression to flag. Adding
    # a selector here opts it out of cross-theme width parity. Layout
    # containers (`.wo-archive-hero`, `.wp-block-woocommerce-product-
    # template`, etc.) stay tracked — they still catch real drift.
    PARITY_WIDTH_TEXT_INTRINSIC: set[str] = {
        ".wo-archive-hero__title",
    }

    out: list[dict] = []
    for (vp, route), per_theme in by_cell.items():
        if len(per_theme) < 3:
            continue
        # Selector-by-selector width comparison.
        selectors_seen: set[str] = set()
        for p in per_theme.values():
            for s in p.get("selectors", []):
                selectors_seen.add(s.get("selector", ""))
        for sel in selectors_seen:
            if sel in PARITY_WIDTH_TEXT_INTRINSIC:
                continue
            widths: dict[str, int] = {}
            for theme, p in per_theme.items():
                for s in p.get("selectors", []):
                    if s.get("selector") != sel:
                        continue
                    inst = (s.get("instances") or [{}])[0]
                    w = inst.get("width") or 0
                    if w > 0:
                        widths[theme] = w
            if len(widths) < 3:
                continue
            sorted_w = sorted(widths.values())
            median = sorted_w[len(sorted_w) // 2]
            if median == 0:
                continue
            for theme, w in widths.items():
                pct = abs(w - median) / median * 100.0
                if pct >= drift_pct:
                    out.append({
                        "severity": "warn",
                        "kind": "parity-drift-width",
                        "message": (
                            f"`{sel}` is {w}px on {theme} but the "
                            f"cross-theme median is {median}px "
                            f"({pct:.0f}% drift)."
                        ),
                        "theme": theme, "viewport": vp, "route": route,
                        "selector": sel,
                        "this_width": w, "median_width": median,
                    })
        # Finding-count parity: a theme that suddenly has 5x more
        # findings than its peers on the same route is probably
        # broken in a way the per-theme review missed.
        counts: dict[str, int] = {
            theme: len([f for f in p.get("findings", [])
                        if f.get("severity") in ("error", "warn")])
            for theme, p in per_theme.items()
        }
        cs = sorted(counts.values())
        median_c = cs[len(cs) // 2]
        if median_c >= 1:  # only meaningful when most themes have findings
            for theme, c in counts.items():
                if c >= median_c * 2 + 2:  # +2 floor avoids "1 vs 3" noise
                    out.append({
                        "severity": "warn",
                        "kind": "parity-drift-findings",
                        "message": (
                            f"{c} error/warn findings on {theme} for "
                            f"`{vp}/{route}` (cross-theme median {median_c})."
                        ),
                        "theme": theme, "viewport": vp, "route": route,
                        "this_count": c, "median_count": median_c,
                    })
    return out


def cmd_report(args: argparse.Namespace) -> int:
    """Aggregate `*.findings.json` into per-theme review markdown.

    Output:
      tmp/snaps/<theme>/review.md      human-readable triage list
      tmp/snaps/review.md              cross-theme rollup with the
                                       worst findings first
      tmp/snaps/review.json            machine-readable summary

    Severity buckets:
      * error  -- definitely broken (broken image, narrow sidebar,
                  PHP debug output, JS uncaught exception, 5xx response)
      * warn   -- likely a polish issue (alt missing, mid-word wrap,
                  WC info notice, 4xx response)
      * info   -- worth a glance (oversized image, missing inspect
                  selector)

    The report is written even when no findings exist so consumers
    can detect "ran cleanly" vs "never ran" from the file's mtime.
    """
    if args.theme:
        themes = [args.theme]
    elif getattr(args, "changed", False):
        affected = _changed_themes(getattr(args, "changed_base", None))
        if affected is None:
            themes = discover_themes()
        elif not affected:
            print(f"{GREEN}--changed: no theme files changed, "
                  f"nothing to report on.{RESET}")
            return 0
        else:
            themes = affected
    elif args.all:
        themes = discover_themes()
    else:
        # Default: report on whatever was last shot. Include incubating
        # themes in the "known" set — `bin/snap.py shoot` (called from
        # quick-visual.yml with `--changed`) already writes snaps under
        # `tmp/snaps/<incubating-theme>/` before this report step runs,
        # and filtering them out here reproduces the same chicken-and-
        # egg cycle that `_changed_themes` had to fix (shipping-only
        # default makes new-theme PRs invisible to every PR gate). Same
        # rationale, same fix: PR workflows MUST see both stages.
        known = set(discover_themes(stages=("shipping", "incubating")))
        themes = sorted(p.name for p in SNAPS_DIR.iterdir()
                        if p.is_dir() and p.name in known) \
            if SNAPS_DIR.exists() else []
    if not themes:
        raise SystemExit(
            "No snaps to report on. Run `bin/snap.py shoot --all` first."
        )

    rollup: list[dict] = []
    cross_theme_findings: list[tuple[dict, dict]] = []
    write_md = args.format in ("md", "both")
    write_json = args.format in ("json", "both")

    # Phase 4: cross-theme parity. Compute once for the whole report
    # so per-theme rendering can attribute parity findings to the
    # right theme alongside its own findings.
    per_theme_payloads: dict[str, list[dict]] = {
        theme: _gather_findings([theme]) for theme in themes
    }
    parity_findings = _cross_theme_parity(per_theme_payloads)
    parity_by_theme: dict[str, list[dict]] = {}
    for f in parity_findings:
        parity_by_theme.setdefault(f["theme"], []).append(f)

    for theme in themes:
        payloads = per_theme_payloads.get(theme, [])
        if not payloads:
            continue
        # Splice parity findings into this theme's per-route payloads
        # so the existing accounting (route_summary, gate) catches
        # them automatically.
        for pf in parity_by_theme.get(theme, []):
            for p in payloads:
                if (p.get("viewport") == pf["viewport"]
                        and p.get("route") == pf["route"]):
                    p.setdefault("findings", []).append(pf)
                    break

        # Apply the heuristic-finding allowlist. `_capture_cell` already
        # demotes findings at shoot time; this is a defence-in-depth pass
        # for the case where someone re-runs `bin/snap.py report` against
        # an older findings.json after editing the allowlist (or for
        # parity findings that were spliced in just above and never went
        # through `_capture_cell`).
        for p in payloads:
            _apply_allowlist_to_findings(
                theme, str(p.get("viewport", "")),
                str(p.get("route", "")),
                p.setdefault("findings", []),
            )

        # Per-route severity totals.
        route_summary: list[dict] = []
        all_findings: list[tuple[dict, dict]] = []
        for p in payloads:
            finds = p.get("findings", [])
            err = sum(1 for f in finds if f.get("severity") == "error")
            warn = sum(1 for f in finds if f.get("severity") == "warn")
            info = sum(1 for f in finds if f.get("severity") == "info")
            # Split 4xx vs 5xx so the tier policy can hard-fail on 5xx
            # alone without also failing on the noisy WC variation HEAD
            # 404 probes that fire on every product page.
            net_4xx = sum(1 for nf in p.get("network_failures", [])
                          if 400 <= nf.get("status", 0) < 500)
            net_5xx = sum(1 for nf in p.get("network_failures", [])
                          if nf.get("status", 0) >= 500)
            net_fail = net_4xx + net_5xx
            page_err = sum(1 for pe in p.get("page_errors", [])
                           if not _is_known_noise(pe))
            console_err = sum(1 for c in p.get("console", [])
                              if c.get("type") == "error"
                              and not _is_known_noise(c.get("text", "")))
            route_summary.append({
                "viewport": p["viewport"], "route": p["route"],
                "error": err, "warn": warn, "info": info,
                "net_fail": net_fail, "net_4xx": net_4xx, "net_5xx": net_5xx,
                "page_err": page_err,
                "console_err": console_err,
                "url": p.get("url", ""),
            })
            for f in finds:
                all_findings.append((p, f))
                cross_theme_findings.append((p, f))

        all_findings.sort(key=lambda pf: (
            _SEVERITY_RANK.get(pf[1].get("severity", "info"), 9),
            pf[0].get("viewport", ""), pf[0].get("route", ""),
            pf[1].get("kind", ""),
        ))

        # Per-theme summary used by both the rollup row and the gate
        # decision. Built once here so the badge at the top of review.md,
        # the JSON, and the cross-theme rollup all agree.
        theme_summary = {
            "theme": theme,
            "errors": sum(r["error"] for r in route_summary),
            "warns": sum(r["warn"] for r in route_summary),
            "infos": sum(r["info"] for r in route_summary),
            "page_errs": sum(r["page_err"] for r in route_summary),
            "console_errs": sum(r["console_err"] for r in route_summary),
            "net_fails": sum(r["net_fail"] for r in route_summary),
            "net_4xx": sum(r["net_4xx"] for r in route_summary),
            "net_5xx": sum(r["net_5xx"] for r in route_summary),
        }
        gate = _compute_gate(theme_summary)
        theme_summary["gate"] = gate

        # Per-theme markdown.
        lines: list[str] = []
        lines.append(f"# {theme} — visual review\n")
        # GATE badge is the first thing humans + agents see, so a
        # "FAIL" never gets buried under tables.
        lines.append(f"{_gate_badge(gate, theme_summary)}\n")
        lines.append(
            f"_Generated by `bin/snap.py report` from "
            f"`tmp/snaps/{theme}/**/*.findings.json`._\n"
        )
        lines.append("## Per-route summary\n")
        lines.append("| viewport | route | err | warn | info | 4xx | 5xx | console err | url |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
        for r in route_summary:
            lines.append(
                f"| {r['viewport']} | {r['route']} | {r['error']} | "
                f"{r['warn']} | {r['info']} | {r['net_4xx']} | "
                f"{r['net_5xx']} | {r['console_err']} | `{r['url']}` |"
            )
        lines.append("")

        if all_findings:
            lines.append("## Findings (worst first)\n")
            theme_dir = SNAPS_DIR / theme
            for p, f in all_findings:
                sev = f.get("severity", "info").upper()
                kind = f.get("kind", "")
                msg = f.get("message", "")
                crop = f.get("crop_path")
                crop_suffix = ""
                if crop:
                    # crop_path is repo-relative; rewrite to theme-relative
                    # so the markdown link works when review.md is opened
                    # in place at tmp/snaps/<theme>/review.md.
                    try:
                        rel = (REPO_ROOT / crop).relative_to(theme_dir)
                        crop_suffix = f" [[evidence]({rel})]"
                    except ValueError:
                        crop_suffix = f" [[evidence]({crop})]"
                allow_suffix = (
                    " _(allowlisted; demoted to info)_"
                    if f.get("allowlisted") else ""
                )
                lines.append(
                    f"- **{sev}** `{p['viewport']}/{p['route']}` "
                    f"`{kind}`: {msg}{crop_suffix}{allow_suffix}"
                )
            lines.append("")
        else:
            lines.append("## Findings\n\n_No DOM heuristic findings._\n")

        # Network failures + page errors get their own sections so a
        # 4xx that's not in `findings[]` still surfaces in triage.
        net_block: list[str] = []
        for p in payloads:
            for nf in p.get("network_failures", []):
                # Suppress the noisy WC variation HEAD probe spam.
                if nf.get("status") == 404 and "?" not in nf.get("url", ""):
                    pass
                net_block.append(
                    f"  * `{p['viewport']}/{p['route']}` "
                    f"{nf['method']} {nf['status']} {nf['url']}"
                )
        if net_block:
            lines.append("## HTTP failures (>=400)\n")
            lines.extend(net_block)
            lines.append("")

        page_err_block: list[str] = []
        for p in payloads:
            for pe in p.get("page_errors", []):
                if _is_known_noise(pe):
                    continue
                page_err_block.append(
                    f"  * `{p['viewport']}/{p['route']}`: {pe}"
                )
        if page_err_block:
            lines.append("## Uncaught JS errors\n")
            lines.extend(page_err_block)
            lines.append("")

        # Selector measurements -- one block per route that defined
        # INSPECT_SELECTORS, helpful for "what's the actual width?"
        # debugging without re-shooting.
        meas_block: list[str] = []
        for p in payloads:
            sels = p.get("selectors", [])
            if not sels:
                continue
            meas_block.append(
                f"\n### {p['viewport']}/{p['route']}\n"
            )
            meas_block.append("| selector | count | width × height (px) | display | grid-template-columns |")
            meas_block.append("|---|---:|---|---|---|")
            for s in sels:
                if s.get("missing"):
                    meas_block.append(
                        f"| `{s['selector']}` | 0 | _missing_ | — | — |"
                    )
                    continue
                inst = (s.get("instances") or [{}])[0]
                wxh = f"{inst.get('width', '?')} × {inst.get('height', '?')}"
                meas_block.append(
                    f"| `{s['selector']}` | {s['count']} | {wxh} | "
                    f"{inst.get('display', '?')} | "
                    f"`{inst.get('grid_template_columns', '?')}` |"
                )
        if meas_block:
            lines.append("## Inspector measurements\n")
            lines.extend(meas_block)
            lines.append("")

        theme_summary["report_path"] = (
            str((SNAPS_DIR / theme / "review.md").relative_to(REPO_ROOT))
        )
        theme_summary["routes"] = route_summary

        if write_md:
            (SNAPS_DIR / theme / "review.md").write_text(
                "\n".join(lines), encoding="utf-8"
            )
        if write_json:
            (SNAPS_DIR / theme / "review.json").write_text(
                json.dumps(theme_summary, indent=2), encoding="utf-8"
            )
        rollup.append(theme_summary)

    overall_gate = _worst_gate(r["gate"] for r in rollup) if rollup else "pass"

    # Cross-theme rollup.
    rollup_lines = ["# Snap review — all themes\n"]
    rollup_lines.append(f"{_gate_badge(overall_gate)}\n")
    rollup_lines.append("| theme | gate | errors | warns | infos | 4xx | 5xx | uncaught JS | console err | report |")
    rollup_lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rollup:
        rollup_lines.append(
            f"| {r['theme']} | {r['gate'].upper()} | {r['errors']} | "
            f"{r['warns']} | {r['infos']} | {r['net_4xx']} | "
            f"{r['net_5xx']} | {r['page_errs']} | {r['console_errs']} | "
            f"`{r['report_path']}` |"
        )
    if parity_findings:
        rollup_lines.append("\n## Cross-theme parity drift\n")
        rollup_lines.append(
            "_One theme's measurement diverged > 25% from the cross-theme "
            "median, OR one theme has > 2x the median error/warn count for "
            "the same route. Often the first sign of a regression that "
            "the per-theme baseline diff hasn't caught yet._\n"
        )
        for pf in parity_findings:
            rollup_lines.append(
                f"- `{pf['theme']}` `{pf['viewport']}/{pf['route']}` "
                f"`{pf['kind']}`: {pf['message']}"
            )

    SNAPS_DIR.mkdir(parents=True, exist_ok=True)
    if write_md:
        (SNAPS_DIR / "review.md").write_text(
            "\n".join(rollup_lines) + "\n", encoding="utf-8"
        )
    if write_json:
        (SNAPS_DIR / "review.json").write_text(
            json.dumps(
                {
                    "gate": overall_gate,
                    "themes": rollup,
                    "parity_drift": parity_findings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # Print a terminal summary that mirrors the rollup.
    print(f"\n{'theme':10s} {'gate':>5s} {'err':>5s} {'warn':>5s} "
          f"{'info':>5s} {'4xx':>4s} {'5xx':>4s} {'js-err':>7s}  report")
    print("-" * 80)
    for r in rollup:
        gate = r["gate"]
        col = RED if gate == "fail" else YELLOW if gate == "warn" else GREEN
        print(f"{r['theme']:10s} {col}{gate.upper():>5s}{RESET} "
              f"{r['errors']:5d} {r['warns']:5d} {r['infos']:5d} "
              f"{r['net_4xx']:4d} {r['net_5xx']:4d} {r['page_errs']:7d}  "
              f"{r['report_path']}")
    print()
    print("Cross-theme rollup: tmp/snaps/review.md")
    if overall_gate == "warn" and getattr(args, "strict", False):
        # Loud banner so a passing-but-noisy run still gets attention,
        # even though we don't exit non-zero on warns.
        print(f"\n{YELLOW}{'!' * 70}{RESET}")
        print(f"{YELLOW}!!  WARN: snap report has {sum(r['warns'] for r in rollup)} "
              f"warning(s) and {sum(r['infos'] for r in rollup)} info finding(s). !!{RESET}")
        print(f"{YELLOW}!!  Build still passes, but please review tmp/snaps/review.md.    !!{RESET}")
        print(f"{YELLOW}{'!' * 70}{RESET}")
    _print_status(overall_gate, source="snap.py report")

    if getattr(args, "open", False) and write_md:
        review_md = SNAPS_DIR / "review.md"
        if review_md.exists() and sys.platform == "darwin":
            try:
                subprocess.run(["open", str(review_md)], check=False)
            except Exception:
                pass

    if getattr(args, "strict", False) and overall_gate == "fail":
        return 1
    return 0


def _collect_current_error_findings(
    themes: list[str],
) -> dict[str, dict[str, list[str]]]:
    """Walk `tmp/snaps/<theme>/<viewport>/<slug>.findings.json` for each
    theme and gather every ERROR-tier finding. The result is shaped
    like the on-disk allowlist file: `<theme>:<viewport>:<route>` ->
    kind -> sorted list of fingerprints.

    Findings without a fingerprint (notably `vision:*` whole-page
    critiques) are recorded with the wildcard sentinel `"*"`, which
    `_apply_allowlist_to_findings` interprets as "all findings of this
    kind on this route." This is the only sane way to baseline a
    finding that has no DOM address; it lets the gate stay clean while
    keeping NEW kinds of vision findings detectable.

    Findings already tagged `allowlisted` are treated as errors here
    (they were originally errors, demoted at shoot time by the current
    allowlist). This makes `regenerate` idempotent AND preserves
    existing cells across re-scans, so a stale shoot on top of an
    existing allowlist doesn't silently drop entries that would
    otherwise still be needed.
    """
    out: dict[str, dict[str, list[str]]] = {}
    for theme in themes:
        theme_dir = SNAPS_DIR / theme
        if not theme_dir.is_dir():
            continue
        for fp_path in sorted(theme_dir.glob("*/*.findings.json")):
            try:
                data = json.loads(fp_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            viewport = str(data.get("viewport", ""))
            route = str(data.get("route", fp_path.stem.removesuffix(".findings")))
            for f in data.get("findings", []) or []:
                # Treat both live errors and allowlist-demoted findings
                # as errors for the purposes of snapshotting: demoted
                # findings would pop back to "error" the moment the
                # matching allowlist entry was removed, so they MUST
                # persist in the regenerated file.
                is_error = f.get("severity") == "error"
                is_demoted = bool(f.get("allowlisted"))
                if not (is_error or is_demoted):
                    continue
                kind = str(f.get("kind") or "")
                if not kind:
                    continue
                fp = _finding_fingerprint(f) or "*"
                key = _allowlist_key(theme, viewport, route)
                cell = out.setdefault(key, {})
                bucket = cell.setdefault(kind, [])
                if fp not in bucket:
                    bucket.append(fp)
    # Sort fingerprints inside each kind for stable diffs. Wildcard
    # entries naturally float to the top alphabetically (`*` < digits
    # < letters).
    for cell in out.values():
        for kind in cell:
            cell[kind].sort()
    return out


def _format_allowlist(data: dict[str, dict[str, list[str]]]) -> str:
    """Stable, diff-friendly JSON for the on-disk allowlist file:
    keys sorted, two-space indent, trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def cmd_allowlist(args: argparse.Namespace) -> int:
    """Manage the heuristic-finding allowlist baseline.

    Two actions:
      * regenerate -- snapshot every current ERROR-tier finding (with a
        stable fingerprint) into
        tests/visual-baseline/heuristics-allowlist.json. Run this once
        at rollout, and again any time the team intentionally accepts a
        new batch of pre-existing offences. Going forward only NEW
        findings (not in the file) fail the gate.
      * diff -- show what would change if you regenerated right now.
        Useful in PRs to spot when the baseline drifts under the radar.

    Both actions read findings from `tmp/snaps/<theme>/**/findings.json`,
    so run a `bin/snap.py shoot` first.
    """
    if getattr(args, "all", False) or args.theme is None:
        themes = discover_themes()
    else:
        themes = [args.theme]
    if not themes:
        raise SystemExit("No themes to scan.")

    current = _collect_current_error_findings(themes)
    existing = _load_allowlist()

    if args.action == "regenerate":
        # Merge: keep every existing entry for cells/kinds we DIDN'T
        # re-scan this run (so a partial shoot doesn't accidentally drop
        # entries for themes/routes the user didn't touch). For cells
        # we DID re-scan, replace the per-cell dict entirely so removed
        # findings disappear and new ones land.
        merged: dict[str, dict[str, list[str]]] = {}
        rescanned_themes = set(themes)
        for key, cell in existing.items():
            theme = key.split(":", 1)[0]
            if theme in rescanned_themes:
                continue
            merged[key] = cell
        for key, cell in current.items():
            merged[key] = cell
        ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        before_total = sum(len(v) for cell in existing.values() for v in cell.values())
        after_total = sum(len(v) for cell in merged.values() for v in cell.values())
        ALLOWLIST_PATH.write_text(
            _format_allowlist(merged), encoding="utf-8"
        )
        _reset_allowlist_cache()
        rel = ALLOWLIST_PATH.relative_to(REPO_ROOT)
        print(f"{GREEN}Wrote {rel}{RESET}")
        print(f"  cells: {len(merged)} (was {len(existing)})")
        print(f"  fingerprints: {after_total} (was {before_total})")
        if rescanned_themes:
            print(f"  rescanned themes: {', '.join(sorted(rescanned_themes))}")
        return 0

    if args.action == "diff":
        # For an apples-to-apples diff we have to merge the same way
        # `regenerate` would, otherwise themes/cells the user didn't
        # rescan show up as spurious removals.
        rescanned_themes = set(themes)
        proposed: dict[str, dict[str, list[str]]] = {}
        for key, cell in existing.items():
            theme = key.split(":", 1)[0]
            if theme in rescanned_themes:
                continue
            proposed[key] = cell
        for key, cell in current.items():
            proposed[key] = cell

        added: list[str] = []
        removed: list[str] = []
        # Walk the union of keys.
        all_keys = sorted(set(existing) | set(proposed))
        for key in all_keys:
            old_cell = existing.get(key, {})
            new_cell = proposed.get(key, {})
            kinds = sorted(set(old_cell) | set(new_cell))
            for kind in kinds:
                old_fps = set(old_cell.get(kind, []))
                new_fps = set(new_cell.get(kind, []))
                for fp in sorted(new_fps - old_fps):
                    added.append(f"  + {key} {kind}: {fp}")
                for fp in sorted(old_fps - new_fps):
                    removed.append(f"  - {key} {kind}: {fp}")

        if not added and not removed:
            print(f"{GREEN}No allowlist changes.{RESET}")
            return 0
        print("Allowlist changes vs current findings:")
        if added:
            print(f"{RED}New findings ({len(added)}) -- not yet allowlisted; "
                  f"these would FAIL the gate today:{RESET}")
            for line in added:
                print(line)
        if removed:
            print(f"{GREEN}Resolved findings ({len(removed)}) -- previously "
                  f"allowlisted, no longer present:{RESET}")
            for line in removed:
                print(line)
        # Non-zero exit when there are NEW findings, so CI / pre-push
        # can plug this in as a check (`bin/snap.py allowlist diff`
        # exits 0 unless something new appeared).
        return 1 if added else 0

    raise SystemExit(f"Unknown allowlist action: {args.action!r}")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verify every dependency the snap pipeline needs.

    Exits 0 with a green tree when ready; 1 with a checklist of fixes
    on miss. Designed to be the first thing a new contributor (or a
    fresh CI run) calls before firing off a full sweep.

    Checks:
      * Python version >= 3.8
      * Pillow available (used by the diff engine)
      * Playwright available + Chromium installed
      * @wp-playground/cli reachable via npx (network OR cache)
      * axe-core vendored at bin/vendor/axe.min.js
      * Per-theme baselines exist under tests/visual-baseline/<theme>/
      * tmp/ writable
    """
    checks: list[tuple[str, bool, str]] = []  # (label, ok, hint)

    # Python
    py_ok = sys.version_info >= (3, 8)
    checks.append((
        f"Python {sys.version.split()[0]} >= 3.8",
        py_ok,
        "Upgrade Python to 3.8 or newer.",
    ))

    # Pillow
    try:
        import PIL  # noqa: F401
        checks.append(("Pillow (image diff engine) installed", True, ""))
    except ImportError:
        checks.append((
            "Pillow not installed",
            False,
            "pip install --user Pillow",
        ))

    # Playwright
    try:
        from playwright.sync_api import sync_playwright
        checks.append(("Playwright (Python) installed", True, ""))
        # Chromium binary
        try:
            with sync_playwright() as p:
                br = p.chromium.launch()
                br.close()
            checks.append(("Playwright Chromium runnable", True, ""))
        except Exception as e:
            checks.append((
                "Playwright Chromium NOT runnable",
                False,
                f"playwright install chromium  (error: {e})",
            ))
    except ImportError:
        checks.append((
            "Playwright not installed",
            False,
            "pip install --user playwright && playwright install chromium",
        ))

    # npx + @wp-playground/cli
    try:
        npx = subprocess.run(
            ["npx", "--version"], capture_output=True, text=True, check=False,
            timeout=10,
        )
        npx_ok = npx.returncode == 0
        checks.append((
            f"npx available ({(npx.stdout or '').strip()})",
            npx_ok,
            "Install Node.js (https://nodejs.org). npx ships with npm.",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks.append((
            "npx not found",
            False,
            "Install Node.js so npx can fetch @wp-playground/cli.",
        ))

    # axe-core
    if AXE_VENDOR_PATH.exists():
        checks.append((
            f"axe-core vendored at {AXE_VENDOR_PATH.relative_to(REPO_ROOT)}",
            True, "",
        ))
    else:
        checks.append((
            "axe-core NOT vendored (will download on first shoot)",
            True,  # not fatal -- snap.py downloads lazily
            "Run `python3 bin/snap.py shoot --quick obel` once with "
            "network access to vendor it.",
        ))

    # Baselines per theme
    for theme in discover_themes():
        bl = BASELINE_DIR / theme
        has_any = bl.exists() and any(bl.rglob("*.png"))
        checks.append((
            f"baseline present: tests/visual-baseline/{theme}/",
            has_any,
            f"Run `python3 bin/snap.py shoot {theme} && "
            f"python3 bin/snap.py baseline {theme}`.",
        ))

    # tmp writable
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        probe = TMP_DIR / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("tmp/ writable", True, ""))
    except Exception as e:
        checks.append((
            "tmp/ NOT writable",
            False,
            f"Fix permissions on tmp/ ({e}).",
        ))

    # Render the tree.
    print(f"\n{DIM}Snap doctor — pre-flight checklist{RESET}")
    print("-" * 60)
    failed = 0
    for label, ok, hint in checks:
        if ok:
            print(f"  {GREEN}✓{RESET} {label}")
        else:
            failed += 1
            print(f"  {RED}✗{RESET} {label}")
            if hint:
                print(f"      {DIM}fix:{RESET} {hint}")
    print()
    if failed:
        print(f"{RED}doctor: {failed} check(s) failed.{RESET}")
        return 1
    print(f"{GREEN}doctor: ready.{RESET}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """shoot then diff then report --strict.

    The single command `bin/check.py --visual` calls. By default
    operates on every theme; `--changed` restricts to themes touched
    by uncommitted + base..HEAD diffs (Phase 5). Returns the worst of
    the three exit codes: shoot crashes (1), pixel-diff regression
    above threshold (1), or tiered-gate `fail` from report (1). Warns
    do NOT fail; report prints a loud banner and returns 0.
    """
    args.theme = None
    args.routes = None
    args.viewports = None
    args.quick = False
    args.concurrency = getattr(args, "concurrency", 1)
    # `--changed` overrides --all; the shoot/diff/report functions all
    # honor `args.changed` when set.
    if not getattr(args, "changed", False):
        args.all = True
    rc = cmd_shoot(args)
    if rc != 0:
        return rc
    args.theme = None
    diff_rc = cmd_diff(args)
    # Report always runs even when diff failed -- the heuristic data is
    # the most useful thing the agent has when something just broke.
    args.format = getattr(args, "format", "both")
    args.strict = True
    report_rc = cmd_report(args)
    return diff_rc or report_rc


# ---------------------------------------------------------------------------
# `boot` subcommand: boot-fatal smoke gate (Tier 1.1, pre-100-themes plan)
# ---------------------------------------------------------------------------
#
# Purpose: give ~30s feedback that a theme's Playground even comes up --
# no PHP fatal, no parse error, no template-layer crash -- without paying
# the cost of a full (route × viewport) snap matrix. A snap shoot that
# ALSO hits a PHP fatal gives the same signal, but ~3-10 minutes later.
#
# Design choices:
#   * No Playwright. Boot smoke uses urllib + substring-scan to check
#     response bodies, so it adds zero dependency weight on top of
#     boot_and_wait.
#   * Probes a short, hard-coded route list (`BOOT_PROBE_ROUTES`) that
#     covers the four public surfaces every WC theme must render:
#     home, shop (archive-product), cart, my-account. Checkout is
#     deliberately NOT probed in boot smoke -- WC's checkout block
#     occasionally hydrates async validation errors on empty sessions
#     and those are out of scope for a boot gate.
#   * Writes `tmp/<theme>-boot.json` for CI / agents to consume; human
#     operators get a compact stdout summary.
#   * Exit code: 0 if every probe returned <500 and no fatal pattern
#     hit, 1 otherwise. Non-fatal warnings (Notice/Deprecated) are
#     recorded but don't fail the gate -- they're normal on a fresh
#     WP+WC boot.
BOOT_PROBE_ROUTES = ("/", "/shop/", "/cart/", "/my-account/")
BOOT_PROBE_TIMEOUT_S = 15.0
# Patterns below come from the WP/PHP error surface seen in real fatals
# across `tmp/<theme>-server.log`. Kept deliberately narrow (NO generic
# "Warning:"/"Notice:") because those fire on every fresh WP boot for
# deprecated filter hooks and would make the gate useless. `check.py`
# already has a "php-debug-output" rule that catches noise in-page;
# boot smoke just catches the unrecoverable stuff.
BOOT_FATAL_PATTERNS = (
    "Fatal error:",
    "Parse error:",
    "PHP Fatal",
    "PHP Parse",
    "Call to undefined function",
    "Call to undefined method",
    "Uncaught Error:",
    "Uncaught TypeError",
    "Uncaught ValueError",
    "WordPress database error",
    "There has been a critical error on this website",
    "There has been a critical error on your website",
    # WP's default renderer for a PHP fatal (wp_die-style) prints a
    # <title> that's unique enough to catch even if the stack trace is
    # display-disabled in the blueprint.
    "<title>WordPress &rsaquo; Error</title>",
)
# Softer signals: surfaced in the verdict JSON but NOT failing the gate.
# Matched case-insensitively against response body + log.
BOOT_WARNING_PATTERNS = (
    "Deprecated:",
    "Warning:",
    "Notice:",
)


def _boot_fatal_hits(text: str) -> list[str]:
    """Return the list of fatal patterns present in `text`.

    Case-insensitive. Deduped, order-preserving so the first hit (most
    likely the most informative) shows up first in the verdict JSON.
    Pure function: unit-testable without booting Playground.
    """
    if not text:
        return []
    lower = text.lower()
    hits: list[str] = []
    for pat in BOOT_FATAL_PATTERNS:
        if pat.lower() in lower and pat not in hits:
            hits.append(pat)
    return hits


def _boot_warning_hits(text: str) -> list[str]:
    """Return the list of soft-warning patterns present in `text`.

    See `_boot_fatal_hits`. Separate list so the verdict JSON can
    distinguish "fails the gate" from "informational".
    """
    if not text:
        return []
    lower = text.lower()
    hits: list[str] = []
    for pat in BOOT_WARNING_PATTERNS:
        if pat.lower() in lower and pat not in hits:
            hits.append(pat)
    return hits


def _probe_body(url: str, timeout_s: float = BOOT_PROBE_TIMEOUT_S) -> dict:
    """GET `url`, return a verdict dict with status + body fatal scan.

    Keys:
      status: HTTP status (int) or None on connection error
      error:  exception class name, populated on network failure
      fatals: list of BOOT_FATAL_PATTERNS matched in the response body
      warns:  list of BOOT_WARNING_PATTERNS matched in the response body
      bytes:  content-length we read (capped at 256 KiB)

    We deliberately do NOT follow redirects via the default opener --
    `Server` already serves 302s for logged-out access to some
    protected routes (/my-account/ -> login redirect) and a 3xx without
    a fatal is fine for boot smoke.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "fifty-boot-smoke/1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = resp.status
            data = resp.read(262144)
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            data = e.read(262144)
        except Exception:
            data = b""
    except (
        TimeoutError,
        urllib.error.URLError,
        ConnectionError,
        OSError,
    ) as e:
        return {
            "status": None,
            "error": type(e).__name__,
            "fatals": [],
            "warns": [],
            "bytes": 0,
        }
    text = data.decode("utf-8", errors="replace") if data else ""
    return {
        "status": status,
        "error": None,
        "fatals": _boot_fatal_hits(text),
        "warns": _boot_warning_hits(text),
        "bytes": len(data),
    }


def _scan_log_for_fatals(log_path: Path, tail_kb: int = 256) -> dict:
    """Scan the last `tail_kb` kilobytes of the server log for fatals.

    Why tail: cold boots emit tens of MB of blueprint chatter; fatals
    that matter for boot smoke show up near the end (post-blueprint,
    serving our probe requests). Reading the whole file on a fleet of
    100 themes would dominate smoke wall-time.
    """
    if not log_path.exists():
        return {"fatals": [], "warns": [], "bytes": 0}
    try:
        size = log_path.stat().st_size
        start = max(0, size - tail_kb * 1024)
        with log_path.open("rb") as fh:
            fh.seek(start)
            data = fh.read()
    except OSError:
        return {"fatals": [], "warns": [], "bytes": 0}
    text = data.decode("utf-8", errors="replace") if data else ""
    return {
        "fatals": _boot_fatal_hits(text),
        "warns": _boot_warning_hits(text),
        "bytes": len(data),
    }


def boot_smoke(
    theme: str,
    *,
    routes: Iterable[str] = BOOT_PROBE_ROUTES,
    cache_state: bool = False,
    port: int | None = None,
) -> dict:
    """Boot Playground, probe each route, tear down, return verdict dict.

    This is the CLI entry point's pure-ish core, broken out so tests
    and CI scripts (nightly-snap-sweep, check.yml pre-shoot gate) can
    call it without re-parsing argv. `cmd_boot` is the thin argparse
    adapter.
    """
    start = time.time()
    probes: list[dict] = []
    log_fatals: list[str] = []
    log_warns: list[str] = []
    boot_error: str | None = None
    log_path: Path | None = None
    try:
        with running_server(
            theme,
            port=port,
            verbosity="normal",
            login=False,
            cache_state=cache_state,
        ) as server:
            log_path = server.log_path
            for route in routes:
                url = f"{server.url}{route}"
                probes.append({"route": route, **_probe_body(url)})
    except SystemExit as e:
        boot_error = f"boot failed: {e}"
    except Exception as e:  # pragma: no cover -- defensive
        boot_error = f"{type(e).__name__}: {e}"

    if log_path is not None:
        scan = _scan_log_for_fatals(log_path)
        log_fatals = scan["fatals"]
        log_warns = scan["warns"]

    # Compose verdict. A probe that returned None (status unreachable)
    # is treated as a fail; >=500 is a fail; any fatal-pattern hit in
    # body or log is a fail. Everything else is pass.
    reasons: list[str] = []
    if boot_error:
        reasons.append(boot_error)
    for p in probes:
        if p["status"] is None:
            reasons.append(f"{p['route']}: no response ({p.get('error')})")
        elif p["status"] >= 500:
            reasons.append(f"{p['route']}: HTTP {p['status']}")
        if p["fatals"]:
            reasons.append(f"{p['route']}: body contains {p['fatals'][0]!r}")
    if log_fatals:
        reasons.append(f"server log contains {log_fatals[0]!r}")

    verdict = {
        "theme": theme,
        "elapsed_s": round(time.time() - start, 2),
        "cache_state": bool(cache_state),
        "probes": probes,
        "log_fatals": log_fatals,
        "log_warns": log_warns,
        "boot_error": boot_error,
        "ok": not reasons,
        "reasons": reasons,
    }
    return verdict


def _write_boot_verdict(theme: str, verdict: dict) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / f"{theme}-boot.json"
    out.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    return out


def cmd_boot(args: argparse.Namespace) -> int:
    """snap boot <theme>: fast boot-fatal smoke gate.

    Boots the theme's Playground, probes a handful of public routes,
    scans both HTTP responses and the server log for PHP fatals, and
    writes `tmp/<theme>-boot.json`. Returns 0 on green, 1 on any
    fatal/unreachable probe. Warnings (Deprecated/Notice) are recorded
    but do NOT fail the gate.

    Cost target: ~30s warm (cache-state), ~2-3min cold on a fresh
    theme (same as any boot_and_wait, since the WP install itself is
    the long pole). The value proposition is that a blown-up theme
    fails HERE instead of 10 minutes into a 44-cell shoot.
    """
    themes: list[str]
    if getattr(args, "all", False):
        themes = discover_themes()
    elif args.theme:
        themes = [args.theme]
    else:
        print("usage: snap.py boot <theme> [--all]", file=sys.stderr)
        return 2

    any_fail = False
    for theme in themes:
        print(f"\n=== boot smoke: {theme} ===")
        verdict = boot_smoke(
            theme,
            cache_state=bool(getattr(args, "cache_state", False)),
            port=getattr(args, "port", None),
        )
        out_path = _write_boot_verdict(theme, verdict)
        if verdict["ok"]:
            print(
                f"  {GREEN}PASS{RESET} {theme} in {verdict['elapsed_s']}s "
                f"({len(verdict['probes'])} probes; "
                f"{len(verdict['log_warns'])} log warns)"
            )
        else:
            any_fail = True
            print(f"  {RED}FAIL{RESET} {theme} in {verdict['elapsed_s']}s")
            for reason in verdict["reasons"]:
                print(f"    - {reason}")
        print(f"  verdict -> {out_path}")
    return 1 if any_fail else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="snap.py",
        description=(
            "Visual snapshot framework: boot Playground, capture pages "
            "with Playwright, diff against baselines."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s_serve = sub.add_parser("serve", help="Boot a theme and leave it running.")
    s_serve.add_argument("theme")
    s_serve.add_argument("--port", type=int, default=None)
    s_serve.add_argument(
        "--shoot-on-demand",
        nargs="?",
        type=int,
        const=9501,
        default=None,
        metavar="PORT",
        help=(
            "Start an HTTP endpoint (default port 9501) that accepts "
            "POST /shoot {route, viewport} against the warm Playground. "
            "Phase 2 of the closed-loop dispatcher; lets bin/dispatch-watch.py "
            "amortize the ~127s cold-boot to once-per-session."
        ),
    )
    s_serve.add_argument("--verbosity", default="normal",
                         choices=["quiet", "normal", "debug"])
    s_serve.add_argument(
        "--cache-state", action="store_true",
        help=(
            "Mount tmp/playground-state/<theme>/wordpress -> /wordpress "
            "(via --mount-before-install). First boot auto-primes the "
            "cache (bidirectional NODEFS mount captures the WP install "
            "into the host dir). Subsequent boots add "
            "--wordpress-install-mode=install-from-existing-files-if-needed "
            "so WP install + plugin install both skip (~40-100s saved "
            "per boot). The blueprint's importWxr + seeder steps still "
            "re-run every boot so content stays fresh. Cache auto-"
            "invalidates on @wp-playground/cli version bump."
        ),
    )
    s_serve.add_argument(
        "--reset-cache", action="store_true",
        help="Wipe tmp/playground-state/<theme>/ before booting (only "
             "effective with --cache-state).",
    )
    s_serve.add_argument(
        "--persistent", action="store_true",
        help=(
            "Wrap the boot in a supervisor loop that auto-restarts "
            "Playground when its wasm worker dies. The HTTP listener "
            "(--shoot-on-demand) survives across restarts. Writes "
            "tmp/snap-server-<theme>.pid so peer tools can detect the "
            "warm server. Phase 3 (phase3-warm-supervisor)."
        ),
    )
    s_serve.set_defaults(func=cmd_serve)

    s_shoot = sub.add_parser("shoot", help="Boot, capture, kill.")
    s_shoot.add_argument("theme", nargs="?", default=None,
                         help="Theme slug, or omit and use --all.")
    s_shoot.add_argument("--all", action="store_true",
                         help="Shoot every discoverable theme.")
    s_shoot.add_argument("--routes", nargs="+", default=None,
                         help="Subset of route slugs (default: all).")
    s_shoot.add_argument("--viewports", nargs="+", default=None,
                         help="Subset of viewport names (default: all).")
    s_shoot.add_argument("--quick", action="store_true",
                         help="Use snap_config.QUICK_* subsets only.")
    s_shoot.add_argument(
        "--auto-routes", action="store_true",
        help=(
            "Smart: within each affected theme, shoot only the routes "
            "whose template/part/pattern dependencies were touched by "
            "the diff. See ROUTE_DEPENDENCIES + ROUTE_GLOBAL_GLOBS in "
            "bin/snap_config.py for the manifest. Falls back to every "
            "route when a global file (theme.json, styles/**, header/"
            "footer, playground fixtures) changes. Combine with "
            "--changed to narrow theme AND route scope together."
        ),
    )
    s_shoot.add_argument("--port", type=int, default=None,
                         help="Pin the playground port. Ignored when "
                         "--concurrency > 1 (each worker auto-picks).")
    s_shoot.add_argument("--concurrency", type=int, default=1,
                         help="Number of themes to shoot in parallel "
                         "(each spawns its own playground; ~400MB/worker). "
                         "Default 1 (serial).")
    s_shoot.add_argument("--verbosity", default="normal",
                         choices=["quiet", "normal", "debug"],
                         help="Forwarded to @wp-playground/cli; default "
                         "'normal' so blueprint progress lands in "
                         "tmp/<theme>-server.log for debugging boot hangs.")
    s_shoot.add_argument(
        "--changed", action="store_true",
        help="Smart: only shoot themes touched by uncommitted + "
        "<changed-base>..HEAD git changes. Framework changes (bin/*) "
        "fall back to all themes. Empty diff exits 0 immediately.",
    )
    s_shoot.add_argument(
        "--changed-base", default=None,
        help="Git base ref for --changed (e.g. main, HEAD~1). "
        "Default: only consider uncommitted changes.",
    )
    s_shoot.add_argument(
        "--cache-state", action="store_true",
        help=(
            "Reuse tmp/playground-state/<theme>/wordpress across boots. "
            "First boot auto-primes; subsequent boots skip WP install + "
            "plugin install (~40-100s saved per boot, which matters most "
            "for iterative single-cell shoots during an audit). Content "
            "seeder still re-runs every boot so playground/content/ edits "
            "are never stale. Cache auto-invalidates on CLI version bump. "
            "See `bin/snap.py serve --cache-state --help` for details."
        ),
    )
    s_shoot.add_argument(
        "--reset-cache", action="store_true",
        help="Wipe tmp/playground-state/<theme>/ before each shoot (only "
             "effective with --cache-state).",
    )
    s_shoot.add_argument(
        "--no-skip", action="store_true",
        help=(
            "Disable Phase 2 signature-based cell skipping -- always "
            "boot Playground and re-shoot every (theme, viewport, route) "
            "cell, even when ROUTE_DEPENDENCIES prove nothing upstream "
            "changed. Use for debugging the skip logic itself, or when "
            "baselines drift for reasons the manifest can't see (flaky "
            "fonts, Chromium rasterization deltas, etc.). Equivalent to "
            "FIFTY_FORCE_RESHOOT=1 but scoped to the invocation."
        ),
    )
    s_shoot.set_defaults(func=cmd_shoot)

    s_touch = sub.add_parser(
        "touch",
        help=(
            "Bump findings.json mtimes without re-shooting. Escape hatch "
            "for provably non-visual edits (e.g. idempotent theme.json "
            "resyncs, @media rules targeting states snaps don't cover). "
            "Requires --reason; pre-push still runs the visual gate."
        ),
    )
    s_touch.add_argument("theme", nargs="?", default=None,
                         help="Theme slug, or omit and use --all.")
    s_touch.add_argument("--all", action="store_true",
                         help="Touch every discoverable theme.")
    s_touch.add_argument(
        "--reason", required=True, default=None,
        help=(
            "Required. Free-form text (>=12 chars) explaining why "
            "skipping a re-shoot is safe for this edit. Logged to "
            "tmp/snap-touch-log.jsonl for audit."
        ),
    )
    s_touch.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be touched without modifying mtimes "
        "or writing an audit entry.",
    )
    s_touch.set_defaults(func=cmd_touch)

    s_baseline = sub.add_parser(
        "baseline",
        help="Promote latest tmp/snaps to tests/visual-baseline/."
    )
    s_baseline.add_argument("theme", nargs="?", default=None)
    s_baseline.add_argument("--route", default=None)
    s_baseline.add_argument("--viewport", default=None)
    s_baseline.add_argument(
        "--missing-only",
        action="store_true",
        help=(
            "Only promote routes that have no existing baseline "
            "(idempotent for design.py re-runs on existing themes)."
        ),
    )
    s_baseline.add_argument(
        "--rebaseline",
        action="store_true",
        help=(
            "Always overwrite (default behaviour today). Mutually exclusive "
            "with --missing-only."
        ),
    )
    s_baseline.set_defaults(func=cmd_baseline)

    s_rebaseline = sub.add_parser(
        "rebaseline",
        help=(
            "Targeted bulk re-baselining: promote drifted and/or stale "
            "baselines only. See module docstring for motivation."
        ),
    )
    s_rebaseline.add_argument(
        "theme", nargs="?", default=None,
        help="Scope to a single theme (default: every discoverable theme).",
    )
    s_rebaseline.add_argument(
        "--route", default=None,
        help="Scope to a single route slug within the theme.",
    )
    s_rebaseline.add_argument(
        "--viewport", default=None,
        help="Scope to a single viewport (e.g. m|t|d|w).",
    )
    s_rebaseline.add_argument(
        "--drifted", action="store_true",
        help=(
            "Only promote cells whose current diff vs baseline is above "
            "--threshold (default 0.5%%). Combined with --since, the cell "
            "must satisfy BOTH filters."
        ),
    )
    s_rebaseline.add_argument(
        "--since", default="",
        help=(
            "Only promote cells whose baseline mtime is older than the "
            "given time. Accepts relative durations (`7d`, `24h`, `2w`) "
            "or ISO timestamps (`2026-04-01`)."
        ),
    )
    s_rebaseline.add_argument(
        "--threshold", type=float, default=0.5,
        help=(
            "Drift threshold for --drifted; cells above this %% of "
            "changed pixels are promoted. Default: 0.5%%."
        ),
    )
    s_rebaseline.add_argument(
        "--channel-tolerance", type=int, default=8,
        help=(
            "Per-channel delta below which pixels are ignored (matches "
            "`snap.py diff`)."
        ),
    )
    s_rebaseline.add_argument(
        "--dry-run", action="store_true",
        help=(
            "List every cell that WOULD be promoted (with its drift %% or "
            "baseline age tag) without copying any files. Safe to run in "
            "CI to surface suspected drift."
        ),
    )
    s_rebaseline.set_defaults(func=cmd_rebaseline)

    s_diff = sub.add_parser(
        "diff",
        help="Compare tmp/snaps to tests/visual-baseline.",
    )
    s_diff.add_argument("theme", nargs="?", default=None)
    s_diff.add_argument("--all", action="store_true")
    s_diff.add_argument("--threshold", type=float, default=0.5,
                        help="Max %% changed pixels before a cell fails.")
    s_diff.add_argument("--channel-tolerance", type=int, default=8,
                        help="Per-channel delta below which pixels are "
                        "treated as unchanged (anti-aliasing noise).")
    s_diff.add_argument("--changed", action="store_true",
                        help="Diff only themes touched by git diff (Phase 5).")
    s_diff.add_argument("--changed-base", default=None,
                        help="Git base ref for --changed.")
    s_diff.set_defaults(func=cmd_diff)

    s_check = sub.add_parser(
        "check",
        help="shoot --all then diff --all (used by bin/check.py --visual).",
    )
    s_check.add_argument("--threshold", type=float, default=0.5)
    s_check.add_argument("--channel-tolerance", type=int, default=8)
    s_check.add_argument("--port", type=int, default=None)
    s_check.add_argument("--concurrency", type=int, default=1)
    s_check.add_argument("--verbosity", default="quiet",
                         choices=["quiet", "normal", "debug"])
    s_check.add_argument(
        "--changed", action="store_true",
        help="Restrict shoot/diff/report to themes touched by git diff. "
        "Bin/* framework changes fall back to all themes.",
    )
    s_check.add_argument("--changed-base", default=None,
                         help="Git base ref for --changed (default: uncommitted).")
    s_check.add_argument(
        "--format", choices=["json", "md", "both"], default="both",
        help="Forwarded to the report stage.",
    )
    s_check.set_defaults(func=cmd_check)

    s_report = sub.add_parser(
        "report",
        help="Aggregate findings.json into review.md (per theme + rollup).",
    )
    s_report.add_argument("theme", nargs="?", default=None,
                          help="Theme slug; default reports on every "
                          "theme that has snaps in tmp/snaps/.")
    s_report.add_argument("--all", action="store_true",
                          help="Force reporting on every discovered theme.")
    s_report.add_argument(
        "--strict", action="store_true",
        help="Exit 1 when the tiered gate is FAIL (heuristic errors, "
        "uncaught JS, or HTTP 5xx). Warns still exit 0 with a loud "
        "banner. `bin/snap.py check` always passes --strict.",
    )
    s_report.add_argument(
        "--format", choices=["json", "md", "both"], default="both",
        help="Which artifacts to write: 'md' for review.md only, "
        "'json' for review.json only, 'both' (default) for both.",
    )
    s_report.add_argument("--changed", action="store_true",
                          help="Report only on themes touched by git diff.")
    s_report.add_argument("--changed-base", default=None,
                          help="Git base ref for --changed.")
    s_report.add_argument(
        "--open", action="store_true",
        help="After writing review.md, open it in the default app "
        "(macOS only; on other platforms this is a no-op).",
    )
    s_report.set_defaults(func=cmd_report)

    s_boot = sub.add_parser(
        "boot",
        help=(
            "Boot-fatal smoke gate: boot Playground, probe /, /shop/, "
            "/cart/, /my-account/, scan body + log for PHP fatals. "
            "Writes tmp/<theme>-boot.json. Exits 1 on any unreachable "
            "probe, HTTP 5xx, or fatal-pattern hit. ~30s warm, ~2-3min "
            "cold. Use as a pre-shoot gate so a broken theme fails in "
            "seconds instead of minutes-into-a-matrix."
        ),
    )
    s_boot.add_argument(
        "theme", nargs="?", default=None,
        help="Theme slug, or omit and use --all.",
    )
    s_boot.add_argument(
        "--all", action="store_true",
        help="Smoke every discoverable theme serially.",
    )
    s_boot.add_argument(
        "--port", type=int, default=None,
        help="Pin the playground port (default: auto-pick).",
    )
    s_boot.add_argument(
        "--cache-state", action="store_true",
        help=(
            "Reuse tmp/playground-state/<theme>/wordpress. First boot "
            "still pays cold-boot cost; subsequent invocations drop "
            "to ~20-30s. See `snap.py shoot --cache-state --help`."
        ),
    )
    s_boot.set_defaults(func=cmd_boot)

    s_doctor = sub.add_parser(
        "doctor",
        help="Verify Playwright/Pillow/axe/baselines are ready.",
    )
    s_doctor.set_defaults(func=cmd_doctor)

    s_allow = sub.add_parser(
        "allowlist",
        help=(
            "Manage the heuristic-finding allowlist baseline "
            "(tests/visual-baseline/heuristics-allowlist.json)."
        ),
    )
    s_allow.add_argument(
        "action",
        choices=("regenerate", "diff"),
        help=(
            "regenerate: snapshot current ERROR findings into the "
            "allowlist file. diff: show what would change without "
            "writing (exits 1 if new un-allowlisted findings exist)."
        ),
    )
    s_allow.add_argument(
        "--theme", default=None,
        help="Limit to one theme (defaults to all discovered themes).",
    )
    s_allow.add_argument(
        "--all", action="store_true",
        help="Explicit alias for 'all themes' (default behaviour).",
    )
    s_allow.set_defaults(func=cmd_allowlist)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
