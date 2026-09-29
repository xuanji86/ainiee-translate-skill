# 对抗性审核（去 AI 味 / 抓误译的第二道工序）

润色 pass 只改「表达」，且同一个模型自己审自己漏得多：Warpath 实测 Sonnet 润色（改写率 5.6%）之后，人工逐句校
ch2–5 仍抓出 ~80 段问题——几乎全是词法/搭配层（非词、固定词取错义、习语直译、句子重心移位、「的」堆叠）和真误译
（`So?` 译成「是吗？」、`I've got her` 的 her 指船）。

本工序把**找问题**和**否决问题**拆给两个互不通气的 agent，主控只做机械闸门与写回：

| 角色 | 模型 | 读 | 写 | 激励 |
|---|---|---|---|---|
| **Blind Reader** | Opus | **只读中文**（`groups/blind_X.json`）+ 分类清单 + `EXAMPLES.md` + 红线 | `flags_X.jsonl` | **奖励召回**：读者读着绊一下就标；不看原文，不必给改法 |
| **Reviewer** | Opus | 本组源文+现译、`hints_X.json`（盲读标记+源文）、分类清单、`EXAMPLES.md`、红线/风格指南、前几段语境 | `findings_X.jsonl` | **奖励召回**：每条 flag 都要处理；用词病改词，句式病**整句重写**；每条引用源文证据 |
| **Challenger** | Opus（另一实例） | `challenge_X.jsonl` + 涉及段 + 红线 + `rules_X.json`/`EXAMPLES.md` + 盲读标记 | `verdicts_X.jsonl` | **奖励否决**：违反红线 / 引入新错 → reject；「原译没错／偏好」只在读者没绊过时才能用；可 amend |
| **Consistency auditor** | Opus ×1 | `review inventory` 生成的术语清单 | `findings_D.jsonl` | 只判「同一英文词该不该一个译法」 |
| **主控** | — | 全部产物 | `apply_X.json`、`review_X.md`、`review_log.jsonl` | `review pre/final` 闸门 → A/B `polish write`，C/D 列给用户 |

Warpath 试点（ch2–5 人工校对做基准）：召回 71–75%（剔除答案泄露后）、Challenger 精度 87–91%，
且 Reviewer 报出而人工没改的段抽查 14/16 是人工漏掉的真问题。Challenger 否掉的典型：「护盾已落」（与「升起护盾」
成对）、「在 Taran'atar **闻**来」（Jem'Hadar 靠嗅觉判人）、「失压体验」（作者冷幽默）——单 agent 审校会把这些改坏。

**盲读基准（v1.11，同书 ch6–10）**：用户在阅读器里逐句读出并亲手改过的 27 段，旧 Reviewer（带源文）覆盖 19 段，
只读中文的 Blind Reader 覆盖 24 段，且标的就是用户改的那句；仍漏的 3 段全是舰桥口令／技术动词。所以盲读放在 Reviewer 之前。

## 分级复核与 token 预算（v1.13，Destiny 合集实测）

Destiny 合集 71 组 × 三角色共 2250 万 subagent token（Reviewer 885 万 / Challenger 696 万 / Blind 541 万）。逐条统计
（`review stats`）：

| finding | 送 Challenger | 被否 | 否决率 |
|---|---|---|---|
| 有 Blind flag 佐证 | 5034 | 5 | **0.1%** |
| 无 flag（Reviewer 自己加的） | 2323 | 152 | 6.5%（C/sev1 达 22.6%） |

Blind flag 93% 被 Reviewer 落成 finding，69% 的 finding 来自 flag——**盲读是召回主力，别砍**；该省的是 Challenger
对「读者已绊过、Reviewer 又对着源文确认过」的条目的复核：两个互不通气的实例已经独立同意了。因此：

- `review segs --tier`：有 flag 且 severity < `--min-sev`（默认 3）的 finding 直接写 `verdicts_X.auto.jsonl`（accept），
  其余（无 flag、severity 3、`latin_change`、`redline_waiver`）+ 按 id 哈希抽的 `--sample`（默认 5%）写 `challenge_X.jsonl`
  给 Challenger。`review final` 先读 auto 再用真 verdict 覆盖。Destiny 回放：7357 → **2745** 条送审（−63%），
  自动放行里历史上最多漏 5 条坏改动。
