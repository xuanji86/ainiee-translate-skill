---
description: 查看模块的提示词与词汇表摘要
argument-hint: [模块名]
allowed-tools: Bash
---
显示模块 `$1`（未给则用当前激活模块）的元数据、术语/角色/禁翻计数，以及两份提示词的开头。

```bash
H="${AINIEE_TRANSLATE_HOME:-$HOME/.ainiee-translate}"
NAME="$1"; NAME="${NAME:-$(sed -n 's/.*"active_module": *"\([^"]*\)".*/\1/p' "$H/active.json" 2>/dev/null)}"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "${AINIEE_PY:-python3}" -m ainiee_translate.module show "${NAME:?没有激活模块，请给模块名}"
head -8 "$H/modules/$NAME/translate_prompt.md" "$H/modules/$NAME/polish_prompt.md" 2>/dev/null
```
