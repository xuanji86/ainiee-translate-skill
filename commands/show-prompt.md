---
description: 查看模块的提示词与词汇表摘要
argument-hint: [模块名]
allowed-tools: Bash, Read
---
显示模块 `$1`（未给则用当前激活模块）的元数据、术语/角色/禁翻计数，以及翻译/润色提示词开头。

```bash
PY="${AINIEE_PY:-python3}"; PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts"
NAME="$1"; [ -z "$NAME" ] && NAME=$(PYTHONPATH="$PYTHONPATH" $PY -c "import json,os;p=os.path.expanduser(os.environ.get('AINIEE_TRANSLATE_HOME','~/.ainiee-translate')+'/active.json');print(json.load(open(p)).get('active_module','')) if os.path.exists(p) else print('')")
PYTHONPATH="$PYTHONPATH" $PY -m ainiee_translate.module show "$NAME"
echo "--- translate_prompt.md ---"; head -8 ~/.ainiee-translate/modules/"$NAME"/translate_prompt.md 2>/dev/null
echo "--- polish_prompt.md ---";    head -8 ~/.ainiee-translate/modules/"$NAME"/polish_prompt.md 2>/dev/null || echo "(无润色提示词)"
```
