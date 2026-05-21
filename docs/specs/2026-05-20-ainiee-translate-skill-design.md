# ainiee-translate —— 独立 Agent 版 AiNiee 翻译系统（设计 / spec）

- 日期：2026-05-20
- 状态：设计已与用户确认，待写实现计划
- 相关：与现有 `ainiee-cache-fix` 技能互补（后者事后修缓存，本技能负责前向翻译）

---

## 1. 目标与动机

把 AiNiee 的「翻译」流程做成一个**完全独立、Agent 原生**的系统：不依赖 AiNiee 应用（无 GUI / HTTP / MCP）在运行，由 **Claude Code（agent）本身**充当翻译引擎，跑在用户的 Claude Code 订阅上。

**动机（已用实测验证）：**
- **成本**：整本约 **~302K token**（输入 ~145K + 输出 ~117K + 术语常驻摊销 ~40K），对比用户此前经 API 跑同一本书的 **1–2M token**，约 **5×（区间 3–7×）更省**。省的全在输入侧——不再像 AiNiee 那样把长提示词 + 术语表在几百个分块里反复重发。用户持有最高档 Max 订阅，单本舒适。
- **质量**：散文质量与 AiNiee 相当；agent 的真正增量在**全局一致性**——去重、术语/人名一致、规则遵守、抓漏译。实测在 某书开场章发现 AiNiee 译文有漏译（"central eyhon" 整段丢失），以及提取表有去重缺陷（Marlow×3、Da'ren 因撇号×2 等）。

## 2. 范围

**v1 = 翻译核心。**
- 输入：epub（复用 AiNiee 解析模块，自带其余格式支持）。
- 流程：解析 → 建并锁定工作术语表 → 逐章翻译（agent，按规则）→ 写回缓存 → 导出成品。
- 术语 seed：AiNiee **公共术语表**（`prompt_dictionary_data`，全局共享）为主；项目有 `analysis_v1`（提取的角色/术语）时叠加。
- 介入模式：A 抽样自动（默认）/ B 每章过目 / C 全自动，用户每次运行时选。

**明确不在 v1（后续阶段）：**
- 提取阶段（对全新、无任何术语 seed 的书做 agent 提取）——v1 靠公共表起步，提取后续再做。
- 校对/润色阶段（独立的规则化一致性 pass）。
- epub 以外格式的专门打磨（解析库本身支持，但 v1 只验证 epub 闭环）。

## 3. 架构与组件

**独立 Python 脚本 + 技能说明，不跑 AiNiee 应用。**

```
~/.claude/skills/ainiee-translate/
  SKILL.md                         # 指挥 Claude Code 跑完整流程（任意源/目标语言）
  references/
    translation_rules.md           # 通用规则（AiNiee 原生提示词）
    <project>.glossary.locked.json # 锁定的工作权威表（每项目一份）
  scripts/                         # 确定性"管道"，全部可单测
    locate_cache.py                # 复用 cache-fix 同名 helper
    parse.py                       # import FileReader → 解析 epub → cache.json
    glossary.py                    # 取 seed → 清洗去重 → 工作权威表
    batch.py                       # 读未译段 / 写回译文（按章节标记分批，无标记则定长 N 段）
    export.py                      # import FileOutputer → cache.json → 成品 epub
    verify.py                      # 复用 cache-fix 检测残留
    _helpers.py                    # 撇号归一 / 拉丁边界 / OCR 粘连（复用 cache-fix）
```

**核心分工（也是可测性的根据）：**
- **脚本 = 确定性管道**（解析 / 缓存读写 / 清洗 / 批次 / 导出 / 校验）→ 可 TDD 单测。
- **Claude Code（agent）= 翻译引擎**：读段、按规则译、写回。不调任何外部 API。

**唯一耦合点：** 脚本通过环境变量 `AINIEE_REPO` 把 AiNiee 仓库加入 `sys.path`，import 它的 `ModuleFolders.Domain.FileReader.FileReader` / `ModuleFolders.Domain.FileOutputer.FileOutputer`（与 MCP server 解析仓库路径同套做法）。已确认这两个 Domain 目录（28 + 27 个 .py）**0 引用 Qt**，可 headless import。`cache.json` 直接复用 AiNiee 的 `CacheProject` 结构（顺带可用 AiNiee GUI 打开检查）。

## 4. 工作流与数据流

```
1. parse.py  --input book.epub --type AutoType → cache.json（CacheProject 结构）
2. glossary.py: seed=公共表(+analysis_v1) → 清洗去重归一 → 你 review 锁定
3. 选介入模式（A / B / C）
4. 翻译循环：batch.py 吐 status=未译 段 → agent 按 锁定表+规则 译 → batch.py 写回
5. 恢复：重跑从首个未译段继续（状态驱动，跨时间窗天然安全）
6. export.py → 成品 epub（FileOutputer 保结构/标签）
7. verify.py 扫残留规则违规
```

- **源永远从 `cache.json` 读**（只读、稳）。
- **译文写回 `cache.json`**（状态→TRANSLATED），导出据此产出。
- **进度靠 `translation_status` 驱动**（译过的跳过 → 可恢复、可跨窗口）。

**v1 验证（已译的 2 本）**：`parse.py` 从 epub **重新解析**出一份干净的（未译）`cache.json`；术语 seed 里的 `analysis_v1` 则从 AiNiee 现有 `ProjectCache/<id>/AinieeCacheData.json` 读取叠加。即「源走新解析、术语借旧分析」，互不混淆。

## 5. 工作权威表清洗（build & lock）

