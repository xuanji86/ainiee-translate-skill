"""从 extra.original_html 重建 epub 项目的 source_text。

用于 v1.4.1 及更早版本解析出来的 cache.json：那时 EpubReader 用
soup.get_text(strip=True) 抽文本，会（a）丢掉行内斜体/粗体，(b) 把片段间的
空格挤掉，产生 "herblade" 这类粘连词。新版解析已修复；本命令让**存量项目**
不必重译即可补回标记与空格。

只改 source_text，不动译文与状态。已译段的 source_text 变化不影响其
translated_text —— 但补回的标记不会自动出现在旧译文里，需要用
`--list-marked` 找出这些段落重译（或润色时一并处理）。
"""
import argparse
import json
import re
import shutil
from datetime import datetime

from ainiee_translate import cache_io
from ainiee_translate._vendor.ModuleFolders.Domain.FileReader.EpubReader import (
    extract_text_with_marks,
)

MARK_RE = re.compile(r"</?[ib]>")


def _plan(proj):
    """返回 [(item, 旧 source_text, 新 source_text)]，只含需要改写的项。"""
    out = []
    for it in cache_io.iter_items(proj):
        html = (it.extra or {}).get("original_html")
        if not html:
            continue
        new = extract_text_with_marks(html)
        if new and new != it.source_text:
            out.append((it, it.source_text, new))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rebuild epub source_text from original_html")
    ap.add_argument("cache", help="项目的 work/cache.json")
    ap.add_argument("--apply", action="store_true", help="写入（默认只预览）")
    ap.add_argument("--list-marked", action="store_true",
                    help="只列出补回标记、且已有译文的段（这些段的译文需重做）")
    ap.add_argument("--limit", type=int, default=10, help="预览条数")
    a = ap.parse_args(argv)

    proj = cache_io.load_cache(a.cache)
    plan = _plan(proj)
    marked = [(i, o, n) for i, o, n in plan if MARK_RE.search(n)]
    glued = [(i, o, n) for i, o, n in plan if MARK_RE.sub("", n).replace(" ", "") == o.replace(" ", "")
             and MARK_RE.sub("", n) != o]

    if a.list_marked:
        stale = [
            {"text_index": it.text_index, "source_text": new,
             "translated_text": it.translated_text}
            for it, _old, new in marked
            if (it.translated_text or "").strip()
        ]
        print(json.dumps(stale, ensure_ascii=False, indent=1))
        return 0

    print(f"需改写 {len(plan)} 段：补回行内标记 {len(marked)} 段，补回空格 {len(glued)} 段")
    for i, o, n in plan[:a.limit]:
        print(f"\n[{i.text_index}]\n  旧: {o[:160]}\n  新: {n[:160]}")

    if a.apply:
        bak = f"{a.cache}.bak.{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(a.cache, bak)
        for it, _, new in plan:
            it.source_text = new
        cache_io.save_cache(proj, a.cache)
        print(f"\n已写入 {a.cache}（备份 {bak}）")
    else:
        print("\n（预览模式，加 --apply 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
