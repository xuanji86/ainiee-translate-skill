---
description: 校验残留规则违规（漏译、人名未保留）
allowed-tools: Bash
---
对当前项目跑校验。

```bash
AINIEE_REPO="${AINIEE_REPO:?}" PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.verify work/cache.json work/glossary.locked.json
```

逐条核对：`empty_translation`（漏译）需修；`name_not_preserved` 常见**假阳性**（城市/同名词、含冠词别名）——确认是真问题再用 `batch write` 修正后重跑。
