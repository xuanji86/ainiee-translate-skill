# 在 Codex（及其他 agent）中使用本技能

本技能的 `SKILL.md` 是跨平台标准格式，管道脚本是纯命令行（经 shell 调用），所以除 Claude Code 外也能在 **OpenAI Codex CLI** 里用。本文件给出 Codex 的安装方式与工具名对照。

## 安装到 Codex

Codex 的技能目录是 `$CODEX_HOME/skills`（默认 `~/.codex/skills`）。把本技能目录放进去（复制或软链整个文件夹）：

```bash
ln -s /path/to/ainiee-translate/skills/ainiee-translate ~/.codex/skills/ainiee-translate
ls ~/.codex/skills/ainiee-translate/SKILL.md     # 确认
```

再设三个路径变量（同 `SKILL.md`「前置依赖与安装」，只是 `SKILL_DIR` 指向 Codex 位置）：

```bash
export SKILL_DIR=~/.codex/skills/ainiee-translate
export AINIEE_REPO=/path/to/AiNiee
export AINIEE_PY=/path/to/AiNiee/.venv/bin/python
```

命令前缀 `<PFX>` 与自检命令完全照搬 `SKILL.md`。Codex 按 `SKILL.md` 的 `name`/`description` 自动发现本技能——直接说「用 ainiee-translate 翻译这本 epub」即可触发，之后照 `SKILL.md` 的步骤执行。

## 工具名对照（`SKILL.md` 写的是 Claude Code 名）

| `SKILL.md` 里写 | Codex 等价 |
|-----------------|-----------|
| `Bash`（跑命令） | 原生 shell（`shell` 工具） |
| `Read` / `Write` / `Edit`（文件） | 原生文件工具 / `apply_patch` |
| `Task`（派发 subagent，见步骤 5+ 并行） | `spawn_agent`（需开多 agent，见下） |
| 多个 `Task` 并发 | 多个 `spawn_agent` |
| Task 返回结果 | `wait` |
| Task 自动结束 | `close_agent`（释放槽位） |
| `TodoWrite`（进度跟踪） | `update_plan` |
| `Skill`（调用技能） | 技能原生加载，按说明执行即可 |

绝大多数步骤只是「跑一条 `<PFX> -m ainiee_translate.*` 命令」，与平台无关，照搬即可。

## 步骤 5+ 多 agent 并行（Codex）

并行翻译（`references/parallel_translation.md`）在 Codex 下要先开多 agent：

```toml
# ~/.codex/config.toml
[features]
multi_agent = true
```

- 用 `spawn_agent(agent_type="worker", message=…)` 派发每个章节范围的翻译子任务；`message` 里放「读 glossary+rules+style+输入 → 产出 `trans_N.json` + `newterms_N.txt`」的指令。用任务委派式措辞（"Your task is…"），必要时用 XML 标签包裹指令以提高遵从度。
- **唯一铁律不变**：subagent 只产出译文 JSON，**绝不** `batch write` 同一个 `cache.json`；由主控 agent 串行写回。
- 用 `wait` 收结果，`close_agent` 释放槽位。

## 斜杠命令（可选，通常不需要）

本仓库的 `commands/*.md` 是 Claude Code 插件命令（用 `${CLAUDE_PLUGIN_ROOT}`、`allowed-tools` 等）。Codex 的自定义提示词放在 `~/.codex/prompts/*.md`（`$1` / `$ARGUMENTS` 占位），但 **Codex 官方已把自定义提示词标为弃用、推荐用技能本身**。因此在 Codex 里建议直接触发技能 / 用自然语言下指令，而不必移植这些命令。如确实想要，可手动把某条命令正文改写成 `~/.codex/prompts/<名字>.md`，并把 `${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts` 换成 `$SKILL_DIR/scripts`。
