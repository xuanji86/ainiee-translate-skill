# 多 agent 并行翻译（大书加速）

把步骤 5 的逐章串行翻译，改为**多个 subagent 同时翻译不同章节范围**，墙钟时间≈最慢的那个 agent。
编排的每一步都有确定性命令：`batch split` 分组、`glossary filter` 瘦身词汇表、`batch validate` 验收、
`batch write` 一次串行写回多组。主控不再手写任何 Python heredoc。

**占位符**：`<PFX>` = `PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY"`；`<PROJ>` = 本翻译项目目录（含 `work/`）；
`<SKILL>` = 本技能目录 `$SKILL_DIR`（插件安装时为 `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate`）。

> **Codex**：下文的「subagent / Agent 工具」读作 `spawn_agent`（需在 `~/.codex/config.toml` 设 `[features] multi_agent = true`），
> 结果用 `wait` 收、`close_agent` 释放；完整工具名对照见 `references/codex-tools.md`。铁律不变。

## 何时用

- 书很大（数百段以上）、章节之间相互独立。
- **风格已锁定**：先用步骤 4 的模式 A 译完约 1 章、经用户确认，再并行。否则各 agent 风格会发散。
- 锁定词汇表 + 用户提示词已就位。并行时新实体一律「保留原文 + 记录」。

## 唯一铁律：subagent 绝不写 cache.json

`batch write` 是「读改写」整个文件。并发写会相互覆盖。`write` 现在带文件锁与写回闸门，
但锁只保证不损坏，**不保证语义正确**——仍然只让主控写。

```
✗ 让每个 subagent 自己 batch write   —— 禁止
✓ subagent 只产出 /tmp/trans_N.jsonl；主控 validate 后一次 write 全部  —— 正确
```

**架构：**
```
主控：batch split → glossary filter（每组）→ 写 STYLE_GUIDE.md（+ 可选 BOOK_BIBLE.md）
  ├─ agent1 (grp_1)  读 style+bible+g1.json+rules+ctx → 边译边 append trans_1.jsonl + newterms_1.txt
  ├─ agent2 (grp_2)  ……（并发，互不写共享文件）
  └─ agentN ……
主控：batch validate 每组 → 不过的只重派那一组 → batch write 一次全部 → merge-newterms → verify + scan → export
```

## 步骤

### 1. 分组 + 抽取源文（一条命令）

```bash
<PFX> -m ainiee_translate.batch split <PROJ>/work/cache.json \
  --target 300 --out-dir <PROJ>/work/par --context 20
```

- 只取 `status=0` 段；按 epub spine 文件（`extra.item_id`）**在章节边界切**，贪心凑到 `--target` 段左右；
  单章超过 1.5×target 自行切块；尾巴不足 0.4×target 并入前一组。非 epub 无章节信息时按定长切。
- 每组产出 `par/grp_N_src.json`（`{text_index, source_text}` 数组，subagent 的输入）和
  `par/grp_N_ctx.json`（该组之前**最近 20 段已译**的原文+译文，只读上下文：章首的代词性别、说话人、上一章结尾靠它；
  紧挨着的前一组若也待译，会自动往前找到有译文的段）。
- stdout 是分组计划（组号、段数、index 范围、章节 id）。

**并发数怎么定**：组数 = 同时跑的 agent 数。约束不是固定上限而是速率预算：**~300 段一组、同时 5–8 个**起步，
限流就回退；组数多于并发数就**分波**发（发一批 → 收完 → 下一批）。别一章一个：章长不均会空等最长那章。

### 2. 每组一份瘦身词汇表

```bash
for f in <PROJ>/work/par/grp_*_src.json; do
  n=$(basename "$f" _src.json | sed 's/grp_//')
  <PFX> -m ainiee_translate.glossary filter --locked <PROJ>/work/glossary.locked.json \
       --for "$f" --out <PROJ>/work/par/g_${n}.json
done
```

只保留该组源文里**实际出现**的角色/术语（`non_translate` 全留）。实测 66 KB 的全表过滤后约 5 KB：
每个 agent 少读 ~20K token 的无关条目，注意力也更集中。命中率写在输出的 `_meta` 里。

### 3. 写项目级 STYLE_GUIDE.md（+ 可选 BOOK_BIBLE.md）

- `STYLE_GUIDE.md`：用 `references/style_guide_template.md` 生成 `<PROJ>/work/STYLE_GUIDE.md`。**要点从已确认的样章反推**：
  样章用了全角逗号就写「全角逗号」，用了 “ ” 就写「对话用 “ ”」——之后 `batch validate` 的 `halfwidth_punct` /
  `cjk_corner_quote` 警告就是对这两条的机械执行。
