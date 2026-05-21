---
description: 从 AiNiee 配置/profile 构建并锁定工作词汇表
argument-hint: [--config PATH] [--analysis PATH]
allowed-tools: Bash, Read, Edit
---
构建锁定词汇表到当前项目 `work/`。

```bash
AINIEE_REPO="${AINIEE_REPO:?}" PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.glossary $ARGUMENTS --out work/glossary.locked.json
```

`--config` 缺省指 AiNiee 的 `config.json`（也可传一个 profile.json）；可选 `--analysis` 叠加项目分析缓存。
生成后**请用户人工复核并锁定**：人名是否保留原文、地名/术语译法、音译唯一性（详见技能 SKILL.md 步骤 3）。已激活模块时，词汇表通常随模块加载，无需重建。
