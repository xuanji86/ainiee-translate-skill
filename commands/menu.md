---
description: 显示 ainiee-translate 的命令菜单（翻译/模块/提示词/润色等）
disable-model-invocation: true
---
# ainiee-translate 命令菜单

**翻译流程**
- `/ainiee-translate:translate <输入文件> [模块名]` —— 端到端翻译（解析→词汇表→翻译→导出→校验）
- `/ainiee-translate:import-project [list | <缓存|项目ID> <项目目录>]` —— 导入已有项目/AiNiee 缓存继续翻译/润色/导出
- `/ainiee-translate:glossary [--config PATH] [--analysis PATH]` —— 构建并锁定词汇表
- `/ainiee-translate:polish [批大小]` —— 对已译文本跑润色 pass
- `/ainiee-translate:export <输入文件>` —— 导出成品
- `/ainiee-translate:verify` —— 校验残留规则违规
- `/ainiee-translate:status` —— 查看进度（已绑模块 / 计数 / 续跑点）

**模块（不同任务的设置包）**
- `/ainiee-translate:import-profile <profile.json> <模块名>` —— 导入 AiNiee profile 为模块
- `/ainiee-translate:module list|show|create|load …` —— 管理模块
- `/ainiee-translate:switch-prompt [模块名]` —— 切换当前项目使用的模块
- `/ainiee-translate:show-prompt [模块名]` —— 查看模块的提示词与词汇表

**提示词**
- `/ainiee-translate:gen-prompt translate|polish [模块名]` —— 让 agent 帮你起草翻译/润色提示词

> 多数命令需要先设好环境变量 `AINIEE_REPO`（本地 AiNiee 仓库）、`AINIEE_PY`（AiNiee venv 的 python）。详见技能 SKILL.md「前置依赖与安装」。
