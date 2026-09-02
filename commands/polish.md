---
description: 对已翻译文本跑润色 pass（按模块的润色提示词二次加工）
argument-hint: [批大小]
allowed-tools: Bash, Read, Edit
context: fork
---
对当前项目 `work/cache.json` 的已译文本做润色（状态 TRANSLATED→POLISHED，可断点续跑）。

前置：`work/polish_prompt.md` 必须存在（由模块提供或 `/ainiee-translate:gen-prompt polish` 生成）；否则告知用户「当前模块无润色提示词」并停止。设好 `AINIEE_PY`/`PYTHONPATH`（`AINIEE_REPO` 仅 PDF/Office 回退才需要）。

循环直到 `read-translated` 返回 `[]`：
1. `<PFX> -m ainiee_translate.batch read-translated work/cache.json --size ${1:-100}` → 得到 `{text_index, source_text, translated_text}` 数组。
2. agent 按 `work/polish_prompt.md` + 锁定词汇表，对每段的 `translated_text` 做润色（**保持逐行 1:1、保留标记、人名/术语按词汇表**），写成 `work/polished_NNN.json`（`{text_index, polished_text}`）。
3. `<PFX> -m ainiee_translate.polish write work/cache.json work/polished_NNN.json`（写回并置 POLISHED）。

大书可并行：`batch split --stage polish --out-dir work/par` 切组 → subagent 各写 `par/polished_N.jsonl` → `batch validate` → `polish write work/cache.json work/par/polished_*.jsonl` 一次写回（详见技能 references/parallel_translation.md「润色也能并行」）。`/ainiee-translate:progress` 会显示润色进度。

`<PFX>` = `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "$AINIEE_PY"`。完成后可 `/ainiee-translate:export` 导出（导出读 final_text，自动用润色后的文本）。
