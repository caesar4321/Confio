#!/bin/sh
# Copies Hermes dSYM into the archive when CocoaPods misses it.
# Add a Run Script Build Phase in your app target AFTER "[CP] Copy dSYMs"
# with:  bash "${SRCROOT}/../scripts/copy-hermes-dsym.sh"

set -euo pipefail

if [ -z "${DWARF_DSYM_FOLDER_PATH:-}" ]; then
  echo "DWARF_DSYM_FOLDER_PATH not set; skipping Hermes dSYM copy."
  exit 0
fi

PODS_HERMES_ROOT="${PODS_ROOT}/hermes-engine"

if [ ! -d "$PODS_HERMES_ROOT" ]; then
  echo "hermes-engine pod not found at $PODS_HERMES_ROOT; skipping."
  exit 0
fi

# Try common locations for hermes dSYM across versions (framework or xcframework)
FOUND_DSYM=""
if [ -d "${PODS_HERMES_ROOT}/destroot/Library/Frameworks/hermes.framework.dSYM" ]; then
  FOUND_DSYM="${PODS_HERMES_ROOT}/destroot/Library/Frameworks/hermes.framework.dSYM"
fi

if [ -z "$FOUND_DSYM" ]; then
  FOUND_DSYM=$(find "$PODS_HERMES_ROOT" -type d -name "hermes.framework.dSYM" -print -quit 2>/dev/null || true)
fi

if [ -z "$FOUND_DSYM" ]; then
  echo "Hermes dSYM not found under $PODS_HERMES_ROOT; nothing to copy."
  exit 0
fi

DEST="${DWARF_DSYM_FOLDER_PATH}/hermes.framework.dSYM"
mkdir -p "${DWARF_DSYM_FOLDER_PATH}"
echo "Copying Hermes dSYM from ${FOUND_DSYM} to ${DEST}"
ditto "${FOUND_DSYM}" "${DEST}"

echo "Hermes dSYM copy complete."
