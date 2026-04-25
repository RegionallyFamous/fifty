#!/usr/bin/env python3
"""Concept-similarity check, run by `bin/check.py`.

Two passes:

1. **Tag overlap.** Reads every ``mockups/<slug>.meta.json`` and looks
   for pairs that share at least
   ``COLLISION_THRESHOLD`` axes from {dominant palette, type, era,
   sector, hero}. Pairs at exactly ``WATCH_THRESHOLD`` axes are
   flagged as warnings only.
2. **Perceptual hash.** When Pillow is installed, computes a tiny
   8x8 average-hash of each mockup PNG and flags pairs with Hamming
   distance below ``PHASH_HAMMING_THRESHOLD`` — catches the case where
   two mockups happen to be visually identical even though their
   tags read as different.

Both passes are allowlist-aware: pairs that the Proprietor has reviewed
and decided to keep go in ``bin/concept-similarity-allowlist.json``.

Output:
    Returns a Result object suitable for printing in `bin/check.py`'s
    standard table. Exit code is implicit via Result.passed.

Usage as a script (handy when triaging the allowlist):
    python3 bin/check-concept-similarity.py
    python3 bin/check-concept-similarity.py --json   # machine-readable

Why allowlist-with-warnings instead of hard-fail-by-default:
    Concept design is iterative. A pair that's borderline today might
    diverge as the agent picks it up and reinterprets it; failing CI
    on every borderline pair would prevent any new concept from
    landing. The default behaviour is therefore to print the pairs
    as warnings (Result.passed remains True). Pairs above
    ``HARD_FAIL_THRESHOLD`` (5/5 axes overlap) DO fail unless
    explicitly allowlisted — that's the "you've literally re-shipped
    the same concept under two slugs" case.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT

MOCKUPS_DIR = MONOREPO_ROOT / "mockups"
ALLOWLIST_PATH = MONOREPO_ROOT / "bin" / "concept-similarity-allowlist.json"

# Same threshold used by `bin/audit-concepts.py` for consistency between
# the human-readable audit document and the machine-enforced gate.
COLLISION_THRESHOLD = 4
WATCH_THRESHOLD = 3
HARD_FAIL_THRESHOLD = 5  # all five axes match -> definitely a duplicate

# Hamming distance threshold for perceptual hash. With an 8x8 average
# hash that produces a 64-bit fingerprint, distances <= 2 are usually
# perceptually-identical images (same mockup re-saved with a different
# compressor); distances 3-8 are "very similar luminance" but often
# include genuinely different concepts that happen to share an
# overall light-dark distribution (e.g. cobbler's leather shoe on
# cream paper vs luthier's wooden guitar on cream paper). We use 8
# as the warn threshold and 2 as the hard-fail threshold so the
# default behaviour is "noisy in the report, only blocks on actual
# PNG duplication".
PHASH_HAMMING_WARN = 8
PHASH_HAMMING_FAIL = 2
PHASH_SIZE = 8  # 8x8 = 64 bits


def _load_allowlist() -> set[frozenset[str]]:
    """Return the set of allowlisted (slug_a, slug_b) pairs as frozensets."""
    if not ALLOWLIST_PATH.is_file():
        return set()
    try:
        data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warn: ignoring malformed {ALLOWLIST_PATH.name}: {e}", file=sys.stderr)
        return set()
    out: set[frozenset[str]] = set()
    for entry in data.get("pairs", []):
        # Two accepted shapes:
        #   ["slug-a", "slug-b"]                       — terse
        #   {"slugs": ["slug-a", "slug-b"], "note": …} — annotated
        # The annotated form lets reviewers leave a paper trail alongside
        # each waiver. We treat the `note` field as documentation only.
        if isinstance(entry, list) and len(entry) == 2:
            out.add(frozenset([str(entry[0]), str(entry[1])]))
        elif isinstance(entry, dict):
            slugs = entry.get("slugs")
            if isinstance(slugs, list) and len(slugs) == 2:
                out.add(frozenset([str(slugs[0]), str(slugs[1])]))
    return out


def _load_metas() -> dict[str, dict]:
    """Read every mockups/<slug>.meta.json into a slug -> meta dict."""
    metas: dict[str, dict] = {}
    if not MOCKUPS_DIR.is_dir():
        return metas
    for path in sorted(MOCKUPS_DIR.glob("*.meta.json")):
        slug = path.stem.removesuffix(".meta")
        try:
            metas[slug] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warn: ignoring malformed {path.name}: {e}", file=sys.stderr)
    return metas


def _shared_axes(a: dict, b: dict) -> list[str]:
    """Count the axes (palette, type, era, sector, hero) where two metas
    match. Mirrors the audit-script logic so the two reports agree."""
    a_tags = a.get("tags") or {}
    b_tags = b.get("tags") or {}
    shared: list[str] = []
    a_pal = frozenset((a_tags.get("palette") or [])[:2])
    b_pal = frozenset((b_tags.get("palette") or [])[:2])
    if a_pal and a_pal == b_pal:
        shared.append("palette")
    for axis in ("type", "era", "sector", "hero"):
        av = a_tags.get(axis)
        bv = b_tags.get(axis)
        if av and av == bv:
            shared.append(axis)
    return shared


def _resolve_mockup_for_phash(slug: str) -> Path | None:
    """Look up the canonical PNG for perceptual hashing.

    Multi-image concepts hash the `home.png` view (the hero — what
    a duplicate would most obviously share). Single-image concepts
    use `mockup-<slug>.png`.
    """
    multi = MOCKUPS_DIR / slug / "home.png"
    if multi.is_file():
        return multi
    single = MOCKUPS_DIR / f"mockup-{slug}.png"
    if single.is_file():
        return single
    return None


def _avg_phash(image_path: Path) -> int | None:
    """8x8 average-hash. 64-bit integer fingerprint, comparable via XOR
    + bit_count. Returns None if Pillow is missing or the image fails
    to load — pHash pass becomes a no-op in that case (the tag-overlap
    pass still runs)."""
    try:
        from PIL import Image  # local import keeps stdlib path clean
    except ImportError:
        return None
    try:
        img = Image.open(image_path).convert("L").resize((PHASH_SIZE, PHASH_SIZE))
    except Exception:
        return None
    pixels = list(img.getdata())
    if not pixels:
        return None
    avg = sum(pixels) / len(pixels)
    bits = 0
    for px in pixels:
        bits = (bits << 1) | (1 if px > avg else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    """Population count of the XOR — number of differing bits.

    Uses ``int.bit_count()`` on Python 3.10+ and falls back to
    ``bin(...).count("1")`` on 3.9 (the project's declared minimum).
    """
    x = a ^ b
    bit_count = getattr(x, "bit_count", None)
    if bit_count is not None:
        return bit_count()
    return bin(x).count("1")


# ---------------------------------------------------------------------------
# Public entrypoints. The Result class is duplicated minimally here so the
# script runs standalone (without importing bin/check.py) and so a future
# refactor that splits Result into _lib doesn't have to change this script.


class _Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = True
        self.skipped = False
        self.demoted = False
        self.details: list[str] = []

    def fail(self, detail: str) -> None:
        self.passed = False
        self.details.append(detail)

    def warn(self, detail: str) -> None:
        # Warnings keep `passed` True but still surface in details.
        self.details.append(detail)

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.details.append(reason)


def run_check() -> _Result:
    result = _Result("Concept queue similarity (tag overlap + perceptual hash)")
    metas = _load_metas()
    if len(metas) < 2:
        result.skip(f"only {len(metas)} concept meta file(s) — nothing to compare")
        return result
    allowlist = _load_allowlist()

    slugs = sorted(metas.keys())
    fails: list[str] = []
    warns: list[str] = []

    # --- Pass 1: tag overlap ------------------------------------------------
    for a, b in combinations(slugs, 2):
        if frozenset([a, b]) in allowlist:
            continue
        shared = _shared_axes(metas[a], metas[b])
        n = len(shared)
        if n >= HARD_FAIL_THRESHOLD:
            fails.append(
                f"{a} ↔ {b}: 5/5 axis overlap ({', '.join(shared)}). "
                f"This is a duplicate concept — rework one OR add the pair "
                f"to bin/concept-similarity-allowlist.json with a rationale."
            )
        elif n >= COLLISION_THRESHOLD:
            warns.append(
                f"{a} ↔ {b}: {n}/5 axis overlap ({', '.join(shared)}). "
                f"See docs/concepts/AUDIT.md for the suggested rework."
            )
        elif n == WATCH_THRESHOLD:
            warns.append(
                f"{a} ↔ {b}: {n}/5 axis overlap ({', '.join(shared)}). "
                f"Watchlist only — confirm the third-axis differentiation reads."
            )

    # --- Pass 2: perceptual hash --------------------------------------------
    # Pillow is dev-dep; on a fresh OS install (where bin/check.py is
    # supposed to run with stdlib only) the hash returns None and we
    # silently skip this pass.
    hashes: dict[str, int] = {}
    pillow_available = True
    for slug in slugs:
        mockup = _resolve_mockup_for_phash(slug)
        if mockup is None:
            continue
        h = _avg_phash(mockup)
        if h is None:
            pillow_available = False
            break
        hashes[slug] = h
    if not pillow_available:
        warns.append(
            "Perceptual-hash pass skipped (Pillow not installed). "
            "Install requirements-dev.txt to enable."
        )
    else:
        for a, b in combinations(sorted(hashes.keys()), 2):
            if frozenset([a, b]) in allowlist:
                continue
            d = _hamming(hashes[a], hashes[b])
            if d <= PHASH_HAMMING_FAIL:
                fails.append(
                    f"{a} ↔ {b}: pHash distance {d} (≤ {PHASH_HAMMING_FAIL}). "
                    f"The mockup PNGs are visually near-identical."
                )
            elif d <= PHASH_HAMMING_WARN:
                warns.append(
                    f"{a} ↔ {b}: pHash distance {d} (≤ {PHASH_HAMMING_WARN}). "
                    f"Mockups read very similarly at thumbnail size."
                )

    if fails:
        for f in fails:
            result.fail(f)
    if warns:
        for w in warns:
            # Warnings ride along in details but don't flip `passed` — see
            # the docstring rationale.
            result.warn(w)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-concept similarity audit.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report.")
    args = parser.parse_args()

    result = run_check()
    if args.json:
        print(
            json.dumps(
                {
                    "name": result.name,
                    "passed": result.passed,
                    "skipped": result.skipped,
                    "details": result.details,
                },
                indent=2,
            )
        )
        return 0 if result.passed else 1

    label = "SKIP" if result.skipped else ("PASS" if result.passed else "FAIL")
    print(f"[{label}] {result.name}")
    for d in result.details:
        print(f"  - {d}")
    return 0 if result.passed or result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
