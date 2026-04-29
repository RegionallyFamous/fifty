#!/usr/bin/env python3
"""Shared prevention catalog for autonomous theme-factory defects.

The rescue loop should teach the generator what not to do next time.
This module is deliberately data-like so `design.py`, `design_unblock.py`,
`design-batch.py`, and tests can agree on the same prevention target.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

PreventionLayer = str
RolloutMode = str


@dataclass(frozen=True)
class PreventionRule:
    category: str
    layer: PreventionLayer
    phase: str
    owner: str
    mode: RolloutMode
    fixture: str
    manual_review_reason: str = ""

    @property
    def promotion_target(self) -> str:
        if self.layer == "spec":
            return "spec-rule"
        if self.layer == "phase":
            return "phase-invariant"
        if self.layer == "recipe":
            return "recipe"
        if self.layer == "render":
            return "render-gate"
        return "manual-review"


RULES: dict[str, PreventionRule] = {
    "php-syntax": PreventionRule(
        category="php-syntax",
        layer="phase",
        phase="clone",
        owner="bin/clone.py",
        mode="hard-fail",
        fixture="tests/tools/test_clone.py",
    ),
    "product-photo-duplicate": PreventionRule(
        category="product-photo-duplicate",
        layer="phase",
        phase="photos",
        owner="bin/generate-product-photos.py",
        mode="hard-fail",
        fixture="tests/tools/test_generate_product_photos.py",
    ),
    "hover-contrast": PreventionRule(
        category="hover-contrast",
        layer="spec",
        phase="validate",
        owner="bin/_design_lib.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_lib.py",
    ),
    "microcopy-duplicate": PreventionRule(
        category="microcopy-duplicate",
        layer="phase",
        phase="microcopy",
        owner="bin/generate-microcopy.py",
        mode="report-only",
        fixture="tests/tools/test_generate_microcopy.py",
    ),
    "wc-microcopy-duplicate": PreventionRule(
        category="wc-microcopy-duplicate",
        layer="phase",
        phase="microcopy",
        owner="bin/generate-microcopy.py",
        mode="hard-fail",
        fixture="tests/tools/test_generate_microcopy.py",
    ),
    "cross-theme-product-images": PreventionRule(
        category="cross-theme-product-images",
        layer="phase",
        phase="photos",
        owner="bin/generate-product-photos.py",
        mode="report-only",
        fixture="tests/tools/test_generate_product_photos.py",
    ),
    "hero-placeholders-duplicate": PreventionRule(
        category="hero-placeholders-duplicate",
        layer="phase",
        phase="photos",
        owner="bin/generate-product-photos.py",
        mode="hard-fail",
        fixture="tests/tools/test_generate_product_photos.py",
    ),
    "screenshot-duplicate": PreventionRule(
        category="screenshot-duplicate",
        layer="phase",
        phase="screenshot",
        owner="bin/build-theme-screenshots.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_phases.py",
    ),
    "snap-a11y-color-contrast": PreventionRule(
        category="snap-a11y-color-contrast",
        layer="render",
        phase="snap",
        owner="bin/snap.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_phases.py",
    ),
    "placeholder-images": PreventionRule(
        category="placeholder-images",
        layer="phase",
        phase="seed",
        owner="bin/seed-playground-content.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_phases.py",
    ),
    "category-images": PreventionRule(
        category="category-images",
        layer="phase",
        phase="photos",
        owner="bin/generate-product-photos.py",
        mode="hard-fail",
        fixture="tests/tools/test_generate_product_photos.py",
    ),
    "snap-evidence-stale": PreventionRule(
        category="snap-evidence-stale",
        layer="render",
        phase="snap",
        owner="bin/snap.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_phases.py",
    ),
    "design-score-low": PreventionRule(
        category="design-score-low",
        layer="render",
        phase="scorecard",
        owner="bin/design-scorecard.py",
        mode="report-only",
        fixture="tests/tools/test_design_scorecard.py",
        manual_review_reason="Design score has judgment-heavy components; keep rendered evidence.",
    ),
    "factory-timeout": PreventionRule(
        category="factory-timeout",
        layer="manual-review",
        phase="watch",
        owner="bin/design-watch.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_watch.py",
        manual_review_reason=(
            "A wall-clock timeout can implicate Playground, API, CI, or factory tooling; "
            "tool-rescue should inspect run artifacts before a deterministic prevention "
            "rule is promoted."
        ),
    ),
    "factory-stall": PreventionRule(
        category="factory-stall",
        layer="manual-review",
        phase="watch",
        owner="bin/design-watch.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_watch.py",
        manual_review_reason=(
            "A no-output stall can be a transient external hang or a missing heartbeat; "
            "tool-rescue should inspect run artifacts before a deterministic prevention "
            "rule is promoted."
        ),
    ),
    "unknown": PreventionRule(
        category="unknown",
        layer="manual-review",
        phase="manual-review",
        owner="bin/design_unblock.py",
        mode="hard-fail",
        fixture="tests/tools/test_design_unblock.py",
        manual_review_reason="Unknown defects need classification before deterministic prevention.",
    ),
}


def get_rule(category: str) -> PreventionRule:
    return RULES.get(category, RULES["unknown"])


def categories() -> set[str]:
    return set(RULES) - {"unknown"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the autonomous theme-factory prevention rule catalog."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the catalog as JSON instead of a compact text summary.",
    )
    args = parser.parse_args(argv)

    if args.json:
        json.dump({key: asdict(rule) for key, rule in sorted(RULES.items())}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    for key, rule in sorted(RULES.items()):
        print(f"{key}: {rule.layer}/{rule.phase} -> {rule.owner} ({rule.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
