---
description: 把翻译好的缓存导出为成品 epub/txt
argument-hint: <原始输入文件>
allowed-tools: Bash
---
导出当前项目的成品（保留原书结构与标签；已润色的段落自动用润色文本）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.export --cache work/cache.json --output out/ --input "$1"
```

完成后报告 `out/` 下的成品路径。
