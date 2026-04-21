#!/usr/bin/env bash
# Apply branch-protection rules to RegionallyFamous/fifty main.
#
# Idempotent: running this twice in a row produces the same state
# (GitHub's API PUT overwrites the ruleset rather than appending).
#
# What it does:
#   1. Require the five CI checks from .github/workflows/check.yml
#      (theme-gate, drift-check, tooling-tests, validator-smoke,
#       lint-format) to pass before a PR can be merged.
#   2. Require branches to be up to date with main before merge.
#   3. Require at least 1 approving review.
#   4. Enforce linear history (no merge commits).
#   5. Disallow force pushes and branch deletion on main.
#   6. Require CODEOWNERS sign-off when the PR touches a CODEOWNERS path.
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
      strict: true,
      contexts: $contexts
    },
    enforce_admins: null,
    required_pull_request_reviews: {
      dismiss_stale_reviews: true,
      require_code_owner_reviews: true,
      required_approving_review_count: 1
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
