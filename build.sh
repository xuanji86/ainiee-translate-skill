#!/usr/bin/env bash
# Sync the canonical source into the plugin bundle so the installed plugin
# matches src/. Run after editing any src/ainiee_translate/*.py or
# skill/references/*.md.  SKILL.md is maintained separately in skill/ (local,
# absolute paths) and skills/ainiee-translate/ (portable) — not synced here.
set -euo pipefail
cd "$(dirname "$0")"

SCRIPTS_DST="skills/ainiee-translate/scripts/ainiee_translate"
REF_DST="skills/ainiee-translate/references"

mkdir -p "$SCRIPTS_DST" "$REF_DST"
rsync -a --delete --exclude='__pycache__' src/ainiee_translate/ "$SCRIPTS_DST/"
cp skill/references/translation_rules.md skill/references/style_guide_template.md \
   skill/references/parallel_translation.md skill/references/codex-tools.md "$REF_DST/"

# Drift guard: bundled scripts must equal src.
if ! diff -rq --exclude='__pycache__' src/ainiee_translate "$SCRIPTS_DST" >/dev/null; then
  echo "ERROR: bundled scripts differ from src/ after sync" >&2
  diff -rq --exclude='__pycache__' src/ainiee_translate "$SCRIPTS_DST" >&2 || true
  exit 1
fi
echo "synced src -> $SCRIPTS_DST  + references -> $REF_DST  (in sync ✓)"
