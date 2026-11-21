---
description: 校验残留规则违规（空译、人名未保留、词汇表术语没按译法出现）
allowed-tools: Bash
---
对当前项目跑校验。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.verify work/cache.json work/glossary.locked.json
```

每个问题一行，总数在 stderr。头衔+人名、`X of Y`、助动词 Will、首字下沉已自动排除。
逐条核对：`empty_translation` 必修；`term_missing`（原文有词汇表术语、译文里没有它的任何译法）对照改；`name_not_preserved` 剩下的假阳性（城市/同名词）复核后存成基线：
`… verify work/cache.json work/glossary.locked.json --write-baseline work/verify_baseline.json`，之后加 `--baseline work/verify_baseline.json` 只看新增。
真问题用 `batch apply`（保住状态）修正后重跑。
