"""Fingerprint-per-theme cache + cross-theme collision helpers.

Why this module exists (Tier 2.1 of pre-100-themes hardening)
--------------------------------------------------------------
`bin/check.py` currently hosts eight cross-theme checks that, on every
single invocation, open every theme's source files to build a full-
fleet view:

  * check_distinctive_chrome            -- reads every theme's theme.json CSS
  * check_front_page_unique_layout      -- reads every theme's front-page.html
  * check_pattern_microcopy_distinct    -- reads every theme's patterns/ + parts/ + templates/
  * check_all_rendered_text_distinct    -- reads every theme's patterns/ + parts/ + templates/
  * check_wc_microcopy_distinct         -- reads every theme's functions.php
  * check_product_images_unique         -- hashes every theme's playground/images/product-wo-*.jpg
  * check_hero_images_unique            -- hashes every theme's playground/images/wonders-*.png
  * check_theme_screenshots_distinct    -- hashes every theme's screenshot.png

With 6 themes today, a single `bin/check.py obel --offline` reads ~400
files for these 8 checks. At 100 themes, it reads ~6,700 -- for ONE
theme's local check run. Multiply by every author who runs `check.py`
through the day, and the hash-the-world loop dominates the tool's cost.

What this module provides
-------------------------
A content-addressed on-disk cache at `tmp/check-fingerprints/<check>/<theme>.json`
that each cross-theme check populates with its own theme's fingerprint
once per unique input-hash. Collisions are detected by reading every
theme's cached fingerprint and comparing.

Cache entry shape:
    {
      "inputs_hash":   "<sha256 of a stable hash over the input files>",
      "data":          <the check-specific fingerprint payload>,
      "theme":         "<slug>",
      "check":         "<check name>",
      "emitted_at":    "<iso timestamp>"
    }

Guarantees:
  * The on-disk cache is safe to delete at any time; checks always fall
    back to recomputing.
  * A single author-triggered edit to one theme invalidates ONLY that
    theme's cache entries, not any sibling theme's.
  * The cache is content-addressed by sha256 of (path, stat, file bytes)
    so mtime jitter across worktrees doesn't trigger spurious recomputes.
  * Env var `FIFTY_FORCE_FINGERPRINT_RECOMPUTE=1` bypasses the cache
    entirely (useful for nightly sweeps and CI safety nets).

API
---
    compute_inputs_hash(paths) -> str
        sha256 over (relative_path, file bytes) for every path. Missing
        files contribute their absence (path + sentinel) so a removal
        invalidates the cache.

    load_or_compute(theme, check_name, input_paths, compute_fn) -> dict
        Return the cached fingerprint data if the inputs_hash for the
        given file set matches; otherwise call compute_fn() and write
        the new entry before returning.

    collect_fleet(themes, check_name, input_builder, compute_fn) -> dict[slug -> data]
        For each theme in `themes`, figure out its input_paths via
        `input_builder(theme)`, then call `load_or_compute`. Returns
        a slug->data dict ready for collision analysis.

    find_exact_collisions(by_theme) -> list[tuple[frozenset[str], Any]]
        Group themes whose fingerprint data is exactly equal. Returns
        the list of (theme_set, shared_data) for every cluster of
        size >= 2. Order-preserving for stable test output.

    clear_cache(check_name=None)
        Nuke the cache dir for one check (or all checks when arg is None).

Thread safety: the cache uses per-file atomic writes via tempfile+rename,
so concurrent `bin/check.py` invocations are safe. Serial-first is the
common case today.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

MONOREPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = MONOREPO_ROOT / "tmp" / "check-fingerprints"
ENV_FORCE = "FIFTY_FORCE_FINGERPRINT_RECOMPUTE"


def _cache_path(check_name: str, theme: str) -> Path:
    """Return the on-disk path for a given (check, theme) entry."""
    safe_check = check_name.replace("/", "_").replace("\\", "_")
    safe_theme = theme.replace("/", "_").replace("\\", "_")
    return CACHE_ROOT / safe_check / f"{safe_theme}.json"


def compute_inputs_hash(paths: Iterable[Path]) -> str:
    """SHA-256 over every (relative_path, bytes) pair in `paths`.

    A missing file still contributes its path + the literal byte
    "MISSING", so removing a file invalidates the cache the same way
    editing it does. Paths are rendered relative to MONOREPO_ROOT so
    the hash is stable across worktrees / CI runners.

    Inputs are hashed in SORTED order so caller ordering can't change
    the result.
    """
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        try:
            rel = p.resolve().relative_to(MONOREPO_ROOT)
        except ValueError:
            rel = Path(p.name)
        h.update(str(rel).encode("utf-8"))
        h.update(b"\0")
        if p.is_file():
            h.update(b"FILE\0")
            with p.open("rb") as fp:
                for chunk in iter(lambda: fp.read(1 << 16), b""):
                    h.update(chunk)
        else:
            # Absent or non-regular (symlink-to-nothing, directory, etc.);
            # either case is meaningful to the fingerprint and should
            # invalidate the cache when it flips.
            h.update(b"MISSING\0")
        h.update(b"\0")
    return h.hexdigest()


def _read_cached(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # tempfile in the same dir so rename is atomic on POSIX.
    fd, tmp = tempfile.mkstemp(prefix=".fp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, sort_keys=True)
            fp.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_or_compute(
    theme: str,
    check_name: str,
    input_paths: Iterable[Path],
    compute_fn: Callable[[], Any],
) -> Any:
    """Return cached fingerprint data for (theme, check) or (re)compute.

    The cache entry is invalidated when any input file's bytes change
    (or the file disappears). `compute_fn` is only called on a cache
    miss. The returned data is JSON-serializable (enforced below) so
    that cache round-trips are lossless.
    """
    path = _cache_path(check_name, theme)
    inputs_hash = compute_inputs_hash(input_paths)
    if os.environ.get(ENV_FORCE) != "1":
        cached = _read_cached(path)
        if cached and cached.get("inputs_hash") == inputs_hash:
            return cached.get("data")
    data = compute_fn()
    try:
        json.dumps(data)  # sanity: must be JSON-serializable
    except (TypeError, ValueError) as e:
        raise TypeError(
            f"fingerprint data for check={check_name!r} theme={theme!r} "
            f"is not JSON-serializable: {e}"
        ) from e
    entry = {
        "inputs_hash": inputs_hash,
        "data": data,
        "theme": theme,
        "check": check_name,
        "emitted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),  # noqa: UP017
    }
    _atomic_write(path, entry)
    return data


def collect_fleet(
    themes: Iterable[Path | str],
    check_name: str,
    input_builder: Callable[[Path], list[Path]],
    compute_fn: Callable[[Path], Any],
) -> dict[str, Any]:
    """Build {theme_slug: fingerprint_data} across every theme.

    `input_builder(theme_dir)` returns the list of file paths whose
    content should invalidate that theme's cache entry. `compute_fn
    (theme_dir)` is the per-theme recomputation closure.
    """
    out: dict[str, Any] = {}
    for entry in themes:
        theme_dir = Path(entry) if not isinstance(entry, Path) else entry
        slug = theme_dir.name
        inputs = input_builder(theme_dir)

        def _compute(td: Path = theme_dir) -> Any:
            return compute_fn(td)

        out[slug] = load_or_compute(slug, check_name, inputs, _compute)
    return out


def find_exact_collisions(
    by_theme: dict[str, Any],
) -> list[tuple[frozenset[str], Any]]:
    """Return (theme_set, shared_data) for every cluster of >=2 themes
    sharing exactly the same fingerprint.

    Comparison is `==` after JSON round-trip, so dict-order and list-
    order differences DO matter (and probably should — if two themes
    emit the same dict but with different key ordering that's a bug in
    the check's compute_fn, not a collision).
    """
    # Bucket by a canonical JSON encoding so unhashable dict values can
    # still key the groups.
    buckets: dict[str, list[str]] = {}
    values: dict[str, Any] = {}
    for slug, data in by_theme.items():
        key = json.dumps(data, sort_keys=True)
        buckets.setdefault(key, []).append(slug)
        values[key] = data
    clusters = [
        (frozenset(slugs), values[key])
        for key, slugs in buckets.items()
        if len(slugs) >= 2
    ]
    # Stable order for test output: sort by the first (alphabetically)
    # theme slug in each cluster.
    clusters.sort(key=lambda kv: sorted(kv[0])[0] if kv[0] else "")
    return clusters


def find_value_overlaps(
    by_theme: dict[str, dict[str, str]],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Find values that appear in multiple themes' per-file digest maps.

    The shape `by_theme[slug] = {filename: digest}` is common to the
    image-hash and microcopy-leak checks: each theme has its own
    universe of (file -> hash) pairs, and a hash appearing in two
    themes' universes is a leak.

    Returns `[(digest, [(theme/file), (theme/file), ...]), ...]`
    for every digest that shows up in >=2 locations (across themes OR
    within one theme). The inner list is sorted for stable test output.
    """
    digest_sites: dict[str, list[tuple[str, str]]] = {}
    for slug, files in by_theme.items():
        for fname, digest in files.items():
            digest_sites.setdefault(digest, []).append((slug, fname))
    return [
        (d, sorted(sites))
        for d, sites in digest_sites.items()
        if len(sites) > 1
    ]


def clear_cache(check_name: str | None = None) -> int:
    """Remove cached fingerprints for one check (or all checks). Returns
    the number of files deleted. Safe to call when the cache doesn't
    exist yet.
    """
    if check_name is None:
        target = CACHE_ROOT
    else:
        target = _cache_path(check_name, "any").parent
    if not target.is_dir():
        return 0
    removed = 0
    for p in target.rglob("*.json"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            continue
    return removed
