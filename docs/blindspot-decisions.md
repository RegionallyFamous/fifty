# Blind-spot decisions -- pre-100-themes hardening

This is the "answers for §Blind spots B.1-B.6" companion to the
[pre-100-themes hardening plan](../.cursor/plans/pre-100-themes_hardening_eaa4ba54.plan.md).
The plan lists six gaps that need a decision before N=100, each
framed as a 10-minute conversation rather than a project. This doc
records the landed-on decision and points to the code that implements
it (or the line of code where implementation would land when pain
arises).

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

- **Decision:** **defer**. Add only when the next batch's wall-time
  exceeds 2 hours for 10 themes (the plan's threshold).
- **Why:** at N≤20 a human can still eyeball slow steps from the
  existing CI logs. The Tier 2.2 dashboard
  (`bin/build-theme-status.py` -> `docs/themes/index.html`) surfaces
  per-theme PASS/FAIL state, which covers the "which theme is
  broken?" case without per-gate wall time. Adding a telemetry
  format now risks picking fields we regret later.
- **Landing site when triggered:**
  `bin/check.py --json-timing tmp/check-timing.json` and a
  `duration_ms` field on every snap cell manifest. A one-page
  `docs/observability.md` records the reading format.
- **Trigger to revisit:** a batch of 10 themes takes >2 hours AND
  no one can point at which step dominated.

## B.3 Deterministic design.py output

- **Decision:** **trust but verify before batch #2**.
- **Why:** if `bin/design.py` is non-deterministic on the same spec,
  a recovery re-run during a Chromium rebaseline will churn diffs
  on otherwise-untouched themes, and the PR review signal degrades.
- **Verification procedure** (~20 min, run once before the next
  multi-theme batch):
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

- **Decision:** **log to `tmp/images-needed.md` per theme, sourcing
  stays manual for now.** Revisit after the next batch if the
  manual image sourcing dominates wall time.
- **Why:** auto-generated images have licensing/copyright
  uncertainty, and a stock library with 2000+ tagged images is a
  multi-day project. Meanwhile, the existing manual flow produces
  good taste and passes
  `check_{product,hero}_images_unique_across_themes`.
- **Operator flow:**
  - `readiness.json.gates.images_unique` stays `false` until the
    theme has 5+ distinct hero / product / category images committed.
  - Before shipping, eyeball
    `tmp/images-needed.md` (a future `check_theme_readiness` can
    emit this list; today operators produce it by hand from the
    images that failed the uniqueness check).
- **Trigger to revisit:** a batch spends >50% of its wall time on
  image sourcing -- at which point the two options are (a) image-gen
  with a licensed model + copyright audit, or (b) commit to a
  licensed stock library with deterministic per-theme assignment.
  Record the decision as an addendum to this section.

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

- **Decision:** **ship a spend logger before batch #2.** Skip the
  hard budget ceiling until we have a measured cost per batch.
- **Why:** a 100-theme rollout with LLM-assisted concept-to-spec +
  spec-from-prompt + snap-vision-review will hit Anthropic dozens of
  times. Without a log we have no way to argue the budget case or
  catch a runaway batch. A hard ceiling (`FIFTY_LLM_BUDGET_USD` abort)
  is tempting but premature -- we'd likely pick the wrong number.
- **Operator flow:**
  - Append-only `tmp/llm-spend.log` written by every LLM-backed
    script (`bin/_vision_lib.py` as the shared site). Format:
    `<iso-timestamp>\t<script>\t<model>\t<input_tokens>\t<output_tokens>\t<est_usd>`.
  - `--no-llm` / `--dry-run` flags on each script. `bin/concept-to-spec.py`
    already has this (Tier 1.2). Audit for coverage before batch #2.
- **Trigger for hard ceiling:** after one real batch, if the measured
  spend curve looks like it would exceed $50 / batch at N=100, add
  `FIFTY_LLM_BUDGET_USD` as an abort.

---

## See also

- [pre-100-themes_hardening plan](../.cursor/plans/pre-100-themes_hardening_eaa4ba54.plan.md)
  §Blind spots -- the authoritative framing for each B-item.
- [docs/shipping-a-theme.md](shipping-a-theme.md) -- the operator
  checklist, which links back to this doc wherever a B-decision
  shows up (§Retirement from B.1, §Product imagery from B.4).
- [docs/batch-playbook.md](batch-playbook.md) -- the batch runner,
  which links here for B.3 (run deterministic-check before starting),
  B.5 (worktree isolation), and B.6 (LLM spend log).