- 不加 `--tier` 时 `challenge_X.jsonl` = 全部 findings，行为同旧版。
- 前 3–5 组跑完就 `review stats`；某一格否决率 > 2% 就把它移回送审（调 `--min-sev` 或不用 `--tier`）。
- `review rules gN`：从 `glossary.locked.json` 与 `EXAMPLES.md` 抽出与本组源文相关的条目 → `rules_gN.json`，agent 读它而不是
  整份裁定文件。裁定文件越长越值：纯口味病例（无英文专名）总是保留，专名裁定只给出现它的组。
- 模型：Reviewer 用 Opus（Sonnet 召回明显低）；Challenger 只审无 flag 的少数条目后，每组负载约为原来的 1/3，可以并两组给一个实例。
  Blind Reader / Challenger 换小模型**未做基准**，要换先在人工校过的章节上 `benchmark/score`。
- 组大小：`--target 140` 是按 Reviewer 上下文定的，别为省固定开销加大——Reviewer 的输出（builder 里的整句重写）才是大头。

**审前先定政策**：全书性的译法选择（种族名音译与否、集体智慧体的代词、军衔体系、外语短句）必须在审校开工前定完，
见 `book_bible_template.md` §5。审完再定 = 再派一轮 agent 全书返工；能用正则落实的一律交给机械脚本，不要让 Reviewer 逐组发现。

**红线豁免**：红线条目写成 `{"re": "上校|舰长|中校", "waivable": true}` 时，finding 带 `"redline_waiver": "源文 Lieutenant Commander，现译中校"`
可以改它；这种 finding 永远送 Challenger，不会自动放行。Destiny 里正确的军衔修正全被「改动即拒」拦下，只能主控强写。

## 缺陷分类与 finding 格式

分类 A 误译 / B 目标语硬伤 / C 翻译腔 / D 跨段不一致 / E 红线（禁区），十二条 AI 味清单，全在
[`review_taxonomy.md`](review_taxonomy.md)。finding 一行一条 JSONL：

```json
{"id":"g1-017","text_index":452,"category":"B","severity":2,
 "offending":"当即拍了主意","source_evidence":"made a snap decision",
 "proposed":"当机立断","reason":"「拍主意」不成词","confidence":0.9}
```

- `offending` 必须在该段现译里**恰好出现一次**；`proposed` 只替换它。整段重写一律拒。
- `proposed` 不得增删 `<i>/<b>`；不得改动任何拉丁字母 token——A 类补回漏译专名除外，需 `"latin_change":true`，且**转人工**不自动应用。
- `severity`：3 意思错/读不通，2 明显别扭，1 可改可不改。

verdict：`{"id":…,"verdict":"accept|reject|amend","amended":"…","reason":"…"}`。Challenger 在 reason 里写
「降为 C」「应为 B」之类，`review final` 会按它改类别；写 `severity 2 改为 1` 会改严重度。

## 目录（默认 `<PROJ>/work/review/`）

```
review/
  config.json          项目规则（见下）；没有也能跑（只用词汇表 dst 当定稿术语）
  groups/grp_X_src.json  batch split --stage review 的产物（含 translated_text）+ grp_X_ctx.json
  findings_X.jsonl     Reviewer 产出 → findings_X.pre.jsonl（过闸门）/ rejected_X.jsonl
  challenge_X.jsonl    送 Challenger 的 findings（--tier 时只是一部分）；segs_X.json 为其涉及的段
  verdicts_X.auto.jsonl  --tier 自动放行的 accept（final 时被真 verdict 覆盖）
  verdicts_X.jsonl     Challenger 产出
  rules_X.json         本组相关的词汇表条目 + 裁定条目（review rules）
  stats.md             各工序产出率（review stats）
  apply_X.json(+.meta) A/B 类，直接喂 polish write；review_X.md / review_ALL.md 给用户过目
  inventory.json       术语清单（Consistency auditor 的唯一输入）
  benchmark.json / scores.md   基准与打分（只在有人工校对过的章节上做）
  review_log.jsonl     留痕：哪个 agent、什么模型、哪份文件、应用了哪些 id
```

