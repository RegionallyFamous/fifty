# Batch playbook -- running N themes through the pipeline

This is the operator guide for taking 5-20 concepts from
`bin/concept_seed.py::CONCEPTS` to merged-on-main in a single batch
using `bin/design-batch.py --from-concepts`. For a single theme, use
[docs/shipping-a-theme.md](shipping-a-theme.md) instead -- it's the
per-theme checklist this playbook wraps.

## When to run a batch

- You want 5+ new themes merged and the single-theme checklist would
  consume a week of hand-operation.
- Tier-0 smoke
  ([docs/day-0-smoke.md](day-0-smoke.md)) is already written; you
  have honest per-phase timings to compare the batch's actual wall
  time against.
- CI capacity permits: a batch of 10 themes will push 10 PRs through
  `.github/workflows/check.yml`, `visual.yml`, and `vision-review.yml`
  over the course of a day. If the CI waves (smart-snaps + CI waves,
  previous plan) are already saturated, stagger.

## Prep

1. Pick the concept slugs. Suggested: avoid clustering by sector or
   era -- mixing `agave` (beauty), `brine` (food/drink), and
   `cathode` (retro/tech) hits more cross-theme uniqueness checks in
   one batch and surfaces collisions early.

2. Pre-flight the controlled vocabulary. `bin/concept-to-spec.py`'s
   `--no-llm` deterministic path relies on palette_tag + type_genre
   lookups; if any of your slugs use tags not yet in the lookup
   tables you'll see "unknown palette_tag" warnings. Either extend
   the tables ([bin/concept-to-spec.py](../bin/concept-to-spec.py)
   has them at module scope) in a pre-batch PR, or export a Miles spec
   for those slugs and merge by hand.

3. Spec generation in `--from-concepts` is **deterministic only**
   (``bin/concept-to-spec`` controlled-vocab mapping — free/offline).
   For mockup-led polish use Miles + ``design.py --miles-artifacts``.
   Batch runs also honor ``--budget-usd`` / ``FIFTY_VISION_DAILY_BUDGET``
   before each theme so a run halts cleanly at the daily cap instead of
   failing mid-theme.

## Kicking off the batch

```bash
python3 bin/design-batch.py \
  --from-concepts \
  --concept-slugs "agave,apiary,brine,cathode,cobbler" \
  --limit 5
```

- `--limit N` is a safety stop -- even if `--concept-slugs` lists 10,
  only the first 5 run. Keeps a typo from spawning 50 branches.
- Omit `--concept-slugs` to let the script discover every concept on
  the bench. `--limit` is still honored.
- The default path is progressive: each theme gets its own worktree,
  runs `bin/design.py build`, opens a draft PR as soon as there is a
  runnable artifact, then runs `bin/design.py dress` on the same
  branch. Use `--single-shot` only when you want the legacy "open a PR
  after every phase succeeds" behavior.
- Branches are named `agent/batch-<run-id>-<slug>`. Reusing the same
  `--run-id` resumes passed themes; `--no-resume` forces a fresh local
  worktree and removes stale generated remote batch branches.
- By default, children run through `bin/design-watch.py`, which can
  self-heal, record repair attempts, and keep the live `STATUS.md`
  file current. Use `--no-self-heal` only when debugging the watcher.
- Use `--keep-going` for proof runs where you want a draft PR and
  evidence even when a phase cannot be fully repaired. The PR remains
  draft until verification/factory-defect promotion says it is safe.

Output: `tmp/batch-<run-id>.json` records the per-theme outcome:
`passed | failed | skipped | budget_capped`, plus worktree, branch,
PR URL, verify status, rescue artifacts, factory defects, and grouped
prevention layers. Scan this first rather than reading every worktree.

## Mid-batch monitoring

- Each in-flight theme has
  `tmp/runs/batch-<run-id>-<slug>-<stage>/STATUS.md` inside its
  worktree. This is the first place to look for current phase,
  screenshot progress, active blocker, and next action.
- `bin/build-theme-status.py` regenerates `docs/themes/index.html`.
  During the batch, run it locally (`python3 bin/build-theme-status.py`)
  to see which themes have boots / microcopy / images / vision green.
