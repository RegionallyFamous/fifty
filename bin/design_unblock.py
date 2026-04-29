#!/usr/bin/env python3
"""Self-healing unblocker for `bin/design.py` runs.

`bin/design-watch.py` captures a blocked run as
`tmp/runs/<run-id>/summary.json` plus per-cell artifacts under
`tmp/snaps/<slug>/`.  This module turns that evidence into three
artifacts that are the operator-facing contract of the self-healing
loop:

* `repair-plan.json` — one compact, reproducible repair packet per
  run.  It classifies each blocker (`product-photo-duplicate`,
  `hover-contrast`, `microcopy-duplicate`, `snap-a11y-color-contrast`,
  `design-score-low`, `unknown`), computes a stable fingerprint for it, pins the evidence
  (snap crops, findings files, affected source files), and names a
  verification ladder (targeted checks first, then route-scoped snap,
  then a full rerun) so the agent never flies blind.
* `repair-attempts.jsonl` — one JSON record per repair attempt.  It
  carries the before/after fingerprints, the files the LLM touched,
  the commands it ran, the verification verdict, and the decision.
* `factory-defects.jsonl` — one JSON record per successful repair that
  should be promoted back into deterministic factory tooling.  Recipe
  fixes are recorded as covered; JSON/tool-rescue fixes are recorded
  as tooling gaps until a check, generator phase, or recipe absorbs
  the failure class.
* `STATUS.md` — updated in place so the operator sees the current
  attempt, files touched, progress signal, and the exact next action.

This file deliberately does no editing on its own; edits are done by
the caller (the agent or the watcher's `--auto-unblock` driver) using
the packet.  `apply` runs the verification ladder and returns the
progress verdict so the caller can decide whether to resume the
pipeline, retry, or stop.

Design ground rules (enforced by tests under `tests/tools/`):

* No `git` mutation helpers.  This module never amends, force-pushes,
  or deletes tracked work.  It also refuses to proceed if the
  worktree has unrelated dirty framework changes that the repair
  would need to overwrite.
* No allowlist growth.  The unblocker never appends to
  `tests/visual-baseline/heuristics-allowlist.json` or
  `tests/check-baseline-failures.json`.  If those are the only way to
  make a check green, escalation is the correct outcome.
* All edits stay inside the current worktree.  The caller is
  responsible for selecting the worktree; this module only reads
  `ROOT` relative to itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from factory_rules import get_rule  # noqa: E402

# ---------------------------------------------------------------------------
# Blocker classification
# ---------------------------------------------------------------------------

# Each entry is (category, title_needle, detail_needle_or_None).  Needles
# are lowercase substring matches over (title + '\n' + detail).  The first
# matching rule wins; fallback is `unknown`.
_CLASSIFIER_RULES: tuple[tuple[str, str, str | None], ...] = (
    ("php-syntax", "php syntax", None),
    ("product-photo-duplicate", "product photographs are visually distinct", None),
    ("hover-contrast", "hover/focus states have legible", None),
    ("microcopy-duplicate", "pattern + heading microcopy distinct", None),
    ("microcopy-duplicate", "all rendered text distinct", None),
    ("wc-microcopy-duplicate", "wc microcopy maps are distinct", None),
    ("cross-theme-product-images", "product photographs are unique across themes", None),
    ("hero-placeholders-duplicate", "hero placeholders are unique across themes", None),
    ("screenshot-duplicate", "theme screenshots distinct", None),
    ("snap-a11y-color-contrast", "recent snaps carry no serious", None),
    ("placeholder-images", "product image", "woocommerce placeholder"),
    ("placeholder-images", "woocommerce placeholder", None),
    ("category-images", "category-images.json", "category cover art"),
    ("snap-evidence-stale", "snap evidence is fresh", None),
    ("scorecard-mass-failure", "scorecard mass failure", None),
    ("design-score-low", "design scorecard meets minimum", None),
    ("factory-timeout", "factory timeout guard", None),
    ("factory-stall", "factory stall guard", None),
)

KNOWN_CATEGORIES = frozenset(
    {
        "php-syntax",
        "product-photo-duplicate",
        "hover-contrast",
        "microcopy-duplicate",
        "wc-microcopy-duplicate",
        "cross-theme-product-images",
        "hero-placeholders-duplicate",
        "screenshot-duplicate",
        "snap-a11y-color-contrast",
        "placeholder-images",
        "category-images",
        "snap-evidence-stale",
        "scorecard-mass-failure",
        "design-score-low",
        "factory-timeout",
        "factory-stall",
    }
)


def _classify(title: str, detail: str) -> str:
    haystack = f"{title}\n{detail}".lower()
    for category, title_needle, detail_needle in _CLASSIFIER_RULES:
        if title_needle in haystack and (detail_needle is None or detail_needle in haystack):
            return category
    return "unknown"


# ---------------------------------------------------------------------------
# Fingerprints (stable across attempts, change when evidence changes)
# ---------------------------------------------------------------------------

# Pull out the "loud" part of a detail string so the fingerprint survives
# small formatting jitter (e.g. a ratio changing by 0.01) but changes when
# the LLM actually touches the right element.
_DETAIL_EXTRACTORS: dict[str, re.Pattern[str]] = {
    "php-syntax": re.compile(r"\b(functions\.php|patterns?/[a-z0-9_-]+\.php)\b"),
    "product-photo-duplicate": re.compile(
        r"(product-wo-[a-z0-9-]+\.jpg)\s*~\s*(product-wo-[a-z0-9-]+\.jpg)"
    ),
    "hover-contrast": re.compile(r"([.#][^{}:\s]+:hover[^{}\s]*)"),
    "microcopy-duplicate": re.compile(
        r"((?:patterns?|templates?|parts?)/[a-z0-9_-]+\.(?:php|html))"
    ),
    "wc-microcopy-duplicate": re.compile(r"(WC microcopy maps share translations)"),
    "cross-theme-product-images": re.compile(r"(\d+)\s+product-wo-\*\.jpg"),
    "hero-placeholders-duplicate": re.compile(r"(\d+)\s+hero placeholder"),
    "screenshot-duplicate": re.compile(r"share identical screenshot\.png"),
    "snap-a11y-color-contrast": re.compile(r"\b(\d+)\s+NEW severity:error finding\(s\)"),
    "placeholder-images": re.compile(r"([a-z0-9-]+/playground/[^\s,;]+)"),
    "category-images": re.compile(r"([a-z0-9-]+/playground/content/category-images\.json)"),
    "snap-evidence-stale": re.compile(r"(\S+\.(?:html|php|json|css))"),
    "scorecard-mass-failure": re.compile(r"([a-z_]+)\s+scored\s+(\d+)/(\d+)"),
    "design-score-low": re.compile(r"([a-z_]+)\s+scored\s+(\d+)/(\d+)"),
    "factory-timeout": re.compile(r"(?:while|phase=)\s+([a-z0-9_-]+)"),
    "factory-stall": re.compile(r"(?:while|phase=)\s+([a-z0-9_-]+)"),
}


def _detail_fingerprint(category: str, detail: str) -> str:
    pat = _DETAIL_EXTRACTORS.get(category)
    if pat is None:
        return hashlib.sha256(detail.strip().lower().encode("utf-8")).hexdigest()[:12]
    match = pat.search(detail)
    if not match:
        return hashlib.sha256(detail.strip().lower().encode("utf-8")).hexdigest()[:12]
    key = "|".join(g for g in match.groups() if g is not None) or match.group(0)
    return hashlib.sha256(key.lower().encode("utf-8")).hexdigest()[:12]


def blocker_fingerprint(category: str, slug: str, detail: str) -> str:
    return f"{category}:{slug}:{_detail_fingerprint(category, detail)}"


# ---------------------------------------------------------------------------
# Evidence packet dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SnapFinding:
    route: str
    viewport: str
    kind: str
    severity: str
    message: str
    selector: str = ""
    crop_path: str = ""
    screenshot_path: str = ""
    axe_help_url: str = ""


@dataclass
class Blocker:
    category: str
    title: str
    summary: str
    detail: str
    next_action: str
    fingerprint: str
    affected_files: list[str] = field(default_factory=list)
    affected_routes: list[str] = field(default_factory=list)
    affected_viewports: list[str] = field(default_factory=list)
    snap_findings: list[SnapFinding] = field(default_factory=list)
    verification: list[list[str]] = field(default_factory=list)
    source_snippets: list[str] = field(default_factory=list)
    recommended_recipes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RepairPlan:
    run_id: str
    slug: str
    run_dir: str
    worktree_root: str
    generated_at: float
    worktree_clean: bool
    worktree_unrelated_files: list[str]
    blockers: list[Blocker]
    resume_phase: str
    verification_ladder: list[list[str]]
    allowed_commands: list[str] = field(default_factory=list)
    recommended_recipes: list[str] = field(default_factory=list)
    requires_secret: list[str] = field(default_factory=list)
    human_boundary: str | None = None
    artifact_paths: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Git worktree inspection (read-only; no mutation)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 127, ""
    return proc.returncode, proc.stdout


def _changed_files(cwd: Path) -> list[str]:
    rc, out = _run_git(["status", "--porcelain=v1"], cwd=cwd)
    if rc != 0:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # porcelain v1: XY␣<path>  (rename = `R  old -> new`)
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip())
    return files


_FRAMEWORK_PREFIXES = ("bin/", ".githooks/", ".cursor/rules/", "playground/")


def _unrelated_framework_files(slug: str, files: list[str]) -> list[str]:
    """Return framework-owned files that are NOT owned by the theme slug."""
    # `bin/design.py` regenerates docs/ late in the pipeline so draft
    # short URLs exist for failed builds too. Those generated redirects are
    # safe to carry while repairing the theme; treating them as unrelated
    # framework drift blocks the self-healing loop immediately after a
    # failed commit hook.
    slug_prefixes = (f"{slug}/", f"tests/visual-baseline/{slug}/")
    unrelated: list[str] = []
    for path in files:
        if path.startswith(slug_prefixes):
            continue
        if path.startswith(_FRAMEWORK_PREFIXES):
            unrelated.append(path)
    return unrelated


# ---------------------------------------------------------------------------
# Snap evidence lookup
# ---------------------------------------------------------------------------


def _snap_review(slug: str) -> dict[str, Any]:
    path = ROOT / "tmp" / "snaps" / slug / "review.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _load_findings(slug: str, viewport: str, route: str) -> list[dict[str, Any]]:
    path = ROOT / "tmp" / "snaps" / slug / viewport / f"{route}.findings.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items = doc.get("findings", [])
    return items if isinstance(items, list) else []


def _error_cells(slug: str) -> list[tuple[str, str]]:
    """Return the (viewport, route) cells that carry severity=error findings."""
    review = _snap_review(slug)
    cells: list[tuple[str, str]] = []
    for row in review.get("routes", []):
        if not isinstance(row, dict):
            continue
        if int(row.get("error", 0) or 0) <= 0:
            continue
        vp = str(row.get("viewport") or "")
        route = str(row.get("route") or "")
        if vp and route:
            cells.append((vp, route))
    return cells


def _snap_findings_for_blocker(slug: str, limit: int = 12) -> list[SnapFinding]:
    findings: list[SnapFinding] = []
    for viewport, route in _error_cells(slug):
        for item in _load_findings(slug, viewport, route):
            if item.get("severity") != "error":
                continue
            findings.append(
                SnapFinding(
                    route=route,
                    viewport=viewport,
                    kind=str(item.get("kind") or ""),
                    severity="error",
                    message=str(item.get("message") or "")[:400],
                    selector=str(item.get("selector") or ""),
                    crop_path=str(item.get("crop_path") or ""),
                    screenshot_path=str(item.get("screenshot_path") or ""),
                    axe_help_url=str(item.get("axe_help_url") or ""),
                )
            )
            if len(findings) >= limit:
                return findings
    return findings


def _latest_design_score(slug: str) -> dict[str, Any]:
    runs_dir = ROOT / "tmp" / "runs"
    if not runs_dir.is_dir():
        return {}
    candidates = sorted(
        [p for p in runs_dir.glob(f"*{slug}*/design-score.json") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        fallback = runs_dir / f"design-{slug}" / "design-score.json"
        candidates = [fallback] if fallback.is_file() else []
    if not candidates:
        return {}
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scorecard_top_findings_snippet(slug: str, *, limit: int = 12) -> str:
    doc = _latest_design_score(slug)
    if not doc:
        return ""
    groups = doc.get("top_weak_findings") or []
    if not isinstance(groups, list):
        groups = []
    lines = [
        f"### scorecard diagnostic packet for {slug}",
        f"- classification: {doc.get('classification', 'unknown')}",
        f"- overall: {doc.get('overall', 'n/a')}/{doc.get('threshold', 'n/a')}",
        f"- weak findings: {len(doc.get('weak_findings') or [])}",
        "- top grouped weak findings:",
    ]
    for item in groups[:limit]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "  - "
            f"{item.get('count', 0)}x "
            f"{item.get('category', 'unknown')}/"
            f"{item.get('kind', 'unknown')} "
            f"on {item.get('route', 'unknown')}/"
            f"{item.get('viewport', 'unknown')} "
            f"({item.get('severity', 'unknown')}): "
            f"{str(item.get('sample_message') or '')[:220]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Affected-file inference
# ---------------------------------------------------------------------------


def _affected_files_for_category(
    category: str,
    slug: str,
    detail: str,
    snap_findings: list[SnapFinding],
) -> list[str]:
    out: list[str] = []

    def add(path: str) -> None:
        if path and path not in out:
            out.append(path)

    if category == "php-syntax":
        add(f"{slug}/functions.php")
        pat = _DETAIL_EXTRACTORS["php-syntax"]
        for rel in pat.findall(detail):
            add(f"{slug}/{rel}")

    elif category == "product-photo-duplicate":
        pat = _DETAIL_EXTRACTORS["product-photo-duplicate"]
        m = pat.search(detail)
        if m:
            for name in m.groups():
                if name:
                    add(f"{slug}/playground/images/{name}")
        add(f"{slug}/playground/content/product-images.json")

    elif category == "hover-contrast":
        add(f"{slug}/theme.json")
        add(f"{slug}/functions.php")

    elif category == "microcopy-duplicate":
        pat = _DETAIL_EXTRACTORS["microcopy-duplicate"]
        for rel in pat.findall(detail):
            add(f"{slug}/{rel}")

    elif category == "wc-microcopy-duplicate":
        add(f"{slug}/functions.php")

    elif category == "cross-theme-product-images":
        add(f"{slug}/playground/content/product-images.json")
        add(f"{slug}/playground/content/image-manifest.json")
        add(f"{slug}/playground/images/")

    elif category == "hero-placeholders-duplicate":
        add(f"{slug}/playground/content/content.xml")
        add(f"{slug}/playground/images/")

    elif category == "screenshot-duplicate":
        add(f"{slug}/screenshot.png")

    elif category == "snap-a11y-color-contrast":
        add(f"{slug}/theme.json")
        # A handful of the known snap contrast selectors land in phase-I
        # overrides or functions.php overrides — surface them as hints so
        # the LLM knows where structural fixes live.
        add("bin/append-wc-overrides.py")

    elif category == "placeholder-images":
        add(f"{slug}/playground/content/product-images.json")
        add(f"{slug}/playground/content/category-images.json")
        # Hint the images/ folder so the agent can see what exists.
        add(f"{slug}/playground/images/")

    elif category == "snap-evidence-stale":
        pat = _DETAIL_EXTRACTORS["snap-evidence-stale"]
        for rel in pat.findall(detail):
            add(rel)

    elif category in {"design-score-low", "scorecard-mass-failure"}:
        add(f"{slug}/theme.json")
        add(f"{slug}/design-intent.md")
        scorecards = sorted((ROOT / "tmp" / "runs").glob("*/design-score.json"))
        for scorecard in scorecards[-3:]:
            try:
                add(str(scorecard.relative_to(ROOT)))
            except ValueError:
                pass

    elif category in {"factory-timeout", "factory-stall"}:
        add("bin/design-watch.py")
        add("bin/design.py")
        add("bin/snap-vision-review.py")
        add("bin/_vision_lib.py")
        for rel in _latest_run_artifacts(slug):
            add(rel)

    # Snap findings usually implicate a template/part/pattern somewhere.
    # We can't safely guess which one; surface the rendered HTML as a
    # pointer so the LLM can trace back to the source.
    for f in snap_findings:
        html = f"tmp/snaps/{slug}/{f.viewport}/{f.route}.html"
        add(html)

    return out


_FILE_LINE_RE = re.compile(
    r"((?:[a-z0-9_-]+/)?(?:functions\.php|(?:patterns?|templates?|parts?)/[a-z0-9_-]+\.(?:php|html)|theme\.json))"
    r"(?:(?:\s+on\s+line|\:)(?:\s*)?|\b.*?\bline\s+)(\d+)",
    re.IGNORECASE,
)


def _line_refs_from_detail(slug: str, detail: str) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for rel, line_raw in _FILE_LINE_RE.findall(detail):
        path = rel
        if not path.startswith(f"{slug}/"):
            path = f"{slug}/{path}"
        try:
            line_no = int(line_raw)
        except ValueError:
            continue
        if (path, line_no) not in refs:
            refs.append((path, line_no))
    return refs


def _focused_snippet(rel: str, line_no: int, *, radius: int = 35) -> str:
    path = ROOT / rel
    if not path.is_file():
        return f"### {rel}:{line_no}\n(missing)"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return f"### {rel}:{line_no}\n(binary)"
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    body = "\n".join(f"{idx}|{lines[idx - 1]}" for idx in range(start, end + 1))
    return f"### {rel}:{line_no}\n```\n{body}\n```"


def _focused_text_snippet(rel: str, needle: str, *, radius: int = 1400) -> str:
    path = ROOT / rel
    if not path.is_file():
        return f"### {rel}\n(missing)"
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"### {rel}\n(binary)"
    idx = data.find(needle)
    if idx == -1:
        return ""
    start = max(0, idx - radius)
    end = min(len(data), idx + len(needle) + radius)
    prefix = "... [truncated before]\n" if start else ""
    suffix = "\n... [truncated after]" if end < len(data) else ""
    return f"### {rel} around `{needle}`\n```\n{prefix}{data[start:end]}{suffix}\n```"


def _source_snippets_for_blocker(
    category: str,
    slug: str,
    detail: str,
    affected_files: list[str],
) -> list[str]:
    snippets: list[str] = []
    for rel, line_no in _line_refs_from_detail(slug, detail):
        snippets.append(_focused_snippet(rel, line_no))
    # If no line was provided, include compact source for the most
    # actionable text/PHP files. Binary assets are intentionally skipped.
    if snippets:
        return snippets
    if category in {"design-score-low", "scorecard-mass-failure"}:
        score_snippet = _scorecard_top_findings_snippet(slug)
        if score_snippet:
            snippets.append(score_snippet)
    if category in {"hover-contrast", "snap-a11y-color-contrast"}:
        for needle in ("single_add_to_cart_button:hover", ".button:hover", ":hover"):
            snippet = _focused_text_snippet(f"{slug}/theme.json", needle)
            if snippet:
                snippets.append(snippet)
                break
    for rel in affected_files:
        if rel.endswith("/") or rel.startswith("tmp/snaps/") or rel.startswith("bin/"):
            continue
        if not rel.endswith((".php", ".html", ".json")):
            continue
        path = ROOT / rel
        snippets.append(f"### {rel}\n```\n{_file_snippet(path)}\n```")
        if category in {"php-syntax", "wc-microcopy-duplicate"}:
            break
    return snippets


def _recipes_for_category(category: str) -> list[str]:
    return {
        "php-syntax": ["php_syntax"],
        "cross-theme-product-images": ["generate_product_photos"],
        "product-photo-duplicate": ["generate_product_photos"],
        "hero-placeholders-duplicate": ["generate_theme_images"],
        "placeholder-images": ["snap_routes"],
        "screenshot-duplicate": ["build_screenshot"],
        "snap-evidence-stale": ["snap_routes"],
    }.get(category, [])


def _latest_run_artifacts(slug: str, limit: int = 6) -> list[str]:
    runs_dir = ROOT / "tmp" / "runs"
    if not runs_dir.is_dir():
        return []
    candidates = sorted(
        [p for p in runs_dir.glob(f"*{slug}*") if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[str] = []
    for run_dir in candidates[:limit]:
        for name in ("STATUS.md", "summary.json", "events.jsonl"):
            rel = run_dir / name
            if rel.exists():
                try:
                    out.append(str(rel.relative_to(ROOT)))
                except ValueError:
                    out.append(str(rel))
    return out


def _allowed_commands_for_categories(categories: list[str]) -> list[str]:
    commands = {"check_quick", "check_only"}
    if any(
        c in categories
        for c in {
            "placeholder-images",
            "snap-evidence-stale",
            "snap-a11y-color-contrast",
            "screenshot-duplicate",
            "design-score-low",
        }
    ):
        commands.add("snap_routes")
        commands.add("snap_report")
    if any(c in categories for c in {"factory-timeout", "factory-stall"}):
        commands.add("snap_report")
    if any(c in categories for c in {"product-photo-duplicate", "cross-theme-product-images"}):
        commands.add("generate_product_photos")
    if "screenshot-duplicate" in categories:
        commands.add("build_screenshot")
    if "design-score-low" in categories:
        commands.add("design_scorecard")
    commands.add("sync_playground")
    commands.add("build_index")
    return sorted(commands)


# ---------------------------------------------------------------------------
# Verification ladder
# ---------------------------------------------------------------------------


# Which `bin/check.py --only` alias to hit first per category.  These map
# onto the `_ONLY_ALIASES` table in `bin/check.py` or the function name
# directly when no alias exists.
_CHECK_ONLY_BY_CATEGORY: dict[str, list[str]] = {
    "product-photo-duplicate": ["product_image_visual_diversity"],
    "hover-contrast": ["hover_state_legibility"],
    "microcopy-duplicate": [
        "pattern_microcopy_distinct",
        "all_rendered_text_distinct_across_themes",
    ],
    "snap-a11y-color-contrast": ["no_serious_axe_in_recent_snaps"],
    "placeholder-images": [
        "no-woocommerce-placeholder",
        "product-images-json",
        "category-images-json",
    ],
    "snap-evidence-stale": ["snap-evidence"],
}


def _check_cmd(slug: str, only: list[str]) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "bin" / "check.py"),
        slug,
        "--quick",
        "--only",
        *only,
    ]


def _snap_routes_for_findings(findings: list[SnapFinding]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in findings:
        if f.route and f.route not in seen:
            seen.add(f.route)
            out.append(f.route)
    return out


def _snap_shoot_cmd(slug: str, routes: list[str]) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "bin" / "snap.py"),
        "shoot",
        slug,
        "--viewports",
        "mobile,desktop",
    ]
    if routes:
        cmd.extend(["--routes", ",".join(routes)])
    return cmd


def _verification_for_blocker(
    category: str, slug: str, snap_findings: list[SnapFinding]
) -> list[list[str]]:
    ladder: list[list[str]] = []

    checks = _CHECK_ONLY_BY_CATEGORY.get(category, [])
    if checks:
        ladder.append(_check_cmd(slug, checks))

    if category == "snap-a11y-color-contrast":
        routes = _snap_routes_for_findings(snap_findings) or ["journal", "journal-post"]
        ladder.append(_snap_shoot_cmd(slug, routes))
        # After reshoot, rerun the same check to re-read fresh evidence.
        ladder.append(_check_cmd(slug, ["no_serious_axe_in_recent_snaps"]))
    elif category == "placeholder-images":
        ladder.append(_snap_shoot_cmd(slug, ["shop", "category"]))
        ladder.append(_check_cmd(slug, ["no-woocommerce-placeholder"]))
    elif category == "design-score-low":
        ladder.append(
            _snap_shoot_cmd(
                slug,
                [
                    "home",
                    "shop",
                    "product-simple",
                    "cart-filled",
                    "checkout-filled",
                    "journal-post",
                ],
            )
        )
        ladder.append(
            [
                sys.executable,
                str(ROOT / "bin" / "design-scorecard.py"),
                slug,
                "--run-id",
                os.environ.get("FIFTY_DESIGN_RUN_ID") or f"design-{slug}",
            ]
        )

    return ladder


def _resume_phase_for(categories: list[str]) -> str:
    # Any visual blocker forces a re-snap + re-check; anything else can
    # be resumed at `check` after the LLM edits.
    visual = {"snap-a11y-color-contrast", "placeholder-images", "design-score-low"}
    if any(c in visual for c in categories):
        return "snap"
    if any(c in {"factory-timeout", "factory-stall"} for c in categories):
        return "validate"
    return "check"


def _full_verification_ladder(slug: str, categories: list[str]) -> list[list[str]]:
    ladder: list[list[str]] = []
    # Final static sweep.
    ladder.append(
        [
            sys.executable,
            str(ROOT / "bin" / "check.py"),
            slug,
            "--quick",
        ]
    )
    # Then a scoped snap sweep if any visual blocker is present.
    if any(
        c in {"snap-a11y-color-contrast", "placeholder-images", "design-score-low"}
        for c in categories
    ):
        ladder.append(
            [
                sys.executable,
                str(ROOT / "bin" / "snap.py"),
                "shoot",
                slug,
            ]
        )
        ladder.append(
            [
                sys.executable,
                str(ROOT / "bin" / "snap.py"),
                "report",
                slug,
            ]
        )
    return ladder


# ---------------------------------------------------------------------------
# Repair plan assembly
# ---------------------------------------------------------------------------


def _summary_to_blockers(summary: dict[str, Any]) -> list[Blocker]:
    slug = str(summary.get("slug") or "")
    blockers: list[Blocker] = []
    for raw in summary.get("check_failures", []) or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "")
        detail = str(raw.get("detail") or "")
        summary_line = str(raw.get("summary") or "")
        next_action = str(raw.get("next_action") or "")
        category = _classify(title, detail)
        fp = blocker_fingerprint(category, slug, detail)
        snap_findings: list[SnapFinding] = []
        if category == "snap-a11y-color-contrast":
            snap_findings = _snap_findings_for_blocker(slug)
        affected_files = _affected_files_for_category(category, slug, detail, snap_findings)
        affected_routes = sorted({f.route for f in snap_findings if f.route})
        affected_viewports = sorted({f.viewport for f in snap_findings if f.viewport})
        verification = _verification_for_blocker(category, slug, snap_findings)
        recipes = _recipes_for_category(category)
        source_snippets = _source_snippets_for_blocker(
            category,
            slug,
            detail,
            affected_files,
        )
        blocker = Blocker(
            category=category,
            title=title,
            summary=summary_line,
            detail=detail,
            next_action=next_action,
            fingerprint=fp,
            affected_files=affected_files,
            affected_routes=affected_routes,
            affected_viewports=affected_viewports,
            snap_findings=snap_findings,
            verification=verification,
            source_snippets=source_snippets,
            recommended_recipes=recipes,
        )
        if category == "unknown":
            blocker.notes.append(
                "Unknown blocker category. Allowed edits are the same "
                "as any other blocker (source/assets in the theme), but "
                "the verification ladder is generic; double-check what "
                "the check actually wants."
            )
        elif category in {"factory-timeout", "factory-stall"}:
            blocker.notes.append(
                "The watcher stopped a wedged or overlong child process. "
                "Inspect STATUS.md, summary.json, and events.jsonl first; "
                "prefer a small fix that makes the slow phase fail fast, "
                "emit progress, narrow its scope, or resume safely."
            )
        elif category == "scorecard-mass-failure":
            blocker.notes.append(
                "Mass scorecard failures are strategy failures, not repair-loop "
                "inputs. Do not run recipes, JSON repair, tool-rescue, "
                "resume-from-snap, or full re-shoots; inspect the diagnostic "
                "packet and fix the generator, spec, design intent, route "
                "state, or scorecard calibration."
            )
        blockers.append(blocker)
    return blockers


def _load_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "summary.json"
    if not path.is_file():
        raise SystemExit(
            f"No summary.json under {run_dir}; run `bin/design-watch.py` first "
            "so the blocker evidence exists."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"summary.json is not valid JSON: {exc}") from exc


def build_repair_plan(run_dir: Path) -> RepairPlan:
    summary = _load_summary(run_dir)
    slug = str(summary.get("slug") or "")
    if not slug:
        raise SystemExit(
            "summary.json has no `slug`; the watcher may not have identified "
            "the theme before the run blocked."
        )
    blockers = _summary_to_blockers(summary)
    changed = _changed_files(ROOT)
    unrelated = _unrelated_framework_files(slug, changed)
    categories = [b.category for b in blockers]
    resume = _resume_phase_for(categories)
    ladder = _full_verification_ladder(slug, categories)
    recommended_recipes = sorted(
        {recipe for blocker in blockers for recipe in blocker.recommended_recipes}
    )
    human_boundary = "scorecard-mass-failure" if "scorecard-mass-failure" in categories else None
    artifact_paths = [
        str(run_dir / "repair-plan.json"),
        str(run_dir / "repair-attempts.jsonl"),
        str(run_dir / "factory-defects.jsonl"),
        str(run_dir / "STATUS.md"),
    ]
    return RepairPlan(
        run_id=str(summary.get("run_id") or run_dir.name),
        slug=slug,
        run_dir=str(run_dir),
        worktree_root=str(ROOT),
        generated_at=time.time(),
        worktree_clean=not unrelated,
        worktree_unrelated_files=unrelated,
        blockers=blockers,
        resume_phase=resume,
        verification_ladder=ladder,
        allowed_commands=_allowed_commands_for_categories(categories),
        recommended_recipes=recommended_recipes,
        requires_secret=[],
        human_boundary=human_boundary,
        artifact_paths=artifact_paths,
    )


def _plan_to_dict(plan: RepairPlan) -> dict[str, Any]:
    d = asdict(plan)
    # asdict keeps dataclasses in `snap_findings`; already fine.
    return d


def write_repair_plan(run_dir: Path, plan: RepairPlan) -> Path:
    out = run_dir / "repair-plan.json"
    out.write_text(
        json.dumps(_plan_to_dict(plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# Attempt records (jsonl append)
# ---------------------------------------------------------------------------


@dataclass
class AttemptRecord:
    at: float
    attempt: int
    decision: str  # improved, not-improved, worse, stopped, fixed
    reason: str
    before: list[str]
    after: list[str]
    touched_files: list[str]
    commands: list[list[str]]
    verification: dict[str, Any]
    notes: list[str] = field(default_factory=list)


@dataclass
class FactoryDefectRecord:
    schema_version: int
    defect_id: str
    at: float
    run_id: str
    slug: str
    attempt: int
    layer: str
    decision: str
    reason: str
    before: list[str]
    after: list[str]
    resolved_fingerprints: list[str]
    category: str
    title: str
    detail: str
    touched_files: list[str]
    commands: list[list[str]]
    recipes: list[str]
    promotion_target: str
    suggested_files: list[str]
    tooling_status: str
    prevention_layer: str
    prevention_phase: str
    owner: str
    fixture: str
    promotion_status: str
    first_seen_run_id: str


SUCCESSFUL_REPAIR_DECISIONS = frozenset({"fixed", "improved"})
FACTORY_DEFECT_SCHEMA_VERSION = 2

_FACTORY_PATH_PREFIXES = (
    "bin/",
    ".githooks/",
    ".cursor/rules/",
    "tests/",
)

_PROMOTION_TARGET_BY_CATEGORY = {
    "php-syntax": "check",
    "product-photo-duplicate": "generator",
    "hover-contrast": "design-phase",
    "microcopy-duplicate": "generator",
    "wc-microcopy-duplicate": "generator",
    "cross-theme-product-images": "generator",
    "hero-placeholders-duplicate": "generator",
    "screenshot-duplicate": "design-phase",
    "snap-a11y-color-contrast": "design-phase",
    "placeholder-images": "design-phase",
    "snap-evidence-stale": "design-phase",
    "design-score-low": "design-phase",
}

_SUGGESTED_FILES_BY_CATEGORY = {
    "php-syntax": ["bin/clone.py", "bin/check.py"],
    "product-photo-duplicate": ["bin/generate-product-photos.py", "bin/design.py"],
    "hover-contrast": ["bin/autofix-contrast.py", "bin/design.py", "bin/check.py"],
    "microcopy-duplicate": ["bin/generate-microcopy.py", "bin/design.py", "bin/check.py"],
    "wc-microcopy-duplicate": ["bin/generate-microcopy.py", "bin/check.py"],
    "cross-theme-product-images": ["bin/generate-product-photos.py", "bin/check.py"],
    "hero-placeholders-duplicate": ["bin/generate-product-photos.py", "bin/check.py"],
    "screenshot-duplicate": ["bin/build-theme-screenshots.py", "bin/design.py"],
    "snap-a11y-color-contrast": ["bin/append-wc-overrides.py", "bin/design.py"],
    "placeholder-images": ["bin/seed-playground-content.py", "bin/design.py"],
    "snap-evidence-stale": ["bin/snap.py", "bin/design.py"],
    "design-score-low": ["bin/design-scorecard.py", "bin/design.py"],
}


def _has_factory_touches(touched_files: list[str]) -> bool:
    return any(path.startswith(_FACTORY_PATH_PREFIXES) for path in touched_files)


def _recipes_from_record(record: AttemptRecord) -> list[str]:
    raw = record.verification.get("recipes") if isinstance(record.verification, dict) else []
    return [str(recipe) for recipe in raw or []]


def _promotion_target(category: str, touched_files: list[str]) -> str:
    if _has_factory_touches(touched_files):
        return "manual-review"
    return get_rule(category).promotion_target


def _tooling_status(layer: str, category: str, touched_files: list[str]) -> str:
    if _has_factory_touches(touched_files):
        return "manual-review"
    if layer == "recipe":
        return "covered-by-recipe"
    if layer in {"json-llm", "tool-rescue"}:
        return "needs-tooling" if category != "unknown" else "manual-review"
    return "candidate"


def _promotion_status(category: str, layer: str, touched_files: list[str]) -> str:
    if _has_factory_touches(touched_files):
        return "manual-review"
    rule = get_rule(category)
    if rule.layer == "manual-review":
        return "manual-review"
    if rule.layer == "render":
        return "render-only"
    if layer == "recipe":
        return "covered-by-recipe"
    return "needs-promotion"


def _defect_id(
    *,
    run_id: str,
    slug: str,
    attempt: int,
    layer: str,
    category: str,
    resolved_fingerprint: str,
) -> str:
    key = "|".join(
        [
            str(FACTORY_DEFECT_SCHEMA_VERSION),
            run_id,
            slug,
            str(attempt),
            layer,
            category,
            resolved_fingerprint,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def _factory_defects_for_attempt(
    run_dir: Path,
    record: AttemptRecord,
) -> list[FactoryDefectRecord]:
    if record.decision not in SUCCESSFUL_REPAIR_DECISIONS:
        return []

    plan = build_repair_plan(run_dir)
    blocker_by_fp = {blocker.fingerprint: blocker for blocker in plan.blockers}
    resolved = sorted(set(record.before) - set(record.after))
    if not resolved:
        return []

    layer = str(record.verification.get("layer") or "unknown")
    recipes = _recipes_from_record(record)
    records: list[FactoryDefectRecord] = []
    for fingerprint in resolved:
        blocker = blocker_by_fp.get(fingerprint)
        category = blocker.category if blocker else "unknown"
        target = _promotion_target(category, record.touched_files)
        rule = get_rule(category)
        records.append(
            FactoryDefectRecord(
                schema_version=FACTORY_DEFECT_SCHEMA_VERSION,
                defect_id=_defect_id(
                    run_id=plan.run_id,
                    slug=plan.slug,
                    attempt=record.attempt,
                    layer=layer,
                    category=category,
                    resolved_fingerprint=fingerprint,
                ),
                at=record.at,
                run_id=plan.run_id,
                slug=plan.slug,
                attempt=record.attempt,
                layer=layer,
                decision=record.decision,
                reason=record.reason,
                before=record.before,
                after=record.after,
                resolved_fingerprints=[fingerprint],
                category=category,
                title=blocker.title if blocker else "",
                detail=blocker.detail if blocker else "",
                touched_files=record.touched_files,
                commands=record.commands,
                recipes=recipes,
                promotion_target=target,
                suggested_files=_SUGGESTED_FILES_BY_CATEGORY.get(category, []),
                tooling_status=_tooling_status(layer, category, record.touched_files),
                prevention_layer=rule.layer,
                prevention_phase=rule.phase,
                owner=rule.owner,
                fixture=rule.fixture,
                promotion_status=_promotion_status(category, layer, record.touched_files),
                first_seen_run_id=plan.run_id,
            )
        )
    return records


def append_factory_defects(run_dir: Path, record: AttemptRecord) -> Path | None:
    defects = _factory_defects_for_attempt(run_dir, record)
    if not defects:
        return None
    path = run_dir / "factory-defects.jsonl"
    for defect in defects:
        _append_jsonl(path, asdict(defect))
    return path


def append_attempt(run_dir: Path, record: AttemptRecord) -> Path:
    path = run_dir / "repair-attempts.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")
    append_factory_defects(run_dir, record)
    # Surface each attempt result on stdout too so an operator tailing
    # the run.log (or watching STATUS.md's upstream) sees progress in
    # real time instead of an opaque multi-minute silence while the
    # verification ladder runs.
    touched = ", ".join(record.touched_files) if record.touched_files else "none"
    summary = record.reason[:160].replace("\n", " ")
    print(
        f"[attempt {record.attempt}] {record.decision}: {summary} (touched: {touched})",
        flush=True,
    )
    return path


# ---------------------------------------------------------------------------
# Verification runner
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str], *, timeout: float | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return {
            "argv": cmd,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-2000:],
            "elapsed_s": round(time.time() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "argv": cmd,
            "returncode": 124,
            "stdout_tail": "",
            "stderr_tail": f"timed out after {timeout}s",
            "elapsed_s": round(time.time() - started, 3),
            "timed_out": True,
        }


_SAFE_ARG_RE = re.compile(r"^[a-z0-9_.:/,-]+$")


def _validate_slug(slug: str) -> None:
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,80}$", slug):
        raise ValueError(f"unsafe theme slug: {slug!r}")


def _validate_safe_args(values: list[str], *, label: str) -> None:
    for value in values:
        if not value or ".." in value or value.startswith("-") or not _SAFE_ARG_RE.match(value):
            raise ValueError(f"unsafe {label}: {value!r}")


def broker_action_to_argv(
    slug: str, action: str, payload: dict[str, Any] | None = None
) -> list[str]:
    """Translate one structured rescue action into an approved command.

    This is intentionally not a shell passthrough. Every command shape is
    enumerated here so recipes and tool-rescue can mutate the worktree only
    through known, scoped repair operations.
    """
    payload = payload or {}
    _validate_slug(slug)
    if action == "check_quick":
        return [sys.executable, str(ROOT / "bin" / "check.py"), slug, "--quick"]
    if action == "check_only":
        only = [str(item) for item in payload.get("only") or []]
        _validate_safe_args(only, label="check alias")
        return [
            sys.executable,
            str(ROOT / "bin" / "check.py"),
            slug,
            "--quick",
            "--only",
            *only,
        ]
    if action == "snap_routes":
        routes = [str(item) for item in payload.get("routes") or []]
        viewports = [str(item) for item in payload.get("viewports") or ["mobile", "desktop"]]
        _validate_safe_args(routes, label="route")
        _validate_safe_args(viewports, label="viewport")
        cmd = [
            sys.executable,
            str(ROOT / "bin" / "snap.py"),
            "shoot",
            slug,
            "--viewports",
            ",".join(viewports),
        ]
        if routes:
            cmd.extend(["--routes", ",".join(routes)])
        return cmd
    if action == "snap_report":
        return [sys.executable, str(ROOT / "bin" / "snap.py"), "report", slug]
    if action == "generate_product_photos":
        cmd = [
            sys.executable,
            str(ROOT / "bin" / "generate-product-photos.py"),
            "--theme",
            slug,
        ]
        if payload.get("force", True):
            cmd.append("--" + "force")
        return cmd
    if action == "build_screenshot":
        return [sys.executable, str(ROOT / "bin" / "build-theme-screenshots.py"), slug]
    if action == "sync_playground":
        return [sys.executable, str(ROOT / "bin" / "sync-playground.py")]
    if action == "build_index":
        return [sys.executable, str(ROOT / "bin" / "build-index.py"), slug]
    if action == "design_scorecard":
        return [
            sys.executable,
            str(ROOT / "bin" / "design-scorecard.py"),
            slug,
            "--run-id",
            str(payload.get("run_id") or os.environ.get("FIFTY_DESIGN_RUN_ID") or f"design-{slug}"),
        ]
    if action == "php_lint":
        rel = str(payload.get("path") or f"{slug}/functions.php").lstrip("./")
        if not rel.startswith(f"{slug}/") or ".." in rel or not rel.endswith(".php"):
            raise ValueError(f"unsafe php lint path: {rel!r}")
        return ["php", "-l", str(ROOT / rel)]
    raise ValueError(f"unsupported broker action: {action}")


def run_broker_action(
    slug: str,
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float | None = 30 * 60,
) -> dict[str, Any]:
    argv = broker_action_to_argv(slug, action, payload)
    result = _run_cmd(argv, timeout=timeout)
    result["action"] = action
    result["payload"] = payload or {}
    return result


def _actions_for_recipe(slug: str, recipe: str, run_id: str) -> list[tuple[str, dict[str, Any]]]:
    if recipe == "php_syntax":
        return [("php_lint", {"path": f"{slug}/functions.php"}), ("check_quick", {})]
    if recipe == "generate_product_photos":
        return [("generate_product_photos", {"force": True}), ("check_quick", {})]
    if recipe == "generate_theme_images":
        generator = ROOT / slug / "playground" / "generate-images.py"
        if generator.is_file():
            # This legacy per-theme script is intentionally not exposed as a
            # general broker command; recipes may invoke it through the
            # normal Python runner shape when it exists.
            return []
        return [("generate_product_photos", {"force": True}), ("check_quick", {})]
    if recipe == "build_screenshot":
        return [
            ("snap_routes", {"routes": ["home"], "viewports": ["desktop"]}),
            ("build_screenshot", {}),
            ("check_quick", {}),
        ]
    if recipe == "snap_routes":
        return [("snap_routes", {}), ("snap_report", {}), ("check_quick", {})]
    if recipe == "design_scorecard":
        return [("design_scorecard", {"run_id": run_id})]
    if recipe == "sync_playground":
        return [("sync_playground", {}), ("check_quick", {})]
    if recipe == "build_index":
        return [("build_index", {}), ("check_quick", {})]
    return []


def apply_recipes(
    run_dir: Path,
    *,
    max_attempts: int = 6,
    max_non_improving: int = 3,
) -> AttemptRecord:
    plan = build_repair_plan(run_dir)
    existing_attempts = _read_attempt_count(run_dir)
    attempt_number = existing_attempts + 1
    if (
        attempt_number > max_attempts
        or _non_improving_streak(run_dir, layer="recipe") >= max_non_improving
    ):
        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision="stopped",
            reason="Recipe repair cap reached before running deterministic recipes.",
            before=[b.fingerprint for b in plan.blockers],
            after=[b.fingerprint for b in plan.blockers],
            touched_files=[],
            commands=[],
            verification={"layer": "recipe"},
            notes=["recipe layer stopped on cap"],
        )
        append_attempt(run_dir, record)
        return record

    before = [b.fingerprint for b in plan.blockers]
    changed_before = set(_changed_files(ROOT))
    results: list[dict[str, Any]] = []
    commands_run: list[list[str]] = []
    notes: list[str] = []

    if not plan.recommended_recipes:
        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision="stopped",
            reason="No deterministic recipe can change source for these blockers.",
            before=before,
            after=before,
            touched_files=[],
            commands=[],
            verification={"layer": "recipe", "recipes": [], "human_boundary": "no-op-repair"},
            notes=["recipe layer stopped before no-op verification or re-shoot"],
        )
        append_attempt(run_dir, record)
        return record

    for recipe in plan.recommended_recipes:
        actions = _actions_for_recipe(plan.slug, recipe, plan.run_id)
        if not actions:
            notes.append(f"recipe {recipe} had no brokered actions")
            continue
        for action, payload in actions:
            result = run_broker_action(plan.slug, action, payload)
            results.append(result)
            commands_run.append([str(part) for part in result.get("argv", [])])
            if int(result.get("returncode", 0) or 0) not in (0, 1):
                notes.append(
                    f"recipe {recipe} stopped after {action} rc={result.get('returncode')}"
                )
                break

    categories = [b.category for b in plan.blockers]
    changed_after_recipes = set(_changed_files(ROOT))
    touched_by_recipes = sorted(
        path
        for path in (changed_after_recipes - changed_before)
        if path.startswith(f"{plan.slug}/")
    )
    if not touched_by_recipes and any(
        recipe in {"snap_routes", "design_scorecard"} for recipe in plan.recommended_recipes
    ):
        notes.append("no source files changed before visual verification; skipped re-shoot")
    else:
        for cmd in plan.verification_ladder:
            result = _run_cmd(cmd, timeout=30 * 60)
            results.append(result | {"action": "verification", "payload": {}})
            commands_run.append(cmd)
            if result["returncode"] not in (0, 1):
                break

    after = _collect_fingerprints(plan.slug, categories)
    verification_failed = any(int(result.get("returncode", 0) or 0) != 0 for result in results)
    decision, reason = _judge_progress(
        before,
        after,
        slug=plan.slug,
        snap_errors_before=_snap_error_count(plan.slug),
        verification_failed=verification_failed,
    )
    changed_after = set(_changed_files(ROOT))
    touched = sorted(
        path for path in (changed_after - changed_before) if path.startswith(f"{plan.slug}/")
    )
    record = AttemptRecord(
        at=time.time(),
        attempt=attempt_number,
        decision=decision,
        reason=reason,
        before=before,
        after=after,
        touched_files=touched,
        commands=commands_run,
        verification={
            "layer": "recipe",
            "recipes": plan.recommended_recipes,
            "results": results,
        },
        notes=notes,
    )
    append_attempt(run_dir, record)
    return record


def _collect_fingerprints(slug: str, categories: list[str]) -> list[str]:
    """Re-read summary-style evidence and emit the current fingerprints.

    This re-runs `bin/check.py <slug> --quick --only <per-category>`
    to refresh the static signal and re-reads `tmp/snaps/<slug>/review.json`
    for snap error cells.  It does NOT re-shoot; the caller decides
    whether to run the verification ladder first.
    """
    fps: list[str] = []
    seen: set[str] = set()
    for cat in sorted(set(categories)):
        only = _CHECK_ONLY_BY_CATEGORY.get(cat)
        if cat == "unknown":
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "check.py"),
                    slug,
                    "--quick",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                continue
            failures = _parse_check_failures(proc.stdout)
            for title, detail in failures:
                fp = blocker_fingerprint(_classify(title, detail), slug, detail)
                if fp in seen:
                    continue
                seen.add(fp)
                fps.append(fp)
            continue
        if cat == "design-score-low":
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "design-scorecard.py"),
                    slug,
                    "--run-id",
                    os.environ.get("FIFTY_DESIGN_RUN_ID") or f"design-{slug}",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                continue
            failures = _parse_check_failures(proc.stdout)
            for title, detail in failures:
                fp = blocker_fingerprint(_classify(title, detail), slug, detail)
                if fp in seen:
                    continue
                seen.add(fp)
                fps.append(fp)
            continue
        if not only:
            continue
        proc = subprocess.run(
            _check_cmd(slug, only),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            continue
        # Re-parse the check output for FAIL lines — cheap, no JSON to
        # maintain.  The output shape:
        #   [FAIL] [<theme>] <title>
        #            <indented detail>
        # so we capture title+detail pairs.
        failures = _parse_check_failures(proc.stdout)
        for title, detail in failures:
            fp = blocker_fingerprint(_classify(title, detail), slug, detail)
            if fp in seen:
                continue
            seen.add(fp)
            fps.append(fp)
    return fps


_FAIL_LINE = re.compile(r"^\s*\[FAIL\]\s+\[[^\]]+\]\s+(.+?)\s*$")


def _parse_check_failures(stdout: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    lines = stdout.splitlines()
    i = 0
    while i < len(lines):
        m = _FAIL_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        title = m.group(1)
        detail_lines: list[str] = []
        j = i + 1
        while j < len(lines) and lines[j].startswith("         "):
            detail_lines.append(lines[j].strip())
            j += 1
        out.append((title, " ".join(detail_lines)))
        i = j
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build a repair packet for a blocked bin/design.py run and, "
            "optionally, run its verification ladder after the LLM has "
            "edited toward green."
        )
    )
    p.add_argument(
        "--run-id",
        required=True,
        help="Run identifier whose tmp/runs/<run-id>/summary.json should be parsed.",
    )
    p.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Override tmp/runs/<run-id> (useful for tests).",
    )
    p.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Stdout format for the repair plan (default: text).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Run the verification ladder against the current worktree "
            "state and append an attempt record. Use after an LLM has "
            "edited files; this command itself does not edit anything."
        ),
    )
    p.add_argument(
        "--recipes",
        action="store_true",
        help=(
            "Run deterministic repair recipes named by the repair plan, "
            "then verify and append a recipe-layer attempt record."
        ),
    )
    p.add_argument(
        "--attempt-number",
        type=int,
        default=None,
        help="Override attempt number (defaults to existing-attempts+1).",
    )
    p.add_argument(
        "--touched-files",
        nargs="*",
        default=None,
        help="Files the LLM edited in the attempt (for the attempt record).",
    )
    p.add_argument(
        "--before-fingerprints",
        nargs="*",
        default=None,
        help=(
            "Fingerprints from the previous attempt, for progress judging. "
            "Default: the fingerprints computed from summary.json."
        ),
    )
    p.add_argument(
        "--note",
        default=None,
        help="Freeform note appended to the attempt record (for humans).",
    )
    p.add_argument(
        "--max-attempts",
        type=int,
        default=6,
        help="Hard cap on repair attempts before --apply refuses (default 6).",
    )
    p.add_argument(
        "--max-non-improving",
        type=int,
        default=3,
        help="Non-improving-attempt cap before --apply refuses (default 3).",
    )
    p.add_argument(
        "--agentic",
        action="store_true",
        help=(
            "Drive a bounded LLM repair loop: the LLM sees the repair packet, "
            "returns JSON edits that get applied in-place, and the "
            "verification ladder runs after each round. Requires "
            "ANTHROPIC_API_KEY; without it the packet is emitted and the "
            "run stops (exit 5). Implies --apply."
        ),
    )
    p.add_argument(
        "--agentic-dry-run",
        action="store_true",
        help=(
            "Emit the repair packet and stop without calling the LLM. "
            "Useful for previewing what would be sent."
        ),
    )
    p.add_argument(
        "--tool-rescue",
        action="store_true",
        help=(
            "Run a bounded tool-rescue loop. The model may request exact "
            "edits and structured broker actions, but never raw shell."
        ),
    )
    p.add_argument(
        "--tool-rescue-dry-run",
        action="store_true",
        help="Emit the tool-rescue packet and stop without calling the model.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override the Anthropic model for --agentic (default: FIFTY_UNBLOCK_MODEL or claude-sonnet-4-6).",
    )
    return p


def _resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir is not None:
        return args.run_dir
    return ROOT / "tmp" / "runs" / args.run_id


def _print_plan_text(plan: RepairPlan) -> None:
    print(f"# Repair plan: {plan.slug} (run {plan.run_id})")
    print(f"worktree_root: {plan.worktree_root}")
    print(f"worktree_clean: {plan.worktree_clean}")
    if plan.allowed_commands:
        print(f"allowed_commands: {', '.join(plan.allowed_commands)}")
    if plan.recommended_recipes:
        print(f"recommended_recipes: {', '.join(plan.recommended_recipes)}")
    if plan.human_boundary:
        print(f"human_boundary: {plan.human_boundary}")
    if plan.worktree_unrelated_files:
        print("unrelated_framework_files:")
        for p in plan.worktree_unrelated_files:
            print(f"  - {p}")
    print(f"resume_phase: {plan.resume_phase}")
    print(f"blockers: {len(plan.blockers)}")
    for i, b in enumerate(plan.blockers, 1):
        print()
        print(f"[{i}] {b.category}  fp={b.fingerprint}")
        print(f"    title:  {b.title}")
        if b.summary:
            print(f"    human:  {b.summary}")
        if b.next_action:
            print(f"    action: {b.next_action}")
        for f in b.affected_files:
            print(f"    file:   {f}")
        for recipe in b.recommended_recipes:
            print(f"    recipe: {recipe}")
        if b.affected_routes:
            print(f"    routes: {', '.join(b.affected_routes)}")
        if b.affected_viewports:
            print(f"    viewports: {', '.join(b.affected_viewports)}")
        for sf in b.snap_findings[:3]:
            print(f"    snap:   {sf.viewport}/{sf.route} [{sf.kind}] {sf.message[:120]}")
            if sf.crop_path:
                print(f"           crop: {sf.crop_path}")
        if b.verification:
            print("    verify:")
            for cmd in b.verification:
                print(f"      $ {' '.join(cmd)}")
        for note in b.notes:
            print(f"    note:   {note}")
    print()
    if plan.verification_ladder:
        print("full verification ladder:")
        for cmd in plan.verification_ladder:
            print(f"  $ {' '.join(cmd)}")


def _read_attempt_count(run_dir: Path) -> int:
    path = run_dir / "repair-attempts.jsonl"
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _non_improving_streak(run_dir: Path, *, layer: str | None = None) -> int:
    path = run_dir / "repair-attempts.jsonl"
    if not path.is_file():
        return 0
    streak = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if layer is not None:
            verification = rec.get("verification") or {}
            if not isinstance(verification, dict) or verification.get("layer") != layer:
                continue
        if rec.get("decision") == "improved" or rec.get("decision") == "fixed":
            streak = 0
        else:
            streak += 1
    return streak


def _snap_error_count(slug: str) -> int:
    review = _snap_review(slug)
    try:
        return int(review.get("errors", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _judge_progress(
    before: list[str],
    after: list[str],
    *,
    slug: str | None = None,
    snap_errors_before: int | None = None,
    verification_failed: bool = False,
) -> tuple[str, str]:
    before_set = set(before)
    after_set = set(after)
    snap_after = _snap_error_count(slug) if slug else 0
    if verification_failed and not after_set:
        return (
            "not-improved",
            "Verification failed, but no blocker fingerprints could be parsed; "
            "treating the blocker set as unchanged.",
        )
    if not after_set and (snap_errors_before is None or snap_after <= snap_errors_before):
        return "fixed", "No blockers remain."
    gained = after_set - before_set
    if gained:
        return (
            "worse",
            f"Repair introduced {len(gained)} new blocker(s) not present before.",
        )
    if snap_errors_before is not None and snap_after > snap_errors_before:
        return (
            "worse",
            f"Snap error cell count rose from {snap_errors_before} to {snap_after}.",
        )
    if after_set == before_set:
        return "not-improved", "Blocker set unchanged after repair attempt."
    cleared = before_set - after_set
    return (
        "improved",
        f"{len(cleared)} blocker(s) cleared, {len(after_set)} remaining.",
    )


def apply_verification(
    run_dir: Path,
    *,
    attempt_number: int | None = None,
    touched_files: list[str] | None = None,
    before_fingerprints: list[str] | None = None,
    note: str | None = None,
    max_attempts: int = 6,
    max_non_improving: int = 3,
) -> AttemptRecord:
    plan = build_repair_plan(run_dir)
    existing_attempts = _read_attempt_count(run_dir)
    if attempt_number is None:
        attempt_number = existing_attempts + 1

    if attempt_number > max_attempts:
        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision="stopped",
            reason=f"Exceeded max-attempts={max_attempts}; escalating.",
            before=before_fingerprints or [b.fingerprint for b in plan.blockers],
            after=[b.fingerprint for b in plan.blockers],
            touched_files=touched_files or [],
            commands=[],
            verification={},
            notes=[note] if note else [],
        )
        append_attempt(run_dir, record)
        return record

    if _non_improving_streak(run_dir) >= max_non_improving:
        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision="stopped",
            reason=(
                f"Non-improving streak reached {max_non_improving}; escalating rather than looping."
            ),
            before=before_fingerprints or [b.fingerprint for b in plan.blockers],
            after=[b.fingerprint for b in plan.blockers],
            touched_files=touched_files or [],
            commands=[],
            verification={},
            notes=[note] if note else [],
        )
        append_attempt(run_dir, record)
        return record

    before = (
        list(before_fingerprints)
        if before_fingerprints is not None
        else [b.fingerprint for b in plan.blockers]
    )
    snap_errors_before = _snap_error_count(plan.slug)

    commands_run: list[list[str]] = []
    verification_log: dict[str, Any] = {
        "ladder": [],
        "snap_errors_before": snap_errors_before,
    }
    for cmd in plan.verification_ladder:
        result = _run_cmd(cmd, timeout=30 * 60)
        commands_run.append(cmd)
        verification_log["ladder"].append(result)
        # If a cheap static check fails catastrophically (non-1 exit),
        # bail early — snap shoots are expensive.
        if result["returncode"] not in (0, 1):
            verification_log["aborted"] = True
            break

    categories = [b.category for b in plan.blockers]
    after = _collect_fingerprints(plan.slug, categories)
    verification_log["snap_errors_after"] = _snap_error_count(plan.slug)
    verification_failed = any(
        int(result.get("returncode", 0) or 0) != 0 for result in verification_log["ladder"]
    )

    decision, reason = _judge_progress(
        before,
        after,
        slug=plan.slug,
        snap_errors_before=snap_errors_before,
        verification_failed=verification_failed,
    )
    record = AttemptRecord(
        at=time.time(),
        attempt=attempt_number,
        decision=decision,
        reason=reason,
        before=before,
        after=after,
        touched_files=touched_files or [],
        commands=commands_run,
        verification=verification_log,
        notes=[note] if note else [],
    )
    append_attempt(run_dir, record)
    return record


# ---------------------------------------------------------------------------
# Agentic repair loop (LLM edits the tree toward green, bounded)
# ---------------------------------------------------------------------------


# Paths the LLM is allowed to edit. Anything else is rejected so a bad
# suggestion cannot, for example, overwrite `bin/check.py` or grow an
# allowlist. `<slug>` is substituted per run.
_EDIT_ALLOW_PREFIXES = ("{slug}/",)

# Hard-forbidden substrings that would bypass the gates (no allowlist
# growth, no `!important`, no `--no-verify`, etc.).
_EDIT_FORBIDDEN_SUBSTRINGS = (
    "!important",
    "--no-verify",
    "tests/check-baseline-failures.json",
    "tests/visual-baseline/heuristics-allowlist.json",
)


def _edit_is_allowed(path: str, slug: str) -> tuple[bool, str]:
    rel = path.lstrip("./")
    allowed = tuple(p.replace("{slug}", slug) for p in _EDIT_ALLOW_PREFIXES)
    if not any(rel.startswith(prefix) for prefix in allowed):
        return False, (
            f"path {rel!r} is outside the editable set (allowed prefixes: "
            + ", ".join(allowed)
            + ")"
        )
    for forbidden in _EDIT_FORBIDDEN_SUBSTRINGS:
        if forbidden in rel:
            return False, f"path {rel!r} is forbidden ({forbidden})"
    return True, ""


def _content_is_allowed(new_string: str) -> tuple[bool, str]:
    for forbidden in _EDIT_FORBIDDEN_SUBSTRINGS:
        if forbidden in new_string:
            return False, f"new content contains forbidden substring {forbidden!r}"
    return True, ""


def _apply_edit(path: Path, old: str, new: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"file does not exist: {path}"
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, f"file is not utf-8: {path}"
    if old not in data:
        return False, f"old_string not found in {path}"
    if data.count(old) > 1:
        return False, f"old_string matches {data.count(old)} times in {path}; ambiguous"
    new_data = data.replace(old, new, 1)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_data, encoding="utf-8")
    tmp.replace(path)
    return True, ""


def _file_snippet(path: Path, *, max_bytes: int = 6000) -> str:
    if not path.is_file():
        return f"(missing: {path})"
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"(binary: {path})"
    if len(data) > max_bytes:
        return data[:max_bytes] + f"\n... [truncated; {len(data) - max_bytes} more bytes]"
    return data


def _build_repair_prompt(plan: RepairPlan, prior_attempts: list[dict[str, Any]]) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for a repair round."""
    system = (
        "You are a careful WordPress block-theme engineer. Your ONLY job is "
        "to produce minimal, surgical edits that clear specific named "
        "blockers in a single theme inside a monorepo. You do not speculate, "
        "you do not refactor unrelated code, and you never bypass gates.\n"
        "\n"
        "Hard rules:\n"
        "1. Only edit files under `<slug>/` (the theme directory).\n"
        "2. Never add `!important`, never modify anything under `tests/` or "
        "`bin/`, never touch allowlist files.\n"
        "3. Prefer the smallest possible string replacement. Each edit must "
        "be an exact, unique `old_string` that appears once in the file.\n"
        "4. This repo intentionally has no theme CSS files such as "
        "`<slug>/styles.css` or `<slug>/assets/css/*.css`. Theme CSS lives in "
        "`<slug>/theme.json` under `styles.css` or block `css` entries.\n"
        "5. If you cannot safely fix a blocker from the evidence provided, "
        "set `done: true` with `rationale` explaining what a human should do "
        "and leave `edits` empty.\n"
        "\n"
        "Respond with EXACTLY ONE JSON object. Do NOT write any prose, "
        "explanation, or markdown before or after the JSON. Do NOT wrap "
        "the JSON in a code fence. Put all reasoning inside the "
        "`rationale` field. Your response MUST start with `{` and end "
        "with `}`.\n"
        "{\n"
        '  "rationale": "<short explanation of the diagnosis>",\n'
        '  "done": false,\n'
        '  "edits": [\n'
        '    {"path": "<slug>/<file>", "old_string": "...", "new_string": "..."}\n'
        "  ]\n"
        "}\n"
        "\n"
        "Set `done: true` only when you believe the current edits (plus any "
        "previously-applied edits) fully clear every blocker."
    )

    blockers_text: list[str] = []
    for b in plan.blockers:
        blockers_text.append(
            f"- [{b.category}] {b.title}\n"
            f"    detail: {b.detail[:800]}\n"
            f"    next_action: {b.next_action}\n"
            f"    fingerprint: {b.fingerprint}"
        )

    file_sections: list[str] = []
    seen_files: set[str] = set()
    for b in plan.blockers:
        for snippet in b.source_snippets:
            if snippet in seen_files:
                continue
            seen_files.add(snippet)
            file_sections.append(snippet)
        for rel in b.affected_files:
            if rel in seen_files:
                continue
            seen_files.add(rel)
            # Skip snap HTML dumps in the prompt; they are huge and
            # rarely actionable as source.
            if rel.startswith("tmp/snaps/"):
                continue
            if rel.startswith("bin/"):
                continue
            path = ROOT / rel
            file_sections.append(f"### {rel}\n```\n{_file_snippet(path)}\n```")

    prior_text = ""
    if prior_attempts:
        prior_text = "\n## Prior attempts\n"
        for rec in prior_attempts[-3:]:
            verification_raw = rec.get("verification")
            verification: dict[str, Any] = (
                verification_raw if isinstance(verification_raw, dict) else {}
            )
            rejected = list(rec.get("rejected_edits") or verification.get("rejected_edits") or [])
            notes = list(rec.get("notes") or [])
            rejected_text = ""
            if rejected or notes:
                rejected_text = f"; rejected: {', '.join([*rejected, *notes])[:700]}"
            prior_text += (
                f"- attempt {rec.get('attempt')}: {rec.get('decision')} "
                f"({rec.get('reason', '')}); files: "
                f"{', '.join(rec.get('touched_files', []))}"
                f"{rejected_text}\n"
            )

    user = (
        f"# Repair packet for theme `{plan.slug}`\n"
        f"Worktree: {plan.worktree_root}\n"
        f"Resume phase after repair: {plan.resume_phase}\n"
        f"\n"
        f"## Blockers ({len(plan.blockers)})\n"
        + "\n".join(blockers_text)
        + prior_text
        + "\n\n## Relevant source files\n"
        + "\n\n".join(file_sections)
        + "\n\nReturn the JSON object now."
    )
    return system, user


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(raw_text: str) -> str:
    """Pull the largest balanced JSON object out of the model response.

    The system prompt asks for JSON-only, but models routinely add
    prose before/after or wrap the payload in a ```json fence. We try
    three fallbacks in order:
      1. A fenced ```json ... ``` block anywhere in the text.
      2. The substring between the first `{` and its matching `}`.
      3. The full text (may be already-clean JSON).
    """
    text = raw_text.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1)
    # Find first `{` and scan forward counting braces inside strings.
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text


