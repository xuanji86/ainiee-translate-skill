---
description: 修复存量 epub 项目的行内标记与空格（旧解析器遗留）
allowed-tools: Bash
---
v1.4.1 及更早解析的 epub 丢了行内斜体/粗体，还把相邻片段粘成一个词。本命令从 `extra.original_html` 就地重建 `source_text`，不动译文与状态，不必重新解析。

```bash
R() { PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "${AINIEE_PY:?}" -m ainiee_translate.repair work/cache.json "$@"; }
R                 # 只预览
```

预览给用户看过、得到确认后才跑 `R --apply`（自动时间戳备份）。补回的标记不会自动进旧译文：再跑 `R --list-marked` 列出源文有标记、译文对不上的段，按 `references/translation_rules.md` 把 `<i>`/`<b>` 补进译文，用 `batch apply` 写回。
