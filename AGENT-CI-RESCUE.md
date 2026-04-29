# Agent CI Rescue Runbook

Use this when a PR is red and the agent needs to repair it without waiting for
manual babysitting.

## First Look

1. Read the failing GitHub checks and PR labels.
2. Resolve local scope with `python3 bin/changed-scope.py --base origin/main`.
3. Map the failed job to the closest local command:
   - `scoped theme gate`: `python3 bin/check.py --changed --changed-base origin/main --offline`
   - `fleet health`: `python3 bin/check.py --all --offline`
   - `snap evidence`: `python3 bin/snap.py shoot --changed --changed-base origin/main --quick`
   - `visual`: `python3 bin/snap.py check --changed --changed-base origin/main`
   - `ruff + mypy`: `python3 bin/lint.py`
   - `pytest tests/`: `python3 -m pytest tests/ --ignore=tests/validator -v`
   - drift jobs: run the named generator, inspect the diff, commit intentional output.

## Retry Rules

Retry transient Playground boot, network, or browser-install failures only after
reading the uploaded artifacts or logs. If the second run fails the same way,
treat it as a real defect.

## Regenerator Rules

When CI reports generated drift, run the deterministic owner:

- `python3 bin/sync-playground.py` for blueprint drift.
- `python3 bin/append-wc-overrides.py` for WC CSS drift.
- `python3 bin/build-brand-assets.py` for brand asset drift.
- `python3 bin/build-redirects.py` for short URL / concept queue drift.
- `python3 bin/build-theme-screenshots.py <theme>` after intentional theme visual changes.

## Rescue Push

Local hooks may be bypassed only with `FIFTY_AGENT_RESCUE=1`. This is audited in
hook output and exists so a repair branch can reach GitHub when local state is
missing unrelated snap evidence. CI remains authoritative; do not merge while the
remote checks are red.

Allowed:

```bash
FIFTY_AGENT_RESCUE=1 git commit -m "Fix scoped CI gate"
FIFTY_AGENT_RESCUE=1 git push
```

Not allowed: destructive git operations, force-pushing `main`, or hiding a real
block markup/editor-parity failure behind hook bypasses.

## Human-Only Blockers

Stop and report when the next action requires a missing secret, label permission
the token does not have, a design decision, a merge conflict that would discard
user work, or a destructive git operation.
