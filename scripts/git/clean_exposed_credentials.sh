#!/bin/bash
#
# Clean exposed credentials from git history
#
# This script removes the compromised mnemonic from all git history.
# WARNING: This rewrites git history and requires force push!
#
# Usage:
#   ./scripts/git/clean_exposed_credentials.sh --dry-run    # Preview changes
#   ./scripts/git/clean_exposed_credentials.sh --execute    # Actually clean history
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# The compromised mnemonic to remove
COMPROMISED_MNEMONIC="<REDACTED_OLD_COMPROMISED_MNEMONIC>"

echo "=========================================="
echo "Git History Cleanup Script"
echo "=========================================="
echo

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}Error: You have uncommitted changes${NC}"
    echo "Please commit or stash your changes first"
    exit 1
fi

# Get current branch
CURRENT_BRANCH=$(git branch --show-current)
echo -e "${YELLOW}Current branch: ${CURRENT_BRANCH}${NC}"
echo

# Parse arguments
DRY_RUN=true
if [ "$1" == "--execute" ]; then
    DRY_RUN=false
    echo -e "${RED}⚠️  EXECUTE MODE: This will rewrite git history!${NC}"
    echo
    read -p "Are you sure you want to proceed? Type 'yes': " -r
    if [ "$REPLY" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
    echo
elif [ "$1" != "--dry-run" ] && [ -n "$1" ]; then
    echo "Usage: $0 [--dry-run|--execute]"
    exit 1
fi

if [ "$DRY_RUN" = true ]; then
    echo -e "${GREEN}DRY RUN MODE: No changes will be made${NC}"
    echo
fi

# Create backup branch
BACKUP_BRANCH="backup-before-history-clean-$(date +%Y%m%d-%H%M%S)"
echo "Creating backup branch: ${BACKUP_BRANCH}"
git branch ${BACKUP_BRANCH}
echo -e "${GREEN}✓ Backup created${NC}"
echo

# Files that contained the compromised mnemonic
FILES_TO_CLEAN=(
    "scripts/admin/create_test_referral_box.py"
    "scripts/admin/fix_broken_referrer_reward.py"
    "scripts/deployment/fund_vault.py"
    "scripts/deployment/bootstrap_rewards.py"
    "scripts/deployment/deploy_fixed_rewards.py"
    "tests/integration/rewards/test_two_sided_final.py"
    "tests/integration/rewards/test_two_sided_reward.py"
    "tests/integration/rewards/test_manual_price.py"
)

echo "Files that will be rewritten:"
for file in "${FILES_TO_CLEAN[@]}"; do
    echo "  - ${file}"
done
echo

# Create a temporary file with the mnemonic for replacement
TEMP_FILE=$(mktemp)
echo "$COMPROMISED_MNEMONIC" > "$TEMP_FILE"

if [ "$DRY_RUN" = true ]; then
    echo "Would remove the compromised mnemonic from git history..."
    echo
    echo "To execute the cleanup, run:"
    echo "  $0 --execute"
    echo
    echo -e "${YELLOW}After executing, you'll need to force push to GitHub:${NC}"
    echo "  git push origin --force --all"
    echo "  git push origin --force --tags"
    rm "$TEMP_FILE"
    exit 0
fi

# Execute the cleanup
echo "Cleaning git history..."
echo

# Method: Use git-filter-repo to replace the mnemonic with a placeholder
# Create a replacements file
REPLACE_FILE=$(mktemp)
echo "literal:${COMPROMISED_MNEMONIC}==><REDACTED_MNEMONIC>" > "$REPLACE_FILE"

# Run git-filter-repo
git filter-repo \
    --replace-text "$REPLACE_FILE" \
    --force

rm "$REPLACE_FILE"
rm "$TEMP_FILE"

echo
echo -e "${GREEN}✓ Git history cleaned successfully!${NC}"
echo

# Show what changed
echo "Verifying cleanup..."
echo
if git log --all --full-history -S "$COMPROMISED_MNEMONIC" | grep -q commit; then
    echo -e "${RED}⚠️  WARNING: Mnemonic may still exist in history!${NC}"
    echo "Commits that may still contain it:"
    git log --all --full-history -S "$COMPROMISED_MNEMONIC" --oneline
else
    echo -e "${GREEN}✓ Mnemonic successfully removed from all history${NC}"
fi
echo

echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo
echo "1. Verify the cleanup worked:"
echo "   git log --all --full-history -S \"congress jaguar\" | grep commit"
echo "   (should return nothing)"
echo
echo "2. Force push to GitHub to update remote history:"
echo -e "   ${YELLOW}git push origin --force --all${NC}"
echo -e "   ${YELLOW}git push origin --force --tags${NC}"
echo
echo "3. Notify all team members:"
echo "   - They must delete their local clones"
echo "   - They must clone fresh from GitHub"
echo "   - DO NOT merge old branches with unrewritten history"
echo
echo "4. If you have the repository cloned elsewhere, update those too:"
echo "   cd /other/location/Confio"
echo "   git fetch origin"
echo "   git reset --hard origin/${CURRENT_BRANCH}"
echo
echo -e "${RED}IMPORTANT: Your backup is in branch '${BACKUP_BRANCH}'${NC}"
echo "If something goes wrong, you can restore with:"
echo "  git reset --hard ${BACKUP_BRANCH}"
echo
