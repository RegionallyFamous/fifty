#!/usr/bin/env python3
"""Cluster every concept on the bench by visual axis and write AUDIT.md.

Goal: surface every group of concepts that overlap on multiple axes
(palette + type genre + era + sector + hero composition) so the
Proprietor can decide whether each member should be **kept**,
**reworked** along a specific axis, or **replaced** with a fresh
direction.

Inputs:  ``bin/concept_seed.py`` (controlled-vocabulary seed for all
         102 concepts; ``mockups/<slug>.meta.json`` files are derived
         from this).

Output:  ``docs/concepts/AUDIT.md`` — published with the queue at
         demo.regionallyfamous.com/concepts/AUDIT.md.

Usage:   python3 bin/audit-concepts.py            # rewrite the audit
         python3 bin/audit-concepts.py --dry-run  # print to stdout

Design notes:

* Cluster strength is graded by how many axes a pair shares. Two
  concepts sharing 4+ axes are highlighted as a near-collision; pairs
  sharing 3 axes get a softer "watch this" callout. The audit groups
  these into clusters using a transitive-closure walk so a single
  cluster can show "swiss / gallery / plinth all sit at the same
  contemporary-white-minimalism corner".
* Verdicts are *suggested*, not enforced. Track A is read-only; the
  follow-up Track B work uses these verdicts as input for any
  regeneration.
* The script is fully deterministic (sorts by slug, breaks ties
  alphabetically) so re-running on an unchanged seed produces a
  byte-identical AUDIT.md — so the file is safe to commit and diff.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT
from concept_seed import (
    CONCEPTS,
    CONCEPTS_BY_SLUG,
    ERAS,
    HERO_COMPOSITIONS,
    SECTORS,
    TYPE_GENRES,
    validate,
)

AUDIT_PATH = MONOREPO_ROOT / "docs" / "concepts" / "AUDIT.md"

# Pair of concepts is a "collision" when they share >= COLLISION_THRESHOLD
# axes (out of 5: dominant palette, type_genre, era, sector,
# hero_composition). 4 was deliberately picked over 3 -- 3-axis overlap
# turns out to be very common (e.g. lots of pre-1950 leather workwear
# photo-hero shops) and would drown out the genuinely-too-similar pairs.
# The "watchlist" section catches the 3-axis pairs separately so they
# don't get lost.
COLLISION_THRESHOLD = 4
WATCH_THRESHOLD = 3


def _palette_signature(concept: dict) -> frozenset[str]:
    """Use the first two palette tags as the dominant-color signature.

    Two concepts that lead with the same two colors will read as
    related at thumbnail size even if their secondary accents differ.
    """
    return frozenset(concept["palette_tags"][:2])


def _shared_axes(a: dict, b: dict) -> list[str]:
    """Return the names of every axis where ``a`` and ``b`` match."""
    shared: list[str] = []
    if _palette_signature(a) == _palette_signature(b):
        shared.append("palette")
    if a["type_genre"] == b["type_genre"]:
        shared.append("type")
    if a["era"] == b["era"]:
        shared.append("era")
    if a["sector"] == b["sector"]:
        shared.append("sector")
    if a["hero_composition"] == b["hero_composition"]:
        shared.append("hero")
    return shared


def _cluster_collisions() -> tuple[
    list[tuple[list[str], list[str]]], list[tuple[str, str, list[str]]]
]:
    """Return (collision_clusters, watch_pairs).

    A collision_cluster is (slugs[], axes_shared_pairwise[]) — the slugs
    are a transitive-closure group where every pair shares
    >= COLLISION_THRESHOLD axes; ``axes_shared_pairwise`` is the
    intersection of axes shared by every pair in the cluster (so the
    cluster's "common DNA" is obvious at a glance).

    A watch_pair is just a single (slug_a, slug_b, shared_axes) — pairs
    that overlap on exactly WATCH_THRESHOLD axes. We don't cluster
    these because the bar is loose enough that a transitive closure
    would balloon into one giant blob.
    """
    by_slug = CONCEPTS_BY_SLUG
    slugs = sorted(by_slug.keys())

    # Build adjacency for collision pairs (>= COLLISION_THRESHOLD axes).
    collision_edges: dict[str, set[str]] = defaultdict(set)
    pair_axes: dict[tuple[str, str], list[str]] = {}
    watch: list[tuple[str, str, list[str]]] = []

    for a, b in combinations(slugs, 2):
        shared = _shared_axes(by_slug[a], by_slug[b])
        n = len(shared)
        if n >= COLLISION_THRESHOLD:
            collision_edges[a].add(b)
            collision_edges[b].add(a)
            pair_axes[(a, b)] = shared
        elif n == WATCH_THRESHOLD:
            watch.append((a, b, shared))

    # Transitive closure -> clusters.
    visited: set[str] = set()
    clusters: list[tuple[list[str], list[str]]] = []
    for slug in slugs:
        if slug in visited or slug not in collision_edges:
            continue
        # BFS the connected component.
        component: list[str] = []
        queue = [slug]
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            queue.extend(collision_edges[cur] - visited)
        component.sort()
        # Common axes = intersection of axes shared by every internal pair.
        # The component is already sorted, so each pair tuple lands in the
        # same canonical order pair_axes was keyed by.
        internal_pairs: list[tuple[str, str]] = []
        seen_pairs = {frozenset(k) for k in pair_axes}
        for x, y in combinations(component, 2):
            if frozenset([x, y]) in seen_pairs:
                a, b = (x, y) if x < y else (y, x)
                internal_pairs.append((a, b))
        if internal_pairs:
            common = set(pair_axes[internal_pairs[0]])
            for p in internal_pairs[1:]:
                common &= set(pair_axes[p])
            common_axes = sorted(common)
        else:
            common_axes = []
        clusters.append((component, common_axes))
    clusters.sort(key=lambda c: (-len(c[0]), c[0][0]))
    watch.sort()
    return clusters, watch


def _suggest_verdict(slug: str, cluster: list[str]) -> tuple[str, str]:
    """Heuristic: the alphabetically-first concept in the cluster keeps
    the strongest claim on the niche; later members get a "rework" verdict
    suggesting which axis to differentiate. The user is free to override.
    """
    if cluster[0] == slug:
        return ("keep", "anchor of this cluster — the others should differentiate from this one")
    return (
        "rework",
        "shift palette OR type-genre OR hero composition so it stops reading as a cousin of "
        + cluster[0],
    )


def _summary_table(label: str, counter: Counter, vocab: set[str]) -> str:
    """Render a markdown table: token | count | bar.

    Tokens with zero usage are listed too so the gap is visible — that's
    where the bench is *under*-indexed and a future concept could land
    without crowding any existing one.
    """
    lines = [f"### {label} distribution\n"]
    lines.append("| token | count | |")
    lines.append("| --- | ---: | --- |")
    max_count = max(counter.values()) if counter else 1
    for tok in sorted(vocab):
        n = counter.get(tok, 0)
        bar = "▮" * round(20 * n / max_count) if n else ""
        lines.append(f"| `{tok}` | {n} | {bar} |")
    return "\n".join(lines) + "\n\n"


def render_audit() -> str:
    errors = validate()
    if errors:
        joined = "\n  ".join(errors)
        raise SystemExit(f"concept_seed validation failed:\n  {joined}")

    clusters, watch = _cluster_collisions()

    # Aggregate counts for the summary section. We count each concept's
    # full palette_tags set (not just the dominant pair) so the
    # distribution table reflects every color family present, not just
    # the one driving the collision logic.
    palette_counter: Counter = Counter()
    type_counter: Counter = Counter()
    era_counter: Counter = Counter()
    sector_counter: Counter = Counter()
    hero_counter: Counter = Counter()
    for c in CONCEPTS:
        for tag in c["palette_tags"]:
            palette_counter[tag] += 1
        type_counter[c["type_genre"]] += 1
        era_counter[c["era"]] += 1
        sector_counter[c["sector"]] += 1
        hero_counter[c["hero_composition"]] += 1

    lines: list[str] = []
    lines.append("# Concept queue audit\n")
    lines.append(
        "Generated by `bin/audit-concepts.py` from `bin/concept_seed.py`. "
        "Re-run after editing the seed; do **not** hand-edit this file.\n"
    )
    lines.append(f"- **Total concepts on the bench (incl. shipped):** {len(CONCEPTS)}\n")
    lines.append(f"- **Collision clusters:** {len(clusters)}\n")
    lines.append(f"- **Watchlist pairs (3-axis overlap):** {len(watch)}\n")
    lines.append("")

    lines.append("## How to read this\n")
    lines.append(
        "A *collision cluster* is two or more concepts that share at "
        f"least **{COLLISION_THRESHOLD}** of these five visual axes: "
        "dominant palette (first two color tags), type genre, era, "
        "sector, and hero composition. Inside each cluster the "
        "alphabetically-first slug is suggested as the **anchor** "
        "(keep), and every other member gets a **rework** verdict "
        "suggesting which axis to push along to escape the cluster's "
        "gravity. The Proprietor has final say — feel free to flip a "
        "verdict to *replace* (and free up the slug) if the rework "
        "would gut the concept's identity.\n"
    )
    lines.append(
        "A *watchlist pair* is two concepts with exactly "
        f"**{WATCH_THRESHOLD}**-axis overlap. They're not flagged for "
        "rework, but they're worth eyeballing in the gallery to make "
        "sure the third axis really does separate them.\n"
    )
    lines.append("")

    lines.append("## Collision clusters\n")
    if not clusters:
        lines.append("_No collision clusters at the current threshold._\n\n")
    for component, common_axes in clusters:
        axis_str = ", ".join(common_axes) if common_axes else "(varies pairwise)"
        lines.append(
            f"### `{' / '.join(component)}` — {len(component)} concepts, shared axes: {axis_str}\n"
        )
        for slug in component:
            verdict, rationale = _suggest_verdict(slug, component)
            c = CONCEPTS_BY_SLUG[slug]
            lines.append(
                f"- **`{slug}`** ({c['name']}) — _{verdict}_. {rationale}.\n"
                f"  - palette: {', '.join(c['palette_tags'])}\n"
                f"  - {c['type_genre']} · {c['era']} · {c['sector']} · {c['hero_composition']}\n"
                f"  - blurb: {c['blurb']}\n"
            )
        lines.append("")

    lines.append("## Watchlist (3-axis overlap)\n")
    if not watch:
        lines.append("_No watchlist pairs._\n\n")
    else:
        lines.append("| pair | shared axes |")
        lines.append("| --- | --- |")
        for a, b, axes in watch:
            lines.append(f"| `{a}` ↔ `{b}` | {', '.join(axes)} |")
        lines.append("")

    lines.append("## Distribution by axis\n")
    lines.append(
        "Where the bench is over- or under-indexed. A concept with a "
        "rare combination is a strong addition; a concept that piles "
        "onto already-saturated tokens (e.g. yet-another `pre-1950 + "
        "cream + slab-serif`) probably needs to differentiate before "
        "shipping.\n"
    )
    lines.append("")
    lines.append(_summary_table("Palette tags", palette_counter, set(palette_counter.keys())))
    lines.append(_summary_table("Type genre", type_counter, TYPE_GENRES))
    lines.append(_summary_table("Era", era_counter, ERAS))
    lines.append(_summary_table("Sector", sector_counter, SECTORS))
    lines.append(_summary_table("Hero composition", hero_counter, HERO_COMPOSITIONS))

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster concepts and write AUDIT.md.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print to stdout instead of writing the file."
    )
    args = parser.parse_args()

    out = render_audit()
    if args.dry_run:
        sys.stdout.write(out)
        return 0
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(out, encoding="utf-8")
    print(f"wrote {AUDIT_PATH.relative_to(MONOREPO_ROOT)} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
