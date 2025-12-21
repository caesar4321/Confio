#!/usr/bin/env bash
set -euo pipefail

# Copies shared assets into web/public so CRA can reference via PUBLIC_URL
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SRC_DIR_PNG="$ROOT_DIR/apps/src/assets/png"
SRC_DIR_SVG="$ROOT_DIR/apps/src/assets/svg"
DST_DIR="$ROOT_DIR/web/public/images"

mkdir -p "$DST_DIR"

copy_if_exists() {
  local name="$1"
  if [ -f "$SRC_DIR_PNG/$name" ]; then
    cp -f "$SRC_DIR_PNG/$name" "$DST_DIR/"
    echo "Copied $name"
  elif [ -f "$SRC_DIR_SVG/$name" ]; then
    cp -f "$SRC_DIR_SVG/$name" "$DST_DIR/"
    echo "Copied $name"
  else
    echo "WARNING: $name not found in $SRC_DIR_PNG or $SRC_DIR_SVG"
  fi
}

copy_if_exists "PioneroBeta.png"
copy_if_exists "Instagram.png"
copy_if_exists "YouTube.png"
copy_if_exists "TelegramLogo.svg"

echo "Done."
