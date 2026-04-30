#!/usr/bin/env python3
"""Build a deterministic design scorecard from snap and vision findings.

The scorecard is intentionally simple: it converts the evidence we already
collect under tmp/snaps/<theme>/ into a small JSON artifact that the autonomous
runner can gate and repair. It does not replace human taste; it gives the agent
a concrete signal for "technically green, visually weak."
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, resolve_theme_root

CATEGORIES = {
    "visual_distinctness": 100,
    "product_photography_fit": 100,
    "hierarchy": 100,
    "cta_clarity": 100,
    "woocommerce_chrome_polish": 100,
    "mobile_desktop_coherence": 100,
}

VISION_CATEGORY_MAP = {
    "vision:photography-mismatch": "product_photography_fit",
    "vision:brand-violation": "visual_distinctness",
    "vision:mockup-divergent": "visual_distinctness",
    "vision:typography-overpowered": "hierarchy",
    "vision:hierarchy-flat": "hierarchy",
    "vision:whitespace-imbalance": "hierarchy",
    "vision:cta-buried": "cta_clarity",
    "vision:color-clash": "visual_distinctness",
    "vision:alignment-off": "mobile_desktop_coherence",
    "vision:content-orphan": "mobile_desktop_coherence",
}

HEURISTIC_CATEGORY_MAP = {
    "placeholder-image": "product_photography_fit",
    "broken-image": "product_photography_fit",
    "background-image-broken": "product_photography_fit",
    "duplicate-nav-block": "woocommerce_chrome_polish",
    "button-label-overflow": "cta_clarity",
    "heading-clipped-vertical": "hierarchy",
    "element-overflow-x": "mobile_desktop_coherence",
    "region-void": "visual_distinctness",
    "region-low-density": "hierarchy",
    "view-transition-name-collision": "woocommerce_chrome_polish",
}

SEVERITY_PENALTY = {
    "error": 18,
    "critical": 18,
    "serious": 18,
    "warn": 9,
    "warning": 9,
    "moderate": 9,
    "info": 4,
    "minor": 4,
}

CONTACT_ROUTES = ("home", "shop", "product-simple", "cart-filled", "checkout-filled", "journal-post")
CONTACT_VIEWPORTS = ("mobile", "desktop")
MASS_FAILURE_VISUAL_DISTINCTNESS_MAX = 10
MASS_FAILURE_WEAK_FINDINGS_MIN = 40


@dataclass
class WeakFinding:
    category: str
    severity: str
    kind: str
    route: str
    viewport: str
    message: str
    screenshot_path: str | None = None
    review_png_path: str | None = None
    crop_path: str | None = None


@dataclass
class WeakFindingGroup:
    category: str
    kind: str
    route: str
    viewport: str
    severity: str
    count: int
    sample_message: str


@dataclass
class Scorecard:
    schema: int
    theme: str
    run_id: str
    generated_at: float
    scores: dict[str, int]
    overall: int
    verdict: str
    classification: str
    mass_failure: bool
    threshold: int
    weak_findings: list[WeakFinding] = field(default_factory=list)
    top_weak_findings: list[WeakFindingGroup] = field(default_factory=list)
    contact_sheet: str | None = None
    next_action: str = ""


def _iter_findings(theme: str) -> list[dict[str, Any]]:
    root = MONOREPO_ROOT / "tmp" / "snaps" / theme
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*.findings.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        route = str(data.get("route") or path.stem)
        viewport = str(data.get("viewport") or path.parent.name)
        for finding in data.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            merged = dict(finding)
            merged.setdefault("route", route)
            merged.setdefault("viewport", viewport)
            out.append(merged)
    return out


def _category_for(kind: str) -> str | None:
    if kind in VISION_CATEGORY_MAP:
        return VISION_CATEGORY_MAP[kind]
    if kind in HEURISTIC_CATEGORY_MAP:
        return HEURISTIC_CATEGORY_MAP[kind]
    if kind.startswith("vision:"):
        return "visual_distinctness"
    if "contrast" in kind:
        return "woocommerce_chrome_polish"
    return None


def _score_findings(findings: list[dict[str, Any]]) -> tuple[dict[str, int], list[WeakFinding]]:
    scores = dict(CATEGORIES)
    weak: list[WeakFinding] = []
    for finding in findings:
        kind = str(finding.get("kind") or "")
        category = _category_for(kind)
        if category is None:
            continue
        severity = str(finding.get("severity") or "info").lower()
        penalty = SEVERITY_PENALTY.get(severity, 4)
        # Vision findings are first-class taste feedback, so do not let
        # an "info" vision note disappear under a tiny penalty.
        if kind.startswith("vision:"):
            penalty = max(penalty, 12)
        scores[category] = max(0, scores[category] - penalty)
        weak.append(
            WeakFinding(
                category=category,
                severity=severity,
                kind=kind,
                route=str(finding.get("route") or ""),
                viewport=str(finding.get("viewport") or ""),
                message=str(finding.get("message") or finding.get("rationale") or "")[:500],
                screenshot_path=finding.get("screenshot_path"),
                review_png_path=finding.get("review_png_path"),
                crop_path=finding.get("crop_path"),
            )
        )
    return scores, weak


def _write_contact_sheet(theme: str, run_dir: Path) -> Path:
    lines = [f"# Contact Sheet: {theme}", ""]
    for viewport in CONTACT_VIEWPORTS:
        lines.append(f"## {viewport.title()}")
        lines.append("")
        for route in CONTACT_ROUTES:
            png = MONOREPO_ROOT / "tmp" / "snaps" / theme / viewport / f"{route}.png"
            if png.is_file():
                rel = png.relative_to(MONOREPO_ROOT)
                lines.append(f"- `{viewport}/{route}`: `{rel}`")
        lines.append("")
    out = run_dir / "contact-sheet.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def _is_mass_failure(scores: dict[str, int], weak: list[WeakFinding]) -> bool:
    return (
        scores.get("visual_distinctness", 100) <= MASS_FAILURE_VISUAL_DISTINCTNESS_MAX
        or any(score == 0 for score in scores.values())
        or len(weak) >= MASS_FAILURE_WEAK_FINDINGS_MIN
    )


def _top_weak_findings(weak: list[WeakFinding], *, limit: int = 12) -> list[WeakFindingGroup]:
    groups: dict[tuple[str, str, str, str, str], list[WeakFinding]] = {}
    for finding in weak:
        key = (
            finding.category,
            finding.kind,
            finding.route,
            finding.viewport,
            finding.severity,
        )
        groups.setdefault(key, []).append(finding)
    ranked = sorted(
        groups.items(),
        key=lambda item: (
            len(item[1]),
            item[0][0],
            item[0][1],
            item[0][2],
            item[0][3],
            item[0][4],
        ),
        reverse=True,
    )
    out: list[WeakFindingGroup] = []
    for (category, kind, route, viewport, severity), items in ranked[:limit]:
        out.append(
            WeakFindingGroup(
                category=category,
                kind=kind,
                route=route,
                viewport=viewport,
                severity=severity,
                count=len(items),
                sample_message=items[0].message,
            )
        )
    return out


def build_scorecard(theme: str, run_id: str, threshold: int) -> Scorecard:
    # Resolve early so typos fail before writing tmp artifacts.
    resolve_theme_root(theme)
    run_dir = MONOREPO_ROOT / "tmp" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    findings = _iter_findings(theme)
    scores, weak = _score_findings(findings)
    overall = min(scores.values()) if scores else 0
    verdict = "pass" if overall >= threshold else "fail"
    mass_failure = verdict == "fail" and _is_mass_failure(scores, weak)
    classification = "mass-failure" if mass_failure else ("marginal" if verdict == "fail" else "green")
    contact = _write_contact_sheet(theme, run_dir)
    if mass_failure:
        next_action = (
            "Stop the factory loop. This is a strategy failure: inspect the grouped "
            "weak findings and adjust the generator/spec/design intent before another run."
        )
    elif verdict == "fail":
        next_action = (
            "Run at most one targeted repair round using the grouped weak findings, "
            "then rerun only the affected rendered evidence."
        )
    else:
        next_action = "Continue the shipping pipeline."
    return Scorecard(
        schema=1,
        theme=theme,
        run_id=run_id,
        generated_at=time.time(),
        scores=scores,
        overall=overall,
        verdict=verdict,
        classification=classification,
        mass_failure=mass_failure,
        threshold=threshold,
        weak_findings=weak,
        top_weak_findings=_top_weak_findings(weak),
        contact_sheet=str(contact.relative_to(MONOREPO_ROOT)),
        next_action=next_action,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--threshold", type=int, default=70)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-fail", action="store_true", help="Write artifacts but never exit non-zero.")
    args = parser.parse_args(argv)

    run_id = args.run_id or f"design-{args.theme}"
    scorecard = build_scorecard(args.theme, run_id, args.threshold)
    out = args.out or (MONOREPO_ROOT / "tmp" / "runs" / run_id / "design-score.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(scorecard), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"design score: {scorecard.overall}/{args.threshold} ({scorecard.verdict})")
    print(f"design scorecard: {out.relative_to(MONOREPO_ROOT)}")
    if scorecard.verdict == "fail":
        label = "WARN" if args.no_fail else "FAIL"
        weakest = min(scorecard.scores.items(), key=lambda item: item[1])
        if scorecard.mass_failure:
            print(
                f"[{label}] [scorecard] Scorecard mass failure\n"
                f"         {weakest[0]} scored {weakest[1]}/{args.threshold}; "
                f"{len(scorecard.weak_findings)} weak finding(s) recorded in {out.relative_to(MONOREPO_ROOT)}; "
                "classification=mass-failure"
            )
            return 0 if args.no_fail else 1
        print(
            f"[{label}] [scorecard] Design scorecard meets minimum\n"
            f"         {weakest[0]} scored {weakest[1]}/{args.threshold}; "
            f"{len(scorecard.weak_findings)} weak finding(s) recorded in {out.relative_to(MONOREPO_ROOT)}"
        )
        return 0 if args.no_fail else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
