#!/usr/bin/env bash
# Sync the canonical source (src/ainiee_translate) into the plugin bundle
# (skills/ainiee-translate/scripts). References and SKILL.md live directly in
# skills/ainiee-translate/ — that directory is the single source of truth for
# everything except the Python package.
set -euo pipefail
cd "$(dirname "$0")"

SCRIPTS_DST="skills/ainiee-translate/scripts/ainiee_translate"
mkdir -p "$SCRIPTS_DST"
rsync -a --delete --exclude='__pycache__' src/ainiee_translate/ "$SCRIPTS_DST/"

# Drift guard: bundled scripts must equal src.
if ! diff -rq --exclude='__pycache__' src/ainiee_translate "$SCRIPTS_DST" >/dev/null; then
  echo "ERROR: bundled scripts differ from src/ after sync" >&2
  diff -rq --exclude='__pycache__' src/ainiee_translate "$SCRIPTS_DST" >&2 || true
  exit 1
fi
echo "synced src -> $SCRIPTS_DST  (in sync ✓)"
