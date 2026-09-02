---
description: 导入 AiNiee profile（或 config.json）为一个可复用模块
argument-hint: <profile.json> <模块名>
allowed-tools: Bash
---
把 AiNiee profile `$1` 导入为模块 `$2`（提取语言、翻译/润色提示词、术语表、禁翻表、风格/世界观/角色）。

```bash
\
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?请先设 AINIEE_PY（AiNiee venv 的 python）}" \
  -m ainiee_translate.profile import --profile "$1" --name "$2"
```

随后用 `/ainiee-translate:module show $2` 检查导入结果。若模块已存在需覆盖，在命令后加 `--force`。
