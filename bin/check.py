#!/usr/bin/env python3
"""Single-command validator. Run before every commit.

This is the "make test" of the Obel theme. It runs every check the project
cares about and exits non-zero if any of them fail.

Checks performed:
  1. JSON validity for theme.json and styles/*.json
  1a. design-intent.md present next to theme.json (consumed by snap-vision-review.py)
  1b. design-intent.md H1 names the theme directory (catches pasted rubrics)
  1c. no repair-narrative / hex-tagged placeholder microcopy in templates/parts/patterns
  2. PHP syntax for every .php file
  3. Block-name validity in theme.json (via validate-theme-json.py)
  4. No `!important` in code (only in AGENTS.md and other rule docs, which is allowed)
  5. No stray .css files (only style.css is allowed)
  6. No block prefixes other than core/* and woocommerce/* in templates/parts
  7. No AI-fingerprint vocabulary in user-facing files
  8. No hardcoded hex colors in templates/parts/patterns
  9. No hardcoded px/em/rem dimensions in style= attributes (outside allowlist)
 10. No duplicate template files in templates/
 11. No raw hex colors in theme.json (outside palette/gradients/duotone)
 12. No remote font URLs (self-hosted Google Fonts only — see AGENTS.md rule 8)
 13. WooCommerce grid integration (clearfix + loop width) safeguards in theme.json
 14. WooCommerce frontend CSS overrides (product tabs etc.) — see AGENTS.md rule 6
 15. Front-page layout differs from every other theme (no "same shape, different
     colors" reskins — see AGENTS.md rule 8)
 16. No unpushed commits on the current branch (a fix isn't "live" until
     `raw.githubusercontent.com` can serve it to the Playground demo)

Usage:
    python3 bin/check.py            # run everything
    python3 bin/check.py --offline  # skip the network-dependent block check
    python3 bin/check.py --quick    # skip the network check, run everything else

Output: one line per check, with PASS/FAIL/SKIP. Exit code 0 if all pass.

Requires Python 3.8+ and `php` on PATH for PHP syntax check (PHP step is
skipped with a warning if `php` is not available).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_uniqueness import (
    collect_fleet,
    find_value_overlaps,
)
from _lib import MONOREPO_ROOT, iter_themes, resolve_changed_scope, resolve_theme_root

# ROOT is set per-theme in main() before any check runs.
ROOT: Path = Path.cwd()

# ANSI colors. Disabled when not a tty.
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
GREEN = "\033[32m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


def _repo_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(MONOREPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git_tracks(path: Path) -> bool:
    """Return whether `path` is already in the git index.

    Playground content is fetched from raw.githubusercontent.com during snaps
    and live demos. A local-but-untracked map is therefore indistinguishable
    from a missing file once Playground boots remotely.
    """
    rel = _repo_relpath(path)
    try:
        return (
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel],
                cwd=MONOREPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return True


class Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = True
        self.skipped = False
        # `demoted` flips to True when a failing check is matched against
        # the `tests/check-baseline-failures.json` allowlist (see
        # `_demote_baseline_failures` below). A demoted result still has
        # `passed == False` (we want the check body, details, and any
        # downstream reporting to treat it as a real finding), but the
        # overall exit code ignores it so pre-existing debt on `main`
        # does not block unrelated feature work. The `render()` pass
        # labels it WARN-BASELINE instead of FAIL so the signal is still
        # loud on stdout.
        self.demoted = False
        # Set by `_evaluate_checks()` to "structural" or "content" based
        # on the backing check function's presence in
        # `_CONTENT_FIT_CHECK_NAMES`. None when the Result was produced
        # outside the phase-filtering path (e.g. direct call from a
        # test). `render()` prepends the tag when present so a mixed
        # run (`--phase all`) clearly separates "fix the CSS" failures
        # from "regenerate the photos" failures.
        self.phase: str | None = None
        self.details: list[str] = []

    def fail(self, detail: str) -> None:
        self.passed = False
        self.details.append(detail)

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.details.append(reason)

    def render(self) -> str:
        if self.skipped:
            label = f"{YELLOW}SKIP{RESET}"
        elif self.passed:
            label = f"{GREEN}PASS{RESET}"
        elif self.demoted:
            # Yellow, not red -- and with a distinct tag so log scrapers
            # can tell the difference between a new regression (FAIL) and
            # known pre-existing debt on main (WARN-BASELINE).
            label = f"{YELLOW}WARN-BASELINE{RESET}"
        else:
            label = f"{RED}FAIL{RESET}"
        # Phase tag is informational -- it never affects gating. A tiny
        # dim prefix keeps mixed runs readable without cluttering the
        # common single-phase case; unset means "phase unknown / not
        # applicable" and we just omit.
        prefix = ""
        if self.phase:
            prefix = f"{DIM}[{self.phase}]{RESET} "
        line = f"  [{label}] {prefix}{self.name}"
        for detail in self.details:
            line += f"\n         {DIM}{detail}{RESET}"
        if self.demoted:
            line += (
                f"\n         {DIM}(demoted to warning by tests/check-baseline-failures.json; "
                f"already failing on origin/main, so not treated as a regression){RESET}"
            )
        return line


# ---------------------------------------------------------------------------
# Phase split (--phase {structural,content,all})
# ---------------------------------------------------------------------------
#
# See `.cursor/plans/two-step_design_pipeline_*.plan.md` for the full
# rationale. Short version: `bin/design.py` used to mash 20 phases into
# one flame pile, so a fresh theme came back red on a mix of
#
#   - "hover contrast fails"                 (structural, fix the CSS)
#   - "product photography is upstream stock" (content,    regen photos)
#
# forcing the operator to triage by eye. The two-step flow splits the
# pipeline into `build` (structural) and `dress` (content). Every check
# in `_build_results()` gets tagged by which phase it's meaningful in,
# so `--phase structural` runs just the structural ones and exits 0 on
# a fresh clone that still has upstream cartoons; `--phase content`
# runs just the content-fit ones after `dress` has regenerated the
# per-theme assets; `--phase all` (the default) runs every check and
# is byte-identical to the pre-split behavior.
#
# Checks NOT in the frozenset below are structural. This is the
# minimum-diff representation: decorating 74 check functions scattered
# across 9,800 lines would churn the file much more.

PHASE_STRUCTURAL = "structural"
PHASE_CONTENT = "content"
PHASE_ALL = "all"
_PHASES = (PHASE_STRUCTURAL, PHASE_CONTENT, PHASE_ALL)

GATE_WORKSTREAM = "workstream"
GATE_PAIRWISE_FLEET = "pairwise-fleet"
GATE_REPO_INFRA = "repo-infra"
GATE_FLEET_HEALTH = "fleet-health"
_GATES = (GATE_WORKSTREAM, GATE_PAIRWISE_FLEET, GATE_REPO_INFRA, GATE_FLEET_HEALTH)

_PAIRWISE_FLEET_CHECK_NAMES = frozenset(
    {
        "check_distinctive_chrome",
        "check_front_page_unique_layout",
        "check_pattern_microcopy_distinct",
        "check_all_rendered_text_distinct_across_themes",
        "check_wc_microcopy_distinct_across_themes",
        "check_product_images_unique_across_themes",
        "check_hero_images_unique_across_themes",
        "check_theme_screenshots_distinct",
    }
)

_REPO_INFRA_CHECK_NAMES = frozenset(
    {
        "check_allowlist_entries_resolve",
        "check_concept_similarity",
        "check_no_unpushed_commits",
    }
)

_FLEET_HEALTH_CHECK_NAMES = frozenset[str]()


def _gate_for(func_name: str) -> str:
    if func_name in _PAIRWISE_FLEET_CHECK_NAMES:
        return GATE_PAIRWISE_FLEET
    if func_name in _REPO_INFRA_CHECK_NAMES:
        return GATE_REPO_INFRA
    if func_name in _FLEET_HEALTH_CHECK_NAMES:
        return GATE_FLEET_HEALTH
    return GATE_WORKSTREAM


def _cross_theme_stages() -> tuple[str, ...]:
    raw = os.environ.get("FIFTY_FLEET_STAGES", "shipping")
    stages = tuple(part.strip() for part in raw.split(",") if part.strip())
    return stages or ("shipping",)


def _cross_theme_roots() -> list[Path]:
    """Return comparison peers plus ROOT, even when ROOT is incubating.

    This keeps `check.py <new-theme>` honest against the shipped fleet without
    sweeping every unrelated incubating WIP theme into targeted runs.
    """
    try:
        roots = list(iter_themes(stages=_cross_theme_stages()))
    except TypeError:
        # Several unit tests monkeypatch iter_themes with the pre-stage
        # signature. Keep the production helper compatible with those narrow
        # fixtures so the behavior under test stays focused on the check.
        roots = list(iter_themes())
    if ROOT.is_dir() and (ROOT / "theme.json").is_file():
        try:
            root_resolved = ROOT.resolve()
            if all(p.resolve() != root_resolved for p in roots):
                roots.append(ROOT)
        except OSError:
            if ROOT not in roots:
                roots.append(ROOT)
    return sorted(roots, key=lambda p: p.name)

# Content-fit checks: only meaningful AFTER `design.py dress` has
# regenerated per-theme product photography, microcopy, and front-page
# structure. Checks NOT in this set are structural and must pass
# immediately after `design.py build` on a fresh clone.
#
# The rename-drift guard in tests/check_py/test_phase_filter.py
# asserts every name here is actually invoked by `_build_results()`,
# so a rename that breaks the tie fails the gate loudly instead of
# silently demoting a content check to "runs in structural".
_CONTENT_FIT_CHECK_NAMES = frozenset(
    {
        "check_product_image_visual_diversity",
        "check_product_images_json_complete",
        "check_no_placeholder_product_images",
        "check_no_woocommerce_placeholder_in_findings",
        "check_product_images_unique_across_themes",
        "check_hero_images_unique_across_themes",
        "check_pattern_microcopy_distinct",
        "check_all_rendered_text_distinct_across_themes",
        "check_front_page_unique_layout",
        "check_concept_similarity",
    }
)


def _phase_for(func_name: str) -> str:
    """Return the phase a check function belongs to."""
    return PHASE_CONTENT if func_name in _CONTENT_FIT_CHECK_NAMES else PHASE_STRUCTURAL


def _phase_keeps(func_name: str, phase: str) -> bool:
    """Decide whether a check named `func_name` runs under `phase`."""
    if phase == PHASE_ALL:
        return True
    return _phase_for(func_name) == phase


_ONLY_ALIASES = {
    "placeholder-images": "check_no_woocommerce_placeholder_in_findings",
    "no-woocommerce-placeholder": "check_no_woocommerce_placeholder_in_findings",
    "woocommerce-placeholder": "check_no_woocommerce_placeholder_in_findings",
    "product-image-map": "check_product_images_json_complete",
    "product-images-json": "check_product_images_json_complete",
    "category-image-map": "check_category_images_json_complete",
    "category-images-json": "check_category_images_json_complete",
    "playground-content": "check_playground_content_seeded",
    "snap-evidence": "check_evidence_freshness",
}


def _normalise_check_selector(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _filter_checks_by_only(
    items: list[tuple[str, Callable[[], Result]]],
    only: list[str] | None,
) -> list[tuple[str, Callable[[], Result]]]:
    """Return checks selected by --only.

    Selectors accept the exact function name, the function name without the
    `check_` prefix, or a curated alias for the common expensive triage loops.
    """
    if not only:
        return items

    by_name: dict[str, tuple[str, Callable[[], Result]]] = {}
    for name, thunk in items:
        by_name[_normalise_check_selector(name)] = (name, thunk)
        by_name[_normalise_check_selector(name.removeprefix("check_"))] = (name, thunk)

    selected: list[tuple[str, Callable[[], Result]]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in only:
        key = _normalise_check_selector(_ONLY_ALIASES.get(raw, raw))
        match = by_name.get(key)
        if not match:
            missing.append(raw)
            continue
        if match[0] in seen:
            continue
        seen.add(match[0])
        selected.append(match)

    if missing:
        available = sorted(name.removeprefix("check_") for name, _ in items)
        raise SystemExit(
            "Unknown --only check selector(s): "
            + ", ".join(missing)
            + ". Available examples: "
            + ", ".join(available[:12])
            + (" ..." if len(available) > 12 else "")
        )
    return selected


def _evaluate_checks(
    items: list[tuple[str, Callable[[], Result]]],
    phase: str,
    only: list[str] | None = None,
) -> list[Result]:
    """Filter by phase, invoke the surviving thunks, tag each Result."""
    results: list[Result] = []
    for name, thunk in _filter_checks_by_only(items, only):
        if not _phase_keeps(name, phase):
            continue
        r = thunk()
        r.phase = _phase_for(name)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Baseline-failure allowlist (FIFTY_ALLOW_BASELINE_FAILURES)
# ---------------------------------------------------------------------------
#
# See `tests/check-baseline-failures.json` for the full rationale. The short
# version: the hooks (pre-commit, pre-push) and CI's theme-gate set
# `FIFTY_ALLOW_BASELINE_FAILURES=1` around their `bin/check.py` runs. That
# tells this script to load the JSON file and DEMOTE any failing check
# whose (theme_name, check_title) pair is listed there -- from FAIL
# (exit-1-able) to WARN-BASELINE (still printed, but harmless).
#
# Rationale: main has always carried a tiny amount of latent debt (e.g.
# Foundry's 2.14:1 hover contrast vs the 3:1 floor). That debt was
# irrelevant to every unrelated PR but blocked them anyway, forcing
# agents to reach for `git commit --no-verify` repeatedly. With this
# mechanism, pre-existing debt is tracked explicitly, new regressions
# still block, and the user's feature commits flow through without
# manual intervention.
#
# Regeneration: `python3 bin/check.py --save-baseline-failures` writes
# the current tree's failures back into the JSON. Run it on origin/main
# (or let the pre-push hook auto-refresh via a detached `git worktree`
# when it notices staleness).

BASELINE_FAILURES_PATH = MONOREPO_ROOT / "tests" / "check-baseline-failures.json"


def _load_baseline_failures() -> set[tuple[str, str]]:
    """Return the set of (theme_name, check_title) pairs known to fail on
    origin/main. Empty set if the file is missing or malformed -- in that
    case the env var is a no-op and the gate stays strict.
    """
    if not BASELINE_FAILURES_PATH.exists():
        return set()
    try:
        data = json.loads(BASELINE_FAILURES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    out: set[tuple[str, str]] = set()
    for entry in data.get("failures", []) or []:
        theme = entry.get("theme")
        check = entry.get("check")
        if isinstance(theme, str) and isinstance(check, str):
            out.add((theme, check))
    return out


def _demote_baseline_failures(results: list[Result], theme_name: str) -> int:
    """Walk `results` and flip `.demoted = True` on any failure whose
    (theme_name, r.name) matches the baseline allowlist. Returns how many
    were demoted.

    No-op unless `FIFTY_ALLOW_BASELINE_FAILURES=1`. The env-var gate is
    there because the default behaviour of `bin/check.py` (called by
    hand, by `ci-on-main`, or by the `tooling-tests` job) must remain
    strict: the allowlist is only correct for feature branches whose
    job is to introduce *new* work without being blocked by pre-
    existing debt. On main the allowlist would just hide real
    regressions.
    """
    if os.environ.get("FIFTY_ALLOW_BASELINE_FAILURES") != "1":
        return 0
    allow = _load_baseline_failures()
    if not allow:
        return 0
    demoted = 0
    for r in results:
        if r.passed or r.skipped:
            continue
        if (theme_name, r.name) in allow:
            r.demoted = True
            demoted += 1
    return demoted


def check_json_validity() -> Result:
    r = Result("JSON validity (theme.json + styles/*.json)")
    targets = [ROOT / "theme.json"] + sorted((ROOT / "styles").glob("*.json"))
    for path in targets:
        if not path.exists():
            r.fail(f"missing: {path.relative_to(ROOT)}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            r.fail(f"{path.relative_to(ROOT)}: {exc}")
    if r.passed and not r.skipped:
        r.details.append(f"{len(targets)} files checked")
    return r


def check_design_intent_present() -> Result:
    """Every theme must ship a `design-intent.md` next to its `theme.json`.

    The file is the canonical design rubric for the theme — voice, palette,
    typography, required and forbidden patterns. It is consumed by
    `bin/snap-vision-review.py`, which concatenates it into the prompt that
    asks the vision model to critique each rendered route. Without it, the
    vision reviewer falls back to a generic rubric and surfaces noise instead
    of brand-grounded findings.

    The file is also a forcing function for design discipline: a theme that
    does not have an articulated brand voice is a theme that cannot be
    coherently extended. Adding `theme.json` without `design-intent.md` is
    treated as a structural omission, on par with a missing block template.
    """
    r = Result("design-intent.md present (paired with theme.json)")
    theme_json = ROOT / "theme.json"
    intent = ROOT / "design-intent.md"
    if not theme_json.exists():
        r.skip("no theme.json -- nothing to pair against")
        return r
    if not intent.exists():
        r.fail(
            "design-intent.md missing. Add a sibling file next to theme.json "
            "that documents Voice, Palette, Typography, Required patterns, "
            "and Forbidden patterns. See `obel/design-intent.md` for the "
            "canonical shape; the file is read by bin/snap-vision-review.py "
            "to ground vision findings in this theme's brand."
        )
        return r
    body = intent.read_text(encoding="utf-8", errors="replace")
    required_sections = ("## Voice", "## Palette", "## Typography")
    missing = [s for s in required_sections if s not in body]
    if missing:
        r.fail(
            f"design-intent.md exists but is missing sections: {', '.join(missing)}. "
            "These sections are concatenated into the vision-review prompt; "
            "without them the reviewer cannot critique against this theme's brand."
        )
        return r
    if len(body.strip()) < 200:
        r.fail(
            f"design-intent.md is too short ({len(body.strip())} chars). "
            "A useful rubric is at least a few hundred characters of "
            "concrete language about voice, palette, and typography."
        )
        return r
    r.details.append(f"{len(body.splitlines())} lines, {len(body)} chars")
    return r


def check_design_intent_brand_match() -> Result:
    """First ATX H1 in design-intent.md must name the theme directory.

    Catches rubrics pasted from another variant (e.g. ``basalt`` still
    opening with ``# foundry``). Vision review concatenates this file;
    a mismatched heading sends the wrong brand criteria at the model.
    """
    r = Result("design-intent.md H1 names this theme directory")
    theme_json = ROOT / "theme.json"
    intent = ROOT / "design-intent.md"
    if not theme_json.exists():
        r.skip("no theme.json")
        return r
    if not intent.exists():
        r.skip("design-intent.md missing (see design-intent present check)")
        return r
    slug = ROOT.name
    slug_hyphen = slug.lower()
    slug_space = slug_hyphen.replace("-", " ")
    body = intent.read_text(encoding="utf-8", errors="replace")
    h1_title = ""
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(#+)\s+(.*)$", line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if level != 1:
            r.fail(
                f"design-intent.md first heading is not an H1: {line[:120]!r}. "
                "Open the file with a single `# …` title line that names this "
                f"theme (directory {slug!r}) before any `##` subsections."
            )
            return r
        h1_title = title
        break
    if not h1_title:
        r.fail(
            "design-intent.md has no ATX H1 (`# Title`). Add an opening line "
            f"such as `# {slug} — design intent` before subsections."
        )
        return r
    h1_low = h1_title.lower()
    if slug_hyphen not in h1_low and slug_space not in h1_low:
        r.fail(
            f"design-intent.md H1 {h1_title!r} does not contain the theme "
            f"directory slug ({slug!r} as `{slug_hyphen}` or spaced words "
            f"`{slug_space}`). Rewrite the opening `# …` line so tooling "
            "and reviewers can tell which theme this rubric belongs to."
        )
        return r
    r.details.append(f"H1 documents {slug!r}")
    return r


_LEAK_FLEET_REGISTER_HEX: re.Pattern[str] | None = None
_STALE_REPAIR_MICROCOPY_RE = re.compile(
    r"(?is)"
    r"\b(?:register|counter)\s+[a-z]{1,24}\s+[0-9a-f]{4,10}\b"
    r"|"
    r"\bparcel\s+(?:basket|record|copy)\s+(?:[a-z]{1,20}\s+)?[0-9a-f]{4,10}\b"
    r"|"
    r"\bcounter\s+record\s+[0-9a-f]{4,10}\b"
    r"|"
    r"\bshop-floor\s+find\s+[0-9a-f]{4,10}\b"
    r"|"
    r"\bvoucher\s+slip\s+[0-9a-f]{4,10}\b"
)


def _leak_fleet_register_hex_pattern() -> re.Pattern[str]:
    """Match ``<any-theme-slug> register <short-hex>`` across the monorepo."""
    global _LEAK_FLEET_REGISTER_HEX
    if _LEAK_FLEET_REGISTER_HEX is not None:
        return _LEAK_FLEET_REGISTER_HEX
    roots = list(iter_themes(MONOREPO_ROOT, stages=()))
    slugs = sorted({p.name.lower() for p in roots}, key=len, reverse=True)
    if not slugs:
        _LEAK_FLEET_REGISTER_HEX = re.compile(r"(?!x)x")
        return _LEAK_FLEET_REGISTER_HEX
    alt = "|".join(re.escape(s) for s in slugs)
    _LEAK_FLEET_REGISTER_HEX = re.compile(
        rf"(?i)\b(?:{alt})\s+register\s+[0-9a-f]{{4,10}}\b"
    )
    return _LEAK_FLEET_REGISTER_HEX


def _iter_placeholder_microcopy_scan_files() -> list[Path]:
    """HTML/PHP surfaces where shopper-visible copy is authored."""
    paths: list[Path] = []
    for sub, suffixes in (
        ("templates", (".html",)),
        ("parts", (".html",)),
        ("patterns", (".html", ".php")),
    ):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in suffixes:
                paths.append(p)
    fp = ROOT / "functions.php"
    if fp.is_file():
        paths.append(fp)
    mo = ROOT / "microcopy-overrides.json"
    if mo.is_file():
        paths.append(mo)
    return sorted(paths, key=lambda p: p.as_posix())


def check_no_placeholder_microcopy() -> Result:
    """Reject repair-narrative / hex-tagged placeholder strings in markup.

    These patterns come from half-applied voice passes (e.g. ``Register
    sum d075``, ``Noir register 2560``) that must never ship in templates,
    patterns, WC gettext maps, or ``microcopy-overrides.json``.
    """
    r = Result("no placeholder repair microcopy in theme sources")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("no theme.json")
        return r
    fleet_re = _leak_fleet_register_hex_pattern()
    repair_re = _STALE_REPAIR_MICROCOPY_RE
    hits: set[tuple[str, str]] = set()
    paths = _iter_placeholder_microcopy_scan_files()
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            r.fail(f"{path.relative_to(ROOT)}: {exc}")
            return r
        rel = path.relative_to(ROOT).as_posix()
        for cre in (fleet_re, repair_re):
            for m in cre.finditer(text):
                hits.add((rel, m.group(0).strip()))
    if hits:
        sample = sorted(hits)[:12]
        lines = [f"  {rel}: {frag!r}" for rel, frag in sample]
        r.fail(
            "Leaked repair/placeholder microcopy (hex-tagged narrative). "
            "Remove or rewrite:\n" + "\n".join(lines)
        )
        return r
    r.details.append(f"{len(paths)} files scanned")
    return r


def check_theme_readiness() -> Result:
    """Every theme SHOULD ship a `readiness.json` (Tier 1.3 of the
    pre-100-themes hardening plan).

    The manifest declares what stage the theme is in
    (``incubating`` | ``shipping`` | ``retired``) and drives:

      * discovery: whether `bin/snap.py shoot --all`, `bin/check.py
        --all`, `bin/append-wc-overrides.py`, and the snap gallery
        include this theme in their default sweep. Incubating themes
        drop out so a WIP folder can't bring CI down until it's
        actually ready.
      * the theme-status dashboard (Tier 2.2): each row's stage + last
        human review date come from this file.

    For backward compat with the six pre-manifest themes we emit WARN
    (not FAIL) when the file is missing; the WARN nudges operators to
    add one without blocking the existing gate. New themes created by
    `bin/clone.py` (Tier 1.2 concept-to-spec integration) will write
    the manifest automatically, so the WARN stays temporary.

    When the file IS present, we validate it strictly: a bad JSON body
    or an invalid `stage` is a FAIL because the discovery layer would
    have silently fallen back to "shipping" and hidden the drift.
    """
    r = Result("readiness.json manifest (stage + summary + owner)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("no theme.json -- nothing to classify")
        return r
    # Import lazily so check.py still runs in isolated environments
    # where bin/ isn't on sys.path (e.g. pytest harness importing a
    # single function). The module is stdlib-only so the import is
    # cheap.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _readiness import (
        MANIFEST_NAME,
        STAGE_SHIPPING,
        VALID_STAGES,
        manifest_path,
        validate_payload,
    )

    path = manifest_path(ROOT)
    if not path.is_file():
        # WARN: soft for backward compat, see docstring.
        r.details.append(
            f"{MANIFEST_NAME} missing. Add one with at least "
            f"`stage` (one of {sorted(VALID_STAGES)}), `summary`, "
            f"and `owner`. Defaults to stage={STAGE_SHIPPING!r} for "
            "discovery today; this check will be upgraded to FAIL "
            "once the backfill has rolled through every branch."
        )
        r.skip("readiness.json missing (backward compat; add one)")
        return r
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        r.fail(f"{MANIFEST_NAME} is not valid JSON: {exc}")
        return r
    problems = validate_payload(data)
    if problems:
        r.fail(f"{MANIFEST_NAME} has schema problems: " + "; ".join(problems))
        return r
    r.details.append(f"stage={data.get('stage')!r}, owner={data.get('owner', '(blank)')!r}")
    return r


def check_php_syntax() -> Result:
    r = Result("PHP syntax (functions.php + patterns/*.php)")
    if not shutil.which("php"):
        r.skip("php not found on PATH")
        return r
    php_files = [ROOT / "functions.php"] + sorted((ROOT / "patterns").glob("*.php"))
    for path in php_files:
        if not path.exists():
            continue
        proc = subprocess.run(
            ["php", "-l", str(path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            r.fail(f"{path.relative_to(ROOT)}: {proc.stderr.strip() or proc.stdout.strip()}")
    if r.passed and not r.skipped:
        r.details.append(f"{len(php_files)} files checked")
    return r


def check_block_names(offline: bool) -> Result:
    r = Result("Block-name validity (validate-theme-json.py)")
    if offline:
        r.skip("--offline / --quick passed")
        return r
    bin_dir = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, str(bin_dir / "validate-theme-json.py"), str(ROOT / "theme.json")],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        r.fail(proc.stdout.strip() or proc.stderr.strip())
    return r


def check_index_in_sync() -> Result:
    r = Result("INDEX.md in sync (build-index.py --check)")
    bin_dir = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, str(bin_dir / "build-index.py"), ROOT.name, "--check"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        r.fail((proc.stderr or proc.stdout).strip())
    return r


# Files where `!important` is allowed because they document the rule itself.
IMPORTANT_RULE_DOCS = {"AGENTS.md", "README.md", "readme.txt", "CHANGELOG.md"}

# Sentinel-bracketed chunks of `theme.json` `styles.css` where `!important`
# is allowed because the cascade fight against WooCommerce plugin CSS is
# unwinnable without it. These are emitted by `bin/append-wc-overrides.py`
# and bracketed by paired `/* <name> */` ... `/* /<name> */` markers.
#
# Adding a chunk to this allow-list is a deliberate decision; do NOT add a
# new entry without:
#   1. trying every selector-specificity workaround first (see
#      `bin/append-wc-overrides.py`'s other chunks for examples that won
#      without `!important`),
#   2. documenting in code WHY the cascade fight cannot be won without it
#      (which exact WC plugin rule + computed specificity beats the theme),
#   3. keeping the chunk as small as humanly possible.
#
# Current entries:
#   * wc-tells-phase-a-premium     -- defends against the legacy
#       woocommerce/product-image-gallery's `opacity:0` start state when
#       its Flexslider/PhotoSwipe JS doesn't init (Playground / fresh-WC
#       failure mode), hides WC blocks loading-skeletons that otherwise
#       flash a blank panel during checkout hydration, and force-fits the
#       variation `<select>`'s font. Without `!important` the WC plugin
#       CSS at `(0,4,3)` wins and the PDP paints empty cream.
#   * wc-tells-phase-c-premium     -- one rule (the WC mini-cart item image
#       sizing for `.wc-block-mini-cart__drawer .wc-block-cart-item__image
#       img, .wc-block-cart-items img`) needs `!important` because WC ships
#       its own width/height on the same selector at the same specificity,
#       and the JS-rendered cart drawer hydrates after our CSS so cascade
#       order doesn't help. Without `!important` cart thumbnails balloon
#       to native image dimensions on first paint.
#   * wc-tells-phase-e-distinctive -- per-theme branded button overrides
#       scoped under `body.theme-<slug>` for `.single_add_to_cart_button`,
#       `.wp-block-button__link`, `.wc-block-components-checkout-place-order-button`,
#       and `.onsale`. WC ships these with property-level `!important` on
#       background/border/padding so the only way for the theme's branded
#       voice to land is to also use `!important`.
IMPORTANT_ALLOWED_SENTINELS = (
    ("/* wc-tells-phase-a-premium */", "/* /wc-tells-phase-a-premium */"),
    ("/* wc-tells-phase-c-premium */", "/* /wc-tells-phase-c-premium */"),
    ("/* wc-tells-phase-e-distinctive */", "/* /wc-tells-phase-e-distinctive */"),
    # Phase J — Aero iridescent voice. Uses !important to win over the
    # cloned-from-obel Phase E rules with `body.theme-aero` selectors that
    # would otherwise paint Aero with Obel's hairline-square voice. The
    # entire chunk is body.theme-aero scoped so it's inert on every other
    # theme.
    ("/* wc-tells-phase-j-aero-iridescent */", "/* /wc-tells-phase-j-aero-iridescent */"),
    # Phase M -- a11y contrast tweaks for upstream-WC component states.
    # Uses !important to win over WC Blocks' own component CSS for the
    # disabled add-to-cart button, the comment-reply-link accent paint,
    # and the `.is-disabled` cart-item loading flash. The whole chunk is
    # documented inline in `bin/append-wc-overrides.py` (PHASE_M block).
    ("/* wc-tells-phase-m-a11y-contrast */", "/* /wc-tells-phase-m-a11y-contrast */"),
)


# ----------------------------------------------------------------------
# Sentinel-bracketed regions of styles.css where raw hex literals are
# allowed by `check_no_hex_in_theme_json`. Same shape and same
# justification as `IMPORTANT_ALLOWED_SENTINELS`: distinctive chrome
# chunks that paint multi-stop gradients (iridescent buttons, y2k
# aurora backgrounds, frosted-glass cards) need precise color stops
# that don't have palette equivalents. Bloating the palette with one
# token per gradient stop ("aurora-stop-1", "shine-stop-2", ...)
# makes the palette useless as a design surface, so the explicit
# allow-list is "yes, this hex is intentional, it's part of a
# multi-stop gradient or a `text-shadow` rgba — not a stray brand
# color that should have been a palette token". Each entry MUST
# cover a chunk that is theme-scoped (`body.theme-<slug>`) so the
# raw hex can't leak into other themes' computed style.
HEX_ALLOWED_SENTINELS = (
    (
        "/* wc-tells-phase-j-aero-iridescent */",
        "/* /wc-tells-phase-j-aero-iridescent */",
    ),
)


def _strip_allowed_hex_chunks(text: str) -> str:
    """Same shape as `_strip_allowed_important_chunks`, but for the
    raw-hex scan inside `theme.json`'s `styles.css` string. Operates
    on the raw string (NOT line-by-line) because
    `bin/append-wc-overrides.py` emits each chunk as one minified
    line (sentinels and rules glued together).
    """
    out = text
    for open_marker, close_marker in HEX_ALLOWED_SENTINELS:
        while True:
            i = out.find(open_marker)
            if i == -1:
                break
            j = out.find(close_marker, i + len(open_marker))
            if j == -1:
                break
            out = out[:i] + out[j + len(close_marker) :]
    return out


def _strip_allowed_important_chunks(text: str) -> str:
    """Remove sentinel-bracketed regions from `text` so the `!important`
    scan can ignore them. Operates on the raw string (NOT line-by-line)
    because `bin/append-wc-overrides.py` emits the chunks as one minified
    line each, so the open + close sentinels usually live on the same
    line as the rules between them.
    """
    out = text
    for open_marker, close_marker in IMPORTANT_ALLOWED_SENTINELS:
        while True:
            i = out.find(open_marker)
            if i == -1:
                break
            j = out.find(close_marker, i + len(open_marker))
            if j == -1:
                # Unclosed marker -- bail out, leave the rest untouched so
                # the scan still catches new !important rules added past
                # the dangling sentinel.
                break
            out = out[:i] + out[j + len(close_marker) :]
    return out


def check_no_important() -> Result:
    r = Result("No `!important` in code")
    pattern = re.compile(r"!important")
    for path in iter_files((".json", ".php", ".html", ".css")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in IMPORTANT_RULE_DOCS:
            continue
        if rel.startswith("bin/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        scanned = _strip_allowed_important_chunks(text)
        for lineno, line in enumerate(scanned.splitlines(), 1):
            if pattern.search(line):
                r.fail(f"{rel}:{lineno}: {line.strip()}")
    return r


def check_no_stray_css() -> Result:
    r = Result("No stray .css files (only style.css allowed)")
    for path in ROOT.rglob("*.css"):
        if any(part in {".git", "node_modules", "vendor"} for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel != "style.css":
            r.fail(rel)
    return r


def check_block_prefixes() -> Result:
    r = Result("Only core/* and woocommerce/* blocks in templates/parts/patterns")
    block_re = re.compile(r"<!--\s*wp:([a-z0-9-]+)/")
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not (
            rel.startswith("templates/") or rel.startswith("parts/") or rel.startswith("patterns/")
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for ns in block_re.findall(line):
                if ns not in ("core", "woocommerce"):
                    r.fail(f"{rel}:{lineno}: forbidden namespace '{ns}'")
    return r


# Vocabulary that signals AI-generated marketing copy. The rule docs themselves
# (AGENTS.md, CHANGELOG.md) reference these words and are excluded.
AI_FINGERPRINT_RE = re.compile(
    r"—|\bleverage\b|\bcomprehensive\b|\bseamless\b|\bdelve\b|\btapestry\b|\brobust\b",
    re.IGNORECASE,
)
AI_FINGERPRINT_TARGETS = ("README.md", "readme.txt", "style.css")


def check_no_hardcoded_colors() -> Result:
    """Scan templates/parts/patterns for hardcoded hex colors.

    The Cover block legitimately outputs background-color on its inner span
    when a custom overlay color is set (customOverlayColor). Since we've
    switched all covers to named palette colors, any remaining hex literal
    is a mistake.

    Allowlist: lines containing 'rgba(' are permitted (used for gradients and
    shadows defined in theme.json, not in markup).
    """
    r = Result("No hardcoded hex colors in templates/parts/patterns")
    # `#RGB` | `#RRGGBB` | `#RRGGBBAA`. The `entity_re` below strips
    # HTML numeric entities (`&#10086;`, `&#x2766;`, etc.) before this
    # regex runs — those are glyph escapes used for ornamental fleurons
    # in templates, not color literals, and without the strip they
    # trip this check. Foundry and chonk both legitimately embed
    # `&#10086;` in decorative groups.
    hex_re = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    entity_re = re.compile(r"&#x?[0-9A-Fa-f]+;")
    skip_dirs = {"templates/", "parts/", "patterns/"}
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "rgba(" in line:
                continue
            stripped = entity_re.sub("", line)
            if hex_re.search(stripped):
                r.fail(f"{rel}:{lineno}: {line.strip()}")
    return r


def check_no_hex_in_theme_json() -> Result:
    """Fail if theme.json contains hex colors outside the palette declarations.

    Allowed locations for raw hex: settings.color.palette, settings.color.gradients,
    settings.color.duotone. Anywhere else (styles.css escape hatches,
    settings.shadow.presets, block-level styles, etc.) must use design tokens
    so a single palette edit ripples everywhere.
    """
    r = Result("No raw hex colors in theme.json (outside palette)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r
    hex_re = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
    allowed_prefixes = (
        "settings.color.palette",
        "settings.color.gradients",
        "settings.color.duotone",
    )

    def walk(node, path: str = "") -> None:
        if any(path.startswith(p) for p in allowed_prefixes):
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            scanned = _strip_allowed_hex_chunks(node) if path.endswith("styles.css") else node
            for m in hex_re.finditer(scanned):
                r.fail(f"theme.json: '{m.group(0)}' at {path}")

    walk(data)
    return r


def check_no_remote_fonts() -> Result:
    """Enforce the self-hosted-Google-Fonts-only rule (AGENTS.md hard rule 8).

    Web fonts MUST be downloaded as .woff2 into assets/fonts/ and registered via
    theme.json `settings.typography.fontFamilies[*].fontFace[*].src` as a
    `file:./assets/fonts/<file>.woff2` path. Any reference to a remote font CDN
    is forbidden — including the Google Fonts CDN. Reasons: privacy, performance,
    license clarity, offline editability.

    Forbidden patterns scanned for:

    1. `theme.json` `fontFace[*].src` containing anything other than `file:` paths
       (`https://`, `http://`, `//cdn`, etc.)
    2. Any string in `theme.json` referencing the known font CDNs
       (fonts.googleapis.com, fonts.gstatic.com, use.typekit.net, fonts.bunny.net,
        fontshare.com, p.typekit.net) — catches `@import` smuggled into
        `styles.css` or per-block `css` escape hatches
    3. Templates / parts / patterns / functions.php / *.php referencing the same
       CDNs (catches `<link rel="preconnect" href="...">`,
       `<link rel="stylesheet" href="...">`, `wp_enqueue_style(..., 'https://fonts...')`)

    System font stacks (`-apple-system`, `BlinkMacSystemFont`, `system-ui`,
    `Helvetica Neue`, `Arial`, `Georgia`, `Iowan Old Style`, etc.) used inside
    `fontFamily` values are always allowed and not scanned.
    """
    r = Result("No remote font URLs (self-hosted Google Fonts only)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    forbidden_hosts = (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "use.typekit.net",
        "p.typekit.net",
        "fonts.bunny.net",
        "api.fontshare.com",
        "use.fontawesome.com",
    )
    remote_scheme_re = re.compile(r"^(https?:)?//", re.IGNORECASE)

    families = data.get("settings", {}).get("typography", {}).get("fontFamilies", []) or []
    for fam in families:
        if not isinstance(fam, dict):
            continue
        fam_slug = fam.get("slug", "?")
        for face_idx, face in enumerate(fam.get("fontFace", []) or []):
            if not isinstance(face, dict):
                continue
            srcs = face.get("src", [])
            if isinstance(srcs, str):
                srcs = [srcs]
            for src_idx, src in enumerate(srcs or []):
                if not isinstance(src, str):
                    continue
                if remote_scheme_re.search(src):
                    r.fail(
                        f"theme.json: fontFamilies[{fam_slug}].fontFace[{face_idx}].src[{src_idx}]"
                        f" is a remote URL ({src!r}); download the .woff2 to assets/fonts/"
                        f" and use 'file:./assets/fonts/<file>.woff2'."
                    )
                elif not src.startswith("file:"):
                    r.fail(
                        f"theme.json: fontFamilies[{fam_slug}].fontFace[{face_idx}].src[{src_idx}]"
                        f" must start with 'file:./assets/fonts/...' (got {src!r})."
                    )

    def walk_strings(node, path: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk_strings(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk_strings(v, f"{path}[{i}]")
        elif isinstance(node, str):
            lower = node.lower()
            for host in forbidden_hosts:
                if host in lower:
                    r.fail(f"theme.json: '{host}' referenced at {path}")

    walk_strings(data)

    file_targets = []
    for sub in ("templates", "parts", "patterns"):
        sub_path = ROOT / sub
        if sub_path.exists():
            for p in sub_path.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".html", ".php"):
                    file_targets.append(p)
    for php in ROOT.glob("*.php"):
        file_targets.append(php)

    for path in file_targets:
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = text.lower()
        for host in forbidden_hosts:
            if host in lowered:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if host in line.lower():
                        r.fail(f"{rel}:{lineno}: '{host}' — {line.strip()[:120]}")

    return r


def check_wc_grid_integration() -> Result:
    """Catch known WooCommerce + theme.json layout integration bugs.

    Specifically:

    1. CLEARFIX-IN-GRID
       WooCommerce's plugin CSS adds clearfix `::before` and `::after` pseudo-
       elements to `ul.products` (`content:" "; display:table; clear:both`).
       When a theme sets `display:grid` on the same `<ul>`, those pseudos
       become real grid items and consume cells, leaving visible empty slots
       (e.g. 2 product cards on a 4-cell grid show in cells 2 and 3, with
       cells 1 and 4 blank). Fix: in the same scope, hide the pseudos with
       `display:none; content:none;`.

       This check fails if `theme.json` `styles.css` contains a rule that
       sets `display:grid` on a selector ending in `ul.products` (or
       `.products`) and the same scope does not also nullify both
       `::before` and `::after` on that same selector.

    2. WC LOOP WIDTH LEAK
       WC sets `.woocommerce ul.products[class*=columns-] li.product
       { width: 22.05% / 30.79% / 48% / 100% }` based on the `.columns-N`
       class. Inside a grid container those percentages stop the LIs filling
       their cells. Fix: a scoped rule resetting `width:100%` on
       `li.product:nth-child(n)` (the `:nth-child(n)` is needed to win
       specificity over WC's `:nth-child(Nn)` margin-reset rules).

       This check fails if a `display:grid` rule on `ul.products` exists
       without an accompanying `li.product` width reset rule in the same
       theme.json `styles.css`.
    """
    r = Result("WooCommerce grid integration (clearfix + loop width)")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    css = ""
    styles = data.get("styles", {})
    if isinstance(styles, dict):
        css = styles.get("css", "") or ""
    if not css:
        return r  # Nothing to check.

    # Find every CSS rule of the form `<selectors> { <body> }`.
    # We deliberately keep this regex simple — theme.json `styles.css` is
    # never deeply nested (no @media, no nesting) by project convention.
    rule_re = re.compile(r"([^{};]+)\{([^{}]*)\}")

    grid_rules: list[tuple[str, str]] = []  # (selectors, body)
    pseudo_rules: list[str] = []  # selector strings
    width_reset_rules: list[str] = []  # selector strings

    for m in rule_re.finditer(css):
        selectors = m.group(1).strip()
        body = m.group(2)
        # Normalize whitespace inside the body for substring checks.
        body_norm = re.sub(r"\s+", "", body)
        sel_list = [s.strip() for s in selectors.split(",")]

        is_grid_on_products = "display:grid" in body_norm and any(
            re.search(r"(?:^|\s|\.)products(?:\s|$)|ul\.products(?:\s|$)", s) for s in sel_list
        )
        if is_grid_on_products:
            grid_rules.append((selectors, body_norm))

        is_pseudo_kill = (
            ("display:none" in body_norm or "content:none" in body_norm)
            and any("::before" in s or "::after" in s for s in sel_list)
            and any("ul.products" in s or "products" in s for s in sel_list)
        )
        if is_pseudo_kill:
            pseudo_rules.extend(sel_list)

        is_width_reset = "width:100%" in body_norm and any("li.product" in s for s in sel_list)
        if is_width_reset:
            width_reset_rules.extend(sel_list)

    if not grid_rules:
        return r  # No grid on ul.products → nothing to enforce.

    # For each grid rule we found, require both a pseudo-element nullifier
    # and a width-reset rule whose scope overlaps. We use a permissive
    # "scope tag" derived from the selector (.upsells / .related / .shop
    # etc.) so that a grid scoped to .upsells must be paired with pseudo-
    # kills and width-resets that also mention .upsells.
    scope_re = re.compile(r"\.(upsells|related|shop|products|cross-sells|cart-cross-sells)")

    for selectors, _body in grid_rules:
        scopes = set(scope_re.findall(selectors))
        if not scopes:
            scopes = {"products"}

        for scope in scopes:
            has_before = any(f".{scope}" in s and "::before" in s for s in pseudo_rules)
            has_after = any(f".{scope}" in s and "::after" in s for s in pseudo_rules)
            has_width_reset = any(f".{scope}" in s and "li.product" in s for s in width_reset_rules)

            if not (has_before and has_after):
                r.fail(
                    f"grid on `ul.products` scoped to `.{scope}` "
                    "without `::before` AND `::after { display:none; content:none; }` "
                    "in the same scope — WC clearfix pseudos will consume grid cells "
                    f"(rule selectors: {selectors[:120]}{'…' if len(selectors) > 120 else ''})"
                )
            if not has_width_reset:
                r.fail(
                    f"grid on `ul.products` scoped to `.{scope}` "
                    "without `li.product { width:100% }` reset — WC loop widths "
                    "(22%/30%/48%) will leak into grid cells "
                    f"(rule selectors: {selectors[:120]}{'…' if len(selectors) > 120 else ''})"
                )

    return r


def check_no_hardcoded_dimensions() -> Result:
    """Scan templates/parts/patterns for hardcoded px/em/rem values in style=
    attributes, excluding common known-safe values.

    Allowlist:
      - 1px, 2px  (borders)
      - min-height  (Cover block canonical attribute output)
      - flex-basis  (Column block width attribute output — no token equivalent)
      - width/height on block wrappers (structural layout, not design token)
    """
    r = Result("No hardcoded dimensions in templates/parts/patterns style= attributes")
    # Match pixel/em/rem literals inside style="..." that are NOT in the allowlist.
    dim_re = re.compile(r'(?<![a-z-])(\d+(?:\.\d+)?)(px|em|rem)(?!["\w])', re.IGNORECASE)
    allowed_values = {"1px", "2px"}
    # CSS properties whose hardcoded values are structurally generated (not design tokens).
    allowed_props = {"min-height", "flex-basis", "width", "height", "max-width"}
    skip_dirs = {"templates/", "parts/", "patterns/"}
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            # Only inspect lines that contain a style= attribute.
            if 'style="' not in line and "style='" not in line:
                continue
            # Extract the style value(s) from the line.
            style_re = re.compile(r'style=["\']([^"\']*)["\']')
            for style_val in style_re.findall(line):
                for m in dim_re.finditer(style_val):
                    full = m.group(0)
                    if full in allowed_values:
                        continue
                    # Identify the CSS property name preceding this value.
                    # segment ends just before the number, so the last ';' delimiter
                    # separates the current declaration from prior ones.
                    segment = style_val[max(0, m.start() - 80) : m.start()]
                    last_decl = segment.rsplit(";", 1)[-1]
                    # The declaration is "property:" — take the part before the colon.
                    prop = last_decl.split(":")[0].strip()
                    if any(p in prop for p in allowed_props):
                        continue
                    r.fail(f"{rel}:{lineno}: hardcoded '{full}' in style attribute")
                    break  # one failure per line is enough
    return r


def check_block_attrs_use_tokens() -> Result:
    """Fail if block attribute JSON in templates/parts/patterns uses hardcoded
    layout widths or aspect ratios instead of the SSOT tokens.

    What this catches:
      - "contentSize":"780px"     -> drop the override (use settings.layout.contentSize)
      - "contentSize":"1440px"    -> use "var(--wp--style--global--wide-size)"
      - "contentSize":"<other>px" -> use "var(--wp--custom--layout--<slug>)"
      - "aspectRatio":"4/3"       -> use "var(--wp--custom--aspect-ratio--<slug>)"

    These all break the "edit one value in theme.json -> ripple everywhere" rule.

    NOTE: cover `minHeight` is intentionally NOT checked here. The cover block's
    save() function reads `minHeight` + `minHeightUnit` from the JSON attrs and
    emits the inline `min-height` itself; using a CSS-var-only inline style with
    no JSON attr produces invalid block markup that the editor silently rewrites
    on load (caught by `bin/blocks-validator/`).
    """
    r = Result("Block attributes use design tokens (no hardcoded layout widths, aspect ratios)")
    skip_dirs = {"templates/", "parts/", "patterns/"}
    content_size_re = re.compile(r'"contentSize"\s*:\s*"(\d[\w./%]+)"')
    aspect_ratio_re = re.compile(r'"aspectRatio"\s*:\s*"([\d/.]+)"')
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in content_size_re.finditer(line):
                r.fail(
                    f'{rel}:{lineno}: hardcoded contentSize "{m.group(1)}". '
                    f"Drop the override (uses settings.layout.contentSize), or use "
                    f'"var(--wp--style--global--wide-size)" / "var(--wp--custom--layout--<slug>)".'
                )
            for m in aspect_ratio_re.finditer(line):
                r.fail(
                    f'{rel}:{lineno}: hardcoded aspectRatio "{m.group(1)}". '
                    f'Use "var(--wp--custom--aspect-ratio--<slug>)".'
                )
    return r


def check_block_markup_anti_patterns() -> Result:
    """Fail if any pattern/template/part contains a known block-markup anti-pattern
    that the WordPress editor will flag as 'invalid content' (or silently auto-
    upgrade on load).

    These are the cheap-to-detect invariants. The expensive editor-parity diff
    lives in `bin/blocks-validator/check-blocks.mjs` (run via
    `check_blocks_validator()` below); this function exists so that a typical
    edit gets quick feedback without requiring Node.js.

    Invariants enforced (one fail line per offender):
      1. core/group: when the JSON declares `border.color` (preset or raw),
         the rendered <div> MUST carry the `has-border-color` class. Save()
         emits it and the validator rejects the block otherwise.
      2. core/paragraph: the class list MUST NOT include legacy
         `wo-empty__*` markers -- core/paragraph doesn't support a custom
         className via that selector and save() drops them, breaking the
         round-trip.
      3. core/button: `box-shadow` belongs on the inner `<a class=
         "wp-block-button__link wp-element-button">`, NEVER on the outer
         `<div class="wp-block-button">`. Save() places it on the link.
      4. core/accordion: the wrapper `<div class="wp-block-accordion">`
         MUST carry `role="group"`. Save() emits it; the editor silently
         rewrites the markup on first load if it's missing, which means
         the next edit-and-save round-trip will produce a noisy diff.
         Caught by `@wordpress/block-library` 9.44+; we lint it here so
         contributors don't need to wait for the Node validator.
      5. <button> in patterns/templates/parts MUST declare an explicit
         `type=` attribute. Without it, the HTML default is `submit`,
         which inside any `<form>` (cart, checkout, mini-cart) silently
         submits the form on click. Belt-and-braces against the editor
         silently injecting `type="button"` on save() and the next
         round-trip looking like a "fix" in CI.
      6. core/heading: when the JSON declares `fontSize` (top-level
         shortcut) or `style.typography.{fontFamily,fontWeight,fontStyle,
         letterSpacing,lineHeight,textTransform,fontSize}`, the rendered
         `<h*>` tag MUST carry the matching `has-<slug>-font-size` /
         `has-<slug>-font-family` class and the matching CSS property
         in its inline `style` attribute. Without the class/style, the
         editor's `parse()` falls through to the deprecation pipeline
         which silently rescues the markup at editor load -- but the
         FRONT-END serves the bare markup, so the heading falls through
         to `styles.elements.h2.fontSize` defaults (typically 4-7.5rem
         display sizes) and renders nothing like the design intent.
         This is the exact regression that shipped chunky 100px display
         headings in the aero/lysholm/selvedge footers; fast-path here
         so future generators can't recreate it without tripping the
         pre-commit hook in <0.1s.
      7. core/post-template: when `layout.type == "grid"`, the JSON
         MUST set EITHER `columnCount` (fixed N columns: produces
         `repeat(N, minmax(0, 1fr))`) OR `minimumColumnWidth` (responsive:
         produces `repeat(auto-fill, minmax(<width>, 1fr))`), NEVER
         both. With both set, WordPress picks the `auto-fill` algorithm
         and ignores `columnCount`, so a `{"columnCount":3,
         "minimumColumnWidth":"18rem"}` on a 1440px wide-size container
         renders as 4-5 column tracks with only 3 populated -- cards
         compress to the minimum width and a void appears beside them.
         This is the exact regression that shipped a "From the
         Workbench" section with cards squished into 60% of the width
         in selvedge/aero/lysholm/obel front-pages. Fast-path here so
         future generators can't recreate it.
    """
    r = Result(
        "Block markup matches save() output "
        "(group classes, button shadow, paragraph classes, accordion role, button type, heading typography, post-template grid, wide-query content-size squeeze)"
    )

    skip_dirs = {"templates/", "parts/", "patterns/"}
    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        files.append(path)

    # --- Invariant 1: core/group with border.color preset must add has-border-color
    group_open_re = re.compile(
        r'<!--\s*wp:group\s+(\{[^>]*?\})\s*-->\s*\n\s*(<(?:div|main|section|aside|nav|header|footer|article|figure)\s+[^>]*class="[^"]*?wp-block-group[^"]*?"[^>]*>)'
    )

    # --- Invariant 3: core/button shadow on outer wrapper
    button_outer_shadow_re = re.compile(
        r'<div\s+class="wp-block-button[^"]*"[^>]*style="[^"]*box-shadow:'
    )

    # NB: We deliberately do NOT lint `woocommerce/product-price` for self-close
    # form. The block ships both render paths and the editor-parity validator
    # stubs WC blocks anyway -- the regex is too coarse to disambiguate
    # standalone uses from query-loop descendants reliably.

    # NB: We deliberately do NOT lint `core/quote` for a JSON `citation` attribute.
    # Save() preserves the inner `<cite>` element inside `<blockquote>` verbatim,
    # so the editor-parity validator round-trips both forms cleanly.

    # NB: We deliberately do NOT lint `core/heading` for a `content` attribute
    # in JSON. Save() round-trips it cleanly when it matches the inner HTML
    # (verified by the editor-parity validator across 2700+ blocks), and a
    # naive regex check produces a flood of false positives.

    # --- Invariant 2: core/paragraph anti-patterns
    para_block_re = re.compile(
        r"<!--\s*wp:paragraph\s+(\{[^>]*?\})\s*-->\s*\n\s*(<p\s+[^>]*>)",
        re.MULTILINE,
    )

    # --- Invariant 4: core/accordion wrapper requires role="group".
    # Match `<!-- wp:accordion ... -->` followed by the next block-element
    # opener whose class list contains `wp-block-accordion` (but NOT one of
    # the child variants like `wp-block-accordion-item`). Allow attribute
    # noise before the class= so themes can add anchor IDs etc.
    accordion_open_re = re.compile(
        r"<!--\s*wp:accordion(?:\s+\{[^}]*\})?\s*-->\s*\n\s*"
        r'(<(?:div|section)\s+[^>]*class="[^"]*\bwp-block-accordion(?!-)[^"]*"[^>]*>)'
    )

    # --- Invariant 5: <button> tags must declare an explicit `type=`.
    # Lookahead: any opening `<button` not immediately followed (within the
    # tag) by a `type=` attribute. We anchor on `<button` followed by either
    # whitespace+attrs or `>`; the `(?![^>]*\stype=)` ensures no `type=`
    # appears before the closing `>`. Self-closing variants are not used in
    # block markup, so we don't bother matching them.
    button_no_type_re = re.compile(r"<button(?![^>]*\stype=)(?:\s[^>]*)?>")

    # --- Invariant 6: core/heading typography JSON ↔ markup coherence.
    # Match `<!-- wp:heading {...} -->` followed by an `<h1>`–`<h6>` tag.
    # We do not anchor on a newline-only join because some patterns put
    # the opening comment and the tag on the same line.
    heading_block_re = re.compile(
        r"<!--\s*wp:heading\s+(\{[^>]*?\})\s*-->\s*\n?\s*(<h[1-6]\b[^>]*>)",
        re.MULTILINE,
    )
    # Map JSON style.typography.<key> → CSS property. Keep `fontSize` last
    # so the message is consistent with how save() orders the inline style.
    HEADING_TYPO_PROPS = (
        ("fontFamily", "font-family"),
        ("fontStyle", "font-style"),
        ("fontWeight", "font-weight"),
        ("fontSize", "font-size"),
        ("letterSpacing", "letter-spacing"),
        ("lineHeight", "line-height"),
        ("textTransform", "text-transform"),
    )

    # --- Invariant 7: post/term-template grid layout must pick ONE
    # column-sizing algorithm. Matches every block whose name ends in
    # `-template` (`wp:post-template`, `wp:term-template`, both share
    # WP's grid-layout engine) and inspects the JSON for the layout
    # block + the two column-sizing keys. Failure logic lives in the
    # per-file loop so the line number is right.
    #
    # The selvedge front-page incident hit BOTH variants on a single
    # template: line 84 (`wp:term-template`, "Shop by Trade") and
    # line 186 (`wp:post-template`, "From the Workbench"). The
    # post-template-only regex would have caught only one.
    post_template_re = re.compile(
        r"<!--\s*wp:((?:[a-z0-9-]+/)?(?:post|term)-template)\s+(\{[^>]*?\})\s*-->",
        re.MULTILINE,
    )

    # --- Invariant 8: wp:query with align=wide|full whose inner layout is
    # `constrained` (without an explicit `contentSize` override) silently
    # squeezes any direct child wp:post-template back to the THEME'S default
    # contentSize -- typically 780px even when the query block itself is
    # painted at 1440px wide. Result: a 3-column grid post-template renders as
    # three ~245px cards stuffed into the left half of the section, with a
    # huge empty void on the right.
    #
    # Past incident: obel/templates/front-page.html "From the journal" section
    # (and the same pattern on every archive/home/category/tag/taxonomy/date/
    # author template across all 5 themes -- 38 files) painted the post grid
    # at content-size, not wide-size, even though `align:"wide"` was set.
    # The user's screenshot showed three small cards in the left column with
    # a giant empty block on the right.
    #
    # Canonical fix: change the wp:query inner `layout` to `{"type":"default"}`
    # so the post-template fills its parent's actual rendered width.
    # Alternative: keep `constrained` but explicitly set
    # `"contentSize":"var(--wp--style--global--wide-size)"`.
    #
    # We only flag the combination that bites: align=wide|full + constrained
    # layout WITHOUT a contentSize override + a direct-child post-template
    # whose own layout is grid. Single-column post lists genuinely want the
    # narrower content-size, so we don't touch those.
    query_open_re = re.compile(
        r"<!--\s*wp:query\s+(\{[^>]*?\})\s*-->",
        re.MULTILINE,
    )
    query_close_re = re.compile(r"<!--\s*/wp:query\s*-->")

    def _slug_to_class_token(slug: str) -> str:
        """Mirror @wordpress/blocks save()'s slug → kebab-case conversion.
        WP inserts a hyphen at every digit↔letter boundary so a JSON
        `fontSize:"4xl"` (or `"4-xl"`) becomes `has-4-xl-font-size` in
        the rendered class list. Without this normalisation the check
        false-positives on every numeric size preset.
        """
        # digit followed by letter, or letter followed by digit
        s = re.sub(r"(\d)([A-Za-z])", r"\1-\2", slug)
        s = re.sub(r"([A-Za-z])(\d)", r"\1-\2", s)
        # collapse any accidental double hyphens (slug already had a `-`)
        return re.sub(r"-+", "-", s)

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        # Invariant 1: group + top-level border.color + has-border-color.
        # Save() only emits `has-border-color` when border.color is set as a
        # single string at the top level of `border`. Per-side borders
        # (`border.top.color`, etc.) are styled inline and do NOT add the class.
        for m in group_open_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            if not re.search(r'"border"\s*:\s*\{[^{}]*?"color"\s*:\s*"', json_part):
                continue
            if "has-border-color" in tag:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/group declares border.color but rendered <{tag.split()[0][1:]}> "
                f"is missing the `has-border-color` class. Add it to the class list."
            )

        # Invariant 2: paragraph legacy wo-empty__ class.
        # core/paragraph save() drops unknown classes from the rendered
        # class list UNLESS they were declared in the `className` block
        # attribute -- the editor uses that attribute as the canonical
        # custom class store and re-emits it on every save. So a
        # `wp:paragraph {"className":"wo-empty__eyebrow"}` keeps the
        # class on round-trip (the cart-page.php pattern relies on this
        # for empty-cart-block CSS hooks); only raw classes injected
        # straight into the `<p>` tag without a matching className attr
        # get silently scrubbed by the editor.
        for m in para_block_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            if "wo-empty__" not in tag:
                continue
            classname_attr = re.search(r'"className"\s*:\s*"([^"]*)"', json_part)
            preserved = set()
            if classname_attr:
                preserved = {c for c in classname_attr.group(1).split() if c}
            tag_classes = re.search(r'\sclass="([^"]*)"', tag)
            tag_class_set = set(tag_classes.group(1).split()) if tag_classes else set()
            unsupported = {
                c for c in tag_class_set if c.startswith("wo-empty__") and c not in preserved
            }
            if not unsupported:
                continue
            lineno = text.count("\n", 0, m.start(2)) + 1
            r.fail(
                f"{rel}:{lineno}: core/paragraph carries legacy `wo-empty__*` "
                f"class(es) {sorted(unsupported)} that are NOT mirrored in "
                f"the block's `className` attribute. core/paragraph save() "
                f"only preserves classes declared via `className`; raw "
                f"classes inlined into `<p>` are dropped on the next editor "
                f'round-trip. Add them to `"className":"..."` in the '
                f"`wp:paragraph` JSON, or remove them."
            )

        # Invariant 3: button shadow on outer wrapper
        for m in button_outer_shadow_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/button has `box-shadow` on the outer "
                f"`.wp-block-button` div. Move it to the inner `a.wp-block-button__link` -- "
                f"that's where save() places it."
            )

        # Invariant 4: accordion wrapper must declare role="group".
        for m in accordion_open_re.finditer(text):
            tag = m.group(1)
            if re.search(r'\brole\s*=\s*"group"', tag):
                continue
            lineno = text.count("\n", 0, m.start(1)) + 1
            r.fail(
                f'{rel}:{lineno}: core/accordion wrapper is missing `role="group"`. '
                f"Save() emits it; without it the editor will silently rewrite the "
                f"markup on first load and the next round-trip will look like a regression."
            )

        # Invariant 5: any <button> in pattern/template/part markup must
        # carry an explicit `type=` attribute. Default-`submit` buttons
        # inside the cart, mini-cart, and checkout forms detonate on click.
        for m in button_no_type_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: <button> is missing an explicit `type=` attribute. "
                f'Add `type="button"` (or `type="submit"` if it really is a form '
                f"submit) -- the HTML default is `submit`, which silently posts any "
                f"surrounding <form> on click."
            )

        # Invariant 6: core/heading typography JSON ↔ markup coherence.
        for m in heading_block_re.finditer(text):
            json_part, tag = m.group(1), m.group(2)
            tag_classes_m = re.search(r'\sclass\s*=\s*"([^"]*)"', tag)
            tag_classes = set(tag_classes_m.group(1).split()) if tag_classes_m else set()
            tag_style_m = re.search(r'\sstyle\s*=\s*"([^"]*)"', tag)
            tag_style = tag_style_m.group(1) if tag_style_m else ""
            tag_style_props = {
                p.split(":", 1)[0].strip().lower() for p in tag_style.split(";") if ":" in p
            }
            missing: list[str] = []

            # 6a. Top-level `fontSize: "<slug>"` shortcut → has-<kebab-slug>-font-size class.
            font_size_short = re.search(r'(?<![\w])"fontSize"\s*:\s*"([A-Za-z0-9_-]+)"', json_part)
            if font_size_short and not re.search(
                r'(?<![\w])"style"\s*:\s*\{[^{}]*?"typography"\s*:\s*\{[^{}]*?"fontSize"',
                json_part,
            ):
                slug = font_size_short.group(1)
                expected = f"has-{_slug_to_class_token(slug)}-font-size"
                if expected not in tag_classes:
                    missing.append(f'class `{expected}` (from JSON fontSize:"{slug}")')

            # 6b. Top-level `fontFamily: "<slug>"` shortcut → has-<kebab-slug>-font-family class.
            # Skip values that look like CSS variables / preset references --
            # those go in `style.typography.fontFamily`, not the shortcut.
            font_family_short = re.search(
                r'(?<![\w])"fontFamily"\s*:\s*"([A-Za-z0-9_-]+)"', json_part
            )
            if font_family_short:
                slug = font_family_short.group(1)
                expected = f"has-{_slug_to_class_token(slug)}-font-family"
                if expected not in tag_classes:
                    missing.append(f'class `{expected}` (from JSON fontFamily:"{slug}")')

            # 6c. style.typography.<prop> → matching CSS property in inline style.
            typo_block = re.search(
                r'"style"\s*:\s*\{[^{}]*?"typography"\s*:\s*(\{[^{}]*?\})',
                json_part,
            )
            if typo_block:
                typo_json = typo_block.group(1)
                for json_key, css_prop in HEADING_TYPO_PROPS:
                    if not re.search(rf'(?<![\w])"{json_key}"\s*:\s*"', typo_json):
                        continue
                    if css_prop not in tag_style_props:
                        missing.append(
                            f"inline `style` property `{css_prop}` "
                            f"(from JSON style.typography.{json_key})"
                        )

            if missing:
                lineno = text.count("\n", 0, m.start(2)) + 1
                tag_name = re.match(r"<(h[1-6])", tag).group(1)
                r.fail(
                    f"{rel}:{lineno}: core/heading <{tag_name}> is missing "
                    f"{len(missing)} attribute(s) the JSON declared: "
                    + "; ".join(missing)
                    + ". Without these, the front-end serves bare markup that "
                    + f"falls through to `styles.elements.{tag_name}` defaults "
                    + "(typically display-size headings). The editor's deprecation "
                    + "pipeline silently rewrites the markup on load so the bug "
                    + "only surfaces in production. Mirror the JSON into the "
                    + "rendered tag (add the class(es) and the inline style "
                    + "properties shown above)."
                )

        # Invariant 7: post/term-template grid layout must pick ONE sizing algo.
        for m in post_template_re.finditer(text):
            block_name, json_part = m.group(1), m.group(2)
            # Only evaluate when layout.type is grid; flex / stack templates
            # don't use these keys.
            if not re.search(r'"layout"\s*:\s*\{[^{}]*?"type"\s*:\s*"grid"', json_part):
                continue
            has_column_count = bool(re.search(r'(?<![\w])"columnCount"\s*:\s*\d+', json_part))
            # `minimumColumnWidth` is "set" only when its value is a non-empty
            # string. `null` and `""` mean "unset" -- the canonical pattern
            # used by every working post/term-template in this repo.
            min_col_width = re.search(r'(?<![\w])"minimumColumnWidth"\s*:\s*"([^"]+)"', json_part)
            if has_column_count and min_col_width:
                lineno = text.count("\n", 0, m.start()) + 1
                r.fail(
                    f"{rel}:{lineno}: wp:{block_name} has BOTH `columnCount` "
                    f'and `minimumColumnWidth: "{min_col_width.group(1)}"`. '
                    f"WordPress's grid layout picks the `auto-fill` algorithm "
                    f"when `minimumColumnWidth` is set and ignores `columnCount`, "
                    f"so the rendered grid creates as many tracks as fit at the "
                    f"minimum width -- only the first N populate, leaving an "
                    f"empty void beside them at wide viewports. Pick one: set "
                    f'`"minimumColumnWidth":null` for fixed N columns, or '
                    f"drop `columnCount` for a responsive grid. The canonical "
                    f'pattern across this repo is `"columnCount":N,'
                    f'"minimumColumnWidth":null`.'
                )

        # Invariant 8: wide/full wp:query + constrained layout (default
        # contentSize) + grid post-template inside == post grid silently
        # squeezed to content-size width.
        for m in query_open_re.finditer(text):
            qjson = m.group(1)
            if not re.search(r'"align"\s*:\s*"(wide|full)"', qjson):
                continue
            layout_m = re.search(r'"layout"\s*:\s*(\{[^{}]*\})', qjson)
            if not layout_m:
                continue
            layout_json = layout_m.group(1)
            if not re.search(r'"type"\s*:\s*"constrained"', layout_json):
                continue
            if "contentSize" in layout_json:
                # Author opted in to a specific contentSize override; trust it.
                continue
            # Find matching close (templates don't nest wp:query, but be safe
            # by taking the next /wp:query after the opener).
            close_m = query_close_re.search(text, m.end())
            inner = text[m.end() : close_m.start()] if close_m else text[m.end() :]
            grid_pt = False
            grid_lineno = None
            for pm in post_template_re.finditer(inner):
                if "post-template" not in pm.group(1):
                    continue
                if re.search(r'"layout"\s*:\s*\{[^{}]*?"type"\s*:\s*"grid"', pm.group(2)):
                    grid_pt = True
                    grid_lineno = text.count("\n", 0, m.end() + pm.start()) + 1
                    break
            if not grid_pt:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: wp:query is `align:wide|full` with inner "
                f'`layout:{{"type":"constrained"}}` (no `contentSize` '
                f"override) AND contains a grid wp:post-template (line "
                f"{grid_lineno}). The constrained layout falls back to the "
                f"theme's DEFAULT contentSize (typically 780px), so the "
                f"post grid is squeezed to content-size width even though "
                f"the query block itself is painted at wide-size. The N "
                f"columns then stack into the left half of the section "
                f"with a void on the right. Fix: change the wp:query "
                f'layout to `{{"type":"default"}}` so the post-template '
                f"fills its parent's actual width, or set an explicit "
                f'`"contentSize":"var(--wp--style--global--wide-size)"` '
                f"on the constrained layout."
            )

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) checked")
    return r


def check_blocks_validator() -> Result:
    """Run the Node.js editor-parity validator (`bin/blocks-validator/`) and
    surface any block that the WP editor would flag or auto-upgrade on load.

    This is the canonical answer to "would the editor accept this markup?".
    The Python anti-pattern check above catches the cheap stuff fast; this
    one boots @wordpress/blocks under JSDOM and runs the real `parse()` +
    `validateBlock()` pipeline, so it finds the long tail (subtle class
    ordering, deprecated attribute shapes, etc.) too.

    Skipped (not failed) if Node.js or the validator's `node_modules/` are
    missing -- the contributor doc explains how to set them up.
    """
    r = Result("Block markup passes the @wordpress/blocks editor-parity validator")
    if shutil.which("node") is None:
        r.skip("`node` not on PATH; install Node 18+ to run editor-parity validation.")
        return r
    validator_dir = MONOREPO_ROOT / "bin" / "blocks-validator"
    if not (validator_dir / "node_modules").exists():
        r.skip(
            f"`{validator_dir}/node_modules/` missing. "
            f"Run `cd {validator_dir} && npm install` once to enable this check."
        )
        return r
    script = validator_dir / "check-blocks.mjs"
    try:
        proc = subprocess.run(
            ["node", str(script), str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        r.fail("blocks-validator timed out after 120s")
        return r
    if proc.returncode == 0:
        # Last line is the summary, e.g. "✓ Validated 569 blocks across 45 file(s) ..."
        last = (proc.stderr.strip().splitlines() or [""])[-1]
        if last:
            r.details.append(last)
        return r
    # Non-zero exit: extract the per-block headers ("─── core/group in <file>") and
    # surface them as fail lines. The full diff stays in stderr for debugging but
    # would drown the summary table.
    headers = [line.strip() for line in proc.stderr.splitlines() if line.startswith("─── ")]
    if not headers:
        # Surface the raw stderr if we can't parse it.
        r.fail(proc.stderr.strip()[:1000])
        return r
    for h in headers:
        # Strip the leading "─── " for the fail-line format.
        r.fail(h[4:])
    return r


def check_bordered_group_text_has_explicit_color() -> Result:
    """Fail when a `wp:group` declares a border/background via block attrs
    AND contains immediate text children (paragraph/list/heading) that
    DON'T declare a `textColor` attribute.

    Why this bites in practice
    --------------------------
    A `wp:group` with
        {
          "style": {
            "border": { "top": { "color": "var:preset|color|contrast", "width": "1px" } },
            "spacing": { ... }
          },
          "backgroundColor": "surface"
        }
    serializes to
        <div class="wp-block-group has-surface-background-color
                    has-background has-border-color"
             style="border-top-color:var(--wp--preset--color--contrast);
                    border-top-width:1px;">
    WordPress's block-library CSS emits a `.has-border-color { color:
    inherit }` fallback, and the theme's ambient paragraph `color`
    inherits down into the group. When the designer meant the paragraph
    to sit on `surface` in `secondary` (a mid-tone), but the theme's
    ambient color is `contrast` (the darkest token), the paragraph
    paints in `contrast` — and for small/thin serif copy that slides
    below the 4.5:1 AA floor on a surface-colored card. This is the
    EXACT pattern the Basalt merge-prep session spent three hours
    fixing by adding `textColor:"secondary"` to every child paragraph
    and list in the materials row and the footer stamp.

    The static fix is equally cheap and deterministic: when a `wp:group`
    carries a border/background decoration AND its immediate text
    children lack an explicit `textColor`, fail the gate. Authors
    either set `textColor` explicitly (which also makes the intent
    legible in the editor) or move the border into `theme.json`
    `styles.css` where the cascade risk is scoped and testable.

    Scope
    -----
    * Runs on `templates/`, `parts/`, and `patterns/` `.html` files.
    * "Text children" = `wp:paragraph`, `wp:heading`, `wp:list` that
      appear as direct descendants of the bordered/backgrounded
      `wp:group` (not nested inside an inner group — the inner group
      owns its own decoration and contrast story).
    * A child is considered safe if its JSON contains ANY of:
        - `textColor` (top-level attribute)
        - `style.color.text` (inline custom color)
        - a `className` starting with `has-` that ends in `-color`
          (e.g. `has-secondary-color` placed manually).
    * A child is also considered safe if `textColor: contrast` or
      `textColor: secondary` (or any preset) is set explicitly — the
      presence of the attribute is the proof that the author thought
      about the cascade.

    False-positive surface
    ----------------------
    Groups that carry a border/background decoration but whose ONLY
    text children are inside further `wp:group`/`wp:columns` wrappers
    (which own their own paint) are fine — we only flag direct text
    children, not transitively. That matches how the cascade bites in
    practice: the inner wrapper interposes a new `color` stacking
    context and the designer is then forced to declare textColor on
    it anyway.
    """
    r = Result("Bordered/backgrounded wp:group children declare an explicit textColor")

    skip_dirs = {"templates/", "parts/", "patterns/"}
    files: list[Path] = []
    for path in iter_files((".html",)):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    # --- Shape detectors ---
    # We parse block-by-block using a tiny, line-numbered walker so we
    # can emit precise error messages and avoid the hairy nested-block
    # gymnastics a pure regex would require.
    block_open_re = re.compile(
        r"<!--\s*wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)"
        r"(?:\s+(\{[^<>]*?\}))?\s*(/?)-->",
    )
    block_close_re = re.compile(
        r"<!--\s*/wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)\s*-->",
    )

    # backgroundColor values that equal the theme's ambient page
    # background. Children of such groups inherit text color from the
    # page normally and the contrast math is unchanged. Don't flag.
    AMBIENT_BG_TOKENS = {"base"}

    def _has_decoration(json_text: str) -> tuple[bool, str]:
        """Return (decorated?, reason). A group is 'decorated' for the
        purposes of THIS check only when it changes the text-contrast
        context for its children -- i.e. it paints a non-ambient
        background, a gradient, or a background image. A border alone
        doesn't change the contrast context (children still render on
        the page's ambient background), so border-only groups are NOT
        flagged; that was the false-positive pattern observed on
        obel/templates/order-confirmation.html (a hairline-bordered
        "next steps" section with no backgroundColor).

        Returns the first reason hit so the error message names the
        attr that triggered the check.
        """
        bg = re.search(r'"backgroundColor"\s*:\s*"([^"]+)"', json_text)
        if bg and bg.group(1) not in AMBIENT_BG_TOKENS:
            return True, f"backgroundColor:{bg.group(1)}"
        if re.search(r'"gradient"\s*:\s*"', json_text):
            return True, "gradient"
        # A `style.background` object only counts when it sets an image
        # or gradient -- raw `style.background.backgroundColor` is the
        # same story as the top-level `backgroundColor` above, already
        # handled.
        if re.search(r'"background"\s*:\s*\{[^{}]*?"backgroundImage"\s*:', json_text):
            return True, "style.background.backgroundImage"
        if re.search(r'"background"\s*:\s*\{[^{}]*?"gradient"\s*:', json_text):
            return True, "style.background.gradient"
        return False, ""

    _SAFE_TEXT_COLOR_RE = re.compile(
        r'("textColor"\s*:\s*"[^"]+"'
        r'|"color"\s*:\s*\{[^{}]*?"text"\s*:\s*"[^"]+"\}'
        r'|"className"\s*:\s*"[^"]*\bhas-[a-z0-9-]+-color\b[^"]*")'
    )

    TEXT_BLOCK_NAMES = {"paragraph", "heading", "list", "list-item", "quote"}

    def _scan_children(
        text: str,
        outer_end: int,
        outer_close: int,
        outer_json: str,
    ) -> list[tuple[int, str, str]]:
        """Return list of (lineno, block_name, reason) for every
        DIRECT text-block child of the outer group that lacks an
        explicit textColor. `outer_end` is the byte offset of the
        group's opening `-->`; `outer_close` is the offset of its
        closing `<!-- /wp:group -->`.
        """
        findings: list[tuple[int, str, str]] = []
        pos = outer_end
        depth = 0  # depth of nested block openings below the outer group
        while pos < outer_close:
            m_open = block_open_re.search(text, pos, outer_close)
            m_close = block_close_re.search(text, pos, outer_close)
            if m_open is None and m_close is None:
                break
            # Pick whichever comes first
            if m_open is not None and (m_close is None or m_open.start() < m_close.start()):
                name = m_open.group(1)
                block_json = m_open.group(2) or ""
                self_closing = m_open.group(3) == "/"
                is_direct_child = depth == 0
                # Short-names: "core/paragraph" -> "paragraph"
                short = name.split("/")[-1]
                if (
                    is_direct_child
                    and short in TEXT_BLOCK_NAMES
                    and not _SAFE_TEXT_COLOR_RE.search(block_json)
                ):
                    lineno = text.count("\n", 0, m_open.start()) + 1
                    findings.append((lineno, name, "no textColor"))
                if not self_closing:
                    depth += 1
                pos = m_open.end()
            else:
                depth -= 1
                pos = m_close.end()  # type: ignore[union-attr]
                if depth < 0:
                    # Shouldn't happen -- defensive against mismatched
                    # block comments. Bail.
                    break
        return findings

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        # Walk every wp:group opener; match its closing tag; if the
        # opener is decorated and has plain text children, emit a
        # failure per child.
        pos = 0
        while True:
            m = block_open_re.search(text, pos)
            if m is None:
                break
            pos = m.end()
            name = m.group(1)
            block_json = m.group(2) or ""
            if m.group(3) == "/":
                continue  # self-closing (impossible for group, but safe)
            if name != "core/group" and name != "group":
                continue
            decorated, reason = _has_decoration(block_json)
            if not decorated:
                continue
            # If the DECORATED group itself declares a textColor (or a
            # custom style.color.text), children inherit that known
            # color via CSS cascade -- they don't need to declare their
            # own. That's the chonk/announcement-bar pattern
            # (`backgroundColor:contrast` + `textColor:accent`) which
            # is safe because `accent` inherits to the paragraph.
            if _SAFE_TEXT_COLOR_RE.search(block_json):
                continue
            # Find the matching closing tag. Depth counts only wp:group
            # opens/closes so nested non-group children don't confuse
            # the match.
            depth = 1
            scan = pos
            close_at: int | None = None
            while depth > 0:
                inner_open = re.search(r"<!--\s*wp:group(?:\s+\{[^<>]*?\})?\s*-->", text[scan:])
                inner_close = re.search(r"<!--\s*/wp:group\s*-->", text[scan:])
                if inner_close is None:
                    break
                if inner_open is not None and inner_open.start() < inner_close.start():
                    depth += 1
                    scan += inner_open.end()
                else:
                    depth -= 1
                    if depth == 0:
                        close_at = scan + inner_close.start()
                        break
                    scan += inner_close.end()
            if close_at is None:
                continue
            findings = _scan_children(text, pos, close_at, block_json)
            for lineno, child_name, why in findings:
                r.fail(
                    f"{rel}:{lineno}: {child_name} inside decorated "
                    f"wp:group (reason: {reason}) but has no `textColor` — "
                    f"paragraphs silently inherit the page's ambient color, "
                    f"which often produces a contrast failure on the "
                    f'group\'s new background. Add `textColor:"<preset>"` '
                    f"to the {child_name} block attrs, or move the "
                    f"decoration into `theme.json` styles.css where it "
                    f"can be tested against the cascade. "
                    f"({why})"
                )
    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) checked")
    return r


def check_block_text_contrast() -> Result:
    """Fail if any block (or the effective (text, bg) pair inherited
    from an ancestor) would paint text below the WCAG AA floor against
    its resolved background.

    Why this exists
    ---------------
    `check_bordered_group_text_has_explicit_color` catches the case
    where a decorated group has children with NO explicit textColor
    (the paragraph silently inherits). But the opposite failure mode
    — every child DECLARES a textColor, but the palette pair itself
    is simply illegible — is not caught anywhere upstream.

    Canonical case (the 2026-04-27 agave regression):

        <!-- wp:group {"backgroundColor":"accent","textColor":"base"} -->
          <!-- wp:paragraph {"className":"agave-wordmark-band__ledger"} -->
            <p class="agave-wordmark-band__ledger">...</p>
          <!-- /wp:paragraph -->
        <!-- /wp:group -->

    The group explicitly declares both textColor AND backgroundColor,
    so `check_bordered_group_text_has_explicit_color` passes (nothing
    inherits silently). But `base` (#f5efe6) on `accent` (#d87e3a) is
    only 2.64:1 — below even the 3:1 AA-Large floor, well below AA
    Normal's 4.5:1 — and the agave front-page ships with the whole
    ledger strap effectively invisible.

    Scope
    -----
    * Runs on `templates/`, `parts/`, and `patterns/` `.html` files.
    * We maintain a stack of `(textColor, backgroundColor)` inherited
      from ancestors. When a block declares a `textColor` and the
      ancestor stack supplies a `backgroundColor` (or the block itself
      declares one), we compute the contrast between the two.
    * A block is also checked when it declares BOTH textColor and
      backgroundColor on ITSELF — the parent doesn't need to supply
      anything.
    * We use `bin/_contrast.py` so the WCAG math matches
      `check_hover_state_legibility` and the `autofix-contrast.py`
      script that rewrites failing pairs.

    Threshold
    ---------
    We use `4.5:1` (WCAG AA Normal) rather than `3:1` (AA Large)
    because the blocks we're looking at (paragraph, list, quote) carry
    body text, not huge display type. Headings that DO qualify as
    "large" per WCAG are skipped — `core/heading` at h1/h2/h3 on a
    theme.json that sets them to >=24px bold or >=18.66px is
    AA-Large and only needs 3:1. We don't have cheap access to the
    resolved font size here, so we take the conservative path: apply
    AA Normal to every block and let `contrast-skip.json` (the
    per-theme escape hatch used by `check-contrast.py`) opt specific
    pairs out if the design legitimately needs a "large display" gap.
    """
    r = Result("Block textColor+backgroundColor pairs meet WCAG AA")

    from _contrast import contrast_ratio, load_palette

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    palette = load_palette(theme_json)
    if not palette:
        r.skip("no palette")
        return r

    skip_dirs = {"templates/", "parts/", "patterns/"}
    files: list[Path] = []
    for path in iter_files((".html",)):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    block_open_re = re.compile(
        r"<!--\s*wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)"
        r"(?:\s+(\{[^<>]*?\}))?\s*(/?)-->",
    )
    block_close_re = re.compile(
        r"<!--\s*/wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)\s*-->",
    )

    textcolor_re = re.compile(r'"textColor"\s*:\s*"([a-z0-9-]+)"')
    bgcolor_re = re.compile(r'"backgroundColor"\s*:\s*"([a-z0-9-]+)"')

    # AA Normal; see docstring for why we don't use 3:1.
    MIN_RATIO = 4.5

    # Per-theme allowlist of (textColor, backgroundColor) pairs that
    # the designer has explicitly signed off as AA-Large-only or
    # otherwise out-of-scope. Shares the file with check-contrast.py.
    skip_path = ROOT / "contrast-skip.json"
    skip_pairs: set[tuple[str, str]] = set()
    if skip_path.exists():
        try:
            entries = json.loads(skip_path.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict):
                        fg = e.get("fg")
                        bg = e.get("bg")
                        if isinstance(fg, str) and isinstance(bg, str):
                            skip_pairs.add((fg, bg))
        except json.JSONDecodeError:
            pass

    # Blocks that shouldn't be contrast-checked as text blocks
    # (spacers, image wrappers, etc.). Checking them fires false
    # positives on backgrounded image containers where the "text
    # color" is irrelevant (no text).
    NON_TEXT_BLOCKS = {
        "spacer",
        "image",
        "gallery",
        "cover",  # cover has its own overlay mechanics
        "embed",
        "video",
        "audio",
        "separator",
        "html",
    }

    failures_reported = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        # Stack of (text_slug, bg_slug) inherited from ancestors. When
        # a block declares its own, we push a new frame; when the
        # block closes, we pop. None entries mean "ancestor didn't
        # change this slot", so the child's resolved slug is the
        # nearest non-None entry in the stack.
        stack: list[tuple[str | None, str | None]] = []
        # Parallel stack tracking the block-name of each opener so
        # we can pop correctly on close (blocks always balance in
        # Gutenberg serialization, but defensive is cheap).
        name_stack: list[str] = []

        pos = 0
        while True:
            m_open = block_open_re.search(text, pos)
            m_close = block_close_re.search(text, pos)
            if m_open is None and m_close is None:
                break
            if m_open is not None and (m_close is None or m_open.start() < m_close.start()):
                name = m_open.group(1)
                block_json = m_open.group(2) or ""
                self_closing = m_open.group(3) == "/"
                short = name.split("/")[-1]

                t_match = textcolor_re.search(block_json)
                b_match = bgcolor_re.search(block_json)
                local_text = t_match.group(1) if t_match else None
                local_bg = b_match.group(1) if b_match else None

                # Resolve effective (text, bg) from the block + stack.
                eff_text = local_text
                eff_bg = local_bg
                if eff_text is None:
                    for st, _ in reversed(stack):
                        if st is not None:
                            eff_text = st
                            break
                if eff_bg is None:
                    for _, sb in reversed(stack):
                        if sb is not None:
                            eff_bg = sb
                            break

                # Only check blocks that are text-bearing AND have a
                # resolved (text, bg) pair. NON_TEXT blocks like
                # spacer/image are skipped.
                should_check = (
                    short not in NON_TEXT_BLOCKS
                    and eff_text is not None
                    and eff_bg is not None
                    and eff_text in palette
                    and eff_bg in palette
                    and (eff_text, eff_bg) not in skip_pairs
                )
                if should_check:
                    try:
                        ratio = contrast_ratio(palette[eff_text], palette[eff_bg])
                    except ValueError:
                        ratio = 0.0
                    if ratio < MIN_RATIO:
                        # Only report the block that introduced the
                        # failing pair (local_text or local_bg set) —
                        # child blocks that just inherit the same bad
                        # pair would spam the report.
                        introduces_local = bool(local_text or local_bg)
                        if introduces_local:
                            lineno = text.count("\n", 0, m_open.start()) + 1
                            failures_reported += 1
                            r.fail(
                                f"{rel}:{lineno}: block `{name}` resolves "
                                f"`textColor:{eff_text}` on "
                                f"`backgroundColor:{eff_bg}` = "
                                f"{ratio:.2f}:1 (need ≥{MIN_RATIO}:1). "
                                f"The block paints body text against a "
                                f"background color it can't legibly sit "
                                f"on. Run "
                                f"`python3 bin/autofix-contrast.py {ROOT.name}` "
                                f"to rewrite the offending textColor to "
                                f"the best-contrast palette slug, or "
                                f"pick a different backgroundColor."
                            )

                if not self_closing:
                    stack.append((local_text, local_bg))
                    name_stack.append(name)
                pos = m_open.end()
            else:
                # Closing tag — pop the matching frame.
                if stack and name_stack:
                    stack.pop()
                    name_stack.pop()
                pos = m_close.end()  # type: ignore[union-attr]

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) checked")
    elif failures_reported:
        r.details.append(
            f"{failures_reported} failing (textColor, backgroundColor) pair(s); "
            f"autofix available: `python3 bin/autofix-contrast.py {ROOT.name}`"
        )
    return r


def check_post_title_link_color_not_accent_on_low_contrast_base() -> Result:
    """Fail when linked post titles use `--accent` as the *resting* link text
    color while the palette's (accent, base) pair is below WCAG AA Normal
    (4.5:1).

    Canonical case: Ember journal listed linked post titles that painted
    terracotta accent on a cream base (~4.06:1) because the cascade did not
    reliably apply `core/post-title` theme.json link colors, tripping
    axe `color-contrast` on `/journal/`.

    Scope
    -----
    * If `accent` or `base` is missing from the palette, skip.
    * If contrast_ratio(accent, base) >= 4.5, pass without scanning — accent
      is legible enough for body-sized linked titles on the page ground.
    * Otherwise, reject:
        - `theme.json` → `styles.blocks["core/post-title"].elements.link.color.text`
          when it is `var(--wp--preset--color--accent)`.
        - Block markup → `wp:post-title` JSON where
          `style.elements.link.color.text` is `var(--wp--preset--color--accent)`.

    `:hover` link colors are intentionally ignored — transient states are
    covered by `check_hover_state_legibility`; this check targets the
    resting fill axe evaluates by default.
    """
    r = Result(
        "Resting post-title link text is not accent when accent-on-base "
        "fails WCAG AA Normal"
    )
    from _contrast import contrast_ratio, load_palette

    theme_json_path = ROOT / "theme.json"
    if not theme_json_path.is_file():
        r.skip("theme.json missing")
        return r
    palette = load_palette(theme_json_path)
    if not palette or "accent" not in palette or "base" not in palette:
        r.skip("palette missing accent/base")
        return r
    try:
        ratio = contrast_ratio(palette["accent"], palette["base"])
    except ValueError:
        r.skip("non-hex accent/base in palette")
        return r
    if ratio >= 4.5:
        r.details.append(
            f"accent-on-base {ratio:.2f}:1 ≥ 4.5:1 — no post-title accent restriction"
        )
        return r

    def _style_link_resting_text_is_accent(attrs: dict) -> bool:
        style = attrs.get("style")
        if not isinstance(style, dict):
            return False
        elements = style.get("elements")
        if not isinstance(elements, dict):
            return False
        link = elements.get("link")
        if not isinstance(link, dict):
            return False
        color = link.get("color")
        if not isinstance(color, dict):
            return False
        return color.get("text") == "var(--wp--preset--color--accent)"

    def _theme_json_post_title_accent_resting_link(theme: dict) -> bool:
        blocks = theme.get("styles", {}).get("blocks", {})
        if not isinstance(blocks, dict):
            return False
        pt = blocks.get("core/post-title")
        if not isinstance(pt, dict):
            return False
        elements = pt.get("elements")
        if not isinstance(elements, dict):
            return False
        link = elements.get("link")
        if not isinstance(link, dict):
            return False
        color = link.get("color")
        if not isinstance(color, dict):
            return False
        return color.get("text") == "var(--wp--preset--color--accent)"

    try:
        theme_data = json.loads(theme_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        r.skip("theme.json invalid JSON")
        return r

    if _theme_json_post_title_accent_resting_link(theme_data):
        r.fail(
            "theme.json styles.blocks[core/post-title].elements.link.color.text "
            f"uses --accent while accent-on-base is {ratio:.2f}:1 (< 4.5:1). "
            "Use --contrast for resting link text; reserve --accent for "
            "hover underline or other non-fill cues."
        )

    block_open_re = re.compile(
        r"<!--\s*wp:([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)?)"
        r"(?:\s+(\{[^<>]*?\}))?\s*(/?)-->",
    )
    skip_dirs = ("templates/", "parts/", "patterns/")
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(d) for d in skip_dirs):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in block_open_re.finditer(text):
            name = m.group(1)
            if name.split("/")[-1] != "post-title":
                continue
            raw = m.group(2)
            if not raw:
                continue
            try:
                attrs = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(attrs, dict):
                continue
            if _style_link_resting_text_is_accent(attrs):
                lineno = text.count("\n", 0, m.start()) + 1
                r.fail(
                    f"{rel}:{lineno}: wp:post-title sets style.elements.link.color."
                    f"text to --accent while accent-on-base is {ratio:.2f}:1 "
                    f"(< 4.5:1). Use --contrast for the link fill."
                )

    if r.passed:
        r.details.append(
            f"accent-on-base {ratio:.2f}:1 < 4.5:1; no resting accent on "
            f"post-title links"
        )
    return r


def check_no_fake_forms() -> Result:
    """Fail if any pattern/template/part contains a 'form-shaped' block that
    cannot actually submit anywhere.

    WordPress core ships **no** working email-capture or newsletter form
    block. The only form-ish blocks in core are:

      * `core/search`             -- submits `?s=…` to the home URL.
      * `core/login`              -- submits to `wp-login.php`.
      * `core/comments` (and kin) -- per-post comment form.

    Project history is full of "newsletter signup" patterns built out of
    `core/search` styled to look like an email field, or `core/html`
    blocks containing a raw `<form action="/?wo-newsletter=1">`. They
    look real but submit to nothing -- a visitor who types their email
    and clicks the button gets either a search-results page for their
    own address or a 404. That's worse than no form at all.

    The hard rule against non-`core/*` / non-`woocommerce/*` blocks
    (AGENTS.md rule #4) makes a real email-capture form impossible
    inside this codebase, so the only honest path is to ban the fake
    ones. Replace newsletter sections with something that actually
    works: `woocommerce/customer-account`, a link to a real journal /
    page, a `core/social-links` cluster, a featured `woocommerce/
    product-collection`, etc.

    Two surfaces are checked:

      1. `core/search` is allowed ONLY in genuinely-search contexts:
         `parts/header.html`, `parts/no-results.html`,
         `templates/search.html`, `templates/product-search-results.html`,
         and `templates/404.html` (where a search prompt makes sense
         when the URL was wrong). Anywhere else it's a fake form.

      2. `core/html` blocks are scanned for `<form`,
         `<input type="email"`, or a Subscribe / Sign up / Notify-me
         button. Any of those is a fake submission target.

    Fix path: pick a real action -- `woocommerce/customer-account`,
    a `<a>` to `/my-account/`, `/journal/`, `/contact/`, a featured
    collection -- and route the user there instead.
    """
    r = Result("No fake forms (no email-capture stand-ins built out of core/search or raw <form>)")

    search_allowed_paths = {
        "parts/header.html",
        "parts/no-results.html",
        "templates/search.html",
        "templates/product-search-results.html",
        "templates/404.html",
    }
    skip_dirs = ("templates/", "parts/", "patterns/")

    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    search_re = re.compile(r"<!--\s*wp:search\b")
    html_block_re = re.compile(
        r"<!--\s*wp:html\s*-->\s*(.*?)\s*<!--\s*/wp:html\s*-->",
        re.DOTALL,
    )
    fake_form_signals = re.compile(
        r"<form\b|<input[^>]*type=[\"']email[\"']|<button[^>]*>\s*(?:subscribe|sign\s*up|notify|join the list)\b",
        re.IGNORECASE,
    )

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        for m in search_re.finditer(text):
            if rel in search_allowed_paths:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/search outside a real search surface. "
                f"This block submits `?s=…` to the home URL -- it can't capture "
                f"emails or subscriptions. Replace with a real CTA "
                f"(woocommerce/customer-account, an <a> to /my-account/ or "
                f"/journal/, a core/social-links cluster, etc.)."
            )

        for m in html_block_re.finditer(text):
            body = m.group(1)
            sig = fake_form_signals.search(body)
            if not sig:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: core/html block contains a raw <form> or "
                f"email-capture markup ('{sig.group(0)[:40]}') that submits to "
                f"nothing real. Replace with a working CTA -- a real <a> to "
                f"/my-account/, a woocommerce/customer-account block, or "
                f"core/social-links."
            )

    if r.passed:
        r.details.append(f"{len(files)} pattern/template/part file(s) scanned for fake forms")
    return r


def check_modern_blocks_only() -> Result:
    """Fail if any `templates/`, `parts/`, or `patterns/` file uses a
    forbidden legacy block (`core/html` except narrow SVG escapes,
    `core/shortcode`, `core/freeform`) or any WooCommerce shortcode
    the monorepo's hard-rule #4 forbids.

    Context
    -------
    The `build-block-theme-variant` skill has long asked agents to
    manually run three `grep -rE` commands before declaring a theme
    done. The skill's checklist said to run these greps, but nothing
    automated enforced them — so the "I forgot to grep" class of
    regression was always latent. This check folds those three greps
    into a real static gate, so "done" implies the same contract
    regardless of whether an agent remembered to run the checklist.

    What's forbidden
    ----------------
    1. `<!-- wp:html -->`, `<!-- wp:shortcode -->`, `<!-- wp:freeform -->`
       in `templates/`, `parts/`, or `patterns/`. (core/html is allowed
       narrowly inside `patterns/` for inline decorative SVG — see the
       SVG escape carve-out in the skill; we detect that here by
       confirming the block body looks like pure `<svg ...>…</svg>`
       with no `<form>` / `<iframe>` / `<script>`.)
    2. Legacy WooCommerce page shortcodes: `[woocommerce_cart]`,
       `[woocommerce_checkout]`, `[woocommerce_my_account]`,
       `[woocommerce_order_tracking]`. The monorepo ships block-based
       equivalents for every one of these.
    3. Legacy WooCommerce catalogue shortcodes: `[products]`,
       `[product_category]`, `[recent_products]`, `[featured_products]`,
       `[sale_products]`, `[product_page]`, `[add_to_cart]`,
       `[shop_messages]`. Every one has a `woocommerce/*` block
       counterpart.
    """
    r = Result("Only modern blocks (no legacy wp:html/shortcode/freeform or WC shortcodes)")
    scan_dirs = ("templates", "parts", "patterns")
    files: list[Path] = []
    for d in scan_dirs:
        base = ROOT / d
        if base.is_dir():
            files.extend(p for p in base.rglob("*.html") if p.is_file())
            files.extend(p for p in base.rglob("*.php") if p.is_file())
    if not files:
        r.skip("no template/part/pattern files")
        return r

    legacy_block_re = re.compile(
        r"<!--\s*wp:(html|shortcode|freeform)\b",
        re.IGNORECASE,
    )
    html_block_body_re = re.compile(
        r"<!--\s*wp:html\s*-->(.*?)<!--\s*/wp:html\s*-->",
        re.DOTALL | re.IGNORECASE,
    )
    wc_page_shortcode_re = re.compile(
        r"\[woocommerce_(cart|checkout|my_account|order_tracking)\b",
        re.IGNORECASE,
    )
    wc_catalogue_shortcode_re = re.compile(
        r"\[(products|product_category|recent_products|featured_products|"
        r"sale_products|product_page|add_to_cart|shop_messages)\b",
        re.IGNORECASE,
    )
    danger_inside_svg_re = re.compile(
        r"<(?:form|iframe|script|input|button)\b",
        re.IGNORECASE,
    )

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")

        for m in legacy_block_re.finditer(text):
            kind = m.group(1).lower()
            lineno = text.count("\n", 0, m.start()) + 1
            if kind == "html":
                body_match = html_block_body_re.search(text, m.start())
                body = body_match.group(1) if body_match else ""
                body_stripped = body.strip()
                has_svg = body_stripped.lower().startswith(("<svg", "<!--"))
                has_danger = bool(danger_inside_svg_re.search(body))
                if "<svg" in body_stripped.lower() and not has_danger and has_svg:
                    continue
            r.fail(
                f"{rel}:{lineno}: legacy wp:{kind} block is forbidden "
                "(hard rule #4: only core/* and woocommerce/* blocks). "
                + (
                    "core/html is permitted narrowly for a pure "
                    "decorative SVG — no <form>/<iframe>/<script>/"
                    "<input>/<button> allowed in the body."
                    if kind == "html"
                    else "Replace with the appropriate core/* block."
                )
            )

        for m in wc_page_shortcode_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: legacy WC page shortcode "
                f"`[woocommerce_{m.group(1)}]`. Use the block equivalent "
                f"(woocommerce/cart, woocommerce/checkout, "
                f"woocommerce/customer-account, etc)."
            )

        for m in wc_catalogue_shortcode_re.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: legacy WC catalogue shortcode "
                f"`[{m.group(1)}]`. Use `woocommerce/product-collection` "
                f"with the appropriate filters."
            )

    if r.passed:
        r.details.append(
            f"{len(files)} template/part/pattern file(s) scanned; no legacy blocks or shortcodes"
        )
    return r


def check_swatch_js_targets_real_select() -> Result:
    """The variation-swatch JS shim in `functions.php` must target the
    real hidden `<select>` that WooCommerce emits -- not a phantom
    `select.wo-swatch-select` class that nothing ever adds.

    Context / why this check exists
    -------------------------------
    Every theme replaces WC's native variation dropdowns with a custom
    swatch UI (bracketed by `// === BEGIN swatches === /` === END
    swatches ===`). The native `<select>` stays in the DOM wrapped in
    `<span class="screen-reader-text">` so the form still submits and
    WC's `variation_form.js` can drive price / stock / image swap.
    An inline footer script is supposed to forward swatch clicks into
    the hidden `<select>` via `sel.dispatchEvent(new Event('change'))`.

    A copy-paste of that JS across all six themes (obel, chonk, aero,
    foundry, lysholm, selvedge) queried for `select.wo-swatch-select`
    -- but the PHP renderer never writes that class onto the select
    (WC re-emits `class=""` late in the tag, which stomps any class
    we inject). So the selector returned `null`, the shim early-
    returned, and swatch buttons did NOTHING. Variable products
    became un-purchaseable on the PDP on every theme.

    The fix is a single character change in every shim
    (`select.wo-swatch-select` -> `select`) -- there is always exactly
    one `<select>` per `.wo-swatch-wrap` by construction. This check
    makes sure nobody re-introduces the phantom selector.

    What's checked
    --------------
    Reads `<theme>/functions.php`, scans the region between the
    `// === BEGIN swatches ===` / `// === END swatches ===` sentinels,
    and FAILs if that region contains the literal string
    `select.wo-swatch-select`. Themes without a swatches region skip.

    Manual fix when this fails: in the offending `functions.php`,
    change `wrap.querySelector('select.wo-swatch-select')` to
    `wrap.querySelector('select')`.
    """
    r = Result("Swatch JS targets real <select> (no phantom select.wo-swatch-select)")
    fn_path = ROOT / "functions.php"
    if not fn_path.exists():
        r.skip("no functions.php at theme root")
        return r
    text = fn_path.read_text(encoding="utf-8", errors="replace")
    open_marker = "// === BEGIN swatches ==="
    close_marker = "// === END swatches ==="
    start = text.find(open_marker)
    end = text.find(close_marker)
    if start == -1 or end == -1 or end <= start:
        r.skip("no swatches sentinel region in functions.php")
        return r
    region = text[start:end]
    phantom = "select.wo-swatch-select"
    if phantom in region:
        offset_in_file = text.find(phantom, start, end)
        lineno = text.count("\n", 0, offset_in_file) + 1 if offset_in_file != -1 else None
        loc = f":{lineno}" if lineno else ""
        r.fail(
            f"functions.php{loc}: swatch JS shim queries for "
            f"'select.wo-swatch-select', but nothing ever adds that "
            f'class to the hidden <select> (WC re-emits class="" '
            f"late in the tag, overwriting any injected class). The "
            f"querySelector returns null, the shim early-returns, and "
            f"swatch buttons do nothing -- variable products become "
            f"un-purchaseable. Fix: change the selector to "
            f"'select' (there is always exactly one <select> per "
            f".wo-swatch-wrap by construction)."
        )
    return r


def check_no_empty_cover_blocks() -> Result:
    """Fail if any pattern/template/part contains a `wp:cover` whose `url`
    is empty/missing AND `dimRatio` is below 30 -- i.e., a cover that
    paints nothing at all.

    Why this exists:
      `wp:cover` is the WP-blessed block for "image-with-text-overlay"
      hero/lookbook/banner surfaces. The block's `url` attribute is
      what gives it the actual cover painting; if you author it as
      `{"url":""}` (or omit `url` entirely) AND leave `dimRatio` at
      the default 0/low values, the block renders as a transparent
      box of `min-height` pixels with text positioned inside it.
      Visually that's a giant empty void above your headline -- the
      exact failure mode this check exists to catch (it shipped on
      Lysholm's front-page lookbook hero from 969b7f6 through 94dface,
      a ~720px transparent base-on-base box that nobody noticed because
      the text inside it WAS painted correctly and axe-core has no
      "huge empty space above headline" rule -- 0dfccab fixed the
      symptom by extracting the hero into
      `lysholm/patterns/hero-lookbook.php`; this gate prevents the
      same shape from re-appearing on a sixth theme).

      The failure mode is built into the workflow: static `.html`
      templates can't run PHP, so they can't inject
      `get_theme_file_uri( 'playground/images/foo.jpg' )` into a
      `wp:cover` `url` attribute. Authors who forget this end up
      leaving `"url":""` as a placeholder and shipping it. The fix
      is always the same -- extract the cover into a `.php` pattern
      where `get_theme_file_uri()` actually resolves, and reference
      it from the template via `<!-- wp:pattern {"slug":"…"} /-->`.
      `lysholm/patterns/hero-lookbook.php` is the worked example.

    What's allowed:
      * `wp:cover` with a non-empty `url` (image-backed cover -- the
        normal case).
      * `wp:cover` with `dimRatio >= 30` (a deliberately-painted color
        block masquerading as a cover -- used by selvedge's
        front-page.html for category cards). 30 is the WP editor's
        "noticeable tint" threshold; below that the overlay is mostly
        transparent and the block needs an image to show anything.
      * Cover markup inside `.php` patterns where the `url` value is
        a PHP expression (`<?php echo esc_url( … ); ?>`) -- the URL
        will be a real file path at render time.

    What's NOT allowed:
      * `wp:cover` with `url` empty/missing AND `dimRatio` < 30 in
        ANY file -- the block paints nothing.
    """
    r = Result("No empty `wp:cover` blocks (no transparent placeholder hero boxes)")

    cover_re = re.compile(r"<!--\s*wp:cover\s*(\{[^}]*\})\s*-->")
    skip_dirs = ("templates/", "parts/", "patterns/")

    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in cover_re.finditer(text):
            attrs_blob = m.group(1)
            url_match = re.search(r'"url"\s*:\s*"([^"]*)"', attrs_blob)
            url_value = url_match.group(1) if url_match else ""
            if "<?php" in url_value or "<?=" in url_value:
                continue
            if url_value.strip():
                continue
            dim_match = re.search(r'"dimRatio"\s*:\s*(\d+)', attrs_blob)
            dim_ratio = int(dim_match.group(1)) if dim_match else 0
            if dim_ratio >= 30:
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            min_h_match = re.search(r"min-height:(\d+)px", text[m.start() : m.start() + 800])
            min_h = (min_h_match.group(1) + "px") if min_h_match else "unknown-height"
            r.fail(
                f"{rel}:{lineno}: wp:cover with empty `url` and dimRatio={dim_ratio} "
                f"(< 30) renders as a transparent {min_h} void. "
                f"Either: (1) move the cover into a `.php` pattern where "
                f"`get_theme_file_uri('playground/images/<file>.jpg')` can "
                f"inject a real URL (see lysholm/patterns/hero-lookbook.php "
                f"for the worked example), (2) set `dimRatio>=30` with an "
                f"intentional `overlayColor` if you actually want a flat "
                f"color-block container, or (3) replace `wp:cover` with "
                f"`wp:group` + `backgroundColor` if you don't need the "
                f"image-overlay machinery."
            )

    if r.passed:
        r.details.append(
            f"{len(files)} pattern/template/part file(s) scanned; no empty wp:cover blocks"
        )
    return r


def check_product_terms_query_show_nested() -> Result:
    """Fail if any `wp:terms-query` for `product_cat` declares
    `showNested:false` without an explicit `include` filter.

    THE SELVEDGE FAIL MODE
    ----------------------
    All canonical demo product categories live under a top-level `Shop`
    parent (`Shop > Tools`, `Shop > Sundries`, etc.). When a
    `core/terms-query` block walks the `product_cat` taxonomy with
    `showNested:false`, the WP loop only emits the top-level term --
    so a "Shop by Trade" / "Shop by Category" surface that should
    list 5+ children renders as a single tile linking to `/shop/`.

    The fix is to set `showNested:true` (so children are included),
    or to explicitly filter `include` to the curated subset the design
    actually wants. Anything else is almost certainly a paste-from-
    obel bug because obel's category seeding is flat.

    What's allowed:
      * `wp:terms-query` blocks for non-`product_cat` taxonomies (post
        category, tag, navigation menu) -- those don't share the
        nested structure.
      * `wp:terms-query` blocks that declare an explicit `include`
        array -- the author has hand-picked the terms.
      * `wp:terms-query` blocks where `showNested:true` (or the key
        is omitted; WP's default depends on the block but most setups
        treat omission as "show nested").

    What's NOT allowed:
      * `wp:terms-query` for `product_cat` with `showNested:false`
        AND no `include` filter -- the block will silently render a
        single category tile.
    """
    r = Result("`wp:terms-query` for product_cat must show nested categories")

    terms_query_re = re.compile(r"<!--\s*wp:terms-query\s*(\{.*?\})\s*-->", re.DOTALL)
    skip_dirs = ("templates/", "parts/", "patterns/")
    files: list[Path] = []
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(d) for d in skip_dirs):
            files.append(path)

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in terms_query_re.finditer(text):
            attrs_blob = m.group(1)
            if '"product_cat"' not in attrs_blob:
                continue
            if re.search(r'"showNested"\s*:\s*true', attrs_blob):
                continue
            include_match = re.search(r'"include"\s*:\s*\[([^\]]*)\]', attrs_blob)
            if include_match and include_match.group(1).strip():
                continue
            if not re.search(r'"showNested"\s*:\s*false', attrs_blob):
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            r.fail(
                f"{rel}:{lineno}: `wp:terms-query` for `product_cat` has "
                f"`showNested:false` but no explicit `include` filter. "
                f"Demo product categories live under the `Shop` parent, "
                f"so this block will render a single tile instead of the "
                f"sub-category grid the design wants. Set "
                f'`"showNested":true` or add `"include":[<term-ids>]` '
                f"with the curated subset."
            )

    if r.passed:
        r.details.append(
            f"{len(files)} pattern/template/part file(s) scanned; "
            f"no product_cat terms-query with hidden nesting"
        )
    return r


def check_no_large_placeholder_groups() -> Result:
    """Fail if a front-page template renders a large `wp:group` whose only
    visible content is a single decorative glyph/icon paragraph and no
    image, media, query, pattern, or product block.

    THE CHONK FAIL MODE
    -------------------
    `check_no_empty_cover_blocks` only flags `wp:cover` voids. The
    chonk hero shipped a giant `wp:group` containing a 7-xl glyph
    paragraph (e.g. `◳`) inside a heavy-bordered card -- the
    rendered page showed an empty cream box with a single Unicode
    character because no image was present. Visually identical to
    the empty-cover bug, but a different block name slipped past the
    cover gate.

    The check looks for `wp:group` blocks whose author intent is
    clearly "a hero card holding a featured image / pattern" but
    whose body has no image, media, query, pattern, or product
    descendant -- only paragraphs (the placeholder glyph + a
    sticker label).

    Heuristic:
      * Group block lives in `templates/front-page.html` (the only
        place an empty hero is catastrophically visible).
      * Group has padding token `2-xl` or larger, OR explicit border
        width >= `thick`, OR a shadow attribute -- i.e. it's an
        intentional card surface, not a layout wrapper.
      * Group's inner blocks contain ONLY `wp:paragraph`,
        `wp:heading`, `wp:spacer`, or `wp:separator` -- no
        `wp:image`, `wp:cover`, `wp:gallery`, `wp:media-text`,
        `wp:video`, `wp:embed`, `wp:pattern`, `wp:query`,
        `wp:woocommerce/*`, or `wp:post-featured-image`.
    """
    r = Result(
        "Front-page hero `wp:group` cards must contain an image, "
        "pattern, or media block (no glyph-only placeholder hero)"
    )

    front = ROOT / "templates" / "front-page.html"
    if not front.is_file():
        r.skip("no templates/front-page.html in this theme")
        return r

    text = front.read_text(encoding="utf-8", errors="replace")

    media_block_re = re.compile(
        r"<!--\s*wp:("
        r"image|cover|gallery|media-text|video|embed|pattern|query|"
        r"post-featured-image|woocommerce/[A-Za-z0-9_-]+|"
        r"latest-posts|featured-content|terms-query"
        r")\b"
    )

    # Hand-rolled brace-balanced parser for `wp:group` attribute JSON --
    # nested objects (style.border.color, style.spacing.padding) make a
    # `[^}]*` regex incorrect.
    def _parse_group_open(s: str, start: int) -> tuple[int, str] | None:
        m = re.compile(r"<!--\s*wp:group(\s*)").match(s, start)
        if not m:
            return None
        i = m.end()
        attrs = ""
        if i < len(s) and s[i] == "{":
            depth = 0
            in_str = False
            esc = False
            j = i
            while j < len(s):
                ch = s[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                j += 1
            attrs = s[i:j]
            i = j
        rest = re.compile(r"\s*-->").match(s, i)
        if not rest:
            return None
        return rest.end(), attrs

    pos = 0
    findings = 0
    open_re = re.compile(r"<!--\s*wp:group\b")
    while True:
        om = open_re.search(text, pos)
        if not om:
            break
        parsed = _parse_group_open(text, om.start())
        if not parsed:
            pos = om.end()
            continue
        body_start, attrs_blob = parsed
        depth = 1
        cursor = body_start
        block_close_re = re.compile(r"<!--\s*(/wp:group|wp:group\b)")
        end_pos = -1
        while depth > 0:
            inner = block_close_re.search(text, cursor)
            if not inner:
                break
            tag = inner.group(1)
            if tag.startswith("/wp:group"):
                depth -= 1
                if depth == 0:
                    close_end = text.find("-->", inner.end())
                    if close_end < 0:
                        break
                    end_pos = close_end + 3
                    break
                cursor = inner.end()
            else:
                nested = _parse_group_open(text, inner.start())
                if nested:
                    cursor = nested[0]
                    depth += 1
                else:
                    cursor = inner.end()
        if end_pos < 0:
            pos = om.end()
            continue
        body = text[body_start:end_pos]

        is_card = (
            "2-xl" in attrs_blob
            or "3-xl" in attrs_blob
            or "4-xl" in attrs_blob
            or '"shadow"' in attrs_blob
            or "width|thick" in attrs_blob
            or ('"border"' in attrs_blob and '"width"' in attrs_blob)
        )
        if not is_card:
            pos = end_pos
            continue
        if media_block_re.search(body):
            pos = end_pos
            continue
        char_text = re.findall(r">([^<>]+)<", body)
        non_ws_chars = "".join(c for c in "".join(char_text) if not c.isspace())
        if len(non_ws_chars) > 60:
            pos = end_pos
            continue

        lineno = text.count("\n", 0, om.start()) + 1
        r.fail(
            f"templates/front-page.html:{lineno}: large `wp:group` card "
            f"(padding/shadow/thick-border) contains no image, pattern, "
            f"or media block -- visible characters: {non_ws_chars[:60]!r}. "
            f"This renders as an empty card with at most a glyph "
            f"placeholder. Add a `<!-- wp:image -->` (resolved via "
            f"`get_theme_file_uri()` in a `.php` pattern), a "
            f'`<!-- wp:pattern {{"slug":"..."}} /-->`, or a '
            f"`<!-- wp:woocommerce/product-image -->` block."
        )
        findings += 1
        if findings >= 5:
            break
        pos = end_pos

    if r.passed:
        r.details.append("front-page.html scanned; no glyph-only hero placeholder groups")
    return r


def check_product_image_visual_diversity() -> Result:
    """Warn if any two `product-wo-*.jpg` photographs inside a single
    theme are perceptually near-identical (visually so similar that the
    catalogue reads as the same image with different filenames).

    THE FOUNDRY FAIL MODE
    ---------------------
    `check_product_images_unique_across_themes` already catches
    cross-theme byte-for-byte copies. But generators can produce a
    set of 30 product photographs that are byte-unique (different
    JPEG compression artifacts, different filenames) yet visually
    repetitive -- the same camera angle, the same prop arrangement,
    the same lighting, the same subject framed slightly differently.
    Visually a shopper sees "this brand has one product photographed
    30 times".

    This check uses an ahash-style perceptual hash (8x8 average-hash
    on the luminance channel, no PIL dependency required) and emits
    a WARN-tier finding when any pair has Hamming distance <= 8 bits
    (out of 64), i.e. when at least 56 of 64 sampled cells agree.
    Empirically that threshold catches near-duplicates while letting
    the same hand-built sticker on three different products through.

    The check is opt-in: it requires Pillow (PIL). When PIL isn't
    available it skips with a hint rather than failing -- the
    project's pyproject pins Pillow but pre-commit hooks may run in
    a stripped venv where the import fails.
    """
    r = Result("Product photographs are visually distinct within a theme")
    images_dir = ROOT / "playground" / "images"
    if not images_dir.is_dir():
        r.skip("no playground/images/ directory")
        return r
    products = sorted(images_dir.glob("product-wo-*.jpg"))
    if len(products) < 2:
        r.skip("fewer than 2 product photographs to compare")
        return r

    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        r.skip("Pillow (PIL) not available; install pillow to run perceptual diff")
        return r

    def ahash(path: Path) -> int:
        with Image.open(path) as im:
            small = im.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
            pixels = list(small.getdata())
        avg = sum(pixels) / 64.0
        bits = 0
        for i, p in enumerate(pixels):
            if p >= avg:
                bits |= 1 << i
        return bits

    hashes: list[tuple[str, int]] = []
    for p in products:
        try:
            hashes.append((p.name, ahash(p)))
        except OSError:
            continue

    near_dupes: list[tuple[str, str, int]] = []
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            name_a, h_a = hashes[i]
            name_b, h_b = hashes[j]
            dist = bin(h_a ^ h_b).count("1")
            # Threshold is 5 bits (out of 64). 0-2 bits is functionally
            # the same image; 3-5 catches the same staging with a
            # different prop swap (the failure mode foundry shipped);
            # 6-9 starts to bleed into legitimate "same brand voice,
            # different subject" pairs and produces too much noise.
            if dist <= 5:
                near_dupes.append((name_a, name_b, dist))

    if near_dupes:
        sample = near_dupes[:5]
        more = f" (+{len(near_dupes) - 5} more)" if len(near_dupes) > 5 else ""
        details = "; ".join(f"{a} ~ {b} (Hamming {d}/64)" for a, b, d in sample)
        verdict_note = ""
        if os.environ.get("FIFTY_JUDGMENT_ENABLED") == "1":
            # The flexible-judgment opt-in: instead of unconditionally
            # failing on a pHash distance <=5, ask the LLM whether the
            # near-duplicates are genuinely the same staging or two
            # distinct products that happen to share a camera angle.
            # The cache is keyed on the image bytes, so a re-shoot with
            # unchanged files short-circuits without re-billing.
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from _judgment_lib import ask_judgment

                # Flatten the sample pairs into an ordered image list
                # (A0, B0, A1, B1, ...) so the model sees each pair
                # adjacent in content blocks. The ahash-flagged sample
                # is capped at 5 pairs upstream so we send at most 10
                # images — well under Anthropic's per-request image cap
                # and the daily budget guard.
                pair_images: list[Path] = []
                for a, b, _ in sample:
                    pair_images.append(images_dir / a)
                    pair_images.append(images_dir / b)
                answer = ask_judgment(
                    theme_slug=ROOT.name,
                    question_id="product-image-diversity",
                    system_prompt=(
                        "You are auditing a shop catalogue's product "
                        "photographs. A perceptual hash (ahash) flagged "
                        "these pairs as near-identical. The images are "
                        "attached in pairs (image 1 & 2 are the first "
                        "pair, 3 & 4 the second, and so on). Decide "
                        "whether each pair shows distinct products/"
                        "compositions (pass) or the same staging with "
                        "a different label (fail). Look at lighting, "
                        "camera angle, props, product silhouette, and "
                        "the product itself. Low confidence -> needs_human."
                    ),
                    user_prompt=(
                        f"Theme: {ROOT.name}\n"
                        f"Near-duplicate pairs (Hamming <=5 / 64), in "
                        f"the order of the attached images:\n"
                        + "\n".join(
                            f"  - pair {i + 1}: {a} vs {b} (distance {d})"
                            for i, (a, b, d) in enumerate(sample)
                        )
                    ),
                    image_paths=pair_images,
                )
                if answer.passed:
                    verdict_note = (
                        f"\nLLM judgment: PASS (confidence "
                        f"{answer.confidence:.2f}): {answer.rationale}"
                    )
                    r.details.append(verdict_note.strip())
                    return r
                verdict_note = (
                    f"\nLLM judgment: {answer.verdict.upper()} "
                    f"(confidence {answer.confidence:.2f}): "
                    f"{answer.rationale}"
                )
            except Exception as exc:
                verdict_note = (
                    f"\nLLM judgment: unavailable ({exc!r}); "
                    "falling back to deterministic hard fail."
                )
        r.fail(
            f"{len(near_dupes)} pair(s) of product photographs are "
            f"perceptually near-identical: {details}{more}. The catalogue "
            f"will read as 'one product, 30 labels'. Regenerate the "
            f"duplicates with different camera angles, props, or staging "
            f"so each parent SKU has a visually distinct portrait." + verdict_note
        )
        return r

    r.details.append(
        f"{len(hashes)} product photograph(s) compared pairwise; no perceptual near-duplicates"
    )
    return r


def check_product_images_json_complete() -> Result:
    """Fail if a theme ships per-theme `product-wo-*.jpg` photographs
    without a `playground/content/product-images.json` mapping.

    `playground/wo-configure.php` reads `product-images.json` (when
    present) at boot to look up which file to attach to each parent
    WC SKU. Without the map, the per-theme photographs sit on disk
    unused and the products fall back to the upstream cartoon PNGs
    (or to whatever the CSV references). Symptom on the live demo:
    the catalogue grid renders a mix of bespoke per-theme photos
    (from the slugs the seeder hardcoded) and stale upstream
    placeholders (everything else).

    The map is required if (and only if) the theme has any
    `product-wo-*.jpg` files and a `playground/blueprint.json`. If
    a theme deliberately has no photographs yet (incubating) it
    can ship without the map; the seeder will use upstream art.
    """
    r = Result("`playground/content/product-images.json` covers every product photograph")
    bp = ROOT / "playground" / "blueprint.json"
    if not bp.exists():
        r.skip("no playground/blueprint.json (theme without a Playground demo)")
        return r
    images_dir = ROOT / "playground" / "images"
    if not images_dir.is_dir():
        r.skip("no playground/images/ directory")
        return r
    photos = sorted(images_dir.glob("product-wo-*.jpg"))
    if not photos:
        r.skip("no product-wo-*.jpg photographs found")
        return r

    map_path = ROOT / "playground" / "content" / "product-images.json"
    if not map_path.is_file():
        r.fail(
            f"theme ships {len(photos)} `product-wo-*.jpg` "
            f"photograph(s) but `playground/content/product-images.json` "
            f"is missing. `playground/wo-configure.php` reads that map "
            f"at boot to attach each parent SKU's thumbnail; without "
            f"it the per-theme photographs sit unused and the catalogue "
            f"renders the upstream cartoon placeholders. Create the "
            f"map (SKU -> filename) -- see "
            f"`.cursor/rules/playground-imagery.mdc` for the canonical "
            f"shape and `obel/playground/content/product-images.json` "
            f"for an example."
        )
        return r
    if not _git_tracks(map_path):
        r.fail(
            "`playground/content/product-images.json` exists locally but is "
            "not tracked by git. Playground fetches this map through "
            "raw.githubusercontent.com during remote snaps/live demos, so an "
            "untracked map 404s and products render WooCommerce placeholders. "
            f"Stage and commit `{_repo_relpath(map_path)}` with the matching "
            "`playground/images/product-wo-*.jpg` files."
        )
        return r

    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.fail(
            f"playground/content/product-images.json is unreadable: {e}. "
            f"Regenerate it from a fresh `bin/seed-playground-content.py "
            f"--theme {ROOT.name} --force` run."
        )
        return r

    if not isinstance(data, dict) or not data:
        r.fail(
            "playground/content/product-images.json is empty or not "
            "a SKU->filename object. Regenerate it; see "
            "`.cursor/rules/playground-imagery.mdc` for the shape."
        )
        return r

    photo_names = {p.name for p in photos}
    referenced = {v for v in data.values() if isinstance(v, str)}
    missing_on_disk = sorted(referenced - photo_names)
    unreferenced = sorted(photo_names - referenced)
    problems: list[str] = []
    if missing_on_disk:
        head = ", ".join(missing_on_disk[:5])
        more = f" (+{len(missing_on_disk) - 5} more)" if len(missing_on_disk) > 5 else ""
        problems.append(
            f"{len(missing_on_disk)} filename(s) listed in the map but "
            f"missing from playground/images/: {head}{more}"
        )
    if unreferenced:
        head = ", ".join(unreferenced[:5])
        more = f" (+{len(unreferenced) - 5} more)" if len(unreferenced) > 5 else ""
        problems.append(
            f"{len(unreferenced)} photograph(s) on disk that no SKU "
            f"references in the map: {head}{more}"
        )
    if problems:
        r.fail(
            "product-images.json is out of sync with playground/images/: "
            + "; ".join(problems)
            + ". Re-run `python3 bin/seed-playground-content.py --theme "
            + ROOT.name
            + " --force` to rebuild the map."
        )
        return r

    r.details.append(
        f"product-images.json maps {len(data)} SKU(s); every entry "
        f"resolves to an on-disk photograph"
    )
    return r


def check_category_images_json_complete() -> Result:
    """Fail if category cover assets cannot be served by the blueprint.

    `playground/wo-configure.php` reads `content/category-images.json` and
    sideloads `cat-*.jpg` files from the same raw GitHub ref. If those files
    are only present locally, product-category archives boot with WooCommerce
    placeholder tiles until a snap catches the runtime failure.
    """
    r = Result("`playground/content/category-images.json` covers category cover art")
    bp = ROOT / "playground" / "blueprint.json"
    if not bp.exists():
        r.skip("no playground/blueprint.json (theme without a Playground demo)")
        return r
    images_dir = ROOT / "playground" / "images"
    if not images_dir.is_dir():
        r.skip("no playground/images/ directory")
        return r

    covers = sorted(images_dir.glob("cat-*.jpg"))
    map_path = ROOT / "playground" / "content" / "category-images.json"
    if not covers and not map_path.exists():
        r.skip("no cat-*.jpg category cover photographs found")
        return r
    if not map_path.is_file():
        r.fail(
            f"theme ships {len(covers)} `cat-*.jpg` category cover image(s) "
            "but `playground/content/category-images.json` is missing. "
            "`playground/wo-configure.php` reads that map at boot to attach "
            "term thumbnails; without it category grids render WooCommerce "
            "placeholder tiles."
        )
        return r
    if not _git_tracks(map_path):
        r.fail(
            "`playground/content/category-images.json` exists locally but is "
            "not tracked by git. Remote Playground boots fetch it through "
            "raw.githubusercontent.com, so an untracked category map behaves "
            f"like a 404. Stage and commit `{_repo_relpath(map_path)}` with "
            "the matching `playground/images/cat-*.jpg` files."
        )
        return r

    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.fail(f"playground/content/category-images.json is unreadable: {e}.")
        return r
    if not isinstance(data, dict) or not data:
        r.fail("playground/content/category-images.json is empty or not a term-name->filename object.")
        return r

    cover_names = {p.name for p in covers}
    referenced = {v for v in data.values() if isinstance(v, str)}
    missing_on_disk = sorted(referenced - cover_names)
    unreferenced = sorted(cover_names - referenced)
    problems: list[str] = []
    if missing_on_disk:
        problems.append(
            "map references missing file(s): " + ", ".join(missing_on_disk[:6])
        )
    if unreferenced:
        problems.append(
            "unmapped cat-*.jpg file(s): " + ", ".join(unreferenced[:6])
        )
    if problems:
        r.fail("category-images.json is out of sync with playground/images/: " + "; ".join(problems))
        return r

    untracked_covers = [p for p in covers if not _git_tracks(p)]
    if untracked_covers:
        head = ", ".join(_repo_relpath(p) for p in untracked_covers[:6])
        more = f" (+{len(untracked_covers) - 6} more)" if len(untracked_covers) > 6 else ""
        r.fail(
            "`cat-*.jpg` category cover image(s) exist locally but are not "
            f"tracked by git: {head}{more}. Remote Playground boots will 404 "
            "them and render WooCommerce placeholders."
        )
        return r

    r.details.append(
        f"category-images.json maps {len(data)} term(s); every cover is tracked and on disk"
    )
    return r


def check_no_duplicate_templates() -> Result:
    """Fail if any two files in templates/ have identical content."""
    r = Result("No duplicate template files in templates/")
    import hashlib

    seen: dict[str, str] = {}
    templates_dir = ROOT / "templates"
    if not templates_dir.exists():
        r.fail("templates/ directory missing")
        return r
    for path in sorted(templates_dir.glob("*.html")):
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        rel = path.relative_to(ROOT).as_posix()
        if digest in seen:
            r.fail(f"{rel} is identical to {seen[digest]}")
        else:
            seen[digest] = rel
    if r.passed and not r.skipped:
        r.details.append(f"{len(seen)} templates checked")
    return r


def check_wc_overrides_styled() -> Result:
    """Fail if any WC surface known to ship hardcoded frontend CSS lacks a
    real override in **top-level** `styles.css`.

    See AGENTS.md rule 6 (No raw WooCommerce frontend CSS bleeds through).

    WHY top-level `styles.css` and not `styles.blocks.<block>.css`:
    WP processes block-scoped css through
    `WP_Theme_JSON::process_blocks_custom_css()`, which wraps every rule in
    `:root :where(<block-selector>) { ... }`. `:where()` has SPECIFICITY
    ZERO, so the *entire* block.css string ends up at `(0,0,1)`. WC's
    plugin CSS sits at `(0,4,3)` (e.g.
    `.woocommerce div.product .woocommerce-tabs ul.tabs li`) — block-scoped
    overrides are silently dwarfed. Top-level `styles.css` is emitted
    verbatim, so we can write the WC selectors with their natural
    specificity and win the cascade by load order (theme after plugin).

    Each entry in WC_OVERRIDE_TARGETS lists:
      - one or more substrings (collapsed of whitespace) the top-level
        styles.css MUST contain — the WC selectors we are overriding,
      - one or more "kill" declarations, at least one of which MUST
        appear, proving WC's defaults (rounded folder corners, pseudo
        shoulders, grey backgrounds) are explicitly suppressed,
      - the block whose `css` field, if present, indicates a stale
        attempt at a block-scoped override that we now treat as a hard
        failure (since it does nothing).
    """
    r = Result("WooCommerce frontend CSS is overridden in styles.css")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r

    styles = data.get("styles", {}) or {}
    top_css = styles.get("css") if isinstance(styles.get("css"), str) else ""
    top_css_norm = re.sub(r"\s+", "", top_css or "")
    blocks = styles.get("blocks") or {}

    # Each entry locks in one previously-WC-default visual surface. The
    # rules are deliberately narrow: a single brittle selector + a single
    # "kill" declaration that proves we're more than tweaking type — we're
    # actively tearing down WC's chrome (rounded panels, alert bars, star
    # glyphs, etc.). The chunk that satisfies all ten lives in
    # bin/append-wc-overrides.py and was appended to each theme's
    # styles.css; if a future edit strips a selector this list catches it.
    #
    # `must_kill_one_of` strings are matched against `top_css_norm` which
    # has had ALL whitespace stripped (`re.sub(r"\s+", "", ...)`), so the
    # fragments below are intentionally written with no spaces.
    WC_OVERRIDE_TARGETS: list[dict] = [
        {
            "name": "Store notices (F)",
            "must_target": [
                ".woocommerce-message",
                ".woocommerce-error",
                ".woocommerce-info",
                ".added_to_cart",
            ],
            "must_kill_one_of": [
                ".woocommerce-message,.woocommerce-error,.woocommerce-info{border:0;border-radius:0;background:transparent",
            ],
            "inert_block": "woocommerce/store-notices",
            "why": "WC ships green/red alert bars with leading icons. Replace with editorial divider rule (border-top/bottom only).",
        },
        {
            "name": "PDP meta labels (I)",
            "must_target": [
                ".product_meta .sku_wrapper>:first-child",
                ".product_meta .posted_in>:first-child",
                ".product_meta .tagged_as>:first-child",
            ],
            "must_kill_one_of": [
                ".product_meta.sku_wrapper>:first-child,.product_meta.posted_in>:first-child,.product_meta.tagged_as>:first-child{display:none",
            ],
            "why": "WC prefixes meta with literal 'SKU:' / 'Category:' / 'Tags:' labels. Hide the label, keep the value.",
        },
        {
            "name": "Star rating (G)",
            "must_target": [
                ".star-rating",
                ".star-rating>span",
            ],
            "must_kill_one_of": [
                ".star-rating{display:inline-block;position:relative;width:6rem;height:2px",
            ],
            "why": "WC renders 5 gold star glyphs via @font-face. Restyle the same markup as a thin horizontal fill bar.",
        },
        {
            "name": "Variable product form (D)",
            "must_target": [
                "table.variations",
                "table.variations select",
                ".reset_variations",
            ],
            "must_kill_one_of": [
                "table.variationsselect{appearance:none",
            ],
            "why": "WC's <table.variations> is a 2-column grey table with a native browser select. Stack rows + custom chevron + editorial labels.",
        },
        {
            "name": "Lightbox + product gallery (E)",
            "must_target": [
                ".pswp__top-bar",
                ".pswp__button",
                ".pswp__counter",
                ".flex-control-thumbs",
                ".flex-control-thumbs img.flex-active",
            ],
            "must_kill_one_of": [
                ".flex-control-thumbs{display:grid;grid-template-columns:repeat(4,1fr)",
            ],
            "inert_block": "woocommerce/product-image-gallery",
            "why": "PhotoSwipe and the FlexSlider thumbs strip ship with WC's own chrome (round buttons, blue active border).",
        },
        {
            "name": "Mini-cart drawer (C)",
            "must_target": [
                ".wc-block-mini-cart__drawer .components-modal__content",
                ".wc-block-mini-cart-items .wc-block-cart-item",
                ".wc-block-mini-cart__footer",
                ".wc-block-mini-cart__footer-actions",
            ],
            "must_kill_one_of": [
                ".wc-block-mini-cart__drawer.components-modal__content{padding:var(--wp--preset--spacing--xl);background:var(--wp--preset--color--base)",
            ],
            "inert_block": "woocommerce/mini-cart-contents",
            "why": "WC ships a left-aligned drawer with grey panel chrome and a red 'Remove' link. Reskin to editorial panel + pill buttons.",
        },
        {
            "name": "Cart page interior (A)",
            "must_target": [
                ".wc-block-cart",
                ".wc-block-cart-items .wc-block-cart-items__row",
                ".wc-block-components-quantity-selector",
                ".wc-block-cart__sidebar",
                ".wc-block-cart__submit-container",
                ".wc-block-components-totals-coupon__form",
            ],
            "must_kill_one_of": [
                ".wc-block-cart{display:grid;grid-template-columns:1fr",
            ],
            "inert_block": "woocommerce/cart",
            "why": "WC's cart ships rounded blue qty steppers, a panelised 'Cart totals' card, and a green proceed button. Restyle to editorial rows + pill buttons.",
        },
        {
            "name": "Checkout page interior (B)",
            "must_target": [
                ".wc-block-checkout",
                ".wc-block-components-checkout-step",
                ".wc-block-components-checkout-step__title",
                ".wc-block-components-text-input input",
                ".wc-block-components-payment-method",
                ".wc-block-components-checkout-place-order-button",
            ],
            "must_kill_one_of": [
                ".wc-block-checkout{display:grid;grid-template-columns:1fr",
            ],
            "inert_block": "woocommerce/checkout",
            "why": "WC's checkout ships numbered step circles, blue accents on inputs, and a giant green Place-Order button. Restyle to editorial steps + pill buttons.",
        },
        {
            "name": "Order confirmation downloads + create-account (J)",
            "must_target": [
                ".wp-block-woocommerce-order-confirmation-downloads",
                ".wp-block-woocommerce-order-confirmation-downloads table",
                ".wp-block-woocommerce-order-confirmation-create-account form",
            ],
            "must_kill_one_of": [
                ".wp-block-woocommerce-order-confirmation-downloadstable{width:100%;border-collapse:collapse",
            ],
            "why": "WC's downloads block ships a standalone bordered card with a blue Download button. Match the existing summary/totals/addresses treatment.",
        },
        {
            "name": "My Account (K)",
            "must_target": [
                ".woocommerce-account .woocommerce",
                ".woocommerce-MyAccount-navigation",
                ".woocommerce-MyAccount-navigation a",
                ".woocommerce-orders-table",
                ".woocommerce-MyAccount-content",
            ],
            "must_kill_one_of": [
                # Three accepted shapes, in order of recency:
                #   (a) the legacy short-hand reset, kept for back-compat with
                #       themes that haven't migrated to the per-theme
                #       `templates/page-my-account.html` pattern yet;
                #   (b) the body-prefixed, .entry-content-scoped grid that
                #       ships with the branded dashboard refactor (applies
                #       indiscriminately to .woocommerce children, including
                #       the logged-out login form which then breaks);
                #   (c) the same grid scoped via :has(>.woocommerce-MyAccount-
                #       navigation) so it ONLY fires on the logged-in dashboard
                #       (the logged-out login screen gets a separate 1fr 1fr
                #       grid scoped via :has(>.wo-account-intro) — see the
                #       my-account chunk in each theme's theme.json).
                ".woocommerce-account.woocommerce{display:grid;grid-template-columns:220px1fr",
                ".woocommerce-account.woocommerce:has(>.woocommerce-MyAccount-navigation){display:grid;grid-template-columns:220px1fr",
                "body.woocommerce-account.entry-content>.woocommerce{display:grid",
                "body.woocommerce-account.entry-content>.woocommerce:has(>.woocommerce-MyAccount-navigation){display:grid",
            ],
            "why": "WC's My Account ships a tab-style sidebar nav and a bordered orders table with WC blue accents. CSS-only restyle to editorial nav + flat tables.",
        },
    ]

    for target in WC_OVERRIDE_TARGETS:
        # 1) Reject any leftover block-scoped `css` field for this surface.
        #    It does nothing (see the docstring) and its presence almost
        #    always means the author thought they had styled the surface
        #    but actually hadn't.
        inert = blocks.get(target["inert_block"]) if target.get("inert_block") else None
        if isinstance(inert, dict) and isinstance(inert.get("css"), str) and inert["css"].strip():
            r.fail(
                f"{target['name']}: found "
                f'`styles.blocks["{target["inert_block"]}"].css`, but WP '
                f"wraps that field in `:root :where(...)` (specificity 0,0,1) "
                f"so it cannot beat WC's `(0,4,3)` plugin CSS. Move the WC "
                f"selectors to top-level `styles.css`."
            )
            continue

        # 2) Required selectors must appear (whitespace-insensitive) in the
        #    verbatim top-level styles.css.
        missing = [s for s in target["must_target"] if re.sub(r"\s+", "", s) not in top_css_norm]
        if missing:
            r.fail(
                f"{target['name']}: top-level `styles.css` is missing "
                f"selector(s) {missing}. {target['why']} Add a rule that "
                f"targets these selectors with theme tokens."
            )
            continue

        # 3) At least one "kill" declaration must appear so we know the
        #    override is doing more than tweaking typography.
        if not any(k in top_css_norm for k in target["must_kill_one_of"]):
            r.fail(
                f"{target['name']}: top-level `styles.css` doesn't kill any "
                f"of WC's defaults (expected one of "
                f"{target['must_kill_one_of']}). Without an explicit reset, "
                f"WC's `::before/::after` shapes and rounded corners leak."
            )
            continue

    if r.passed and not r.skipped:
        if WC_OVERRIDE_TARGETS:
            r.details.append(f"{len(WC_OVERRIDE_TARGETS)} WC surface(s) checked")
        else:
            r.details.append(
                "no WC surfaces currently require a top-level styles.css "
                "override (the tabs surface was retired by "
                "`check_no_wc_tabs_block`)"
            )
    return r


# Matches a single Gutenberg block delimiter comment:
#   <!-- wp:core/group {"foo":"bar"} -->         opening, attrs
#   <!-- wp:core/group -->                        opening, no attrs
#   <!-- wp:core/spacer {"height":"4px"} /-->     self-closing
#   <!-- /wp:core/group -->                       closing
# Captures: 1 = "/wp:NAME" or "wp:NAME", 2 = JSON attrs (or None), 3 = "/" if self-closing.
_BLOCK_DELIMITER_RE = re.compile(
    r"<!--\s*(/?wp:[a-z][a-z0-9_/-]*)(?:\s+(\{.*?\}))?\s*(/?)-->",
    re.DOTALL,
)


def _front_page_fingerprint(html: str) -> list[str]:
    """Return the structural fingerprint of front-page.html's <main> root.

    The fingerprint is the ordered list of direct children of the
    `<!-- wp:group {"tagName":"main",...} -->` root. Each entry is one of:

        "pattern:slug/name"               — for `wp:pattern` references
        "block-name(first-class-name)"    — when the block carries a className
        "block-name"                      — bare block, no distinguishing class

    Two themes that produce the SAME list have the SAME homepage composition,
    even if every color / font / token underneath differs. That is exactly the
    failure mode the user wants to prevent ("same layout, different colors").

    Empty list = no <main> group found, or no children inside it.
    """
    # Find the opening delimiter of the <main> root group. We can't use a single
    # regex with `[^}]*` here because group attrs routinely embed nested JSON
    # ({"layout":{"type":"constrained"}}). Iterate every wp:group opener and
    # parse its attrs as JSON, picking the first one whose tagName is "main".
    main_open = None
    for m in re.finditer(
        r"<!--\s*wp:group\s+(\{[^>]*?\})\s*-->",
        html,
    ):
        try:
            attrs = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if attrs.get("tagName") == "main":
            main_open = m
            break
    if main_open is None:
        return []

    fingerprint: list[str] = []
    depth = 0
    for tok in _BLOCK_DELIMITER_RE.finditer(html, pos=main_open.end()):
        name = tok.group(1)
        attrs_json = tok.group(2)
        self_closing = tok.group(3) == "/"

        if name.startswith("/wp:"):
            if depth == 0:
                # Closing tag for the <main> group itself — done.
                break
            depth -= 1
            continue

        # Opening (or self-closing) block.
        if depth == 0:
            block = name[len("wp:") :]
            label = block
            if attrs_json:
                try:
                    attrs = json.loads(attrs_json)
                except json.JSONDecodeError:
                    attrs = {}
                if block == "pattern":
                    # Strip the theme-slug prefix from pattern slugs.
                    # Two themes that compose `<theme>/hero-split + grid
                    # + grid` are structurally identical even though
                    # `aero/hero-split` and `obel/hero-split` are
                    # technically different slugs. The prefix-stripped
                    # form is what matters for the "same shape, different
                    # paint" diversity test.
                    raw_slug = attrs.get("slug", "?")
                    bare = raw_slug.split("/", 1)[1] if "/" in raw_slug else raw_slug
                    label = f"pattern:{bare}"
                else:
                    cls = attrs.get("className", "")
                    first = cls.split()[0] if isinstance(cls, str) and cls else ""
                    if first:
                        label = f"{block}({first})"
            fingerprint.append(label)

        if not self_closing:
            depth += 1

    return fingerprint


def check_no_wc_tabs_block() -> Result:
    """Fail if `wp:woocommerce/product-details` is rendered anywhere.

    `woocommerce/product-details` is the umbrella tabs block (Description /
    Additional Information / Reviews) that ships WC's hardcoded rounded
    "folder" tab markup. It is the single biggest "this is a default
    WooCommerce store" tell on a PDP and Baymard's research shows that
    tab-hidden content is ignored by 50%+ of users. We replaced it with a
    description-always-visible composition + native `core/details`
    disclosures (see `single-product.html`).

    This check enforces two things:

    1. No template / part / pattern in this theme references the umbrella
       tabs block (`wp:woocommerce/product-details`). If you need to surface
       a piece of product info, render the relevant individual WC block
       directly (`woocommerce/product-description`, `woocommerce/product-
       reviews`, etc.), wrapped in a `core/details` for collapsible
       sections.

    2. `styles.blocks["woocommerce/product-details"]` is not set in
       `theme.json`. The block is no longer rendered, so any styling there
       is stale config — and historically the surface most likely to drag
       the tabs back into the build by accident.

    See AGENTS.md rule 6.
    """
    r = Result("woocommerce/product-details (tabs block) is not rendered")

    # Part 1: scan templates/parts/patterns for the block delimiter.
    pattern = re.compile(r"<!--\s*wp:woocommerce/product-details(?:\s|/|-->)")
    for path in iter_files((".html", ".php")):
        rel = path.relative_to(ROOT).as_posix()
        if not (
            rel.startswith("templates/") or rel.startswith("parts/") or rel.startswith("patterns/")
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                r.fail(
                    f"{rel}:{lineno}: renders `wp:woocommerce/product-details` "
                    f"(the WC tabs block). Replace it with `wp:woocommerce/"
                    f"product-description` for the always-visible description "
                    f"and one `wp:details` per collapsible section "
                    f"(`wp:woocommerce/product-reviews` lives inside one)."
                )

    # Part 2: stale theme.json entry would imply someone is mid-restoration.
    theme_json = ROOT / "theme.json"
    if theme_json.exists():
        try:
            data = json.loads(theme_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        blocks = (data.get("styles") or {}).get("blocks") or {}
        if "woocommerce/product-details" in blocks:
            r.fail(
                'theme.json still has `styles.blocks["woocommerce/product-'
                'details"]`. The block is no longer rendered — delete the '
                "entry. Style `core/details` instead."
            )

    if r.passed and not r.skipped:
        r.details.append(
            "no WC tabs block in templates/parts/patterns and no stale theme.json styling"
        )
    return r


def check_no_duplicate_stock_indicator() -> Result:
    """Fail if a single-product template renders both
    `wp:woocommerce/product-stock-indicator` AND `wp:woocommerce/add-to-cart-form`
    without a top-level `styles.css` rule that hides the form's native
    `<p class="stock">`.

    Why this exists:
      `wp:woocommerce/add-to-cart-form` is a WC plugin block that echoes the
      add-to-cart `<form>` exactly like the legacy single-product template,
      including `wc_get_stock_html()` → `<p class="stock in-stock">41 in
      stock</p>`. If the template ALSO renders our designed
      `wp:woocommerce/product-stock-indicator` block (which we use to style
      stock copy in the theme's voice — uppercase, tracked, etc.), the
      product page shows "in stock" twice on every PDP. Reviewers consistently
      flag this as the most obvious "default WooCommerce theme" tell on the
      page.

      The fix is a top-level `styles.css` rule that hides the form's
      `<p class="stock">` (and the variation-availability paragraph it shows
      for variable products as the shopper picks attributes). Block-scoped
      `styles.blocks["woocommerce/add-to-cart-form"].css` is NOT enough
      because WP wraps that field in `:root :where(...)` (specificity 0,0,1)
      and WC's stock paragraph CSS hits 0,0,2 — see `check_wc_overrides_styled`
      for the full specificity story.

    What this check enforces, ONLY when the template renders both blocks
    together (i.e. the duplicate is actually possible):

      - Top-level `styles.css` must include selectors that match the form's
        `.stock` element under at least one of: `form.cart` (legacy +
        block-rendered form, the latter inherits `class="cart"`),
        `.wp-block-add-to-cart-form` (the block's outer wrapper),
        `.wc-block-add-to-cart-form__stock` (newer WC versions).
      - It must include a kill declaration (`display:none` or `visibility:hidden`).
      - Variation availability (`.woocommerce-variation-availability`) should
        also be hidden — variable products show a SECOND duplicate "in stock"
        paragraph as the shopper picks attributes if you only hide the form's
        initial one.

    See AGENTS.md rule 6.
    """
    r = Result("No duplicate stock indicator on single-product templates")

    template_paths = [
        ROOT / "templates" / "single-product.html",
        ROOT / "templates" / "single-product-variable.html",
    ]
    template_paths = [p for p in template_paths if p.exists()]
    if not template_paths:
        r.skip("no single-product template found in this theme")
        return r

    needs_hide_rule = False
    triggering_template: Path | None = None
    for path in template_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        renders_indicator = (
            re.search(r"<!--\s*wp:woocommerce/product-stock-indicator(?:\s|/|-->)", text)
            is not None
        )
        renders_form = (
            re.search(r"<!--\s*wp:woocommerce/add-to-cart-form(?:\s|/|-->)", text) is not None
        )
        if renders_indicator and renders_form:
            needs_hide_rule = True
            triggering_template = path
            break

    if not needs_hide_rule:
        r.skip("template doesn't render both product-stock-indicator and add-to-cart-form")
        return r

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing — cannot verify the stock-hide rule.")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    top_css_norm = re.sub(r"\s+", "", top_css)

    # The hide rule needs both: a selector that matches the form's .stock,
    # and a declaration that suppresses it. Accept any of the three known
    # WC selector roots so this check is robust across WC releases.
    selector_roots = [
        "form.cart.stock",
        ".wp-block-add-to-cart-form.stock",
        ".wc-block-add-to-cart-form__stock",
    ]
    matched_selector = next(
        (sel for sel in selector_roots if sel in top_css_norm),
        None,
    )
    if matched_selector is None:
        r.fail(
            f"{triggering_template.relative_to(ROOT).as_posix()} renders both "
            f"`wp:woocommerce/product-stock-indicator` (designed copy) and "
            f"`wp:woocommerce/add-to-cart-form` (which renders WC's native "
            f'`<p class="stock">` above the quantity input). The result is '
            f'"in stock" appearing twice on every PDP. Add a rule to '
            f"top-level `styles.css` matching one of "
            f"{selector_roots} (whitespace ignored) and "
            f"`display:none` so the form's stock paragraph is hidden. The "
            f"recommended selector list is: `form.cart .stock,"
            f".wp-block-add-to-cart-form .stock,"
            f".wc-block-add-to-cart-form__stock,"
            f".woocommerce-variation-availability {{ display: none; }}`. "
            f'Block-scoped `styles.blocks["woocommerce/add-to-cart-form"]'
            f".css` does NOT work — see check_wc_overrides_styled."
        )
        return r

    if "display:none" not in top_css_norm and "visibility:hidden" not in top_css_norm:
        r.fail(
            f"top-level `styles.css` matches `{matched_selector}` but never "
            f"declares `display:none` (or `visibility:hidden`). The form's "
            f'`<p class="stock">` is still visible — duplicating the '
            f"designed product-stock-indicator above."
        )
        return r

    if ".woocommerce-variation-availability" not in top_css_norm:
        r.fail(
            "stock paragraph is hidden, but `.woocommerce-variation-"
            "availability` isn't. On variable products WC renders a SECOND "
            'duplicate `<p class="stock">`-style line under the variation '
            "selector as the shopper picks attributes. Add "
            "`.woocommerce-variation-availability` to the same hide rule."
        )
        return r

    r.details.append(
        f"matched `{matched_selector}` + `display:none` + variation-"
        f"availability hide in top-level styles.css"
    )
    return r


def _srgb_lin(c: float) -> float:
    """sRGB component (0..1) -> linear-light component for WCAG luminance."""
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _wcag_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance for a #RRGGBB hex string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return 0.2126 * _srgb_lin(r) + 0.7152 * _srgb_lin(g) + 0.0722 * _srgb_lin(b)


def _wcag_contrast(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB hex strings (1..21)."""
    la, lb = _wcag_luminance(hex_a), _wcag_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def check_hover_state_legibility() -> Result:
    """Fail if any `:hover` / `:focus` / `:focus-visible` / `:active` rule
    in top-level `styles.css` produces text that's effectively invisible
    against the background it sits on.

    Why this exists:
      A theme can pass every other check and still ship a hover state
      that paints text in a color with ~1:1 contrast against the page.
      The classic case (caught in production review on chonk's cart
      page): `.button:hover { background: var(--accent); }` paints a
      yellow surface, but the button's default `color: var(--base)` is
      kept — so the button text becomes cream-on-yellow, contrast ~1.1:1,
      effectively invisible. Same shape: `.link:hover { color:
      var(--accent); }` on a theme whose accent is a saturated near-base
      hue (chonk's `#FFE600` sits 1.12:1 above the cream `--base`;
      lysholm's `#C9A97C` sits 2.04:1 above the cream `--base`).

      The bug is endemic to themes that copy WC override boilerplate
      across files without re-checking palette interactions: the same
      ruleset that's fine on a theme with a high-contrast accent silently
      fails on a theme whose accent collapses against the body bg. We
      need a check that runs *after* the palette and *after* the rules
      have been applied so it catches the palette/rule interaction.

    What this check enforces:
      For every rule in top-level `styles.css` whose selector contains
      `:hover`, `:focus`, `:focus-visible`, or `:active`:

      1. **Resolve effective text color.**
         - If the rule sets `color: var(--wp--preset--color--<X>)`, use
           palette[X].
         - Otherwise assume default `--contrast` (the inherited body
           text color in every theme in the monorepo).
      2. **Resolve effective background color.**
         - If the rule sets `background:` or `background-color:` to a
           palette token, use that.
         - If the rule sets a non-palette background (gradient, hex,
           transparent, none, etc.), skip the rule — we can't reason
           about contrast against an arbitrary value.
         - Otherwise assume default `--base` (the body background).
      3. **Compute WCAG contrast ratio** between the two resolved hex
         colors and require ≥ 3.0:1 (WCAG 2.x AA-Large bar — relaxed
         for state changes since they're typically transient and rarely
         long-form prose). Below 3.0 fails.

      Bullets 1+2 are deliberately conservative: an explicit text +
      explicit bg in the same rule are checked against each other; an
      explicit bg with no text declaration is checked against the
      assumed-default text color. The latter is exactly the
      `bg:accent` button-hover footgun.

    Tokens not present in the palette (e.g. typo, theme-specific custom
    name) are silently skipped so a typo doesn't masquerade as a
    contrast bug — `check_no_hex_in_theme_json` and theme.json schema
    validation catch those.
    """
    r = Result("Hover/focus states have legible text-vs-background contrast")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    palette_list = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    palette: dict[str, str] = {
        p["slug"]: p["color"]
        for p in palette_list
        if isinstance(p, dict)
        and isinstance(p.get("slug"), str)
        and isinstance(p.get("color"), str)
        and re.fullmatch(r"#[0-9A-Fa-f]{6}", p.get("color", ""))
    }
    if not palette or "base" not in palette or "contrast" not in palette:
        r.skip("palette is missing required `base` or `contrast` slug")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # Default text + bg if a rule doesn't set them and no resting state
    # is found. Every theme in the monorepo inherits
    # body { color: contrast; background: base; }.
    DEFAULT_TEXT = palette["contrast"]
    DEFAULT_BG = palette["base"]

    state_re = re.compile(r":(hover|focus|focus-visible|active)\b")
    # The slug terminator is `[)\s,]` (not just `)`) so fallback syntax
    # like `color:var(--wp--preset--color--accent,var(--wp--preset--color--contrast))`
    # captures the primary slug (accent). The CSS cascade paints the
    # first var in the chain that resolves; since every theme in this
    # repo defines every palette slug, the first slug is what shows.
    color_re = re.compile(
        r"(?:^|[;{\s])color\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)(?=[\s,)])"
    )
    bg_re = re.compile(
        r"\bbackground(?:-color)?\s*:\s*var\(--wp--preset--color--([a-z0-9-]+)(?=[\s,)])"
    )
    bg_unrecognised_re = re.compile(
        r"\bbackground(?:-color)?\s*:\s*(?!var\(--wp--preset--color--)([^;}]+)"
    )
    state_strip_re = re.compile(r":(?:hover|focus|focus-visible|active)\b")

    # Pre-build an index of every rule body by individual selector so we
    # can look up the resting-state declarations a `:hover` rule
    # inherits from. Necessary because a hover rule like
    # `.btn:hover { background: var(--accent); }` doesn't declare
    # `color:` -- but the resting `.btn { color: var(--base); }` does,
    # and that's the color that actually paints the hover text.
    rest_index: dict[str, list[str]] = {}
    for rest_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sel_group, body_group = rest_match.group(1), rest_match.group(2)
        if state_re.search(sel_group):
            continue  # Only index resting-state rules.
        for raw_sel in sel_group.split(","):
            key = raw_sel.strip()
            if key:
                rest_index.setdefault(key, []).append(body_group)

    def _resting_color_token(hover_selectors: str) -> str | None:
        """For each comma-separated selector in the hover rule, strip the
        state pseudo-class and look up the resting rule(s). Return the
        first palette `color:` token declared on the resting state, or
        None if no resting rule sets one. We pick the first match in
        source order, which mirrors how a single rule's inherited text
        color gets resolved in practice (the most-specific resting rule
        for that exact selector is what wins for the hover state)."""
        for raw_sel in hover_selectors.split(","):
            resting_sel = state_strip_re.sub("", raw_sel).strip()
            if not resting_sel:
                continue
            for rest_body in rest_index.get(resting_sel, ()):
                m = color_re.search(rest_body)
                if m:
                    return m.group(1)
        return None

    # Build an index of body.theme-<slug> overrides so we can honour
    # per-theme cascade winners when evaluating generic rules. Each entry
    # maps a trailing selector (the part after `body.theme-<slug> `) to a
    # list of rule bodies that override it in the current theme context.
    # Overrides from other themes (`body.theme-<other>`) are indexed under
    # their own slug so we can ignore them.
    theme_slug = ROOT.name
    # Match any body-class prefix scoped to the current theme, e.g.
    # `body.theme-foundry ` or the doubled-specificity variant
    # `body.theme-foundry.theme-foundry `.
    current_prefix_re = re.compile(rf"^body(?:\.theme-{re.escape(theme_slug)})+\s+")
    other_prefix_re = re.compile(r"^body\.theme-([a-z0-9-]+)")
    overrides_by_trailing: dict[str, list[str]] = {}
    for o_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        o_sels, o_body = o_match.group(1), o_match.group(2)
        if not state_re.search(o_sels):
            continue
        for raw in o_sels.split(","):
            norm = " ".join(raw.split())
            m = current_prefix_re.match(norm)
            if m:
                trailing = norm[m.end() :]
                overrides_by_trailing.setdefault(trailing, []).append(o_body)

    def _apply_theme_override(
        trailing_sels: str, base_color_token: str | None, base_bg_token: str | None
    ) -> tuple[str | None, str | None]:
        """For a generic rule's selector list, check if `body.theme-<slug>`
        redefines color/bg for any of those trailing selectors. If so, the
        override wins per cascade (specificity +1 from the body class).
        Returns (resolved_color_token, resolved_bg_token) — either inherited
        from the base rule or overridden by the per-theme scoped rule."""
        color_tok, bg_tok = base_color_token, base_bg_token
        for raw in trailing_sels.split(","):
            key = " ".join(raw.split())
            for o_body in overrides_by_trailing.get(key, ()):
                cm = color_re.search(o_body)
                if cm:
                    color_tok = cm.group(1)
                bm = bg_re.search(o_body)
                if bm:
                    bg_tok = bm.group(1)
        return color_tok, bg_tok

    failures: list[str] = []
    checked = 0

    for rule_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sels, body = rule_match.group(1), rule_match.group(2)
        if not state_re.search(sels):
            continue

        # The `[^{}]+` group eats any `/* ... */` comments that live
        # between the previous rule's `}` and this rule's `{`. Strip
        # them before doing any selector-prefix matching, or a rule
        # that follows a sentinel comment (`body.theme-cipher ...`
        # right after `/* wc-tells-phase-ff-hover-polarity-autoflip */`)
        # looks like it starts with `/*` instead of `body.`, and the
        # other-theme-prefix match below silently fails.
        sels = re.sub(r"/\*.*?\*/", "", sels, flags=re.DOTALL).strip()
        if not sels:
            continue

        # Rules scoped to a different theme via `body.theme-<other>` are
        # inert in the current theme's runtime — skip them so we don't
        # flag another theme's contrast choices against the current
        # theme's palette.
        first_sel = sels.strip().split(",")[0].strip()
        other_theme_match = other_prefix_re.match(first_sel)
        if other_theme_match and other_theme_match.group(1) != theme_slug:
            continue

        # Resolve text color: hover's own declaration wins; otherwise
        # inherit from the resting state of the same selector; otherwise
        # fall back to the body default.
        color_match = color_re.search(body)
        if color_match:
            text_token = color_match.group(1)
            text_source = "hover"
        else:
            inherited = _resting_color_token(sels)
            if inherited is not None:
                text_token = inherited
                text_source = "inherited from resting state"
            else:
                text_token = None
                text_source = "body default"
        text_hex = palette.get(text_token) if text_token else DEFAULT_TEXT
        if text_token and text_hex is None:
            # Token not in palette (typo / custom name) — skip this rule.
            continue

        # Resolve background color.
        bg_match = bg_re.search(body)
        bg_token = bg_match.group(1) if bg_match else None
        bg_hex = palette.get(bg_token) if bg_token else None
        if bg_token and bg_hex is None:
            continue
        if bg_hex is None:
            # No palette bg in this rule. If the rule sets a non-palette
            # background (gradient, hex, transparent, etc.), we can't
            # reason about it — skip. Otherwise assume body default.
            unrec = bg_unrecognised_re.search(body)
            if unrec:
                continue
            bg_hex = DEFAULT_BG

        # Honour per-theme `body.theme-<slug>` cascade overrides. If this
        # is a generic rule that a theme-scoped rule redefines (higher
        # specificity), swap in the override's color/bg before computing
        # contrast — that's what paints at runtime for the current theme.
        if not other_theme_match:
            ov_color_tok, ov_bg_tok = _apply_theme_override(sels, text_token, bg_token)
            if ov_color_tok != text_token and ov_color_tok in palette:
                text_token = ov_color_tok
                text_hex = palette[ov_color_tok]
                text_source = f"overridden by body.theme-{theme_slug}"
            if ov_bg_tok != bg_token and ov_bg_tok in palette:
                bg_token = ov_bg_tok
                bg_hex = palette[ov_bg_tok]

        ratio = _wcag_contrast(text_hex, bg_hex)
        checked += 1
        if ratio < 3.0:
            # Pretty-print the offending selector list, capped to keep
            # the failure log scannable.
            sel_pretty = " ".join(sels.split())
            if len(sel_pretty) > 140:
                sel_pretty = sel_pretty[:137] + "..."
            color_desc = (
                f"`color: var(--{text_token})` ({text_hex}, {text_source})"
                if text_token
                else f"`color: var(--contrast)` ({text_hex}, body default)"
            )
            bg_desc = (
                f"`background: var(--{bg_token})` ({bg_hex})"
                if bg_token
                else f"inherited `background: var(--base)` ({bg_hex})"
            )
            failures.append(
                f"{sel_pretty}: {color_desc} vs {bg_desc} = "
                f"{ratio:.2f}:1, below the 3:1 floor. The hover state "
                f"renders the text effectively invisible against its "
                f"new background. Either flip `color:` to a palette "
                f"token that has ≥3:1 contrast with the new background "
                f"(usually `--contrast` for bright accents, `--base` "
                f"for dark backgrounds), or replace the bg-color shift "
                f"with a non-color hover signal (border, shadow, "
                f"underline-via-text-decoration-color)."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(f"{checked} hover/focus state rule(s) verified at ≥3:1 contrast")
    return r


# ---------------------------------------------------------------------------
# check_palette_polarity_coherent — catches the "partial spec left source
# palette slugs as stale leftovers" footgun that cratered cipher's build
# smoke on 2026-04-28. A theme.json whose `base` is dark but whose
# `subtle` is obel's cream near-white silently ships cream-on-near-white
# text sitewide (1.17:1) and fires 70+ axe color-contrast findings.
# ---------------------------------------------------------------------------

# Palette slugs that MUST share `base`'s luminance side (both light-half
# or both dark-half). These are the tokens the monorepo's block / WC /
# override CSS paints AS BACKGROUNDS at high density — if any of them
# flips polarity away from `base`, the text tokens drawn on top of them
# (which expect a `base`-polarity surface) become invisible.
#
# Why these specific slugs:
#   subtle      — the `.has-subtle-background-color` block class, used
#                 heavily across obel's inherited templates for quiet
#                 section backgrounds (3,000+ refs monorepo-wide). A
#                 polarity flip here paints 22-29 nodes per page at
#                 sub-1.2:1 contrast.
#   surface     — explicit card surfaces (cart sidebar, checkout
#                 sidebar, mini-cart drawer). Flipping surface against
#                 base shows up immediately in cart/checkout snapshots.
#   accent-soft — paired with accent; painted as soft fill on hover
#                 and on promo strips. Obel's `#EFD9C3` on a dark-base
#                 theme paints text-on-peach at 1.03:1.
#
# NOT in this set (on purpose):
#   muted       — `basalt/theme.json`'s `#9e9e9e` is a legitimate mid-
#                 gray tone intended for muted text, not for painting
#                 backgrounds. Holding it to strict polarity would
#                 false-positive on basalt without a matching snap-
#                 level contrast failure (axe confirms basalt's actual
#                 `muted`-painted surfaces still clear AA). If a muted
#                 surface ever DOES fail contrast, `check_block_text_
#                 contrast` + axe's `a11y-color-contrast` will catch it
#                 — the polarity check doesn't need to.
#   accent, secondary, tertiary, primary, primary-hover, border, status
#               — each of these either gets painted as text (covered by
#                 contrast ratio checks) or has semantics that flex
#                 across palettes (status colors can be dark OR light
#                 as long as they clear AA against base).
_BASE_POLARITY_SAMESIDE_SLUGS = frozenset({"subtle", "surface", "accent-soft"})

# Semantic opposite of base: must land on the OTHER luminance side.
# Kept tight — most "text" tokens flex across palettes so we don't
# enforce polarity on them.
_BASE_POLARITY_OPPOSITE_SLUGS = frozenset({"contrast"})


def check_palette_polarity_coherent() -> Result:
    """Fail if `settings.color.palette` contains a slug whose luminance
    polarity contradicts its semantic role against `base`.

    Why this exists (the 2026-04-28 cipher incident):
        `_design_lib.apply_palette` explicitly documents "slugs the spec
        doesn't mention are left untouched". When a spec inherits from
        obel but flips `base` from light → dark (or vice versa) and
        doesn't enumerate the full 16-slug palette, obel's `subtle`
        (`#F2F1EC`, near-white) stays in the child theme's palette next
        to the new dark `base`. Every block that paints
        `.has-subtle-background-color` then renders the child theme's
        `contrast` token (cream) on obel's leftover near-white — 1.17:1
        — and axe flags 20-29 nodes per page with `color-contrast`.

        The failure is invisible on every shipping theme because each
        of their specs historically enumerated the full palette; the
        first partial-spec authored by an LLM (or a terser hand-written
        one) cratered on a gate no existing check could name. This
        check closes the hole so the same shape can't ship again.

    What this enforces:
        1. `base` polarity is the theme's self-identified light/dark
           axis (`_wcag_luminance(base) >= 0.5` → light; else dark).
        2. Every `_BASE_POLARITY_SAMESIDE_SLUGS` entry present in the
           palette MUST have the same polarity (both halves of a
           well-chosen palette are either clustered near `base` or
           clustered near `contrast` — we care about the first group).
        3. Every `_BASE_POLARITY_OPPOSITE_SLUGS` entry (just `contrast`
           for now) MUST have the opposite polarity — a theme that
           declared `base` dark and `contrast` also dark would paint
           invisible body text.

        Slugs not in either set are skipped; the narrowness of this
        check is intentional. Widening it risks false positives on
        themes with legitimately low-contrast accent tokens
        (iridescents, dark-on-dark decoratives).

    What this check does NOT do:
        - It does NOT compute contrast ratios. `check_block_text_contrast`
          and `check_hover_state_legibility` are the AA-ratio gates;
          this check only catches POLARITY inversion, the failure mode
          ratio-based checks can't name ("your subtle is too close to
          contrast's side of the palette" is a structural statement,
          not a numeric one).
        - It does NOT fix anything. A failure here means the spec
          under-covered the source palette; the remedy is to extend
          the spec's `palette` block to include the flagged slugs.
        - It does NOT look at source-theme lineage. A hand-edited
          `theme.json` with a mismatched `subtle` will fail the same
          way a `design.py apply` with a partial spec does — which is
          intentional (the check is a property of the artifact, not
          of how it got there).

    Remediation hint:
        The failure message names each mismatched slug, its current
        hex, its luminance, and the polarity side `base` expects. The
        operator then either extends their spec or edits `theme.json`
        directly. If this fires in CI, the commit author should inspect
        `settings.color.palette` in their theme.json — every slug named
        in the failure is a leftover from the source theme.
    """
    r = Result("Palette slug luminance polarity is coherent with base")

    theme_json_path = ROOT / "theme.json"
    if not theme_json_path.is_file():
        r.skip("no theme.json on disk")
        return r

    try:
        theme_json = json.loads(theme_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Another check (`check_json_validity`) will fail loudly on this;
        # skipping here keeps the polarity check's diagnostic focused
        # on its own concern.
        r.skip("theme.json is not valid JSON (see check_json_validity)")
        return r

    palette_entries = theme_json.get("settings", {}).get("color", {}).get("palette", [])
    by_slug = {
        entry["slug"]: entry["color"]
        for entry in palette_entries
        if isinstance(entry, dict) and "slug" in entry and "color" in entry
    }

    base = by_slug.get("base")
    if not base or not isinstance(base, str) or not base.startswith("#"):
        r.skip("no `base` slug with a hex value in palette")
        return r

    try:
        base_lum = _wcag_luminance(base)
    except (ValueError, IndexError):
        r.skip(f"could not parse base color `{base}`")
        return r

    base_side = "light" if base_lum >= 0.5 else "dark"
    failures: list[str] = []
    checked = 0

    def _polarity_side(hex_color: str) -> str | None:
        try:
            return "light" if _wcag_luminance(hex_color) >= 0.5 else "dark"
        except (ValueError, IndexError):
            return None

    for slug in sorted(_BASE_POLARITY_SAMESIDE_SLUGS):
        hex_value = by_slug.get(slug)
        if not hex_value or not isinstance(hex_value, str) or not hex_value.startswith("#"):
            continue
        side = _polarity_side(hex_value)
        if side is None:
            continue
        checked += 1
        if side != base_side:
            lum = _wcag_luminance(hex_value)
            failures.append(
                f"`{slug}: {hex_value}` (luminance {lum:.3f}, {side}-side) "
                f"opposes `base: {base} ({base_lum:.3f}, {base_side}-side). "
                f"This slug is painted AS A BACKGROUND by inherited obel "
                f"templates; text drawn on it will paint against a "
                f"{side}-side surface while the rest of the theme assumes "
                f"{base_side}-side backgrounds → near-zero contrast on "
                f"every page that uses `.has-{slug}-background-color`."
            )

    for slug in sorted(_BASE_POLARITY_OPPOSITE_SLUGS):
        hex_value = by_slug.get(slug)
        if not hex_value or not isinstance(hex_value, str) or not hex_value.startswith("#"):
            continue
        side = _polarity_side(hex_value)
        if side is None:
            continue
        checked += 1
        if side == base_side:
            lum = _wcag_luminance(hex_value)
            failures.append(
                f"`{slug}: {hex_value}` (luminance {lum:.3f}, {side}-side) "
                f"shares a side with `base: {base} ({base_lum:.3f}, {base_side}-side). "
                f"`contrast` is the body-text token — same-side as base means "
                f"body text is effectively invisible (the only AA ratio you "
                f"can get is between two similar-luminance colors, which "
                f"tops out around 1.5:1)."
            )

    if failures:
        # `relative_to` can raise when tests point `check.ROOT` outside
        # the monorepo (pytest tmp_path lives under /private/var/...);
        # fall back to the absolute path so the diagnostic stays
        # readable either way.
        try:
            path_label = str(theme_json_path.relative_to(MONOREPO_ROOT))
        except ValueError:
            path_label = str(theme_json_path)
        r.fail(
            f"{len(failures)} palette slug(s) have polarity mismatched with "
            f"`base`. This is almost always a symptom of a `design.py apply` "
            f"spec that under-covered the source palette — obel's 16 palette "
            f"slugs weren't all enumerated, and the untouched ones retained "
            f"their light-theme defaults against a new dark base (or vice "
            f"versa). Fix by extending the spec's `palette` block to include "
            f"these slugs, or by editing `settings.color.palette` in "
            f"`{path_label}` directly."
        )
        for msg in failures:
            r.details.append(msg)
        return r

    r.details.append(
        f"all {checked} polarity-significant palette slug(s) land on the "
        f"correct side of `base` ({base_side}-side)."
    )
    return r


def check_background_clip_text_legibility() -> Result:
    """Fail if any `background-clip: text` rule paints text using a
    gradient whose stops are ALL too light to read against the body
    background.

    Why this exists:
      The "chrome wordmark" pattern -- `background: linear-gradient(...);
      -webkit-background-clip: text; color: transparent;` -- is a common
      way to make a brand title look metallic/iridescent. But if every
      gradient stop is a pale palette token (e.g. `--surface`, `--muted`,
      `--tertiary-light`), the text becomes invisible against a pale
      body background. In-production example: Aero's footer wordmark was
      `linear-gradient(surface → muted → tertiary → muted → surface)`
      clipped to text; on the #F5EEFF body, only the middle 20% (the
      tertiary stop) was readable -- the wordmark looked like a faint
      ghost and the site's brand disappeared.

      The bug is particularly nasty because it passes
      `check_hover_state_legibility` (which only looks at explicit
      `color:` tokens, and these rules declare `color: transparent`)
      and it passes axe-core (which can't evaluate gradient-clipped
      text). We need a targeted check that knows about the pattern.

    What this check enforces:
      For every CSS rule in top-level `styles.css` whose body contains
      `background-clip: text` (or the `-webkit-` prefix):

      1. Pull every `var(--wp--preset--color--<slug>)` token out of the
         rule's `background:` (or `background-image:`) declaration.
      2. Resolve each token to its hex via the theme palette.
      3. Require at least ONE stop to have ≥3:1 WCAG contrast against
         `--base` (the body background). 3:1 is the WCAG AA-Large bar,
         which is correct here: `background-clip: text` is almost always
         applied to large display type (headings, wordmarks), never to
         body copy.

      If all stops fall below 3:1, the wordmark is effectively
      invisible across at least half its height, and we fail with a
      pointer to the actual palette stops that need replacing.

    Rules whose gradient references non-palette values (raw hex,
    `rgba(...)`, `currentColor`, etc.) are skipped -- we can't reason
    about contrast for an arbitrary gradient -- but rules with a
    mix of palette + raw-hex stops still fail if all their PALETTE
    stops fail, because the raw-hex stops are not covered by palette
    tokens this check is meant to gate.
    """
    r = Result("Text clipped to a gradient has at least one readable stop")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    palette_list = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    palette: dict[str, str] = {
        p["slug"]: p["color"]
        for p in palette_list
        if isinstance(p, dict)
        and isinstance(p.get("slug"), str)
        and isinstance(p.get("color"), str)
        and re.fullmatch(r"#[0-9A-Fa-f]{6}", p.get("color", ""))
    }
    if not palette or "base" not in palette:
        r.skip("palette is missing required `base` slug")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    base_hex = palette["base"]

    # `background-clip: text` is the trigger. Match it case-insensitively
    # and allow the -webkit- prefix. We deliberately require the whole
    # declaration (`<prop>: text`) so we don't false-positive on e.g.
    # `content-clip: text` hypothetical names.
    clip_re = re.compile(r"(?:-webkit-)?background-clip\s*:\s*text\b", re.IGNORECASE)
    bg_decl_re = re.compile(r"\bbackground(?:-image)?\s*:\s*([^;}]+)", re.IGNORECASE)
    token_re = re.compile(r"var\(--wp--preset--color--([a-z0-9-]+)\)")

    checked = 0
    failures: list[str] = []

    for rule_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sels, body = rule_match.group(1), rule_match.group(2)
        if not clip_re.search(body):
            continue

        # Pull the first palette-tokenized gradient we see. Real themes
        # only ever declare one `background:` per rule.
        tokens: list[str] = []
        for bg_match in bg_decl_re.finditer(body):
            tokens.extend(token_re.findall(bg_match.group(1)))

        if not tokens:
            # Gradient references non-palette colors only (raw hex,
            # rgba, currentColor, ...). We can't reason about contrast
            # for arbitrary stops, so skip rather than false-positive.
            continue

        stops = [(t, palette[t]) for t in tokens if t in palette]
        if not stops:
            continue

        checked += 1
        best_ratio = 0.0
        best_token = ""
        for token, hex_val in stops:
            ratio = _wcag_contrast(hex_val, base_hex)
            if ratio > best_ratio:
                best_ratio = ratio
                best_token = token

        if best_ratio < 3.0:
            sel_pretty = " ".join(sels.split())
            if len(sel_pretty) > 140:
                sel_pretty = sel_pretty[:137] + "..."
            stop_desc = ", ".join(
                f"--{t} ({h}, {_wcag_contrast(h, base_hex):.2f}:1)" for t, h in stops
            )
            failures.append(
                f"{sel_pretty}: background-clip:text with gradient stops "
                f"[{stop_desc}] against --base ({base_hex}). "
                f"Best stop is `--{best_token}` at {best_ratio:.2f}:1, "
                f"below the 3:1 large-text floor. The wordmark/heading "
                f"will be effectively invisible against the body bg. "
                f"Swap at least one stop to a dark palette token "
                f"(typical: `--contrast`, `--primary`, `--secondary`, "
                f"or `--accent` if it's saturated enough), and keep a "
                f"`color:` fallback on the base rule so the text stays "
                f"readable if `background-clip:text` is unsupported."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if checked == 0:
        r.skip("no background-clip:text rules in top-level styles.css")
    else:
        r.details.append(
            f"{checked} background-clip:text rule(s) verified: at least "
            f"one gradient stop ≥3:1 vs --base"
        )
    return r


def check_nav_item_pill_scoped_to_horizontal() -> Result:
    """Fail if `.wp-block-navigation-item__content` is given a horizontal
    pill treatment (non-zero inline padding, rounded-pill radius, and/or
    a hover background) without scoping the rule to horizontal-only
    navigation.

    Why this exists:
      WordPress renders the same DOM (`.wp-block-navigation-item__content`)
      for both header (horizontal) and footer/sidebar (vertical) nav.
      A theme often wants header links to look like rounded pills with
      an on-hover tinted capsule -- but the same rule blindly applied
      to a vertical footer column makes every link an isolated pill
      that inherits the header's horizontal inline padding, blowing
      out the vertical rhythm and mis-aligning the links with their
      column headings. In-production example (caught 2026-04-22 on
      Aero): `body.theme-aero .wp-block-navigation
      .wp-block-navigation-item__content { padding: xs md !important; }`
      was intended for the header's horizontal bar, but because the
      selector didn't discriminate orientation, Aero's footer rendered
      each "All products / Lookbook / Cart / My account" link with
      wasted horizontal space and a distracting pill-on-hover flash.

    What this check enforces:
      For every rule in top-level `styles.css` whose selector ends with
      `.wp-block-navigation-item__content` (or its `:hover`/`:focus`
      state):

      1. If the selector already restricts orientation via
         `:not(.is-vertical)`, `.is-horizontal`, or a header-scoped
         ancestor (`header`, `.site-header`, `.aero-header__...`,
         `.wp-block-template-part[data-slug*="header"]`, etc.), skip
         the rule -- correctly scoped.
      2. Otherwise, fail if the rule body declares ANY of:
         - a `padding:` / `padding-inline:` / `padding-left|right:` with
           a non-zero value (the horizontal pill breathing room);
         - a `border-radius:` that resolves to a pill / "9999px" / 50%
           (the capsule silhouette);
         - a `:hover` or `:focus` state setting a non-transparent
           `background:` / `background-color:` (the tinted-capsule
           flash that reads wrong in a vertical column).

      These are the three signatures of a "pill hover" treatment that
      only belongs on a horizontal bar. Rules that just set `color:`,
      `text-decoration:`, or `padding-block:` (vertical padding only)
      are fine for both orientations and pass.
    """
    r = Result("Nav-item pill treatment is scoped to horizontal-only nav")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # Selector must mention the nav-item content class. We match the
    # class loosely so `.wp-block-navigation-item__content::after`
    # and `.wp-block-navigation-item__content:hover` both count.
    nav_item_re = re.compile(r"\.wp-block-navigation-item__content\b")

    # Signals that a selector is already correctly scoped to a
    # horizontal context. Any ONE of these is enough.
    horizontal_scope_re = re.compile(
        r":not\(\.is-vertical\)"
        r"|\.is-horizontal\b"
        r"|(?:^|[,\s>+~])header\b"
        r"|\.site-header\b"
        r"|\.wp-site-blocks\s*>\s*header\b"
        r"|\[data-slug\*?=[\"']?header"
        r"|[a-zA-Z0-9_-]*-header(?:__[a-zA-Z0-9_-]+)?",
    )

    # Signals inside the rule body that this IS pill treatment.
    # 1. non-zero horizontal padding.
    pad_all_re = re.compile(r"(?:^|[;{\s])padding\s*:\s*([^;}]+)", re.IGNORECASE)
    pad_inline_re = re.compile(
        r"(?:^|[;{\s])padding-(?:inline|left|right)\s*:\s*([^;}]+)",
        re.IGNORECASE,
    )
    # 2. pill-ish radius.
    radius_re = re.compile(r"(?:^|[;{\s])border-radius\s*:\s*([^;}]+)", re.IGNORECASE)
    # 3. :hover/:focus bg.
    state_re = re.compile(r":(?:hover|focus|focus-visible|active)\b")
    bg_re = re.compile(r"(?:^|[;{\s])background(?:-color)?\s*:\s*([^;}]+)", re.IGNORECASE)

    def _has_nonzero_horizontal_padding(body: str) -> bool:
        # `padding: <top> <right> <bottom> <left>` shorthand: a non-zero
        # 2nd or 4th value implies horizontal padding.
        m = pad_all_re.search(body)
        if m:
            parts = m.group(1).strip().split()
            # 1 value applies to all sides, 2 -> (v, h), 3 -> (t, h, b),
            # 4 -> (t, r, b, l). For our purposes, any non-"0" value in
            # a slot that covers horizontal is a hit.
            horizontal_slots: list[str] = []
            if len(parts) == 1:
                horizontal_slots = parts
            elif len(parts) in (2, 3):
                horizontal_slots = [parts[1]]
            elif len(parts) >= 4:
                horizontal_slots = [parts[1], parts[3]]
            for slot in horizontal_slots:
                # Anything that isn't literally "0", "0px", "0rem",
                # "0em", or "initial"/"unset" counts as non-zero.
                s = slot.strip().removesuffix("!important").strip()
                if s.lower() not in ("0", "0px", "0rem", "0em", "unset", "initial", "none"):
                    return True
        # Dedicated padding-inline / padding-left / padding-right
        # with a non-zero value.
        for m2 in pad_inline_re.finditer(body):
            s = m2.group(1).strip().removesuffix("!important").strip().split()[0]
            if s.lower() not in ("0", "0px", "0rem", "0em", "unset", "initial", "none"):
                return True
        return False

    def _has_pill_radius(body: str) -> bool:
        m = radius_re.search(body)
        if not m:
            return False
        val = m.group(1).lower()
        return ("9999" in val) or ("50%" in val) or ("pill" in val) or ("--radius--pill" in val)

    def _has_state_bg(selectors: str, body: str) -> bool:
        if not state_re.search(selectors):
            return False
        m = bg_re.search(body)
        if not m:
            return False
        val = m.group(1).lower().strip()
        # `background: transparent|none|inherit|initial|unset` is a reset
        # (unscoped resets are fine -- the vertical nav will look
        # normal).
        non_trigger_first_tokens = {
            "transparent",
            "none",
            "inherit",
            "initial",
            "unset",
        }
        first_token = val.split()[0].rstrip(";").rstrip(",")
        return first_token not in non_trigger_first_tokens

    failures: list[str] = []
    checked = 0

    for rule_match in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        sels, body = rule_match.group(1), rule_match.group(2)
        if not nav_item_re.search(sels):
            continue
        # Evaluate each comma-separated selector independently. Even one
        # unscoped selector in a selector list is enough to over-apply.
        bad_selectors = []
        for raw_sel in sels.split(","):
            s = raw_sel.strip()
            if not nav_item_re.search(s):
                continue
            if horizontal_scope_re.search(s):
                continue
            bad_selectors.append(s)

        if not bad_selectors:
            checked += 1
            continue

        signals: list[str] = []
        if _has_nonzero_horizontal_padding(body):
            signals.append("non-zero horizontal padding (pill breathing room)")
        if _has_pill_radius(body):
            signals.append("pill-shaped border-radius")
        if _has_state_bg(sels, body):
            signals.append(":hover/:focus background fill (capsule flash)")
        # Require at least TWO signals to flag the rule. A single signal
        # alone is too weak: base rules often set a tiny optical
        # padding-inline (e.g. 2-xs ≈ 4px) on all nav items without
        # breaking the vertical layout. The footgun is the COMBINATION
        # (pill padding + pill radius, or hover-bg + pill padding),
        # which unambiguously announces "this is meant to be a
        # horizontal pill bar" and only-then is misapplied to the
        # vertical footer nav.
        if len(signals) < 2:
            checked += 1
            continue

        checked += 1
        sel_pretty = ", ".join(bad_selectors)
        if len(sel_pretty) > 180:
            sel_pretty = sel_pretty[:177] + "..."
        failures.append(
            f"{sel_pretty}: applies [{'; '.join(signals)}] to "
            f"`.wp-block-navigation-item__content` without scoping to a "
            f"horizontal-only context. The same rule hits the vertical "
            f"footer nav, where the pill/padding blows out link rhythm "
            f"and mis-aligns links with their column heading. Scope the "
            f"selector with `:not(.is-vertical)` (simplest), "
            f"`.is-horizontal`, or a header ancestor (`header`, "
            f"`.site-header`, `.{{theme}}-header__nav`). If the "
            f"vertical nav needs its own treatment, add a separate "
            f"`.is-vertical` rule."
        )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if checked == 0:
        r.skip("no .wp-block-navigation-item__content rules in top-level styles.css")
    else:
        r.details.append(
            f"{checked} nav-item rule(s) scoped correctly (horizontal-only or orientation-neutral)"
        )
    return r


def check_disabled_atc_button_styled_per_theme() -> Result:
    """Fail if a theme's `single_add_to_cart_button.disabled` /
    `:disabled` / `.wc-variation-selection-needed` state is not
    explicitly restated under `body.theme-<slug>`.

    Why this exists:
      Variable-product PDPs ship the WooCommerce add-to-cart button
      pre-disabled (until the shopper picks a variant). Without an
      explicit theme-scoped disabled-state rule, the browser drops the
      theme's `--contrast` paint and falls back to UA defaults: a flat
      ~#7B7974 / ~#8A8987 background under the theme's `--base` text.
      The result is a ~2.2-3.2:1 ratio (axe-core flags it as a
      `serious` `color-contrast` violation, blocking the AA 4.5:1
      threshold for body text). In-production example (caught
      2026-04-24 on Foundry's `/product/bottled-morning-variants/`):
      the "Into the parcel" button rendered as a muted khaki pill
      (~#9a9580 background, ~#f0e8d8 text) with WCAG ratio ~2.18:1.

      The fix is one line per theme that restates the active state's
      `--contrast` ground + `--base` ink, plus `opacity:1` and
      `cursor:not-allowed` so the disabled affordance is carried by
      the cursor rather than by fading the label below legibility.

    What this check enforces:
      For every theme (chonk, lysholm, obel, selvedge, foundry, aero
      -- the six theme slugs we ship), top-level `styles.css` MUST
      contain a rule whose selector starts with `body.theme-<slug> `
      (or `body.theme-<slug>.`) and matches at least one of:
        - `.single_add_to_cart_button.disabled`
        - `.single_add_to_cart_button:disabled`
        - `.single_add_to_cart_button.wc-variation-selection-needed`

      AND whose body sets a non-default `background:` (any value other
      than `transparent` / `inherit` / `initial`) so we know the rule
      is doing the contrast restoration.

    The check operates on the merged top-level `styles.css` of the
    current theme (not a multi-theme sweep), but it scans for the
    CURRENT theme's slug only. The append-wc-overrides.py phase-M
    block ships rules for ALL six themes into every theme.json (the
    selectors are body-scoped so they're inert in the wrong theme),
    so this check passes for any of the six theme dirs.

    See AGENTS.md "WooCommerce add-to-cart disabled state" rule.
    """
    r = Result("Disabled add-to-cart button has theme-scoped contrast rule")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # Identify which theme dir we're in via the directory name. Any
    # theme that ships a `single-product.html` template AND a
    # top-level `styles.css` with WC chrome is expected to paint the
    # disabled-ATC state per-theme. Previously the check hardcoded the
    # set of six original themes, which silently skipped every new
    # theme (basalt, etc.). Switching to a presence check means every
    # theme is gated.
    slug = ROOT.name.lower()
    has_pdp = (ROOT / "single-product.html").is_file() or (
        ROOT / "templates" / "single-product.html"
    ).is_file()
    if not has_pdp:
        r.skip(f"theme `{slug}` has no single-product.html — no PDP to gate")
        return r

    css_no_comments = re.sub(r"/\*.*?\*/", " ", top_css, flags=re.S)

    # Look for ANY rule containing both `body.theme-<slug>` and a
    # disabled-state selector. We're permissive on selector form
    # (any of the three signatures suffices) and just need one
    # non-transparent background declaration.
    body_re = re.escape(f"body.theme-{slug}")
    disabled_signature_re = re.compile(
        body_re
        + r"\s*[^{}]*?\.single_add_to_cart_button"
        + r"(?:\.disabled|:disabled|\.wc-variation-selection-needed)"
        + r"[^{}]*\{([^{}]*)\}",
        re.IGNORECASE,
    )

    found_rule = False
    has_background = False
    for m in disabled_signature_re.finditer(css_no_comments):
        found_rule = True
        body = m.group(1)
        # Reject `transparent` / `inherit` / `initial` / `none` -- the
        # rule has to actually paint a background.
        bg_match = re.search(r"background(?:-color)?\s*:\s*([^;}!]+)", body, re.IGNORECASE)
        if bg_match:
            value = bg_match.group(1).strip().lower()
            if value not in {"transparent", "inherit", "initial", "none", ""}:
                has_background = True
                break

    if not found_rule:
        r.fail(
            f"`body.theme-{slug}` has no disabled-state rule for "
            f"`.single_add_to_cart_button`. Variable-product PDPs ship "
            f"the button pre-disabled until a variant is picked; without "
            f"an explicit theme-scoped rule the browser falls back to "
            f"UA grey chrome (~2.2-3.2:1 contrast vs `--base` text), "
            f"which axe flags as a serious color-contrast violation. "
            f"Add a rule under `body.theme-{slug} "
            f".single_add_to_cart_button.disabled, "
            f"body.theme-{slug} .single_add_to_cart_button:disabled, "
            f"body.theme-{slug} "
            f".single_add_to_cart_button.wc-variation-selection-needed` "
            f"that restates `background:var(--wp--preset--color--contrast)`, "
            f"`color:var(--wp--preset--color--base)`, `opacity:1`, and "
            f"`cursor:not-allowed`. (See "
            f"`bin/append-wc-overrides.py` Phase M for the canonical "
            f"shape.)"
        )
        return r
    if not has_background:
        r.fail(
            f"`body.theme-{slug}` has a disabled-state selector for "
            f"`.single_add_to_cart_button` but doesn't paint a "
            f"non-transparent `background:`. The whole point of the "
            f"rule is to restore `--contrast` ground under `--base` "
            f"ink so the disabled paint clears WCAG AA 4.5:1. Add "
            f"`background:var(--wp--preset--color--contrast) "
            f"!important;` to the rule body."
        )
        return r

    r.details.append(
        f"`body.theme-{slug}` ships an explicit disabled-state rule "
        f"with a non-transparent background"
    )
    return r


def check_account_grid_scoped_to_sidebar() -> Result:
    """Fail if `.woocommerce-account .woocommerce` is given a sidebar-style
    two-column grid (`grid-template-columns: <fixed-px> 1fr`) without
    scoping the rule to the logged-in dashboard via
    `:has(>.woocommerce-MyAccount-navigation)` (or equivalent).

    Why this exists:
      WooCommerce's `/my-account/` page reuses the same body class
      (`woocommerce-account`) AND the same `.woocommerce` wrapper for
      both the logged-in dashboard (which DOES have a
      `.woocommerce-MyAccount-navigation` sidebar in column 1) and the
      logged-out login screen (which does NOT -- it only shows the WC
      login form, optionally wrapped in our branded `.wo-account-intro`
      + `.wo-account-login-grid` two-column split).

      The legacy rule `.woocommerce-account .woocommerce { display:grid;
      grid-template-columns: 220px 1fr }` was written for the dashboard,
      but because it's unscoped it ALSO fires on the logged-out login
      screen. There, the entire login form is the sole child of
      `.woocommerce`, so it gets crammed into the fixed 220px first
      column and the `1fr` column is empty. The login form then
      wraps every word and every INPUT field letter-by-letter down
      the page, producing a ~14000px-tall vertical stream of one
      character per line. In-production example (caught 2026-04-24
      on Aero / Chonk / Lysholm / Selvedge): `/my-account/` rendered
      the "Sign in" panel at clientWidth=65-66px with scrollWidth
      137-154px and a page height of 13672px. The page was still
      technically usable -- you could click through if you knew
      exactly where to aim -- but reviewers reliably read it as
      "the account page is broken".

    What this check enforces:
      For every rule in top-level `styles.css` whose selector contains
      `.woocommerce-account` AND whose body declares `display:grid`
      AND `grid-template-columns:` with a fixed-width first track
      (e.g., `220px 1fr`, `minmax(180px,220px) 1fr`, `200px 1fr`):

      1. If the selector already restricts via `:has(
         >.woocommerce-MyAccount-navigation)` or `:has(
         .woocommerce-MyAccount-navigation)` (logged-in dashboard
         only), skip the rule -- correctly scoped.
      2. If the selector already restricts via `.logged-in` or
         explicit body class, skip -- also correctly scoped.
      3. Otherwise, fail.

      Rules that write `grid-template-columns: 1fr` (single column,
      the reset) or `grid-template-columns: minmax(0,1fr)
      minmax(0,1fr)` (the logged-OUT 2-col login split) are fine and
      pass -- they don't introduce the 220px squeeze.

    See AGENTS.md "my-account logged-out login layout" rule.
    """
    r = Result("My-account grid is scoped to logged-in dashboard only")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # Find every rule whose selector mentions `.woocommerce-account`.
    # We need to collect (selector, body) pairs, stripped of comments.
    css_no_comments = re.sub(r"/\*.*?\*/", " ", top_css, flags=re.S)

    # Walk rules with a simple tokenizer that handles nested @media.
    # For simplicity, just find all top-level `selector{body}` pairs
    # without @media nesting detection -- media queries still get
    # surfaced.
    rule_re = re.compile(r"([^{}]+)\{([^{}]*)\}")

    # Fixed-width first track: accepts `220px 1fr`, `200px 1fr`,
    # `minmax(180px,220px) 1fr`, `minmax(200px,260px) 1fr`, etc.
    # Rejects `1fr`, `1fr 1fr`, `minmax(0,1fr) minmax(0,1fr)`.
    fixed_first_track_re = re.compile(
        r"grid-template-columns\s*:\s*"
        r"(?:\d+px|minmax\(\s*\d+px\s*,\s*\d+px\s*\))"
        r"\s+1fr",
        re.IGNORECASE,
    )

    # Acceptable scoping -- any ONE of these makes the rule safe.
    scoped_ok_re = re.compile(
        r":has\(\s*>?\s*\.woocommerce-MyAccount-navigation"
        r"|\.logged-in\b",
        re.IGNORECASE,
    )

    checked = 0
    failures = []
    for m in rule_re.finditer(css_no_comments):
        selector = m.group(1).strip()
        body = m.group(2).strip()

        # Selector must mention .woocommerce-account AND .woocommerce
        # (the combined dashboard/login wrapper). This keeps us from
        # matching unrelated rules.
        if ".woocommerce-account" not in selector:
            continue
        if ".woocommerce" not in selector.replace(".woocommerce-account", ""):
            # The selector only targets the BODY class, not the
            # wrapper -- those rules don't force a grid on the
            # wrapper and can't cause the squeeze.
            continue
        if "display:grid" not in re.sub(r"\s+", "", body):
            continue
        if not fixed_first_track_re.search(body):
            continue
        if scoped_ok_re.search(selector):
            checked += 1
            continue

        checked += 1
        sel_pretty = selector
        if len(sel_pretty) > 180:
            sel_pretty = sel_pretty[:177] + "..."
        body_pretty = re.sub(r"\s+", " ", body)
        if len(body_pretty) > 140:
            body_pretty = body_pretty[:137] + "..."
        failures.append(
            f"{sel_pretty} {{ {body_pretty} }}: forces a fixed-width "
            f"sidebar grid on `.woocommerce-account .woocommerce` "
            f"without scoping to the logged-in dashboard. The same "
            f"rule hits the logged-out `/my-account/` login screen, "
            f"which has no sidebar -- WC's login form then renders "
            f"inside the 220px first column and wraps letter-by-letter. "
            f"Scope the selector with "
            f"`:has(>.woocommerce-MyAccount-navigation)` so the grid "
            f"only fires on the dashboard; let the login screen fall "
            f"back to `display:block` or its own "
            f"`.wo-account-login-grid` 2-column layout."
        )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if checked == 0:
        r.skip("no fixed-width account grid rules in top-level styles.css")
    else:
        r.details.append(
            f"{checked} account-grid rule(s) scoped correctly "
            f"(`:has(>.woocommerce-MyAccount-navigation)` or logged-in)"
        )
    return r


def check_wc_card_surfaces_padded() -> Result:
    """Fail if any WC "panel/card" surface is given a `background:` in
    top-level `styles.css` without enough internal padding for the panel to
    breathe.

    Why this exists:
      The cart sidebar, checkout sidebar, mini-cart drawer, order-summary
      panel, etc. are *card surfaces* — opaque blocks that sit inside the
      page and hold dense compound content (subtotals, taxes, totals,
      coupon input, primary CTA, etc.). The moment we paint them with a
      non-transparent `background:` they READ as a panel and acquire the
      visual debt of a panel: shoppers expect generous internal padding,
      because the alternative — content butting up against the panel edge
      — looks like a half-finished plugin echo. The default WC theme.json
      block-scoped output ships these surfaces at `padding: lg` (≈24-40px
      depending on viewport), which is fine for type-only blocks but
      visibly cramped on a totals card with a price column on the right
      and a checkout button on the bottom. Reviewers reliably flag it as
      "feels like a default WooCommerce site".

      Worse, when these rules are written in `styles.blocks.*.css` they
      get wrapped in `:root :where(...)` (specificity 0,0,1) and lose the
      cascade fight with WC's own padding declarations. Once you've
      committed to overriding a card surface in top-level `styles.css`,
      the padding token MUST hold.

    What this check enforces:
      - For each KNOWN card surface (the WC selectors listed below),
        every top-level rule that sets a non-transparent `background:`
        must ALSO set padding (or padding-left + padding-right) using a
        spacing token of `xl` or larger.
      - Allowed tokens: `xl`, `2-xl`, `3-xl`, `4-xl`, `5-xl`. Anything
        smaller (`lg`, `md`, `sm`, `xs`, `2-xs`) fails — a panel painted
        with chrome below `xl` of internal padding is exactly the bug
        this check exists to prevent.
      - If a surface has padding split across multiple rules, ANY rule
        writing the bigger token is enough — we don't reject `padding:lg`
        if a sibling rule for the same selector sets `padding:xl` later.
        (This is permissive on purpose; the goal is "the panel breathes",
        not "the rule is written a specific way".)

      Surfaces that are styled but have no `background:` (transparent
      sections inside a parent panel) are skipped — they inherit the
      parent's padding context and don't need their own.

    See AGENTS.md "WooCommerce panel surfaces" rule.
    """
    r = Result("WC card surfaces have enough internal padding to breathe")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # WC selectors the theme paints as opaque card surfaces.
    # Add to this list as new surfaces get reskinned.
    CARD_SURFACES = [
        ".wc-block-cart__sidebar",
        ".wc-block-checkout__sidebar",
        ".wc-block-mini-cart__drawer .components-modal__content",
    ]

    # Spacing tokens that satisfy the "panel breathes" bar. Anything below
    # xl is intentionally rejected — see docstring.
    OK_TOKENS = ("xl", "2-xl", "3-xl", "4-xl", "5-xl")

    def _padding_token(decl_block: str) -> str | None:
        """Return the spacing slug used in `padding` / `padding-left` /
        `padding-right` declarations of a single CSS rule body, or None
        if no padding is set. Prefers `padding-left` over the shorthand
        because the shorthand can include 4 values."""
        # Try padding-left first (the side most visually responsible for
        # whether content reads as cramped against the panel edge).
        for prop in ("padding-left", "padding-inline", "padding"):
            for m in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                decl_block,
            ):
                value = m.group(1)
                token_match = re.search(
                    r"var\(--wp--preset--spacing--([a-z0-9-]+)\)",
                    value,
                )
                if token_match:
                    return token_match.group(1)
        return None

    # Walk every rule of the form `<selectors> { <decls> }`. Group rules
    # by the card surface they target, accumulating which tokens we've
    # seen for that surface — a surface passes if ANY of its rules use a
    # qualifying token.
    seen_surfaces: dict[str, list[str]] = {}
    bg_surfaces: set[str] = set()
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments from the selectors blob so a rule
        # whose head is glued to a sentinel comment (the way
        # `bin/append-wc-overrides.py` emits its chunks) still parses
        # cleanly — without this strip, the first selector in the
        # rule carries the leading `/* ... */` and never matches a
        # bare-string equality test.
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        # Multiple selectors per rule (`a, b, c { ... }`). For each card
        # surface, check if the rule's selector list mentions it as a
        # full selector (not a substring of a different selector — `+
        # \b` enforced by character-class lookbehind).
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        for surface in CARD_SURFACES:
            for sel in sel_list:
                if (
                    sel == surface
                    or sel.startswith(surface + " ")
                    or sel.endswith(" " + surface)
                    or sel.startswith(surface + ":")
                    or sel.startswith(surface + ".")
                ):
                    if sel != surface:
                        # Only the *bare* selector (no descendant /
                        # state suffix) describes the panel itself; a
                        # descendant rule like `.wc-block-cart__sidebar
                        # .wp-block-heading` is internal type, not the
                        # panel.
                        continue
                    has_bg = (
                        re.search(
                            r"\bbackground(?:-color)?\s*:\s*(?!transparent\b|none\b|inherit\b|initial\b|unset\b)[^;}]+",
                            body,
                        )
                        is not None
                    )
                    if has_bg:
                        bg_surfaces.add(surface)
                    token = _padding_token(body)
                    if token:
                        seen_surfaces.setdefault(surface, []).append(token)

    # Only enforce the rule on surfaces that are actually painted as
    # opaque panels in this theme. Untouched surfaces are skipped —
    # the theme might not render the cart/checkout at all.
    if not bg_surfaces:
        r.skip("no WC card surfaces are painted with a background in this theme")
        return r

    failures: list[str] = []
    for surface in sorted(bg_surfaces):
        tokens = seen_surfaces.get(surface, [])
        if not tokens:
            failures.append(
                f"{surface}: top-level rule sets `background:` but no "
                f"`padding` (or `padding-left` / `padding-inline`) was "
                f"found on the bare selector. A painted panel without "
                f"explicit padding inherits zero from WC's reset and "
                f"reads as cramped. Add `padding: var(--wp--preset--"
                f"spacing--xl)` (or larger)."
            )
            continue
        if not any(t in OK_TOKENS for t in tokens):
            failures.append(
                f"{surface}: rule(s) set `background:` and `padding: "
                f"var(--wp--preset--spacing--{tokens[0]})`, but `"
                f"{tokens[0]}` is below the `xl` panel-breathing bar. "
                f"On a card surface holding totals + a primary CTA, "
                f"`lg` and below visibly cramps the content against "
                f"the panel edge. Bump to `xl` or larger."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(f"{len(bg_surfaces)} painted card surface(s) — all use ≥xl internal padding")
    return r


def check_wc_totals_blocks_padded() -> Result:
    """Fail if `wp-block-woocommerce-cart-totals-block` or
    `wp-block-woocommerce-checkout-totals-block` doesn't carry an
    `xl`-or-larger padding declaration in top-level `styles.css`.

    Why this is its own check (vs piggybacking on
    `check_wc_card_surfaces_padded`):

    `check_wc_card_surfaces_padded` is gated on the surface having a
    NON-TRANSPARENT `background:` painted on it — the assumption is "if
    you painted it as a panel, give it panel padding". That gate is
    correct for the SIDEBAR WRAPPER (`.wc-block-cart__sidebar` /
    `.wc-block-checkout__sidebar`) because that wrapper might be
    transparent on some themes (the base layer of the page bleeds
    through and there's no card to "breathe").

    The two TOTALS BLOCKS (`.wp-block-woocommerce-cart-totals-block`
    and `.wp-block-woocommerce-checkout-totals-block`) are different.
    In current WooCommerce blocks (9.x+) the totals block IS the
    visible "Order summary" card on every theme — it ALWAYS becomes
    the painted surface a shopper sees, because:

      * Phase C ships a `::before` "Order summary" pseudo-element
        directly on `.wp-block-woocommerce-cart-totals-block` /
        `.wp-block-woocommerce-checkout-totals-block`. That pseudo
        title sits at the top-left of whatever bounds those selectors
        own; if they have no padding, the title sits flush at the
        edge.
      * The WC block markup renders the totals block at width:100%
        inside the sidebar wrapper. If the sidebar wrapper is
        unpainted (or painted the same color as the page background,
        like Selvedge's dark base where `--surface` ≈ page bg), the
        totals block IS the visible card, and the only thing inset
        from its perimeter is whatever padding the totals block
        itself declares.

    So even if the SIDEBAR WRAPPER passes
    `check_wc_card_surfaces_padded`, the inner totals block can still
    render edge-to-edge content (the bug we're preventing). This check
    closes that gap by enforcing padding on the totals blocks
    UNCONDITIONALLY — no background prerequisite, because in modern
    WC the totals block is always the visible card surface on at
    least some themes.

    What this check enforces:

      * For each of the two totals selectors above, at least one
        top-level `styles.css` rule whose selector list mentions the
        bare selector must declare `padding`, `padding-left`, or
        `padding-inline` using a spacing token of `xl` or larger
        (`xl`, `2-xl`, `3-xl`, `4-xl`, `5-xl`).
      * If multiple rules apply, the bigger token wins (matches the
        permissive semantics in `check_wc_card_surfaces_padded`).

    Enforced at write time by:
      `bin/append-wc-overrides.py` Phase H
      (`wc-tells-phase-h-totals-padding`), which emits the baseline
      `padding: xl` on these selectors into every theme's
      `styles.css`.

    See AGENTS.md "WooCommerce panel surfaces" rule for the broader
    context.
    """
    r = Result("WC totals blocks (cart + checkout) have ≥xl internal padding")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # The two selectors that ALWAYS render as the visible "Order
    # summary" card in current WC. Add to this list as new always-
    # painted totals containers ship in WC.
    TOTALS_SELECTORS = (
        ".wp-block-woocommerce-cart-totals-block",
        ".wp-block-woocommerce-checkout-totals-block",
    )
    OK_TOKENS = ("xl", "2-xl", "3-xl", "4-xl", "5-xl")

    def _padding_tokens(decl_block: str) -> list[str]:
        """Collect every spacing slug used in any `padding`-family
        declaration of a single rule body. Returns [] if nothing
        token-shaped is found."""
        tokens: list[str] = []
        for prop in ("padding-left", "padding-inline", "padding"):
            for m in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                decl_block,
            ):
                value = m.group(1)
                tokens.extend(
                    re.findall(
                        r"var\(--wp--preset--spacing--([a-z0-9-]+)\)",
                        value,
                    )
                )
        return tokens

    # selector -> list of every padding token we saw on the bare
    # selector across every rule in top-level styles.css.
    seen: dict[str, list[str]] = {sel: [] for sel in TOTALS_SELECTORS}

    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments from the selectors blob so a
        # rule that's prefixed with sentinel markers (the way
        # `bin/append-wc-overrides.py` emits its chunks) still
        # parses cleanly. Without this strip the FIRST selector
        # in the rule has the sentinel comment glued to its head
        # and `sel == surface` never matches.
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        for surface in TOTALS_SELECTORS:
            for sel in sel_list:
                # Only the BARE selector (or a selector list that
                # contains the bare selector as one of its entries)
                # describes the panel itself; descendant rules like
                # `.wp-block-woocommerce-cart-totals-block .heading`
                # are inner type, not the panel.
                if sel == surface:
                    seen[surface].extend(_padding_tokens(body))

    failures: list[str] = []
    for surface in TOTALS_SELECTORS:
        tokens = seen[surface]
        if not tokens:
            failures.append(
                f"{surface}: no `padding` (or `padding-left` / "
                f"`padding-inline`) declaration found on the bare "
                f"selector in top-level `styles.css`. This block is "
                f"the visible 'Order summary' card on current WC; "
                f"without explicit padding its content sits flush at "
                f"the panel edge. Re-run `bin/append-wc-overrides.py` "
                f"to (re-)emit Phase H, or add `padding: var(--wp--"
                f"preset--spacing--xl)` (or larger) to a top-level "
                f"rule whose selector list contains exactly `{surface}`."
            )
            continue
        if not any(t in OK_TOKENS for t in tokens):
            biggest = tokens[0]
            failures.append(
                f"{surface}: padding token `{biggest}` is below the "
                f"`xl` panel-breathing bar. The totals card is dense "
                f"(subtotal + tax + total + coupon row + primary "
                f"CTA); `lg` and below visibly cramps the stack "
                f"against the panel edge. Bump to `xl` or larger."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"{len(TOTALS_SELECTORS)} totals block(s) — all carry ≥xl internal padding (Phase H)"
    )
    return r


def check_wc_notices_styled() -> Result:
    """Fail if the Phase L `wc-tells-phase-l-notices` sentinel block is
    missing from a theme's `theme.json` root `styles.css`, or if the
    block is present but doesn't carry the canonical surface-restyling
    rules.

    Why this exists:
      WooCommerce paints notices in five different markup shapes
      (modern Blocks notice banner, per-field validation error,
      snackbar, store-notices wrapper, and the classic
      `.woocommerce-message`/`-error`/`-info` triad). Out of the box
      every one of them paints with WC's hardcoded plugin voice
      (white pill background, stock SVG icon, sans-serif at a fixed
      size, no theme tokens) — exactly the "this is a free
      WooCommerce site" failure mode this monorepo exists to prevent.
      The fix lives in `bin/append-wc-overrides.py` Phase L, which
      ships token-driven chrome that uses each theme's existing
      `info` / `success` / `warning` / `error` palette tokens for the
      variant signal so the same chunk paints per-theme without any
      raw hex.

      A regression on this surface is invisible during normal demo
      browsing (notices only appear when the shopper triggers
      something — failed login, invalid coupon, sold-out variation,
      etc.), so the static gate has to enforce the chunk's presence
      directly. Without this check, someone hand-stripping the
      Phase L chunk to re-author it inline (and forgetting to commit
      the replacement) ships a theme whose notice surfaces silently
      revert to WC's plugin defaults, and the regression only shows
      up the next time a shopper triggers a notice in the live demo.

    What this check enforces:
      - The Phase L sentinel pair (`/* wc-tells-phase-l-notices */`
        … `/* /wc-tells-phase-l-notices */`) is present in
        `theme.json` root `styles.css`.
      - Inside the sentinel block, the canonical surface restyles
        are present:
          * the modern banner selector
            `.wc-block-components-notice-banner`,
          * the four variant signals (`.is-info`, `.is-success`,
            `.is-warning`, `.is-error`),
          * the per-field validation error
            (`.wc-block-components-validation-error`),
          * the snackbar list
            (`.wc-block-components-notices__snackbar` OR
            `.wc-block-components-notice-snackbar-list`),
          * the legacy classic triad
            (`.woocommerce-message`, `.woocommerce-error`,
            `.woocommerce-info`).

    Enforced at write time by:
      `bin/append-wc-overrides.py` Phase L (`wc-tells-phase-l-notices`).
      Re-run the script after any styles.css drift to regenerate
      the chunk.
    """
    r = Result("WC notice surfaces are restyled (banner + validation + snackbar)")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    open_marker = "/* wc-tells-phase-l-notices */"
    close_marker = "/* /wc-tells-phase-l-notices */"
    open_idx = top_css.find(open_marker)
    close_idx = top_css.find(close_marker)
    if open_idx < 0 or close_idx < 0 or close_idx <= open_idx:
        r.fail(
            "Phase L sentinel block (wc-tells-phase-l-notices) is "
            "missing from `theme.json` root `styles.css`. The chunk "
            "ships token-driven restyles for every WC notice surface "
            "(modern banner, per-field validation error, snackbar, "
            "store-notices wrapper, classic message/error/info). "
            "Without it, every notice paints with WC's hardcoded "
            "plugin voice. Re-run `python3 bin/append-wc-overrides.py` "
            "to (re-)emit Phase L."
        )
        return r

    chunk = top_css[open_idx:close_idx]
    chunk_norm = re.sub(r"\s+", "", chunk)

    required = (
        ("modern banner", ".wc-block-components-notice-banner"),
        ("info variant", ".wc-block-components-notice-banner.is-info"),
        ("success variant", ".wc-block-components-notice-banner.is-success"),
        ("warning variant", ".wc-block-components-notice-banner.is-warning"),
        ("error variant", ".wc-block-components-notice-banner.is-error"),
        ("validation error", ".wc-block-components-validation-error"),
        ("legacy message", ".woocommerce-message"),
        ("legacy error", ".woocommerce-error"),
        ("legacy info", ".woocommerce-info"),
    )
    missing: list[str] = []
    for label, selector in required:
        if re.sub(r"\s+", "", selector) not in chunk_norm:
            missing.append(f"{label} (`{selector}`)")

    snackbar_selectors = (
        ".wc-block-components-notices__snackbar",
        ".wc-block-components-notice-snackbar-list",
    )
    if not any(re.sub(r"\s+", "", s) in chunk_norm for s in snackbar_selectors):
        missing.append(
            "snackbar (one of `.wc-block-components-notices__snackbar` "
            "or `.wc-block-components-notice-snackbar-list`)"
        )

    if missing:
        r.fail(
            "Phase L sentinel block exists but is missing canonical "
            "notice surface restyles for: " + ", ".join(missing) + ". "
            "Re-run `python3 bin/append-wc-overrides.py` to regenerate "
            "the chunk."
        )
        return r

    r.details.append(f"Phase L block present + {len(required)} surface restyles + snackbar covered")
    return r


def check_navigation_overlay_opaque() -> Result:
    """Fail if any `core/navigation` block in `parts/` (or `templates/`)
    opens a mobile overlay menu without explicit `overlayBackgroundColor`
    and `overlayTextColor` attributes pointing at palette tokens.

    Why this exists:
      WordPress core's mobile navigation overlay (the modal that opens
      when the hamburger is tapped) ships with `background-color: inherit`
      as the default paint. When the surrounding header is also a
      transparent or `inherit`-colored container, the modal renders
      transparent — the underlying page (heading, hero image, etc.)
      bleeds straight through behind the menu items, leaving the user
      staring at a stack of unreadable links floating over a `Lookbook`
      hero. The fix is to set `overlayBackgroundColor` (and a paired
      `overlayTextColor`) directly on the `core/navigation` block so the
      block emits its own `--navigation-overlay-background-color` /
      `--navigation-overlay-text-color` custom properties at the right
      specificity. WP core then paints the modal opaquely on every
      breakpoint with no theme.json shim required.

      A regression on this surface is invisible during normal desktop
      browsing (the modal only opens on mobile / when `overlayMenu`
      kicks in), so the static gate has to enforce the attributes
      directly. Without this check, anyone hand-editing `parts/header.html`
      (or copy-pasting a nav block from another part) ships a header
      whose mobile menu silently reverts to the bleed-through default,
      and the regression only shows up the next time someone opens the
      site on a phone.

    What this check enforces:
      For every `core/navigation` block found in `parts/*.html` and
      `templates/*.html` whose `overlayMenu` attribute is set to anything
      other than `"never"` (i.e. `"mobile"` or `"always"` — the two
      values WP supports that actually open the modal):
        - `overlayBackgroundColor` MUST be present and resolve to a
          palette slug declared in `settings.color.palette`.
        - `overlayTextColor` MUST be present and resolve to a palette slug
          declared in `settings.color.palette`.

      Custom hex colors via `style.color.background` / `style.color.text`
      are intentionally rejected — palette tokens keep the overlay
      brand-coherent across light/dark mode and palette swaps. If a theme
      genuinely needs a one-off color, add it to the palette first.
    """
    r = Result("Navigation overlay menus paint with palette tokens")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    palette = ((data.get("settings") or {}).get("color") or {}).get("palette") or []
    palette_slugs = {p.get("slug") for p in palette if isinstance(p, dict)}

    candidates: list[Path] = []
    for sub in ("parts", "templates"):
        d = ROOT / sub
        if d.is_dir():
            candidates.extend(sorted(d.glob("*.html")))

    if not candidates:
        r.skip("no parts/ or templates/ to scan")
        return r

    nav_open_re = re.compile(r"<!--\s*wp:navigation\s+(\{.*?\})\s*(/?)-->", re.DOTALL)
    failures: list[str] = []
    nav_blocks_seen = 0

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in nav_open_re.finditer(text):
            attrs_raw = match.group(1)
            try:
                attrs = json.loads(attrs_raw)
            except json.JSONDecodeError:
                failures.append(
                    f"{path.relative_to(ROOT)}: `core/navigation` block has "
                    f"un-parseable JSON attrs near offset {match.start()}."
                )
                continue
            nav_blocks_seen += 1
            overlay_mode = attrs.get("overlayMenu", "mobile")
            if overlay_mode == "never":
                continue
            rel = path.relative_to(ROOT)
            bg = attrs.get("overlayBackgroundColor")
            fg = attrs.get("overlayTextColor")
            if not bg:
                failures.append(
                    f'{rel}: `core/navigation` (overlayMenu="{overlay_mode}") '
                    f"is missing `overlayBackgroundColor`. Without it WP core "
                    f"paints the mobile modal `background-color: inherit`, so "
                    f"the page bleeds through behind the menu items. Set it to "
                    f'a palette slug, e.g. `"overlayBackgroundColor":"base"`.'
                )
            elif bg not in palette_slugs:
                failures.append(
                    f"{rel}: `core/navigation` `overlayBackgroundColor` "
                    f"=`{bg}` is not a slug in `settings.color.palette`. "
                    f"Use a palette token so the overlay survives palette "
                    f"swaps and dark mode."
                )
            if not fg:
                failures.append(
                    f'{rel}: `core/navigation` (overlayMenu="{overlay_mode}") '
                    f"is missing `overlayTextColor`. Pair it with "
                    f"`overlayBackgroundColor` so the menu text reads against "
                    f'the modal paint, e.g. `"overlayTextColor":"contrast"`.'
                )
            elif fg not in palette_slugs:
                failures.append(
                    f"{rel}: `core/navigation` `overlayTextColor`=`{fg}` "
                    f"is not a slug in `settings.color.palette`. Use a "
                    f"palette token so the menu text inherits the theme's "
                    f"voice."
                )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if nav_blocks_seen == 0:
        r.skip("no core/navigation blocks found")
        return r

    r.details.append(
        f"{nav_blocks_seen} `core/navigation` block(s) carry palette-token overlay paint"
    )
    return r


def check_outline_button_paired_with_primary() -> Result:
    """Fail if `theme.json` defines an `is-style-outline` variation for
    `core/button` that isn't visually paired with the primary button —
    i.e. its border-radius doesn't match the primary, or its border-width
    is hairline-thin (≤1px) while the primary carries visible heft.

    Why this exists:
      Primary and outline buttons almost always render side-by-side
      ("Shop the bench" + "Read the journal", "Add to cart" + "Continue
      shopping", etc.). For the pair to read as ONE coordinated CTA,
      they need to share the same shape grammar — same corner radius,
      comparable border weight, the same approximate footprint. WP
      core's stock `is-style-outline` ships with a 1px hairline border
      and inherits whatever radius the variation declares, but that
      radius is independent of `styles.elements.button.border.radius`.
      The two can drift apart silently:

        * a designer rounds the primary to a pill but leaves the outline
          square (or vice-versa), and suddenly the pair looks like two
          different design systems mashed together;
        * the outline ships at `border-width: 1px` next to a primary
          that sits at `var(--border--width--thick)` (2-3px), and the
          outline reads as a faint suggestion rather than a real CTA.

      Both failure modes are baked into WP's stock outline style. The
      fix is to declare an outline variation in
      `styles.blocks.core/button.variations.outline` whose `border.radius`
      matches the primary's `styles.elements.button.border.radius` and
      whose `border.width` is ≥ 2px (or a `--border--width--thick`-style
      token that resolves to ≥ 2px).

    What this check enforces:
      For every theme that declares
      `styles.blocks.core/button.variations.outline.border`:
        - `outline.border.radius` MUST equal
          `styles.elements.button.border.radius` when both are set.
          (If primary has no `border.radius` set, the outline's radius
          is unconstrained — WP defaults to the same UA value for both.)
        - `outline.border.width` MUST NOT be a literal `1px` / `0` /
          `none`. The check passes any token reference
          (`var(--wp--custom--border--width--*)`) under the assumption
          that the token itself is ≥ 2px (the
          `check_distinctive_chrome` companion already verifies token
          values across themes); literal `2px`/`3px`/`4px` etc. are
          also accepted.
        - `outline.border.style` MUST be present and not `none`.
        - `outline.color.background` MUST be `transparent` (or absent —
          WP defaults to transparent for outline) so the variation
          actually reads as outlined; if it's a solid color, the
          author probably meant to add a third button variation, not
          an "outline".

      Themes with no `outline` variation declared are skipped (the
      check has nothing to enforce — no outline means no mispairing).
    """
    r = Result("Outline button variation is visually paired with primary")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r

    styles = data.get("styles") or {}
    btn_elem = (styles.get("elements") or {}).get("button") or {}
    primary_border = (btn_elem.get("border") or {}) if isinstance(btn_elem, dict) else {}
    primary_radius = primary_border.get("radius")

    blocks_btn = (styles.get("blocks") or {}).get("core/button") or {}
    outline = (blocks_btn.get("variations") or {}).get("outline") or {}
    if not outline:
        r.skip("no outline variation declared on core/button")
        return r

    out_border = outline.get("border") or {}
    out_color = outline.get("color") or {}

    failures: list[str] = []

    out_radius = out_border.get("radius")
    if primary_radius is not None and out_radius != primary_radius:
        failures.append(
            f"`styles.blocks.core/button.variations.outline.border.radius`="
            f"`{out_radius}` does not match the primary "
            f"`styles.elements.button.border.radius`=`{primary_radius}`. "
            f"A primary + outline pair that disagrees on corner shape "
            f"reads as two different design systems mashed together. "
            f"Set both to the same value (or remove the outline radius "
            f"to inherit the primary's)."
        )

    out_width = out_border.get("width")
    if out_width is None:
        failures.append(
            "`styles.blocks.core/button.variations.outline.border.width` "
            "is not set. Outline buttons need an explicit border-width — "
            "WP's UA default of 0 is invisible. Set it to "
            "`var(--wp--custom--border--width--thick)` (or any value ≥2px)."
        )
    else:
        # Reject anything that resolves to a hairline / nothing.
        # Accept token references (assumed ≥2px; verified by token check).
        thin = {"0", "0px", "none", "1px", ".5px", "0.5px"}
        if isinstance(out_width, str):
            ws = out_width.strip().lower()
            if ws in thin:
                failures.append(
                    f"`styles.blocks.core/button.variations.outline.border.width`="
                    f"`{out_width}` is too thin to balance a primary CTA. "
                    f"A 1px outline next to a chunky filled primary reads "
                    f"as a faint suggestion rather than a real button. "
                    f"Use `var(--wp--custom--border--width--thick)` (or "
                    f"any literal ≥2px)."
                )

    out_style = out_border.get("style")
    if out_style in (None, "none"):
        failures.append(
            f"`styles.blocks.core/button.variations.outline.border.style`="
            f"`{out_style}` — an outline variation needs a visible "
            f"border-style (typically `solid`)."
        )

    out_bg = out_color.get("background")
    if out_bg not in (None, "transparent"):
        failures.append(
            f"`styles.blocks.core/button.variations.outline.color.background`="
            f"`{out_bg}` — an `is-style-outline` variation should paint "
            f"`transparent` so the border carries the chrome. If you want "
            f"a third filled-but-different variation, register it under a "
            f"different name (e.g. `secondary`) so its intent is explicit."
        )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"outline variation paired with primary (radius=`{out_radius}`, width=`{out_width}`)"
    )
    return r


def check_wc_card_padding_not_zeroed() -> Result:
    """Fail if any rule in top-level `styles.css` zeros horizontal
    padding on a painted WC card surface.

    Why this is its own check (vs trusting
    `check_wc_card_surfaces_padded` and `check_wc_totals_blocks_padded`
    to enforce the floor):

    Those two checks verify that *some* rule declares an `xl`-or-bigger
    padding on the bare selector. They do NOT verify that no
    higher-specificity rule elsewhere in the same `styles.css` quietly
    UNDECLARES that padding — which is exactly the regression that
    shipped in Q2 when `wc-tells-grid-cell-fill` zeroed
    `padding-left` and `padding-right` on
    `.wc-block-components-sidebar-layout.wc-block-cart > .wc-block-
    components-sidebar` (specificity `(0,3,0)`). The DOM that matched
    that selector is the SAME element that carries
    `.wc-block-cart__sidebar` AND
    `.wp-block-woocommerce-cart-totals-block`, so the painted-card
    rules at specificity `(0,1,0)` lost the cascade and the "Order
    summary" stack rendered flush at the panel's left edge across
    every theme. The bug was visually invisible to the existing
    "panel has padding declared" checks because the bare-selector
    rule still declared `padding: xl` — it just got overruled.

    What this check enforces:

      * For each rule in top-level `styles.css`, parse the selector
        list and the declaration block.
      * If any selector in the list contains one of the painted card
        surface class names listed in `_CARD_SURFACE_CLASSES` below,
        AND the rule body declares any of `padding`, `padding-left`,
        `padding-right`, `padding-inline`, `padding-inline-start`,
        `padding-inline-end` with a literal `0` value (with or
        without a unit suffix), the check fails with a pointer to
        the offending selector and declaration.
      * Whitelist: the bare card-surface selectors themselves
        (e.g. `.wc-block-cart__sidebar`) are allowed to set
        `padding: 0` on RESET-style chunks if a sibling rule re-paints
        the padding back. We don't bother detecting that: in practice,
        no current chunk needs to zero padding on a painted card, so
        any match is the regression we're guarding against.

    Companion to:
      * `check_wc_card_surfaces_padded` — verifies the floor.
      * `check_wc_totals_blocks_padded` — verifies the totals card
        floor specifically.
      * `bin/append-wc-overrides.py::CSS_GRID_FIX` block comment —
        the load-bearing reminder that explains WHY GRID_FIX no
        longer zeros padding (and what to do if WC's percentage
        paddings ever leak back).
    """
    r = Result("WC painted card surfaces don't get horizontal padding zeroed")

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.skip("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    if not top_css.strip():
        r.skip("no top-level styles.css")
        return r

    # The painted card surfaces. A rule that matches ANY of these
    # classes (anywhere in any of its selectors) and zeros horizontal
    # padding will UNDO the panel's breathing room because the DOM
    # node carrying these classes is the visible card a shopper sees.
    _CARD_SURFACE_CLASSES = (
        "wc-block-cart__sidebar",
        "wc-block-checkout__sidebar",
        "wp-block-woocommerce-cart-totals-block",
        "wp-block-woocommerce-checkout-totals-block",
        # `.wc-block-components-sidebar` shares its DOM node with
        # `.wc-block-cart__sidebar` and `.wc-block-checkout__sidebar`
        # (verified in WC blocks 9.x markup), so a rule targeting
        # the components-sidebar class on a cart/checkout host is
        # ALSO painting the card. This catches the original
        # GRID_FIX regression directly.
        "wc-block-components-sidebar",
    )

    # CSS values that count as "zeroing horizontal padding": bare 0,
    # 0px, 0rem, 0em, 0%, 0vh, 0vw, etc. We deliberately do NOT match
    # `padding: 0 var(--xl)` or `padding: 0 1rem` because those leave
    # horizontal padding intact — only the vertical is zeroed and the
    # card still breathes left-to-right. The regex is anchored on a
    # word boundary so we don't false-positive on `0.5rem`.
    _ZERO_VALUE_RE = re.compile(r"^\s*0(?:px|rem|em|%|vh|vw|vmin|vmax)?\s*$")

    # The padding properties that, if set to 0, would strip the
    # horizontal breathing room. `padding-top` / `padding-bottom` are
    # intentionally NOT in this list — vertical zero is fine, the
    # check is about left/right inset only.
    _HORIZONTAL_PADDING_PROPS = (
        "padding-left",
        "padding-right",
        "padding-inline",
        "padding-inline-start",
        "padding-inline-end",
    )

    failures: list[str] = []

    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", top_css):
        selectors_blob, body = m.group(1), m.group(2)
        # Strip CSS block comments so sentinel-prefixed rules parse
        # cleanly (mirrors the strip in
        # `check_wc_totals_blocks_padded`).
        selectors_blob = re.sub(r"/\*.*?\*/", "", selectors_blob)
        selectors_blob = selectors_blob.strip()
        if not selectors_blob:
            continue
        sel_list = [s.strip() for s in selectors_blob.split(",")]
        # Find every selector that targets a painted card surface.
        offending_selectors = [
            s for s in sel_list if any(f".{cls}" in s for cls in _CARD_SURFACE_CLASSES)
        ]
        if not offending_selectors:
            continue
        # Walk the declaration block looking for any
        # `padding-{left,right,inline,inline-start,inline-end}: 0`
        # OR a shorthand `padding: 0` (the latter zeros all four
        # sides, including horizontal).
        for prop in _HORIZONTAL_PADDING_PROPS:
            for d in re.finditer(
                rf"\b{re.escape(prop)}\s*:\s*([^;}}]+)",
                body,
            ):
                value = d.group(1).strip()
                # Only flag rules that set the property to a literal
                # zero. `var(--xl)`, `revert`, `unset`, etc. are all
                # fine — they restore breathing room.
                if _ZERO_VALUE_RE.match(value):
                    failures.append(
                        f"{', '.join(offending_selectors)} "
                        f"sets `{prop}: {value}` — this strips "
                        f"horizontal padding from a painted card "
                        f"surface and undoes Phase G/H/cart-fix's "
                        f"breathing room. See "
                        f"`bin/append-wc-overrides.py::CSS_GRID_FIX` "
                        f"comment for the regression history."
                    )
        # Shorthand `padding: 0` is the other way to zero horizontal
        # padding. We allow `padding: 0 <something-non-zero>` (vertical
        # zero, horizontal painted) and `padding: 0 ... ...` only when
        # the second value is non-zero.
        for d in re.finditer(r"\bpadding\s*:\s*([^;}]+)", body):
            value = d.group(1).strip()
            parts = value.split()
            if not parts:
                continue
            # If the shorthand is JUST `0` (one value), all four sides
            # are zero — horizontal included.
            if len(parts) == 1 and _ZERO_VALUE_RE.match(parts[0]):
                failures.append(
                    f"{', '.join(offending_selectors)} sets "
                    f"`padding: {value}` — single-value `0` zeros "
                    f"all four sides, including horizontal, and "
                    f"strips the painted card's breathing room."
                )
                continue
            # If the shorthand is `0 0 ... ...` (two or four values
            # where the SECOND value is zero), horizontal is zero.
            if len(parts) >= 2 and _ZERO_VALUE_RE.match(parts[1]):
                failures.append(
                    f"{', '.join(offending_selectors)} sets "
                    f"`padding: {value}` — the horizontal slot "
                    f"is `0`, which strips the painted card's "
                    f"breathing room."
                )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    r.details.append(
        f"{len(_CARD_SURFACE_CLASSES)} card-surface class(es) — no "
        f"rule zeros horizontal padding on a painted card"
    )
    return r


# Selectors that paint user-visible "chrome" — the parts of the storefront
# where a shopper sees this theme's voice and not the next theme's. Each
# entry is matched VERBATIM against rule selectors in top-level `styles.css`
# (whitespace normalised, but selector lists must match in order).
#
# Rule: nothing in this list is allowed to ship a byte-identical CSS body in
# two or more themes UNLESS each of those themes also provides a per-theme
# `body.theme-<slug> <selector>` override that visually overpowers the base.
# A "standard" treatment shared across themes is exactly the "feels like a
# default WooCommerce site" bug we keep flagging on demos.
#
# Add a selector here whenever a new premium-chrome surface ships (cart
# sidebar, primary CTA chrome, sale badge, hero, trust strip, footer mark,
# …). Structural / utility / accessibility rules are deliberately NOT in
# this list — a `min-width:0` overflow fix or a screen-reader visually-
# hidden rule SHOULD be byte-identical across themes; that's not chrome,
# that's plumbing.
DISTINCT_CHROME_SELECTORS: list[str] = [
    ".wc-block-cart__sidebar",
    ".wc-block-checkout__sidebar",
    ".wo-payment-icons__icon",
]

def _normspace(s: str) -> str:
    """Collapse all whitespace runs in a CSS fragment so two rules can be
    compared byte-for-byte without being defeated by minifier whitespace."""
    return re.sub(r"\s+", "", s)


def _strip_css_comments(css: str) -> str:
    """Remove every `/* ... */` block from a CSS string. The phase-N
    sentinels appended by `bin/append-wc-overrides.py` live as comments
    immediately before each rule, so without stripping them the regex
    below ends up capturing `<comment> <selector> {...}` as one selector
    blob — and `selector.startswith("body.theme-…")` then never matches."""
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)


def _find_base_rule_body(css: str, target_selector: str) -> str | None:
    """Return the normalised body of the FIRST top-level rule whose selector
    list (whitespace-normalised) exactly equals `target_selector`. We compare
    the whole selector list — comma-separated bundles like `a,b,c` must
    match in their entirety, because changing the bundle is itself a
    legitimate way to make a theme's chrome distinctive.

    Returns None if no matching rule exists. Skips selectors that begin
    with `body.theme-` because those are per-theme overrides, not the base.
    """
    target_norm = _normspace(target_selector)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", _strip_css_comments(css)):
        sel_blob, body = m.group(1), m.group(2)
        sel_norm = _normspace(sel_blob)
        if sel_norm.startswith("body.theme-"):
            continue
        if sel_norm == target_norm:
            return _normspace(body)
    return None


def _has_per_theme_override(css: str, theme_slug: str, target_selector: str) -> bool:
    """Return True iff `css` contains at least one rule whose selector list
    starts with `body.theme-<slug>` and whose remainder mentions any of the
    comma-separated parts of `target_selector` as the trailing component.

    Phase E/F overrides live in the same blob as the base rules (the
    bin/append-wc-overrides.py CSS chunk is appended verbatim to every
    theme's styles.css), so the override for chonk is present in *every*
    theme's CSS — the body class is what gates which one fires at runtime.
    Checking presence in any theme's CSS is therefore equivalent to
    checking that the override exists at all.
    """
    target_parts = [_normspace(p) for p in target_selector.split(",")]
    prefix = f"body.theme-{theme_slug}"
    for m in re.finditer(r"([^{}]+)\{[^}]*\}", _strip_css_comments(css)):
        sel_blob = m.group(1)
        for raw_sel in sel_blob.split(","):
            sel_norm = _normspace(raw_sel)
            if not sel_norm.startswith(prefix):
                continue
            rest = sel_norm[len(prefix) :]
            if not rest.startswith("."):
                # Prefix must be followed by a descendant combinator
                # (which gets normalised away); a bare `body.theme-X` rule
                # wouldn't be a per-selector override.
                continue
            for part in target_parts:
                if rest.endswith(part):
                    return True
    return False


def check_distinctive_chrome() -> Result:
    """Fail if any "premium chrome" selector (see DISTINCT_CHROME_SELECTORS)
    ships a byte-identical CSS body in two or more themes WITHOUT a
    per-theme `body.theme-<slug> <selector>` override that lets each theme
    in the cluster express its own voice.

    Why this exists
    ---------------
    The fastest way to make a WooCommerce demo read as "off-the-shelf" is
    to paint the visible chrome the same way in every theme variant. The
    cart sidebar, the checkout sidebar, the trust-strip pills, the primary
    CTA — these are exactly the surfaces a shopper looks at to answer
    "does this brand have its own taste?" If chonk and obel render the
    payment-icon row with byte-identical white pills, both themes lose
    the answer.

    The rule isn't "no shared CSS rules anywhere" — utility and structural
    plumbing (overflow fixes, screen-reader helpers, layout grids) MUST
    be byte-identical or the themes drift inconsistently. The rule is
    scoped to the curated DISTINCT_CHROME_SELECTORS list, which lives at
    the top of this file and is meant to grow as new chrome surfaces
    ship.

    What "distinctive" means here
    -----------------------------
    A theme can earn a unique treatment two ways:
      1. Its base rule body for the selector differs from the other
         themes' base rule bodies. (Chonk just authors a different rule
         in `styles.blocks` or `styles.css`.)
      2. The base rule body is shared across themes, but EACH theme in
         the shared cluster also provides a `body.theme-<slug>
         <selector>` override (in `bin/append-wc-overrides.py` Phase E
         or Phase F) that visibly differentiates it.

    Either path satisfies the rule.

    What this check enforces
    ------------------------
    For every selector S in DISTINCT_CHROME_SELECTORS:
      - Load every shipped theme's top-level styles.css (cross-theme).
      - Group themes by the byte-identical base rule body for S.
      - For each cluster of 2+ themes with the same body, fail any
        theme in the cluster that does NOT also ship a per-theme
        override for S.
    """
    r = Result("Visible chrome rules are theme-distinct (no shared 'standard' look)")

    def _chrome_inputs(theme: Path) -> list[Path]:
        p = theme / "theme.json"
        return [p] if p.exists() else []

    def _chrome_fp(theme: Path) -> dict[str, str]:
        p = theme / "theme.json"
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        css = (data.get("styles", {}) or {}).get("css") or ""
        return {"css": css} if css.strip() else {}

    cached_css = collect_fleet(
        _cross_theme_roots(),
        check_name="distinctive_chrome",
        input_builder=_chrome_inputs,
        compute_fn=_chrome_fp,
    )
    theme_css: dict[str, str] = {
        slug: payload["css"]
        for slug, payload in cached_css.items()
        if payload and payload.get("css")
    }

    if len(theme_css) < 2:
        r.skip(
            f"need >=2 themes loaded to compare chrome; found {len(theme_css)} "
            f"({', '.join(sorted(theme_css)) or 'none'})."
        )
        return r

    failures: list[str] = []
    verified: list[str] = []

    for selector in DISTINCT_CHROME_SELECTORS:
        # Bucket themes by their base rule body for this selector.
        clusters: dict[str, list[str]] = {}
        skipped_themes: list[str] = []
        for slug, css in sorted(theme_css.items()):
            body = _find_base_rule_body(css, selector)
            if body is None:
                # No base rule for this selector in this theme — that's
                # fine; the theme just doesn't paint this surface yet.
                skipped_themes.append(slug)
                continue
            clusters.setdefault(body, []).append(slug)

        cluster_failed = False
        for body, slugs in clusters.items():
            if len(slugs) < 2:
                continue
            # Cluster of 2+ themes sharing one base body. Each theme in
            # the cluster must provide its OWN per-theme override.
            offenders = [
                slug
                for slug in slugs
                if not _has_per_theme_override(theme_css[slug], slug, selector)
            ]
            if len(offenders) < 2:
                # At most one theme leans on the shared base — every
                # other one in the cluster has overridden it.
                continue
            cluster_failed = True
            failures.append(
                f"`{selector}`: themes [{', '.join(offenders)}] ship "
                f"byte-identical base CSS with no `body.theme-<slug> "
                f"{selector.split(',')[0]}` override. Either (a) author "
                f"a different base rule body in one of the themes' "
                f"`styles.css` / `styles.blocks`, or (b) add per-theme "
                f"distinctive overrides in `bin/append-wc-overrides.py` "
                f"Phase E/F so every theme expresses its own voice on "
                f"this surface. Shared 'standard' chrome is what makes "
                f"WooCommerce demos read as off-the-shelf — see AGENTS.md "
                f"\"Nothing is 'standard'\"."
            )

        if not cluster_failed:
            covered = sorted(theme_css)
            if skipped_themes:
                covered = [s for s in covered if s not in skipped_themes]
            verified.append(f"`{selector}` distinct across [{', '.join(covered)}]")

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if verified:
        for v in verified:
            r.details.append(v)
    else:
        r.skip("no DISTINCT_CHROME_SELECTORS rules present in any theme yet")
    return r


def check_archive_sort_dropdown_styled() -> Result:
    """Fail if a `wp:woocommerce/catalog-sorting` block appears in any archive
    template but the theme never overrides the browser-default `<select>` chrome.

    Why this exists:
      `wp:woocommerce/catalog-sorting` renders a single `<form>` containing a
      bare `<select class="orderby">`. With no theme intervention the browser
      paints its OS-native dropdown — Chevy-grey on macOS, blue on Windows,
      square edges on Linux — directly into an editorial layout. Reviewers
      consistently call this out as the loudest "default WooCommerce theme"
      tell on a shop archive: it breaks the visual rhythm of every adjacent
      typographic element (results count, breadcrumbs, product titles).

      Block-scoped CSS in `styles.blocks["woocommerce/catalog-sorting"].css`
      gets wrapped by WP in `:root :where(.wp-block-woocommerce-catalog-
      sorting)` (specificity 0,0,1) and is overridden by both UA select
      defaults and several WC plugin rules (e.g. `.woocommerce-ordering
      select.orderby` at 0,0,2). Top-level `styles.css` is the only place
      where a rule reliably wins.

      Additionally, `wp:woocommerce/catalog-sorting` is the BLOCK form, but
      the same dropdown is rendered as a legacy `<form class="woocommerce-
      ordering">` on shortcode-driven catalogs (e.g. cart upsell carousel
      templates, `[products]` shortcodes). Selectors must cover both roots
      so a shopper never hits an unstyled native dropdown by accident.

    What this check enforces, ONLY when an archive-style template renders
    the catalog-sorting block (so themes without a shop archive aren't
    forced into rules they don't need):

      - Top-level `styles.css` must include a selector that targets either
        `.wp-block-woocommerce-catalog-sorting select.orderby` or
        `.woocommerce-ordering select.orderby` (whitespace ignored).
      - That rule must declare `appearance:none` (in any of the three
        appearance variants), which is the load-bearing line that strips
        the OS-native chrome and unlocks every other style.
      - Both selector roots should appear, so the legacy non-block render
        also gets the theme's treatment. (Only one selector is REQUIRED for
        the check to pass; missing the second is a warning logged in
        details, not a hard fail — block-only themes still benefit.)

    See AGENTS.md (monorepo) "Shop archive header" rule.
    """
    r = Result("Catalog-sorting <select> styled in top-level styles.css")

    template_paths = (
        sorted((ROOT / "templates").glob("archive-product*.html"))
        if (ROOT / "templates").exists()
        else []
    )
    triggering = next(
        (
            p
            for p in template_paths
            if re.search(
                r"<!--\s*wp:woocommerce/catalog-sorting(?:\s|/|-->)",
                p.read_text(encoding="utf-8", errors="replace"),
            )
        ),
        None,
    )
    if triggering is None:
        r.skip("no archive template renders wp:woocommerce/catalog-sorting")
        return r

    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing — cannot verify the dropdown override.")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    top_css = (data.get("styles", {}) or {}).get("css") or ""
    top_css_norm = re.sub(r"\s+", "", top_css)

    selector_block = ".wp-block-woocommerce-catalog-sortingselect.orderby"
    selector_legacy = ".woocommerce-orderingselect.orderby"
    has_block_sel = selector_block in top_css_norm
    has_legacy_sel = selector_legacy in top_css_norm

    if not (has_block_sel or has_legacy_sel):
        r.fail(
            f"{triggering.relative_to(ROOT).as_posix()} renders "
            f"`wp:woocommerce/catalog-sorting` (a bare `<select "
            f'class="orderby">`) but top-level `styles.css` never '
            f"targets `.wp-block-woocommerce-catalog-sorting select.orderby` "
            f"or `.woocommerce-ordering select.orderby`. Shoppers see the "
            f'OS-native dropdown — the loudest "default WooCommerce theme" '
            f"tell on a shop archive. Add a rule like "
            f"`.wp-block-woocommerce-catalog-sorting select.orderby,"
            f".woocommerce-ordering select.orderby {{ appearance:none; "
            f"-webkit-appearance:none; ... }}` to top-level `styles.css`. "
            f'Block-scoped `styles.blocks["woocommerce/catalog-sorting"]'
            f".css` does NOT win against the UA select chrome — see "
            f"check_wc_overrides_styled for the specificity story."
        )
        return r

    if "appearance:none" not in top_css_norm:
        r.fail(
            "top-level `styles.css` matches the catalog-sorting <select> "
            "but never declares `appearance:none`. Without the appearance "
            "reset the browser's native dropdown chrome (chevron, border, "
            "OS focus ring) still paints over your theme styles. Add "
            "`appearance:none;-webkit-appearance:none;-moz-appearance:none` "
            "to the same rule."
        )
        return r

    if not (has_block_sel and has_legacy_sel):
        missing = (
            "legacy `.woocommerce-ordering`"
            if has_block_sel
            else "block `.wp-block-woocommerce-catalog-sorting`"
        )
        r.details.append(
            f"WARNING: only one selector root present; consider also "
            f"covering the {missing} root so shortcode-driven catalogs "
            f"render the same dropdown."
        )
    r.details.append("matched dropdown selector + `appearance:none` in top-level styles.css")
    return r


def check_cart_checkout_pages_are_wide() -> Result:
    """Guard against the cart/checkout `contentSize` squeeze regression.

    `templates/page.html` constrains `wp:post-content` to the theme's
    default `contentSize` (780px) so blog and long-form pages get an
    editorial measure. Without an explicit `align:wide` on the seeded
    `wp:woocommerce/cart` and `wp:woocommerce/checkout` root blocks,
    the entire two-column layout inherits the 780px container at every
    viewport width, which is still too narrow for the cart/checkout
    grid to breathe.

    Symptom (caught in production review on 2026-04-20):
      * Tablet (<782px viewport): the responsive grid stacks to a
        single column inside the default container, so the squeeze is
        invisible.
      * Desktop (>=782px viewport): the grid kicks in inside that same
        780px container -> sidebar takes 300-360px and the form
        column collapses to ~420-480px. Order-summary item content
        ("Artisanal Silence (8 oz Jar)") wraps per-letter again,
        exactly the bug `check_no_squeezed_wc_sidebars` was supposed
        to prevent. CSS alone could not fix it because the container
        itself is the wrong width.

    Fix lives in two places now:
      * Cart root block: `<theme>/patterns/cart-page.php`
        (`Block Types: woocommerce/cart`). `wo-configure.php`
        `include`s the pattern with output buffering so its
        translated block tree becomes the Cart page `post_content`.
      * Checkout root block: still inlined in `wo-configure.php`
        (no per-theme microcopy on Checkout — the brand work lives
        on the Cart page).

    Both root blocks carry `{"align":"wide"}` so they opt out of the
    default contentSize (780px) and use the theme's wideSize (1440px)
    instead. At 1440px the 1fr / minmax(300px,360px) grid breathes
    correctly: ~1040px form, ~360px sidebar.

    This rule asserts the markers are present in the per-theme cart
    pattern (Cart) and in the inlined `wo-configure.php` of the
    theme's `playground/blueprint.json` (Checkout).
    """
    r = Result("Cart/Checkout root blocks are align:wide")
    bp_path = ROOT / "playground" / "blueprint.json"
    if not bp_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground blueprint)")
        return r
    try:
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"playground/blueprint.json: invalid JSON ({exc}).")
        return r

    # Cart side: read the per-theme pattern file directly. The pattern
    # is the source of truth for the cart block tree (wo-configure.php
    # `include`s it via output buffering; see § 11d). Reading the file
    # rather than re-parsing the blueprint lets the gate fire even if
    # the blueprint hasn't been re-synced after a pattern edit.
    cart_pattern_path = ROOT / "patterns" / "cart-page.php"
    cart_src = ""
    if cart_pattern_path.is_file():
        cart_src = cart_pattern_path.read_text(encoding="utf-8")
    else:
        r.fail(
            "patterns/cart-page.php missing — wo-configure.php § 11d "
            "reads this file via include + ob_start to seed the Cart "
            "page. Without it the demo Cart renders WC default chrome."
        )

    # Checkout side: still inlined in wo-configure.php. sync-playground.py
    # emits it as a `writeFile` step at `wp-content/mu-plugins/wo-configure.php`.
    cfg_data: str | None = None
    for step in bp.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if step.get("step") != "writeFile":
            continue
        path = step.get("path") or ""
        if "wo-configure.php" not in path:
            continue
        data = step.get("data")
        if isinstance(data, str):
            cfg_data = data
            break

    if cfg_data is None:
        # No inlined wo-configure.php means the blueprint either uses a
        # different content-seeding strategy or hasn't been synced. Either
        # way this rule cannot validate the checkout block markup.
        r.skip("no inlined wo-configure.php in blueprint (run bin/sync-playground.py)")
        return r

    required = [
        (
            cart_src,
            'wp:woocommerce/cart {"align":"wide"}',
            "patterns/cart-page.php",
            "Cart root block (`wp:woocommerce/cart`) is missing "
            '`{"align":"wide"}` in patterns/cart-page.php. Without it '
            "the cart inherits the default `contentSize` (780px) from "
            "`templates/page.html` and the sidebar collapses on desktop, "
            "producing per-letter text wrapping in the totals column.",
        ),
        (
            cfg_data,
            'wp:woocommerce/checkout {"align":"wide"}',
            "playground/wo-configure.php (inlined into blueprint)",
            "Checkout root block (`wp:woocommerce/checkout`) is missing "
            '`{"align":"wide"}` in inlined wo-configure.php. Without it '
            "the checkout inherits the default `contentSize` (780px) from "
            "`templates/page.html` and the order-summary sidebar collapses "
            "on desktop, producing per-letter wraps of product names like "
            "'Artisanal Silence'.",
        ),
    ]
    for src, needle, where, message in required:
        if src and needle not in src:
            r.fail(f"{where}: {message}")

    # Belt and suspenders: the rendered wrapper div must also carry
    # `alignwide` so the front-end CSS picks up the wide-width rules.
    # WordPress derives the class from the block attribute, but the
    # cart pattern + checkout heredoc write the wrapper div by hand;
    # if the editor ever re-saves the page the class will be regenerated
    # correctly, but the seeded source must already match so first
    # paint is correct.
    div_required = [
        (
            cart_src,
            "wp-block-woocommerce-cart alignwide",
            "patterns/cart-page.php",
            "Cart wrapper div is missing the `alignwide` class. The wrapper "
            'must read `<div class="wp-block-woocommerce-cart alignwide is-loading">` '
            "to match the `align:wide` block attribute on first render.",
        ),
        (
            cfg_data,
            "wp-block-woocommerce-checkout alignwide",
            "playground/wo-configure.php (inlined into blueprint)",
            "Checkout wrapper div is missing the `alignwide` class. The wrapper "
            'must read `<div class="wp-block-woocommerce-checkout alignwide wc-block-checkout is-loading">` '
            "to match the `align:wide` block attribute on first render.",
        ),
    ]
    for src, needle, where, message in div_required:
        if src and needle not in src:
            r.fail(f"{where}: {message}")

    if r.passed and not r.skipped:
        r.details.append(
            "verified `align:wide` on cart root block + wrapper div in "
            "patterns/cart-page.php, and on checkout root block + "
            "wrapper div in inlined wo-configure.php"
        )
    return r


def check_prose_layout_token_purged() -> Result:
    """The `--wp--custom--layout--prose` token is banned monorepo-wide.

    Context / why this check exists
    -------------------------------
    Every theme used to ship a `settings.custom.layout.prose` token
    set to `560px`, and all six `templates/{single,page,singular}.html`
    + several utility templates wrapped `wp:post-content` in a
    `{"layout":{"type":"constrained","contentSize":"var(--wp--custom--
    layout--prose)"}}` group. That forced every blog post + page body
    into a 560px column — too narrow to feel editorial, narrower than
    any of the mockups we've built against, and visibly distinct from
    the 780px default `contentSize` we actually want.

    The fix was a one-time purge: delete the token from every
    `theme.json`, strip every `contentSize:var(--wp--custom--layout--
    prose)` from templates/parts/patterns, and let `wp:post-content`
    fall back to the theme's default `contentSize: 780px`. This rule
    exists so the token stays purged: any future copy-paste from an
    old template, any resurrected pattern from git archaeology, any
    `bin/clone.py` output from a pre-purge branch immediately trips
    the gate.

    What's checked
    --------------
    The repo is scanned for three ban patterns:
      * `--wp--custom--layout--prose` — the CSS custom property form
        used inside serialized block attrs and CSS `var()` calls.
      * `layout|prose`              — the `var:preset|...` form WP
        occasionally emits for the same token.
      * `"prose": "`                — the `settings.custom.layout.prose`
        key in `theme.json`.

    Scan covers every theme's `templates/`, `parts/`, `patterns/`,
    `styles/`, `theme.json`, and `functions.php`, plus the shared
    `playground/wo-configure.php` and everything under `bin/` except
    `check.py` itself (where the token strings appear literally in
    this docstring and the BANNED_PATTERNS tuple below). Any hit is a
    FAIL; the message names the file + match.
    """
    r = Result("layout--prose token purged from monorepo")

    banned: tuple[tuple[str, str], ...] = (
        ("--wp--custom--layout--prose", "CSS custom property form"),
        ("layout|prose", "var:preset form"),
        ('"prose": "', "theme.json settings.custom.layout key"),
    )

    # Every theme dir + shared playground/bin trees.
    scan_roots: list[Path] = []
    for theme_dir in sorted(MONOREPO_ROOT.glob("*/theme.json")):
        scan_roots.append(theme_dir.parent)
    for sub in ("playground", "bin"):
        p = MONOREPO_ROOT / sub
        if p.is_dir():
            scan_roots.append(p)

    allowed_paths: set[Path] = {
        # This file itself documents the ban patterns verbatim.
        (MONOREPO_ROOT / "bin" / "check.py").resolve(),
    }

    scan_suffixes = {
        ".html",
        ".php",
        ".json",
        ".css",
        ".js",
        ".py",
    }
    # Skip generated / large build artefacts under these dir names,
    # anywhere in the scan tree.
    skip_dir_names = {
        "node_modules",
        "vendor",
        "tmp",
        ".git",
        "snaps",
        "blocks-validator",
    }

    files_scanned = 0
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in scan_suffixes:
                continue
            if any(part in skip_dir_names for part in path.parts):
                continue
            if path.resolve() in allowed_paths:
                continue
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for needle, label in banned:
                if needle in text:
                    rel = path.relative_to(MONOREPO_ROOT)
                    r.fail(
                        f"{rel}: contains banned token `{needle}` "
                        f"({label}). The `--wp--custom--layout--prose` "
                        "token was purged from the monorepo; fall back "
                        "to the theme's default `contentSize` (780px) "
                        "or choose a different layout token."
                    )

    if r.passed:
        r.details.append(f"{files_scanned} file(s) scanned; no banned token found")
    return r


def check_wc_chrome_sentinel_present() -> Result:
    """Every theme must carry the WC-chrome sentinel block in its
    `theme.json` `styles.css`.

    Context / why this check exists
    -------------------------------
    `bin/append-wc-overrides.py` emits the sentinel-bracketed CSS that
    polishes WooCommerce blocks (account-page grid, cart sidebar,
    checkout actions row, return-to-cart button, notice banners, etc.)
    across every theme in the monorepo. For a long time the script
    hardcoded `THEMES = ["obel", "chonk", ...]`, so a new theme added
    AFTER that list was last edited (Foundry, in PR #29) silently
    skipped every phase and shipped with default WC chrome — visibly
    broken at the account, cart, and checkout routes.

    We've since switched the script to auto-discover themes from disk,
    but that defense is only as strong as "someone remembered to run
    the script before shipping." This check is the second wall: every
    discovered theme must have the top-level sentinel AND the most
    recent phase sentinel in `theme.json`'s `styles.css`. A theme that
    fails this check will not pass `bin/check.py` and therefore cannot
    be committed (pre-commit hook) or merged (CI), which means no
    broken-chrome theme can reach `demo.regionallyfamous.com`.

    What's checked
    --------------
      1. The top-level `/* wc-tells: ... */` ... `/* /wc-tells */`
         region exists in `styles.css`.
      2. The most recently added sentinel (Phase Y) also exists —
         so a theme that was left behind at an older revision of the
         script surfaces as a FAIL rather than a silent PASS.

    Manual fix when this fails: run `python3 bin/append-wc-overrides.py`
    with no arguments. The script auto-discovers every theme now and
    is idempotent, so it's always safe to re-run.
    """
    r = Result("WC chrome sentinel block present in theme.json")
    tj_path = ROOT / "theme.json"
    if not tj_path.exists():
        r.skip("no theme.json at theme root")
        return r
    try:
        data = json.loads(tj_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"theme.json: invalid JSON ({exc}).")
        return r
    css = (data.get("styles", {}) or {}).get("css", "") or ""
    if not isinstance(css, str):
        r.fail("styles.css: expected string value")
        return r

    required_markers = [
        (
            "/* wc-tells: notices, meta, rating, variations, lightbox, "
            "mini-cart, cart, checkout, order-confirm, my-account */",
            "/* /wc-tells */",
            "top-level WC chrome sentinel",
        ),
        (
            "/* wc-tells-phase-y-login-grid-desktop */",
            "/* /wc-tells-phase-y-login-grid-desktop */",
            "Phase Y (desktop 2-column login grid + wide cart/checkout)",
        ),
        (
            "/* wc-tells-phase-z-desktop-wc-chrome-polish */",
            "/* /wc-tells-phase-z-desktop-wc-chrome-polish */",
            "Phase Z (1280px cart/checkout widening + word-wrap order "
            "summary + return-to-cart button style)",
        ),
        (
            "/* wc-tells-phase-aa-return-to-cart-svg-inflow */",
            "/* /wc-tells-phase-aa-return-to-cart-svg-inflow */",
            "Phase AA (return-to-cart SVG in-flow so the arrow sits "
            "beside the label instead of on top of it)",
        ),
    ]
    missing: list[str] = []
    for open_marker, close_marker, label in required_markers:
        if open_marker not in css or close_marker not in css:
            missing.append(label)
    if missing:
        details = ", ".join(missing)
        r.fail(
            f"theme.json styles.css missing: {details}. "
            "Fix: run `python3 bin/append-wc-overrides.py` (idempotent; "
            "auto-discovers every theme; safe to re-run)."
        )
    return r


def check_no_squeezed_wc_sidebars() -> Result:
    """Guard against the WC cart/checkout sidebar-squeeze regression.

    Symptoms (caught in production review on 2026-04-20):
      * Cart page sidebar squeezed to ~200px on tablet/narrow-desktop
        widths -> 'CART TOTALS' wraps to two lines, 'Add coupons'
        wraps to one letter per line, the Proceed-to-Checkout button
        balloons into an oversized pill that overflows the card.
      * Checkout page right column hosting `<order-summary-item>` (a
        nested 64px / 1fr / auto grid) squeezed below ~150px ->
        product names ('Artisanal Silence (8 oz Jar)') and prices wrap
        one glyph per line ('A / r / t / i / s / a / n / a / l').

    Three independent root causes need to all stay fixed for the
    sidebar to render correctly. This rule asserts each one is locked
    in `theme.json` -> top-level `styles.css`:

      1. The original `grid-template-columns:2fr 1fr` shrinks the
         sidebar to below readable width. The fix is
         `grid-template-columns:minmax(0,1fr) minmax(300px,360px)`.
         This rule forbids the bad pattern.

      2. Grid children default to `min-width:auto`, which is the
         intrinsic content width. That defeats `minmax(0, ...)` and
         forces the row to overflow horizontally. Every grid child
         that hosts long-form text inside the sidebar must declare
         `min-width:0`. This rule asserts that for the three
         hot-path selectors.

      3. `word-break:break-all` wraps text on letter boundaries
         instead of word boundaries (it 'fixes' overflow by chopping
         words mid-character). For graceful long-word handling we
         use `overflow-wrap:break-word; word-break:normal` instead.
         This rule forbids `break-all` anywhere in styles.css.

    The CSS that satisfies this lives in
    `bin/append-wc-overrides.py` (`/* wc-tells-cart-sidebar-fix */`
    + `/* wc-tells-checkout-summary-fix */`). If a future edit drops
    a `min-width:0` declaration, re-introduces the `2fr 1fr` grid,
    or sneaks in `word-break:break-all`, this rule fires and the
    bug becomes undeployable.
    """
    r = Result("WC cart/checkout sidebars are not squeeze-prone")
    theme_json = ROOT / "theme.json"
    if not theme_json.exists():
        r.fail("theme.json missing")
        return r
    try:
        data = json.loads(theme_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(str(exc))
        return r
    styles = data.get("styles") or {}
    top_css = styles.get("css") if isinstance(styles.get("css"), str) else ""
    css_norm = re.sub(r"\s+", "", top_css or "")

    # 1. Forbid `grid-template-columns:2fr 1fr` for either sidebar parent.
    bad_grids = {
        ".wc-block-cart{grid-template-columns:2fr1fr": ".wc-block-cart",
        ".wc-block-checkout{grid-template-columns:2fr1fr": ".wc-block-checkout",
    }
    for needle, sel in bad_grids.items():
        if needle in css_norm:
            r.fail(
                f"top-level styles.css applies `grid-template-columns: 2fr 1fr` "
                f"to `{sel}`. On tablet widths (~800-1000px) that collapses "
                f"the sidebar to ~200px and triggers per-letter text wrapping. "
                f"Use `minmax(0,1fr) minmax(300px,360px)` instead."
            )

    # 2. Forbid `word-break:break-all` anywhere. It chops words mid-character
    #    when space is tight; we want word-boundary wrapping via
    #    `overflow-wrap:break-word` + `word-break:normal`.
    if "word-break:break-all" in css_norm:
        r.fail(
            "top-level styles.css contains `word-break: break-all`. That wraps "
            "text on letter boundaries (renders 'Artisanal' as 'A r t i s a n "
            "a l' in tight columns). Use `overflow-wrap: break-word; "
            "word-break: normal` instead so wrapping happens on word boundaries."
        )

    # 3. Require `min-width:0` for the three hot-path sidebar grid children.
    #    Heuristic: find every `{...}` body whose preceding selector list
    #    contains the target selector and verify the body declares
    #    `min-width:0`. Multiple appended chunks may target the same
    #    selector in different rules; any one of them counts.
    required_selectors = [
        ".wc-block-cart__sidebar",
        ".wc-block-checkout__sidebar",
        ".wc-block-components-order-summary-item__description",
    ]
    for selector in required_selectors:
        sel_norm = re.sub(r"\s+", "", selector)
        found = False
        idx = 0
        while True:
            i = css_norm.find(sel_norm, idx)
            if i < 0:
                break
            # Walk forward to the rule body for the rule containing this
            # selector occurrence. Only count this selector if it is at the
            # top of its own rule (i.e. the next `{` is the rule body, not
            # a deeper nested at-rule).
            brace_open = css_norm.find("{", i)
            if brace_open < 0:
                break
            brace_close = css_norm.find("}", brace_open)
            if brace_close < 0:
                break
            body = css_norm[brace_open:brace_close]
            if "min-width:0" in body:
                found = True
                break
            idx = brace_close + 1
        if not found:
            r.fail(
                f"top-level styles.css has no rule that targets `{selector}` "
                f"AND declares `min-width:0`. Without this the grid child "
                f"defaults to `min-width:auto` (== intrinsic content width), "
                f"which forces the row to overflow horizontally and triggers "
                f"per-letter text wrapping inside the sidebar. Append a rule "
                f"like `{selector}{{min-width:0}}` to styles.css."
            )

    if r.passed and not r.skipped:
        r.details.append(
            f"checked {len(required_selectors)} sidebar selector(s) for "
            f"`min-width:0`; verified no `word-break:break-all` and no "
            f"`2fr 1fr` grid for cart/checkout"
        )
    return r


def check_blueprint_landing_page() -> Result:
    """Fail if `playground/blueprint.json`'s `landingPage` is anything other
    than `/`.

    Why this matters:
      The repo's docs/<theme>/index.html homepage redirector sends visitors
      to `…&url=/` (because PAGES[0] in bin/_lib.py is `{"slug": "",
      "url": "/", "label": "Home"}`). Playground's `&url=` query param
      overrides `landingPage` from the blueprint, so a stale `landingPage`
      in the JSON wouldn't immediately break the short URL — but it WOULD
      take effect any time someone:

        - Loads the bare blueprint (drag-and-drop, blueprint editor,
          `?blueprint-url=…` with no extra `&url=`),
        - Embeds the blueprint in a third-party launcher,
        - Builds a deep link from `bin/_lib.playground_deeplink(theme,
          "/")` (which omits `&url=` for the home case in some versions).

      Pinning `landingPage` to `/` keeps the blueprint's standalone
      behaviour aligned with the homepage card on demo.regionallyfamous.com
      ("opens the homepage", not "/shop/" or "/wp-admin/"). This check
      exists because the repo's READMEs once silently disagreed with the
      blueprint about which page visitors land on, and the only way to
      catch that is to assert the contract in code.

    See AGENTS.md (monorepo).
    """
    r = Result("Playground blueprint lands on `/`")
    blueprint_path = ROOT / "playground" / "blueprint.json"
    if not blueprint_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground blueprint)")
        return r
    try:
        data = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.fail(f"playground/blueprint.json: invalid JSON ({exc}). Cannot validate `landingPage`.")
        return r
    landing = data.get("landingPage")
    if landing is None:
        r.fail(
            "playground/blueprint.json: missing `landingPage`. Set it to "
            '`"/"` so the bare blueprint opens the designed homepage '
            "(not WP's default `/wp-admin/` landing). The docs/<theme>/ "
            "redirector forces `&url=/` already, but the blueprint is "
            "consumed standalone too (drag-and-drop, blueprint editor, "
            "third-party launchers)."
        )
    elif landing != "/":
        r.fail(
            f"playground/blueprint.json: `landingPage` is "
            f'`{json.dumps(landing)}`, expected `"/"`. The repo\'s '
            f"homepage card on demo.regionallyfamous.com claims the "
            f"blueprint lands on the home page; keep them in sync. If "
            f"you really do want a different default, update PAGES[0] in "
            f"bin/_lib.py and every README's deeplink table at the same "
            f"time."
        )
    if r.passed and not r.skipped:
        r.details.append("landingPage is `/`")
    return r


def check_front_page_unique_layout() -> Result:
    """Every theme's homepage must be structurally distinct from every other theme's.

    "Different colors and fonts on the same layout" is explicitly disallowed —
    a variant that ships the identical block sequence as obel (or any sibling)
    has not earned its place in the monorepo. Force a real composition.
    """
    r = Result("Front page layout differs from every other theme")
    fp_path = ROOT / "templates" / "front-page.html"
    if not fp_path.exists():
        r.skip("no templates/front-page.html (front page falls through to home/index.html)")
        return r

    my_fp = _front_page_fingerprint(fp_path.read_text(encoding="utf-8"))
    if not my_fp:
        r.fail(
            "templates/front-page.html has no <main> group root, or the root has "
            "no top-level children. Wrap the page in <!-- wp:group "
            '{"tagName":"main", ...} -->.'
        )
        return r

    def _inputs(theme: Path) -> list[Path]:
        return [theme / "templates" / "front-page.html"]

    def _compute(theme: Path) -> list[str]:
        p = theme / "templates" / "front-page.html"
        if not p.exists():
            return []
        return list(_front_page_fingerprint(p.read_text(encoding="utf-8")))

    by_theme = collect_fleet(
        _cross_theme_roots(),
        check_name="front_page_unique_layout",
        input_builder=_inputs,
        compute_fn=_compute,
    )
    conflicts: list[tuple[str, list[str]]] = []
    for slug, other_fp in by_theme.items():
        if not other_fp:
            continue
        if slug == ROOT.name:
            continue
        if other_fp == list(my_fp):
            conflicts.append((slug, other_fp))

    if conflicts:
        names = ", ".join(name for name, _ in conflicts)
        r.fail(
            f"templates/front-page.html has the SAME top-level block sequence as "
            f"{names}. A theme variant must do more than reskin colors and fonts: "
            f"the homepage composition itself must differ. Change the section count, "
            f"swap which dynamic surfaces appear (terms-query, product-collection, "
            f"query, media-text, cover, …), reorder them, or introduce a different "
            f"hero pattern.\n"
            f"  this theme: {my_fp}\n"
            f"  {conflicts[0][0]:<11} {conflicts[0][1]}"
        )
    else:
        r.details.append(
            f"{len(my_fp)} top-level section(s); fingerprint unique vs every other theme"
        )
    return r


def check_no_ai_fingerprints() -> Result:
    r = Result("No AI-fingerprint vocabulary in user-facing files")
    for name in AI_FINGERPRINT_TARGETS:
        path = ROOT / name
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if AI_FINGERPRINT_RE.search(line):
                r.fail(f"{name}:{lineno}: {line.strip()}")
    return r


def check_pdp_has_image() -> Result:
    """Fail if a single-product template has no PDP image block.

    PDP IMAGE FAIL MODE
    -------------------
    The single-product template originally rendered the WC image gallery via
    `wp:woocommerce/product-image-gallery`. The block depends on
    Flexslider + PhotoSwipe wiring at runtime; on Playground (and on a fresh
    WC install where the gallery JS hasn't initialised yet) the markup
    sometimes paints as a single empty cream-coloured box with a
    magnifying-glass icon overlay — the worst possible "PDP that's broken"
    tell on the demo.

    Phase A migrates every theme's single-product PDP to render the image
    via `wp:post-featured-image` instead, which is a server-rendered img
    tag with no JS dependency. To make sure that swap is locked in we
    require the template to render AT LEAST ONE of:

        wp:post-featured-image
        wp:woocommerce/product-image-gallery
        wp:woocommerce/product-image
        wp:woocommerce/product-gallery

    If `wp:woocommerce/product-image-gallery` is the only image block, we
    issue a warning (it's the regression-prone path); the check passes
    because some themes legitimately need it (e.g. for the lightbox).

    See AGENTS.md hard rule "PDP must always have a product image".
    """
    r = Result("PDP single-product template renders a product image block")
    template_paths = [
        ROOT / "templates" / "single-product.html",
        ROOT / "templates" / "single-product-variable.html",
    ]
    template_paths = [p for p in template_paths if p.exists()]
    if not template_paths:
        r.skip("no single-product template found in this theme")
        return r

    image_blocks = (
        "wp:post-featured-image",
        "wp:woocommerce/product-image-gallery",
        "wp:woocommerce/product-image",
        "wp:woocommerce/product-gallery",
    )
    for path in template_paths:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(b in text for b in image_blocks):
            r.fail(
                f"{rel} renders no product image block. PDPs without an "
                f'image are the loudest "this site is broken" tell on '
                f"the demo. Add one of: `wp:post-featured-image` "
                f"(preferred — server-rendered, no JS dependency), "
                f"`wp:woocommerce/product-image-gallery` (legacy — "
                f"depends on Flexslider/PhotoSwipe init), "
                f"`wp:woocommerce/product-image`, or "
                f"`wp:woocommerce/product-gallery`."
            )
            continue
        # If only the legacy gallery block is present, surface that as a
        # detail line so a human reviewer can decide whether to swap to
        # post-featured-image. This is informational, not a fail.
        if (
            "wp:woocommerce/product-image-gallery" in text
            and "wp:post-featured-image" not in text
            and "wp:woocommerce/product-image" not in text
            and "wp:woocommerce/product-gallery" not in text
        ):
            r.details.append(
                f"WARNING: {rel} renders ONLY "
                f"`wp:woocommerce/product-image-gallery`. That block "
                f"sometimes fails to initialise its Flexslider/PhotoSwipe "
                f"JS on Playground and paints as an empty cream box with "
                f"a magnifying-glass icon. Consider swapping to "
                f"`wp:post-featured-image` (server-rendered, no JS)."
            )
    if r.passed and not r.skipped and not r.details:
        r.details.append(f"{len(template_paths)} template(s) checked")
    return r


# Pattern microcopy strings shorter than this are treated as labels
# (e.g. "Shop", "Returns", "Privacy", "Read more", "Read the journal")
# and ignored — they're conventional wayfinding text every store needs
# and re-using them across themes is normal. Anything longer is body
# copy or a headline that must be rewritten in the theme's own voice.
PATTERN_MICROCOPY_MIN_CHARS = 20

# Translatable string call-sites we scan inside patterns/*.php. We
# deliberately exclude the `esc_attr_*` family because those wrap
# alt-text / aria-label / title attributes, which describe the same
# image or icon across themes and SHOULD match by design (an image of
# a coral-linen-tagged glass bottle is a coral-linen-tagged glass bottle
# regardless of the theme's voice).
#
# The string-body subpattern `(?:\\.|(?!\1).)*` skips over backslash-
# escaped characters (e.g. `\'` inside a single-quoted PHP string)
# instead of stopping at the first inner quote. The earlier regex used
# a non-greedy `.*?` which truncated at the first `\'`, so strings like
# `'What if it doesn\'t fit right?'` extracted as just `What if it
# doesn\` and silently collided across themes that all happened to
# start with the same eight letters. Handle escapes properly.
PATTERN_MICROCOPY_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:esc_html_e|esc_html__|_e|__)\s*\(\s*(['"])((?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)


def _extract_pattern_microcopy(patterns_dir: Path) -> dict[str, set[str]]:
    """Map basename → set of long user-facing strings inside each pattern.

    We bucket per-file so the failure message can tell you exactly which
    pattern in the current theme still ships the obel default for the
    same-named pattern.
    """
    out: dict[str, set[str]] = {}
    if not patterns_dir.is_dir():
        return out
    for php in sorted(patterns_dir.glob("*.php")):
        text = php.read_text(encoding="utf-8", errors="ignore")
        strings = {
            m.group(2)
            for m in PATTERN_MICROCOPY_RE.finditer(text)
            if len(m.group(2)) >= PATTERN_MICROCOPY_MIN_CHARS
        }
        if strings:
            out[php.name] = strings
    return out


# Heading content extracted from `<!-- wp:heading {...content":"..."} -->`
# delimiters in template / part HTML files. We treat heading copy with
# the same distinctness rule as pattern microcopy: the same headline
# appearing on two different themes is a "this is the same theme with
# a different paint job" tell.
TEMPLATE_HEADING_RE = re.compile(
    r'<!--\s*wp:heading\s+(\{[^}]*?"content"\s*:\s*"((?:\\"|[^"])*)"[^}]*?\})\s*/?-->',
    re.DOTALL,
)


def _normalize_heading(s: str) -> str:
    """Lowercase + collapse whitespace + strip trailing punctuation so
    "Field notes", "Field notes.", and "Field notes from the workshop"
    all share a comparable normalised core. We keep the words intact;
    the substring/word-overlap test runs on the normalised form."""
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.rstrip(".,;:!?— -")


# Generic wayfinding headings every store needs. These appear on every
# theme by design and should NOT trip the "shared microcopy" check.
# Anything outside this allowlist is treated as voice / brand copy.
SHARED_HEADING_ALLOWLIST = frozenset(
    {
        "shop",
        "categories",
        "cart",
        "checkout",
        "account",
        "my account",
        "log in",
        "register",
        "search results",
        "404",
        "page not found",
        "shop by category",
        "featured products",
        "new arrivals",
        "on sale",
        "related products",
        "you may also like",
        "your cart",
        "order summary",
        "billing",
        "shipping",
        "payment",
        "order details",
    }
)


def _extract_template_headings(theme_dir: Path) -> dict[str, set[str]]:
    """Map relative file path → set of normalised heading copy strings
    found in template + part HTML (excludes wayfinding allowlist)."""
    out: dict[str, set[str]] = {}
    for sub in ("templates", "parts"):
        d = theme_dir / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.html")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            headings: set[str] = set()
            for m in TEMPLATE_HEADING_RE.finditer(text):
                raw = m.group(2).encode("utf-8").decode("unicode_escape", errors="ignore")
                norm = _normalize_heading(raw)
                # Keep headings 4+ chars that aren't pure wayfinding.
                if len(norm) >= 4 and norm not in SHARED_HEADING_ALLOWLIST:
                    headings.add(norm)
            if headings:
                out[path.relative_to(theme_dir).as_posix()] = headings
    return out


def check_no_woocommerce_placeholder_in_findings() -> Result:
    """Fail if the latest `tmp/snaps/<theme>/<viewport>/<route>.findings.json`
    files for the current theme contain "placeholder rendered where a
    product image was expected" warnings.

    Why this exists:
      The WooCommerce placeholder image
      (`woocommerce-placeholder-*.webp`) is the single strongest
      "this is a half-built demo" visual tell on the site. It appears
      whenever a product card or category cover lacks a featured
      image. Common root causes (caught 2026-04-22 on Foundry):
        - `playground/content/product-images.json` is missing, so the
          seeder never sideloads per-theme product images for variant
          parent products.
        - `playground/content/category-images.json` is missing, so
          the seeder never attaches category cover images.
        - The CSV's `Images` column points at a 404 URL (typo in a
          filename or a slug change without a sync).
        - The blueprint inlined `wo-import.php` script ran but was
          rate-limited / network-failed, leaving products with no
          attachment.

      This check looks at the LATEST findings.json files written to
      `tmp/snaps/<theme>/<viewport>/<route>.findings.json` (which
      `bin/snap.py shoot` writes per route + viewport) and fails if
      any of them contains a "Placeholder image rendered where a
      product image was expected" warning. That is the runtime ground
      truth -- if the rendered page shows a placeholder, it doesn't
      matter why; the demo is broken and a Proprietor will lose
      confidence in the theme.

    What this check enforces:
      For each `*.findings.json` under `tmp/snaps/<current-theme>/`,
      collect every issue whose message starts with "Placeholder image
      rendered". If the count is > 0, fail with the affected
      route/viewport list and remediation guidance.

    If no findings.json files exist (e.g. the theme was never shot),
    the check skips. Run `python3 bin/snap.py shoot <theme>` first.

    See AGENTS.md root rule "Every theme that seeds products must seed
    images too".
    """
    r = Result("No WooCommerce placeholder images in latest snap.py findings")

    theme_slug = ROOT.name.lower()
    snaps_root = ROOT.parent / "tmp" / "snaps" / theme_slug
    if not snaps_root.is_dir():
        r.skip(
            f"no `tmp/snaps/{theme_slug}/` (theme has not been shot; run "
            f"`python3 bin/snap.py shoot {theme_slug}` to populate)."
        )
        return r

    placeholder_hits: list[tuple[str, str]] = []  # (route, viewport)
    for findings_path in sorted(snaps_root.rglob("*.findings.json")):
        try:
            data = json.loads(findings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        issues = data.get("issues") or data.get("findings") or []
        for issue in issues:
            msg = (issue.get("message") or issue.get("title") or "").lower()
            if "placeholder" in msg and ("product image" in msg or "expected" in msg):
                viewport = findings_path.parent.name
                route = findings_path.stem.replace(".findings", "")
                placeholder_hits.append((route, viewport))
                break

    if placeholder_hits:
        # Group by viewport for readability.
        from collections import defaultdict

        by_vp: dict[str, list[str]] = defaultdict(list)
        for route, vp in placeholder_hits:
            by_vp[vp].append(route)
        groups = "; ".join(
            f"{vp}: {', '.join(sorted(set(routes)))}" for vp, routes in sorted(by_vp.items())
        )
        r.fail(
            f"`{theme_slug}` is rendering the WooCommerce placeholder "
            f"image on {len(placeholder_hits)} cell(s): {groups}. "
            f"This is the strongest 'half-built demo' visual tell. "
            f"Likely fixes (apply in order): "
            f"(1) ensure `{theme_slug}/playground/content/product-images.json` "
            f"and `category-images.json` exist (copy from `obel/` if "
            f"the SKUs match), "
            f"(2) verify the CSV `Images` column points at real URLs "
            f"under `{theme_slug}/playground/images/`, "
            f"(3) re-shoot with `python3 bin/snap.py shoot {theme_slug}` "
            f"to refresh the findings."
        )
        return r

    r.details.append(
        f"scanned {sum(1 for _ in snaps_root.rglob('*.findings.json'))} "
        f"findings.json files; no placeholder rendering."
    )
    return r


def check_product_reviews_uses_inner_blocks_not_legacy_render() -> Result:
    """Fail if any template/part/pattern contains a self-closing
    `<!-- wp:woocommerce/product-reviews /-->` tag.

    Why this exists:
      A SELF-CLOSING `wp:woocommerce/product-reviews` block (no inner
      blocks between the opener and closer) triggers WC's
      `ProductReviews::render_legacy_block()` path:

        protected function render( $attributes, $content, $block ) {
            if ( empty( $block->parsed_block['innerBlocks'] ) ) {
                return $this->render_legacy_block( $attributes, $content, $block );
            }
            …
        }

      That path delegates to WP's `comments_template()` → WC's
      `templates/single-product-reviews.php`, which emits a plain
      `<select id="rating" name="rating">` with no Interactivity
      hooks. On block themes, WooCommerce intentionally does NOT
      enqueue `wc-single-product.js` (see
      `class-wc-frontend-scripts.php:527` — gated on
      `! wp_is_block_theme()`), so the select is NEVER converted to
      the styled stars widget. Shoppers see a raw native dropdown
      with "Rate…" as the placeholder option (reported 2026-04-24).

      The fix is to expand the block to the modern inner-block
      structure (`product-reviews-title`, `product-review-template`,
      `product-reviews-pagination`, `product-review-form`). The
      inner-block path uses the WP Interactivity API — loaded on
      every block theme by core — so the `<select id="rating-selector">`
      is hidden and replaced by the `.stars-wrapper` radio group
      automatically, with no theme-side enqueue.

    What this check enforces:
      A byte-level scan of every `.html` under `templates/` and
      `parts/`, and every `.php` under `patterns/`, for the exact
      self-closing delimiter pattern. Any hit fails the check and
      lists the file + line + remediation hint.

      The modern opener `<!-- wp:woocommerce/product-reviews -->`
      (without the trailing space+slash) is allowed — that's the
      correct, inner-block-carrying shape.

    Related runtime gate:
      `check_no_unstyled_review_rating_in_findings` watches the
      `product-simple.reviews-open` snap flow for the failure
      symptom. This static check catches the CAUSE before the flow
      even runs.
    """
    r = Result("Product-reviews block uses modern inner-block structure")

    theme_slug = ROOT.name.lower()
    # Previously this hardcoded the six shipped theme slugs, which
    # silently skipped every new theme. Switch to a presence check on
    # a `single-product.html` template so every theme with a PDP gets
    # gated against the legacy-render regression.
    has_pdp = (ROOT / "templates" / "single-product.html").is_file() or (
        ROOT / "single-product.html"
    ).is_file()
    if not has_pdp:
        r.skip(f"theme `{theme_slug}` has no single-product.html — no PDP to gate")
        return r

    # The exact byte-sequence that flips WC into the legacy render
    # path. The block editor normalises whitespace when saving, so
    # any of these three shapes will appear in a stored template:
    #   <!-- wp:woocommerce/product-reviews /-->
    #   <!-- wp:woocommerce/product-reviews/-->
    #   <!-- wp:woocommerce/product-reviews  /-->
    # We match all three via a permissive regex.
    legacy_re = re.compile(r"<!--\s*wp:woocommerce/product-reviews\s*/-->")

    hits: list[tuple[Path, int, str]] = []
    scan_roots = [ROOT / "templates", ROOT / "parts", ROOT / "patterns"]
    scanned = 0
    for scan_root in scan_roots:
        if not scan_root.is_dir():
            continue
        for path in scan_root.rglob("*"):
            if path.suffix.lower() not in (".html", ".php"):
                continue
            if not path.is_file():
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in legacy_re.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                line_text = (
                    text.splitlines()[line_no - 1] if line_no <= len(text.splitlines()) else ""
                )
                rel = path.relative_to(ROOT)
                hits.append((rel, line_no, line_text.strip()))

    if hits:
        lines = "\n  ".join(f"{rel}:{ln}  →  `{preview[:100]}`" for rel, ln, preview in hits)
        r.fail(
            f"`{theme_slug}` has {len(hits)} self-closing "
            f"`<!-- wp:woocommerce/product-reviews /-->` occurrence(s). "
            f"That shape triggers WC's `render_legacy_block()` path, "
            f'which emits a raw `<select id="rating">` the browser '
            f"never restyles (WC skips `wc-single-product.js` on block "
            f"themes). Replace with the modern inner-block structure "
            f"(`product-reviews-title`, `product-review-template`, "
            f"`product-reviews-pagination`, `product-review-form` — see "
            f"any other theme's `templates/single-product.html` for the "
            f"canonical shape). Affected files:\n  {lines}"
        )
        return r

    r.details.append(
        f"scanned {scanned} template/part/pattern file(s); no legacy "
        f"self-closing `wp:woocommerce/product-reviews` found."
    )
    return r


def check_no_unstyled_review_rating_in_findings() -> Result:
    """Fail if the latest `tmp/snaps/<theme>/<viewport>/<route>.findings.json`
    files contain `unstyled-review-rating` warnings.

    Why this exists:
      The runtime counterpart to
      `check_review_stars_fallback_present_per_theme`. The static
      check verifies every theme's `functions.php` carries the
      sentinel block + the right enqueue call; this one verifies
      those enqueues actually work at page-render time. Pair: a
      theme could keep the sentinel but WC could rename the script
      handle, or the `is_product()` gate could start returning false
      on a specific route. Runtime evidence closes those gaps.

      The detector lives in `bin/snap.py`'s page-heuristics pass: it
      fires when a visible `<select id="rating">` (or
      `<select id="rating-selector">` from the newer Interactivity
      block) has no accompanying `<p class="stars">` /
      `<p class="stars-wrapper">` replacement widget. The snap
      `product-simple.reviews-open` flow expands the Reviews
      <details> accordion so the detector can see the form.

    What this check enforces:
      For each `*.findings.json` under `tmp/snaps/<current-theme>/`,
      count every issue whose `kind` field equals
      `unstyled-review-rating`. Fail with the affected route/viewport
      list if the count is > 0.
    """
    r = Result("No unstyled-review-rating findings in latest snap.py evidence")

    theme_slug = ROOT.name.lower()
    snaps_root = ROOT.parent / "tmp" / "snaps" / theme_slug
    if not snaps_root.is_dir():
        r.skip(
            f"no `tmp/snaps/{theme_slug}/` (theme has not been shot; run "
            f"`python3 bin/snap.py shoot {theme_slug}` to populate)."
        )
        return r

    hits: list[tuple[str, str]] = []
    scanned = 0
    for findings_path in sorted(snaps_root.rglob("*.findings.json")):
        scanned += 1
        try:
            data = json.loads(findings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        issues = data.get("issues") or data.get("findings") or []
        for issue in issues:
            kind = (issue.get("kind") or "").lower()
            if kind == "unstyled-review-rating":
                viewport = findings_path.parent.name
                route = findings_path.stem.replace(".findings", "")
                hits.append((route, viewport))
                break

    if hits:
        from collections import defaultdict

        by_vp: dict[str, list[str]] = defaultdict(list)
        for route, vp in hits:
            by_vp[vp].append(route)
        groups = "; ".join(
            f"{vp}: {', '.join(sorted(set(routes)))}" for vp, routes in sorted(by_vp.items())
        )
        r.fail(
            f"`{theme_slug}` is rendering an unstyled native <select> "
            f"for the product review rating on {len(hits)} cell(s): "
            f"{groups}. The `wc-single-product` JS is not executing on "
            f"these pages — either the `review-stars-fallback` sentinel "
            f"block was removed from `{theme_slug}/functions.php`, WC's "
            f"`is_product()` returns false on the snap URL, or WC "
            f"renamed the script handle. Inspect the flow screenshot "
            f"at `tmp/snaps/{theme_slug}/<viewport>/product-simple."
            f"reviews-open.png` and restore the fix."
        )
        return r

    r.details.append(f"scanned {scanned} findings.json files; no unstyled-review-rating.")
    return r


def check_pattern_microcopy_distinct() -> Result:
    """Fail when patterns OR template/part headings ship copy that
    overlaps with another theme's same-named pattern, or whose heading
    string is shared (or contained-within / containing) another theme's
    heading.

    Why this exists
    ---------------
    Two failure modes are unmistakable "this is the same theme with a
    different paint job" tells on the live demo:

    (a) `bin/clone.py` copies obel's patterns into every new theme,
        rewriting only the slug + textdomain. Without a follow-up pass
        the new theme inherits obel's placeholder microcopy ("A short
        statement of intent.", "Two or three sentences explaining why
        your brand exists...") and ships it in production.

    (b) An author drops a heading like "Field notes" onto a theme's
        front-page section without realising another theme already
        owns that phrase ("Field notes from the workshop." in
        selvedge's footer). Even a partial overlap reads as a borrowed
        voice on a side-by-side demo browse.

    What this check enforces
    ------------------------
    PATTERNS: pairwise across every theme — for each pattern file in
    the current theme, compare its translatable strings ≥
    PATTERN_MICROCOPY_MIN_CHARS chars to the same-named pattern in
    every other theme. Fail on any byte-identical match.

    TEMPLATE/PART HEADINGS: pairwise across every theme — for each
    `wp:heading` in templates/ and parts/, normalise (lowercase,
    collapse whitespace, strip trailing punctuation), drop wayfinding
    allowlist items ("Shop", "Cart", "My Account", …), then fail on
    any (a) byte-identical normalised heading shared with another
    theme, or (b) word-substring overlap where one heading wholly
    contains the other and BOTH are 2+ words.

    The fix is always the same: rewrite the offending string in the
    theme's own brand voice. The check fires per-string so you can see
    exactly which copy is being shared.
    """
    r = Result("Pattern + heading microcopy distinct across themes")

    theme_slug = ROOT.name
    theme_patterns = _extract_pattern_microcopy(ROOT / "patterns")
    theme_headings = _extract_template_headings(ROOT)

    if not theme_patterns and not theme_headings:
        r.skip("no patterns/*.php and no headings in templates/ or parts/")
        return r

    def _pattern_inputs(theme: Path) -> list[Path]:
        d = theme / "patterns"
        return sorted(d.glob("*.php")) if d.is_dir() else []

    def _compute_patterns(theme: Path) -> dict[str, list[str]]:
        raw = _extract_pattern_microcopy(theme / "patterns")
        return {k: sorted(v) for k, v in raw.items()}

    def _headings_inputs(theme: Path) -> list[Path]:
        out: list[Path] = []
        for sub in ("templates", "parts", "patterns"):
            d = theme / sub
            if d.is_dir():
                out.extend(sorted(d.rglob("*.html")))
                out.extend(sorted(d.rglob("*.php")))
        return out

    def _compute_headings(theme: Path) -> dict[str, list[str]]:
        raw = _extract_template_headings(theme)
        return {k: sorted(v) for k, v in raw.items()}

    cached_patterns = collect_fleet(
        _cross_theme_roots(),
        check_name="pattern_microcopy_distinct.patterns",
        input_builder=_pattern_inputs,
        compute_fn=_compute_patterns,
    )
    cached_headings = collect_fleet(
        _cross_theme_roots(),
        check_name="pattern_microcopy_distinct.headings",
        input_builder=_headings_inputs,
        compute_fn=_compute_headings,
    )

    # PATTERN-vs-PATTERN: pairwise across every other theme.
    for other in _cross_theme_roots():
        other_slug = other.name
        if other_slug == theme_slug:
            continue
        other_patterns_raw = cached_patterns.get(other_slug) or {}
        other_patterns = {k: set(v) for k, v in other_patterns_raw.items()}
        if not other_patterns:
            continue
        for fname, strings in sorted(theme_patterns.items()):
            other_set = other_patterns.get(fname, set())
            if not other_set:
                continue
            for s in sorted(strings & other_set):
                short = s if len(s) <= 80 else s[:77] + "..."
                r.fail(
                    f"patterns/{fname}: ships microcopy verbatim shared "
                    f"with {other_slug}/patterns/{fname} — "
                    f'"{short}" — rewrite in {theme_slug}\'s voice'
                )

    # HEADING-vs-HEADING: pairwise across every other theme. We compare
    # the union of every heading in the current theme against the union
    # of every heading in each other theme (NOT same-file matched —
    # "Field notes" in aero front-page collides with "Field notes from
    # the workshop" in selvedge footer).
    if theme_headings:
        my_all = set().union(*theme_headings.values())
        for other in _cross_theme_roots():
            other_slug = other.name
            if other_slug == theme_slug:
                continue
            other_headings_raw = cached_headings.get(other_slug) or {}
            other_headings = {k: set(v) for k, v in other_headings_raw.items()}
            if not other_headings:
                continue
            other_all = set().union(*other_headings.values())

            for h in sorted(my_all):
                # (a) byte-identical normalised heading shared.
                if h in other_all:
                    rel = next(
                        (rel for rel, hs in theme_headings.items() if h in hs),
                        "?",
                    )
                    r.fail(
                        f'{rel}: ships heading "{h}" shared verbatim '
                        f"with {other_slug} — rewrite in {theme_slug}'s "
                        f"voice (every theme on the demo browse should "
                        f"speak in its own voice end-to-end)"
                    )
                    continue
                # (b) word-overlap: one heading wholly contains the
                # other AND both are 2+ words AND the shared core is
                # 2+ words. This catches "Field notes" ⊂ "Field notes
                # from the workshop." but doesn't fire on single-word
                # accidents like "Featured" ⊂ "Featured products".
                my_words = h.split()
                if len(my_words) < 2:
                    continue
                for o in other_all:
                    o_words = o.split()
                    if len(o_words) < 2:
                        continue
                    # Require a contiguous 2+ word phrase shared.
                    shared = _longest_shared_phrase(my_words, o_words)
                    if shared and len(shared.split()) >= 2:
                        rel = next(
                            (rel for rel, hs in theme_headings.items() if h in hs),
                            "?",
                        )
                        r.fail(
                            f'{rel}: heading "{h}" shares the phrase '
                            f'"{shared}" with {other_slug}\'s heading '
                            f'"{o}" — pick a phrase no other theme is '
                            f"already using"
                        )
                        break

    if r.passed and not r.skipped:
        r.details.append(
            f"{len(theme_patterns)} pattern file(s) + "
            f"{len(theme_headings)} template/part file(s) with headings; "
            f"all microcopy distinct vs every other theme"
        )
    return r


# ---------------------------------------------------------------------------
# Comprehensive cross-theme rendered-text distinctness check.
#
# `check_pattern_microcopy_distinct` only looks at:
#   - PHP `__()/_e()/...` strings inside patterns/*.php
#   - `wp:heading` block delimiters in templates/parts
#
# That's a small slice of what the demo actually paints. Every paragraph,
# button label, list item, blockquote, verse, pullquote, footer
# copyright, eyebrow strap, FAQ question, hero subtitle, and care-copy
# block also reads on a side-by-side demo browse — and `bin/clone.py`
# copies them verbatim from obel into every new theme. The audit script
# below documents what we found before this gate was added: 39 distinct
# strings duplicated across 2–5 themes. The check below scans EVERY
# rendered text surface so the same regression can't reach the demo
# again.
#
# Scanned surfaces (in templates/, parts/, patterns/):
#   - block delimiter `"content":"…"` for any of:
#       wp:heading, wp:paragraph, wp:button, wp:list-item, wp:verse,
#       wp:pullquote, wp:preformatted
#   - inner text inside any block-rendered `<h1-6>`, `<p>`, `<li>`,
#     `<button>`, `<a>`, `<figcaption>`, `<blockquote>` tag
#   - PHP `__()/_e()/esc_html_e()/esc_html__()/esc_attr_e()/esc_attr__()`
#     literals inside *.php
# ---------------------------------------------------------------------------

ALL_TEXT_MIN_CHARS = 12

ALL_TEXT_BLOCK_DELIMITER_RE = re.compile(
    r"<!--\s*wp:(?:heading|paragraph|button|list-item|verse|pullquote|preformatted)\s+"
    r'(\{[^}]*?"content"\s*:\s*"((?:\\.|[^"\\])*)"[^}]*?\})\s*/?-->',
    re.DOTALL,
)

ALL_TEXT_INNER_HTML_RE = re.compile(
    r"<(?:h[1-6]|p|li|figcaption|blockquote|button|a)[^>]*>([^<]{4,})"
    r"</(?:h[1-6]|p|li|figcaption|blockquote|button|a)>"
)

ALL_TEXT_PHP_TX_RE = re.compile(
    r"""(?<![A-Za-z0-9_])(?:esc_html_e|esc_html__|esc_attr_e|esc_attr__|_e|__)\s*\(\s*"""
    r"""(['"])((?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)

# Generic wayfinding / system text every store needs end-to-end. Each
# entry must already be normalised (lowercased, whitespace collapsed,
# trailing punctuation stripped) — see `_normalize_for_text_audit`.
ALL_TEXT_ALLOWLIST = frozenset(
    {
        # short imperatives + nav (most are <12 chars and won't reach the
        # check anyway, but we list them defensively)
        "shop",
        "cart",
        "checkout",
        "account",
        "my account",
        "log in",
        "login",
        "register",
        "search",
        "menu",
        "home",
        "about",
        "contact",
        "blog",
        "journal",
        "read more",
        "view all",
        "view cart",
        "add to cart",
        "shop all",
        "shop now",
        "learn more",
        "all",
        "next",
        "previous",
        "back",
        "close",
        "open",
        "submit",
        "subscribe",
        "newsletter",
        "instagram",
        "twitter",
        "facebook",
        "pinterest",
        "tiktok",
        "returns",
        "shipping",
        "help",
        "faq",
        "support",
        "press",
        "careers",
        "company",
        "product",
        "products",
        "collection",
        "collections",
        "categories",
        "category",
        # 404 / search empty states
        "page not found",
        "search results",
        "no results",
        "no posts",
        # cart / checkout system labels
        "continue shopping",
        "order summary",
        "subtotal",
        "total",
        "tax",
        "discount",
        "view details",
        "see details",
        "read the journal",
        "read the story",
        # short attribute / image labels often shared by design (alt-text,
        # status pills, etc.)
        "in stock",
        "out of stock",
        "free",
        "sold out",
        "on sale",
    }
)


def _normalize_for_text_audit(s: str) -> str:
    """Lowercase, collapse whitespace, strip HTML tags, strip trailing
    punctuation. Mirrors `_normalize_heading` but also drops PHP-source
    backslash-escaped quotes and common JSON-encoded characters."""
    s = s.replace("\\'", "'").replace('\\"', '"')
    s = s.replace("\\u2019", "'").replace("\\u2014", "—").replace("\\u2013", "–")
    s = s.replace("\\n", " ").replace("\\/", "/")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower().rstrip(".,;:!?— -")


def _extract_all_rendered_text(theme_dir: Path) -> dict[str, set[str]]:
    """Map normalised user-visible text → set of "{rel}::{raw}" tags.

    We collect every text fragment a visitor would see end-to-end:
    block-delimiter content, inner HTML text, and PHP translatable
    literals. Any fragment whose normalised form is < ALL_TEXT_MIN_CHARS
    or appears in the wayfinding allowlist is dropped — those are
    expected to repeat across themes by design.
    """
    out: dict[str, set[str]] = {}
    for sub in ("templates", "parts", "patterns"):
        d = theme_dir / sub
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*")):
            if not path.is_file() or path.suffix not in {".html", ".php"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = path.relative_to(theme_dir).as_posix()

            fragments: list[str] = []
            for m in ALL_TEXT_BLOCK_DELIMITER_RE.finditer(text):
                # Block-attribute JSON values are unicode-escaped; decode
                # so smart quotes / em-dashes normalise the same way as
                # the inner-HTML form of the same string.
                raw = m.group(2)
                try:
                    raw = raw.encode("utf-8").decode("unicode_escape", errors="ignore")
                except Exception:
                    pass
                fragments.append(raw)
            for m in ALL_TEXT_INNER_HTML_RE.finditer(text):
                fragments.append(m.group(1))
            if path.suffix == ".php":
                for m in ALL_TEXT_PHP_TX_RE.finditer(text):
                    fragments.append(m.group(2))

            for raw in fragments:
                norm = _normalize_for_text_audit(raw)
                if len(norm) < ALL_TEXT_MIN_CHARS:
                    continue
                if norm in ALL_TEXT_ALLOWLIST:
                    continue
                out.setdefault(norm, set()).add(rel)
    return out


def check_all_rendered_text_distinct_across_themes() -> Result:
    """Fail when ANY rendered text fragment in this theme appears
    verbatim (after case-insensitive whitespace normalisation) in
    another theme.

    Why this exists
    ---------------
    `check_pattern_microcopy_distinct` only inspects PHP translatable
    strings inside patterns/*.php and the `content` attribute of
    `wp:heading` block delimiters. That misses the long tail of copy
    that actually paints on the demo:

        - paragraph body text (`wp:paragraph`)
        - button labels (`wp:button`, plain `<a class=…__link>`)
        - list items, blockquotes, verses, pullquotes, preformatted
        - eyebrow / strap paragraphs
        - footer copyright lines
        - 404 / no-results / coming-soon body copy
        - order-confirmation step lists ("01 — Confirmation", …)
        - care + shipping policy paragraphs on PDPs

    A single audit pass against every theme on this branch found 39
    such duplicate strings, all originating from `bin/clone.py` copying
    obel verbatim into the new theme without a follow-up voice pass.
    The result reads on a side-by-side demo browse as one shop in
    different paint jobs — exactly the failure mode the project goes
    out of its way to avoid.

    What this check enforces
    ------------------------
    For every theme, walk templates/, parts/, patterns/. From each
    *.html and *.php file, extract:

        (1) every `"content":"…"` value inside a wp:heading,
            wp:paragraph, wp:button, wp:list-item, wp:verse,
            wp:pullquote, or wp:preformatted block delimiter,
        (2) every inner-text run inside a block-rendered <h1-6>, <p>,
            <li>, <button>, <a>, <figcaption>, or <blockquote> tag,
        (3) every PHP `__()/_e()/esc_html_e()/esc_html__()/
            esc_attr_e()/esc_attr__()` literal in *.php files.

    Normalise (lowercase, collapse whitespace, strip trailing
    punctuation, decode JSON unicode escapes and PHP backslash escapes,
    strip inline tags). Drop fragments shorter than
    ALL_TEXT_MIN_CHARS (12 chars) and any fragment in
    ALL_TEXT_ALLOWLIST (functional wayfinding text every store needs).

    Then for every remaining fragment in this theme, fail if the same
    normalised fragment appears in any other theme's surface.

    Fix path
    --------
    Two options when this fires:
      1. If the duplicate is intentional functional / system text,
         add it to ALL_TEXT_ALLOWLIST above (with a comment).
      2. Otherwise, rewrite the offending fragment in this theme's
         own brand voice. `bin/personalize-microcopy.py` holds the
         per-theme substitution map used to clean up the original
         clone-and-skin debt — extend that map and re-run, or edit
         the file directly.
    """
    r = Result("All rendered text distinct across themes")

    theme_slug = ROOT.name
    my_text = _extract_all_rendered_text(ROOT)
    if not my_text:
        r.skip("no templates/, parts/, or patterns/ with rendered text")
        return r

    def _text_inputs(theme: Path) -> list[Path]:
        out: list[Path] = []
        for sub in ("templates", "parts", "patterns"):
            d = theme / sub
            if d.is_dir():
                out.extend(sorted(d.rglob("*.html")))
                out.extend(sorted(d.rglob("*.php")))
        return out

    def _compute_text(theme: Path) -> dict[str, list[str]]:
        # _extract_all_rendered_text returns {normalised: set(rel_paths)};
        # serialize sets as sorted lists for JSON storage.
        return {norm: sorted(rels) for norm, rels in _extract_all_rendered_text(theme).items()}

    cached_text = collect_fleet(
        _cross_theme_roots(),
        check_name="all_rendered_text_distinct",
        input_builder=_text_inputs,
        compute_fn=_compute_text,
    )
    other_index: dict[str, dict[str, set[str]]] = {}
    for other_slug, norm_map in cached_text.items():
        if other_slug == theme_slug:
            continue
        for norm, rels in norm_map.items():
            other_index.setdefault(norm, {})[other_slug] = set(rels)

    collisions = 0
    for norm in sorted(my_text):
        if norm not in other_index:
            continue
        my_rel = next(iter(sorted(my_text[norm])))
        for other_slug, other_rels in sorted(other_index[norm].items()):
            other_rel = next(iter(sorted(other_rels)))
            shown = norm if len(norm) <= 100 else norm[:97] + "..."
            r.fail(
                f"{my_rel}: ships rendered text shared verbatim with "
                f'{other_slug}/{other_rel} — "{shown}" — rewrite in '
                f"{theme_slug}'s voice (or add to ALL_TEXT_ALLOWLIST "
                f"if it's truly system / wayfinding copy)"
            )
            collisions += 1

    if r.passed and not r.skipped:
        r.details.append(
            f"{len(my_text)} text fragment(s) scanned across "
            f"templates/, parts/, patterns/; all distinct vs every "
            f"other theme"
        )
    return r


def _longest_shared_phrase(a: list[str], b: list[str]) -> str:
    """Longest contiguous shared word-sequence between two heading word
    lists, normalised. Returns empty string if no overlap."""
    best = ""
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > 0:
                phrase = " ".join(a[i : i + k])
                if len(phrase) > len(best):
                    best = phrase
    return best


def check_no_default_wc_strings() -> Result:
    """Fail if a theme's functions.php doesn't ship every canonical
    default-WC microcopy override.

    DEFAULT-WC-STRING FAIL MODE
    ---------------------------
    Even after Phases A–E reskin every WC surface, four or five strings
    on the cart, account login, and shop archive are unmistakable
    "this is a stock WooCommerce install" tells:

        - "Showing 1-16 of 55 results"  (loop result count)
        - "Default sorting"             (catalog-sorting first option)
        - "Estimated total"             (cart totals label)
        - "Proceed to Checkout"         (order-button text)
        - "Lost your password?"         (account form link)

    Since the theme-shipped microcopy refactor, every theme owns its
    own override block bracketed by `// === BEGIN wc microcopy ===`
    sentinels at the bottom of `<theme>/functions.php`. The block
    rewrites those strings in that theme's brand voice. This check
    asserts both halves: the sentinel block is present, AND each of
    the canonical override fragments survives inside it. Drop the
    block and the live demo paints with stock WC strings; drop a
    fragment and the matching surface regresses individually.

    The check is per-theme because the override block is per-theme
    (each theme has its own voice + text domain). The previous
    iteration scanned the inlined mu-plugin in blueprint.json; that
    mu-plugin was deleted because shopper-facing brand must travel
    with the released theme, not be bolted on by a Playground-only
    must-use plugin.

    See AGENTS.md hard rule "No default WC strings on the live demo".
    """
    r = Result("Default WC microcopy is overridden in <theme>/functions.php")
    fn_path = ROOT / "functions.php"
    if not fn_path.exists():
        r.skip("no functions.php (theme without PHP bootstrap)")
        return r

    src = fn_path.read_text(encoding="utf-8")
    begin = "// === BEGIN wc microcopy ==="
    end = "// === END wc microcopy ==="
    if begin not in src or end not in src:
        r.fail(
            "functions.php has no `// === BEGIN wc microcopy === ... "
            "// === END wc microcopy ===` block. The live demo will "
            "paint with WC's default strings (\"Showing 1-16 of 55 "
            'results", "Default sorting", "Estimated total", '
            '"Proceed to Checkout", "Lost your password?"). Append '
            "the canonical block to `functions.php` (see obel/functions.php "
            "for the reference shape) — it MUST live in the theme so the "
            "overrides ship when the theme is dropped into wp-content/themes/."
        )
        return r

    block = src[src.index(begin) : src.index(end) + len(end)]

    # Each entry: a fragment of the override that MUST appear in the
    # block, plus the user-facing default string it displaces. Fragments
    # are intentionally narrow (the WP filter hook name or the literal
    # WC default string in the gettext map) so a future refactor that
    # splits the filter into multiple closures still works as long as
    # the displaced string still gets replaced.
    required = [
        ("woocommerce_blocks_cart_totals_label", '"Estimated total" cart totals label'),
        ("woocommerce_order_button_text", '"Proceed to Checkout" / "Place order" button text'),
        (
            "woocommerce_default_catalog_orderby_options",
            '"Default sorting" catalog-sorting first option',
        ),
        ("Lost your password?", '"Lost your password?" account login link'),
        (
            "render_block_woocommerce/product-results-count",
            '"Showing 1-16 of 55 results" loop result count '
            "(rewritten in place via render_block filter — a "
            "woocommerce_before_shop_loop echo would produce a duplicate "
            "floating count inside wp:woocommerce/product-collection)",
        ),
    ]
    for needle, label in required:
        if needle not in block:
            r.fail(
                f"functions.php wc microcopy block is missing the override "
                f"for {label} (looked for `{needle}` between the BEGIN/END "
                f"sentinels). The default string will paint on the live demo."
            )

    if r.passed and not r.skipped:
        r.details.append(
            f"all {len(required)} default-WC microcopy overrides "
            f"present in functions.php wc microcopy block"
        )
    return r


def check_no_brand_filters_in_playground() -> Result:
    """Forbid shopper-facing brand filters in any `playground/*.php`.

    BRAND-IN-PLAYGROUND FAIL MODE
    -----------------------------
    The `playground/` directory is for boot-time setup that has no
    analogue on a real WordPress install: WXR import, WC catalogue
    seeding, demo cart pre-fill, swatch markup, payment-icon strip.
    Anything that affects what a real shopper sees on a released theme
    MUST live in the theme directory (`<theme>/functions.php`,
    templates, parts, patterns, `theme.json`, `styles/`, `style.css`)
    so the override travels with the theme when a Proprietor downloads
    it and drops it into `wp-content/themes/`.

    Before the theme-shipped microcopy refactor, `wo-microcopy-mu.php`
    in `playground/` registered ~12 filters that affected exactly that
    surface area: cart/checkout `gettext` map, sort labels, pagination
    arrows, result-count rewrite, WC Blocks button text, required-field
    marker swap. The mu-plugin was inlined into every blueprint and
    nothing else; release-only consumers got bare WC default strings.
    The fix moved every filter into `<theme>/functions.php` and
    deleted the mu-plugin. This check guarantees no future regression:
    if any `add_filter` / `add_action` registered against a known
    brand-affecting hook reappears in `playground/*.php`, the gate
    fails, names the file, names the hook, and points at the rule.

    The denylist is conservative on purpose. Hooks that legitimately
    only matter at boot (`init`, `wp_loaded`, `woocommerce_init`,
    `woocommerce_loaded`, `pre_get_posts` for the seed step, etc.)
    are never on it; only hooks that change a string a shopper reads
    or HTML a shopper sees are denied.

    Allowlist: a forbidden hook may be registered if its `add_filter`
    call sits inside an `if ( defined('WO_DEMO_ONLY') )` (or any
    `defined('WO_*')` constant) guard, so a future genuine demo-only
    override can opt out of the rule explicitly. The check looks for
    `defined(` within 200 chars before the `add_filter` call.

    See AGENTS.md root-rule "Shopper-facing brand lives in the theme,
    not in playground/".
    """
    r = Result("playground/*.php registers no shopper-facing brand filters")
    pg_dir = MONOREPO_ROOT / "playground"
    if not pg_dir.is_dir():
        r.skip("no playground/ directory")
        return r

    # Hooks whose every callback rewrites a string a shopper reads
    # (gettext family, WC Blocks React strings, sort labels, page-title
    # visibility) or HTML a shopper sees (form-field marker, archive
    # result-count rewrite, pagination arrows). Wildcards are matched
    # by prefix.
    forbidden_exact = {
        "gettext",
        "gettext_with_context",
        "ngettext",
        "ngettext_with_context",
        "woocommerce_form_field",
        "woocommerce_default_catalog_orderby_options",
        "woocommerce_catalog_orderby",
        "woocommerce_pagination_args",
        "woocommerce_show_page_title",
        "woocommerce_order_button_text",
        "woocommerce_order_button_html",
        # Page-level brand surfaces migrated out of the now-deleted
        # `playground/wo-pages-mu.php` and `playground/wo-swatches-mu.php`
        # into per-theme `<theme>/functions.php` blocks between
        # `// === BEGIN <slug> ===` sentinels. Re-registering any of these
        # from `playground/` would silently double-paint in the demo and
        # disappear entirely on a real install.
        "woocommerce_before_customer_login_form",
        "woocommerce_after_customer_login_form",
        "woocommerce_cart_is_empty",
        "woocommerce_no_products_found",
        "woocommerce_before_main_content",
        "woocommerce_dropdown_variation_attribute_options_html",
        # `body_class` once carried the `theme-<slug>` filter from the
        # now-deleted `playground/wo-pages-mu.php`. Each theme now
        # hardcodes its own slug in the `// === BEGIN body-class ===`
        # block; playground has no business touching frontend body
        # classes.
        "body_class",
    }
    forbidden_prefix = (
        "render_block_woocommerce/",
        "woocommerce_blocks_",
    )

    # Marker classes that only ever appear inside theme-shipped paint
    # callbacks or theme-shipped patterns. If they reappear in any
    # `playground/*.php` file the brand surface is leaking out of the
    # theme directory: at runtime via a mu-plugin, or at seed time via
    # an inline HEREDOC inside `wo-configure.php` (the previous home of
    # the branded empty-cart-block before it migrated to each theme's
    # `patterns/cart-page.php`, which `wo-configure.php` now reads via
    # `include` + output buffering). Comments are stripped from the
    # source by the scrubber below so HISTORICAL NOTE blocks in the
    # gutted mu-plugins are safe.
    forbidden_markers = (
        "wo-empty",
        "wo-account-",
        "wo-archive-hero",
        "wo-swatch",
        "wo-payment-icons",
    )

    register_re = re.compile(
        r"add_(?:filter|action)\s*\(\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )

    failures: list[str] = []
    files_scanned = 0
    for php_path in sorted(pg_dir.glob("*.php")):
        files_scanned += 1
        src = php_path.read_text(encoding="utf-8")
        # Strip line + block comments so a docstring example like
        # `add_filter('gettext', ...)` doesn't trip the gate.
        scrubbed = re.sub(r"//[^\n]*", "", src)
        scrubbed = re.sub(r"/\*[\s\S]*?\*/", "", scrubbed)
        for match in register_re.finditer(scrubbed):
            hook = match.group(1)
            denied = hook in forbidden_exact or any(hook.startswith(p) for p in forbidden_prefix)
            if not denied:
                continue
            # Allowlist: if the call sits inside a `defined('WO_*')`
            # guard within 200 chars upstream, treat as opt-out.
            window = scrubbed[max(0, match.start() - 200) : match.start()]
            if re.search(r"defined\s*\(\s*['\"]WO_[A-Z0-9_]+['\"]\s*\)", window):
                continue
            line_no = scrubbed.count("\n", 0, match.start()) + 1
            failures.append(
                f"  playground/{php_path.name}:{line_no}: registers "
                f"`{hook}` — that hook rewrites a string or HTML a "
                f"shopper reads on a real install. Move the filter into "
                f"`<theme>/functions.php` between the "
                f"`// === BEGIN wc microcopy ===` sentinels (or guard "
                f"the registration with `if ( defined( 'WO_DEMO_ONLY' ) )` "
                f"if it really is demo-only)."
            )

        # Marker scan: every `playground/*.php` source. Mu-plugins paint
        # at runtime; `wo-configure.php` paints via post_content seed —
        # both leak shopper-facing brand outside the theme directory if
        # they hardcode a `wo-*` marker. `wo-configure.php` previously
        # HEREDOC'd the branded empty-cart-block; that markup now comes
        # from `<theme>/patterns/cart-page.php` via `include` + output
        # buffering, so the marker stays scoped to the theme directory
        # and the gate can scan the seed script too.
        for marker in forbidden_markers:
            idx = scrubbed.find(marker)
            if idx == -1:
                continue
            line_no = scrubbed.count("\n", 0, idx) + 1
            failures.append(
                f"  playground/{php_path.name}:{line_no}: contains "
                f"`{marker}` marker — that class is part of a per-theme "
                f"paint callback or pattern (see `<theme>/functions.php` "
                f"`// === BEGIN <slug> ===` sentinels and "
                f"`<theme>/patterns/cart-page.php`). Painting it from "
                f"`playground/` would shadow the theme in the demo and "
                f"vanish on a real install."
            )

    if failures:
        r.fail(
            "playground/*.php registers brand-affecting filters; the "
            "release theme will paint with WC default strings because "
            "the mu-plugin doesn't ship with it. See AGENTS.md root-rule "
            '"Shopper-facing brand lives in the theme, not in '
            'playground/":\n' + "\n".join(failures)
        )
    else:
        r.details.append(
            f"scanned {files_scanned} playground/*.php file(s); no "
            f"brand-affecting filter registrations"
        )
    return r


def check_theme_ships_cart_page_pattern() -> Result:
    """Forbid a theme from missing `patterns/cart-page.php`.

    The Cart page's `post_content` is seeded by `playground/wo-configure.php`
    § 11d via `include` + output buffering of the active theme's
    `<theme>/patterns/cart-page.php`. Reading the pattern means the
    branded `wp:woocommerce/empty-cart-block` (with `wo-empty` /
    `wo-empty__title` / `wo-empty__lede` classes + per-theme microcopy
    + per-theme CTA labels) lives inside the theme directory and ships
    with it on a real install — a Proprietor who picks the Cart pattern
    from the editor's Cart-block placeholder dropdown gets exactly the
    same chrome as the Playground demo. Root rule: "Shopper-facing
    brand lives in the theme, not in playground/".

    The check enforces three guarantees per theme:

      1. The file `<theme>/patterns/cart-page.php` exists. Without it,
         the seed step in wo-configure.php silently leaves the Cart
         page on its default WC empty-cart text and the demo regresses
         to a generic "Your cart is currently empty!" line.

      2. The pattern header carries `Block Types: woocommerce/cart`,
         which is what surfaces the pattern in the editor's Cart-block
         placeholder picker on a real install (a Proprietor inserts
         the WC Cart block on a fresh page and the pattern dropdown
         offers this pre-built version). Without the header the file
         is invisible to the editor and a real install never gets the
         branded chrome even if wo-configure has run.

      3. The pattern body contains the branded `wo-empty` markers
         (eyebrow + title + lede + CTA buttons). Without them the
         pattern would seed an unstyled WC empty-cart-block and the
         per-theme empty-cart paint never reaches the shopper.
    """
    r = Result("Each theme ships patterns/cart-page.php with woocommerce/cart Block Types")
    pattern_path = ROOT / "patterns" / "cart-page.php"
    if not pattern_path.is_file():
        r.fail(
            "patterns/cart-page.php missing — `wo-configure.php` § 11d "
            "reads this file via `include` + `ob_start` to seed the "
            "Cart page `post_content`. Without the file the demo Cart "
            "regresses to WC's default empty-cart text and a real "
            "install never gets the branded chrome via the Cart-block "
            "placeholder picker."
        )
        return r

    src = pattern_path.read_text(encoding="utf-8")

    # 1. Block Types header.
    if not re.search(r"^\s*\*\s*Block Types:\s*woocommerce/cart\s*$", src, re.MULTILINE):
        r.fail(
            "patterns/cart-page.php: header is missing "
            "`Block Types: woocommerce/cart`. Without that line the "
            "pattern is invisible to the editor's Cart-block placeholder "
            "picker, so a Proprietor on a real install never sees this "
            "pattern offered when they insert a WC Cart block."
        )

    # 2. Branded empty-cart markers.
    required_markers = (
        "wo-empty wo-empty--cart",
        "wo-empty__eyebrow",
        "wo-empty__title",
        "wo-empty__lede",
    )
    missing = [m for m in required_markers if m not in src]
    if missing:
        r.fail(
            "patterns/cart-page.php: missing branded empty-cart "
            f"markers {missing}. The pattern's empty-cart-block must "
            "carry the same `wo-empty` / `wo-empty__eyebrow` / "
            "`wo-empty__title` / `wo-empty__lede` classes the theme's "
            "`// === BEGIN empty-states ===` callback uses, so the "
            "seeded Cart page picks up the per-theme empty-cart CSS."
        )

    # 3. Sanity: the cart root block must be present at all.
    if "<!-- wp:woocommerce/cart" not in src:
        r.fail(
            "patterns/cart-page.php: contains no `wp:woocommerce/cart` "
            "block — the file is in the right place but doesn't render "
            "a Cart block, so wo-configure.php would seed garbage into "
            "post_content."
        )

    if r.passed and not r.skipped:
        r.details.append(
            "cart-page.php present with `Block Types: woocommerce/cart` "
            "and the four `wo-empty*` markers"
        )
    return r


def check_wc_microcopy_distinct_across_themes() -> Result:
    """Fail if two themes' wc microcopy maps translate the same WC
    default string to the same override (excluding genuine universals
    on the allowlist).

    SAME-VOICE-EVERYWHERE FAIL MODE
    -------------------------------
    Each theme's `<theme>/functions.php` has a `// === BEGIN wc
    microcopy ===` block whose `static $map = array(...);` rewrites
    WC default strings into that theme's voice. A clone (`bin/clone.py`)
    copies obel verbatim, so a fresh variant ships with obel's voice
    until somebody rewrites the map. Without this gate, a side-by-side
    review of five themes reads as "one shop in different paint jobs"
    on every cart, checkout, account-login, and shop-archive surface
    — the exact failure mode the per-theme microcopy refactor exists
    to prevent.

    The check parses each theme's `static $map = array( 'WC default'
    => 'Theme override', ... );` block, groups translations by WC
    default key, and fails on any key whose translation repeats across
    two or more themes UNLESS the WC default is in the universal
    allowlist at `bin/wc_microcopy_universal.json`. The allowlist
    covers tiny utility verbs, single-word financial labels, and
    case-variant duplicates ("Username or email address" / "Username
    or Email Address") where forcing 5 distinct translations would
    feel artificial.

    Failure message names the WC default key, the duplicate translation,
    and the themes sharing it; the fix is to rewrite the offending
    theme's value in its own voice (preferred) or, very rarely, add
    the WC default to `bin/wc_microcopy_universal.json` with a
    one-line rationale.

    See AGENTS.md hard rule "Per-theme WC microcopy must be distinct
    across themes".
    """
    r = Result("WC microcopy maps are distinct across themes")
    allowlist_path = MONOREPO_ROOT / "bin" / "wc_microcopy_universal.json"
    allowlist: set[str] = set()
    if allowlist_path.is_file():
        try:
            raw = json.loads(allowlist_path.read_text(encoding="utf-8"))
            allowlist = {k for k in raw if not k.startswith("_comment")}
        except json.JSONDecodeError as exc:
            r.fail(f"wc_microcopy_universal.json: invalid JSON ({exc}).")
            return r

    begin = "// === BEGIN wc microcopy ==="
    end = "// === END wc microcopy ==="
    # PHP map entry: `'key' => 'value',` (single quotes only — the
    # render template ships single-quoted PHP literals).
    pair_re = re.compile(
        r"'((?:[^'\\]|\\.)*)'\s*=>\s*'((?:[^'\\]|\\.)*)'",
    )

    def php_unquote(literal: str) -> str:
        # PHP single-quoted strings: only \\ and \' are escaped.
        return literal.replace("\\'", "'").replace("\\\\", "\\")

    def _inputs(theme: Path) -> list[Path]:
        return [theme / "functions.php"]

    def _parse_map(theme: Path) -> dict[str, str]:
        fn_path = theme / "functions.php"
        if not fn_path.is_file():
            return {}
        src = fn_path.read_text(encoding="utf-8")
        if begin not in src or end not in src:
            return {}
        block = src[src.index(begin) : src.index(end) + len(end)]
        map_match = re.search(
            r"static\s+\$map\s*=\s*array\s*\(([\s\S]*?)\)\s*;",
            block,
        )
        if not map_match:
            return {}
        map_body = map_match.group(1)
        return {php_unquote(k): php_unquote(v) for k, v in pair_re.findall(map_body)}

    per_theme_raw = collect_fleet(
        _cross_theme_roots(),
        check_name="wc_microcopy_distinct",
        input_builder=_inputs,
        compute_fn=_parse_map,
    )
    per_theme: dict[str, dict[str, str]] = {k: v for k, v in per_theme_raw.items() if v}

    if len(per_theme) < 2:
        r.skip(
            f"only {len(per_theme)} theme(s) ship a wc microcopy map; "
            f"cross-theme comparison needs at least 2"
        )
        return r

    # All keys present in any theme. For each key we'll collect the
    # per-theme translations and look for duplicates.
    all_keys: set[str] = set()
    for m in per_theme.values():
        all_keys.update(m.keys())

    failures: list[str] = []
    pairs_checked = 0
    for key in sorted(all_keys):
        if key in allowlist:
            continue
        # value -> [theme slugs that translate to that value]
        by_value: dict[str, list[str]] = {}
        for slug, m in per_theme.items():
            if key in m:
                by_value.setdefault(m[key], []).append(slug)
        for value, slugs in by_value.items():
            pairs_checked += 1
            if len(slugs) >= 2:
                failures.append(
                    f"  {sorted(slugs)} all translate `{key}` -> "
                    f"`{value}`. Rewrite at least one in its own voice "
                    f"(or, if the WC default genuinely should not vary, "
                    f"add it to bin/wc_microcopy_universal.json)."
                )

    if failures:
        r.fail(
            f"WC microcopy maps share translations across themes "
            f"(checked {pairs_checked} per-key translations across "
            f"{len(per_theme)} themes; see the allowlist at "
            f"bin/wc_microcopy_universal.json for genuine universals):\n" + "\n".join(failures)
        )
    else:
        r.details.append(
            f"checked {pairs_checked} per-key translations across "
            f"{len(per_theme)} themes; every non-allowlisted "
            f"translation is unique"
        )
    return r


def check_playground_content_seeded() -> Result:
    """Fail if a theme ships a playground/blueprint.json without the
    matching playground/content/ + playground/images/ payload.

    UNSEEDED-PLAYGROUND FAIL MODE
    -----------------------------
    Every theme's `playground/blueprint.json` references its own
    `https://raw.githubusercontent.com/RegionallyFamous/fifty/main/<theme>/playground/content/content.xml`
    (WXR import) and `.../content/products.csv` (WC seed step), and a
    fleet of `.../images/*` URLs the WXR + the WC seeder both reach for
    when sideloading attachments. If those files don't exist in the repo
    (or the seeded image set is missing) the live demo cascades:

        * raw.githubusercontent.com returns 404 for content.xml
        * the WXR import step bails
        * every subsequent `wp eval-file` (wo-import.php, wo-configure.php,
          wo-cart.php, …) crashes because it tries to read products WC
          never imported
        * the user sees an unbroken stream of `PHP.run() failed with
          exit code 1` in the browser console and a blank page

    The fix is `python3 bin/seed-playground-content.py --theme <slug>`
    followed by `python3 bin/sync-playground.py`, but the fail mode is
    invisible from a local checkout (the theme dir looks "complete" — it
    has a blueprint, templates, theme.json, patterns…). This check is
    the static gate that makes shipping an unseeded theme impossible.

    See AGENTS.md hard rule "Every Playground blueprint must ship its
    content payload alongside it".
    """
    r = Result("Playground blueprint has its content/ + images/ payload seeded")
    bp_path = ROOT / "playground" / "blueprint.json"
    if not bp_path.exists():
        r.skip("no playground/blueprint.json (theme without a Playground demo)")
        return r

    content_dir = ROOT / "playground" / "content"
    images_dir = ROOT / "playground" / "images"
    content_xml = content_dir / "content.xml"
    products_csv = content_dir / "products.csv"

    missing: list[str] = []
    if not content_xml.exists():
        missing.append("playground/content/content.xml")
    if not products_csv.exists():
        missing.append("playground/content/products.csv")
    if not images_dir.is_dir() or not any(images_dir.iterdir()):
        missing.append("playground/images/ (empty or missing)")

    if missing:
        r.fail(
            "this theme ships a playground/blueprint.json but is "
            "missing its content payload: "
            + ", ".join(missing)
            + ". The live demo will 404 on raw.githubusercontent.com "
            "and every PHP step in the blueprint will exit 1. Run "
            "`python3 bin/seed-playground-content.py --theme "
            f"{ROOT.name}` to copy the canonical wonders-oddities "
            "CSV/WXR/images into this theme, then "
            "`python3 bin/sync-playground.py` to refresh the inlined "
            "mu-plugins, then commit content/ + images/ + the updated "
            "blueprint together."
        )
        return r

    # Bonus: warn if the blueprint references image URLs whose files
    # don't exist on disk. The CSV/XML rewriter in the seed script
    # normally keeps these in sync, but a manual edit could drift.
    try:
        bp_text = bp_path.read_text(encoding="utf-8")
    except OSError:
        bp_text = ""
    image_url_re = re.compile(
        r"raw\.githubusercontent\.com/RegionallyFamous/fifty/main/"
        + re.escape(ROOT.name)
        + r"/playground/images/([A-Za-z0-9._-]+)"
    )
    referenced = set(image_url_re.findall(bp_text))
    on_disk = {p.name for p in images_dir.iterdir() if p.is_file()}
    drift = sorted(referenced - on_disk)
    if drift:
        # Cap the noise — show the first 5 missing files.
        head = ", ".join(drift[:5])
        more = f" (+{len(drift) - 5} more)" if len(drift) > 5 else ""
        r.fail(
            f"playground/blueprint.json references {len(drift)} image "
            f"file(s) that don't exist in playground/images/: {head}{more}. "
            "The blueprint will 404 on those URLs at boot. Re-run "
            "`python3 bin/seed-playground-content.py --theme "
            f"{ROOT.name}` to re-pull the missing assets."
        )
        return r

    asset_count = len(on_disk)
    r.details.append(f"content.xml + products.csv present; {asset_count} image asset(s) on disk")
    return r


def check_no_placeholder_product_images() -> Result:
    """Fail if a theme's `playground/content/products.csv` (or content.xml)
    references the upstream `wonders-<product-slug>.png` flat-cartoon
    placeholders instead of bespoke per-theme `product-wo-<slug>.jpg`
    photographs.

    PLACEHOLDER-IMAGERY FAIL MODE
    -----------------------------
    `bin/seed-playground-content.py` pulls the canonical
    `RegionallyFamous/wonders-oddities` catalogue, which ships flat
    illustrated cartoons under `wonders-<slug>.png` (mug silhouette on
    a yellow background, etc.). Those cartoons are never the look any
    theme actually wants -- every theme is supposed to ship its own
    visual voice as `product-wo-<slug>.jpg` photographs (Y2K iridescent
    chrome for aero, sepia workshop for selvedge, etc.). The seeder
    runs an *upgrade pass* that, when bespoke photos are present in
    `<theme>/playground/images/`, rewrites every CSV/XML reference from
    `wonders-<slug>.png` to `product-wo-<slug>.jpg` and deletes the
    cartoon files.

    The fail modes this check guards:

      * **No bespoke photos generated yet (the aero shape).** The
        seeder copied the upstream cartoons in but no one has produced
        per-theme photographs. The catalogue paints the demo with flat
        cartoons that look nothing like the theme. Fix: generate
        `product-wo-<slug>.jpg` photos for every product slug in this
        theme's voice, drop them in `playground/images/`, then re-run
        the seeder so the upgrade pass swaps the refs.

      * **Photos exist but the seeder upgrade pass never ran (the
        lysholm shape).** The bespoke `product-wo-<slug>.jpg` files
        sit on disk but the CSV/XML still point at the upstream
        cartoons. Fix: re-run `bin/seed-playground-content.py
        --theme <slug>` (idempotent -- it rewrites the refs and cleans
        up the now-unused cartoon PNGs).

      * **CSV references a `product-wo-<slug>.jpg` that's missing on
        disk.** The blueprint will 404 on that URL at boot. Fix: make
        sure the photo is committed at the expected path.

    Page/post hero placeholders (`wonders-page-*.png`,
    `wonders-post-*.png`) are deliberately excluded -- they live on a
    separate generation track and don't have `product-wo-*`
    counterparts.
    """
    r = Result("Product imagery is bespoke (no upstream placeholder cartoons)")
    csv_path = ROOT / "playground" / "content" / "products.csv"
    xml_path = ROOT / "playground" / "content" / "content.xml"
    images_dir = ROOT / "playground" / "images"

    if not csv_path.exists():
        r.skip("no playground/content/products.csv (theme without a Playground demo)")
        return r

    placeholder_re = re.compile(r"wonders-([a-z0-9-]+)\.png")
    bespoke_re = re.compile(r"product-wo-([a-z0-9-]+)\.jpg")

    on_disk = (
        {p.name for p in images_dir.iterdir() if p.is_file()} if images_dir.is_dir() else set()
    )

    failures: list[str] = []
    placeholder_slugs: set[str] = set()
    bespoke_slugs: set[str] = set()

    for label, path in (("products.csv", csv_path), ("content.xml", xml_path)):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in placeholder_re.finditer(text):
            slug = m.group(1)
            if slug.startswith(("page-", "post-")):
                continue
            placeholder_slugs.add(slug)
        for m in bespoke_re.finditer(text):
            slug = m.group(1)
            bespoke_slugs.add(slug)
            if f"product-wo-{slug}.jpg" not in on_disk:
                failures.append(
                    f"playground/content/{label} references "
                    f"`product-wo-{slug}.jpg` but the file is missing from "
                    f"playground/images/. The live demo will 404 on that URL "
                    f"at boot. Re-run `python3 bin/seed-playground-content.py "
                    f"--theme {ROOT.name}` to re-pull the missing asset, or "
                    f"regenerate it."
                )

    if placeholder_slugs:
        sample = sorted(placeholder_slugs)[:5]
        more = f" (+{len(placeholder_slugs) - 5} more)" if len(placeholder_slugs) > 5 else ""
        sample_list = ", ".join(f"`wonders-{s}.png`" for s in sample)
        missing_photos = sorted(
            s for s in placeholder_slugs if f"product-wo-{s}.jpg" not in on_disk
        )
        if missing_photos:
            failures.append(
                f"playground/content/ references {len(placeholder_slugs)} "
                f"upstream cartoon placeholder image(s): "
                f"{sample_list}{more}.\n"
                f"  Of those, {len(missing_photos)} have NO bespoke "
                f"`product-wo-<slug>.jpg` photograph on disk for this theme -- "
                f"the catalogue will paint flat illustrated cartoons instead "
                f"of branded photography. Generate the missing photos as "
                f"`{ROOT.name}/playground/images/product-wo-<slug>.jpg` (one "
                f"per slug, in this theme's visual voice), then re-run "
                f"`python3 bin/seed-playground-content.py --theme {ROOT.name}` "
                f"to swap the CSV/XML refs and clean up the cartoons."
            )
        else:
            failures.append(
                f"playground/content/ references {len(placeholder_slugs)} "
                f"upstream cartoon placeholder image(s) "
                f"({sample_list}{more}) even though every "
                f"matching `product-wo-<slug>.jpg` photograph is already "
                f"on disk. The seeder's upgrade pass never ran on this "
                f"theme -- fix it by running `python3 "
                f"bin/seed-playground-content.py --theme {ROOT.name}` "
                f"(idempotent; rewrites the refs and deletes the now-unused "
                f"cartoons)."
            )

    if failures:
        for f in failures:
            r.fail(f)
        return r

    if not bespoke_slugs:
        r.skip("no product image refs found in CSV/XML")
        return r

    r.details.append(
        f"{len(bespoke_slugs)} bespoke `product-wo-<slug>.jpg` ref(s); "
        f"no upstream placeholder cartoons remaining"
    )
    return r


def check_product_images_unique_across_themes() -> Result:
    """Fail if any `product-wo-<slug>.jpg` is byte-identical across two
    themes -- that's a copy-paste leak, not bespoke per-theme imagery.

    CROSS-THEME COPY-PASTE FAIL MODE
    --------------------------------
    Even when every theme ships the right *count* of
    `product-wo-<slug>.jpg` files (`check_no_placeholder_product_images`
    passes), an entire `playground/images/` folder can still have been
    cloned wholesale from another theme without per-theme regeneration.
    The catalogue then renders with the source theme's photography
    while everything else (`theme.json`, `style.css`, templates,
    patterns) tries to be a different brand. The two real-world hits:

      * **The aero shape (untracked-leftover):** during a generation
        pass, 7 product slugs were skipped, leaving `selvedge`'s
        scratch-copies in `aero/playground/images/`. Those 7 files
        were byte-identical to the matching `selvedge` photos. `git
        status` showed 30 added files and looked complete; only an
        md5/sha256 cross-check across themes surfaced the leak.

      * **The lysholm shape (theme-init copy-paste):** when `lysholm`
        was cloned from `obel` as a starting point, the entire
        `playground/images/` folder was copied verbatim. All 30
        `product-wo-<slug>.jpg` files were byte-identical to `obel`'s.
        The catalogue rendered with obel's quiet-editorial photography
        while the rest of the theme tried to be Nordic home-goods.

    The check sha256-hashes every theme's `playground/images/product-wo-*.jpg`
    files and fails when any two themes share the same digest. Page +
    post hero placeholders (`wonders-page-*.png`, `wonders-post-*.png`)
    live on a separate generation track and are intentionally excluded.

    Remediation hint: the check can't infer which theme is the copier
    vs. the original (no git context at check time), so it names both
    themes involved in the duplication and asks the human to regenerate
    the copier (typically the newer theme) using that theme's voice
    from `<theme>/style.css`'s Description.
    """
    import hashlib

    r = Result("Product photographs are unique across themes (no copy-paste leak)")

    def _inputs(theme: Path) -> list[Path]:
        d = theme / "playground" / "images"
        return sorted(d.glob("product-wo-*.jpg")) if d.is_dir() else []

    def _fp(theme: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in _inputs(theme):
            try:
                out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
        return out

    by_theme = collect_fleet(
        _cross_theme_roots(),
        check_name="product_images_unique",
        input_builder=_inputs,
        compute_fn=_fp,
    )
    total_photos = sum(len(v) for v in by_theme.values())
    if not total_photos:
        r.skip("no product-wo-*.jpg photographs found in any theme")
        return r

    overlaps = find_value_overlaps(by_theme)
    if overlaps:
        themes_involved: dict[frozenset[str], list[tuple[str, list[str]]]] = {}
        for digest, sites in overlaps:
            theme_set = frozenset(slug for slug, _ in sites)
            files = [f"{slug}/{fname}" for slug, fname in sites]
            themes_involved.setdefault(theme_set, []).append((digest, files))

        for theme_set, group in sorted(themes_involved.items(), key=lambda kv: sorted(kv[0])):
            theme_list = ", ".join(sorted(theme_set))
            count = len(group)
            sample = sorted(files for _, files in group)[:3]
            sample_str = "; ".join(" == ".join(f) for f in sample)
            more = f" (+{count - 3} more)" if count > 3 else ""
            r.fail(
                f"{count} product-wo-*.jpg file(s) byte-identical across "
                f"[{theme_list}]: {sample_str}{more}. "
                f"At least one of these themes is shipping another "
                f"theme's photography under its own slug -- the live "
                f"demo will paint the wrong-theme aesthetic for those "
                f"products. Regenerate the duplicates in whichever "
                f"theme is the copier (typically the newer one) using "
                f"that theme's visual voice (see each theme's "
                f"`style.css` Description), drop the new files in "
                f"`<theme>/playground/images/`, and re-run this check "
                f"to confirm uniqueness."
            )
        return r

    r.details.append(
        f"{total_photos} `product-wo-*.jpg` file(s) hashed across all themes; "
        f"every photograph is byte-unique to its theme"
    )
    return r


def check_hero_images_unique_across_themes() -> Result:
    """Fail if any `wonders-page-*.png` or `wonders-post-*.png` is
    byte-identical across two themes (or duplicated within one).

    SISTER FAIL MODE TO `check_product_images_unique_across_themes`
    ----------------------------------------------------------------
    The product-photo check (above) deliberately exempted page +
    post hero placeholders because, at the time, the seeder was
    expected to handle hero uniqueness end-to-end. It does not.
    The selvedge incident demonstrated the gap: every
    `wonders-page-*.png` (8 files) and `wonders-post-*.png` (20
    files) under `selvedge/playground/images/` was byte-identical
    to obel's, so the live demo painted obel's bright coral
    geometric placeholders inside selvedge's dark editorial
    cinematic theme. Visually obvious to a human, completely
    invisible to every other check we ship -- the file COUNT was
    correct, the slugs all matched, the seeder wired the right
    file into each post, and `check_product_images_unique_across_themes`
    walked past hero PNGs by design.

    The check sha256-hashes every theme's `playground/images/`
    `wonders-page-*.png` and `wonders-post-*.png` files and fails
    when any two of those files share the same digest -- whether
    across themes (selvedge shape) or inside a single theme
    (obel shape: 4 page/post heroes shipped as 3 hash groups, so
    `wonders-page-home.png` rendered identically to two unrelated
    journal posts in the live demo). Same remediation shape as
    the product check: name everything involved, point at
    `<theme>/playground/generate-images.py` (or the matching
    bespoke pipeline) as the source of truth, and ask the human
    to regenerate the duplicates.
    """
    import hashlib

    r = Result(
        "Hero placeholders are unique across themes "
        "(no copy-paste leak in wonders-page-*.png / wonders-post-*.png)"
    )

    def _inputs(theme: Path) -> list[Path]:
        d = theme / "playground" / "images"
        if not d.is_dir():
            return []
        return sorted(list(d.glob("wonders-page-*.png")) + list(d.glob("wonders-post-*.png")))

    def _fp(theme: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in _inputs(theme):
            try:
                out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
        return out

    by_theme = collect_fleet(
        _cross_theme_roots(),
        check_name="hero_images_unique",
        input_builder=_inputs,
        compute_fn=_fp,
    )
    total_heroes = sum(len(v) for v in by_theme.values())
    if not total_heroes:
        r.skip("no wonders-page-*.png / wonders-post-*.png placeholders found in any theme")
        return r

    overlaps = find_value_overlaps(by_theme)
    if overlaps:
        themes_involved: dict[frozenset[str], list[tuple[str, list[str]]]] = {}
        for digest, sites in overlaps:
            theme_set = frozenset(slug for slug, _ in sites)
            files = [f"{slug}/{fname}" for slug, fname in sites]
            themes_involved.setdefault(theme_set, []).append((digest, files))

        for theme_set, group in sorted(themes_involved.items(), key=lambda kv: sorted(kv[0])):
            theme_list = ", ".join(sorted(theme_set))
            count = len(group)
            sample = sorted(files for _, files in group)[:3]
            sample_str = "; ".join(" == ".join(f) for f in sample)
            more = f" (+{count - 3} more)" if count > 3 else ""
            r.fail(
                f"{count} hero placeholder(s) byte-identical across "
                f"[{theme_list}]: {sample_str}{more}. At least one of "
                f"these themes is shipping another theme's hero imagery "
                f"under its own slugs -- the live demo will paint the "
                f"wrong-theme aesthetic for every journal post and page "
                f"that uses one of these files. Regenerate the duplicates "
                f"in whichever theme is the copier (typically the newer "
                f"one) using that theme's visual voice (see each theme's "
                f"`style.css` Description and the brief in "
                f"`.cursor/rules/playground-imagery.mdc`); the canonical "
                f"path is `<theme>/playground/generate-images.py` (see "
                f"chonk and selvedge for working examples). Drop the new "
                f"files in `<theme>/playground/images/` and re-run this "
                f"check to confirm uniqueness."
            )
        return r

    r.details.append(
        f"{total_heroes} hero placeholder(s) hashed across all themes; "
        f"every page/post hero is byte-unique to its theme"
    )
    return r


def check_theme_screenshots_distinct() -> Result:
    """Fail when any two themes ship the same ``screenshot.png`` bytes.

    Background
    ----------
    Every WordPress theme has a ``screenshot.png`` (admin Themes screen
    card image, ~1200x900). The convention is that the screenshot is a
    representative shot of the theme rendering — for the Fifty monorepo
    that means the home page from the snap framework, cropped+resized
    by ``bin/build-theme-screenshots.py``.

    Before this check was added, every theme in the monorepo shipped
    the SAME placeholder bytes (md5 was identical across obel/chonk/
    lysholm/selvedge/aero), so the admin Themes grid showed five
    identical cards labelled with five different theme names. Catching
    that in CI keeps the regression from re-appearing — common ways it
    silently re-appears are:

        * `bin/clone.py` copying the source theme's screenshot.png
          verbatim into a new variant and the author forgetting to
          re-run the screenshot builder.
        * A theme being rebaselined but `bin/build-theme-screenshots.py`
          not being re-run, leaving an old screenshot pointing at a
          stale render.
        * A copy-paste between themes in a "fix everything in parallel"
          edit.

    What this check enforces
    ------------------------
    For every theme directory in the monorepo, hash its
    ``screenshot.png`` (sha-256, full file). If any two themes share a
    hash, fail with both theme names — that's the duplicate. Also fail
    if a theme is missing its screenshot.png entirely. We deliberately
    do NOT compare visual similarity — even cropping/resizing slight
    variations of the same source baseline produces distinct bytes, so
    a byte-exact match is the unambiguous regression signal.
    """
    import hashlib

    r = Result("Theme screenshots distinct (no duplicate-bytes)")

    def _inputs(theme: Path) -> list[Path]:
        return [theme / "screenshot.png"]

    def _fp(theme: Path) -> dict[str, str]:
        p = theme / "screenshot.png"
        if not p.exists():
            return {}
        return {"screenshot.png": hashlib.sha256(p.read_bytes()).hexdigest()}

    themes_list = _cross_theme_roots()
    for theme in themes_list:
        if not (theme / "screenshot.png").exists():
            r.fail(f"{theme.name}/: missing screenshot.png")

    by_theme = collect_fleet(
        themes_list,
        check_name="theme_screenshot_distinct",
        input_builder=_inputs,
        compute_fn=_fp,
    )
    # Flatten {slug: {filename: digest}} -> {digest: [slugs]} for the
    # message shape this check has always emitted.
    by_hash: dict[str, list[str]] = {}
    for slug, fps in by_theme.items():
        for digest in fps.values():
            by_hash.setdefault(digest, []).append(slug)
    for digest, themes in by_hash.items():
        if len(themes) > 1:
            r.fail(
                f"{', '.join(sorted(themes))} share identical screenshot.png "
                f"(sha256={digest[:12]}…). Re-run "
                f"`python3 bin/build-theme-screenshots.py` to regenerate "
                f"per-theme screenshots from each theme's home snap."
            )

    return r


# ---------------------------------------------------------------------------
# Heuristic-finding allowlist (READ-side mirror of `bin/snap.py`).
# ---------------------------------------------------------------------------
# The allowlist file at `tests/visual-baseline/heuristics-allowlist.json`
# is the single source of truth for "yes we know about this finding,
# don't fail the gate on it". `bin/snap.py` consults it at WRITE time
# (`_apply_allowlist_to_findings`) so the findings.json files it
# emits already have demotions baked in. But:
#
#   * On a fresh checkout the developer hasn't re-shot yet -- the
#     findings.json on disk was written before the allowlist landed.
#   * After `bin/snap.py allowlist regenerate` adds new entries, every
#     stale findings.json under tmp/ is now wrong by allowlist standards
#     until re-shot (~127s per theme).
#
# Either case has the static check failing on findings the allowlist
# already covers -- gate noise that pushes contributors back to
# `--no-verify`. Mirror the apply-at-read logic here so the source of
# truth wins regardless of when the findings.json was written. Kept
# small and self-contained on purpose -- the snap.py canonical version
# does the same thing with a cache + per-cell in-place mutation, but
# this read-only helper just needs (kind, fingerprint) -> bool.
#
# When updating: keep `_AXE_ALLOWLIST_PATH`, the key shape
# `theme:viewport:route`, and `_axe_finding_fingerprint`'s
# `fingerprint`-then-`selector` precedence in sync with
# `bin/snap.py:ALLOWLIST_PATH`, `_allowlist_key`, and
# `_finding_fingerprint`. There's a self-test in
# `tests/check_py/test_axe_allowlist.py` that asserts both
# implementations agree on a synthetic finding.
_AXE_ALLOWLIST_PATH = MONOREPO_ROOT / "tests" / "visual-baseline" / "heuristics-allowlist.json"


def _load_axe_allowlist() -> dict[str, dict[str, set[str]]]:
    """Return `{theme:viewport:route -> {kind -> {fingerprint, ...}}}`.

    Missing/malformed file becomes `{}` (no suppressions). Sets
    instead of lists for O(1) membership tests in the hot loop below.
    """
    if not _AXE_ALLOWLIST_PATH.is_file():
        return {}
    try:
        data = json.loads(_AXE_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, set[str]]] = {}
    for key, kinds in data.items():
        if not isinstance(kinds, dict):
            continue
        cell: dict[str, set[str]] = {}
        for kind, fps in kinds.items():
            if not isinstance(fps, list):
                continue
            cell[str(kind)] = {str(fp) for fp in fps if isinstance(fp, str)}
        if cell:
            out[str(key)] = cell
    return out


def _axe_finding_fingerprint(f: dict) -> str | None:
    """Mirror of `bin/snap.py:_finding_fingerprint`. Prefer the
    explicit `fingerprint` field, fall back to `selector`. Returns
    None when neither is available -- matches snap.py's policy that
    such findings can't be allowlisted (they're an unconditional
    failure)."""
    fp = f.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp
    sel = f.get("selector")
    if isinstance(sel, str) and sel:
        return sel
    return None


def _axe_merge_allowlist_cells(
    allowlist: dict[str, dict[str, set[str]]],
    theme: str,
    viewport: str,
    route: str,
) -> dict[str, set[str]]:
    """Mirror of `snap.py:_merge_allowlist_cells` for the read-side.

    Unions the per-theme cell with the cross-theme `*:viewport:route`
    cell. Wildcard selector sets (containing `"*"` or empty) win
    immediately for that kind so a single global wildcard entry
    suppresses every finding of that kind on every theme."""
    merged: dict[str, set[str]] = {}
    for key in (f"{theme}:{viewport}:{route}", f"*:{viewport}:{route}"):
        cell = allowlist.get(key)
        if not cell:
            continue
        for kind, selectors in cell.items():
            existing = merged.get(kind)
            if existing is None:
                merged[kind] = set(selectors)
                continue
            existing_wild = (not existing) or ("*" in existing)
            new_wild = (not selectors) or ("*" in selectors)
            if existing_wild or new_wild:
                merged[kind] = {"*"}
            else:
                merged[kind] = existing | set(selectors)
    return merged


def _axe_finding_is_allowlisted(
    allowlist: dict[str, dict[str, set[str]]],
    theme: str,
    viewport: str,
    route: str,
    finding: dict,
) -> bool:
    """True iff this finding's (kind, fingerprint) is registered for
    this (theme, viewport, route) cell. Findings already marked
    `allowlisted` (e.g. because snap.py demoted them at write time
    and a tool kept the marker) also count, so a stale findings.json
    that was generated against an older allowlist still respects
    today's policy.

    Wildcard support (mirror of `bin/snap.py:_apply_allowlist_to_findings`):
    a cell entry whose selector set contains `"*"` -- or that is empty
    -- matches every finding of that `kind` on that route, regardless
    of fingerprint. Used by `vision:*` findings (no DOM address) and
    by globally-allowlisted heuristic kinds.

    Cross-theme wildcard: a `*:viewport:route` cell unions on top of
    the per-theme cell, so a chronic cross-theme finding can be
    suppressed in one place instead of N.
    """
    if finding.get("allowlisted"):
        return True
    cell = _axe_merge_allowlist_cells(allowlist, theme, viewport, route)
    if not cell:
        return False
    kind = str(finding.get("kind") or "")
    if kind not in cell:
        return False
    selectors = cell[kind]
    if (not selectors) or ("*" in selectors):
        return True
    fp = _axe_finding_fingerprint(finding)
    if fp is None:
        return False
    return fp in selectors


def check_no_serious_axe_in_recent_snaps() -> Result:
    """Fail if any `tmp/snaps/<theme>/<viewport>/*.findings.json` for the
    current theme records a `severity: "error"` finding (axe-core
    impact >= serious).

    Why this exists:
      `bin/snap.py` runs axe-core on every captured page and writes
      its violations into a per-route `*.findings.json` payload, with
      axe `serious`/`critical` mapped to our internal `error` severity
      (see `_AXE_IMPACT_TO_SEVERITY` in `bin/snap.py`). The visual
      gate (`bin/snap.py check`) already fails on those — but it's an
      OPT-IN step (`bin/check.py --visual`) that pre-commit and the
      default `--offline` CI loop don't invoke. The result is the
      embarrassing failure mode this check exists to prevent: a real
      axe-core violation (e.g. 1.27:1 placeholder contrast on
      Selvedge's checkout) sits in `tmp/snaps/.../findings.json` for
      hours, but the offline gate is green and pre-commit waves the
      change through.

      This check closes the loop without forcing every contributor to
      pay the 2-5 minute Playground boot cost in `--offline`: if the
      developer (or CI worker, or agent) HAS recently shot the theme,
      the artifacts on disk are treated as evidence and any serious
      finding fails the static gate. Re-shooting with the fix in
      place clears the artifacts; deleting them with `rm -rf
      tmp/snaps/<theme>` also clears the gate for contributors who
      haven't run snap at all.

    What this check enforces:
      Walk `tmp/snaps/<theme>/**/findings.json`. For each file, parse
      the top-level `findings: []` array and collect every entry
      where `severity == "error"`. Group by `kind` (e.g.
      `a11y-color-contrast`) so multiple repeated nodes of the same
      axe rule report as one group with a node count. Fail with the
      route+viewport coordinates so the offending page is one click
      away.

      Skips gracefully when:
        * `tmp/snaps/<theme>/` doesn't exist (developer never ran snap)
        * No `*.findings.json` exists under it (snap was interrupted)
        * Every findings file parses but contains no error-severity
          entries (theme is clean — the common path).
    """
    r = Result("Recent snaps carry no serious axe-core errors")
    require_evidence = os.environ.get("FIFTY_REQUIRE_SNAP_EVIDENCE") == "1"
    snaps_dir = MONOREPO_ROOT / "tmp" / "snaps" / ROOT.name
    missing_msg = (
        f"tmp/snaps/{ROOT.name}/ has no findings (snap not run for this theme). "
        f"Run `python3 bin/snap.py shoot {ROOT.name}` to generate evidence."
    )
    if not snaps_dir.is_dir():
        if require_evidence:
            r.fail(
                f"FIFTY_REQUIRE_SNAP_EVIDENCE=1 but tmp/snaps/{ROOT.name}/ does not exist. "
                f"Run `python3 bin/snap.py shoot {ROOT.name}` first."
            )
        else:
            r.skip(f"no tmp/snaps/{ROOT.name}/ on disk (snap not run for this theme)")
        return r

    findings_files = sorted(snaps_dir.rglob("*.findings.json"))
    if not findings_files:
        if require_evidence:
            r.fail(
                f"FIFTY_REQUIRE_SNAP_EVIDENCE=1 but no *.findings.json under "
                f"tmp/snaps/{ROOT.name}/. {missing_msg}"
            )
        else:
            r.skip(f"tmp/snaps/{ROOT.name}/ exists but has no *.findings.json files")
        return r

    allowlist = _load_axe_allowlist()
    failures: list[str] = []
    files_checked = 0
    error_total = 0
    allowlisted_total = 0
    for fp in findings_files:
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        findings = payload.get("findings") or []
        if not isinstance(findings, list):
            continue
        files_checked += 1
        # Derive (viewport, route) from the file path so we can ask the
        # allowlist whether each finding has already been triaged. Layout
        # is `tmp/snaps/<theme>/<viewport>/<route>.findings.json` (route
        # may itself contain dots, e.g. `checkout-filled.field-focus`).
        try:
            rel_to_snaps = fp.relative_to(snaps_dir)
            viewport = rel_to_snaps.parts[0]
            route = fp.stem
            if route.endswith(".findings"):
                route = route[: -len(".findings")]
        except (ValueError, IndexError):
            viewport, route = "", ""

        # Collapse same-kind errors so the message stays compact:
        # one entry per axe rule per route/viewport. Allowlisted
        # findings counted separately for the summary line so the
        # backlog stays visible without failing the gate.
        by_kind: dict[str, dict] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            if f.get("severity") != "error":
                continue
            if _axe_finding_is_allowlisted(allowlist, ROOT.name, viewport, route, f):
                allowlisted_total += 1
                continue
            kind = f.get("kind", "unknown")
            entry = by_kind.setdefault(kind, {"count": 0, "first": None, "axe_url": None})
            entry["count"] += 1
            if entry["first"] is None:
                entry["first"] = f.get("message", "")[:200]
                entry["axe_url"] = f.get("axe_help_url")
        if by_kind:
            try:
                rel = fp.relative_to(MONOREPO_ROOT)
            except ValueError:
                rel = fp
            for kind, info in sorted(by_kind.items()):
                error_total += info["count"]
                msg = f"  {rel}: {kind} x{info['count']} -- {info['first']}"
                if info["axe_url"]:
                    msg += f" (see {info['axe_url']})"
                failures.append(msg)

    if failures:
        hint = (
            f"{error_total} NEW severity:error finding(s) across snap "
            f"artifacts for {ROOT.name} (not in "
            f"tests/visual-baseline/heuristics-allowlist.json). Re-shoot "
            f"with the fix in place (`python3 bin/snap.py shoot "
            f"{ROOT.name}`) to clear, or `rm -rf tmp/snaps/{ROOT.name}` "
            f"if you intend to drop the evidence. If this is intentional "
            f"backlog, run `python3 bin/snap.py allowlist regenerate "
            f"--theme {ROOT.name}` to add the entries"
        )
        if allowlisted_total:
            hint += f"; {allowlisted_total} pre-existing allowlisted finding(s) suppressed"
        r.fail(hint + ":\n" + "\n".join(failures))
        return r

    detail = (
        f"scanned {files_checked} findings file(s) under "
        f"tmp/snaps/{ROOT.name}/; no NEW severity:error entries"
    )
    if allowlisted_total:
        detail += (
            f" ({allowlisted_total} suppressed via tests/visual-baseline/heuristics-allowlist.json)"
        )
    r.details.append(detail)
    return r


def check_visual_baseline_present() -> Result:
    """Fail if a SHIPPING theme has no committed visual baselines.

    Why this exists:
      `tests/visual-baseline/<theme>/<viewport>/<route>.png` is the
      committed reference that `bin/snap.py diff` (and the
      `visual.yml` CI workflow) diffs against. A theme with NO
      baseline files at all looks "green" to the diff because there's
      nothing to diff -- the same loophole as the no-snap SKIP, but
      one layer up. Aero shipped without baselines for weeks and the
      gate never noticed.

      This check enforces "every SHIPPING theme has at least one PNG
      under tests/visual-baseline/<theme>/". The downstream
      `bin/snap.py diff` is responsible for catching new routes that
      don't yet have a baseline (it already does, via the "no
      baseline at this path" row).

    Why only SHIPPING (not incubating):
      An incubating theme is still being iterated on — microcopy, photo
      pass, front-page restructure, etc. Generating baselines before
      the theme is visually done is wasted work: the first committed
      baseline would diverge from reality on the very next design
      iteration. The `first-baseline.yml` workflow automatically
      generates baselines AND promotes stage to "shipping" once a
      theme is ready; until then, no baseline requirement.

    Skips gracefully when:
      * `FIFTY_SKIP_VISUAL_BASELINE_CHECK=1` is set (escape hatch
        for fixture-only test themes that don't ship baselines).
      * The theme's `readiness.json` declares `stage != "shipping"`
        (incubating / retired themes are exempt).
    """
    r = Result("Visual baseline directory exists for this theme")
    if os.environ.get("FIFTY_SKIP_VISUAL_BASELINE_CHECK") == "1":
        r.skip("FIFTY_SKIP_VISUAL_BASELINE_CHECK=1")
        return r
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _readiness import STAGE_SHIPPING, load_readiness

    readiness = load_readiness(ROOT)
    if readiness.stage != STAGE_SHIPPING:
        r.skip(
            f"stage={readiness.stage!r} — baselines only required for shipping themes "
            "(see .github/workflows/first-baseline.yml for auto-promotion)"
        )
        return r
    baseline_dir = MONOREPO_ROOT / "tests" / "visual-baseline" / ROOT.name
    if not baseline_dir.is_dir():
        r.fail(
            f"no tests/visual-baseline/{ROOT.name}/ directory. Run "
            f"`python3 bin/snap.py shoot {ROOT.name} && "
            f"python3 bin/snap.py baseline {ROOT.name} --missing-only` "
            "and commit the PNGs so visual diff has something to compare against."
        )
        return r
    pngs = list(baseline_dir.rglob("*.png"))
    if not pngs:
        r.fail(
            f"tests/visual-baseline/{ROOT.name}/ exists but contains no PNGs. "
            f"Run `python3 bin/snap.py baseline {ROOT.name} --missing-only` "
            "and commit the result."
        )
        return r
    r.details.append(f"{len(pngs)} baseline PNG(s) under tests/visual-baseline/{ROOT.name}/")
    return r


def check_allowlist_entries_resolve() -> Result:
    """Fail if `tests/visual-baseline/heuristics-allowlist.json` references
    a theme/viewport/route triple that doesn't exist in `bin/snap_config.py`.

    Why this exists:
      The allowlist suppresses pre-existing heuristic findings so a
      theme can ship while a known issue is on the to-fix queue. But
      typo'd entries (e.g. `selvedge:wide:checkout` after the route
      was renamed to `checkout-filled`) silently match nothing, so a
      genuine regression in the renamed route walks straight through
      the gate without being suppressed-or-failed -- it's just
      ignored. This check turns those orphan entries into a hard
      failure with the offending key named.

      Wildcard cells (kind => ["*"] or kind => []) are still checked
      for the theme:viewport:route key existing; only the selector
      list is allowed to be empty/wildcard.

    Skips gracefully when:
      * The allowlist file doesn't exist (no entries to validate).
    """
    r = Result("heuristics-allowlist.json entries resolve to known cells")
    allowlist_path = _AXE_ALLOWLIST_PATH
    if not allowlist_path.is_file():
        r.skip("no heuristics-allowlist.json on disk")
        return r
    try:
        raw = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.fail(f"could not parse {allowlist_path}: {e}")
        return r
    if not isinstance(raw, dict):
        r.fail(f"{allowlist_path} top-level must be an object; got {type(raw).__name__}")
        return r

    sys.path.insert(0, str(MONOREPO_ROOT / "bin"))
    try:
        import snap_config
    except ImportError as e:
        r.skip(f"could not import snap_config: {e}")
        return r

    valid_themes = {p.name for p in MONOREPO_ROOT.iterdir() if (p / "theme.json").is_file()}
    valid_viewports = {v.name for v in snap_config.VIEWPORTS}
    valid_routes = {route.slug for route in snap_config.ROUTES}
    # snap.py also emits per-interaction variants named
    # `<route>.<interaction>` (e.g. `checkout-filled.field-focus`)
    # whenever an INTERACTIONS entry exists for that route. Treat
    # those as valid lookup targets too so allowlist entries pinned
    # to the post-interaction snapshot don't get flagged as orphans.
    interactions = getattr(snap_config, "INTERACTIONS", {}) or {}
    for route_slug, interaction_list in interactions.items():
        for interaction in interaction_list:
            valid_routes.add(f"{route_slug}.{interaction.name}")

    orphans: list[str] = []
    for key in raw:
        parts = str(key).split(":")
        if len(parts) != 3:
            orphans.append(f"{key} (malformed; expected theme:viewport:route)")
            continue
        theme, viewport, route = parts
        if theme != "*" and theme not in valid_themes:
            orphans.append(f"{key} (unknown theme `{theme}`)")
            continue
        if viewport not in valid_viewports:
            orphans.append(f"{key} (unknown viewport `{viewport}`)")
            continue
        if route not in valid_routes:
            orphans.append(f"{key} (unknown route `{route}`)")

    if orphans:
        r.fail(
            f"{len(orphans)} orphan allowlist entr(ies) in "
            f"{allowlist_path.relative_to(MONOREPO_ROOT)}:\n  "
            + "\n  ".join(orphans)
            + "\nDelete or rename them; orphans silently suppress nothing."
        )
        return r
    r.details.append(f"all {len(raw)} allowlist cell(s) resolve.")
    return r


def check_evidence_freshness() -> Result:
    """Fail if uncommitted source edits are newer than the most recent
    snap evidence for this theme.

    Why this exists:
      AGENTS.md rule #18 says "snap before declaring done." Phase 1 of
      the closed-loop plan turns that aspiration into a gate. After
      you edit a theme.json/template/part/pattern/style/functions
      file, the corresponding `tmp/snaps/<theme>/**/findings.json`
      mtime should be newer than the source mtime -- otherwise the
      evidence is stale and the offline gate is reading findings
      from the PRE-edit world. Pre-commit then waves the change
      through because old findings happen to be green.

    What this enforces:
      For the current theme:
        1. Find every theme source file (theme.json, functions.php,
           templates/**, parts/**, patterns/**, styles/**) that has
           uncommitted edits in the working tree.
        2. Find the most recent `*.findings.json` mtime under
           `tmp/snaps/<theme>/`.
        3. Fail if any uncommitted source edit is newer than that
           findings mtime, OR if there's a source edit but no
           findings exist at all.

    Skips gracefully when:
      * `git` isn't available (no way to know what's uncommitted)
      * No uncommitted edits to source (committed code path -- the
        Phase 1 spec says we trust commits-with-snaps; freshness only
        gates the WIP path)
      * The escape hatch FIFTY_SKIP_EVIDENCE_FRESHNESS=1 is set (used
        by the pre-push hook AFTER it's already run a fresh visual
        gate; double-gating would be redundant).
    """
    r = Result("Snap evidence is fresh vs uncommitted source edits")
    if os.environ.get("FIFTY_SKIP_EVIDENCE_FRESHNESS") == "1":
        r.skip("FIFTY_SKIP_EVIDENCE_FRESHNESS=1 (pre-push already ran the visual gate)")
        return r
    if not shutil.which("git"):
        r.skip("git not available on PATH")
        return r

    theme_root = ROOT
    try:
        rel_theme = theme_root.relative_to(MONOREPO_ROOT)
    except ValueError:
        r.skip("theme outside monorepo root")
        return r

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", str(rel_theme)],
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        r.skip(f"git status failed: {e}")
        return r
    if proc.returncode != 0:
        r.skip(f"git status returned {proc.returncode}: {proc.stderr.strip()}")
        return r

    source_suffixes = {".json", ".php", ".html", ".css"}
    source_dirs = (
        "theme.json",
        "functions.php",
        "styles",
        "templates",
        "parts",
        "patterns",
        "playground",
    )
    edited_sources: list[Path] = []
    for line in proc.stdout.splitlines():
        if not line or len(line) < 4:
            continue
        # Porcelain format: XY<space>path[ -> renamed-path]
        rest = line[3:]
        path_str = rest.split(" -> ")[-1].strip().strip('"')
        p = MONOREPO_ROOT / path_str
        if not p.is_file():
            continue
        try:
            sub = p.relative_to(theme_root)
        except ValueError:
            continue
        # Only count actual theme source files; tmp/, screenshot
        # regen, .DS_Store etc don't gate evidence freshness.
        first = sub.parts[0] if sub.parts else ""
        if first not in source_dirs and p.name not in {"theme.json", "functions.php"}:
            continue
        if p.suffix.lower() not in source_suffixes:
            continue
        edited_sources.append(p)

    if not edited_sources:
        r.skip("no uncommitted source edits in this theme")
        return r

    snaps_dir = MONOREPO_ROOT / "tmp" / "snaps" / theme_root.name
    findings_files = sorted(snaps_dir.rglob("*.findings.json")) if snaps_dir.is_dir() else []
    if not findings_files:
        r.fail(
            f"{len(edited_sources)} uncommitted source file(s) in {theme_root.name} "
            f"but no snap evidence exists at tmp/snaps/{theme_root.name}/. "
            f"Run `python3 bin/snap.py shoot {theme_root.name}` "
            "to generate fresh findings before committing."
        )
        return r

    latest_findings = max(f.stat().st_mtime for f in findings_files)

    stale: list[tuple[Path, float]] = []
    for src in edited_sources:
        try:
            src_mtime = src.stat().st_mtime
        except OSError:
            continue
        if src_mtime > latest_findings + 1.0:  # 1s slop for filesystem rounding
            stale.append((src, src_mtime - latest_findings))

    if stale:
        bullets = []
        for src, delta in sorted(stale, key=lambda x: -x[1])[:10]:
            try:
                rel = src.relative_to(MONOREPO_ROOT)
            except ValueError:
                rel = src
            bullets.append(f"  {rel} (newer than newest findings by {delta:.0f}s)")
        r.fail(
            f"{len(stale)} source file(s) edited after the latest snap "
            f"({len(findings_files)} findings file(s) under "
            f"tmp/snaps/{theme_root.name}/). Re-shoot with "
            f"`python3 bin/snap.py shoot {theme_root.name}` so findings "
            f"reflect the post-edit state, then re-run the gate.\n" + "\n".join(bullets)
        )
    return r


def check_wc_specificity_winnable() -> Result:
    """Fail if any selector in `bin/append-wc-overrides.py`'s CHUNKS
    has lower CSS specificity than the matching WooCommerce Blocks
    default selector.

    Why this exists:
      Today's Selvedge bug -- placeholder text rendering at 1.27:1
      against the input chrome -- was a cascade-loss: our override
      `body .wc-block-components-text-input input` (specificity
      0,1,2) was being beaten by WC Blocks' default
      `.wc-block-components-form .wc-block-components-text-input input`
      (0,3,1). Phase 1 of the closed-loop plan: detect this kind of
      cascade-loss STATICALLY, before the `body` prefix ever ships.

    How:
      1. Import bin/append-wc-overrides.py and walk every selector
         in its CSS chunks. Compute the selector's specificity.
      2. Group those selectors by their rightmost compound (base
         element + classes + attrs + pseudo-classes). For each
         compound, find the maximum specificity WC Blocks ships for
         the SAME compound (looked up in bin/wc-blocks-specificity.json).
      3. If our specificity is STRICTLY LESS THAN WC's max -> fail.
         Equal specificity is a win because theme styles load AFTER
         plugin styles (source-order tiebreaker).
      4. Filter out non-runtime WC selectors (editor-only, loading-
         state, theme-namespaced) so we don't chase ghosts.
      5. Honor bin/wc-specificity-known-losses.json: pre-existing
         losses are grandfathered so the gate only catches NEW
         regressions, not the historical tech debt this gate found
         on initial rollout. To regenerate the baseline after fixing
         losses, re-run this check and copy the reported losses
         into the JSON file (or delete the file to fail loud on
         everything).

    Skips when:
      * bin/wc-blocks-specificity.json is missing (run
        `python3 bin/build-wc-specificity-index.py`)
      * bin/append-wc-overrides.py is missing
    """
    r = Result("WC override selectors win the cascade vs WC Blocks defaults")
    spec_index = MONOREPO_ROOT / "bin" / "wc-blocks-specificity.json"
    overrides_script = MONOREPO_ROOT / "bin" / "append-wc-overrides.py"
    losses_baseline = MONOREPO_ROOT / "bin" / "wc-specificity-known-losses.json"
    if not spec_index.is_file():
        r.skip(
            f"missing {spec_index.relative_to(MONOREPO_ROOT)}; run "
            "`python3 bin/build-wc-specificity-index.py` to generate it"
        )
        return r
    if not overrides_script.is_file():
        r.skip(f"missing {overrides_script.relative_to(MONOREPO_ROOT)}")
        return r

    try:
        index = json.loads(spec_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.fail(f"failed to read {spec_index}: {e}")
        return r

    wc_version = (index.get("_meta") or {}).get("wc_version", "unknown")
    wc_selectors: dict[str, tuple[int, int, int]] = {
        sel: tuple(spec) for sel, spec in (index.get("selectors") or {}).items()
    }

    grandfathered: set[str] = set()
    if losses_baseline.is_file():
        try:
            grandfathered = set(
                json.loads(losses_baseline.read_text(encoding="utf-8")).get("selectors") or []
            )
        except (OSError, json.JSONDecodeError):
            pass

    # Lazy-import the override script to get its CHUNKS list. The
    # script is sentinel-based so importing it doesn't run the
    # injection loop; the chunks are module-level constants.
    import importlib.util

    spec = importlib.util.spec_from_file_location("_append_wc_overrides", overrides_script)
    if spec is None or spec.loader is None:
        r.fail("failed to load bin/append-wc-overrides.py for selector inspection")
        return r
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as e:
        r.fail(f"failed to import bin/append-wc-overrides.py: {e}")
        return r

    chunks = getattr(module, "CHUNKS", None)
    if not chunks:
        r.skip("bin/append-wc-overrides.py has no CHUNKS attribute to inspect")
        return r

    sys.path.insert(0, str(MONOREPO_ROOT / "bin"))
    try:
        from build_wc_specificity_index import (  # type: ignore
            compute_specificity,
            iter_selectors,
        )
    except ImportError:
        # build-wc-specificity-index.py uses a hyphenated name; load
        # it directly via importlib instead.
        builder_path = MONOREPO_ROOT / "bin" / "build-wc-specificity-index.py"
        if not builder_path.is_file():
            r.skip("bin/build-wc-specificity-index.py not present; cannot parse selectors")
            return r
        builder_spec = importlib.util.spec_from_file_location("_wc_spec_builder", builder_path)
        if builder_spec is None or builder_spec.loader is None:
            r.fail("failed to load build-wc-specificity-index.py")
            return r
        builder_mod = importlib.util.module_from_spec(builder_spec)
        try:
            builder_spec.loader.exec_module(builder_mod)  # type: ignore[union-attr]
        except Exception as e:
            r.fail(f"failed to import build-wc-specificity-index.py: {e}")
            return r
        compute_specificity = builder_mod.compute_specificity  # type: ignore[assignment]
        iter_selectors = builder_mod.iter_selectors  # type: ignore[assignment]

    # Index WC selectors by their rightmost compound so we can compare
    # apples to apples. WC's `.wc-block-components-form .text-input
    # input` compound key is `(input, set(), set(), set())`; our
    # `body .text-input input` compound key matches it.
    def _compound_key(selector: str) -> tuple[str, frozenset, frozenset, frozenset]:
        rightmost = re.split(r"\s*[ >+~]\s*", selector.strip())[-1]
        rightmost = re.sub(r"::[A-Za-z][A-Za-z0-9-]*", "", rightmost)
        type_match = re.match(r"^([a-zA-Z][a-zA-Z0-9-]*)", rightmost)
        base = type_match.group(1).lower() if type_match else ""
        classes = frozenset(re.findall(r"\.[A-Za-z_][A-Za-z0-9_-]*", rightmost))
        attrs = frozenset(re.findall(r"\[[^\]]+\]", rightmost))
        pcs = frozenset(
            m.group(0).split("(", 1)[0]
            for m in re.finditer(r":(?!:)[A-Za-z][A-Za-z0-9-]*(?:\([^)]*\))?", rightmost)
        )
        return (base, classes, attrs, pcs)

    # Filter out WC selectors that only fire in non-runtime contexts
    # (editor previews, loading shimmers, theme-specific has-* state
    # classes). Those legitimately have higher specificity but won't
    # paint over our overrides at visitor-render time.
    _NONRUNTIME_TOKENS = (
        ".editor-styles-wrapper",
        ".block-editor-",
        ".is-loading",
        ".is-disabled",
        ".has-dark-controls",
        ".has-light-controls",
        ".wp-admin",
    )

    def _wc_selector_is_runtime(sel: str) -> bool:
        return all(tok not in sel for tok in _NONRUNTIME_TOKENS)

    wc_by_compound: dict[tuple, tuple[tuple[int, int, int], str]] = {}
    for sel, spec_tuple in wc_selectors.items():
        if not _wc_selector_is_runtime(sel):
            continue
        key = _compound_key(sel)
        existing = wc_by_compound.get(key)
        if existing is None or spec_tuple > existing[0]:
            wc_by_compound[key] = (spec_tuple, sel)

    losses: list[str] = []
    selectors_checked = 0
    theme_only = 0
    grand_tolerated = 0

    for chunk in chunks:
        # CHUNKS entries in bin/append-wc-overrides.py are 4-tuples
        # `(sentinel_open, sentinel_close, css, prev_marker)`. Be
        # defensive: also accept dict / dataclass shapes if the
        # script is refactored later.
        css_text = ""
        if isinstance(chunk, (tuple, list)) and len(chunk) >= 3:
            css_text = chunk[2]
        elif isinstance(chunk, dict):
            css_text = chunk.get("css", "") or ""
        else:
            css_text = getattr(chunk, "css", "") or ""
        if not css_text:
            continue
        for sel in iter_selectors(css_text):
            selectors_checked += 1
            our_spec = compute_specificity(sel)
            key = _compound_key(sel)
            wc_entry = wc_by_compound.get(key)
            if wc_entry is None:
                theme_only += 1
                continue
            wc_spec, wc_sel = wc_entry
            if our_spec < wc_spec:
                if sel in grandfathered:
                    grand_tolerated += 1
                    continue
                losses.append(
                    f"  ours    = {our_spec}  ({sel})\n      WC max  = {wc_spec}  ({wc_sel})"
                )

    if losses:
        r.fail(
            f"{len(losses)} NEW override selector(s) lose the cascade "
            f"against WC Blocks (WC {wc_version}). Either boost specificity "
            f"in bin/append-wc-overrides.py (doubled-class trick: "
            f"`.foo.foo` instead of `body .foo`), or add the selector to "
            f"bin/wc-specificity-known-losses.json if you're knowingly "
            f"deferring the fix.\n" + "\n".join(losses)
        )
        return r

    r.details.append(
        f"{selectors_checked} override selector(s) checked vs WC "
        f"{wc_version}, {len(wc_selectors)} WC selectors indexed "
        f"({theme_only} theme-only selectors skipped); "
        f"{grand_tolerated} grandfathered loss(es) tolerated per "
        f"bin/wc-specificity-known-losses.json"
    )
    return r


def check_view_transitions_wired() -> Result:
    """Rule #22 — every theme MUST wire the four pieces of the cross-
    document View Transitions contract documented in AGENTS.md
    "View Transitions (cross-document)":

      1. CSS prelude in `theme.json` declares the opt-in plus a
         default `view-transition-type` (so `:root:active-view-
         transition-type(fifty-default)` selectors have something to
         match on the cold-path navigation).
      2. `render_block` filter in `functions.php` covers the four
         block names that render product/post titles and images
         (core/post-title, core/post-featured-image,
         woocommerce/product-image, woocommerce/product-image-gallery).
      3. The per-request dedup tracker is reset on `init` (otherwise
         long-lived PHP workers leak `view-transition-name` state
         between requests and silently drop names on later pages).
      4. The inline `pageswap`/`pagereveal` handler is registered on
         `wp_head` priority 1 (parser-blocking, classic script) AND
         the `<script type="speculationrules">` block is emitted from
         `wp_head`. Both must be present — the first makes the per-
         route flavor selectable from CSS, the second is the largest
         perceived-perf lever for cross-document VT.

    Failure mode this catches: a theme regressing on any of the four
    pieces (e.g. a clone that shipped before the WC product-image
    block was added to the filter) silently breaks the morph at
    runtime — `bin/snap.py`'s click-through probe will eventually
    catch it too, but this static gate fails the pre-push hook with
    a precise diagnostic instead of a manifest entry buried in tmp/.
    """
    r = Result("rule #22 — view transitions wired (theme.json + functions.php)")
    theme_json = ROOT / "theme.json"
    functions_php = ROOT / "functions.php"
    if not theme_json.exists():
        r.skip("no theme.json (not a theme directory)")
        return r
    if not functions_php.exists():
        r.fail("missing functions.php (theme cannot wire VT without it)")
        return r

    css = theme_json.read_text(encoding="utf-8")
    php = functions_php.read_text(encoding="utf-8")

    # Piece 1 — CSS prelude with @view-transition + at least one
    # named type that pairs with the JS handler in piece 4.
    if "@view-transition" not in css:
        r.fail(
            "theme.json styles.css is missing `@view-transition` opt-in "
            "(no cross-document transitions will fire)"
        )
    if "fifty-default" not in css:
        r.fail(
            "theme.json styles.css is missing the `types: fifty-default` "
            "descriptor on `@view-transition` — required so CSS rules can "
            "use `:root:active-view-transition-type(fifty-default)` for "
            "the cold-path navigation"
        )

    # Piece 2 — render_block filter MUST cover the four block names.
    # We grep for the literal block strings rather than parsing PHP
    # so a theme that registers an additional block name (e.g. a
    # custom card block) still passes — we only require the four
    # core+Woo blocks to be present.
    required_blocks = (
        "core/post-title",
        "core/post-featured-image",
        "woocommerce/product-image",
        "woocommerce/product-image-gallery",
    )
    missing_blocks = [b for b in required_blocks if b not in php]
    if missing_blocks:
        r.fail(
            "functions.php render_block filter does not name "
            + ", ".join(f"`{b}`" for b in missing_blocks)
            + " — cross-document image morph will silently no-op for "
            + "those block(s); extend the `$names` map in the "
            + "`render_block` filter"
        )

    # Piece 3 — per-request dedup reset on `init`.
    if "fifty_vt_assigned" not in php:
        r.fail(
            "functions.php is missing the `fifty_vt_assigned` per-page "
            "dedup tracker (long-lived PHP workers will leak "
            "`view-transition-name` state across requests)"
        )

    # Piece 4 — pageswap/pagereveal handler + speculationrules.
    if "fifty_view_transitions_inline_script" not in php:
        r.fail(
            "functions.php is missing the inline pageswap/pagereveal "
            "handler (`fifty_view_transitions_inline_script`) — without "
            "it the per-route flavor classes (fifty-shop-to-detail, "
            "fifty-paginate, fifty-cart-flow) never get added and the "
            "CSS in theme.json has nothing to match against"
        )
    elif "wp_head" not in php or "fifty_view_transitions_inline_script" not in php:
        r.fail(
            "the inline VT handler must be registered on `wp_head` so "
            "the pagereveal listener installs before the destination's "
            "first paint"
        )
    if "speculationrules" not in php:
        r.fail(
            'functions.php is missing the `<script type="speculationrules">` '
            "block (`fifty_view_transitions_speculation_rules`) — the "
            "largest perceived-perf lever for cross-document VT"
        )

    if r.passed and not r.skipped:
        r.details.append(
            "@view-transition opt-in, types descriptor, 4 named blocks, "
            "dedup reset, inline pageswap handler, speculation rules — all wired"
        )
    return r


def check_concept_similarity() -> Result:
    """Cross-concept similarity audit. Wraps `bin/check-concept-similarity.py`.

    Runs the same tag-overlap + perceptual-hash analysis as
    `bin/audit-concepts.py` but in a Result-returning shape so the
    standard check.py table picks it up. Pairs flagged as warnings
    keep `r.passed == True` (so the gate doesn't block on iterative
    overlap that the Proprietor will resolve out of band); only true
    duplicates (5/5 axis overlap or pHash distance ≤ 2) flip the
    Result to failed, and even those can be allowlisted in
    `bin/concept-similarity-allowlist.json`.

    The work itself lives in the standalone script so it can also be
    run by hand (`python3 bin/check-concept-similarity.py --json`)
    while triaging the allowlist.
    """
    r = Result("Concept queue similarity (tag overlap + perceptual hash)")
    # Importing here (not at module scope) keeps cold-start cheap for
    # the 99% of runs that don't end up needing the similarity audit.
    # The hyphen in the filename means we go through importlib rather
    # than a normal `import` statement.
    try:
        from importlib import import_module

        sim_mod = import_module("check-concept-similarity")
    except ImportError as e:
        r.skip(f"could not import check-concept-similarity ({e})")
        return r
    sub = sim_mod.run_check()
    if sub.skipped:
        r.skip(sub.details[0] if sub.details else "no concept metas to compare")
        return r
    # The sub-script appends both fails AND warns to `details` but
    # only flips `passed` for true duplicates. Mirror that here by
    # re-classifying via the message wording (the only stable signal
    # since `_Result.warn` discards the fail/warn distinction). Fails
    # come from the hard thresholds in run_check() and use one of two
    # specific phrasings we own.
    for d in sub.details:
        if "duplicate concept" in d or "near-identical" in d:
            r.fail(d)
        else:
            r.details.append(d)
    return r


def check_no_unpushed_commits() -> Result:
    """Fail if local HEAD has commits that haven't reached origin yet.

    This catches a recurring silent-failure mode: an agent makes a fix,
    commits it, claims "fix is live", but never runs `git push`. The
    Playground demos load themes from `raw.githubusercontent.com/.../main/`
    so any commit that hasn't been pushed is invisible to anyone visiting
    the live demo, even though the local checkout, `git log`, and
    `bin/snap.py` (which mounts the local theme dir) all see the fix.

    We treat unpushed commits as a HARD FAIL rather than a warning so the
    CI/pre-commit loop refuses to declare success while a fix is sitting
    only on the local branch. The user can override by pushing or by
    rebasing the unpushed commits away.

    Skips gracefully if:
      * `git` isn't available
      * the working tree isn't a git repo
      * the current branch has no upstream (e.g. detached HEAD, or a
        feature branch that hasn't been published yet)

    The check is monorepo-wide -- it runs once per theme but always reports
    the same answer for the same git state. We don't dedupe because the
    extra ~10ms per theme is negligible and keeps the per-theme report
    self-contained.
    """
    r = Result("No unpushed commits on current branch (push before claiming a fix is live)")
    # Pre-push hook escape hatch: when this script is invoked FROM the
    # `.githooks/pre-push` hook, the to-be-pushed commits are by
    # definition not yet on the remote (that's the whole point of the
    # hook), so this check would deadlock the push it's supposed to
    # protect. The hook sets FIFTY_SKIP_UNPUSHED_CHECK=1 around its
    # `bin/check.py` invocation so this single check skips itself
    # while every other check still runs. Any other caller (CI, local
    # `bin/check.py`, pre-commit) leaves the env var unset and gets
    # the full check.
    if os.environ.get("FIFTY_SKIP_UNPUSHED_CHECK") == "1":
        r.skip(
            "FIFTY_SKIP_UNPUSHED_CHECK=1 (set by .githooks/pre-commit + pre-push to avoid in-flight-commit deadlock)"
        )
        return r
    if not shutil.which("git"):
        r.skip("git not available on PATH")
        return r
    try:
        # Use the monorepo root; the per-theme ROOT is a subdirectory so
        # `git -C` would also work, but MONOREPO_ROOT is the canonical anchor.
        cwd = str(MONOREPO_ROOT)
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            r.skip("not inside a git working tree")
            return r

        upstream = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if upstream.returncode != 0:
            r.skip("current branch has no upstream tracking ref")
            return r

        ahead = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ahead.returncode != 0:
            r.skip(f"git rev-list failed: {ahead.stderr.strip()}")
            return r

        n = int(ahead.stdout.strip() or "0")
        if n > 0:
            unpushed = subprocess.run(
                ["git", "log", "--oneline", "@{u}..HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            r.fail(
                f"{n} unpushed commit{'s' if n != 1 else ''} on "
                f"{upstream.stdout.strip()}: run `git push` so the live "
                f"Playground demo (which loads theme/ from raw.githubusercontent.com) "
                f"actually sees them."
            )
            for line in unpushed.stdout.strip().splitlines():
                r.fail(f"  {line}")
    except (subprocess.TimeoutExpired, ValueError) as exc:
        r.skip(f"git probe failed: {exc}")
    return r


def _baseline_decay(max_age_days: int = 30) -> int:
    """Scan `tests/check-baseline-failures.json` and print which
    entries are decayed -- older than `max_age_days` (default 30) or
    missing the `justification` / `owner` fields. Exits 0 if nothing
    is decayed, 1 if any entry needs attention.

    Wired from `.github/workflows/nightly-snap-sweep.yml` (Tier 2.4
    of the pre-100-themes hardening plan) so the baseline doesn't
    quietly accrete permanent debt: any entry that's been on main
    for more than 30 days without a justification opens a visible
    workflow failure, which the owner is expected to resolve by
    either fixing the underlying check or writing a real
    justification.

    We intentionally DO NOT auto-delete decayed entries. The allow
    list is a safety net for feature branches, not a to-do list the
    bot can prune. Humans pay the owner-notification cost on purpose.
    """
    from datetime import datetime, timezone

    if not BASELINE_FAILURES_PATH.exists():
        print(f"{GREEN}ok{RESET}: {BASELINE_FAILURES_PATH.name} not present; nothing to decay")
        return 0
    try:
        data = json.loads(BASELINE_FAILURES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"{RED}error{RESET}: cannot parse {BASELINE_FAILURES_PATH.name}: {exc}")
        return 1

    entries = data.get("failures", []) or []
    if not entries:
        print(f"{GREEN}ok{RESET}: no baseline failures recorded")
        return 0

    today = datetime.now(timezone.utc).date()  # noqa: UP017

    stale: list[tuple[dict[str, str], int]] = []
    missing_justification: list[dict[str, str]] = []
    missing_owner: list[dict[str, str]] = []
    malformed: list[dict[str, str]] = []

    for entry in entries:
        added_at = entry.get("added_at", "")
        justification = (entry.get("justification") or "").strip()
        owner = (entry.get("owner") or "").strip()

        if not added_at:
            malformed.append(entry)
        else:
            try:
                added_date = datetime.strptime(added_at, "%Y-%m-%d").date()
                age = (today - added_date).days
                if age > max_age_days:
                    stale.append((entry, age))
            except ValueError:
                malformed.append(entry)

        if not justification:
            missing_justification.append(entry)
        if not owner:
            missing_owner.append(entry)

    def _fmt(entry: dict[str, str]) -> str:
        return f"{entry.get('theme', '?')} / {entry.get('check', '?')}"

    total_issues = len(stale) + len(missing_justification) + len(missing_owner) + len(malformed)
    if total_issues == 0:
        print(
            f"{GREEN}ok{RESET}: {len(entries)} baseline entries, all within "
            f"{max_age_days} days and fully documented"
        )
        return 0

    print(
        f"{YELLOW}baseline-decay{RESET}: {total_issues} issue"
        f"{'s' if total_issues != 1 else ''} across {len(entries)} entries"
    )
    if stale:
        print(f"\n{RED}stale ({len(stale)}, >{max_age_days}d old):{RESET}")
        for entry, age in sorted(stale, key=lambda pair: -pair[1]):
            print(f"  [{age}d] {_fmt(entry)}  (added_at={entry.get('added_at', '?')})")
    if missing_justification:
        print(f"\n{RED}missing justification ({len(missing_justification)}):{RESET}")
        for entry in missing_justification:
            print(f"  {_fmt(entry)}")
    if missing_owner:
        print(f"\n{YELLOW}missing owner ({len(missing_owner)}):{RESET}")
        for entry in missing_owner:
            print(f"  {_fmt(entry)}")
    if malformed:
        print(f"\n{RED}malformed or missing added_at ({len(malformed)}):{RESET}")
        for entry in malformed:
            print(f"  {_fmt(entry)}  (added_at={entry.get('added_at', '<missing>')!r})")
    print(
        "\nFix: edit tests/check-baseline-failures.json by hand -- add a real "
        "justification, or fix the underlying check and re-run "
        "`python3 bin/check.py --save-baseline-failures` from origin/main to "
        "drop the entry."
    )
    return 1


def _git_committer_email() -> str:
    """Return `git log -1 --format=%ae` or '' on failure.

    Used to auto-populate the `owner` field on newly-discovered baseline
    entries so operators don't have to hand-type an email address when
    first writing the file. When the tree is not a git checkout (or the
    bot doesn't have an identity, like in ephemeral CI runners) we fall
    back to '' and let `--baseline-decay` warn about the empty field
    separately.
    """
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ae"],
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _save_baseline_failures(offline: bool) -> int:
    """Rebuild `tests/check-baseline-failures.json` from the CURRENT
    working tree. Runs every check silently across every theme in the
    monorepo (via iter_themes), collects the names of every failure,
    and writes them back as `(theme, check)` pairs alongside the
    origin/main SHA the tree matches (if any).

    Each entry carries three Tier 2.4 fields (pre-100-themes hardening):

      * `added_at`      ISO date (YYYY-MM-DD) the pair was first seen.
                        Preserved across regenerations so the decay
                        rule (>30 days => nightly baseline-stale issue)
                        isn't reset by a routine refresh.
      * `owner`         Populated from `git log -1 --format=%ae` when
                        the entry is first added. Re-runs keep the
                        existing owner; a missing owner stays empty
                        and is flagged by --baseline-decay.
      * `justification` Short free-text explanation. Starts empty on
                        first write; operators fill it in by hand
                        when the entry lands. --baseline-decay flags
                        empty justifications just like stale ones.

    Callers are expected to run this from a tree that REPRESENTS the
    canonical baseline -- either a clean checkout of `origin/main`, or
    a detached `git worktree` pointing there. Running it from an
    arbitrary feature branch will record THAT branch's failure set,
    which is almost never what you want -- but the file's
    `recorded_sha` + `recorded_against` fields make it obvious after
    the fact, and a human re-regeneration from main is cheap.

    Returns 0 on successful write, 1 on any unexpected error.
    """
    from datetime import datetime, timezone

    global ROOT

    # Preserve `added_at` / `owner` / `justification` across
    # regenerations: a re-run that re-discovers an existing
    # (theme, check) pair must NOT reset its first-seen date or the
    # operator will never see the decay warning fire.
    existing_by_key: dict[tuple[str, str], dict[str, str]] = {}
    if BASELINE_FAILURES_PATH.exists():
        try:
            prior = json.loads(BASELINE_FAILURES_PATH.read_text(encoding="utf-8"))
            for entry in prior.get("failures", []) or []:
                theme = entry.get("theme")
                check = entry.get("check")
                if isinstance(theme, str) and isinstance(check, str):
                    existing_by_key[(theme, check)] = entry
        except (json.JSONDecodeError, OSError):
            existing_by_key = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # noqa: UP017
    owner = _git_committer_email()

    pairs: list[dict[str, str]] = []
    prev_allow = os.environ.pop("FIFTY_ALLOW_BASELINE_FAILURES", None)
    try:
        for theme in iter_themes():
            ROOT = theme
            # Baseline regeneration must cover every phase (structural
            # AND content) because the allowlist is authoritative for
            # the full `--phase all` gate. Using `_evaluate_checks` with
            # PHASE_ALL also keeps the (name, thunk) plumbing honest.
            results = _evaluate_checks(_build_results(offline=offline), PHASE_ALL)
            for r in results:
                if not r.passed and not r.skipped:
                    key = (theme.name, r.name)
                    prior_entry = existing_by_key.get(key)
                    if prior_entry is not None:
                        # Preserve every prior metadata field verbatim;
                        # only `theme` and `check` are authoritative
                        # from this run.
                        entry = dict(prior_entry)
                        entry["theme"] = theme.name
                        entry["check"] = r.name
                        entry.setdefault("added_at", today)
                        entry.setdefault("owner", owner)
                        entry.setdefault("justification", "")
                    else:
                        entry = {
                            "theme": theme.name,
                            "check": r.name,
                            "added_at": today,
                            "owner": owner,
                            "justification": "",
                        }
                    pairs.append(entry)
    finally:
        if prev_allow is not None:
            os.environ["FIFTY_ALLOW_BASELINE_FAILURES"] = prev_allow

    # Try to capture the SHA this tree corresponds to. If origin/main
    # resolves, assume the caller ran the regen against main (that's the
    # documented workflow); fall back to the HEAD SHA so the record is
    # at least truthful.
    sha = ""
    ref = "origin/main"
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=str(MONOREPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if not sha:
            raise RuntimeError("origin/main unresolved")
    except (subprocess.TimeoutExpired, RuntimeError):
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(MONOREPO_ROOT),
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            ref = "HEAD"
        except subprocess.TimeoutExpired:
            sha = "UNKNOWN"

    payload = {
        "_doc": [
            "Snapshot of which (theme, check-title) pairs are already failing on",
            "origin/main. When FIFTY_ALLOW_BASELINE_FAILURES=1 (which pre-commit,",
            "pre-push, and CI's theme-gate set automatically), bin/check.py prints",
            "these as WARN-BASELINE in yellow and does NOT count them toward its",
            "exit code -- only NEW failures, introduced by the current branch,",
            "can block a commit/push/PR.",
            "",
            "Each entry carries added_at (YYYY-MM-DD, preserved across refreshes),",
            "owner (git committer email), and justification (operator-supplied).",
            "Entries older than 30 days or missing a justification are surfaced",
            "by `python3 bin/check.py --baseline-decay` (also run nightly via",
            ".github/workflows/nightly-snap-sweep.yml) so the baseline doesn't",
            "quietly accrete permanent debt.",
            "",
            "Regenerate: `python3 bin/check.py --save-baseline-failures`, ideally",
            "from a detached `git worktree` at origin/main so the snapshot",
            "reflects main's reality and not the feature branch's.",
        ],
        "recorded_against": ref,
        "recorded_sha": sha,
        "recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017  (datetime.UTC is Py 3.11+; pyproject's `requires-python` is >=3.9)
        "failures": sorted(pairs, key=lambda d: (d["theme"], d["check"])),
    }
    BASELINE_FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FAILURES_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"{GREEN}wrote{RESET} {BASELINE_FAILURES_PATH.relative_to(MONOREPO_ROOT)} "
        f"({len(pairs)} failure{'s' if len(pairs) != 1 else ''} recorded against "
        f"{ref} @ {sha[:10]})"
    )
    return 0


def iter_files(suffixes: tuple[str, ...]):
    skip_dirs = {".git", "node_modules", "vendor", "__pycache__"}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in suffixes:
            yield path


def _build_results(offline: bool) -> list[tuple[str, Callable[[], Result]]]:
    """Return every check as a `(function_name, thunk)` pair.

    The function-name string is the authoritative identity used by
    `_CONTENT_FIT_CHECK_NAMES` and the phase filter; `Result.name`
    (the human-readable title each check sets on its own Result) is
    keyed separately by `tests/check-baseline-failures.json`, so the
    two name systems stay decoupled on purpose.

    The thunk is the zero-arg closure that runs the check. Almost
    every check already takes no args; the one exception is
    `check_block_names(offline=offline)`, which we bind to the current
    `offline` flag with a lambda.

    Callers must set the module-level `ROOT` to the target theme
    BEFORE calling this, since many checks read ROOT at invocation
    time.
    """
    return [
        ("check_json_validity", check_json_validity),
        ("check_design_intent_present", check_design_intent_present),
        ("check_design_intent_brand_match", check_design_intent_brand_match),
        ("check_theme_readiness", check_theme_readiness),
        ("check_php_syntax", check_php_syntax),
        ("check_block_names", lambda: check_block_names(offline=offline)),
        ("check_index_in_sync", check_index_in_sync),
        ("check_no_important", check_no_important),
        ("check_no_stray_css", check_no_stray_css),
        ("check_block_prefixes", check_block_prefixes),
        ("check_no_wc_tabs_block", check_no_wc_tabs_block),
        ("check_no_ai_fingerprints", check_no_ai_fingerprints),
        ("check_no_placeholder_microcopy", check_no_placeholder_microcopy),
        ("check_no_hardcoded_colors", check_no_hardcoded_colors),
        ("check_no_hex_in_theme_json", check_no_hex_in_theme_json),
        ("check_no_remote_fonts", check_no_remote_fonts),
        ("check_wc_grid_integration", check_wc_grid_integration),
        ("check_wc_overrides_styled", check_wc_overrides_styled),
        ("check_no_hardcoded_dimensions", check_no_hardcoded_dimensions),
        ("check_block_attrs_use_tokens", check_block_attrs_use_tokens),
        ("check_block_markup_anti_patterns", check_block_markup_anti_patterns),
        ("check_blocks_validator", check_blocks_validator),
        (
            "check_bordered_group_text_has_explicit_color",
            check_bordered_group_text_has_explicit_color,
        ),
        ("check_block_text_contrast", check_block_text_contrast),
        (
            "check_post_title_link_color_not_accent_on_low_contrast_base",
            check_post_title_link_color_not_accent_on_low_contrast_base,
        ),
        ("check_no_fake_forms", check_no_fake_forms),
        ("check_modern_blocks_only", check_modern_blocks_only),
        ("check_swatch_js_targets_real_select", check_swatch_js_targets_real_select),
        ("check_no_empty_cover_blocks", check_no_empty_cover_blocks),
        ("check_product_terms_query_show_nested", check_product_terms_query_show_nested),
        ("check_no_large_placeholder_groups", check_no_large_placeholder_groups),
        ("check_product_image_visual_diversity", check_product_image_visual_diversity),
        ("check_product_images_json_complete", check_product_images_json_complete),
        ("check_category_images_json_complete", check_category_images_json_complete),
        ("check_no_duplicate_templates", check_no_duplicate_templates),
        ("check_no_duplicate_stock_indicator", check_no_duplicate_stock_indicator),
        ("check_archive_sort_dropdown_styled", check_archive_sort_dropdown_styled),
        ("check_no_squeezed_wc_sidebars", check_no_squeezed_wc_sidebars),
        ("check_wc_card_surfaces_padded", check_wc_card_surfaces_padded),
        ("check_wc_totals_blocks_padded", check_wc_totals_blocks_padded),
        ("check_wc_notices_styled", check_wc_notices_styled),
        ("check_navigation_overlay_opaque", check_navigation_overlay_opaque),
        ("check_outline_button_paired_with_primary", check_outline_button_paired_with_primary),
        ("check_wc_card_padding_not_zeroed", check_wc_card_padding_not_zeroed),
        ("check_hover_state_legibility", check_hover_state_legibility),
        ("check_palette_polarity_coherent", check_palette_polarity_coherent),
        ("check_background_clip_text_legibility", check_background_clip_text_legibility),
        ("check_nav_item_pill_scoped_to_horizontal", check_nav_item_pill_scoped_to_horizontal),
        ("check_account_grid_scoped_to_sidebar", check_account_grid_scoped_to_sidebar),
        ("check_disabled_atc_button_styled_per_theme", check_disabled_atc_button_styled_per_theme),
        ("check_distinctive_chrome", check_distinctive_chrome),
        ("check_cart_checkout_pages_are_wide", check_cart_checkout_pages_are_wide),
        ("check_prose_layout_token_purged", check_prose_layout_token_purged),
        ("check_wc_chrome_sentinel_present", check_wc_chrome_sentinel_present),
        ("check_blueprint_landing_page", check_blueprint_landing_page),
        ("check_front_page_unique_layout", check_front_page_unique_layout),
        ("check_pdp_has_image", check_pdp_has_image),
        (
            "check_no_woocommerce_placeholder_in_findings",
            check_no_woocommerce_placeholder_in_findings,
        ),
        (
            "check_product_reviews_uses_inner_blocks_not_legacy_render",
            check_product_reviews_uses_inner_blocks_not_legacy_render,
        ),
        (
            "check_no_unstyled_review_rating_in_findings",
            check_no_unstyled_review_rating_in_findings,
        ),
        ("check_pattern_microcopy_distinct", check_pattern_microcopy_distinct),
        (
            "check_all_rendered_text_distinct_across_themes",
            check_all_rendered_text_distinct_across_themes,
        ),
        ("check_no_default_wc_strings", check_no_default_wc_strings),
        ("check_no_brand_filters_in_playground", check_no_brand_filters_in_playground),
        ("check_theme_ships_cart_page_pattern", check_theme_ships_cart_page_pattern),
        ("check_wc_microcopy_distinct_across_themes", check_wc_microcopy_distinct_across_themes),
        ("check_playground_content_seeded", check_playground_content_seeded),
        ("check_no_placeholder_product_images", check_no_placeholder_product_images),
        ("check_product_images_unique_across_themes", check_product_images_unique_across_themes),
        ("check_hero_images_unique_across_themes", check_hero_images_unique_across_themes),
        ("check_theme_screenshots_distinct", check_theme_screenshots_distinct),
        ("check_wc_specificity_winnable", check_wc_specificity_winnable),
        ("check_no_serious_axe_in_recent_snaps", check_no_serious_axe_in_recent_snaps),
        ("check_visual_baseline_present", check_visual_baseline_present),
        ("check_allowlist_entries_resolve", check_allowlist_entries_resolve),
        ("check_evidence_freshness", check_evidence_freshness),
        ("check_view_transitions_wired", check_view_transitions_wired),
        ("check_concept_similarity", check_concept_similarity),
        ("check_no_unpushed_commits", check_no_unpushed_commits),
    ]


def run_checks_for(
    theme_root: Path,
    offline: bool,
    phase: str = PHASE_ALL,
    only: list[str] | None = None,
) -> int:
    global ROOT
    ROOT = theme_root
    phase_suffix = "" if phase == PHASE_ALL else f", phase={phase}"
    only_suffix = "" if not only else f", only={', '.join(only)}"
    print(
        f"Running checks for {theme_root.name} "
        f"({'offline' if offline else 'online'}{phase_suffix}{only_suffix})...\n"
    )

    results = _evaluate_checks(_build_results(offline), phase, only)

    # Demote known pre-existing failures (see `_demote_baseline_failures`)
    # BEFORE rendering so the labels in `render()` reflect the demotion.
    # No-op when the env var is unset or the JSON is empty. Count goes
    # into the summary line below via `demoted_failed`, not a return
    # value -- we need the per-Result state anyway to split real vs
    # demoted failures, so pulling the number back out of the list is
    # cheaper than plumbing an extra int through.
    _demote_baseline_failures(results, theme_root.name)

    for r in results:
        print(r.render())

    # Split failures into "real" (new, this-branch) vs "demoted" (already
    # failing on origin/main, waved through by the baseline allowlist).
    # Only real failures count toward exit 1.
    real_failed = [r for r in results if not r.passed and not r.skipped and not r.demoted]
    demoted_failed = [r for r in results if not r.passed and not r.skipped and r.demoted]
    skipped = [r for r in results if r.skipped]

    print()
    if real_failed:
        msg = (
            f"{RED}FAILED{RESET}: {len(real_failed)} of {len(results)} checks "
            f"failed for {theme_root.name}."
        )
        if demoted_failed:
            msg += (
                f" (+{len(demoted_failed)} pre-existing failure"
                f"{'s' if len(demoted_failed) != 1 else ''} demoted via "
                f"tests/check-baseline-failures.json)"
            )
        print(msg)
        return 1
    if demoted_failed:
        print(
            f"{YELLOW}OK (with baseline warnings){RESET}: all new checks pass "
            f"for {theme_root.name}; {len(demoted_failed)} pre-existing "
            f"failure{'s' if len(demoted_failed) != 1 else ''} on origin/main "
            f"demoted to WARN-BASELINE (see tests/check-baseline-failures.json)."
        )
        return 0
    if skipped:
        print(
            f"{GREEN}OK{RESET}: all checks passed for {theme_root.name} ({len(skipped)} skipped)."
        )
    else:
        print(f"{GREEN}OK{RESET}: all {len(results)} checks passed for {theme_root.name}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every Fifty project check.")
    parser.add_argument(
        "theme",
        nargs="?",
        default=None,
        help="Theme directory name (e.g. 'obel'). Defaults to cwd if it contains theme.json.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run against every theme in the monorepo.",
    )
    parser.add_argument(
        "--changed",
        action="store_true",
        help=(
            "Run against themes touched by git diff only. Rendering-framework "
            "changes intentionally widen to all themes; docs/tooling-only "
            "changes run no theme checks."
        ),
    )
    parser.add_argument(
        "--changed-base",
        default=None,
        help="Git base ref for --changed (compared as <base>...HEAD, e.g. origin/main).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="With --changed, inspect only staged changes (pre-commit hook mode).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip checks that require network (block-name validation against Gutenberg).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Alias for --offline.",
    )
    parser.add_argument(
        "--phase",
        choices=list(_PHASES),
        default=PHASE_ALL,
        help=(
            "Which checks to run. `structural` (default for `design.py "
            "build`) skips the 10 content-fit checks that only pass once "
            "per-theme photos / microcopy / front-page have been regen'd. "
            "`content` (default for `design.py dress`) runs ONLY those "
            "10. `all` (default here, keeps pre-split behaviour) runs "
            "every check. See `_CONTENT_FIT_CHECK_NAMES`."
        ),
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help=(
            "Run only the named check(s), by function name, name without "
            "`check_`, or alias (for example: placeholder-images, "
            "playground-content, product-images-json). Intended for fast "
            "triage; full gates should omit this flag."
        ),
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help=(
            "After all static checks pass, also run the visual-snapshot "
            "framework (`bin/snap.py check`) which boots Playground for "
            "the affected themes, captures Playwright screenshots across "
            "snap_config.ROUTES x VIEWPORTS, diffs against the "
            "committed baselines under `tests/visual-baseline/`, and "
            "applies the tiered heuristic gate (`bin/snap.py report "
            "--strict`). Default scope is `--visual-scope=changed` "
            "(only re-shoots themes touched by git diff); pass "
            "`--visual-scope=all` for the full sweep before a release."
        ),
    )
    parser.add_argument(
        "--visual-scope",
        choices=["changed", "all", "quick"],
        default="changed",
        help=(
            "How wide a visual sweep to run when --visual is passed. "
            "'changed' (default) -> only themes touched by uncommitted "
            "+ <visual-base>..HEAD git diff (framework changes fall back "
            "to all). 'all' -> every theme, every route, every viewport "
            "(2-5 min). 'quick' -> the snap_config.QUICK_* subset for a "
            "single theme; falls back to obel if no theme is selected."
        ),
    )
    parser.add_argument(
        "--visual-base",
        default=None,
        help=(
            "Git base ref for --visual-scope=changed (e.g. main, HEAD~1). "
            "Default: only consider uncommitted changes."
        ),
    )
    parser.add_argument(
        "--visual-threshold",
        type=float,
        default=0.5,
        help=(
            "Max %% changed pixels per (route, viewport) cell before the "
            "visual diff fails. Default 0.5%% (~one button-sized region). "
            "Only used when --visual is passed."
        ),
    )
    parser.add_argument(
        "--save-baseline-failures",
        action="store_true",
        help=(
            "Run every check across every theme and write the resulting "
            "set of failing (theme, check-title) pairs to "
            "tests/check-baseline-failures.json. That file is consulted "
            "by FIFTY_ALLOW_BASELINE_FAILURES=1 (set by the git hooks + "
            "CI theme-gate) to demote pre-existing failures on main to "
            "WARN-BASELINE so feature branches don't get blocked by "
            "unrelated debt. Regenerate this file whenever origin/main "
            "moves in a way that changes the failure set -- ideally "
            "from a detached worktree pointing at origin/main so the "
            "baseline reflects main's reality, not your branch's."
        ),
    )
    parser.add_argument(
        "--baseline-decay",
        action="store_true",
        help=(
            "Scan tests/check-baseline-failures.json and exit 1 if any "
            "entry is older than --baseline-decay-days (default 30) or "
            "is missing a justification / owner. Wired from "
            ".github/workflows/nightly-snap-sweep.yml (Tier 2.4 of the "
            "pre-100-themes hardening plan) so the allow list doesn't "
            "quietly accrete permanent debt. Intentionally does NOT "
            "auto-delete decayed entries -- humans pay the owner-"
            "notification cost on purpose."
        ),
    )
    parser.add_argument(
        "--baseline-decay-days",
        type=int,
        default=30,
        help=(
            "Max age (in days) for a baseline entry before "
            "--baseline-decay flags it as stale. Default 30."
        ),
    )
    args = parser.parse_args()

    offline = args.offline or args.quick

    if args.save_baseline_failures:
        return _save_baseline_failures(offline=offline)

    if args.baseline_decay:
        return _baseline_decay(max_age_days=args.baseline_decay_days)

    if args.all and args.changed:
        parser.error("--all and --changed are mutually exclusive")

    if args.changed:
        scope = resolve_changed_scope(base=args.changed_base, staged=args.staged)
        if scope.all_themes_required:
            print(
                "Changed-scope theme gate: framework change detected "
                f"({scope.reason}); skipping per-theme checks. Run "
                "`bin/check.py --all` or the fleet-health workflow when "
                "explicit all-theme validation is desired."
            )
            static_rc = 0
        elif not scope.themes:
            print(f"Changed-scope theme gate: no themes to check ({scope.reason}).")
            static_rc = 0
        else:
            print(
                "Changed-scope theme gate: "
                f"{'all themes' if scope.all_themes_required else ', '.join(scope.themes)} "
                f"({scope.reason})."
            )
            exit_codes = []
            for slug in scope.themes:
                theme_root = resolve_theme_root(slug)
                print(f"\n{'=' * 60}")
                exit_codes.append(run_checks_for(theme_root, offline, args.phase, args.only))
            static_rc = 1 if any(exit_codes) else 0
    elif args.all:
        exit_codes = []
        for theme in iter_themes():
            print(f"\n{'=' * 60}")
            exit_codes.append(run_checks_for(theme, offline, args.phase, args.only))
        static_rc = 1 if any(exit_codes) else 0
    else:
        theme_root = resolve_theme_root(args.theme)
        static_rc = run_checks_for(theme_root, offline, args.phase, args.only)

    # Visual diff runs LAST and only if static checks already passed.
    # Bailing out early on a static failure avoids spending 2-5 minutes
    # booting Playgrounds for code that won't compile.
    if static_rc != 0 or not args.visual:
        return static_rc

    # Late-import so contributors who never run --visual don't pay for
    # importing Playwright/Pillow on every check.
    print(f"\n{'=' * 60}")
    snap_path = str(Path(__file__).resolve().parent / "snap.py")
    if args.visual_scope == "quick":
        # `quick` shoots the snap_config.QUICK_* subset for one theme
        # (default obel) -- the absolute fastest way to verify a CSS
        # tweak didn't blow up the inner loop. Falls through to a
        # plain `shoot --quick` (no diff/report); use `--visual-scope
        # =changed` for the gated path.
        target_theme = args.theme if not args.all else "obel"
        print(f"Running quick visual smoke (`bin/snap.py shoot {target_theme} --quick`)...\n")
        snap_cmd = [sys.executable, snap_path, "shoot", target_theme, "--quick"]
    else:
        print(
            f"Running visual snapshot diff (`bin/snap.py check --scope={args.visual_scope}`)...\n"
        )
        snap_cmd = [
            sys.executable,
            snap_path,
            "check",
            f"--threshold={args.visual_threshold}",
        ]
        if args.visual_scope == "changed":
            snap_cmd.append("--changed")
            if args.visual_base:
                snap_cmd.extend(["--changed-base", args.visual_base])
    snap_rc = subprocess.call(snap_cmd, cwd=str(Path(__file__).resolve().parent.parent))
    return snap_rc


if __name__ == "__main__":
    sys.exit(main())
