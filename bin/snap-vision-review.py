#!/usr/bin/env python3
"""Vision-based design reviewer for snap.py screenshots.

What this does
--------------
Walks `tmp/snaps/<theme>/<viewport>/<slug>.png`, sends each PNG to the
Anthropic vision model with the theme's `design-intent.md` and a generic
visual rubric, parses the structured-JSON response, and appends `vision:*`
findings to `<slug>.findings.json` so they flow into
`tmp/dispatch-state.json` alongside DOM heuristics + axe-core findings.

The agent reads `dispatch-state.json` via `.cursor/rules/dispatch-state.mdc`
and now (via `.cursor/rules/vision-findings.mdc` shipped in PR 3) is
required to open the PNG + the annotated `<slug>.review.png` before
attempting a fix.

Cost discipline
---------------
Every PNG is fingerprinted (PNG bytes + intent.md + prompt version + model
id). On rerun, unchanged PNGs are skipped. Combined with smart-snap-pipeline
PR 3 (route-level reshoot avoidance), a typical edit-iteration touches
fewer than 10 PNGs and costs < $0.30.

A pre-filter rejects "obviously fine" images (very high whitespace ratio
plus low color-entropy) before they reach the API. This is a cheap
~10ms-per-PNG check that catches near-blank intermediate states without
spending a token.

Daily spend cap (`FIFTY_VISION_DAILY_BUDGET`, default $20) is enforced
inside `bin/_vision_lib.py`; this script raises BudgetExceededError up
front if the cap would be hit.

Operating modes
---------------
    # Normal: review every cached PNG for a theme
    python3 bin/snap-vision-review.py selvedge

    # Subset:
    python3 bin/snap-vision-review.py selvedge --routes home cart-filled

    # Force a fresh review (ignore cache):
    python3 bin/snap-vision-review.py selvedge --no-cache

    # Dry-run: print the prompt that WOULD be sent, write empty findings,
    # do not call the API. Useful for prompt iteration without burning $.
    python3 bin/snap-vision-review.py selvedge --dry-run

    # Validate against the labelled fixture set:
    python3 bin/snap-vision-review.py --validate \
        tests/fixtures/visual-regressions

Outputs (per PNG)
-----------------
    <slug>.findings.json          mutated -- vision:* findings appended
    <slug>.review.png             new -- annotated PNG (bbox + severity)
    <slug>.vision-fingerprint     new -- cache stamp (sha256 of inputs)

Exit codes
----------
    0  success (or --validate met thresholds)
    1  --validate did not meet precision/recall thresholds
    2  budget exceeded / API key missing / no theme found
    3  other unhandled error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Pillow is imported lazily inside the two functions that touch pixels
# (`_passes_prefilter`, `_annotate_review_png`) so that `--help`, the
# CLI smoke test, and the dry-run usage-error tests can load this
# module without Pillow installed. The reviewer's actual runtime path
# still requires Pillow; CI installs it via requirements-dev.txt.

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vision_lib import (
    DEFAULT_DAILY_BUDGET_USD,
    DEFAULT_LEDGER_PATH,
    DEFAULT_MODEL,
    PROMPT_VERSION,
    VISION_PHASE_ALL,
    VISION_PHASES,
    ApiCallFailedError,
    ApiKeyMissingError,
    BudgetExceededError,
    VisionError,
    VisionResponse,
    fingerprint_inputs,
    review_image,
    today_spend_usd,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPS_DIR = REPO_ROOT / "tmp" / "snaps"

# Severity-coded colors for bbox annotation in the review PNG.
SEVERITY_COLORS: dict[str, tuple[int, int, int]] = {
    "error": (220, 30, 40),
    "warn": (240, 170, 30),
    "info": (60, 130, 200),
}

# Pre-filter thresholds. An image with > WHITESPACE_FRAC pixels close to
# pure white AND fewer than UNIQUE_COLORS_FLOOR unique colors is treated as
# "obviously empty" and skipped. Tuned against the fixture set + a sample
# of real obel snaps -- captures intermediate near-blank states without
# rejecting deliberately whitespace-heavy designs (lysholm, deliberate-
# whitespace fixture).
WHITESPACE_FRAC_FLOOR = 0.97
UNIQUE_COLORS_FLOOR = 60


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class ReviewItem:
    """One unit of review work: a single PNG belonging to a theme/route/vp.

    Plain class (not @dataclass) because the smoke-test
    `tests/tools/test_bin_scripts_smoke.py::test_script_imports` loads
    every `bin/*.py` via `spec_from_file_location` without registering
    the module in `sys.modules` first. Python 3.9's dataclasses
    internals call `sys.modules.get(cls.__module__).__dict__` during
    field-type resolution and crash with AttributeError when the
    module isn't registered yet. Plain classes don't trigger that path.
    """

    __slots__ = ("png_path", "route", "theme", "viewport")

    def __init__(self, theme, route, viewport, png_path):
        self.theme = theme
        self.route = route
        self.viewport = viewport
        self.png_path = png_path

    @property
    def findings_path(self):
        return self.png_path.with_suffix("").with_suffix(".findings.json")

    @property
    def review_png_path(self):
        return self.png_path.with_name(self.png_path.stem + ".review.png")

    @property
    def fingerprint_path(self):
        return self.png_path.with_name(self.png_path.stem + ".vision-fingerprint")


class ReviewResult:
    """Outcome of reviewing one ReviewItem. Plain class for the same
    reason ReviewItem is — see its docstring."""

    __slots__ = ("cost_usd", "elapsed_s", "findings", "item", "note", "status")

    def __init__(self, item, status, findings=None, cost_usd=0.0, elapsed_s=0.0, note=""):
        self.item = item
        self.status = status
        self.findings = findings if findings is not None else []
        self.cost_usd = cost_usd
        self.elapsed_s = elapsed_s
        self.note = note


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_purpose(theme_root: Path, route: str) -> str:
    """Best-effort one-line description of what `route` is for. We use
    `bin/snap_config.py`'s ROUTES table when importable; otherwise empty."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from snap_config import ROUTES

        for r in ROUTES:
            if r.slug == route:
                return r.description
    except Exception:
        return ""
    return ""


