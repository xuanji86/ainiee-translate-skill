---
name: ainiee-translate
description: Use when the user wants to translate a novel/epub end-to-end on Claude Code itself (no AiNiee app), AiNiee-style — parse, build a locked glossary, translate chapter by chapter following rules (names preserved, title 3-way, term consistency), write back and export. Triggers on "用 agent 翻译这本书", "agent 版 aniee 翻译", "把这本 epub 翻译了" and similar.
---

# ainiee-translate 技能指南

## 总览

本技能让 **Claude Code（agent 本身）** 充当翻译引擎，配合一组确定性 Python 管道脚本，把一本 epub/txt 小说**端到端翻译**：

```
parse → 构建锁定词汇表 → 逐章翻译（agent 按规则） → 写回缓存 → 导出成品
```

- Agent IS 翻译引擎：无需调用任何外部 API；翻译质量由 agent 按规则实时应用保证。
- **不限于中译**：支持任意源语言 → 目标语言（`{source_language}` 解析时自动检测、`{target_language}` 由用户指定）；本指南以中文为例，其他目标语言同理。
- 进度状态驱动（`translation_status`）：中断后重跑自动从首个未译段继续，天然可恢复。
- 每批写回前自动备份（时间戳）：`cache.json.bak.YYYYMMDD_HHMMSS`。

---

## 真实运行时说明（重要）

`parse` 和 `export` 模块内部调用 AiNiee 的 `FileReader` / `FileOutputer`，需要 AiNiee 的运行时依赖（如 `msgspec`、epub 解析库等）。

**因此必须使用 AiNiee 的 venv，不能用独立的空 venv。**

**命令前缀（后文用 `<PFX>` 代替）：**

```bash
AINIEE_REPO=/Users/Anji/Desktop/AiNiee \
PYTHONPATH=/Users/Anji/Desktop/ainiee-translate/src \
/Users/Anji/Desktop/AiNiee/.venv/bin/python
```

或者，先把包装进 AiNiee 的 venv（只需一次）：

```bash
cd /Users/Anji/Desktop/ainiee-translate
/Users/Anji/Desktop/AiNiee/.venv/bin/pip install -e .
```

安装后可以省略 `PYTHONPATH`，但仍需 `AINIEE_REPO` 和 AiNiee venv 的 Python。

**测试命令示例：**

```bash
cd /Users/Anji/Desktop/ainiee-translate
AINIEE_REPO=/Users/Anji/Desktop/AiNiee \
/Users/Anji/Desktop/AiNiee/.venv/bin/python -m pytest -v
```

---

## 步骤 1：环境准备

1. **设置 `AINIEE_REPO`**（指向本地 AiNiee 仓库）：

   ```bash
   export AINIEE_REPO=/Users/Anji/Desktop/AiNiee
   ```

2. **技能符号链接**（只需一次）：

   ```bash
   ln -s /Users/Anji/Desktop/ainiee-translate/skill ~/.claude/skills/ainiee-translate
   ```

3. **准备工作目录**（每个翻译项目独立）：

   ```bash
   mkdir -p ~/my-project/work ~/my-project/out
   ```

---

## 步骤 2：解析输入书籍

将 epub/txt 解析成 `cache.json`（AiNiee `CacheProject` 格式）：

```bash
<PFX> -m ainiee_translate.parse \
  --input /path/to/book.epub \
  --type AutoType \
  --out ~/my-project/work/cache.json
```

- `--type`：`AutoType`（自动检测）、`Epub`、`Txt` 等，默认 `AutoType`。
- 成功后打印：`parsed N items -> work/cache.json`。

---

## 步骤 2 替代：导入已有项目（含 AiNiee 缓存）

不必每次从头解析。若已有一个翻译缓存——AiNiee 的工程缓存（`AinieeCacheData.json`）或另一个 ainiee-translate 项目的 `cache.json`（同为 `CacheProject` 格式）——可直接导入，再续翻/润色/校验/导出。

- 列出可导入的 AiNiee 工程（扫描 `~/Library/Application Support/AiNiee/ProjectCache`，可用 `AINIEE_CACHE_DIR` 覆盖）：

  ```bash
  <PFX> -m ainiee_translate.project list
  ```

  每项给出 `project_id`、`project_name`、`input_path`（原书）及状态计数（未译/已译/已润色/已排除）。

