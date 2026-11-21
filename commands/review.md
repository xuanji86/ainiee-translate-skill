---
description: 对抗性审核（盲读 + 逐段对读台账 → Reviewer → 机械闸门 → Challenger；A/B 自动写回、C/D 给用户过目），去 AI 味 + 抓误译漏译
argument-hint: <起-止段号> [--target 140] [--benchmark <校对前备份>]
allowed-tools: Bash, Read, Write, Agent
context: fork
---
对 `work/cache.json` 的已译/已润色段跑一轮对抗性审核。范围 `$1`（必填，如 `438-719`；全书给 `1-<总段数>`），每组 `--target` 段（默认 140）。协议与闸门见技能 `references/adversarial_review.md`，各角色 prompt 见 `references/review_prompts.md`，分类见 `references/review_taxonomy.md`。

- **只有主控写 cache.json**；subagent 只写 `$REV` 下自己的文件。
- 角色都用 **Opus**，各是不同实例。同时最多 5 个在跑，完成一个补一个，某组落地就推进它的下一步。每个 agent 收齐后记一笔：`R log $C --stage <角色> --group gN --model <模型> --agent <名> --file <产物>`。
- 简写：`<PFX>` = `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" "${AINIEE_PY:?}"`；`R` = `<PFX> -m ainiee_translate.review`；`C` = `work/cache.json`；`G` = 全部组名 `g1 g2 …`；`REV` = `work/review`。第二轮起每条 `R` 命令加 `--run <名>`，`REV` = `work/review/<名>`（`config.json`、`EXAMPLES.md`、`read_ok.json` 仍在根目录）。

1. **准备**。`<PFX> -m ainiee_translate.state card $C --range $1` 看本范围已定的口径。`work/review/config.json` 不存在就按 adversarial_review.md 的格式写一份（没有裁定过的写法只留 `glossary_settled`）。全书性译法（种族名、集体智慧体代词、军衔体系、外语短句）按 `references/book_bible_template.md` §5 先问清用户。
2. **切组**。
   ```bash
   <PFX> -m ainiee_translate.batch split $C --stage review --range $1 --target 140 --prefix g --out-dir $REV/groups --context 3
   R rules $C G              # → rules_gN.json：各角色读它，不读整份 EXAMPLES.md
   R blind $C G              # → groups/blind_gN.json：只含中文
   R coverage $C G --todo    # → groups/read_gN.json：待对读的段，清单为空的组不派 Pair Reader
   ```
3. **盲读 + 对读**（同一波）。每组一个 Blind Reader → `flags_gN.jsonl`；一个 Pair Reader → `read_gN.jsonl`，每段一行结论。收齐后：
   ```bash
   R hints $C $REV/flags_g*.jsonl    # → hints_gN.json
   R coverage $C G                   # → pairs_gN.json + coverage.json
   ```
   `coverage` 退出码 1 = 有段没交结论或引文对不上：退回该组补齐，不带缺口往下走。
4. **Reviewer**。每组一个，读 `hints_gN.json` 和 `pairs_gN.json`（每条对读问题都要落成 A 类 finding），直接写 `findings_gN.jsonl`，自己跑 `R check $C gN` 到 OK。
5. **预闸门**。
   ```bash
   R pre $C $REV/findings_g*.jsonl                     # → findings_gN.pre.jsonl / rejected_gN.jsonl
   R segs --mode slim $C $REV/findings_g*.pre.jsonl    # → challenge_gN.jsonl + segs_gN.json；有盲读 flag 的 C 直接放行
   R inventory $C --range $1                           # → inventory.json
   ```
6. **Challenger + Consistency auditor**。每组一个 Challenger（读 `challenge_gN.jsonl`、`segs_gN.json`、`rules_gN.json`、`hints_gN.json` 和红线；读者绊过的 B/C 不许以「原译可通／偏好」否决）→ `verdicts_gN.jsonl`。全书一个 Consistency auditor（读 `inventory.json`）→ `findings_D.jsonl`。前 3–5 组收齐后 `R stats $C G` → `stats.md`，哪一格否决率 >2% 就把它移回送审。
7. **终闸门与写回**。
   ```bash
   R pre $C $REV/findings_D.jsonl
   R final $C G D            # → apply_gN.json（A/B）+ review_gN.md（C/D）
   <PFX> -m ainiee_translate.batch apply $C $REV/apply_g*.json --source adversarial
   R log $C --stage apply --group gN --file $REV/apply_gN.meta.json
   R coverage $C G           # unanswered = 对读报了问题、却没有任何 finding 的段
   R merge $C G D            # → review_ALL.md
   ```
   再跑 `verify` / `audit` / `scan --mode strays`，与审核前比对无新增，然后 `/ainiee-translate:export`。
8. **过目**。把 `review_ALL.md`、自动写回了哪些 id、`coverage.json` 的合计和 `unanswered` 交给用户。用户点名要改的：`R pick $C G D --ids …`（或 `--min-sev 2 --exclude X`）→ `apply_pick.json` → `batch apply … --source user`。用户说改坏的：写一条反向 apply 回退，并 `R log $C --stage revert`。

可选 `--benchmark <校对前备份>`：先在人工校对过的章节上打分（`batch split --stage review` 切该备份 + `R benchmark` + 跑 b 组 + `R score`），召回（剔除泄露段）≥60% 且 Challenger 精度 ≥80% 再铺其余章节。