def _intent_md(theme_root: Path) -> str | None:
    """Return the theme's design-intent.md contents, or None if missing."""
    p = theme_root / "design-intent.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def _mockup_path(theme: str) -> Path | None:
    for candidate in (
        REPO_ROOT / "mockups" / f"mockup-{theme}.png",
        REPO_ROOT / "docs" / "mockups" / f"{theme}.png",
    ):
        if candidate.is_file():
            return candidate
    return None


def _discover_items(
    theme: str,
    *,
    routes: list[str] | None,
    viewports: list[str] | None,
) -> list[ReviewItem]:
    """Walk `tmp/snaps/<theme>/<vp>/<slug>.png` and yield ReviewItems."""
    base = SNAPS_DIR / theme
    if not base.is_dir():
        return []
    items: list[ReviewItem] = []
    for vp_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        if viewports and vp_dir.name not in viewports:
            continue
        for png in sorted(vp_dir.glob("*.png")):
            # skip the annotated review PNGs themselves to avoid recursion
            if png.stem.endswith(".review"):
                continue
            slug = png.stem
            if routes and slug not in routes:
                continue
            items.append(
                ReviewItem(
                    theme=theme,
                    route=slug,
                    viewport=vp_dir.name,
                    png_path=png,
                )
            )
    return items


