---
description: 把翻译好的缓存导出为成品 epub/txt
argument-hint: <原始输入文件>
allowed-tools: Bash
---
导出当前项目的成品（保留原书结构与标签；已润色的段落自动用润色文本）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.export --cache work/cache.json --output out/ --input "$1" --finalize
```

`--finalize` 读 `work/export.json`（书名、`zh-CN`、**固定 identifier**、交付路径 `deliver`；首次导出自动生成 identifier，之后不变），
改元数据、查 XML/链接/锚点、核对每个已译段都在成品里，再复制到 `deliver`。第一次可带 `--title … --name … --deliver …` 写进配置。
完成后报告成品路径、核对段数与 warnings（源书自带的坏链接只警告）。
