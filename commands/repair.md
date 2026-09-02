---
description: 修复存量 epub 项目的行内标记与空格（旧解析器遗留）
allowed-tools: Bash
---
v1.4.1 及更早版本的 epub 解析用 `soup.get_text(strip=True)`：**丢掉行内斜体/粗体**，
并对每个文本片段单独 strip 再无缝拼接，产生系统性粘连词
（`her <i>blade</i> fell` → `herbladefell`）。解析层已修复——本命令让**存量项目**
不必重新解析（那会丢掉已有译文）即可从 `extra.original_html` 就地重建 `source_text`。

先预览：

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.repair work/cache.json
```

确认无误后写入（自动时间戳备份）：

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.repair work/cache.json --apply
```

只改 `source_text`，不动译文与状态。**补回的标记不会自动进旧译文**，所以接着列出
需要重做的段：

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.repair work/cache.json --list-marked
```

对列出的每段，按 `references/translation_rules.md` 把 `<i>`/`<b>` 标记补进译文
（包住中文里对应的那一段），再用 `batch write`（status=1 已译）或
`polish write`（status=2 已润色，保住状态）写回。
