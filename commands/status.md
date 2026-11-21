---
description: 查看当前项目状态（已绑模块 / 各状态段数 / 下一步）
allowed-tools: Bash
---
报告当前项目（`./work/`）状态。

```bash
cat work/active_module.json 2>/dev/null || echo "(未绑定模块)"; echo
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.cache stats work/cache.json
```

按各状态段数判断下一步：有 `untranslated` → `/ainiee-translate:translate`；全是 `translated` 且 `work/polish_prompt.md` 非空 → `/ainiee-translate:polish`；否则 → `/ainiee-translate:export`。
