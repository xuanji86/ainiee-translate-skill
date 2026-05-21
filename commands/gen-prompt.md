---
description: 让 agent 帮你起草翻译或润色提示词（AiNiee 风格），写进模块
argument-hint: <translate|polish> [模块名]
allowed-tools: Read, Write, Bash
context: fork
---
帮用户**起草**一份 `$1`（translate 或 polish）提示词，写入模块 `$2`（未给则问用户，或用当前激活模块）。

先读这两份作为「家规/风格基准」：
- `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/references/translation_rules.md`（AiNiee 原生原则：逐行、保留标记、忠实准确）
- `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/references/style_guide_template.md`

然后**访谈用户**（逐条问、给默认值）：题材/作品、源语言→目标语言、人名处理（保留原文/按表）、头衔/称谓如何摆放、对白与叙述风格、需保留原文的专名类别、是否有偏好示例。据此写出一份结构清晰的 AiNiee 风格提示词（含「逐行对应/保留标记/忠实准确」+ 用户的领域规则 + textarea 输出约定）。

写入：`~/.ainiee-translate/modules/<模块>/translate_prompt.md`（或 `polish_prompt.md`）。若模块不存在，先 `python -m ainiee_translate.module create <模块>`。完成后展示草稿首段并提示用户 `/ainiee-translate:show-prompt` 复核、`/ainiee-translate:switch-prompt` 启用。
