#!/bin/sh
# Copies the correct Hermes dSYM (matching UUID) into the archive when CocoaPods misses it.
# Add a Run Script Build Phase in your app target AFTER "[CP] Copy dSYMs"
# with:  bash "${SRCROOT}/scripts/copy-hermes-dsym.sh"

set -euo pipefail
set -x

if [ -z "${DWARF_DSYM_FOLDER_PATH:-}" ]; then
  echo "DWARF_DSYM_FOLDER_PATH not set; skipping Hermes dSYM copy."
  exit 0
fi

PODS_HERMES_ROOT="${PODS_ROOT}/hermes-engine"

if [ ! -d "$PODS_HERMES_ROOT" ]; then
  echo "hermes-engine pod not found at $PODS_HERMES_ROOT; skipping."
  exit 0
fi

# If Hermes is statically linked, there will be no hermes.framework and no dSYM needed
HERMES_FW_IN_APP="${TARGET_BUILD_DIR}/${FRAMEWORKS_FOLDER_PATH:-Frameworks}/hermes.framework/hermes"
if [ ! -f "$HERMES_FW_IN_APP" ]; then
  echo "No dynamic hermes.framework found in app; assuming static Hermes."
  exit 0
fi

# Determine expected UUID of the hermes binary embedded in the app
EXPECTED_UUIDS=$(dwarfdump -u "$HERMES_FW_IN_APP" 2>/dev/null | awk '/UUID:/ {print $2}')
if [ -z "$EXPECTED_UUIDS" ]; then
  echo "Could not read UUIDs from $HERMES_FW_IN_APP; skipping."
  exit 0
fi
echo "Expected Hermes UUID(s): $EXPECTED_UUIDS"

# Search all candidate Hermes dSYMs under the pod and pick one matching any expected UUID
FOUND_MATCHING_DSYM=""
while IFS= read -r dsym_file; do
  # dsym_file points to the DWARF file inside the .dSYM bundle
  DSYM_BUNDLE_DIR=$(dirname "$dsym_file")/..
  for uuid in $EXPECTED_UUIDS; do
    if dwarfdump -u "$dsym_file" 2>/dev/null | grep -q "$uuid"; then
      FOUND_MATCHING_DSYM=$(cd "$DSYM_BUNDLE_DIR" && pwd)
      echo "Found matching Hermes dSYM: $FOUND_MATCHING_DSYM"
      break 2
    fi
  done
done <<EOF
$(find "$PODS_HERMES_ROOT" -type f -path "*/hermes.framework.dSYM/Contents/Resources/DWARF/*" 2>/dev/null)
EOF

if [ -z "$FOUND_MATCHING_DSYM" ]; then
  echo "No Hermes dSYM with matching UUID found under $PODS_HERMES_ROOT; skipping."
  exit 0
fi

DEST="${DWARF_DSYM_FOLDER_PATH}/hermes.framework.dSYM"
mkdir -p "${DWARF_DSYM_FOLDER_PATH}"
echo "Copying Hermes dSYM from ${FOUND_MATCHING_DSYM} to ${DEST}"
ditto "$FOUND_MATCHING_DSYM" "$DEST"

echo "Hermes dSYM copy complete."