### config.json

```json
{"redline": ["Jem[’']Hadar|詹哈达", "[A-Za-z]象限", "</i> 号", "上校|舰长|中校|指挥官", "隐形|遁形"],
 "settled": ["Berzel 平原", "鉴证", "突击队"],
 "glossary_settled": true,
 "forbid": "[「」\"]",
 "term_only": [["Kira 舰长", "Kira 上校"], ["遁形", "隐形"]],
 "norm": [["舰长|上校", "⟨R1⟩"]],
 "leak_files": ["EXAMPLES.md"]}
```

- `redline`：**改动即拒，提及允许**——`offending` 与 `proposed` 里各正则命中的多重集必须相同。放用户裁定过的
  「看似不一致其实故意」的写法（并存的英/中译名、无空格的象限、军衔写法、舰名带号…）。第一版用「提及即拒」误杀了
  `竖发→刺猬似短发`（子串里带着没动的「安全官」），别走回头路。
- `settled`：定稿术语，**只许加不许删**——改向定稿是对的（数据恢复队→组），从 offending 里删掉不行。
  `glossary_settled`（默认 true）把词汇表所有 `dst` 也当定稿术语；语境依赖的词条（`crew` 舰上「船员」/站上「站上人员」）
  会因此误拒一两条，看 `rejected_X.jsonl` 里的 `E_settled_removed` 手工放行即可。
- `forbid`：绝不允许引入的字符（默认「」和 ASCII 引号）。`soft_block`：不得新增的 audit 软问题（默认半角标点/「」/…）。
- `term_only` / `norm`：只给 `benchmark` 用——人工校对期间顺手做的批量定名替换（舰长→上校）不算「实质修改」，
  两边文本套同一映射后相同就剔出分母。
- `leak_files`：项目里收录了本书病例的清单文件；`score` 会把旧译含这些病例的段标为「答案泄露」另算一行。

## 流程

`<PFX>` = `PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY"`；`<PROJ>` 项目目录；`REV=<PROJ>/work/review`。

```bash
# 0. 切组：已译/已润色段都审；--range 限定章节；--prefix 让组名区分（g=真审核，b=基准）
<PFX> -m ainiee_translate.batch split <PROJ>/work/cache.json --stage review --range 438-719 \
      --target 140 --prefix g --out-dir $REV/groups --context 3
# 0.2 每组相关的词汇表/裁定切片（agent 读 rules_gN.json）
<PFX> -m ainiee_translate.review rules <PROJ>/work/cache.json g1 g2
# 0.5 盲读：去掉源文，每组一个 Blind Reader（Opus 并发）→ flags_gN.jsonl；校验并挂回源文 → hints_gN.json
<PFX> -m ainiee_translate.review blind <PROJ>/work/cache.json g1 g2
<PFX> -m ainiee_translate.review hints <PROJ>/work/cache.json $REV/flags_g1.jsonl $REV/flags_g2.jsonl
# 1. Wave 1：每组一个 Reviewer（Opus，同一条消息并发；读 hints_gN.json；prompt 见 review_prompts.md）
<PFX> -m ainiee_translate.review log <PROJ>/work/cache.json --stage reviewer --group g1 --model claude-opus-5 --agent rev-g1 --file $REV/findings_g1.jsonl
# 2. 预闸门 + 抽 Challenger 要看的段
<PFX> -m ainiee_translate.review pre  <PROJ>/work/cache.json $REV/findings_g1.jsonl $REV/findings_g2.jsonl
<PFX> -m ainiee_translate.review segs <PROJ>/work/cache.json --tier $REV/findings_g1.pre.jsonl $REV/findings_g2.pre.jsonl
<PFX> -m ainiee_translate.review inventory <PROJ>/work/cache.json --range 438-719      # → inventory.json
# 3. Wave 2：每组一个 Challenger（读 challenge_gN.jsonl）+ 一个 Consistency auditor（并发）
#    前几组落地后：<PFX> -m ainiee_translate.review stats <PROJ>/work/cache.json g1 g2 …   # → stats.md，看分级是否安全
# 4. 终闸门：合并 verdicts → apply_X.json（A/B）+ review_X.md（C/D）
<PFX> -m ainiee_translate.review pre   <PROJ>/work/cache.json $REV/findings_D.jsonl
<PFX> -m ainiee_translate.review final <PROJ>/work/cache.json g1 g2 D
# 5. 写回 A/B（只有主控写 cache）、复核、导出
<PFX> -m ainiee_translate.polish write <PROJ>/work/cache.json $REV/apply_g1.json $REV/apply_g2.json
<PFX> -m ainiee_translate.review log <PROJ>/work/cache.json --stage apply --group g1 --file $REV/apply_g1.meta.json
<PFX> -m ainiee_translate.verify <PROJ>/work/cache.json <PROJ>/work/glossary.locked.json
<PFX> -m ainiee_translate.audit  <PROJ>/work/cache.json
# 6. C/D 合并成一张表给用户；用户点名的 id 用 pick 生成 apply 文件再 polish write
<PFX> -m ainiee_translate.review merge <PROJ>/work/cache.json g1 g2 D            # → review_ALL.md
<PFX> -m ainiee_translate.review pick  <PROJ>/work/cache.json g1 g2 D --ids g1-012 g1-043 D-001   # → apply_pick.json
<PFX> -m ainiee_translate.polish write <PROJ>/work/cache.json $REV/apply_pick.json
```

