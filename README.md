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

## 为什么

实测：整本约 ~302K token，对比经 API 跑同书的 1–2M，约 **5× 更省**（省在不重发提示词/术语）；质量与原管线相当，**全局一致性更好**（去重、术语一致、抓漏译）。

## 设计文档

[docs/specs/2026-05-20-ainiee-translate-skill-design.md](docs/specs/2026-05-20-ainiee-translate-skill-design.md)

> 状态：v1.3.0 — 跨平台（Claude Code / Codex）+ 模块化 + AiNiee profile 导入 + 导入已有项目/缓存 + 斜杠命令菜单 + 润色 pass（含多 agent 并行翻译）。

## 许可证

[GNU AGPL-3.0-only](LICENSE)。Copyright (C) 2026 Anji Xu。

本项目把 [AiNiee](https://github.com/NEKOparapa/AiNiee) 的解析/导出模块当库使用；AiNiee 同为 AGPL-3.0 许可。
