# Shipping a theme -- operator checklist

This is the step-by-step for taking a new theme from a concept in
`bin/concept_seed.py::CONCEPTS` to merged-on-main with
`readiness.json.stage = "shipping"`. Every step links to the command
that runs it; every step that can block a PR is called out as
**(gating)**.

If you're running 2+ themes in one pass, use
[docs/batch-playbook.md](batch-playbook.md) instead -- it wraps this
same checklist in a `bin/design-batch.py --from-concepts` loop with
logging and recovery patterns for a multi-theme run.

---

## 1. Pick a concept

Start from the public queue at
[`demo.regionallyfamous.com/concepts/`](https://demo.regionallyfamous.com/concepts/)
or from `bin/concept_seed.py::CONCEPTS`. The queue is the best
operator-facing source because it can deliberately put a same-slug
concept back "on the bench" even when an experimental theme directory
already exists.

For a scriptable list, use the batch runner's discovery mode:

```bash
python3 bin/design-batch.py --from-concepts --dry-run --limit 10
```

## 2. Generate the `design.py` spec

Preferred path (Tier 1.2):

```bash
python3 bin/concept-to-spec.py <slug>           # LLM-assisted (default)
python3 bin/concept-to-spec.py <slug> --no-llm  # deterministic from seed
```

Output lands at `tmp/specs/<slug>.json`. `--no-llm` is useful when you
want a reproducible spec from the concept seed alone (no network, no
Anthropic spend, no non-determinism).

Fallback: hand-write the spec against
[bin/design.py](../bin/design.py)'s docstring for its schema. Only use
this if the LLM path is broken or you need a structure concept-to-spec
doesn't emit.

## 3. Run `bin/design.py`

```bash
python3 bin/design.py build --spec tmp/specs/<slug>.json
python3 bin/design.py dress --spec tmp/specs/<slug>.json
```

`build` creates the structurally sound artifact: clone, tokens,
seeded Playground content, generated photos/microcopy/front-page,
index, prepublish, snap, baseline, screenshot, checks, redirects,
commit, and publish. `dress` re-runs the content-fit phases on the
same branch. The flat form, `python3 bin/design.py --spec ...`, still
runs the full pipeline in one invocation, but the build/dress split is
the preferred shape because batch mode can open a draft PR after
`build` and keep useful evidence even if a later phase fails.

## 4. Boot smoke (gating)

```bash
python3 bin/snap.py boot <slug>
```

`bin/snap.py boot` catches PHP fatals and broken templates in roughly
30-60s on a warm cache. It runs in the CI/snap evidence path before
the heavier screenshot matrix, so any push with a bootless theme gets
blocked fast. Fix whatever it reports before moving on.

Output: `tmp/<slug>-boot.json` -- read by the theme-status dashboard
(`bin/build-theme-status.py`) so stage-promotion reviewers can see at
a glance whether the theme actually boots.

## 5. Review the generated taste passes

These used to be manual passes. They now run inside `bin/design.py`,
but they are still the surfaces that most often need a human eye.
Budget review time explicitly -- if any of these blow up your wall
time by >2x compared to the batch, log the overrun back into
[day-0-smoke.md](day-0-smoke.md).

### 5a. WooCommerce microcopy

`bin/generate-microcopy.py --theme <slug>` is called by the pipeline.
Hand-review the resulting strings in `<slug>/functions.php` and the
theme patterns. `check_wc_microcopy_distinct_across_themes` in
[bin/check.py](../bin/check.py) gates cross-theme duplication; if two
themes end up with the same WooCommerce override, one will fail.

### 5b. Product imagery

`bin/generate-product-photos.py --theme <slug>` is called by the
pipeline and writes product, category, and page/post hero imagery
under `<slug>/playground/images/`. Hand-review the result for
theme-fit. Gate:
`check_product_images_unique_across_themes` +
`check_hero_images_unique_across_themes`.

### 5c. Front-page restructure

`bin/diversify-front-page.py --theme <slug>` is called by the
pipeline. Hand-review `<slug>/templates/front-page.html` and the
referenced patterns until the front page is visually distinct from the
Obel skeleton. `check_front_page_unique_layout` gates cross-theme
similarity.

## 6. `bin/check.py` clean (gating)

```bash
python3 bin/check.py --all --offline
```

Iterate until clean for your theme. If you hit a pre-existing failure
on `origin/main` that's unrelated to your work, the
`FIFTY_ALLOW_BASELINE_FAILURES=1` demotion path
(`tests/check-baseline-failures.json`) is already set by the hooks; a
new failure on your branch is the only thing that blocks. See
[tier 2.4 baseline-decay](../tests/check-baseline-failures.json) --
the allow list is a safety net, not a to-do list.

## 7. Visual baseline (gating on PR)

```bash
python3 bin/snap.py shoot <slug> --cache-state
python3 bin/snap.py baseline <slug>
```

The PR-time `check.yml` snap-evidence job plus `visual.yml` will
re-shoot and diff. If you hit Chromium drift hitting all themes, use
`bin/snap.py rebaseline --drifted --dry-run` rather than re-baselining
by hand.

## 8. Vision review (gating for NEW themes)

Apply the `design` label on the PR to trigger
`.github/workflows/vision-review.yml`. When the LLM critique passes,
the workflow adds a `vision-reviewed` label.

Tier 2.3 gate in `.github/workflows/check.yml::vision-review-gate`
enforces the `vision-reviewed` label as a *required* check for PRs
that introduce a brand-new theme (detected by
`bin/visual-matrix.py::_new_themes`). Existing themes stay on the
advisory path.

## 9. Promote to `stage: "shipping"`

Edit `<slug>/readiness.json`:

```jsonc
{
  "slug": "<slug>",
  "stage": "shipping",
  "gates": {
    "boots": true,
    "visual_baseline": true,
    "microcopy_distinct": true,
    "images_unique": true,
    "vision_review_passed": true
  },
  "notes": "promoted YYYY-MM-DD after <reviewer> eyeballed the home + shop passes"
}
```

`check_theme_readiness` in `bin/check.py` cross-checks the `gates.*`
claims against reality (the dashboard would look foolish if a theme
could self-declare `vision_review_passed` without the label). Lying
in `readiness.json` is caught at check time.

## 10. Open the PR

Title: `<slug>: initial theme`

The `check.yml`, `visual.yml`, `vision-review.yml`, and
`first-baseline.yml` workflows do the rest. `publish-demo.yml`
rebuilds and deploys the GH Pages demo site from `docs/` after pushes
to `main`; no docs-publishing PAT is needed.

---

## Retirement

(Blind spot §B.1 recommendation.) To retire a theme, flip
`readiness.json.stage = "retired"`. The three discovery sites
(`bin/_lib.iter_themes`, `bin/snap.discover_themes`,
`bin/append-wc-overrides.discover_themes`) already honor the stage
filter, so a retired theme drops out of snap / gallery / check
fan-outs but its source stays on disk for history. No separate
retirement script is needed.

## See also

- [docs/day-0-smoke.md](day-0-smoke.md) -- timed baseline findings.
- [docs/batch-playbook.md](batch-playbook.md) -- multi-theme batch
  runner.
- [docs/tier-3-deferrals.md](tier-3-deferrals.md) -- what is
  intentionally NOT shipped yet and under what trigger to build it.
- [docs/blindspot-decisions.md](blindspot-decisions.md) -- landed
  decisions for the six open §B-items.
- The pre-100-themes hardening plan (Cursor-local, not checked in)
  was the original framing for the tier work; the checked-in docs
  above are now the source of truth.
