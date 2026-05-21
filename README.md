# ainiee-translate

独立、**Agent 原生**的小说翻译系统（**任意源 → 目标语言**，不限中译）——工作方式类似 [AiNiee](https://github.com/NEKOparapa/AiNiee)，但**不依赖 AiNiee 应用运行**（无 GUI / HTTP / MCP）。由**编码 agent 本身（Claude Code / Codex）**充当翻译引擎，跑在订阅额度上，而非按 token 计费的外部 API。

## 安装

**前置依赖（必读）**：解析/导出复用本地 [AiNiee](https://github.com/NEKOparapa/AiNiee) 仓库当库，所以需要一份本地 AiNiee 仓库及其 venv：

```bash
git clone https://github.com/NEKOparapa/AiNiee.git    # 并按其说明建好 .venv、装好依赖
```

### 方式一：作为 Claude Code 插件安装（推荐）

```text
/plugin marketplace add xuanji86/ainiee-translate
/plugin install ainiee-translate@ainiee-translate
```

之后按 `skills/ainiee-translate/SKILL.md`「前置依赖与安装」设三个环境变量（`SKILL_DIR` 指向已安装的技能目录、`AINIEE_REPO` 指向本地 AiNiee 仓库、`AINIEE_PY` 指向 AiNiee venv 的 python），即可对它说「用 agent 翻译这本 epub」。更新：`/plugin marketplace update ainiee-translate` 后 `/reload-plugins`。

### 方式二：手动安装（不走插件）

```bash
git clone https://github.com/xuanji86/ainiee-translate.git
cp -r ainiee-translate/skills/ainiee-translate ~/.claude/skills/    # 个人技能目录
```

技能自带管道脚本（`skills/ainiee-translate/scripts/`），无需 `pip install`；同样设好上面三个环境变量即可。

### 方式三：在 Codex（OpenAI Codex CLI）中使用

SKILL.md 是跨平台标准格式，可直接装进 Codex 的技能目录（`~/.codex/skills`），Codex 会自动发现：

```bash
git clone https://github.com/xuanji86/ainiee-translate.git
ln -s "$PWD/ainiee-translate/skills/ainiee-translate" ~/.codex/skills/ainiee-translate
```

设好 `SKILL_DIR`（指向 `~/.codex/skills/ainiee-translate`）、`AINIEE_REPO`、`AINIEE_PY`，对 Codex 说「用 ainiee-translate 翻译这本 epub」即可。工具名对照（Bash→shell、Task→spawn_agent…）、多 agent 并行所需的 `multi_agent` 配置见 [`skills/ainiee-translate/references/codex-tools.md`](skills/ainiee-translate/references/codex-tools.md)。

## 它做什么

- 复用 AiNiee 的 `ModuleFolders.Domain` 解析/导出模块**当库**（epub 等格式），不跑其应用。
- 取 AiNiee 公共术语表为 seed，**清洗并锁定**一张工作权威表（去重、归一、人名/地名分类）。
- 由 agent 按 **AiNiee 原生提示词 ＋ 用户自定义提示词（自己写规则，如人名/头衔/风格，复用 AiNiee 配置或手写）＋ 锁定表** 逐章翻译，写回缓存并导出成品。
- 状态驱动、可恢复、可跨时间窗；三种介入模式（抽样自动 / 每章过目 / 全自动）。
- **导入已有项目**：直接导入 AiNiee 的工程缓存（`AinieeCacheData.json`）或既有 `cache.json`，接着续翻 / 润色 / 校验 / 重新导出（缓存自带原书路径，导出无需再指）。
- **模块化**：把整套任务设置（翻译/润色提示词、词汇表、禁翻表、风格、源/目标语言）存成可复用**模块**（`~/.ainiee-translate/modules/`），一个插件应对不同书；可**一键从 AiNiee profile 导入**。
- **命令菜单**：装成插件后用 `/ainiee-translate:*` 斜杠命令完成导入/切换模块、生成提示词、翻译、**润色**、导出、校验等（`/ainiee-translate:menu` 看清单）。

## 命令

分两层：**斜杠命令**（装成插件后用，`/ainiee-translate:*`）和它们底层调用的 **Python CLI**（Codex / 手动 / 调试用）。多数命令需先设好 `AINIEE_REPO`、`AINIEE_PY`、`SKILL_DIR` 三个环境变量（见上「安装」）。

### 斜杠命令（13 个）

**翻译流程**

| 命令 | 用法 | 作用 |
|------|------|------|
| `/ainiee-translate:translate` | `<输入文件> [模块名]` | 端到端翻译一本 epub/txt（解析→词汇表→翻译→导出→校验）|
| `/ainiee-translate:import-project` | `[list \| <AinieeCacheData.json 或项目ID> <项目目录>]` | 导入已有项目（AiNiee 缓存或既有 cache.json）继续翻译/润色/校验/导出 |
| `/ainiee-translate:glossary` | `[--config PATH] [--analysis PATH]` | 从 AiNiee 配置/profile 构建并锁定工作词汇表 |
| `/ainiee-translate:polish` | `[批大小]` | 对已翻译文本跑润色 pass（按模块润色提示词二次加工）|
| `/ainiee-translate:export` | `<原始输入文件>` | 把翻译好的缓存导出为成品 epub/txt |
| `/ainiee-translate:verify` | （无参数）| 校验残留规则违规（漏译、人名未保留）|
| `/ainiee-translate:status` | （无参数）| 查看项目状态（已绑模块 / 未译·已译计数 / 续跑点）|

**模块与提示词**

| 命令 | 用法 | 作用 |
|------|------|------|
| `/ainiee-translate:import-profile` | `<profile.json> <模块名>` | 导入 AiNiee profile/config 为可复用模块 |
| `/ainiee-translate:module` | `<list\|show\|create\|load> [名字] [--work 项目目录]` | 管理模块（列出/查看/新建/加载进项目）|
| `/ainiee-translate:switch-prompt` | `[模块名]` | 切换当前项目使用的模块/提示词 |
| `/ainiee-translate:show-prompt` | `[模块名]` | 查看模块的提示词与词汇表摘要 |
| `/ainiee-translate:gen-prompt` | `<translate\|polish> [模块名]` | 让 agent 帮你起草翻译/润色提示词（AiNiee 风格）写进模块 |
| `/ainiee-translate:menu` | （无参数）| 显示命令菜单 |

### 底层 Python CLI

前缀 `<PFX>` = `AINIEE_REPO="$AINIEE_REPO" PYTHONPATH="$SKILL_DIR/scripts" "$AINIEE_PY"`，调用形如 `<PFX> -m ainiee_translate.<模块> …`：

| 模块 | 用法 | 作用 |
|------|------|------|
| `parse` | `--input <书> --type AutoType --out <cache.json>` | 解析 epub/txt 成缓存 |
| `glossary` | `--config <config.json> [--analysis <路径>] --out <locked.json>` | 构建锁定词汇表 |
| `batch` | `read <cache> --size N` · `read-translated <cache> --size N` · `write <cache> <译文.json>` | 取未译批 / 取待润色批 / 写回译文 |
| `prompt` | `--config <config> [--out F] [--translate-system\|--polish]` | 汇总用户自定义/系统/润色提示词 |
| `module` | `list` · `show <名>` · `create <名> [--source-language X --target-language Y]` · `load <名> [--work DIR]` | 模块管理 |
| `profile` | `import --profile <p.json> --name <名> [--target-language X] [--force]` | profile → 模块 |
| `project` | `list [--ainiee-cache-dir DIR]` · `import (--ainiee <ID>\|--cache <路径>) --work <目录>` | 列出/导入已有项目 |
| `polish` | `write <cache> <润色.json>` | 写回润色结果（状态→POLISHED）|
| `export` | `--cache <cache> --output <目录> --input <原书>` | 导出成品 |
| `verify` | `<cache> <locked.json>` | 校验漏译/人名未保留 |

## 构建模块

**模块**把一整套任务设置（翻译/润色提示词、词汇表、禁翻表、风格、源/目标语言）打包成一个可复用、可切换的文件夹，让同一个插件应对不同书。模块默认放在 `~/.ainiee-translate/modules/<名字>/`（可用环境变量 `AINIEE_TRANSLATE_HOME` 覆盖根目录）。

### 模块目录结构

```
~/.ainiee-translate/modules/<名字>/
  module.json          # 元数据 + 清单（名字、源/目标语言、各开关、来源）
  translate_prompt.md  # 翻译提示词（AiNiee 风格；加载后即项目里的 user_prompt.md）
  polish_prompt.md     # 润色提示词（可选；没有则不提供润色）
  glossary.locked.json # 锁定词汇表 {characters, terms, non_translate}
  style.md             # 写作风格/世界观（可选，自由文本）
  examples.json        # few-shot 示例（可选）
```

`glossary.locked.json` 的形状：

```json
{
  "characters": [
    {"canonical": "James Marlow", "render": "James Marlow", "aliases": ["Marlow"], "gender": "M", "note": "舰长"}
  ],
  "terms": [
    {"src": "Korin", "dst": "科林", "category": "race"},
    {"src": "Highmark", "dst": "Highmark", "keep_source": true, "category": "place"}
  ],
  "non_translate": [{"marker": "<i>", "category": "tag"}]
}
```

- `characters[].render`：人名最终写法（人名通常 `render == canonical`，即保留原文）。
- `terms[].keep_source: true`：该词保持原文不译（`dst == src` 时自动标记）。
- `non_translate[].marker`：原样保留的标记/占位符。

### 三种建法

**① 从 AiNiee profile 导入（最快）** —— 一把梭把语言、翻译/润色提示词、术语表、禁翻表全提进来：

```bash
<PFX> -m ainiee_translate.profile import --profile <profile.json> --name mybook
# 或插件里：/ainiee-translate:import-profile <profile.json> mybook
<PFX> -m ainiee_translate.module show mybook        # 检查导入结果
```

**② 新建空模块再填** —— 适合从零手写规则：

```bash
<PFX> -m ainiee_translate.module create mybook --source-language English --target-language 简体中文
# 然后编辑 ~/.ainiee-translate/modules/mybook/ 下的：
#   translate_prompt.md   写你的翻译规则（人名/头衔/风格/标点等）
#   polish_prompt.md      写润色规则（可留空 = 不润色）
#   glossary.locked.json  填角色/术语/禁翻
```
不想手写提示词？用 `/ainiee-translate:gen-prompt translate mybook`（或 `polish`）让 agent 访谈你后起草，直接写进模块。

**③ 直接放文件** —— 按上面的目录结构手动建文件夹也行（`module.json` 可参照已有模块）。

### 加载 / 切换

把模块拷进某个翻译项目（自包含），翻译时即生效：

```bash
<PFX> -m ainiee_translate.module load mybook --work ~/my-project
# 或插件里：/ainiee-translate:switch-prompt mybook
```

加载会把模块的 `translate_prompt.md`→`user_prompt.md`、`polish_prompt.md`、`glossary.locked.json` 拷进 `~/my-project/work/`（已存在则先时间戳备份），之后 `translate` / `polish` 自动遵循「AiNiee 原生原则 ＋ 模块提示词 ＋ 锁定词汇表」。`module list` 看所有模块，`/ainiee-translate:show-prompt mybook` 看摘要。

> 模块可放进独立 git 仓库分发：`git clone <repo> ~/.ainiee-translate/modules/<名字>` 即装。

## 为什么

实测：整本约 ~302K token，对比经 API 跑同书的 1–2M，约 **5× 更省**（省在不重发提示词/术语）；质量与原管线相当，**全局一致性更好**（去重、术语一致、抓漏译）。

## 设计文档

[docs/specs/2026-05-20-ainiee-translate-skill-design.md](docs/specs/2026-05-20-ainiee-translate-skill-design.md)

> 状态：v1.3.0 — 跨平台（Claude Code / Codex）+ 模块化 + AiNiee profile 导入 + 导入已有项目/缓存 + 斜杠命令菜单 + 润色 pass（含多 agent 并行翻译）。

## 许可证

[GNU AGPL-3.0-only](LICENSE)。Copyright (C) 2026 Anji Xu。

本项目把 [AiNiee](https://github.com/NEKOparapa/AiNiee) 的解析/导出模块当库使用；AiNiee 同为 AGPL-3.0 许可。
