#!/usr/bin/env bash
# Apply branch-protection rules to RegionallyFamous/fifty main.
#
# Idempotent: running this twice in a row produces the same state
# (GitHub's API PUT overwrites the ruleset rather than appending).
#
# What it does:
#   1. Require the seven CI checks from .github/workflows/check.yml
#      (theme-gate, drift-check, playground-sync-drift,
#       brand-assets-drift, tooling-tests, validator-smoke,
#       lint-format) to pass before a PR can be merged.
#   2. DO NOT require branches to be up to date with main before merge
#      (`strict: false`). See the block below for the rationale.
#   3. Do NOT require an approving review. CODEOWNERS still routes
#      review requests to the Proprietor, and the seven required
#      status checks below enforce every hard rule in AGENTS.md, but
#      a solo-maintainer repo can't satisfy "1 approving review" on
#      PRs opened by that same maintainer (GitHub forbids self-
#      approval) -- required_approving_review_count: 1 would stall
#      every PR at REVIEW_REQUIRED forever. If this ever becomes a
#      multi-maintainer repo, raise this back to 1 in the payload
#      below (search for `required_approving_review_count`).
#   4. Enforce linear history (no merge commits).
#   5. Disallow force pushes and branch deletion on main.
#   6. Require CODEOWNERS sign-off when the PR touches a CODEOWNERS path.
#
# ---- Why strict: false --------------------------------------------
# With `strict: true`, GitHub requires every PR branch to be current
# with main before it can merge. When one PR lands, every OTHER open
# PR goes BEHIND, and either (a) GitHub's auto-merge queue rebases
# each one, or (b) the author runs `gh pr update-branch`. Each rebase
# creates a new head SHA -> `synchronize` event -> every workflow
# re-runs. With 5 active PRs open, merging one cascades 4 full CI
# fleets; with 20 it cascades 19. The 2026-04-27 first-5 batch hit
# this hard -- each merge in a 5-PR queue triggered ~100 runner-
# minutes of redundant re-runs that we already knew were green.
#
# This monorepo is structured to make `strict: false` safe: each
# theme lives in its own directory, so cross-PR conflicts on
# theme-only PRs are impossible. The only place PRs can conflict is
# shared framework code in `bin/`, `.github/`, `playground/`, and
# top-level config -- a small surface that the CI's static gates
# (check.py, ruff, pytest, blocks-validator) catch on push-to-main
# even without a pre-merge rebase. The single-PR-at-a-time exception
# for framework work is an operational convention, not a branch-
# protection constraint.
#
# The `visual.yml` workflow is DELIBERATELY NOT in the required list —
# it is still warm-up / warn-only, and only runs on theme-path PRs
# anyway. Promote it to required once the baselines stabilise by
# editing REQUIRED_CHECKS below and re-running this script.
#
# Dependencies: `gh` CLI authenticated against the repo. Run from
# anywhere in the checkout.
#
# Usage:
#     bash bin/setup-branch-protection.sh
#
# One-off review of the current ruleset:
#     gh api repos/RegionallyFamous/fifty/branches/main/protection

set -euo pipefail

REPO="${REPO:-RegionallyFamous/fifty}"
BRANCH="${BRANCH:-main}"

# Required check names MUST match the `name:` field of each job in
# the workflow YAML, not the filename. Keep this list in lockstep
# with .github/workflows/check.yml.
REQUIRED_CHECKS=(
  "bin/check.py --all --offline"
  "append-wc-overrides.py is a no-op"
  "sync-playground.py is a no-op"
  "build-brand-assets.py --check"
  "pytest tests/"
  "node blocks-validator smoke"
  "ruff + mypy"
)

echo ">> Applying branch protection to ${REPO}:${BRANCH}"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: the gh CLI is required (brew install gh / apt install gh)" >&2
  exit 2
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "error: gh is not authenticated. Run: gh auth login" >&2
  exit 2
fi

# Build the JSON payload using jq so check names with spaces are
# quoted correctly. Mapping to the REST API shape documented at
# https://docs.github.com/en/rest/branches/branch-protection
payload=$(jq -n \
  --argjson contexts "$(printf '%s\n' "${REQUIRED_CHECKS[@]}" | jq -R . | jq -s .)" \
  '{
    required_status_checks: {
      strict: false,
      contexts: $contexts
    },
    enforce_admins: null,
    required_pull_request_reviews: {
      dismiss_stale_reviews: true,
      require_code_owner_reviews: true,
      required_approving_review_count: 0
    },
    restrictions: null,
    required_linear_history: true,
    allow_force_pushes: false,
    allow_deletions: false,
    required_conversation_resolution: true,
    lock_branch: false,
    allow_fork_syncing: true
  }')

echo "$payload" | jq .

gh api \
  --method PUT \
  "repos/${REPO}/branches/${BRANCH}/protection" \
  --input - <<< "$payload"

echo
echo "Done. Review: https://github.com/${REPO}/settings/branches"
