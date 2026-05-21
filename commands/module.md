---
description: 管理翻译模块（list / show / create / load）
argument-hint: <list|show|create|load> [名字] [--work 项目目录]
allowed-tools: Bash
---
管理模块（存放于 `~/.ainiee-translate/modules/`）。把用户给的参数透传给 module CLI：

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts" \
"${AINIEE_PY:-python3}" -m ainiee_translate.module $ARGUMENTS
```

- `list` —— 列出所有模块（标记当前激活）
- `show <名字>` —— 看某模块的元数据 + 术语/角色/禁翻计数
- `create <名字> [--source-language X --target-language Y --title T]` —— 新建空模块
- `load <名字> [--work 项目目录]` —— 设为激活；给 `--work` 时把提示词+词汇表拷进该项目 `work/`

注：`module` 子命令为纯文件操作，不需要 `AINIEE_REPO`。
