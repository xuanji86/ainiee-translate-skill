# 外部审校交接（Codex / 人工 / 另一个模型）

外部审校与本技能走**同一条管线**：对方只读快照、只交 findings；写回一律由主控经闸门完成。

## 交给对方

1. 快照：`cache dump work/cache.json --range A-B --out snapshot.json`（`[{i, en, zh}]`）+ `shasum -a 256 work/cache.json`。
   复审只给改过的段：加 `--changed-since work/cache.json.pre_xxx`。
2. 规则：`state card work/cache.json --range A-B`（已定口径、原文笔误、标记例外、已修语义——这些不要报）+ `work/user_prompt.md`。
3. 产出格式（JSONL，每个问题一行）：
   ```json
   {"text_index": 1610, "offending": "她不恨 Marlow 做的事。", "proposed": "她并不因 Marlow 的所作所为而恨他。",
    "severity": 2, "category": "A", "reason": "恨的对象是人，不是那件事"}
   ```
   `offending` 必须是当前译文里**原样、恰好出现一次**的片段；`category` A 误译 / B 硬伤 / C 翻译腔 / D 不一致（缺省按 severity：≥2 记 A，否则 C）。
   也接受 `{i, current, fix, sev, issue}` 这种写法。

## 收回来

```bash
<PFX> -m ainiee_translate.review import work/cache.json their_findings.jsonl --group x --source codex --run codex-1
<PFX> -m ainiee_translate.review pre    work/cache.json --run codex-1 work/review/codex-1/findings_x.jsonl
<PFX> -m ainiee_translate.review merge  work/cache.json --run codex-1 x          # → review_ALL.md 给用户勾
<PFX> -m ainiee_translate.review pick   work/cache.json --run codex-1 x --ids x-001 x-004 …   # 或 --min-sev 2 --exclude …
<PFX> -m ainiee_translate.batch apply   work/cache.json work/review/codex-1/apply_pick.json --source codex --reason "Codex 复核"
```

- 对方读的是旧快照也没关系：`pre` 只认在**当前**译文里恰好出现一次的 `offending`，已被别的修改覆盖的条目会被拒（`ambiguous(0)`），不会误写。
- `--source codex` 记进 `provenance.jsonl`：之后的对抗审若想把这次修掉的说法改回去，闸门拒收（`E_reverts_fix`）。
- 对方若交的是整段改写，转成 `{text_index, patches: [[旧, 新]]}` 后直接 `batch apply`。
