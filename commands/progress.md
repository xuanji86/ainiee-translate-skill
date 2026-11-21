---
description: 显示翻译进度面板（全书进度 + 每个并行组的状态/速率/卡死/可写回）
argument-hint: [--line | --json]
allowed-tools: Bash
---
渲染一次当前项目的进度面板。并行时每组一行：`running` / `stalled`（超 3 分钟没动）/ `ready`（可写回）/ `needs_fix`（有空译或标记不匹配）/ `written`。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.progress work/cache.json $ARGUMENTS   # 没给参数就用 --once
```

要持续盯盘：把上面命令的 `--once` 换成 `--watch`（或 `--serve 8765 --open` 起网页看板），**填好两个变量的实际值和 cache.json 的绝对路径后交给用户**在自己的终端里跑——在会话里跑会阻塞。