- `BOOK_BIBLE.md`（推荐，尤其是有军衔/亲属/舰级体系的书）：
  - **书已译了一部分**（续翻/补章）：一条命令从已译段机械抽先例——待译段里每个专名在已译文本中怎么处理、后接什么称谓：
    ```bash
    <PFX> -m ainiee_translate.precedents <PROJ>/work/cache.json --for <PROJ>/work/par/grp_*_src.json \
         --locked <PROJ>/work/glossary.locked.json --out <PROJ>/work/BOOK_BIBLE.md
    ```
  - **全新的书**：翻译前先派 1–2 个便宜 agent 通读各组源文，按 `references/book_bible_template.md` 抽**事实**：
    每个角色的性别、实衔、亲属关系、舰名与舰级、每章一句梗概。
  Janeway 上将/中将、Irene 姑妈/姨妈这类错误，靠事后校对要改上百段；靠 bible 在译前就定死。

### 3.5 开一个进度面板（可选，另一个终端）

```bash
<PFX> -m ainiee_translate.progress <PROJ>/work/cache.json --watch
```
每组一行：`running` / `stalled`（>180 秒没 append）/ `ready`（可写回）/ `needs_fix` / `written`，附速率与 ETA。它同时把一行摘要写进 `~/.ainiee-translate/progress.line` 供 statusline 显示（见 SKILL.md 附录 D）。
没有终端分屏（Claude Code Desktop）就用 `--serve 8765 --open` 开本地网页；要在手机上看就用 Artifact 看板：主控在**每次收到 subagent 完成通知**和**每波写回后**跑 `progress --json --out <PROJ>/work/progress_snapshot.json`，再 `write_db` 到 `progress/current`（附录 D）。

### 4. 并发派发 subagent（同一条消息里发多个 Agent 调用；一波 ~5–8 个）

每个 agent 的 prompt 自包含（模板见下）。关键点：
- 先读：`STYLE_GUIDE.md`、`BOOK_BIBLE.md`（若有）、`par/g_N.json`（本组词汇表）、`user_prompt.md`、`<SKILL>/references/translation_rules.md`、`par/grp_N_ctx.json`。
- 读 `par/grp_N_src.json`，逐段翻译，**1:1**（`text_index` 不变、不合并/拆分/漏译）。
- **边译边写 JSONL**：每译 30–50 段，用一小段 Python 把这批 `{"text_index", "translated_text"}` 以 `json.dumps(ensure_ascii=False)`
  逐行 **append** 到 `par/trans_N.jsonl`。不要攒到最后写一个大文件——中途出错只丢尾巴，且不存在手写 JSON 转义问题。
- 保留为英文的新专名写入 `par/newterms_N.txt`（每行一个）。
- **禁止**碰 `cache.json`、禁止跑 `batch write`。

### 5. 逐组验收（一条命令）

```bash
<PFX> -m ainiee_translate.batch validate <PROJ>/work/par/grp_N_src.json <PROJ>/work/par/trans_N.jsonl
```

退出码 0 = 可写。报告分两层：
- `hard`（必须先修）：`missing_index` / `extra_index` / `duplicate_index`、`segment`（空译、`<i>`/`<b>` 数量对不上）。
- `warnings`（风格漂移探测）：`cjk_corner_quote`（用了「」）、`halfwidth_punct`、`ascii_ellipsis`、`inner_space`、
  `identical_untranslated`、`too_short`/`too_long`（漏译/注水的长度比信号）等，带段号。

**不过怎么办**：只重派那一组（把 hard 清单连同「1:1 对应」的强调一起回传，让它只补那些 index 到同一个 jsonl）。
其余组不受影响。警告类先看数量：某组 `cjk_corner_quote` 几十条 = 那个 agent 用了台式引号，让它自己 sed 一遍再验；
零星几条主控顺手改。

### 6. 一次写回 + 收尾

```bash
<PFX> -m ainiee_translate.batch write <PROJ>/work/cache.json <PROJ>/work/par/trans_*.jsonl
```

- 所有组**一次**锁定/备份/加载/保存；同一 index 出现在两个文件里会拒绝（`--force` 让后者胜出）。
- 写回闸门与 validate 相同：空译、标记不匹配、未知 index 一律拒收并列出，其余照写；退出码 1 表示有拒收。
  项目规则允许标记数变化（如中译书名从 `<i>` 换成《》）时加 `--allow-tag-mismatch`。
- 然后：
  ```bash
  <PFX> -m ainiee_translate.glossary merge-newterms --locked <PROJ>/work/glossary.locked.json <PROJ>/work/par/newterms_*.txt --apply
  <PFX> -m ainiee_translate.glossary lint  --locked <PROJ>/work/glossary.locked.json
  <PFX> -m ainiee_translate.verify <PROJ>/work/cache.json <PROJ>/work/glossary.locked.json
  <PFX> -m ainiee_translate.scan   <PROJ>/work/cache.json --locked <PROJ>/work/glossary.locked.json --mode all
  <PFX> -m ainiee_translate.audit  <PROJ>/work/cache.json --out <PROJ>/work/audit.json
  ```
  **分波时每波收工就做这一段**（而不是整本译完才做）：merge 进去的新词、scan 揪出的问题，下一波 agent 直接受益。