闸门顺序（`review pre` 逐条）：必填字段 → 类别 ∈ A–D → `offending` 恰好一次 → 红线/定稿/禁字 →
`<i>/<b>` 成对（`audit.lint_pair`）→ 不新增 `soft_block` 软问题 → 拉丁 token 多重集不变（除 A+`latin_change` → 转人工）。
`review final`：reject 丢弃；amend 用 `amended` 重过闸门；同一段多条按顺序叠加到同一份文本再查一次标记；
无 `verdicts_X.jsonl` 的组（如 D）全部进过目表。

**铁律**：subagent 只写 `$REV/` 下自己的文件，不碰 `cache.json`、不跑 `ainiee_translate` 任何写命令。

## 先试点再铺全书

有人工校对过的章节就拿来当基准，用当时的备份重建旧译：

```bash
<PFX> -m ainiee_translate.batch split <PROJ>/work/cache.json.bak.<校对前> --stage review --range 128-437 --prefix b --out-dir $REV/groups
<PFX> -m ainiee_translate.review benchmark <PROJ>/work/cache.json --baseline <PROJ>/work/cache.json.bak.<校对前> --range 128-437
# … Reviewer/Challenger 跑 b 组（只打分，永不写回）…
<PFX> -m ainiee_translate.review score <PROJ>/work/cache.json b1 b2
```

判定门：**召回（剔除泄露段）≥ 60% 且 Challenger 精度 ≥ 80%** → 铺全书；否则先改清单/prompt。
`score` 里「报了但人工没改」的段要抽读——Warpath 里这一类多数是人工漏掉的真问题，人工基准本身有缺口。

- 备份轮转：`cache.json.bak.*` 默认只留 10 个，人工校对开始前**手动**复制一份 `cache.json.pre_review`（非 `.bak.` 后缀不会被清）。
- 组大小 140 段左右；一波 5 个 Opus 顺畅。Reviewer ~125k、Blind ~75k token 一组；Challenger 全审 ~100k，`--tier` 后约 1/3。
- 清单里的病例会泄露答案：项目病例放 `EXAMPLES.md`（config `leak_files`），基准打分看「剔除泄露段」那行。
- C/D 过目表按 severity 排序，severity 1 默认不改；用户否掉的自动应用项，用 `pick` 的反向（把 `offending`/`proposed` 对调写一条 finding）或直接手写 apply 文件回退，并 `review log --stage revert`。
