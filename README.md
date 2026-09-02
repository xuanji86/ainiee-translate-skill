<div align="center">

# ainiee-translate

**Agent 原生的长篇翻译管线** —— 让编码 agent 本身当翻译引擎，端到端译完一本书。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.9.0-green.svg)](https://github.com/xuanji86/ainiee-translate-skill/releases)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-90%20passing-brightgreen.svg)](tests/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-333.svg)](skills/ainiee-translate/references/codex-tools.md)

[安装](#安装) · [快速开始](#快速开始) · [工作原理](#工作原理) · [命令](#命令) · [模块](#模块) · [质量闭环](#质量闭环)

</div>

---

## 这是什么

工作方式类似 [AiNiee](https://github.com/NEKOparapa/AiNiee)，但**不跑 AiNiee 应用**（无 GUI / HTTP / MCP）：翻译由**编码 agent 自己**（Claude Code / Codex）完成，一组确定性 Python 脚本负责解析、批次调度、词汇表锁定、写回与导出。

支持**任意源语言 → 任意目标语言**，不限中译。

### 与直连 API 翻译的区别

|  | 经外部 API | ainiee-translate |
|---|---|---|
| 计费 | 按 token，整本约 1–2M token | 走订阅额度，整本约 **~302K token**（约 **5×** 更省——省在不重发提示词/术语表） |
| 术语一致性 | 每批各自为政，易漂移 | 全书共用一张**锁定词汇表**，机械校验 |
| 中断恢复 | 自行处理 | 状态驱动（`translation_status`），重跑自动续上 |
| 富文本 | 常被压平 | 斜体/粗体按源书写法**原样还原** |
| 质量兜底 | 无 | 写回闸门（空译/标记不成对拒收）+ `verify` + `audit` + `scan` 四种发现模式 + 时间戳备份 |

---

## 安装

**自包含**：解析/导出模块已内置（`skills/ainiee-translate/scripts/ainiee_translate/_vendor/`，改写自 AiNiee、剥离其 App 框架），**无需克隆 AiNiee 仓库**。

```bash
python3 -m venv ~/.venvs/ainiee-translate
~/.venvs/ainiee-translate/bin/pip install \
  msgspec beautifulsoup4 lxml rich openpyxl polib python-pptx chardet
```

自带 15 种格式：`epub` `txt` `md` `docx` `xlsx` `pptx` `csv` `srt` `vtt` `ass` `lrc` `po` `json` `rpy` `trans`。
仅 **PDF 与 Windows Office 转换**未自包含——需要时设 `AINIEE_REPO` 回退到 AiNiee。

### 方式一：Claude Code 插件（推荐）

```text
/plugin marketplace add xuanji86/ainiee-translate-skill
/plugin install ainiee-translate@ainiee-translate
```

更新：`/plugin marketplace update ainiee-translate` 后 `/reload-plugins`。

### 方式二：手动装为技能

```bash
git clone https://github.com/xuanji86/ainiee-translate-skill.git
cp -r ainiee-translate-skill/skills/ainiee-translate ~/.claude/skills/
```

### 方式三：Codex（OpenAI Codex CLI）

SKILL.md 是跨平台标准格式，Codex 会自动发现：

```bash
git clone https://github.com/xuanji86/ainiee-translate-skill.git
ln -s "$PWD/ainiee-translate-skill/skills/ainiee-translate" ~/.codex/skills/ainiee-translate
```

工具名对照（Bash→shell、Task→spawn_agent…）与多 agent 并行配置见
[`references/codex-tools.md`](skills/ainiee-translate/references/codex-tools.md)。

### 环境变量

| 变量 | 必需 | 说明 |
|---|---|---|
| `SKILL_DIR` | ✅ | 技能安装目录 |
| `AINIEE_PY` | ✅ | 上面 venv 的 python |
| `AINIEE_REPO` | — | **可选**，仅 PDF / Windows Office 回退时需要 |
| `AINIEE_TRANSLATE_HOME` | — | 模块根目录，默认 `~/.ainiee-translate` |

自检：

```bash
PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY" \
  -c "from ainiee_translate import io_dispatch; print('formats OK:', io_dispatch.supported_extensions())"
```

---

## 快速开始

装成插件后，一句话即可：

```text
/ainiee-translate:translate ~/books/mybook.epub star-trek
```

或对 agent 说「用 agent 翻译这本 epub」。它会走完 解析 → 词汇表 → 逐章翻译 → 导出 → 校验，
并在开始前与你确认**介入模式**：

| 模式 | 行为 | 适用 |
|---|---|---|
| **A 抽样自动** | 先译约 1 章给你确认风格，之后自动跑完；遇表外歧义实体停下询问 | 首次翻新书（默认）|
| **B 每章过目** | 每章译完给你点头后才写回 | 需要细粒度监控 |
| **C 全自动** | 一气跑完，歧义记入 `needs_review` 最后统一报告 | 风格已熟 |

---

## 工作原理

```
       ┌─────────┐   ┌──────────┐   ┌───────────┐   ┌────────┐   ┌────────┐
书 ──▶ │  parse  │──▶│ glossary │──▶│  translate│──▶│ polish │──▶│ export │──▶ 成品
       └─────────┘   └──────────┘   └───────────┘   └────────┘   └────────┘
            │             │            ▲     │                        ▲
       cache.json    锁定词汇表    batch read  batch write        original_html
       (含原书 HTML)   (人工复核)      │     │                    (结构/标签还原)
                                      └──┬──┘
                                    agent = 翻译引擎
                                  (规则 + 词汇表 + 提示词)
                                         │
                              ┌──────────┴──────────┐
                              │  verify  ·  scan    │  质量闭环
                              └─────────────────────┘
```

- **状态驱动**：每段有 `translation_status`（未译/已译/已润色/排除）。`batch read` 只返回未译段，
  所以中断后重跑天然续上，无需记录进度。
- **写回有闸门、有锁、有备份**：空译 / `<i>` `<b>` 不成对 / 未知 index 拒收；文件锁 + 原子写；每次写前时间戳备份（默认保留最近 10 个）。
- **agent 即引擎**：不调用任何外部翻译 API，质量由 agent 实时应用
  「AiNiee 原生提示词 ＋ 用户自定义提示词 ＋ 锁定词汇表」保证。
- **富文本保真**：源书的行内斜体/粗体在 `source_text` 里统一成 `<i>…</i>` / `<b>…</b>` 标记，
  导出时按该段原文的实际写法（`<i>`、`<em>`、`<span class="italic">` …）还原。

### 关键特性

- **导入已有项目** —— 直接接管 AiNiee 工程缓存（`AinieeCacheData.json`）或既有 `cache.json`，续翻 / 润色 / 校验 / 重新导出。
- **模块化** —— 整套任务设置（提示词、词汇表、禁翻表、风格、语言对）打包成可复用模块，一个插件应对不同书；支持从 AiNiee profile 一键导入。
- **多 agent 并行** —— 风格锁定后可派多个 subagent 并发翻不同章节（实测 11 章 1704 段 / 7 agent / ~9 分钟）。编排全是命令：`batch split` 按章节边界分组并附前文上下文，`glossary filter` 给每组一份瘦身词汇表（66 KB → ~5 KB），subagent 边译边写 JSONL，`batch validate` 逐组验收，`batch write` 一次写回全部。铁律：subagent 只产出译文文件，**由主控写回**。
- **润色 pass** —— 可选二次加工，状态 `TRANSLATED → POLISHED`，导出自动采用润色文本。

---

## 命令

两层：**斜杠命令**（插件内用）和其底层 **Python CLI**（Codex / 手动 / 调试）。

### 斜杠命令（17 个）

**翻译流程**

| 命令 | 参数 | 作用 |
|---|---|---|
| `/ainiee-translate:translate` | `<输入> [模块]` | 端到端翻译一本书 |
| `/ainiee-translate:import-project` | `[list \| <缓存或项目ID> <项目目录>]` | 导入已有项目继续处理 |
| `/ainiee-translate:glossary` | `[--config P] [--analysis P]` | 构建并锁定工作词汇表 |
| `/ainiee-translate:polish` | `[批大小]` | 润色 pass |
| `/ainiee-translate:export` | `<原始输入文件>` | 导出成品 |
| `/ainiee-translate:status` | — | 项目状态（模块 / 计数 / 续跑点）|

**质量与修复**

| 命令 | 参数 | 作用 |
|---|---|---|
| `/ainiee-translate:verify` | — | 校验漏译、锁定人名未保留 |
| `/ainiee-translate:scan` | `[discover\|terms\|strays\|merges\|all]` | 补 verify 盲区（见[质量闭环](#质量闭环)）|
| `/ainiee-translate:repair` | — | 修复存量 epub 项目的行内标记与空格 |
| `/ainiee-translate:audit` | `[--allow-tag-mismatch]` | 机械体检：空译/标记不匹配 + 半角标点/「」/长度比等 |
| `/ainiee-translate:progress` | `[--line\|--json]` | 进度面板：全书 + 每个并行组的状态/速率/卡死 |

**模块与提示词**

| 命令 | 参数 | 作用 |
|---|---|---|
| `/ainiee-translate:import-profile` | `<profile.json> <模块>` | AiNiee profile → 模块 |
| `/ainiee-translate:module` | `<list\|show\|create\|load> [名] [--work D]` | 模块管理 |
| `/ainiee-translate:switch-prompt` | `[模块]` | 切换当前项目的模块 |
| `/ainiee-translate:show-prompt` | `[模块]` | 查看提示词与词汇表摘要 |
| `/ainiee-translate:gen-prompt` | `<translate\|polish> [模块]` | 让 agent 起草提示词 |
| `/ainiee-translate:menu` | — | 命令菜单 |

### 底层 Python CLI

前缀 `<PFX>` = `PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY"`，形如 `<PFX> -m ainiee_translate.<模块> …`：

| 模块 | 用法 |
|---|---|
| `parse` | `--input <书> --type AutoType --out <cache.json>` |
| `glossary` | `build --config <config.json> [--analysis <路径>] --out <locked.json>` · `filter --locked L --for grp_N_src.json --out g_N.json` · `lint --locked L` · `merge-newterms --locked L newterms_*.txt --apply` |
| `batch` | `read <cache> --size N` · `read-translated <cache> --size N` · `split <cache> --target 300 --out-dir D --context 20 [--stage polish]` · `validate <src.json> <trans.jsonl>` · `write <cache> <译文.json|.jsonl>… [--force] [--allow-tag-mismatch]` |
| `polish` | `write <cache> <润色.json|.jsonl>… [--force] [--allow-tag-mismatch]` |
| `prompt` | `--config <config> [--out F] [--translate-system\|--polish]` |
| `module` | `list` · `show <名>` · `create <名> [--source-language X --target-language Y]` · `load <名> [--work D]` |
| `profile` | `import --profile <p.json> --name <名> [--target-language X] [--force]` |
| `project` | `list [--ainiee-cache-dir D]` · `import (--ainiee <ID>\|--cache <路径>) --work <目录>` |
| `export` | `--cache <cache> --output <目录> --input <原书>` |
| `verify` | `<cache> <locked.json>` |
| `scan` | `<cache> --locked <locked.json> --mode all` |
| `repair` | `<cache> [--apply] [--list-marked]` |
| `audit` | `<cache> [--out audit.json] [--allow-tag-mismatch]` |
| `progress` | `<cache> [--watch\|--once\|--line\|--json [--out F]\|--serve PORT [--open]]`（多 agent 进度面板 / statusline 一行 / 本地网页看板；润色阶段双进度条）|
| `precedents` | `<cache> --for grp_*_src.json [--locked L] --out BOOK_BIBLE.md`（续翻时从已译段抽专名先例）|

---

## 模块

**模块**把一整套任务设置打包成可复用、可切换的文件夹，默认在 `~/.ainiee-translate/modules/<名字>/`：

```
module.json          # 元数据 + 清单（语言对、各开关、来源）
translate_prompt.md  # 翻译提示词（加载后即项目里的 user_prompt.md）
polish_prompt.md     # 润色提示词（可选；没有则不提供润色）
glossary.locked.json # 锁定词汇表 {characters, terms, non_translate}
style.md             # 写作风格/世界观（可选）
examples.json        # few-shot 示例（可选）
```

`glossary.locked.json` 的形状：

```json
{
  "characters": [
    {"canonical": "James Marlow", "render": "James Marlow",
     "aliases": ["Marlow"], "gender": "M", "note": "舰长"}
  ],
  "terms": [
    {"src": "Korin", "dst": "科林", "category": "race"},
    {"src": "Highmark", "dst": "Highmark", "keep_source": true, "category": "place"}
  ],
  "non_translate": [{"marker": "{0}", "category": "placeholder"}]
}
```

- `characters[].render` —— 人名最终写法（保留原文时 `render == canonical`）。
- `terms[].keep_source: true` —— 该词保持原文不译。
- `non_translate[].marker` —— 原样保留的标记/占位符。

### 三种建法

**① 从 AiNiee profile 导入（最快）** —— 语言、提示词、术语表、禁翻表一把梭：

```bash
<PFX> -m ainiee_translate.profile import --profile <profile.json> --name mybook
<PFX> -m ainiee_translate.module show mybook          # 检查导入结果
```

**② 新建空模块再填** —— 从零手写规则：

```bash
<PFX> -m ainiee_translate.module create mybook \
  --source-language English --target-language 简体中文
```

不想手写提示词？`/ainiee-translate:gen-prompt translate mybook` 让 agent 访谈你后起草。

**③ 直接放文件** —— 按上面结构手建文件夹亦可。

### 加载

```bash
<PFX> -m ainiee_translate.module load mybook --work ~/my-project
```

把模块的提示词与词汇表拷进项目 `work/`（已存在先时间戳备份）。

> 模块可独立成 git 仓库分发：`git clone <repo> ~/.ainiee-translate/modules/<名字>` 即装。

---

## 质量闭环

翻完不等于译对。本管线提供四件工具，**分工明确**：

### `verify` —— 词汇表执行器

只查两类硬伤：`empty_translation`（漏译）、`name_not_preserved`（锁定表人名消失）。

> ⚠️ **「verify 干净」≠「没有翻译错误」**。它只认**锁定表里登记过的**名字——没进表的名字它根本不知道要查。
> 一份「2 个问题」的干净报告，往往只说明表里恰好只有 2 个相关名字。

### `scan` —— 发现器（补 verify 盲区）

| 模式 | 抓什么 |
|---|---|
| `discover` | 表外专名：`inconsistent`（时而保留时而消失，**高置信优先处理**）/ `never_preserved`（全程被音译的真名 + 合法意译的术语，需人眼分） |
| `terms` | **反向漏译**——词汇表有中文译名的术语，个别段却留成英文 |
| `strays` | **幻觉插入**——译文里出现、原文却没有的英文 token（凭空错名）|
| `merges` | 丢空格的粘连词（超长 Latin 串 / camelCase 跳变）|

### `audit` —— 机械体检（与写回闸门同一套检查）

硬伤 `empty` / `tag_mismatch`；风格警告 `halfwidth_punct`、`cjk_corner_quote`、`ascii_ellipsis`、`inner_space`、
`identical_untranslated`、`too_short` / `too_long`（Han 字数 ÷ 源文词数的长度比，抓漏译与注水）。
CJK 相关检查只对含 CJK 的译文生效。`glossary lint` 则查表本身：alias 带头衔、两人共用 alias、同姓角色、重复/缺译名术语。

**推荐闭环**：`verify` 清表内硬伤 → `audit` 机械体检 → `glossary lint` 查表 → `scan --mode all` 发现表外问题 →
**把确认的真名补进词汇表** → 再 `verify`（这下表全了，能守住）。

### `repair` —— 存量项目的行内标记修复

v1.4.1 及更早的 epub 解析用 `soup.get_text(strip=True)`，会丢掉行内斜体/粗体，
并把片段间空格挤掉（`her <i>blade</i> fell` → `herbladefell`）。**v1.5.0 已在解析层修复**；
存量项目不必重新解析（那会丢译文）：

```bash
<PFX> -m ainiee_translate.repair work/cache.json               # 预览
<PFX> -m ainiee_translate.repair work/cache.json --apply       # 写入（自动备份）
<PFX> -m ainiee_translate.repair work/cache.json --list-marked # 列出译文需重做的段
```

---

## 开发

```bash
git clone https://github.com/xuanji86/ainiee-translate-skill.git
cd ainiee-translate-skill
PYTHONPATH=src python -m pytest -q      # 90 tests
./build.sh                              # src/ → skills/ 同步（含漂移守卫）
```

**布局**：`src/ainiee_translate/` 是**唯一源**；`build.sh` 用 rsync 同步进
`skills/ainiee-translate/scripts/` 并校验无漂移。`SKILL.md` 与 `references/` 直接住在
`skills/ainiee-translate/` 下，不经同步。改完 `src/` 后**务必跑一次** `./build.sh`。

设计文档：[docs/specs/2026-05-20-ainiee-translate-skill-design.md](docs/specs/2026-05-20-ainiee-translate-skill-design.md)

---

## 许可证

[GNU AGPL-3.0-only](LICENSE) · Copyright (C) 2026 Anji Xu

本项目把 [AiNiee](https://github.com/NEKOparapa/AiNiee) 的解析/导出模块当库使用；AiNiee 同为 AGPL-3.0。