- `verify` 的 `name_not_preserved` 常见假阳性：城市名/同名词（Paris=巴黎）、含头衔的别名。`glossary lint` 会把
  `alias_has_title`（如 `Admiral Janeway`）和 `alias_collides`（两人共用 `Paris`）先揪出来，改表再 verify。

`translation_status=7` 的段是排除项，无需翻译、不必写回。全书译完的判据是 `batch read` 返回 `[]`。

## 润色也能并行

同一套编排换一个阶段：

```bash
<PFX> -m ainiee_translate.batch split <PROJ>/work/cache.json --stage polish --target 300 --out-dir <PROJ>/work/par --context 20
#   组文件 grp_N_src.json 带 translated_text（润色 agent 读原文 + 初译）；par/_stage.json 记下 stage=polish
#   … subagent 按 work/polish_prompt.md 边润边 append par/polished_N.jsonl，每行 {"text_index","polished_text"} …
<PFX> -m ainiee_translate.batch validate <PROJ>/work/par/grp_N_src.json <PROJ>/work/par/polished_N.jsonl   # 同一套闸门
<PFX> -m ainiee_translate.polish write <PROJ>/work/cache.json <PROJ>/work/par/polished_*.jsonl            # 一次写回，状态→POLISHED
```

`progress` 会自动切到润色视图（两条总进度条，组识别 `polished_N.jsonl`，`written` = 全部已 POLISHED）。
润色 agent 的红线与翻译相同：锁定术语零变动、标记成对、1:1；另加「不改事实只改表达」。

## subagent prompt 模板（按组填 {N}/{RANGE}/{COUNT}）

> 你是把一本小说从源语言译成目标语言的文学译者，负责第 {N} 组（{RANGE}，{COUNT} 段）。前几章已译好并经用户确认，你的产出必须与既有风格**完全一致**。
>
> 第 1 步 先**完整读**：`<PROJ>/work/STYLE_GUIDE.md`、`<PROJ>/work/BOOK_BIBLE.md`（若存在；人物性别/军衔/亲属/舰级以它为准）、`<PROJ>/work/par/g_{N}.json`（本组词汇表，人名/术语唯一真相源）、`<PROJ>/work/user_prompt.md`（项目规则，若有）、`<SKILL>/references/translation_rules.md`、`<PROJ>/work/par/grp_{N}_ctx.json`（紧接在你这组之前的 20 段原文与译文，只读，用来接住语境和风格）。
>
> 第 2 步 读输入 `<PROJ>/work/par/grp_{N}_src.json`（`{"text_index","source_text"}` 数组，{COUNT} 段）。
>
> 第 3 步 逐段译成目标语言，硬性规则：人名/专名保留原文（除非词汇表给了译名）；头衔/风格按用户提示词与 STYLE_GUIDE；词汇表已收录的术语用其译名、表外专名默认保留原文（不自创音译）；标点/排版按 STYLE_GUIDE（对话引号用 “ ” 不用「」；与中文相邻的标点用全角）；`<i>`/`<b>` 标记原样保留、成对、包住对应内容；**1:1 对应**，不合并/拆分/漏译。
>
> 第 4 步 **边译边写**：每译完 30–50 段，用 Python 把这批以 JSONL 追加到 `<PROJ>/work/par/trans_{N}.jsonl`——每行 `json.dumps({"text_index": i, "translated_text": t}, ensure_ascii=False)`，以 `open(path, "a", encoding="utf-8")` 追加。全部译完后跑 `<PFX> -m ainiee_translate.batch validate <PROJ>/work/par/grp_{N}_src.json <PROJ>/work/par/trans_{N}.jsonl`，`hard` 不为空就修：同一 index 出现两行会被判 `duplicate_index`，所以改译文时**先删掉旧行再追加**（或整文件重写），直到退出码为 0。
>
> 第 5 步 把保留为英文的新专名写入 `<PROJ>/work/par/newterms_{N}.txt`（每行一个，没有就空文件）。
>
> 约束：**不要**改 `cache.json` 或任何 glossary 文件；**不要**跑 `batch write`；只产出 `trans_{N}.jsonl` 与 `newterms_{N}.txt`。忠实完整翻译，不得概括或跳过。
>
> 返回（只要这几行）：译了多少段；validate 是否通过（hard=0）；warnings 各类计数；新保留原文的专名清单。

## 模型选择（默认建议）

- **Opus**：样章（模式 A）、BOOK_BIBLE 抽取的复核、最终一致性通读与 reconcile。
- **Sonnet**：正文各组翻译。术语一致性靠瘦身词汇表 + validate/verify 机械保证，不靠模型档次。
- 想要与样章同等的文学质量，再让 subagent 继承父级模型。

## 用 Workflow 固化整条流水线（可选）

`references/parallel_workflow.js` 是一份 Workflow 脚本模板：主控先跑 `batch split` + `glossary filter` 得到组清单，
把组号数组作为 `args` 传入；脚本对每组 `pipeline(translate → validate → 若不过则重派一次)`，
全部通过后返回可写回的文件清单，主控再一次 `batch write`。写回与 verify 仍留在主控手里（prod 数据只经一个入口）。