- 导入到项目（项目 ID 用 `--ainiee`，缓存文件路径用 `--cache`）：

  ```bash
  <PFX> -m ainiee_translate.project import --ainiee <项目ID> --work ~/my-project
  # 或：--cache /path/to/AinieeCacheData.json --work ~/my-project
  ```

  把缓存规范化进 `~/my-project/work/cache.json`（已存在则先时间戳备份），并打印 `input_path` 与状态计数。

导入后按状态接续：还有未译段→步骤 5 续翻；已译待润色→步骤 6.5 润色；直接出成品→步骤 6 导出（原书路径见 `input_path`）；查残留→步骤 7。

---

## 步骤 3：构建并锁定词汇表

从 AiNiee 公共术语表（`prompt_dictionary_data`）和可选的项目分析缓存（`analysis_v1`）生成锁定表：

```bash
<PFX> -m ainiee_translate.glossary \
  --config "/Users/Anji/Library/Application Support/AiNiee/config.json" \
  --analysis "/Users/Anji/Library/Application Support/AiNiee/ProjectCache/<project_id>/AinieeCacheData.json" \
  --out ~/my-project/skill/references/mybook.glossary.locked.json
```

- `--analysis` 可省略（无项目分析时跳过）。
- 生成后，**必须人工 review 并锁定**：检查人名分类（是否保留原文）、地名/种族译法、音译唯一性。复核时特别注意：自动清洗按姓氏末词归并同一角色，可能把**同姓的不同角色**误并为一条——检查每条的 aliases 里没有混入另一个人。
- 锁定表格式：

```json
{
  "characters": [
    {"canonical": "James Marlow", "render": "James Marlow",
     "aliases": ["Marlow", "Jim"], "gender": "M", "note": "船长"}
  ],
  "terms": [
    {"src": "the Ravensguard", "dst": "鸦卫军", "category": "faction"},
    {"src": "Highmark", "dst": "Highmark", "keep_source": true}
  ],
  "non_translate": [{"marker": "<i>", "category": "tag"}]
}
```

---

## 模块（可选）：一套设置应对不同书

「模块」= 一个可复用的任务设置包，存于 `~/.ainiee-translate/modules/<名字>/`，含：翻译提示词、润色提示词、词汇表、禁翻表、风格/世界观/角色、源/目标语言。同一个技能/插件靠切换模块应对不同小说/文档。

- 导入 AiNiee profile 为模块：`<PFX> -m ainiee_translate.profile import --profile <profile.json> --name <名字>`
- 新建空模块：`<PFX> -m ainiee_translate.module create <名字> [--source-language X --target-language Y]`
- 列出/查看：`<PFX> -m ainiee_translate.module list` / `show <名字>`
- 加载进项目：`<PFX> -m ainiee_translate.module load <名字> --work ~/my-project`

加载只是把模块的 `translate_prompt.md`→`work/user_prompt.md`、`polish_prompt.md`、`glossary.locked.json` 拷进项目 `work/`——即后续步骤本就在读的文件。**不用模块的项目，流程与下文完全一致。** 此外 `prompt.py` 还能从 AiNiee 配置/profile 提取所选系统提示词（`--translate-system`）与润色提示词（`--polish`）。命令行入口见附录 C。

---

## 步骤 3+：用户自定义提示词（可选，像 AiNiee 一样自己写规则）

翻译规则分两层，**领域/风格规则不写死在技能里**——和 AiNiee 一样由用户自己写：
- **通用层（技能自带）**：`references/translation_rules.md`，即 AiNiee 原生标准提示词（逐行、保留标记、忠实准确）。
- **项目层（用户自己写）**：人名怎么处理、头衔怎么摆、对话风格、世界观、示例等，全由用户提供。

两种来源：
1. **复用 AiNiee app 的提示词设置**（推荐）：你在 AiNiee 里配的「自定义系统提示词 / 角色介绍 / 写作风格 / 世界观 / 翻译示例」都存在 `config.json`，按各自开关汇总成一份：
   ```bash
   <PFX> -m ainiee_translate.prompt --config "<AiNiee config.json>" --out ~/my-project/work/user_prompt.md
   ```
   （读取 `translation_user_prompt_data` / `characterization_data` / `writing_style_content` / `world_building_content` / `translation_example_data`，仅纳入开关打开的部分。）
2. **手写项目提示词**：直接在 `~/my-project/work/user_prompt.md` 写你的规则（如「人名保留原文」「军衔后置」等）。

翻译时 agent 遵循：**AiNiee 原生原则（translation_rules.md）＋ 用户自定义提示词（user_prompt.md，若有）＋ 锁定表（术语表/角色表）**。技能本身不预设任何特定题材的规则。

