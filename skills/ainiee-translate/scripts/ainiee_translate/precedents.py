"""Precedent sheet for a partially translated book (the cheap BOOK_BIBLE).

For every proper noun that occurs in the pending groups' source, report how the
already-translated segments rendered it: glossary entry if any, else whether it
was kept verbatim / always translated / inconsistent, plus the most frequent
CJK word following it (rank, title, 先生…). Parallel agents read this instead of
re-deriving the book's conventions from scratch — and instead of each deciding
differently.

    precedents cache.json --for work/par/grp_*_src.json --locked work/glossary.locked.json --out work/BOOK_BIBLE.md
"""
import argparse
import collections
import json
import re

from .helpers import normalize_apostrophes as N, latin_boundary_search as LB, has_cjk
from .scan import _proper_noun_vocab, _STOP

_WORD = re.compile(r"[A-Z][A-Za-z'’\-]{2,}")
_AFTER_STOP = {"说", "的", "和", "与", "在", "道", "了", "是"}


def _glossary_index(locked):
    gl = {}
    for c in (locked or {}).get("characters", []):
        for n in [c.get("canonical"), c.get("render")] + list(c.get("aliases") or []):
            if n:
                gl[N(n).lower()] = ("角色", c.get("render") or c.get("canonical"), c.get("note", ""))
    for t in (locked or {}).get("terms", []):
        if t.get("src"):
            dst = f"{t['src']}（保留原文）" if t.get("keep_source") else t.get("dst", "")
            gl[N(t["src"]).lower()] = ("术语", dst, t.get("note", ""))
    return gl


def build(items, pending_texts, locked=None, title="BOOK_BIBLE") -> str:
    done = [it for it in items if it.get("translation_status") in (1, 2) and (it.get("translated_text") or "").strip()]
    vocab = _proper_noun_vocab(items)
    gl = _glossary_index(locked)
    cjk_target = any(has_cjk(it["translated_text"]) for it in done[:200])
    names = collections.Counter()
    for text in pending_texts:
        for m in _WORD.finditer(N(text)):
            w = m.group()[:-2] if m.group().endswith("'s") else m.group()
            if w in vocab and w.lower() not in _STOP and not w.isupper():
                names[w] += 1
    rows = []
    for w, c in names.most_common():
        glo = gl.get(w.lower())
        seen = kept = 0
        after = collections.Counter()
        for it in done:
            if not LB(w, it["source_text"]):
                continue
            seen += 1
            t = it["translated_text"]
            if LB(w, t):
                kept += 1
                if cjk_target:
                    for m in re.finditer(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z]) ?([一-鿿]{{1,3}})", N(t)):
                        after[m.group(1)] += 1
        if glo:
            prec = f"词汇表{glo[0]}：**{glo[1]}**" + (f"（{glo[2]}）" if glo[2] else "")
        elif seen == 0:
            prec = "**新名**：已译部分未出现 → 保留原文 + 记 newterms"
        elif kept == seen:
            prec = f"已译 {seen} 处全部保留原文"
        elif kept == 0:
            prec = f"已译 {seen} 处**全部译成目标语言**（表外！去 ctx/前文找同一译法）"
        else:
            prec = f"已译 {seen} 处，保留原文 {kept} 处（不一致，以词汇表/ctx 为准）"
        top = ", ".join(f"{k}×{v}" for k, v in after.most_common(3) if v >= 2 and k not in _AFTER_STOP)
        rows.append(f"| {w} ({c}) | {prec} | {top} |")
    lines = [f"# {title}（机械抽取自已译 {len(done)} 段的先例）", "",
             "已译部分经用户确认。**每个专名的既有处理方式就是标准**；后接头衔/称谓沿用最高频那种；"
             "表外且已译成目标语言的，去 ctx/前文找同一译法。", "",
             "## 待译段里出现的专名", "", "| 专名（待译段出现次数） | 既有先例 | 高频后接 |", "|---|---|---|", *rows]
    if cjk_target:
        rank = collections.Counter()
        for it in done:
            for m in re.finditer(r"[A-Z][A-Za-z'’]+ (上校|中校|少校|上尉|中尉|少尉|上将|中将|少将|准将|舰长|指挥官|医生|大使|议长|将军|监政官|摄政王|教授|先生|女士|小姐)", N(it["translated_text"])):
                rank[m.group(0)] += 1
        lines += ["", "## 姓名 + 衔级/称谓 既有写法（频次 ≥3，直接照抄）", "",
                  ", ".join(f"{k}×{v}" for k, v in rank.most_common() if v >= 3) or "（无）"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    from . import cache_io
    ap = argparse.ArgumentParser(description="Precedent sheet (BOOK_BIBLE) from the already-translated part of the book")
    ap.add_argument("cache")
    ap.add_argument("--for", dest="sources", nargs="+", required=True, metavar="SRC_JSON",
                    help="grp_N_src.json files whose proper nouns to look up")
    ap.add_argument("--locked", help="locked glossary (adds the table's own answer per name)")
    ap.add_argument("--out", help="write markdown here (default stdout)")
    ap.add_argument("--title", default="BOOK_BIBLE")
    a = ap.parse_args(argv)
    proj = cache_io.load_cache(a.cache)
    items = [{"source_text": it.source_text, "translated_text": it.translated_text,
              "translation_status": it.translation_status} for it in cache_io.iter_items(proj)]
    texts = []
    for p in a.sources:
        with open(p, encoding="utf-8") as f:
            texts.extend(r.get("source_text", "") for r in json.load(f))
    locked = None
    if a.locked:
        with open(a.locked, encoding="utf-8") as f:
            locked = json.load(f)
    md = build(items, texts, locked, a.title)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"precedents -> {a.out} ({md.count(chr(10))} lines)")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