def _passes_prefilter(png_bytes: bytes) -> tuple[bool, str]:
    """Return (proceed, reason). `proceed=False` means skip the API call."""
    from PIL import Image

    try:
        with Image.open(_BytesIO(png_bytes)) as img:
            img = img.convert("RGB")
            # Downscale for speed; whitespace ratio is robust to this.
            img.thumbnail((400, 400))
            pixels = list(img.getdata())
            if not pixels:
                return False, "empty image"
            # Whitespace = pixels >= (240,240,240) on each channel
            white = sum(1 for r, g, b in pixels if r >= 240 and g >= 240 and b >= 240)
            white_frac = white / len(pixels)
            unique = len(set(pixels))
            if white_frac >= WHITESPACE_FRAC_FLOOR and unique < UNIQUE_COLORS_FLOOR:
                return False, (
                    f"prefilter: {white_frac:.0%} whitespace, "
                    f"{unique} unique colors -- nothing to review"
                )
            return True, ""
    except Exception as exc:
        return True, f"prefilter error (proceeding anyway): {exc!r}"


def _BytesIO(b: bytes):
    """Local alias to avoid a top-level `import io` for one use."""
    import io

    return io.BytesIO(b)


def _annotate_review_png(item: ReviewItem, findings: list[dict]) -> None:
    """Write a copy of the screenshot with severity-colored bboxes drawn
    over each finding's bounding box. Findings without a bbox just appear
    as a legend entry in the corner.

    Renders even when there are zero findings: a `<slug>.review.png` with
    a "No findings" stamp tells the agent the route was reviewed clean
    rather than untouched.
    """
    from PIL import Image, ImageDraw

    try:
        with Image.open(item.png_path) as src:
            canvas = src.convert("RGB").copy()
    except Exception:
        return
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    for f in findings:
        color = SEVERITY_COLORS.get(f.get("severity", "warn"), SEVERITY_COLORS["warn"])
        bbox = f.get("bbox") or {}
        if isinstance(bbox, dict) and bbox.get("w") and bbox.get("h"):
            x1, y1 = int(bbox["x"]), int(bbox["y"])
            x2, y2 = x1 + int(bbox["w"]), y1 + int(bbox["h"])
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            for off in range(4):  # 4-pixel-thick border
                draw.rectangle((x1 - off, y1 - off, x2 + off, y2 + off), outline=color)
            label = f.get("kind", "vision:?").removeprefix("vision:")
            draw.rectangle((x1, max(0, y1 - 20), x1 + len(label) * 7 + 8, y1), fill=color)
            draw.text((x1 + 4, max(0, y1 - 18)), label, fill=(255, 255, 255))
    legend_y = 10
    if not findings:
        draw.rectangle((10, 10, 200, 36), fill=(40, 160, 80))
        draw.text((18, 16), "vision: no findings", fill=(255, 255, 255))
    else:
        draw.rectangle((10, legend_y, 280, legend_y + 18 + 18 * len(findings)), fill=(20, 20, 20))
        draw.text((18, legend_y + 2), f"vision findings: {len(findings)}", fill=(255, 255, 255))
        for i, f in enumerate(findings):
            color = SEVERITY_COLORS.get(f.get("severity", "warn"), SEVERITY_COLORS["warn"])
            label = f.get("kind", "?").removeprefix("vision:")
            draw.rectangle((18, legend_y + 22 + i * 18, 28, legend_y + 32 + i * 18), fill=color)
            draw.text((34, legend_y + 22 + i * 18), label, fill=(220, 220, 220))
    canvas.save(item.review_png_path, format="PNG", optimize=True)


