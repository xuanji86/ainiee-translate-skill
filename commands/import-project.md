---
description: 导入已有项目（AiNiee 缓存或既有 cache.json）以继续翻译/润色/校验/导出
argument-hint: [list | <AinieeCacheData.json 路径或 AiNiee 项目ID> <项目目录>]
allowed-tools: Bash
---
把一个**已有的翻译缓存**导入到项目目录的 `work/cache.json`，之后可无缝续翻、润色、校验或重新导出。源可以是 AiNiee 的工程缓存（`AinieeCacheData.json`），也可以是另一个 ainiee-translate 项目的 `cache.json`（两者同为 CacheProject 格式）。

**先列出可导入的 AiNiee 工程**（无参数或 `$1` 为 `list` 时）：

```bash
\
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?请先设 AINIEE_PY（AiNiee venv 的 python）}" \
  -m ainiee_translate.project list
```

输出每个工程的 `project_id`、`project_name`、`input_path`（原书）及各状态计数（未译/已译/已润色/已排除）。

**导入**：`$1` = AiNiee 项目ID（来自上面的 `project_id`）或 `AinieeCacheData.json` 路径；`$2` = 目标项目目录。项目ID 用 `--ainiee`，文件路径用 `--cache`：

```bash
\
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" \
  -m ainiee_translate.project import --ainiee "$1" --work "$2"
# 或：--cache "/path/to/AinieeCacheData.json" --work "$2"
```

导入会把缓存规范化进 `$2/work/cache.json`（已存在则先时间戳备份），并打印 `input_path` 与状态计数。**之后**：
- 还有未译段 → `/ainiee-translate:translate`（或 `batch read` 续翻）。
- 已译待润色 → `/ainiee-translate:polish`。
- 直接出成品 → `/ainiee-translate:export <input_path 指向的原书>`。
- 查残留问题 → `/ainiee-translate:verify`。
