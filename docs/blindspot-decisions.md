# Blind-spot decisions -- pre-100-themes hardening

This is the "answers for §Blind spots B.1-B.6" companion to the pre-100-themes hardening plan
(authored in Cursor's local `.cursor/plans/`, not checked into git).
The plan lists six gaps that need a decision before N=100, each
framed as a 10-minute conversation rather than a project. This doc
records the landed-on decision and points to the code that implements
it (or the line of code where implementation would land when pain
arises). Once a blind spot is landed here, this doc -- not the plan
-- is the source of truth.

Updating rules:

- One heading per blind spot, matching the plan's B.1-B.6 numbering.
- If a blind spot's decision changes later, edit the heading's
  **Decision** field rather than appending a new section -- this doc
  should always read as the *current* stance, not the history.
- If a section still says "TBD" at the start of a batch, that batch
  is gated on resolving it. Do not begin a batch with unresolved
  B-items.

---

## B.1 Theme retirement / removal flow

- **Decision:** **(a)** stage flipped to `retired` in
  `<slug>/readiness.json`; theme source kept on disk; discovery
  dropped across `bin/_lib.iter_themes`, `bin/snap.discover_themes`,
  and `bin/append-wc-overrides.discover_themes` (the three sites
  already share a `stage` filter from Tier 1.3).
- **Why:** the readiness manifest already supports it, it's
  reversible, and the source-kept-on-disk path preserves PR history
  without needing an `archive/` move or a destructive delete. Option
  (b) "source moved + baselines purged" is strictly worse for git
  history; (c) "git commit delete" loses the PR trail.
- **Operator flow:** hand-edit `<slug>/readiness.json`:
  ```jsonc
  { "stage": "retired", "notes": "retired YYYY-MM-DD, <reason>" }
  ```
  plus a `git commit -am "<slug>: retire"`. No new script; no
  `bin/retire-theme.py` until the flow is actually exercised twice.
- **Documented in:** [docs/shipping-a-theme.md](shipping-a-theme.md)
  §Retirement.

## B.2 Per-theme, per-gate timing telemetry

- **Decision:** **partially shipped**. `bin/design.py` writes
  per-phase durations into each run's `summary.json`; `bin/design-batch.py`
  records per-theme elapsed time, verification state, and rescue
  artifacts in `tmp/batch-<run-id>.json`. Defer deeper per-gate timing
  until this is not enough.
- **Why:** the current run summaries answer the immediate question:
  "which phase or theme is slow?" without introducing a second telemetry
  format. The Tier 2.2 dashboard (`bin/build-theme-status.py` ->
  `docs/themes/index.html`) still covers the public PASS/FAIL view.
- **Landing site when triggered:** add `duration_ms` to snap cell
  manifests and a one-page `docs/observability.md` that explains how
  to read phase, snap-cell, and CI timing together.
- **Trigger to revisit:** a batch of 10 themes takes >2 hours AND
  `summary.json` / `tmp/batch-<run-id>.json` do not identify the
  dominant phase.

## B.3 Deterministic design.py output

- **Decision:** **trust but verify on any generator refactor**.
- **Why:** if `bin/design.py` is non-deterministic on the same spec,
  a recovery re-run during a Chromium rebaseline will churn diffs
  on otherwise-untouched themes, and the PR review signal degrades.
- **Verification procedure** (~20 min, run before a large batch or
  after changing generator phases):
  1. Pick a recently-shipped slug with a clean `tmp/specs/<slug>.json`.
  2. In two parallel git worktrees (`git worktree add ../check-a` +
     `../check-b`), run `python3 bin/design.py tmp/specs/<slug>.json`
     in each.
  3. `diff -r <slug>/` between the two worktrees. Anything beyond a
     timestamp comment is the culprit.
  4. If non-deterministic, pin the LLM seed inside `_vision_lib` and
     cache responses to `tmp/llm-cache/<hash>.json` so rerun uses
     cache.
- **Landing site when triggered:** `bin/_vision_lib.py` (seed + cache)
  and `bin/design.py` (use cache by default).

## B.4 Imagery + content variety

- **Decision:** **generated first pass, human review before shipping.**
  `bin/generate-product-photos.py` now creates per-theme product,
  category, and page/post hero images during the design pipeline.
  Operators still review the images for taste, licensing posture, and
  theme fit before promotion.
- **Why:** the factory needs a complete visual payload to boot, snap,
  and verify without manual intervention. The uniqueness gates still
  catch duplicate product/hero imagery, while human review catches
  taste and rights questions that a deterministic check cannot.
- **Operator flow:**
  - Let `bin/design.py` run its `photos` phase.
  - Review `<slug>/playground/images/` and the generated
    `product-images.json` / `category-images.json` maps.
  - Keep `readiness.json.gates.images_unique` false until the
    uniqueness checks and visual review are clean.
- **Trigger to revisit:** a batch spends >50% of wall time repairing
  generated imagery, or a licensing/compliance review rejects the
  generated-image approach. The likely next option is a licensed stock
  library with deterministic per-theme assignment.

## B.5 Concurrency safety of check.py / snap.py under worktrees

- **Decision:** **confirm isolation before batch #2**. `tmp/` MUST be
  per-worktree, not shared with the primary repo.
- **Why:** `bin/design-batch.py` creates worktrees under
  `.cursor/worktrees/batch-<run-id>/<slug>/` and each runs its own
  `bin/design.py` -> snap -> check. If two of them simultaneously
  write `tmp/snaps/` or `tmp/playground-state/` at the repo root,
  we get crossed snaps and bogus drift findings.
- **Verification procedure:**
  1. In the primary repo, create two worktrees at different SHAs:
     `git worktree add ../fifty-a main; git worktree add ../fifty-b main`.
  2. In each, run `python3 bin/snap.py boot <slug> --cache-state`
     simultaneously.
  3. Verify `tmp/` is created inside each worktree, not shared.
     Specifically: `ls ../fifty-a/tmp/snaps/` and
     `ls ../fifty-b/tmp/snaps/` should show disjoint contents.
- **Landing site when broken:** `bin/_lib.py` -- wherever `TMP_DIR`
  or similar is computed, anchor to `Path(__file__).parent.parent`
  of the currently-running script, not `os.getcwd()` or a fixed
  `MONOREPO_ROOT`.

## B.6 LLM spend / rate-limit exposure

- **Decision:** **shipped.** Vision/LLM-backed flows write an
  append-only spend ledger and batch runs enforce a daily cap before
  each theme.
- **Why:** a 100-theme rollout with LLM-assisted concept-to-spec +
  spec-from-prompt + snap-vision-review will hit Anthropic dozens of
  times. Without a log we have no way to argue the budget case or
  catch a runaway batch. A per-day cap is now safer than guessing a
  lifetime project budget.
- **Operator flow:**
  - Append-only `tmp/vision-spend.jsonl` written through
    `bin/_vision_lib.py`.
  - `FIFTY_VISION_DAILY_BUDGET` / `--budget-usd` gates batch runs
    before each theme.
  - `--no-llm` / `--dry-run` flags remain the escape hatch for local
    rehearsals.
- **Trigger for next change:** if non-vision LLM calls grow outside
  `_vision_lib.py`, move the ledger naming from "vision" to a generic
  LLM spend ledger without losing historical entries.

---

## See also

- The pre-100-themes hardening plan's §Blind spots section was the
  original framing for each B-item. The plan is Cursor-local and
  not checked in; this file is now the source of truth for each
  landed decision.
- [docs/shipping-a-theme.md](shipping-a-theme.md) -- the operator
  checklist, which links back to this doc wherever a B-decision
  shows up (§Retirement from B.1, §Product imagery from B.4).
- [docs/batch-playbook.md](batch-playbook.md) -- the batch runner,
  which links here for B.3 (run deterministic-check before starting),
  B.5 (worktree isolation), and B.6 (LLM spend log).
