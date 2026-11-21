---
description: 导入已有项目（AiNiee 缓存或既有 cache.json）以继续翻译/润色/校验/导出
argument-hint: [list | <AinieeCacheData.json 路径或 AiNiee 项目ID> <项目目录>]
allowed-tools: Bash
---
把已有的翻译缓存（AiNiee 的 `AinieeCacheData.json`，或另一个项目的 `cache.json`）导入 `$2/work/cache.json`（已存在则先时间戳备份）。

无参数或 `$1` 为 `list`：列出可导入的 AiNiee 工程（`project_id`、原书路径、各状态段数）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.project list
```

导入：`$1` 是项目ID 用 `--ainiee`，是文件路径用 `--cache`。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.project import --ainiee "$1" --work "$2"
```

导入后报告 `input_path` 与状态段数，下一步见 `/ainiee-translate:status`。