**seed**：AiNiee 公共术语表 `prompt_dictionary_data`（全局共享）；项目有 `analysis_v1` 时叠加角色/术语/禁翻。

`glossary.py` + agent：
1. **去重归一**：撇号归一（`' ' ʼ → '`，合并 Da'ren 双胞胎）；剥离头衔取**裸名做 canonical**，变体挂 `aliases`（Captain Marlow / James Marlow / James Marlow → 一条）。
2. **分类**：人名→保留原文（render）；地名/组织/术语→译名（取 dst）。
3. **音译归一**：一名多译 → 用户定一个 canonical。

（头衔摆放、对话风格等**领域规则不写入锁定表**，改由用户自定义提示词提供——见 §6。）

产出 `references/<project>.glossary.locked.json`：
```json
{ "characters":[{"canonical":"James Marlow","render":"James Marlow",
                 "aliases":["Marlow","Jim Marlow"],"gender":"M","note":"船长"}],
  "terms":[{"src":"Korin","dst":"科林","category":"race"},
           {"src":"Highmark","dst":"Highmark","keep_source":true}],
  "non_translate":[{"marker":"<i>","why":"tag"}] }
```
**用户 review 锁定一次**（重点核：人名/地名分类 + 音译 canonical——用户的领域知识）。锁定表 = 翻译全程的常驻权威。

## 6. 规则编码（两层）

**通用层**（`references/translation_rules.md`，项目无关）= **AiNiee 原生标准提示词** + 管线适配：
- 逐行对应（不并不拆）、保留标签/占位/转义/序号（`<i>`、`\n`、代码）、忠实准确不删减。
- 术语/人名以**锁定表**（术语表/角色表）为唯一真相源；表外专名默认保留原文。
- OCR 粘连还原、撇号归一、反漏译等实务兜底。
- **本技能不预设任何特定题材的规则**（如「人名怎么处理」「军衔怎么摆」「对话风格」）。

**项目层**（用户自己写，像 AiNiee 一样）：人名/头衔/风格/世界观/示例等领域规则由**用户自定义提示词**提供，两种来源——
- 复用 AiNiee 配置：`translation_user_prompt_data` / `characterization_data` / `writing_style_content` / `world_building_content` / `translation_example_data`（各带开关），由 `prompt.py` 按开关汇总成 `user_prompt.md`；
- 或手写 `user_prompt.md`。

**原则**：通用提示词 + 用户提示词 + 锁定表三者在翻译当下应用；技能保持题材中立，领域规则归用户。

## 7. 写回、恢复、三模式、错误处理

- **写回**：`batch.py` 按 `text_index` 把译文写进 `cache.json`（状态→TRANSLATED）。独立版只有一个我们自己拥有的缓存文件，无在线/离线之分；每批写前备份（时间戳）。
- **恢复**：状态驱动——只译 `未翻译` 段、跳过已译。半途中断可续，跨时间窗安全。
- **三模式**（开跑时用户选）：
  - **A 抽样自动（默认）**：先译 ~1 章 → 给用户核对对齐（风格/术语/规则）→ 之后自动逐章；**只在歧义**（锁定表外新实体 / 分类不清）时停下问。
  - **B 每章过目**：每章译完 → 用户点头 → 写回 → 下一章。
  - **C 全自动**：整本译完写回 → `verify.py` 扫残留 → 报告。
- **错误/边界**：行数不符（破坏逐行）→ 重做该批；某段无产出 → 反漏译触发重试；锁定表外实体 → 问（A/B）或记入待审单（C）；源含 OCR 粘连 → 尽力译 + 标记；解析/导出失败 → 抛 AiNiee reader/writer 的错误。

## 8. 测试（TDD）

- **脚本确定性 → 先写失败测试**：
  - `glossary.py`：去重/归一/分类（Marlow×3→1、撇号合并、人/地分类）。
  - `prompt.py`：按开关汇总用户自定义提示词。
  - `batch.py`：读未译 / 写回 / 状态流转 / 恢复。
  - `_helpers.py`：撇号归一、拉丁边界 `(?<![A-Za-z])`、OCR 粘连（复用 cache-fix 的测试用例）。
  - `parse.py` / `export.py`：小 fixture epub 往返、结构保真（集成测试，需 `AINIEE_REPO`）。
  - `verify.py`：残留检测。
- **不可单测**：agent 的译文（模型输出）。其周边脚手架全可测；译文**质量**靠模式 A 抽样把关 + `verify.py` 残留扫描保证。

## 9. 依赖与假设

- `AINIEE_REPO` 指向本地 AiNiee 仓库；其 `ModuleFolders.Domain.{FileReader,FileOutputer}` + `Service.Cache` 可 headless import（已确认 0 Qt 引用）。
- Python 解析依赖（epub 等）取自 AiNiee 仓库的环境/依赖。
- v1 默认面向 macOS 路径（公共表/项目缓存位置同 `ainiee-cache-fix` 所述），路径覆盖沿用 `FilePathConfig` 的环境变量。
- 复用 `ainiee-cache-fix` 的 helper（撇号/边界/OCR、locate_cache、verify 思路）——技能自包含，少量代码复制一份，不做跨技能依赖。

## 10. 后续阶段（非 v1）

1. **提取阶段**：对无 seed 的全新书做 agent 提取，产出/补充术语表。
2. **校对/润色阶段**：独立的规则化一致性 pass（可作用于本技能或 AiNiee 已有译文）。
3. **多格式打磨**：验证 epub 之外格式的闭环。
