---
description: 显示翻译进度面板（全书进度 + 每个并行组的状态/速率/卡死/可写回）
argument-hint: [--line | --json]
allowed-tools: Bash
---
对当前项目 `work/cache.json` 渲染一次进度面板。多 agent 并行时每组一行：`running`（在译）/ `stalled`（超 3 分钟没动）/ `ready`（译完可写回）/ `needs_fix`（译完但有空译或标记不匹配）/ `written`（已写回）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.progress work/cache.json ${ARGUMENTS:---once}
```

要**持续**盯盘，在另一个终端分屏跑（不要在 Claude Code 会话里跑，它会阻塞）：

```bash
PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY" -m ainiee_translate.progress ~/<项目>/work/cache.json --watch
```

它每 2 秒刷新，并把一行摘要写到 `~/.ainiee-translate/progress.line`，statusline 会自动显示（见 SKILL.md 附录 D）。
