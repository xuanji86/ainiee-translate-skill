---
description: 切换当前项目使用的模块/提示词
argument-hint: [模块名]
allowed-tools: Bash
---
切换激活模块。给了名字 `$1` 就直接加载；否则先列出再问用户选哪个。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" PY="${AINIEE_PY:-python3}"
if [ -n "$1" ]; then
  $PY -m ainiee_translate.module load "$1" --work "${PWD}"
else
  $PY -m ainiee_translate.module list
fi
```

若只列出了模块，请用户挑一个，再用 `/ainiee-translate:switch-prompt <名字>` 加载（加载会把该模块的 `user_prompt.md`/`polish_prompt.md`/`glossary.locked.json` 拷进当前项目 `work/`）。
