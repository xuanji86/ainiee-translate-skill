---
description: 端到端翻译一本 epub/txt（解析→词汇表→翻译→导出→校验）
argument-hint: <输入文件> [模块名]
allowed-tools: Bash, Read, Edit, Task
context: fork
---
用 **ainiee-translate 技能** 把 `$1` 端到端翻译完。

前置：确认环境变量 `AINIEE_PY` 已设（`AINIEE_REPO` 可选，仅 PDF/Office）（脚本路径 `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts`，作为 `PYTHONPATH`）；未设则先按技能 SKILL.md「前置依赖与安装」提示用户设置，再继续。

步骤：
1. 准备项目工作目录（如 `~/<书名>-translate/{work,out}`）。
2. 若提供了模块名 `$2`：先 `python -m ainiee_translate.module load $2 --work <项目>`（把该模块的提示词+词汇表载入项目）。否则提示用户用 `/ainiee-translate:import-profile` 或 `/ainiee-translate:module create` 准备一个模块，或直接用 AiNiee 配置走默认流程。
3. 按技能 SKILL.md 的步骤执行：parse → glossary（如未由模块提供）→ 读取用户提示词（模块的 `work/user_prompt.md`）→ 模式 A 抽样确认 → 逐章翻译（大书可用并行）→ export → verify。
4. 翻译规则遵循：AiNiee 原生原则（references/translation_rules.md）＋ 模块/用户提示词 ＋ 锁定词汇表。

完成后报告进度与产物路径。