- `bin/snap.py rebaseline --drifted --dry-run` (Tier 1.4) -- if mid-
  batch you see drift on unrelated themes, it's almost certainly a
  Chromium bump on the runner. Confirm with
  [.github/workflows/nightly-snap-sweep.yml](../.github/workflows/nightly-snap-sweep.yml)
  and use the rebaseline preview mode rather than reshooting by hand.
- `.github/workflows/check.yml::theme-status-dashboard` auto-commits
  the dashboard on every push to main, so any merged batch is
  visible on the dashboard within minutes.

## Recovery patterns

### A slug fails `concept-to-spec`

```bash
tail tmp/batch-<run-id>.json  # which slug? why?
python3 bin/concept-to-spec.py <slug> --no-llm --verbose
```

If validation still fails, the concept metadata is off-schema for
`bin/design.py` — fix the seed tags or author a Miles-exported spec and
point the manifest at ``{"spec": "..."}``.

### A slug fails `design.py` / `design-watch.py`

Read the stage-specific `STATUS.md` and `summary.json` under the
child worktree's `tmp/runs/` directory. If self-healing ran, also read
`repair-attempts.jsonl` and `factory-defects.jsonl`. The batch report
will point to these files. Rerun with `--retry-failed` after fixing
the blocker, or `--no-resume` when you want a completely fresh proof.

### A slug fails `boot`

`tmp/<slug>-boot.json` + `tmp/<slug>-server.log` hold the fatal. 99%
of the time it's a `functions.php` typo from a hand-edit. Fix and
rerun `python3 bin/snap.py boot <slug>`.

### Drift on already-merged themes during the batch

Two interpretations, decide which:

1. **Uniform drift** (every theme shifts by the same few pixels):
   Chromium on `ubuntu-latest` bumped. One PR:

   ```bash
   python3 bin/snap.py rebaseline --drifted
   git commit -am "snap: rebaseline after 2026-MM-DD Chromium bump"
   ```

2. **Theme-specific drift** (one theme moved, others didn't): real
   regression. Bisect, don't rebaseline. Use git worktrees on the
   last-known-good SHA to confirm.

### Baseline allow-list filled up mid-batch

Unusual but possible -- a new cross-theme check catches pre-existing
debt that was fine with fewer themes. Treat as either:

- Fix the underlying check violation (preferred), or
- Record in `tests/check-baseline-failures.json` with a real
  `justification` per Tier 2.4 schema. The nightly baseline-decay job
  will start its 30-day clock from the day you added it.

## End-of-batch wrap

1. Review `tmp/batch-<run-id>.json` -- every `passed` row should have
   a PR open (or merged); every `failed` row should point at a status
   file, rescue artifact, or follow-up plan.

2. Run `python3 bin/check.py --save-baseline-failures` only from a
   detached worktree pointing at `origin/main` AFTER the batch has
   merged -- never from the batch's own worktrees, or you'll snapshot
   your in-flight failures as "pre-existing main debt".

3. Update [docs/day-0-smoke.md](day-0-smoke.md) with the batch's
   dominant cost (spec, manual, check iteration, or shoot). The Tier
   prioritization rechecks against this measurement at every batch.

4. If you want the GH Pages demo site to publish after a batch without
   relying on per-theme PRs touching `docs/`, run the batch with
   `--publish-demo` or run `python3 bin/build-redirects.py` once after
   the theme PRs merge. `publish-demo.yml` deploys the generated
   `docs/` artifact via GitHub Pages.

5. Archive `tmp/batch-<run-id>.json` if you want a long-term record;
   otherwise `tmp/` is cleaned up by the next `bin/design-batch.py`
   run.

## See also

- [docs/shipping-a-theme.md](shipping-a-theme.md) -- per-theme
  checklist this playbook wraps.
- [docs/day-0-smoke.md](day-0-smoke.md) -- honest per-phase timings
  the playbook's "end-of-batch wrap" compares against.
- [docs/tier-3-deferrals.md](tier-3-deferrals.md) -- shared patterns
  / functions.d / perf budgets are deferred until a batch
  concretely demonstrates their pain. Log evidence there.
- The pre-100-themes hardening plan (Cursor-local, not checked in)
  was the authoring context for the tier work these docs describe.
  The plan's conclusions now live in this doc, `shipping-a-theme.md`,
  `blindspot-decisions.md`, `day-0-smoke.md`, and
  `tier-3-deferrals.md` -- treat those as the source of truth.
