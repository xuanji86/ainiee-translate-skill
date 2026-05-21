# 多 agent 并行翻译（大书加速）

把步骤 5 的逐章串行翻译，改为**多个 subagent 同时翻译不同章节范围**，墙钟时间≈最慢的那个 agent。
本流程在一本 ~2400 段的小说上实测：11 章 1704 段由 7 个 agent 并发，约 9 分钟译完（串行需十几轮）。

**占位符说明**：`<PFX>` = AiNiee venv 命令前缀（见 SKILL.md「真实运行时说明」）；`<PROJ>` = 本翻译项目目录
（如 `~/mybook`）；`<SKILL>` = 本技能目录 `/Users/Anji/Desktop/ainiee-translate/skill`；`<book>` = 锁定表文件名前缀。

> **Codex**：下文的「subagent / Task」读作 `spawn_agent`（需在 `~/.codex/config.toml` 设 `[features] multi_agent = true`），结果用 `wait` 收、`close_agent` 释放；完整工具名对照见 `references/codex-tools.md`。「唯一铁律」（subagent 不写 `cache.json`）不变。

## 何时用

- 书很大（数百段以上）、章节之间相互独立。
- **风格已锁定**：先用步骤 4 的模式 A 译完约 1 章、经用户确认，再并行。否则各 agent 风格会发散。
- 锁定词汇表 + 用户自定义提示词已就位（涵盖主要人物/术语/项目规则；并行时新实体一律「保留原文 + 记录」，靠它们保证一致）。

## 唯一铁律：subagent 绝不写 cache.json

`batch write` 会「读改写」整个 `cache.json`。多个 agent 并发写 → 相互覆盖 / 文件损坏。

```
✗ 让每个 subagent 自己 batch write 到同一个 cache.json   —— 数据竞争，必坏
✓ subagent 只产出译文 JSON 文件；主控 agent 串行写回      —— 安全
```

**架构：**
```
主控：拆分章节 → 抽取各组源文件 → 写 STYLE_GUIDE.md
  ├─ agent1 (ch a-b)  读 glossary+rules+style+输入 → 产出 trans_1.json + newterms_1.txt
  ├─ agent2 (ch c-d)  ……（并发，互不写共享文件）
  └─ agentN ……
主控：校验各输出 → 归一化风格漂移 → **串行** batch write 每个文件 → 合并新词 → 全书 verify → 导出
```

## 步骤

### 1. 拆分章节（在边界上、按段数均衡）
先程序化地枚举章节边界，再按 `status==0` 的段数均衡分组，每组 ~200–300 段，**在章节边界切**
（章内段落彼此独立，但同章共享场景上下文，整章给同一 agent 读起来更连贯）。

```python
# <PFX> python - <<'PY'  —— 找章节边界 + 各章未译段数
import json, re
d=json.load(open('work/cache.json')); items=list(d['files'].values())[0]['items']
# 章节分隔段：本管线里多为「纯数字一段」，且常被标为 status=7（排除，无需翻译）
marks=[(it['text_index'],int(it['source_text'].strip()))
       for it in items if re.fullmatch(r'\d{1,2}', it.get('source_text','').strip() or '')]
chs=[]; expect=1                                  # 只保留单调递增的章号序列 1,2,3,…
for idx,n in marks:
    if n==expect: chs.append(idx); expect+=1
last=items[-1]['text_index']
for i,a in enumerate(chs):
    b=chs[i+1] if i+1<len(chs) else last+1
    u=sum(1 for it in items if a<=it['text_index']<b and it.get('translation_status',0)==0)
    print(f"ch{i+1}: idx {a}-{b-1}  untrans={u}")    # 据此手工把相邻章拼成 ~200-300 段的组
# PY
```
（不同 epub 的分隔段形式可能不同——也可能是 `Chapter N`、罗马数字或带状态 7 的破折号 `—`；先打印若干段确认形式。）

**并发数怎么定**：组数 = 同时跑的 agent 数。Claude 订阅**不设固定的并发 agent 上限**，也没有按套餐分配的"agent 个数"——真正的约束是你的**速率预算**（每个并行 agent 独立扣同一份额度，套餐等级只决定这份预算大小）。所以并发数是经验值，不是固定数：

- **每组 ~200–300 段**（上面的分组目标），保证每个 agent 的活够份量。
- **同时真正跑 ~5–8 个**起步；看到限流 / 重试 / 明显变慢就回退，顺畅再加（套餐越高余量越大：Pro < Max 5× < Max 20×）。
- **组数 > 并发数就分波次**：发一批 → `wait` 收完 → 再发下一批，别一次性全发。
- 别"一章一个"：章长不均会让你空等最长那章，且组太碎主控收口/串行写回的开销反而拖慢——**按段数均衡分组**才是重点。

### 2. 抽取各组源文件（只取未译段）
```python
# <PFX> python - <<'PY'
import json
d=json.load(open('work/cache.json')); items=list(d['files'].values())[0]['items']
groups={1:(642,884), 2:(884,1190), ...}   # {组号:(起,止)} 半开区间，按章节边界
for g,(a,b) in groups.items():
    seg=[{"text_index":it['text_index'],"source_text":it['source_text']}
         for it in items if a<=it['text_index']<b and it.get('translation_status',0)==0]
    json.dump(seg,open(f'/tmp/grp_{g}_src.json','w'),ensure_ascii=False,indent=1)
# PY
```

### 3. 写项目级 STYLE_GUIDE.md
所有 agent 必须产出**完全一致**的风格，光靠锁定表不够。用 `references/style_guide_template.md` 生成本书的
`<PROJ>/skill/references/STYLE_GUIDE.md`（标点、空格、人名/专名处理、日期格式、新名保留原文等；具体规则摘自用户提示词），让每个 agent 先读它。

