"""从 extra.original_html 重建 epub 项目的 source_text。

用于 v1.4.1 及更早版本解析出来的 cache.json：那时 EpubReader 用
soup.get_text(strip=True) 抽文本，会（a）丢掉行内斜体/粗体，(b) 把片段间的
空格挤掉，产生 "herblade" 这类粘连词。新版解析已修复；本命令让**存量项目**
不必重译即可补回标记与空格。

只改 source_text，不动译文与状态。带 extra.epub_tokens（⟦n⟧ 占位符）的段是新版解析的，跳过。已译段的 source_text 变化不影响其
translated_text —— 但补回的标记不会自动出现在旧译文里，需要用
`--list-marked` 找出这些段落重译（或润色时一并处理）。
"""
import argparse
import json
import re

from ainiee_translate import cache_io, helpers
from ainiee_translate._vendor.ModuleFolders.Domain.FileReader.EpubReader import (
    extract_text_with_marks,
)

MARK_RE = re.compile(r"</?[ib]>")


def _plan(proj):
    """返回 ([(item, 旧 source_text, 新 source_text)], 跳过数)。只含需要改写的项；
    带 extra.epub_tokens 的段是新版解析的（源文里有 ⟦n⟧ 占位符），重抽会抹掉占位符，一律跳过。"""
    out, skipped = [], 0
    for it in cache_io.iter_items(proj):
        extra = it.extra or {}
        html = extra.get("original_html")
        if not html:
            continue
        if extra.get("epub_tokens"):
            skipped += 1
            continue
        new = extract_text_with_marks(html)
        if new and new != it.source_text:
            out.append((it, it.source_text, new))
    return out, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rebuild epub source_text from original_html")
    ap.add_argument("cache", help="项目的 work/cache.json")
    ap.add_argument("--apply", action="store_true", help="写入（默认只预览）")
    ap.add_argument("--list-marked", action="store_true",
                    help="列出源文有行内标记、但译文标记对不上的段（译文需重做）；"
                         "--apply 前后均可用")
    ap.add_argument("--limit", type=int, default=10, help="预览条数")
    a = ap.parse_args(argv)

    proj = cache_io.load_cache(a.cache)
    plan, skipped = _plan(proj)
    marked = [(i, o, n) for i, o, n in plan if MARK_RE.search(n)]
    glued = [(i, o, n) for i, o, n in plan if MARK_RE.sub("", n).replace(" ", "") == o.replace(" ", "")
             and MARK_RE.sub("", n) != o]

    if a.list_marked:
        # 独立于「是否待改写」判断：源文带标记、但译文里标记数量对不上的段。
        # 这样 --apply 之前之后都能用（apply 后 plan 为空，但陈旧译文仍在）。
        stale = []
        for it in cache_io.iter_items(proj):
            trans = (it.translated_text or "").strip()
            if not trans:
                continue
            for mark in ("i", "b"):
                if it.source_text.count(f"<{mark}>") != trans.count(f"<{mark}>"):
                    stale.append({
                        "text_index": it.text_index,
                        "source_text": it.source_text,
                        "translated_text": it.translated_text,
                        "translation_status": int(it.translation_status),
                    })
                    break
        print(json.dumps(stale, ensure_ascii=False, indent=1))
        return 0

    print(f"需改写 {len(plan)} 段：补回行内标记 {len(marked)} 段，补回空格 {len(glued)} 段")
    if skipped:
        print(f"跳过 {skipped} 段：带链接/锚点占位符（新版解析，无需修复）")
    for i, o, n in plan[:a.limit]:
        print(f"\n[{i.text_index}]\n  旧: {o[:160]}\n  新: {n[:160]}")

    if a.apply:
        with cache_io.locked(a.cache):
            proj = cache_io.load_cache(a.cache)          # 锁内重读，别盖掉预览之后别人写进来的译文
            plan, _ = _plan(proj)
            if plan:
                bak = helpers.backup_file(a.cache)
                for it, _, new in plan:
                    it.source_text = new
                cache_io.save_cache(proj, a.cache)
        print(f"\n已写入 {a.cache}（{len(plan)} 段，备份 {bak}）" if plan else "\n无需写入")
    else:
        print("\n（预览模式，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