---

## 步骤 4：选择介入模式

开始翻译前，与用户确认介入模式：

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| **A 抽样自动（默认）** | 先译约 1 章展示给用户确认风格和规则对齐；之后自动逐章。遇到锁定表外的歧义新实体时停下询问。 | 第一次翻译新书 |
| **B 每章过目** | 每章译完后展示给用户，点头确认后写回，再译下一章。歧义实体停下询问。 | 用户想细粒度监控 |
| **C 全自动** | 整本一次性译完写回，歧义实体不停止，记入 `needs_review` 列表，最后统一报告。| 已熟悉风格、快速跑完 |

---

## 步骤 5：翻译循环

### 5a. 读取未译批次

```bash
<PFX> -m ainiee_translate.batch read \
  ~/my-project/work/cache.json \
  --size 100
```

输出：JSON 数组，每项包含 `text_index`（段落编号）和 `source_text`（源文）：

```json
[
  {"text_index": 1, "source_text": "The room fell silent."},
  {"text_index": 2, "source_text": "Marlow studied the letter."}
]
```

**恢复机制**：`read` 只返回 `translation_status = UNTRANSLATED` 的段落。重跑时自动跳过已译段，从断点继续。

### 5b. Agent 翻译

**Agent 本身就是翻译引擎。** 读取上一步的 JSON，逐段按以下规则翻译：

1. **通用规则**见 `references/translation_rules.md`（AiNiee 原生：逐行对应、保留标记、忠实准确）。
2. **项目规则**（人名保留、头衔摆放、风格等）见用户自定义提示词（步骤 3+，由用户自己写，不写死在技能里）。
3. **人名/术语** 以锁定表（术语表/角色表）为唯一真相源；`render` 为英文则保留原文。
4. 遇到锁定表外的新实体：模式 A/B 停下询问用户；模式 C 用锁定表最近匹配或保留原文，并记入待审列表。

将翻译结果写成 JSON 文件：

```json
[
  {"text_index": 1, "translated_text": "房间里一片寂静。"},
  {"text_index": 2, "translated_text": "Marlow 端详着那封信。"}
]
```

保存为 `~/my-project/work/translations_batch_001.json`（命名自取）。

### 5c. 写回缓存

```bash
<PFX> -m ainiee_translate.batch write \
  ~/my-project/work/cache.json \
  ~/my-project/work/translations_batch_001.json
```

- 写回前自动创建带时间戳的备份：`cache.json.bak.YYYYMMDD_HHMMSS`。
- 成功后打印：`applied N translation(s)`。
- 重复执行步骤 5a → 5c 直到 `batch read` 返回空数组（`[]`）为止。

---

## 步骤 5+：多 agent 并行翻译（可选，大书加速）

书很大、章节相互独立、且**风格已用模式 A 锁定**后，可派多个 subagent 并发翻译不同章节范围，
墙钟时间≈最慢的 agent（实测 11 章 1704 段用 7 个 agent 约 9 分钟译完）。

**唯一铁律：subagent 绝不写 `cache.json`**（并发「读改写」会损坏文件）。subagent 只产出译文 JSON 文件，
**由主控 agent 串行 `batch write` 回写**。各 agent 共享同一份锁定表 + `translation_rules.md` + 项目级
`STYLE_GUIDE.md`（用 `references/style_guide_template.md` 生成）以保证风格一致；新实体一律「保留原文 + 记录」。

完整流程（拆分、抽取、派发模板、风格漂移归一化、串行写回、收尾 verify）见 **`references/parallel_translation.md`**。

---

## 步骤 6：导出成品

```bash
<PFX> -m ainiee_translate.export \
  --cache ~/my-project/work/cache.json \
  --output ~/my-project/out/ \
  --input /path/to/book.epub
```

- 使用 AiNiee 的 `FileOutputer` 保留原书结构和富文本标签。
- 输出文件名带 `_translated` 后缀（默认），例如 `book_translated.epub`。

---

## 步骤 6.5：润色（可选）

若当前模块带 `polish_prompt.md`（已随加载落到 `work/`），可对已译文本做润色 pass：状态 TRANSLATED→POLISHED，可断点续跑；导出读 `final_text`，自动采用润色后的文本。模块无润色提示词则跳过本步。

