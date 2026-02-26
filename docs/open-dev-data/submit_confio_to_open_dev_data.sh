#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./docs/open-dev-data/submit_confio_to_open_dev_data.sh <your-github-username>
# Example:
#   ./docs/open-dev-data/submit_confio_to_open_dev_data.sh caesar4321

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <your-github-username>"
  exit 1
fi

GH_USER="$1"
TS="$(date -u +"%Y-%m-%dT%H%M%S")"
BRANCH="codex/add-confio-open-dev-data"
WORKDIR="$(mktemp -d)"
UPSTREAM_REPO="electric-capital/open-dev-data"
FORK_REPO="${GH_USER}/open-dev-data"

cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "[1/8] Cloning electric-capital/open-dev-data"
git clone "https://github.com/${UPSTREAM_REPO}.git" "$WORKDIR/open-dev-data"
cd "$WORKDIR/open-dev-data"

echo "[2/8] Creating branch: $BRANCH"
git checkout -b "$BRANCH"

echo "[3/8] Adding migration"
MIGRATION_FILE="migrations/${TS}_add_confio"
cp /Users/julian/Confio/docs/open-dev-data/confio_migration.lua "$MIGRATION_FILE"

echo "[4/8] Running validation"
if command -v uvx >/dev/null 2>&1; then
  uvx open-dev-data validate
elif command -v open-dev-data >/dev/null 2>&1; then
  open-dev-data validate
elif [[ "${SKIP_VALIDATE:-0}" == "1" ]]; then
  echo "Skipping validation because SKIP_VALIDATE=1"
else
  echo "Neither uvx nor open-dev-data found."
  echo "Install uv (https://docs.astral.sh/uv/) and rerun, or run with SKIP_VALIDATE=1 to proceed without validation."
  exit 1
fi

echo "[5/8] Committing changes"
git add "$MIGRATION_FILE"
git commit -m "add Confio ecosystem and repo"

echo "[6/8] Ensuring your fork remote"
# Fail early with a clear message if the fork doesn't exist yet.
if ! curl -fsS "https://api.github.com/repos/${FORK_REPO}" >/dev/null 2>&1; then
  echo "Fork not found: https://github.com/${FORK_REPO}"
  echo "Create it first at: https://github.com/${UPSTREAM_REPO}/fork"
  exit 1
fi

# Prefer SSH if available to avoid PAT prompts for HTTPS.
if ssh -T git@github.com >/dev/null 2>&1; then
  FORK_URL="git@github.com:${FORK_REPO}.git"
else
  FORK_URL="https://github.com/${FORK_REPO}.git"
fi

if git remote get-url fork >/dev/null 2>&1; then
  git remote set-url fork "$FORK_URL"
else
  git remote add fork "$FORK_URL"
fi

echo "[7/8] Pushing branch to your fork"
git push -u fork "$BRANCH"

echo "[8/8] Done. Open this URL to create the PR:"
echo "https://github.com/${UPSTREAM_REPO}/compare/master...${GH_USER}:${BRANCH}?expand=1"
echo
echo "Use PR body from: /Users/julian/Confio/docs/open-dev-data/confio_pr_template.md"
echo "Migration file created: $MIGRATION_FILE"