### 4. 并发派发 subagent（同一条消息里发多个 Agent 调用；一批 ~5–8 个，组数更多就分波次——见步骤 1「并发数怎么定」）
每个 agent 的 prompt 必须自包含（见下方模板）。关键点：
- 先**读** STYLE_GUIDE.md + 锁定表 + translation_rules.md。
- 读自己的 `/tmp/grp_N_src.json`，逐段翻译，**1:1 对应**（输出条数==输入条数，`text_index` 不变、顺序不变，不合并/拆分/漏译）。
- 用 **Python builder 脚本**产出 `/tmp/trans_N.json`（避免手写 JSON 转义出错；正文用中文标点“”『』《》就不会和 JSON 的 ASCII `"` 冲突）。脚本结尾断言「无缺失 index、条数==输入」。
- 把保留为英文的新专名写入 `/tmp/newterms_N.txt`（每行一个）。
- **禁止**碰 `cache.json`、禁止跑任何 `batch write`。

### 5. 校验各输出
```python
for g in groups:
    src=json.load(open(f'/tmp/grp_{g}_src.json')); tr=json.load(open(f'/tmp/trans_{g}.json'))
    assert [x['text_index'] for x in src]==[x['text_index'] for x in tr]   # 条数+索引+顺序
    assert all(x['translated_text'].strip() for x in tr)                   # 无空译
    kagi=sum(x['translated_text'].count('「') for x in tr)                  # 风格漂移探测
```
**断言失败怎么办**：若某组条数/索引对不上、或有空译，**重派那一个 agent**（把校验结果连同要求 1:1 的强调一起回传），
其余组的产出不受影响、无需重跑。不要带着不对齐的文件去写回——写回按 `text_index` 匹配，错位会污染缓存。

### 6. 归一化风格漂移（实测必查的三处）
不同 agent 会有细微漂移，主控统一收口：
| 漂移 | 探测 | 修正 |
|------|------|------|
| 对话引号用了「」而非“” | 统计每组 `「` 数量 | 该组 `「→“`、`」→”`（内层 `『』` 保持） |
| 译名/称谓/风格各 agent 不一致 | 抽查关键人名、头衔、口头禅等 | 对照用户提示词 + 锁定表统一改写 |
| 新译名各自音译 | 看 newterms | 统一「保留原文」，需要中文时主控定一次、回写锁定表 |

### 7. 串行写回 + 收尾
```bash
for g in 1 2 3 4 5 6 7; do
  <PFX> -m ainiee_translate.batch write <PROJ>/work/cache.json /tmp/trans_$g.json
done
```
然后：合并 `newterms_*` 进锁定表（默认 `keep_source`）→ 全书 `verify` → 修正 → `export`。
`verify` 的 `name_not_preserved` 常见**假阳性**：城市名/同名词（如 Paris=巴黎）、含冠词的别名（`the Basileus`）。逐条确认是真问题再改；可在锁定表里把会误报的别名去掉。

`translation_status=7` 的段（章号、`—` 分隔符等）是被排除项，**无需翻译、不必写回**；`export` 会原样保留它们。
全书译完的判据是 `batch read` 返回 `[]`（即再无 `status=0`），而非所有段都变成已译。

## subagent prompt 模板（按组填 {N}/{RANGE}/{COUNT}）

> 你是把一本小说从源语言译成目标语言的文学译者，负责{RANGE}（{COUNT} 段）。前几章已译好并经用户确认，你的产出必须与既有风格**完全一致**。
>
> 第 1 步 先**完整读**：`<PROJ>/skill/references/STYLE_GUIDE.md`、`<PROJ>/skill/references/<book>.glossary.locked.json`（人名/术语唯一真相源）、`<PROJ>/work/user_prompt.md`（用户自定义项目规则，若有）、`<SKILL>/references/translation_rules.md`。
>
> 第 2 步 读输入 `/tmp/grp_{N}_src.json`（`{"text_index","source_text"}` 数组，{COUNT} 段）。
>
> 第 3 步 逐段译成目标语言，硬性规则：人名/专名保留原文（除非锁定表给了译名）；人名/头衔/风格按用户提示词处理；锁定表已收录的术语用其译名、表外专名默认保留原文（不自创音译）；标点/排版/本地化（引号、空格、日期等）按目标语言惯例（见 STYLE_GUIDE）；OCR 粘连词（如 `Marlowstepped`、`intothe`）要还原边界；**1:1 对应**，不合并/拆分/漏译。
>
> 第 4 步 写 Python builder `/tmp/build_{N}.py`：定义 `T={index:"译文"}` 覆盖每个输入 index，载入源文件，按输入顺序构建 `[{"text_index":i,"translated_text":T[i]}]`，断言无缺失，`json.dump` 到 `/tmp/trans_{N}.json`（`ensure_ascii=False`）。正文只用中文标点，避免 ASCII `"`。跑它并打印条数、确认 0 缺失（==`{COUNT}`）。
>
> 第 5 步 把保留为英文的新专名写入 `/tmp/newterms_{N}.txt`（每行一个，没有就空文件）。
>
> 约束：**不要**改 `cache.json` 或任何 glossary 文件；**不要**跑 `batch write` 或任何 ainiee_translate 命令；只产出那两个 /tmp 文件。忠实完整翻译，不得概括或跳过。
>
> 返回：译了多少段、确认条数=={COUNT}、新保留原文的专名清单。

## 模型选择
- 想要与采样章节同等的文学质量：让 subagent 继承父级模型（通常 Opus）。
- 想更快/更省：用 Sonnet 做翻译，锁定表会约束术语；主控做最终一致性通读与 verify。