循环直到 `batch read-translated` 返回 `[]`：
1. `<PFX> -m ainiee_translate.batch read-translated work/cache.json --size 100` → `{text_index, source_text, translated_text}` 数组。
2. agent 按 `work/polish_prompt.md` + 锁定词汇表润色每段（**逐行 1:1、保留标记、人名/术语依词汇表**），写 `work/polished_NNN.json`（`{text_index, polished_text}`）。
3. `<PFX> -m ainiee_translate.polish write work/cache.json work/polished_NNN.json`（写回并置 POLISHED）。

---

## 步骤 7：验证残留规则违规

```bash
<PFX> -m ainiee_translate.verify \
  ~/my-project/work/cache.json \
  ~/my-project/skill/references/mybook.glossary.locked.json
```

输出 JSON 格式的问题列表，并打印问题总数。两类检测：

- `empty_translation`：源段有内容但译文为空（漏译）。
- `name_not_preserved`：源段含锁定表英文人名但译文中该名消失（人名汉化）。

对每个问题，使用 `batch write` 修正对应 `text_index` 的译文后重新跑 verify，直到无问题。

---

## 附录 A：命令速查

```bash
# 设置环境变量（每次新终端）
export AINIEE_REPO=/Users/Anji/Desktop/AiNiee

# 命令前缀
PFX="AINIEE_REPO=/Users/Anji/Desktop/AiNiee PYTHONPATH=/Users/Anji/Desktop/ainiee-translate/src /Users/Anji/Desktop/AiNiee/.venv/bin/python"

# 解析
$PFX -m ainiee_translate.parse --input book.epub --type AutoType --out work/cache.json

# 词汇表
$PFX -m ainiee_translate.glossary --config "~/Library/Application Support/AiNiee/config.json" --out work/mybook.locked.json

# 用户自定义提示词（汇总 AiNiee 配置里的自定义提示词）
$PFX -m ainiee_translate.prompt --config "~/Library/Application Support/AiNiee/config.json" --out work/user_prompt.md

# 批次读取
$PFX -m ainiee_translate.batch read work/cache.json --size 100

# 批次写回
$PFX -m ainiee_translate.batch write work/cache.json work/translations_001.json

# 导出
$PFX -m ainiee_translate.export --cache work/cache.json --output out/ --input book.epub

# 验证
$PFX -m ainiee_translate.verify work/cache.json work/mybook.locked.json

# 完整测试套件
cd /Users/Anji/Desktop/ainiee-translate
AINIEE_REPO=/Users/Anji/Desktop/AiNiee /Users/Anji/Desktop/AiNiee/.venv/bin/python -m pytest -v
```

---

## 附录 B：常见问题

**Q: `parse` 报错找不到模块？**
A: 确认 `AINIEE_REPO` 已设置且指向正确路径，且使用的是 AiNiee 的 venv（`/Users/Anji/Desktop/AiNiee/.venv/bin/python`）而不是系统 Python。

**Q: `batch read` 返回空数组 `[]`？**
A: 所有段落均已翻译完毕（`translation_status = TRANSLATED`），可以进行导出步骤。

**Q: 导出后 epub 没有内容？**
A: 检查 `cache.json` 中是否有 `translation_status = 1` 的段落（即已译段）。可用 `batch read` 确认剩余未译数量。

**Q: 如何重做某段译文？**
A: 直接用 `batch write` 写入新的 `translated_text`（按 `text_index` 覆盖），`write_back` 会用新值替换旧值。

**Q: 如何跳过不需要翻译的段落（如纯数字章节号）？**
A: 在 `translations.json` 中将 `translated_text` 设为源文原样（或空字符串后用 verify 检测），或在生成时 agent 判断后直接复制源文。

---

## 附录 C：斜杠命令（菜单）

安装为插件后，所有操作都可用 `/ainiee-translate:<命令>` 完成（`/` 选择器即菜单，或 `/ainiee-translate:menu` 看清单）：

| 命令 | 作用 |
|------|------|
| `menu` | 显示命令菜单 |
| `translate <输入> [模块]` | 端到端翻译（解析→词汇表→翻译→导出→校验）|
| `import-profile <profile.json> <模块>` | 导入 AiNiee profile 为模块 |
| `module list\|show\|create\|load …` | 管理模块 |
| `gen-prompt translate\|polish [模块]` | 让 agent 起草翻译/润色提示词 |
| `switch-prompt [模块]` / `show-prompt [模块]` | 切换 / 查看模块 |
| `polish [批大小]` | 润色 pass |
| `glossary` / `export <输入>` / `verify` / `status` | 词汇表 / 导出 / 校验 / 状态 |

命令脚本路径用 `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts`，并需用户设好 `AINIEE_REPO`/`AINIEE_PY`。
