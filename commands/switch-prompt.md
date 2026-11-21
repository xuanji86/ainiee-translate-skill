---
description: 切换当前项目使用的模块/提示词
argument-hint: [模块名]
allowed-tools: Bash
---
给了模块名就加载（把它的 `user_prompt.md` / `polish_prompt.md` / `glossary.locked.json` 拷进当前项目 `work/`）；没给就列出模块，请用户挑一个再加载。

```bash
M() { PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "${AINIEE_PY:-python3}" -m ainiee_translate.module "$@"; }
NAME="$1"; if [ -n "$NAME" ]; then M load "$NAME" --work "$PWD"; else M list; fi
```
