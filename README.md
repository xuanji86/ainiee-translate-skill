<div align="center">

# ainiee-translate

**Agent 原生的长篇翻译管线** —— 让编码 agent 本身当翻译引擎，端到端译完一本书。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.18.0-green.svg)](https://github.com/xuanji86/ainiee-translate-skill/releases)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)](pyproject.toml)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-333.svg)](skills/ainiee-translate/references/codex-tools.md)

[安装](#安装) · [快速开始](#快速开始) · [工作原理](#工作原理) · [并行翻译](#并行翻译与项目状态) · [命令](#命令) · [模块](#模块) · [质量闭环](#质量闭环) · [推荐流程](#推荐流程与模型)

</div>

---

## 这是什么

工作方式类似 [AiNiee](https://github.com/NEKOparapa/AiNiee)，但**不跑 AiNiee 应用**（无 GUI / HTTP / MCP）：翻译由**编码 agent 自己**（Claude Code / Codex）完成，一组确定性 Python 脚本负责解析、划定范围、批次调度、词汇表锁定、写回闸门与导出。

支持**任意源语言 → 任意目标语言**，不限中译。

|  | 经外部 API 翻译 | ainiee-translate |
|---|---|---|
| 计费 | 按 token 付费 | 走 agent 的订阅额度，不调用任何外部翻译 API |
| 术语一致性 | 每批各自为政，易漂移 | 全书共用一张**锁定词汇表**，机械校验 |
| 中断恢复 | 自行处理 | 状态驱动（`translation_status`），重跑自动续上 |
| 富文本 | 常被压平 | 斜体/粗体按源书写法还原；epub 段内的链接、脚注号、锚点、行内图片用 `⟦n⟧` 占位符保护 |
| 质量兜底 | 无 | 写回闸门（空译 / 标记不成对 / 占位符不符即拒收）+ `verify` + `audit` + `scan`（五种模式）+ 对抗性审核 + 时间戳备份 |

## 安装

解析/导出模块已随技能打包（`_vendor/`，AiNiee 读写器的改写副本），**无需克隆 AiNiee 仓库**。按顺序三步：

**1. 建 venv 装依赖**（Python ≥ 3.12）

```bash
python3 -m venv ~/.venvs/ainiee-translate
~/.venvs/ainiee-translate/bin/pip install \
  msgspec beautifulsoup4 lxml rich openpyxl polib python-pptx chardet
```

**2. 设 `AINIEE_PY`**（写进 shell profile，或 Claude Code `~/.claude/settings.json` 的 `env`）

```bash
export AINIEE_PY=~/.venvs/ainiee-translate/bin/python
```

**3. 装插件**（Claude Code，推荐）

```text
/plugin marketplace add xuanji86/ainiee-translate-skill
/plugin install ainiee-translate@ainiee-translate
```

更新：`/plugin marketplace update ainiee-translate` 后 `/reload-plugins`。

自带 15 种格式：`epub` `txt` `md` `docx` `xlsx` `pptx` `csv` `srt` `vtt` `ass` `lrc` `po` `json` `rpy` `trans`。
仅 **PDF 与 Windows Office 转换**未自包含——需要时设 `AINIEE_REPO` 回退到一份 AiNiee checkout。

### 其他安装方式

这两种方式**只有技能 + CLI，没有斜杠命令**（`commands/` 只随插件走）；对 agent 说「用 agent 翻译这本 epub」触发技能即可。

```bash
git clone https://github.com/xuanji86/ainiee-translate-skill.git
# Claude Code：手动装为技能（更新：git pull 后重新 cp）
cp -r ainiee-translate-skill/skills/ainiee-translate ~/.claude/skills/
# Codex：软链（更新：git pull）
ln -s "$PWD/ainiee-translate-skill/skills/ainiee-translate" ~/.codex/skills/ainiee-translate
```

Codex 的工具名对照（Bash→shell、Task→spawn_agent…）与多 agent 配置见 [`references/codex-tools.md`](skills/ainiee-translate/references/codex-tools.md)；环境变量以本页为准。

### 环境变量

| 变量 | 说明 |
|---|---|
| `AINIEE_PY` | **必需**。上面 venv 的 python，斜杠命令用它跑脚本 |
| `AINIEE_REPO` | 可选。AiNiee checkout 路径，仅 PDF / Windows Office 回退时用 |
| `AINIEE_TRANSLATE_HOME` | 模块与进度行的根目录，默认 `~/.ainiee-translate` |
| `AINIEE_BACKUP_KEEP` | 每个文件保留的时间戳备份数，默认 `10`，`0` = 不清理 |
| `AINIEE_CACHE_DIR` | `project list/import --ainiee` 扫描的 AiNiee ProjectCache 目录 |
| `STATUSPANE_PROGRESS_DIR` | `progress` 写 [claude-statuspane](https://github.com/xuanji86/claude-statuspane) 进度条的目录，默认 `~/.claude/statuspane/progress` |

手动跑 CLI 时的约定（下文 `<PFX>`）：`SKILL_DIR` 指向技能目录——手动安装是 `~/.claude/skills/ainiee-translate`，插件安装在 `~/.claude/plugins/cache/ainiee-translate/ainiee-translate/<版本>/skills/ainiee-translate`。代码本身不读 `SKILL_DIR`。

```bash
# <PFX> = PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY"，自检：
PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY" \
  -c "from ainiee_translate import io_dispatch; print('formats OK:', io_dispatch.supported_extensions())"
```

## 快速开始

**先有一个模块**（提示词 + 词汇表，见[模块](#模块)），再翻译：

```text
# 有 AiNiee profile / config.json：一步导入
/ainiee-translate:import-profile ~/profiles/mybook.json mybook

# 没有 AiNiee：建空模块，让 agent 访谈后起草提示词
/ainiee-translate:module create mybook
/ainiee-translate:gen-prompt translate mybook

# 翻译
/ainiee-translate:translate ~/books/mybook.epub mybook
```

它会走完 解析 → 划定范围（预览后确认）→ 词汇表 → 抽样确认 → 逐章翻译 → 导出 → 校验。空模块的词汇表是空的：开译前 `scan --mode pending` 找出反复出现的新词先定名，翻译中各组记下的新词用 `glossary merge-newterms` 并入。

开始前 agent 会与你确认**介入模式**：

| 模式 | 行为 | 适用 |
|---|---|---|
| **A 抽样自动** | 先译约 1 章给你确认风格，之后自动跑完；遇表外歧义实体停下询问 | 首次翻新书（默认）|
| **B 每章过目** | 每章译完给你点头后才写回 | 需要细粒度监控 |
| **C 全自动** | 一气跑完，歧义记入 `needs_review` 最后统一报告 | 风格已熟 |

译完想再抓一轮 AI 味和误译：`/ainiee-translate:review 1-<总段数>`（见[质量闭环](#质量闭环)）。已有 AiNiee 工程缓存或旧 `cache.json`：`/ainiee-translate:import-project` 接管后续翻 / 润色 / 校验 / 重新导出。

## 工作原理

```
书 ─▶ parse ─▶ scope ─▶ glossary ─▶ translate ─▶ polish ─▶ review ─▶ export --finalize ─▶ 成品
        │        │          │         ▲    │      (可选)    (可选)          │
   cache.json  非正文     锁定词汇表   │    │   Reviewer→闸门→Challenger    元数据 / 固定 identifier
  (含原书HTML) 标为排除   (人工复核)  读批次  写回闸门                       链接·锚点·段落核对
                                      └─┬──┘
                                  agent = 翻译引擎            质量闭环：verify · scan · audit · review
                              (规则 + 提示词 + 词汇表)
```

- **状态驱动**：每段有 `translation_status`——`0` 未译、`1` 已译、`2` 已润色、`7` 排除。`batch read` 只返回未译段，中断后重跑天然续上。
- **只译该译的**：`scope` 按书内文件判定，只留正文（章节、序幕/尾声/间章、分部页）、紧邻正文的背景说明页和两份目录；书评、版权、献词、题记、致谢、作者简介、广告页标为排除，导出保留原文。先预览，确认后 `--apply`，`--keep/--drop ID` 纠错。
- **写回有闸门、有锁、有备份**：空译、`<i>`/`<b>` 数量不符或反序/交叉嵌套（含与 `⟦n⟧…⟦/n⟧` 交叉）、`⟦n⟧` 占位符缺/多/改号、未知 index 一律拒收（`--allow-tag-mismatch` 只放行标记数，不放行占位符和嵌套错乱）；文件锁 + 原子写（Windows 无 `fcntl`，锁为空操作）；有实际改动才写时间戳备份 `cache.json.bak.YYYYMMDD_HHMMSS`（全部拒收或内容没变的写入不备份，重试坏文件不会把还原点轮转掉）。
- **富文本保真**：行内斜体/粗体在 `source_text` 里统一成 `<i>…</i>` / `<b>…</b>`，导出时按该段原文的实际写法（`<i>`、`<em>`、`<span class="italic1">` …）还原。epub 段内的超链接、脚注号、id 锚点、行内图片写成 `⟦n⟧`（整个元素，不译）或 `⟦n⟧…⟦/n⟧`（包住的文字照译），原 HTML 存在 `extra.epub_tokens`，导出时还原。
- **定稿导出**：`export --finalize`（epub）写目标语言元数据、**固定的 `dc:identifier`**（重导覆盖阅读器里的原条目而不是新增一本）、查 XML / 链接 / 锚点、核对每个已译段都在成品里，可 `--deliver` 复制到交付路径。

### 项目目录

每本书一个工作目录，下设 `work/`（状态）与 `out/`（成品）：

```
work/cache.json            # 全书分段、译文、状态、原书 HTML（及 .bak.* 备份）
work/glossary.locked.json  # 锁定词汇表
work/user_prompt.md        # 翻译提示词（模块加载而来）
work/polish_prompt.md      # 润色提示词
work/active_module.json    # 本项目绑定的模块
work/decisions.json        # 已定口径 / 原文笔误 / 标记例外 / 本书 lint 规则
work/provenance.jsonl      # batch apply --source 的修正留痕
work/export.json           # 成品书名、语言、固定 identifier、交付路径
work/progress.jsonl        # 每次写回的事件（进度面板读它）
work/par/                  # 并行分组：grp_N_src.json、bundle_N.md、trans_N.jsonl、newterms_N.txt
work/review/               # 对抗性审核：config.json、EXAMPLES.md、groups/、findings / verdicts / apply
```

## 并行翻译与项目状态

风格用模式 A 锁定后，可派多个 subagent 并发翻不同章节（实测 11 章 1704 段 / 7 agent / 约 9 分钟）。编排的每一步都是一条命令：

```bash
<PFX> -m ainiee_translate.scan work/cache.json --locked work/glossary.locked.json --mode pending   # 开译前找新词，先定名进表
<PFX> -m ainiee_translate.batch split work/cache.json --target 300 --out-dir work/par --context 20 # 按章节边界分组 + 前文上下文
<PFX> -m ainiee_translate.batch bundle work/cache.json work/par/grp_*_src.json --include work/user_prompt.md
#   … 每个 subagent 读一次 bundle_N.md，写一次 trans_N.jsonl + newterms_N.txt …
<PFX> -m ainiee_translate.batch validate work/par/grp_1_src.json work/par/trans_1.jsonl --cache work/cache.json
<PFX> -m ainiee_translate.glossary merge-newterms --locked work/glossary.locked.json work/par/newterms_*.txt   # 预览；跨组译法不同、或与表内已有译法不同都报 CONFLICT
<PFX> -m ainiee_translate.batch write work/cache.json work/par/trans_*.jsonl
<PFX> -m ainiee_translate.glossary merge-newterms --locked work/glossary.locked.json work/par/newterms_*.txt --apply
```

`bundle_N.md` = 交付约定 + 规则卡 + 本组词汇表 + 前文 + 原文，agent **读一次、写一次**，校验交给主控。铁律：**subagent 绝不写 `cache.json`**，由主控 validate 后一次写回。`progress --watch` 看每组的状态、速率与卡死。派发 prompt 模板、Workflow 脚本模板见 [`references/parallel_translation.md`](skills/ainiee-translate/references/parallel_translation.md)。

**项目状态与留痕**（所有阶段共读）：

- `decisions.json`（`state` 命令维护）：`settled` 已定口径、`errata` 原文笔误、`tag_exceptions` 段级标记例外、`lint` 本书规则；`state card` 出一张规则卡，`batch bundle` 与 `review rules` 自动带上。
- `batch apply` 是唯一的修正写回入口：保住每段状态，可只给 `patches`；`--source` 记进 `provenance.jsonl`。来源为 `dual` / `codex` / `user` / `editor` 的修正受保护——之后的审核提议若要把删掉的说法改回去，闸门以 `E_reverts_fix` 拒收；`polish write`、`batch write` 和不带受保护来源的 `batch apply` 同样拒收（`reverts_fix`）。`batch write` 只写未译段，已译段的修正走 `batch apply`。
- 复审只看改过的段：`batch split --changed-since <审前快照>` / `cache dump --changed-since`。

## 命令

### 斜杠命令（18 个，仅插件安装）

| 命令 | 参数 | 作用 |
|---|---|---|
| `/ainiee-translate:translate` | `<输入文件> [模块]` | 端到端翻译一本书 |
| `/ainiee-translate:import-project` | `[list \| <缓存路径或 AiNiee 项目ID> <项目目录>]` | 导入已有项目继续处理 |
| `/ainiee-translate:glossary` | `--config PATH [--analysis PATH]` | 从 AiNiee 配置/profile 构建锁定词汇表（`--config` 必填；用模块时词汇表随模块加载，不必重建）|
| `/ainiee-translate:polish` | `[批大小]` | 润色 pass（`已译 → 已润色`，导出自动采用润色文本）|
| `/ainiee-translate:export` | `<原始输入文件>` | 定稿导出（固定带 `--finalize`，仅 epub；其他格式用 CLI `export` 不带该参数）|
| `/ainiee-translate:status` | — | 项目状态（模块 / 计数 / 续跑点）|
| `/ainiee-translate:progress` | `[--line \| --json \| --serve 8765 --open]` | 进度面板：全书 + 每个并行组 |
| `/ainiee-translate:verify` | — | 漏译、锁定人名未保留、术语译名缺失 |
| `/ainiee-translate:scan` | `[discover\|terms\|strays\|merges\|pending\|all]` | 补 verify 盲区，默认 `all` |
| `/ainiee-translate:audit` | `[--allow-tag-mismatch]` | 机械体检，报告写 `work/audit.json` |
| `/ainiee-translate:repair` | — | 修复存量 epub 项目的行内标记与空格 |
| `/ainiee-translate:review` | `<起-止段号> [--target 140] [--benchmark <校对前备份>]` | 对抗性审核 |
| `/ainiee-translate:import-profile` | `<profile.json> <模块>` | AiNiee profile → 模块 |
| `/ainiee-translate:module` | `<list\|show\|create\|load> [名] [--work 目录]` | 模块管理 |
| `/ainiee-translate:switch-prompt` | `[模块]` | 切换当前项目的模块 |
| `/ainiee-translate:show-prompt` | `[模块]` | 查看提示词与词汇表摘要 |
| `/ainiee-translate:gen-prompt` | `<translate\|polish> [模块]` | 让 agent 起草提示词 |
| `/ainiee-translate:menu` | — | 命令菜单 |

### Python CLI

形如 `<PFX> -m ainiee_translate.<模块> …`；每个模块与子命令都支持 `--help`，以它为准。

<details>
<summary>CLI 参考（展开）</summary>

```
parse       --input I [--type AutoType] [--exclude 通配,…] [--out cache.json] [--force]
scope       <cache> [--apply] [--keep ID…] [--drop ID…] [--force]
glossary    build --config C [--analysis A] --out O
            filter --locked L --for SRC_JSON… --out O
            lint --locked L
            merge-newterms --locked L FILES… [--apply] [--category C]
prompt      --config C [--out F] [--translate-system] [--polish]
batch       read <cache> [--size N]  |  read-translated <cache> [--size N]
            split <cache> [--target 300] [--out-dir D] [--context N] [--stage translate|polish|review]
                  [--range A-B] [--prefix P] [--changed-since OLD_CACHE]
            bundle <cache> SRC_JSON… [--stage …] [--locked L] [--include MD…] [--out-dir D]
            validate <src.json> <trans.json|jsonl> [--cache C] [--allow-tag-mismatch]
            write <cache> FILES… [--overwrite] [--force] [--allow-tag-mismatch]
            apply <cache> FILES… [--source S] [--reason R] [--force] [--allow-tag-mismatch]
polish      write <cache> FILES… [--force] [--allow-tag-mismatch]
cache       stats <cache>  |  show <cache> --range A-B [--status …] [--width N]
            dump <cache> [--range A-B] --out F [--status …] [--changed-since OLD_CACHE]
            set-status <cache> --range A-B --from N --to N [--apply]     （N ∈ 0/1/2/7）
            fill-dupes <cache> [--max-words N] [--apply]                 （忽略 ⟦n⟧ 占位符匹配并按目标首尾重包；占位符在文中的段跳过并列出；过写回闸门，拒收的列出、退出码 1）
state       show <cache>  |  settle <cache> --dst D [--src S] [--note N]
            errata <cache> IDX --note N  |  tag-exception <cache> IDX --reason R
            lint-rule <cache> NAME --re REGEX [--msg M]  |  card <cache> [--range A-B]
module      list | show <名> | create <名> [--source-language X] [--target-language Y] [--title T]
            load <名> [--work D]
profile     import --profile P --name N [--target-language X] [--force]
project     list [--ainiee-cache-dir D]
            import (--cache 路径 | --ainiee 项目ID) --work W [--ainiee-cache-dir D]
export      --cache C --output O --input I [--finalize [--allow-partial]] [--title T] [--name N] [--deliver PATH]
verify      <cache> <locked> [--json] [--out F] [--baseline F] [--write-baseline F]
scan        <cache> [--locked L] [--mode discover|terms|strays|merges|pending|all]
            [--min-merge-len N] [--min-count N] [--json] [--out F] [--top N]
audit       <cache> [--out F] [--json] [--allow-tag-mismatch] [--samples N]
repair      <cache> [--apply] [--list-marked] [--limit N]
precedents  <cache> --for SRC_JSON… [--locked L] [--out F] [--title T]
progress    [cache] [--par D] [--stall 秒] [--watch|--once|--line|--json|--serve [PORT]]
            [--open] [--out F] [--interval 秒]
review      （除 dual-merge 外都接受 [--dir DIR] [--run RUN]）
            rules <cache> GROUP… [--locked L] [--examples MD…]
            blind <cache> GROUP…  |  hints <cache> FLAGS_JSONL…  |  coverage <cache> GROUP…
            check <cache> GROUP… [--file F]
            pre <cache> FINDINGS_JSONL…
            segs <cache> FINDINGS_PRE_JSONL… [--mode all|tier|slim] [--tier] [--min-sev N] [--sample F]
            inventory <cache> --range A-B [--locked L] [--min-count N] [--max-terms N]
            stats <cache> GROUP…  |  final <cache> GROUP…  |  score <cache> GROUP…
            merge <cache> GROUP… [--out F]
            pick <cache> GROUP… [--ids …] [--min-sev N] [--exclude …] [--out F]
            import <cache> FILE --group G [--source S]
            dual-merge <cache> FILES… --out F
            benchmark <cache> --baseline OLD_CACHE --range A-B
            log <cache> --stage S [--group G] [--model M] [--agent A] [--file F] [--note N]
                [--tokens N] [--segments N]  |  ledger <cache>
```

`verify` / `scan` / `audit` 默认向 stdout 打摘要；脚本解析请加 `--json`。`batch write` / `apply` / `polish write` 接受多个 JSON 或 JSONL 文件。

- 写回只在有实际改动时备份：闸门全部拒收、或内容与状态都没变的写入不产生 `.bak`。
- `batch write` 只写未译段：已译 / 已润色 / 已排除的段拒收（`already_translated` / `already_polished` / `excluded`），修正走 `batch apply`，确要重译加 `--overwrite`（`--force` 不放行这一条）。
- `batch write` / `polish write` / 不带受保护来源的 `batch apply`：新文本带回受保护修正（`dual` / `codex` / `user` / `editor`）删掉的说法即拒收 `reverts_fix`，`--force` 也不放行；确要改回用 `batch apply --source user`。
- `parse` 不覆盖已有译文的 cache（`--force` 先备份再覆盖）；一段都没解析出来时报错退出、不落盘。
- `export` 打印未译段计数；`--finalize` 下有未译段即失败（`--allow-partial` 放行）；有文件没有对应 writer 时非零退出。
- `scope` 对单个 txt（无文件结构）和非拉丁文字源文不做判定；`--apply --keep ID` 会把该文件已排除、无译文的段恢复成未译。

</details>

## 模块

**模块**把一整套任务设置打包成可复用、可切换的文件夹，默认在 `~/.ainiee-translate/modules/<名字>/`：

```
module.json          # 元数据（语言对、各开关、来源）
translate_prompt.md  # 翻译提示词（加载后即项目里的 work/user_prompt.md）
polish_prompt.md     # 润色提示词
glossary.locked.json # 锁定词汇表 {characters, terms, non_translate}
```

`module load` 只把这三份内容文件拷进项目（已存在先时间戳备份；模块里空白的提示词、没有条目的词汇表不覆盖项目里已有的非空文件；模块词汇表缺了项目表里的条目时照常覆盖，打印少了几条）；`module create` 另建的空 `style.md` 目前管线不读——风格要求请写进 `translate_prompt.md`。

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
- `terms[].dst` —— 译名；可用 `a/b` 列出多个可接受译法。`keep_source: true` 表示保持原文不译。
- `non_translate[].marker` —— 原样保留的标记/占位符。

三种建法：

```bash
# ① 从 AiNiee profile 导入：语言、提示词、术语表、禁翻表一并带入
<PFX> -m ainiee_translate.profile import --profile <profile.json> --name mybook
# ② 新建空模块再填（提示词可用 /ainiee-translate:gen-prompt 起草）
<PFX> -m ainiee_translate.module create mybook --source-language English --target-language 简体中文
# ③ 按上面结构手建文件夹；模块也可独立成 git 仓库：git clone <repo> ~/.ainiee-translate/modules/<名字>

<PFX> -m ainiee_translate.module show mybook                      # 检查
<PFX> -m ainiee_translate.module load mybook --work ~/my-project  # 载入项目 work/
```

## 质量闭环

翻完不等于译对。机械工具各管一段，外加一道模型对抗的审核工序。

### `verify` —— 词汇表执行器

查三类：`empty_translation`（漏译）、`name_not_preserved`（锁定表人名消失）、`term_missing`（表里有译名的术语在源文出现，译文里却没有任何一个可接受译法；`rank` / `title` / `role` 类因人而异，不查）。复核过的误报存 `--write-baseline`，之后 `--baseline` 只看新增。

> ⚠️ **「verify 干净」≠「没有翻译错误」**。它只认**锁定表里登记过的**条目——没进表的名字它根本不知道要查。

### `scan` —— 发现器（补 verify 盲区）

| 模式 | 抓什么 |
|---|---|
| `discover` | 表外专名：`inconsistent`（时而保留时而消失，**高置信优先处理**）/ `never_preserved`（全程被音译的真名 + 合法意译的术语，需人眼分） |
| `terms` | **反向漏译**——词汇表有译名的术语，个别段却留成原文 |
| `strays` | **幻觉插入**——译文里出现、原文却没有的拉丁 token（凭空错名）|
| `merges` | 丢空格的粘连词（超长拉丁串 / camelCase 跳变）|
| `pending` | **开译前**：未译部分里反复出现、已译部分没有、表里也没有的新词，先定名再分组 |

`--mode all` = 前四种。

### `audit` 与 `glossary lint` —— 机械体检

`audit` 与写回闸门是同一套检查。硬伤：`empty`、`tag_mismatch`（`<i>`/`<b>` 数量与源文不符，或标记反序 / 彼此交叉 / 与 `⟦n⟧…⟦/n⟧` 交叉——后者导出即坏 XHTML，标记例外也不放行）、`token_mismatch`。风格警告：`identical_untranslated`、`markup_leak`、`halfwidth_punct`、`halfwidth_period`、`cjk_corner_quote`、`ascii_ellipsis`、`single_dash`、`inner_space`、`odd_ascii_quotes`、`too_short` / `too_long`（长度比，抓漏译与注水），以及 `decisions.json` 里的本书 lint 规则。CJK 相关检查只对含 CJK 的译文生效。`glossary lint` 查表本身：alias 带头衔、两人共用 alias、同姓角色、缺 `render` 等。

**推荐闭环**：`verify` → `audit` → `glossary lint` → `scan --mode all` → **把确认的真名补进词汇表** → 再 `verify`（表全了，才守得住）。

### `review` —— 对抗性审核

机械检查抓不到「中文没错但味道不对」和「词汇表之外的误译」。`review` 把**找问题**和**否决问题**拆给互不通气的模型实例：

| 角色 | 激励 | 产出 |
|---|---|---|
| Blind Reader | 只读译文，像读者一样标出读着别扭的地方 | `flags_X.jsonl` |
| Reviewer | 奖励召回：对照源文逐条落实，引用源文证据，只报子串级替换 | `findings_X.jsonl`（A 误译 / B 硬伤 / C 翻译腔，含严重度）|
| Challenger | 奖励否决：原译没错 / 违反红线 / 引入新错 / 纯偏好 → reject | `verdicts_X.jsonl` |
| Consistency auditor | 只读术语清单，判同一原文词该不该一个译法 | `findings_D.jsonl` |

主控只跑机械半边：`batch split --stage review` 切组 → `review rules`（每组的词汇表/裁定切片）→ `blind` / `hints` → `coverage --todo` / `coverage`（逐段对读台账：每段都要有 ok 或问题结论，引文原样；第二轮起只读改过的段）→ Reviewer 写完跑只读的 `review check` 自检 → `review pre` 闸门（字段类型与 `severity` 1/2/3、id 不重复、`offending` 在现译中恰好一次、红线改动即拒、定稿术语只加不删（按出现次数计，词汇表 `a/b` 多译法逐个算）、标记成对、不动拉丁 token；finding 的 `flags` 只认本组盲读文件里**同一段**的 flag，其余清掉）→ `review segs --mode slim`（A/B 全部送 Challenger，有盲读佐证的 C/D 直接进过目表）→ `review stats` 复核否决率 → `review final`（A/B 进 `apply_X.json` → `batch apply`；C/D 进 `review_ALL.md` 给人勾选 → `review pick`）。第二轮起加 `--run <名>`，各轮文件互不撞名。

先在人工校对过的章节上 `review benchmark` + `score` 打分再铺全书（试点书：召回 71–75%、Challenger 精度 87–91%）。协议、红线配置、prompt 模板见 [`adversarial_review.md`](skills/ainiee-translate/references/adversarial_review.md) / [`review_taxonomy.md`](skills/ainiee-translate/references/review_taxonomy.md) / [`review_prompts.md`](skills/ainiee-translate/references/review_prompts.md)。

- **双模型意义审**：`cache dump` 给两个不同模型族各审一遍 → `review dual-merge` → 编辑出补丁 → `batch apply --source dual`。模板 [`review_workflow.js`](skills/ainiee-translate/references/review_workflow.js)。
- **外部审校**（Codex / 人工）：`review import` 把对方的 findings 收进同一道 `pre` 闸门。交接格式见 [`external_review.md`](skills/ainiee-translate/references/external_review.md)。

### `repair` —— 存量项目的行内标记修复

旧版解析会丢掉行内斜体/粗体并把片段间空格挤掉（`her <i>blade</i> fell` → `herbladefell`），也不认带编号的类名（`italic1`、`bold2`）。解析层已修复；存量项目不必重新解析（那会丢译文）：

```bash
<PFX> -m ainiee_translate.repair work/cache.json               # 预览
<PFX> -m ainiee_translate.repair work/cache.json --apply       # 写入（自动备份）
<PFX> -m ainiee_translate.repair work/cache.json --list-marked # 列出译文需重做的段
```

`repair` 只补 `<i>`/`<b>` 与空格，不会给存量项目补 `⟦n⟧` 占位符；已带占位符（新版解析）的段直接跳过。

## 推荐流程与模型

出版级质量的做法（两本书实测，详见 [`SKILL.md`](skills/ainiee-translate/SKILL.md)）：

| 阶段 | 做法 |
|---|---|
| 翻译 | 最强一档模型按章并行（`batch bundle` 读一次、写一次）；**正文不用最小档模型**——问题量高一个量级，token 也不省 |
| 意义审 | 换一个模型族再审一遍，或两家都审后 `review dual-merge`；单一审校必漏 |
| 风格审 | 对抗性审核，C/D 类用 `review pick --min-sev 2` |
| 复审 | 只审改过的段（`--changed-since`）|

预算紧时先砍「同族第二审」，意义审不砍。每个 agent 收工 `review log` 记 token，`review ledger` 出每阶段 token/段，下一本书按数据删层。

## 开发

```bash
git clone https://github.com/xuanji86/ainiee-translate-skill.git
cd ainiee-translate-skill
~/.venvs/ainiee-translate/bin/pip install pytest
~/.venvs/ainiee-translate/bin/python -m pytest
./build.sh                              # src/ → skills/ 同步（含漂移守卫）
```

**布局**：`src/ainiee_translate/` 是 Python 的**唯一源**；`build.sh` 用 rsync 同步进 `skills/ainiee-translate/scripts/` 并校验无漂移。`SKILL.md` 与 `references/` 直接住在 `skills/ainiee-translate/`，斜杠命令在 `commands/`，都不经同步。改完 `src/` 后**务必跑一次** `./build.sh`。

版本变化见 [Releases](https://github.com/xuanji86/ainiee-translate-skill/releases)；最初的设计稿在 [docs/specs/](docs/specs/2026-05-20-ainiee-translate-skill-design.md)（v1，仅供了解来历）。

## 许可证

[GNU AGPL-3.0-only](LICENSE) · Copyright (C) 2026 Anji Xu

`_vendor/` 下的读写器是 [AiNiee](https://github.com/NEKOparapa/AiNiee)（同为 AGPL-3.0）的 vendored 副本，剥离了其应用框架；来源 commit 与改动说明见 [`_vendor/NOTICE`](src/ainiee_translate/_vendor/NOTICE)。
