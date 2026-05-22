---
description: 发现表外被音译/丢失的专名 + OCR 粘连词（补 verify 盲区）
allowed-tools: Bash
---
对当前项目跑发现型扫描（补 `verify` 的盲区：verify 只查锁定表内的名字、且二元在/不在）。模式 `$1`（`all`|`discover`|`terms`|`strays`|`merges`，默认 `all`）。

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:?}" -m ainiee_translate.scan work/cache.json --locked work/glossary.locked.json --mode "${1:-all}"
```

读法：
- `discover.inconsistent`（**高置信，优先改**）：同名时而保留英文、时而消失（单点滑落 / 同段对错并存）。
- `discover.never_preserved`（**人眼判断**）：从不以英文出现，含「全程被音译的真名」与「合法意译的术语」两类，挑出真名。
- `untranslated_terms`：有中文译名的术语被漏成英文（`Starfleet` 漏译）。
- `stray_latin`（**复查列表**）：译文里出现、原文没有的英文 token（幻觉错名 `Vic`/`Sam`/`Lt`）；含粘连词/术语噪声，眼判。
- `merges`：原文丢空格的粘连词（`thenaiskosfragment`、`speciesDraco`）。

确认的真名/地名补进 `glossary.locked.json` 的 `characters`、保留英文的通名补进 `terms`（`keep_source:true`），再跑 `verify`。改已润色段用 `polish write` 保住状态。
