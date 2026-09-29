---
description: 对抗性审核（Reviewer 找问题 → 机械闸门 → Challenger 否决 → A/B 自动写回、C/D 给用户过目），去 AI 味 + 抓润色漏掉的误译
argument-hint: <起-止段号> [--target 140] [--benchmark <校对前备份>]
allowed-tools: Bash, Read, Write, Agent
context: fork
---
对当前项目 `work/cache.json` 的已译/已润色段跑一轮对抗性审核。范围 `$1`（如 `438-719`，必填；全书就给 `1-<总段数>`），
每组 `--target` 段（默认 140）。完整协议与闸门语义见技能 `references/adversarial_review.md`，prompt 模板见 `references/review_prompts.md`，
分类标准见 `references/review_taxonomy.md`。**只有主控写 cache.json；subagent 只写 `work/review/` 下自己的文件。**

`<PFX>` = `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "${AINIEE_PY:?}"`；`REV=work/review`。

1. **准备**：若 `work/review/config.json` 不存在，从 `work/POLISH_REDLINES.md`/词汇表整理红线写一份（格式见 adversarial_review.md；没有裁定过的写法就只留 `glossary_settled`）。切组：
   ```bash
   <PFX> -m ainiee_translate.batch split work/cache.json --stage review --range $1 --target ${TARGET:-140} --prefix g --out-dir $REV/groups --context 3
   ```
1.5 **盲读**：`<PFX> -m ainiee_translate.review blind work/cache.json g1 g2 …` 生成只含中文的 `groups/blind_gN.json`；每组派一个 **Opus** Blind Reader（review_prompts.md 模板，不给源文），产出 `$REV/flags_gN.jsonl`；`review hints work/cache.json $REV/flags_g*.jsonl` → `hints_gN.json`（校验 quote、挂回源文）。项目若有 `$REV/EXAMPLES.md`（用户改过的病例），三个角色都要读。
2. **Wave 1**：每组派一个 **Opus** Reviewer（同一条消息并发，一波 ≤5 个），prompt 用 review_prompts.md 的 Reviewer 模板填空，产出 `$REV/findings_gN.jsonl`。每个收齐就 `review log --stage reviewer --group gN --model <模型> --agent <名> --file …`。
3. **预闸门**：`<PFX> -m ainiee_translate.review pre work/cache.json $REV/findings_g*.jsonl` → `findings_gN.pre.jsonl` / `rejected_gN.jsonl`；`review segs work/cache.json $REV/findings_g*.pre.jsonl` → `segs_gN.json`；`review inventory work/cache.json --range $1` → `inventory.json`。
4. **Wave 2**：每组一个 **Opus** Challenger（另一实例，读 findings.pre + segs + 红线 + EXAMPLES.md + hints_gN.json；读者绊过的地方不许以「原译可通／偏好」否决）+ 一个 Consistency auditor（读 inventory.json，产出 `findings_D.jsonl`）。同样 `review log`。
5. **终闸门**：`review pre work/cache.json $REV/findings_D.jsonl`，然后 `<PFX> -m ainiee_translate.review final work/cache.json g1 g2 … D` → `apply_gN.json`（A/B）+ `review_gN.md`（C/D）。
6. **写回 + 复核 + 导出**：`<PFX> -m ainiee_translate.polish write work/cache.json $REV/apply_g*.json`；`review log --stage apply --group gN --file $REV/apply_gN.meta.json`；跑 `verify` / `audit` / `scan --mode strays` 与审核前比对无新增；`/ainiee-translate:export` 重新导出。
7. **过目**：`<PFX> -m ainiee_translate.review merge work/cache.json g1 g2 … D` → `review_ALL.md`，把表给用户（附自动写回了哪些 id）。用户点名的 id：`review pick work/cache.json g1 g2 … D --ids …` → `apply_pick.json` → `polish write`；用户说改坏的：写一条反向 apply 回退并 `review log --stage revert`。

可选 `--benchmark <校对前备份>`：先在人工校对过的章节上打分（`batch split --stage review` 切该备份 + `review benchmark` + 跑 b 组 + `review score`），召回（剔除泄露段）≥60% 且 Challenger 精度 ≥80% 再铺其余章节。