def _merge_findings(findings_path: Path, vision_findings: list[dict]) -> None:
    """Merge `vision_findings` into `<route>.findings.json` non-destructively.

    Strategy:
      1. Drop any pre-existing entries with `source == 'vision'` (so reruns
         don't duplicate). Non-vision findings (DOM heuristics, axe-core)
         are preserved untouched.
      2. Append the new vision entries.
      3. Atomic-write back via temp file rename so a crash mid-write
         leaves the old file intact.
    """
    if findings_path.exists():
        try:
            payload = json.loads(findings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    existing = payload.get("findings")
    if not isinstance(existing, list):
        existing = []
    kept = [f for f in existing if not (isinstance(f, dict) and f.get("source") == "vision")]
    payload["findings"] = kept + list(vision_findings)
    tmp = findings_path.with_suffix(findings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(findings_path)


# ---------------------------------------------------------------------------
# Per-item review
# ---------------------------------------------------------------------------


def review_one(
    item: ReviewItem,
    intent_md: str,
    *,
    model: str,
    dry_run: bool,
    use_cache: bool,
    daily_budget_usd: float,
    ledger_path: Path,
    phase: str = VISION_PHASE_ALL,
) -> ReviewResult:
    png_bytes = item.png_path.read_bytes()
    mockup = _mockup_path(item.theme)
    mockup_fp = hashlib.sha256(mockup.read_bytes()).hexdigest() if mockup is not None else ""
    fp = fingerprint_inputs(
        png_bytes=png_bytes,
        intent_md=intent_md,
        prompt_version=PROMPT_VERSION,
        model=model,
        # Fold phase into the cache key so a switch between `content`
        # and `all` doesn't serve stale structural findings (the prompt
        # differs + the output allowlist differs).
        extra=f"{item.theme}/{item.route}/{item.viewport}/{phase}/{mockup_fp}",
    )

    if use_cache and item.fingerprint_path.exists():
        cached = item.fingerprint_path.read_text(encoding="utf-8").strip()
        if cached == fp:
            return ReviewResult(item=item, status="cached", note="fingerprint hit")

    proceed, reason = _passes_prefilter(png_bytes)
    if not proceed:
        # Even when prefiltered, write empty review.png + clear vision
        # findings so a stale review from a previous run doesn't linger.
        # Dry-run is purely read-only by contract; skip all writes.
        if not dry_run:
            _merge_findings(item.findings_path, [])
            _annotate_review_png(item, [])
            item.fingerprint_path.write_text(fp, encoding="utf-8")
        return ReviewResult(item=item, status="prefiltered", note=reason)

    purpose = _route_purpose(REPO_ROOT / item.theme, item.route)
    try:
        resp: VisionResponse = review_image(
            png_path=item.png_path,
            intent_md=intent_md,
            mockup_path=mockup,
            theme=item.theme,
            route=item.route,
            viewport=item.viewport,
            route_purpose=purpose,
            model=model,
            dry_run=dry_run,
            ledger_path=ledger_path,
            daily_budget_usd=daily_budget_usd,
            phase=phase,
        )
    except (ApiKeyMissingError, BudgetExceededError):
        raise
    except ApiCallFailedError as exc:
        return ReviewResult(item=item, status="errored", note=str(exc))

    # Dry-run is purely read-only by contract: no merging into
    # findings.json, no review.png write, no fingerprint stamp. Otherwise
    # an iteration with --dry-run would clobber real vision findings from
    # a previous live run.
    if not resp.dry_run:
        _merge_findings(item.findings_path, resp.findings)
        _annotate_review_png(item, resp.findings)
        item.fingerprint_path.write_text(fp, encoding="utf-8")
    return ReviewResult(
        item=item,
        status="reviewed",
        findings=resp.findings,
        cost_usd=resp.cost_usd,
        elapsed_s=resp.elapsed_s,
        note=("dry-run" if resp.dry_run else f"{resp.input_tokens}in/{resp.output_tokens}out"),
    )


# ---------------------------------------------------------------------------
# Validation against fixture manifest
# ---------------------------------------------------------------------------


def validate_against_fixtures(
    fixtures_dir: Path,
    *,
    model: str,
    dry_run: bool,
    daily_budget_usd: float,
    ledger_path: Path,
) -> int:
    """Run the reviewer against the labelled fixture set and compare
    findings against the manifest. Print precision/recall + return 0 if
    thresholds met, 1 otherwise."""
    manifest_path = fixtures_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"!! manifest.json not found at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = manifest.get("fixtures") or []
    accept = manifest.get("_meta", {}).get("acceptance", {})
    intent_md = (
        "# generic test rubric\n"
        "## Voice\nGeneric.\n## Palette\nWarm cream + ink.\n"
        "## Typography\nAny.\n"
    )

    print(f"== validating against {len(fixtures)} fixtures ==")
    if dry_run:
        print("   (dry-run: no API call; only structural sanity)")

    results = []
    for spec in fixtures:
        png = fixtures_dir / spec["file"]
        if not png.exists():
            print(f"  ?? missing fixture: {spec['file']}")
            continue
        # Synthetic ReviewItem; we don't write findings/review files for
        # fixtures (would dirty the repo). Call the lib directly.
        png_bytes = png.read_bytes()
        proceed, reason = _passes_prefilter(png_bytes)
        if not proceed and not dry_run:
            findings: list[dict] = []
            note = f"prefiltered ({reason})"
        else:
            try:
                resp = review_image(
                    png_path=png,
                    intent_md=intent_md,
                    theme="<fixture>",
                    route=spec["file"],
                    viewport="desktop",
                    model=model,
                    dry_run=dry_run,
                    ledger_path=ledger_path,
                    daily_budget_usd=daily_budget_usd,
                )
            except VisionError as exc:
                print(f"  !! {spec['file']}: {exc}")
                return 2
            findings = resp.findings
            note = "dry" if resp.dry_run else f"${resp.cost_usd:.3f}"
        results.append((spec, findings, note))

    # Compute stats. Each fixture contributes:
    #   - true positive  if any expected_findings kind appears
    #   - false negative if no expected_findings kind appears (regression)
    #   - false positive if any forbidden_findings kind appears (well-designed)
    regs_caught = 0
    regs_total = 0
    wd_fp = 0
    wd_total = 0
    tp = fp = fn = 0
    for spec, findings, note in results:
        kinds: set[str] = {str(f.get("kind") or "") for f in findings if f.get("kind")}
        expected: set[str] = set(spec.get("expected_findings") or [])
        forbidden: set[str] = set(spec.get("forbidden_findings") or [])
        if spec.get("kind") == "regression":
            regs_total += 1
            if expected & kinds:
                regs_caught += 1
                tp += 1
                ok = "PASS"
            else:
                fn += 1
                ok = "MISS"
            print(
                f"  [{ok}] {spec['file']}: expected={sorted(expected)} got={sorted(kinds)} ({note})"
            )
        else:
            wd_total += 1
            if forbidden & kinds:
                wd_fp += 1
                fp += 1
                ok = "FAIL(false-positive)"
            else:
                ok = "PASS"
            print(
                f"  [{ok}] {spec['file']}: forbidden={sorted(forbidden)} got={sorted(kinds)} ({note})"
            )

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    print()
    print(
        f"   regressions caught:        {regs_caught}/{regs_total} (min {accept.get('regressions_caught_min', '?')})"
    )
    print(
        f"   well-designed false +:     {wd_fp}/{wd_total} (max {accept.get('well_designed_false_positives_max', '?')})"
    )
    print(f"   precision:                 {precision:.2f} (min {accept.get('precision_min', '?')})")
    print(f"   recall:                    {recall:.2f} (min {accept.get('recall_min', '?')})")

    if dry_run:
        print()
        print(
            "   (dry-run: precision/recall meaningless without real API. "
            "Re-run with ANTHROPIC_API_KEY set to get real numbers.)"
        )
        return 0

    fail = (
        regs_caught < int(accept.get("regressions_caught_min", 4))
        or wd_fp > int(accept.get("well_designed_false_positives_max", 1))
        or precision < float(accept.get("precision_min", 0.80))
        or recall < float(accept.get("recall_min", 0.70))
    )
    return 1 if fail else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "theme", nargs="?", help="Theme slug (e.g. selvedge). Omit when using --validate."
    )
    p.add_argument("--routes", nargs="*", default=None, help="Route slugs to review (default: all)")
    p.add_argument(
        "--viewports", nargs="*", default=None, help="Viewport names to review (default: all)"
    )
    p.add_argument(
        "--no-cache", action="store_true", help="Ignore cached fingerprints; re-review every PNG."
    )
    p.add_argument("--dry-run", action="store_true", help="Build prompts but do not call the API.")
    p.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Override model (default {DEFAULT_MODEL})."
    )
    p.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_DAILY_BUDGET_USD,
        help=f"Daily $ cap (default ${DEFAULT_DAILY_BUDGET_USD:.2f}).",
    )
    p.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help=f"Path to spend ledger (default {DEFAULT_LEDGER_PATH}).",
    )
    p.add_argument(
        "--validate",
        type=Path,
        default=None,
        help="Run against the labelled fixture set at this path; skip normal review.",
    )
    p.add_argument(
        "--phase",
        choices=list(VISION_PHASES),
        default=VISION_PHASE_ALL,
        help=(
            "Which vision-finding kinds to grade. `content` (used by "
            "`design.py dress`) runs the reviewer with only the 4 "
            "catalogue-fit kinds (photography-mismatch, color-clash, "
            "brand-violation, mockup-divergent); `structural` runs the "
            "complement; `all` (default) runs both buckets, same as "
            "pre-split behaviour."
        ),
    )
    args = p.parse_args(argv)

    if args.validate:
        return validate_against_fixtures(
            args.validate,
            model=args.model,
            dry_run=args.dry_run,
            daily_budget_usd=args.budget,
            ledger_path=args.ledger,
        )

    if not args.theme:
        print("!! Theme required (or pass --validate <fixtures-dir>).", file=sys.stderr)
        return 2

    theme_root = REPO_ROOT / args.theme
    if not theme_root.is_dir():
        print(f"!! No such theme: {theme_root}", file=sys.stderr)
        return 2
    intent_md = _intent_md(theme_root)
    if intent_md is None:
        print(
            f"!! {args.theme}/design-intent.md missing. Add one first "
            "(see obel/design-intent.md for the canonical shape).",
            file=sys.stderr,
        )
        return 2

    items = _discover_items(args.theme, routes=args.routes, viewports=args.viewports)
    if not items:
        print(
            f"!! No PNGs to review. Run `python3 bin/snap.py shoot {args.theme}` first.",
            file=sys.stderr,
        )
        return 2

    print(
        f"== reviewing {len(items)} PNGs for {args.theme} "
        f"(model={args.model}, dry_run={args.dry_run})"
    )
    print(
        f"   today's spend so far: ${today_spend_usd(path=args.ledger):.3f} "
        f"/ ${args.budget:.2f} cap"
    )

    totals = {"reviewed": 0, "cached": 0, "prefiltered": 0, "errored": 0, "skipped": 0}
    cost = 0.0
    findings_count = 0

    for index, item in enumerate(items, start=1):
        print(f">> reviewing {index}/{len(items)} {item.viewport}/{item.route}", flush=True)
        try:
            r = review_one(
                item,
                intent_md,
                model=args.model,
                dry_run=args.dry_run,
                use_cache=not args.no_cache,
                daily_budget_usd=args.budget,
                ledger_path=args.ledger,
                phase=args.phase,
            )
        except ApiKeyMissingError as exc:
            print(f"!! {exc}", file=sys.stderr)
            return 2
        except BudgetExceededError as exc:
            print(f"!! {exc}", file=sys.stderr)
            print(
                f"   Stopping after {totals['reviewed']} reviews (cost ${cost:.3f}).",
                file=sys.stderr,
            )
            return 2
        totals[r.status] = totals.get(r.status, 0) + 1
        cost += r.cost_usd
        findings_count += len(r.findings)
        marker = {
            "reviewed": "  ",
            "cached": "= ",
            "prefiltered": ".. ",
            "errored": "!!",
            "skipped": "-",
        }.get(r.status, "?")
        print(
            f"  {marker} {item.viewport}/{item.route} [{r.status}] "
            f"{len(r.findings)} findings  {r.note}"
        )

    print()
    print(
        f"   reviewed={totals.get('reviewed', 0)} cached={totals.get('cached', 0)} "
        f"prefiltered={totals.get('prefiltered', 0)} errored={totals.get('errored', 0)}"
    )
    print(f"   total findings: {findings_count}")
    print(f"   call cost: ${cost:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