def _parse_llm_edits(raw_text: str) -> dict[str, Any]:
    """Parse the model response; tolerate markdown fencing and prose."""
    candidate = _extract_json_object(raw_text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("model response must be a JSON object")
    data.setdefault("edits", [])
    data.setdefault("rationale", "")
    data.setdefault("done", False)
    if not isinstance(data["edits"], list):
        raise ValueError("`edits` must be a list")
    return data


def _parse_tool_rescue_response(raw_text: str) -> dict[str, Any]:
    data = _parse_llm_edits(raw_text)
    data.setdefault("actions", [])
    data.setdefault("human_boundary", None)
    if not isinstance(data["actions"], list):
        raise ValueError("`actions` must be a list")
    if data["human_boundary"] is not None and not isinstance(data["human_boundary"], str):
        raise ValueError("`human_boundary` must be null or a string")
    return data


def _human_boundary_from_exception(exc: Exception) -> str | None:
    status = getattr(exc, "status", None)
    if status == 429:
        return "external-rate-limit"
    text = str(exc)
    if "Too Many Requests" in text or "HTTPError 429" in text:
        return "external-rate-limit"
    if "ApiKeyMissingError" in text or "ANTHROPIC_API_KEY" in text:
        return "missing-api-key"
    return None


def _exception_boundary_metadata(exc: Exception) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    retry_after = getattr(exc, "retry_after_seconds", None)
    if retry_after is not None:
        metadata["retry_after_seconds"] = retry_after
    rate_headers = getattr(exc, "rate_limit_headers", None)
    if isinstance(rate_headers, dict) and rate_headers:
        metadata["rate_limit_headers"] = rate_headers
    return metadata


def _apply_llm_edits(
    slug: str,
    edits: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return (applied_files, rejected_reasons)."""
    applied: list[str] = []
    rejected: list[str] = []
    for edit in edits:
        path_str = str(edit.get("path") or "").strip()
        old = edit.get("old_string")
        new = edit.get("new_string")
        if not path_str or not isinstance(old, str) or not isinstance(new, str):
            rejected.append(f"malformed edit: {edit}")
            continue
        ok, reason = _edit_is_allowed(path_str, slug)
        if not ok:
            rejected.append(reason)
            continue
        ok, reason = _content_is_allowed(new)
        if not ok:
            rejected.append(reason)
            continue
        path = ROOT / path_str
        ok, reason = _apply_edit(path, old, new)
        if not ok:
            rejected.append(f"{path_str}: {reason}")
            continue
        if path_str not in applied:
            applied.append(path_str)
    return applied, rejected


def _run_rescue_actions(
    slug: str,
    allowed: list[str],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    rejected: list[str] = []
    allowed_set = set(allowed)
    for action in actions:
        name = str(action.get("action") or "")
        payload = action.get("payload") or {}
        if name not in allowed_set:
            rejected.append(f"action {name!r} is not allowed")
            continue
        if not isinstance(payload, dict):
            rejected.append(f"action {name!r} payload must be an object")
            continue
        try:
            results.append(run_broker_action(slug, name, payload))
        except ValueError as exc:
            rejected.append(str(exc))
    return results, rejected


def _build_tool_rescue_prompt(
    plan: RepairPlan, prior_attempts: list[dict[str, Any]]
) -> tuple[str, str]:
    system = (
        "You are a bounded tool-using rescue agent for a WordPress block theme "
        "factory. You may propose exact file edits and structured broker "
        "actions, but you may not run raw shell commands. Work only inside the "
        "active theme and generated per-theme artifacts. For `factory-timeout` "
        "or `factory-stall` blockers, your first job is diagnosis: inspect the "
        "provided STATUS.md / summary.json / events.jsonl evidence, explain the "
        "most likely stuck phase, and request only safe broker actions. Do not "
        "edit framework files from this rescue loop; if a framework change is "
        "needed, set `human_boundary` to `factory-tooling-change` with a clear "
        "rationale. Never edit allowlists, never use destructive git operations, "
        "and never bypass checks. This repo intentionally has no theme CSS files "
        "such as `<slug>/styles.css` or `<slug>/assets/css/*.css`; theme CSS lives "
        "in `<slug>/theme.json` under `styles.css` or block `css` entries.\n\n"
        "Respond with exactly one JSON object:\n"
        "{\n"
        '  "rationale": "<diagnosis>",\n'
        '  "done": false,\n'
        '  "human_boundary": null,\n'
        '  "actions": [{"action": "check_quick", "payload": {}}],\n'
        '  "edits": [{"path": "<slug>/<file>", "old_string": "...", "new_string": "..."}]\n'
        "}\n"
        "Use `human_boundary` only for credentials, budget cap, destructive "
        "approval, external outage, or genuinely ambiguous design judgment."
    )
    blockers_text: list[str] = []
    snippets: list[str] = []
    seen: set[str] = set()
    for b in plan.blockers:
        blockers_text.append(
            f"- [{b.category}] {b.title}\n"
            f"    detail: {b.detail[:1000]}\n"
            f"    next_action: {b.next_action}\n"
            f"    recipes: {', '.join(b.recommended_recipes) or 'none'}\n"
            f"    fingerprint: {b.fingerprint}"
        )
        for snippet in b.source_snippets:
            if snippet not in seen:
                seen.add(snippet)
                snippets.append(snippet)
        for rel in b.affected_files:
            if rel in seen or rel.startswith("tmp/snaps/") or rel.startswith("bin/"):
                continue
            seen.add(rel)
            snippets.append(f"### {rel}\n```\n{_file_snippet(ROOT / rel)}\n```")
    prior_text = ""
    if prior_attempts:
        prior_text = "\n## Prior attempts\n"
        for rec in prior_attempts[-5:]:
            verification_raw = rec.get("verification")
            verification: dict[str, Any] = (
                verification_raw if isinstance(verification_raw, dict) else {}
            )
            rejected = list(rec.get("rejected_edits") or verification.get("rejected_edits") or [])
            notes = list(rec.get("notes") or [])
            rejected_text = ""
            if rejected or notes:
                rejected_text = f"; rejected: {', '.join([*rejected, *notes])[:900]}"
            prior_text += (
                f"- attempt {rec.get('attempt')}: {rec.get('decision')} "
                f"({rec.get('reason', '')}); files: "
                f"{', '.join(rec.get('touched_files', []))}"
                f"{rejected_text}\n"
            )
    user = (
        f"# Tool rescue packet for `{plan.slug}`\n"
        f"Worktree: {plan.worktree_root}\n"
        f"Resume phase: {plan.resume_phase}\n"
        f"Allowed broker actions: {', '.join(plan.allowed_commands)}\n"
        f"Recommended recipes: {', '.join(plan.recommended_recipes) or 'none'}\n"
        f"\n## Blockers\n"
        + "\n".join(blockers_text)
        + prior_text
        + "\n\n## Source snippets\n"
        + "\n\n".join(snippets)
        + "\n\nReturn JSON now."
    )
    return system, user


def _read_attempts_jsonl(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "repair-attempts.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def agentic_repair(
    run_dir: Path,
    *,
    max_attempts: int = 6,
    max_non_improving: int = 3,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    """Drive an LLM-powered repair loop against a blocked run.

    Returns the process exit code:
    * 0 — every blocker cleared (`fixed`).
    * 0 — some blockers cleared (`improved`), caller should resume.
    * 3 — repair made things worse.
    * 4 — non-improving streak or attempt cap tripped; human needed.
    * 5 — API key missing or repair was a dry-run; packet emitted only.
    * 2 — worktree is dirty with unrelated framework changes.
    """
    # Resolve the LLM helper lazily so `design_unblock.py` can run in
    # contexts without the vision lib available (tests, dry triage).
    try:
        from _vision_lib import (
            ApiKeyMissingError,
            text_completion,
        )
    except Exception:
        print("refusing to --agentic: bin/_vision_lib.py is unavailable", file=sys.stderr)
        return 5

    plan = build_repair_plan(run_dir)
    if not plan.worktree_clean:
        print(
            "refusing to --agentic: worktree has unrelated framework changes:",
            file=sys.stderr,
        )
        for p in plan.worktree_unrelated_files:
            print(f"  - {p}", file=sys.stderr)
        return 2

    if not plan.blockers:
        print("no blockers to repair", file=sys.stderr)
        return 0

    attempt_history = _read_attempts_jsonl(run_dir)
    attempt_number = len(attempt_history)
    while attempt_number < max_attempts:
        attempt_number += 1

        # Check non-improving streak before each attempt.
        if _non_improving_streak(run_dir, layer="json-llm") >= max_non_improving:
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason=(
                    f"Non-improving streak reached {max_non_improving}; "
                    "escalating rather than looping."
                ),
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={"layer": "json-llm", "human_boundary": "non-improving-streak"},
                notes=["agentic repair stopped on non-improving streak"],
            )
            append_attempt(run_dir, record)
            return 4

        system, user = _build_repair_prompt(plan, attempt_history)

        if dry_run or not os.environ.get("ANTHROPIC_API_KEY"):
            # Emit the packet so a human (or external agent) can act.
            print("---- REPAIR PACKET (dry-run) ----", flush=True)
            print(user, flush=True)
            print("---- END PACKET ----", flush=True)
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason=("Dry-run or ANTHROPIC_API_KEY missing; packet emitted for human handoff."),
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={"layer": "json-llm", "human_boundary": "missing-api-key"},
                notes=["dry-run agentic repair; no edits applied"],
            )
            append_attempt(run_dir, record)
            return 5

        try:
            resp = text_completion(
                system_prompt=system,
                user_prompt=user,
                model=model or os.environ.get("FIFTY_UNBLOCK_MODEL") or "claude-sonnet-4-6",
                label="design-unblock",
                max_output_tokens=8000,
            )
        except ApiKeyMissingError as exc:
            print(f"refusing to --agentic: {exc}", file=sys.stderr)
            return 5
        except Exception as exc:
            # A transient API failure is a stop; the operator should retry.
            boundary = _human_boundary_from_exception(exc)
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason=f"LLM call failed: {exc!s}",
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={
                    "layer": "json-llm",
                    **({"human_boundary": boundary} if boundary else {}),
                    **_exception_boundary_metadata(exc),
                },
                notes=[repr(exc)],
            )
            append_attempt(run_dir, record)
            return 4

        before = [b.fingerprint for b in plan.blockers]
        try:
            parsed = _parse_llm_edits(resp.raw_text)
        except ValueError as exc:
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="not-improved",
                reason=f"LLM response parse failure: {exc!s}",
                before=before,
                after=before,
                touched_files=[],
                commands=[],
                verification={"layer": "json-llm", "raw_tail": resp.raw_text[:2000]},
                notes=["LLM returned malformed JSON"],
            )
            append_attempt(run_dir, record)
            attempt_history.append(asdict(record))
            continue

        applied, rejected = _apply_llm_edits(plan.slug, parsed.get("edits", []))

        # Verify.
        snap_errors_before = _snap_error_count(plan.slug)
        commands_run: list[list[str]] = []
        verification_log: dict[str, Any] = {
            "layer": "json-llm",
            "ladder": [],
            "llm_rationale": parsed.get("rationale", "")[:800],
            "llm_done": bool(parsed.get("done")),
            "rejected_edits": rejected,
            "snap_errors_before": snap_errors_before,
        }
        for cmd in plan.verification_ladder:
            result = _run_cmd(cmd, timeout=30 * 60)
            commands_run.append(cmd)
            verification_log["ladder"].append(result)
            if result["returncode"] not in (0, 1):
                verification_log["aborted"] = True
                break

        categories = [b.category for b in plan.blockers]
        after = _collect_fingerprints(plan.slug, categories)
        verification_log["snap_errors_after"] = _snap_error_count(plan.slug)
        verification_failed = any(
            int(result.get("returncode", 0) or 0) != 0 for result in verification_log["ladder"]
        )
        decision, reason = _judge_progress(
            before,
            after,
            slug=plan.slug,
            snap_errors_before=snap_errors_before,
            verification_failed=verification_failed,
        )

        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision=decision,
            reason=reason,
            before=before,
            after=after,
            touched_files=applied,
            commands=commands_run,
            verification=verification_log,
            notes=(["edits rejected: " + "; ".join(rejected)] if rejected else []),
        )
        append_attempt(run_dir, record)
        attempt_history.append(asdict(record))

        print(
            f"attempt {attempt_number}: {decision} — {reason}; "
            f"applied={len(applied)} rejected={len(rejected)}",
            flush=True,
        )

        if decision == "fixed":
            return 0
        if decision == "improved":
            # Recompute the plan from the current blocker set so the
            # next prompt reflects the reduced surface.
            plan = build_repair_plan(run_dir)
            if not plan.blockers:
                return 0
            continue
        if decision == "worse":
            return 3
        # not-improved: keep iterating until cap / streak.

    # Hit the attempt cap without success.
    record = AttemptRecord(
        at=time.time(),
        attempt=attempt_number,
        decision="stopped",
        reason=f"Exceeded max-attempts={max_attempts}; escalating.",
        before=[b.fingerprint for b in plan.blockers],
        after=[b.fingerprint for b in plan.blockers],
        touched_files=[],
        commands=[],
        verification={"layer": "json-llm", "human_boundary": "attempt-cap"},
        notes=["agentic repair stopped on attempt cap"],
    )
    append_attempt(run_dir, record)
    return 4


def tool_rescue(
    run_dir: Path,
    *,
    max_attempts: int = 3,
    max_non_improving: int = 2,
    dry_run: bool = False,
    model: str | None = None,
) -> int:
    try:
        from _vision_lib import (
            ApiKeyMissingError,
            text_completion,
        )
    except Exception:
        print("refusing to --tool-rescue: bin/_vision_lib.py is unavailable", file=sys.stderr)
        return 5

    plan = build_repair_plan(run_dir)
    if not plan.worktree_clean:
        print(
            "refusing to --tool-rescue: worktree has unrelated framework changes:",
            file=sys.stderr,
        )
        for p in plan.worktree_unrelated_files:
            print(f"  - {p}", file=sys.stderr)
        return 2
    if not plan.blockers:
        print("no blockers to rescue", file=sys.stderr)
        return 0

    attempt_history = _read_attempts_jsonl(run_dir)
    attempt_number = len(attempt_history)
    while attempt_number < max_attempts:
        attempt_number += 1
        if _non_improving_streak(run_dir, layer="tool-rescue") >= max_non_improving:
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason=(
                    f"Tool rescue non-improving streak reached {max_non_improving}; "
                    "escalating with typed boundary."
                ),
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={"layer": "tool-rescue", "human_boundary": "non-improving-streak"},
                notes=["tool rescue stopped on non-improving streak"],
            )
            append_attempt(run_dir, record)
            return 4

        system, user = _build_tool_rescue_prompt(plan, attempt_history)
        if dry_run or not os.environ.get("ANTHROPIC_API_KEY"):
            print("---- TOOL RESCUE PACKET (dry-run) ----", flush=True)
            print(user, flush=True)
            print("---- END PACKET ----", flush=True)
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason="Dry-run or ANTHROPIC_API_KEY missing; tool-rescue packet emitted.",
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={"layer": "tool-rescue", "human_boundary": "missing-api-key"},
                notes=["tool rescue dry-run; no edits or actions applied"],
            )
            append_attempt(run_dir, record)
            return 5

        try:
            resp = text_completion(
                system_prompt=system,
                user_prompt=user,
                model=model
                or os.environ.get("FIFTY_RESCUE_MODEL")
                or os.environ.get("FIFTY_UNBLOCK_MODEL")
                or "claude-sonnet-4-6",
                label="design-tool-rescue",
                max_output_tokens=10000,
            )
            parsed = _parse_tool_rescue_response(resp.raw_text)
        except ApiKeyMissingError as exc:
            print(f"refusing to --tool-rescue: {exc}", file=sys.stderr)
            return 5
        except Exception as exc:
            boundary = _human_boundary_from_exception(exc)
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped" if boundary else "not-improved",
                reason=f"Tool rescue call/parse failure: {exc!s}",
                before=[b.fingerprint for b in plan.blockers],
                after=[b.fingerprint for b in plan.blockers],
                touched_files=[],
                commands=[],
                verification={
                    "layer": "tool-rescue",
                    "error": repr(exc),
                    **({"human_boundary": boundary} if boundary else {}),
                    **_exception_boundary_metadata(exc),
                },
                notes=["tool rescue response failed"],
            )
            append_attempt(run_dir, record)
            if boundary:
                return 4
            attempt_history.append(asdict(record))
            continue

        before = [b.fingerprint for b in plan.blockers]
        human_boundary = parsed.get("human_boundary")
        if human_boundary:
            record = AttemptRecord(
                at=time.time(),
                attempt=attempt_number,
                decision="stopped",
                reason=f"Tool rescue reported human boundary: {human_boundary}",
                before=before,
                after=before,
                touched_files=[],
                commands=[],
                verification={"layer": "tool-rescue", "human_boundary": human_boundary},
                notes=[str(parsed.get("rationale") or "")[:800]],
            )
            append_attempt(run_dir, record)
            return 4

        action_results, rejected_actions = _run_rescue_actions(
            plan.slug,
            plan.allowed_commands,
            parsed.get("actions", []),
        )
        applied, rejected_edits = _apply_llm_edits(plan.slug, parsed.get("edits", []))
        commands_run = [[str(part) for part in result.get("argv", [])] for result in action_results]
        verification_results: list[dict[str, Any]] = []
        for cmd in plan.verification_ladder:
            result = _run_cmd(cmd, timeout=30 * 60)
            verification_results.append(result)
            commands_run.append(cmd)
            if result["returncode"] not in (0, 1):
                break
        categories = [b.category for b in plan.blockers]
        after = _collect_fingerprints(plan.slug, categories)
        verification_failed = any(
            int(result.get("returncode", 0) or 0) != 0
            for result in [*action_results, *verification_results]
        )
        decision, reason = _judge_progress(
            before,
            after,
            slug=plan.slug,
            snap_errors_before=_snap_error_count(plan.slug),
            verification_failed=verification_failed,
        )
        record = AttemptRecord(
            at=time.time(),
            attempt=attempt_number,
            decision=decision,
            reason=reason,
            before=before,
            after=after,
            touched_files=applied,
            commands=commands_run,
            verification={
                "layer": "tool-rescue",
                "llm_rationale": str(parsed.get("rationale") or "")[:800],
                "actions": action_results,
                "verification": verification_results,
                "rejected_actions": rejected_actions,
                "rejected_edits": rejected_edits,
            },
            notes=(["actions rejected: " + "; ".join(rejected_actions)] if rejected_actions else [])
            + (["edits rejected: " + "; ".join(rejected_edits)] if rejected_edits else []),
        )
        append_attempt(run_dir, record)
        attempt_history.append(asdict(record))
        print(
            f"tool-rescue attempt {attempt_number}: {decision} — {reason}; "
            f"actions={len(action_results)} edits={len(applied)}",
            flush=True,
        )
        if decision in {"fixed", "improved"}:
            return 0
        if decision == "worse":
            return 3
        plan = build_repair_plan(run_dir)

    record = AttemptRecord(
        at=time.time(),
        attempt=attempt_number,
        decision="stopped",
        reason=f"Exceeded tool-rescue max-attempts={max_attempts}; escalating.",
        before=[b.fingerprint for b in plan.blockers],
        after=[b.fingerprint for b in plan.blockers],
        touched_files=[],
        commands=[],
        verification={"layer": "tool-rescue", "human_boundary": "attempt-cap"},
        notes=["tool rescue stopped on attempt cap"],
    )
    append_attempt(run_dir, record)
    return 4


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    run_dir = _resolve_run_dir(args)
    if not run_dir.is_dir():
        raise SystemExit(f"run-dir does not exist: {run_dir}")

    plan = build_repair_plan(run_dir)
    write_repair_plan(run_dir, plan)

    if args.format == "json":
        print(json.dumps(_plan_to_dict(plan), indent=2, sort_keys=True))
    else:
        _print_plan_text(plan)

    if args.agentic:
        return agentic_repair(
            run_dir,
            max_attempts=args.max_attempts,
            max_non_improving=args.max_non_improving,
            dry_run=args.agentic_dry_run,
            model=args.model,
        )
    if args.tool_rescue:
        return tool_rescue(
            run_dir,
            max_attempts=args.max_attempts,
            max_non_improving=args.max_non_improving,
            dry_run=args.tool_rescue_dry_run,
            model=args.model,
        )
    if args.recipes:
        if not plan.worktree_clean:
            print(
                "refusing to --recipes: worktree has unrelated framework changes:",
                file=sys.stderr,
            )
            for p in plan.worktree_unrelated_files:
                print(f"  - {p}", file=sys.stderr)
            return 2
        record = apply_recipes(
            run_dir,
            max_attempts=args.max_attempts,
            max_non_improving=args.max_non_improving,
        )
        print()
        print(f"attempt {record.attempt}: {record.decision}")
        print(f"reason: {record.reason}")
        if record.decision in {"fixed", "improved"}:
            return 0
        if record.decision == "worse":
            return 3
        if record.decision == "stopped":
            return 4
        return 1
    if args.apply:
        # Hard safety: refuse to apply if the worktree is mixed with
        # unrelated framework changes (the theme edits the caller made
        # would ship alongside unrelated drift if this passed).
        if not plan.worktree_clean:
            print(
                "refusing to --apply: worktree has unrelated framework changes:",
                file=sys.stderr,
            )
            for p in plan.worktree_unrelated_files:
                print(f"  - {p}", file=sys.stderr)
            return 2
        record = apply_verification(
            run_dir,
            attempt_number=args.attempt_number,
            touched_files=args.touched_files,
            before_fingerprints=args.before_fingerprints,
            note=args.note,
            max_attempts=args.max_attempts,
            max_non_improving=args.max_non_improving,
        )
        print()
        print(f"attempt {record.attempt}: {record.decision}")
        print(f"reason: {record.reason}")
        if record.decision == "fixed":
            return 0
        if record.decision == "improved":
            return 0
        if record.decision == "worse":
            return 3
        if record.decision == "stopped":
            return 4
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
