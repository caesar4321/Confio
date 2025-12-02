#!/bin/bash
# Generate a hermes.framework dSYM during archive so upload succeeds.
# Run from an Xcode build phase, after pods are available.

set -euo pipefail

if [[ -z "${DWARF_DSYM_FOLDER_PATH:-}" || -z "${PODS_ROOT:-}" ]]; then
  echo "[Hermes dSYM] Missing DWARF_DSYM_FOLDER_PATH or PODS_ROOT; skipping."
  exit 0
fi

HERMES_XCFRAMEWORK="${PODS_ROOT}/hermes-engine/destroot/Library/Frameworks/universal/hermes.xcframework"

if [[ ! -d "$HERMES_XCFRAMEWORK" ]]; then
  echo "[Hermes dSYM] Hermes xcframework not found at ${HERMES_XCFRAMEWORK}; skipping."
  exit 0
fi

# Choose the correct slice for the current platform
if [[ "${PLATFORM_NAME:-}" == *"simulator"* ]]; then
  HERMES_SLICE_DIR="ios-arm64_x86_64-simulator"
else
  HERMES_SLICE_DIR="ios-arm64"
fi

HERMES_BINARY="${HERMES_XCFRAMEWORK}/${HERMES_SLICE_DIR}/hermes.framework/hermes"

if [[ ! -f "$HERMES_BINARY" ]]; then
  echo "[Hermes dSYM] Hermes binary not found at ${HERMES_BINARY}; skipping."
  exit 0
fi

DEST_DSYM="${DWARF_DSYM_FOLDER_PATH}/hermes.framework.dSYM"
mkdir -p "${DWARF_DSYM_FOLDER_PATH}"

echo "[Hermes dSYM] Generating dSYM from ${HERMES_BINARY} -> ${DEST_DSYM}"
dsymutil "$HERMES_BINARY" -o "$DEST_DSYM"

echo "[Hermes dSYM] Done."
