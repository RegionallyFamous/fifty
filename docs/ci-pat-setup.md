# `FIFTY_AUTO_PAT` — one-time setup

This repo's PR automation may commit back into PR branches from two
workflows:

- `.github/workflows/first-baseline.yml` — seeds
  `tests/visual-baseline/<theme>/` and flips `readiness.stage` to
  `shipping` the moment a PR is labelled `ready-for-baseline`.
- `.github/workflows/visual.yml` (rebaseline mode) — promotes fresh
  snaps to the committed baseline tree and regenerates
  `<theme>/screenshot.png`.

Those PR-branch pushes need to **retrigger the PR's checks**
(`check.yml` / `visual.yml`) so the PR can go green and auto-merge
without a human in the loop.

GitHub deliberately blocks this when the push is attributed to the
default `GITHUB_TOKEN`:

> When you use the repository's GITHUB_TOKEN to perform tasks,
> events triggered by the GITHUB_TOKEN, with the exception of
> workflow_dispatch and repository_dispatch, will not create a new
> workflow run. This prevents you from accidentally creating
> recursive workflow runs.
> — [Triggering a workflow from a workflow](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow)

To close the loop we push with a **classic personal access token
(PAT)** attributed to a real user. Pushes from a PAT fire
`pull_request.synchronize` normally, so `check.yml` / `visual.yml`
re-run and auto-merge lands when they're green.

Without the PAT everything still works — first-baseline still commits
baselines, visual.yml still rebaselines — but a human may have to kick
CI to re-evaluate the PR (close+reopen, or push an empty commit). The
workflows print a loud `::warning::` when this fallback path is in
effect so you never silently stall.

This PAT is **not** needed for the public demo site. `publish-demo.yml`
uses `actions/upload-pages-artifact` + `actions/deploy-pages` with the
default `GITHUB_TOKEN` and `pages:write` permission, so docs/ and
mockups/ deployment no longer requires a push-to-main token.

## Setup (one-time, ~3 minutes)

1. Go to <https://github.com/settings/tokens?type=beta> (Fine-grained
   PATs) **or** <https://github.com/settings/tokens> (Classic).
   Classic is simpler and works; fine-grained is tighter-scoped and
   recommended.
2. Create a token:
   - **Name**: `fifty auto-push (CI retrigger)`
   - **Expiration**: a realistic one. 1y is fine for a personal repo;
     90d is the maximum GitHub pre-populates and forces a rotation
     cadence.
   - **Classic scopes**: `repo` (this grants push access to the repo
     and read access to protected branches — needed for the rebaseline
     push because the PR branch will often point at a protected-ish
     state).
   - **Fine-grained**: only `RegionallyFamous/fifty` in "Repository
     access", then under "Repository permissions" grant:
     - `Contents: Read and write` (for `git push`)
     - `Pull requests: Read and write` (future-proofing — if we ever
       have a workflow auto-label or auto-merge via `gh pr`)
     - Everything else: `No access`.
3. Copy the generated token (you won't see it again).
4. In this repo: Settings → Secrets and variables → Actions → New
   repository secret.
   - **Name**: `FIFTY_AUTO_PAT`
   - **Secret**: paste the token.
5. Verify: re-run `.github/workflows/first-baseline.yml` on any open
   PR that has a `ready-for-baseline` label and look at the `Report
   push-token mode` step output. You should see:
   > ::notice::first-baseline push will be attributed to the
   > FIFTY_AUTO_PAT user → pull_request.synchronize WILL fire on the
   > PR, so check.yml/visual.yml re-run automatically and auto-merge
   > can land once they're green.

## Rotation

The secret has a hard expiration. Two things break when it expires:

- New `first-baseline.yml` runs fall back to `GITHUB_TOKEN` and the
  `Report push-token mode` step flips to a `::warning::`. The commit
  still lands but the PR stalls at "baselines present but un-gated".
- Same for `visual.yml` rebaseline mode.

Rotation recipe: repeat the setup steps above with a new token, paste
into the same `FIFTY_AUTO_PAT` secret, revoke the old token at
<https://github.com/settings/tokens>.

## What we don't do with this PAT

- **Publish the demo site.** GH Pages deployment is handled by
  `publish-demo.yml` with `pages:write`; do not reuse this PAT for
  Pages.
- **Merge commits on main.** Branch-protection rules on `main`
  require a PR review; `FIFTY_AUTO_PAT` intentionally does not grant
  the permissions that would let a workflow bypass this. If someone
  later wants push-to-main automation, use a separate secret with a
  narrower scope or a GitHub App.
- **Push to unrelated repos.** Fine-grained PATs are scoped to
  `RegionallyFamous/fifty` exactly. Classic PATs are scoped to all
  your repos — using the fine-grained variant is the mitigation.
- **Read secrets.** Neither PAT variant grants access to repo
  secrets. GitHub Actions still handles secret masking, so the token
  never appears in logs.

## Troubleshooting

- **`remote: Permission to RegionallyFamous/fifty.git denied`** on
  the `git push` step: the PAT was revoked, expired, or typo'd.
  Regenerate and re-paste.
- **`pull_request.synchronize` still doesn't fire**: confirm the
  workflow's `actions/checkout@v6` step has
  `token: ${{ secrets.FIFTY_AUTO_PAT || secrets.GITHUB_TOKEN }}` —
  the `persist-credentials: true` must also be set (it's the default
  but worth re-checking). The `::notice::` vs `::warning::` line in
  `Report push-token mode` is the live indicator.
- **PR has two competing label events from one `gh pr edit
  --add-label A --add-label B`** (`vision-review.yml` does this) and
  the second one doesn't fire workflows: unrelated. That's the
  [webhook-delivery batching behavior](https://github.com/orgs/community/discussions/22704);
  both events fire, just sometimes with a 1–2s gap.
