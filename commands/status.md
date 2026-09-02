---
description: 查看当前项目状态（已绑模块 / 未译·已译计数 / 续跑点）
allowed-tools: Bash, Read
---
报告当前项目（`./work/`）状态。

```bash
echo "=== 已绑模块 ==="; cat work/active_module.json 2>/dev/null || echo "(未绑定模块)"
PFX="PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/ainiee-translate/scripts ${AINIEE_PY:-python3}"
echo "=== 下一批未译（空=翻译完成）==="; eval $PFX -m ainiee_translate.batch read work/cache.json --size 1 2>/dev/null || echo "(无 cache.json 或环境未就绪)"
echo "=== 下一批待润色 ==="; eval $PFX -m ainiee_translate.batch read-translated work/cache.json --size 1 2>/dev/null
```

据此判断下一步：还有未译→`/ainiee-translate:translate`；全部已译且有润色提示词→`/ainiee-translate:polish`；都完成→`/ainiee-translate:export`。
