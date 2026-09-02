---
description: 机械体检已译/已润色段（空译、标记不匹配、半角标点、「」、长度比异常、未译原样搬运）
argument-hint: [--allow-tag-mismatch]
allowed-tools: Bash
---
对当前项目 `work/cache.json` 跑机械体检（不用模型、不用词汇表）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.audit work/cache.json --out work/audit.json $ARGUMENTS
```

读法：`empty` / `tag_mismatch` 是硬伤（写回闸门本会拒收，出现即说明是老数据或 `--force` 写的），必修；
其余是风格警告（`halfwidth_punct`、`cjk_corner_quote`、`ascii_ellipsis`、`inner_space`、`identical_untranslated`、
`too_short`/`too_long`），按 `work/audit.json` 里的段号抽查后用 `batch write`（已译）/`polish write`（已润色）修正。
