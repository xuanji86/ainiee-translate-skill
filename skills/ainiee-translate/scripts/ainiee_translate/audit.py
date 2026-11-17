"""Mechanical lint for translated segments — no model, no glossary.

Two tiers, shared by `batch write` (gate), `batch validate` (pre-write) and the
`audit` CLI (whole cache):

- hard  → the segment must not be written: `empty` (source has text, target
  none), `token_mismatch` (epub link/anchor placeholders ⟦n⟧ / ⟦n⟧…⟦/n⟧ not
  each kept exactly once, or a pair closed before it opens — never waivable),
  `tag_mismatch` (<i>/<b> open/close counts differ from the source;
  pass allow_tag_mismatch for projects whose rules permit an exception, e.g.
  translated book titles switching from <i> to 《》 — or the marks are closed
  out of order / cross each other or a ⟦n⟧…⟦/n⟧ pair, which would export as
  broken XHTML and is never waivable).
- soft  → style slips worth a look, tallied not blocking: identical_untranslated,
  markup_leak, and — only when the target contains CJK — halfwidth_punct,
  halfwidth_period, cjk_corner_quote, ascii_ellipsis, single_dash, inner_space,
  odd_ascii_quotes, too_short / too_long (Han chars per source word).

Ported from the per-project `_audit.py` scripts that kept getting rewritten."""
import json
import re
import sys

from .helpers import has_cjk

_MARK = re.compile(r"</?[ib]>")
_LATIN_WORD = re.compile(r"[A-Za-z']+")
_HAN = re.compile(r"[一-鿿]")

_TOKEN = re.compile(r"⟦/?\d+⟧")

HARD_KINDS = ("empty", "token_mismatch", "tag_mismatch")


def token_mismatch(src: str, tgt: str) -> bool:
    """Every placeholder from the source exactly once in the target, nothing invented,
    and each ⟦n⟧…⟦/n⟧ pair still opens before it closes (order between tokens may change)."""
    s, t = _TOKEN.findall(src), _TOKEN.findall(tgt)
    if sorted(s) != sorted(t):
        return True
    pos = {tok: i for i, tok in enumerate(t)}
    return any(pos[f"⟦{tok[2:]}"] > pos[tok] for tok in t if tok.startswith("⟦/"))


_NEST = re.compile(r"<(/?)([ib])>|⟦(/?)(\d+)⟧")


def well_nested(text: str) -> bool:
    """<i>/<b> marks and ⟦n⟧…⟦/n⟧ pairs close in the reverse order they opened, so they turn into
    well-formed inline tags on export. A lone ⟦n⟧ (footnote number, image) is an atom, not a pair."""
    toks = [(m[1] or m[3], m[2] or "⟦" + m[4]) for m in _NEST.finditer(text)]
    paired = {name for close, name in toks if close and name[0] == "⟦"}
    stack = []
    for close, name in toks:
        if name[0] == "⟦" and name not in paired:
            continue
        if not close:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def mark_mismatch(src: str, tgt: str) -> list[str]:
    """Marks whose open/close counts differ from the source, plus "nesting" when the counts could
    pass but the target closes marks out of order or lets them cross each other / a ⟦n⟧ pair
    (`</i>翠鸟号<i>`, `⟦1⟧第<i>二⟦/1⟧</i>部`) while the source nests cleanly."""
    out = []
    for m in ("i", "b"):
        if (src.count(f"<{m}>") != tgt.count(f"<{m}>")
                or src.count(f"</{m}>") != tgt.count(f"</{m}>")):
            out.append(m)
    if well_nested(src) and not well_nested(tgt):
        out.append("nesting")
    return out


def hard_checks(src: str, tgt: str, allow_tag_mismatch: bool = False) -> list[str]:
    src, tgt = src or "", tgt or ""
    if src.strip() and not tgt.strip():
        return ["empty"]
    if token_mismatch(src, tgt):
        return ["token_mismatch"]
    bad = mark_mismatch(src, tgt)
    if bad and (not allow_tag_mismatch or "nesting" in bad):   # a count exception never excuses broken nesting
        return ["tag_mismatch"]
    return []


def soft_checks(src: str, tgt: str) -> list[str]:
    s, t = src or "", tgt or ""
    if not t.strip():
        return []
    w = []
    words = len(_LATIN_WORD.findall(s))
    if words >= 8 and t.strip() == s.strip():
        w.append("identical_untranslated")
    bare = _TOKEN.sub("", _MARK.sub("", t))
    if re.search(r"[<>]|&[a-z]+;", bare):
        w.append("markup_leak")
    if has_cjk(t):
        if re.search(r"[一-鿿][,;:!?]|[,;:!?][一-鿿]", t):
            w.append("halfwidth_punct")
        if re.search(r"[一-鿿]\.(?!\d)", t):
            w.append("halfwidth_period")
        if "「" in t or "」" in t:
            w.append("cjk_corner_quote")
        if "..." in t or ". . ." in t:
            w.append("ascii_ellipsis")
        if re.search(r"(?<!—)—(?!—)", t):
            w.append("single_dash")
        if re.search(r"[一-鿿] +[一-鿿]", t):
            w.append("inner_space")
        if t.count('"') % 2:
            w.append("odd_ascii_quotes")
        if words >= 25:
            ratio = len(_HAN.findall(t)) / words
            if ratio < 0.75:
                w.append("too_short")
            elif ratio > 2.6:
                w.append("too_long")
    return w


def rule_checks(tgt: str, rules=()) -> list[str]:
    """Book-specific lint rules from decisions.json: [(name, regex, msg)] that must not match the target."""
    return [f"rule:{name}" for name, rx, _ in rules if rx.search(tgt or "")]


def lint_pair(src: str, tgt: str, allow_tag_mismatch: bool = False, rules=()) -> tuple[list[str], list[str]]:
    hard = hard_checks(src, tgt, allow_tag_mismatch)
    return hard, ([] if hard == ["empty"] else soft_checks(src, tgt) + rule_checks(tgt, rules))


def audit_items(items: list[dict], allow_tag_mismatch: bool = False,
                statuses=(1, 2), sample: int = 5, tag_exceptions=(), rules=()) -> dict:
    """items: [{text_index, source_text, translated_text, translation_status}].
    `tag_exceptions`: text_indexes whose <i>/<b> counts may differ (decisions.json).
    Returns {category: {"count", "segments": [idx...], "samples": [{text_index, source, target}]}}."""
    out: dict[str, dict] = {}
    exc = set(tag_exceptions)
    for it in items:
        if it.get("translation_status") not in statuses:
            continue
        s, t = it.get("source_text") or "", it.get("translated_text") or ""
        hard, soft = lint_pair(s, t, allow_tag_mismatch or it["text_index"] in exc, rules)
        for c in hard + soft:
            row = out.setdefault(c, {"count": 0, "segments": [], "samples": []})
            row["count"] += 1
            row["segments"].append(it["text_index"])
            if len(row["samples"]) < sample:
                row["samples"].append({"text_index": it["text_index"], "source": s[:120], "target": t[:120]})
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))


def main(argv=None):
    import argparse
    from . import cache_io
    ap = argparse.ArgumentParser(description="Mechanical lint of translated/polished segments")
    ap.add_argument("cache")
    ap.add_argument("--out", help="also write the full report JSON here")
    ap.add_argument("--json", action="store_true", help="print the full report JSON (stdout = pure JSON)")
    ap.add_argument("--allow-tag-mismatch", action="store_true")
    ap.add_argument("--samples", type=int, default=5)
    a = ap.parse_args(argv)
    from . import state
    d = state.load(a.cache)
    proj = cache_io.load_cache(a.cache)
    items = [{"text_index": it.text_index, "source_text": it.source_text,
              "translated_text": it.translated_text, "translation_status": it.translation_status}
             for it in cache_io.iter_items(proj)]
    rep = audit_items(items, a.allow_tag_mismatch, sample=a.samples,
                      tag_exceptions=state.tag_exceptions(d), rules=state.lint_rules(d))
    hard = sum(v["count"] for k, v in rep.items() if k in HARD_KINDS)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for k, v in rep.items():
            segs = v["segments"]
            print(f"{k:24s} {v['count']:5d}  {segs[:12]}{' …' if len(segs) > 12 else ''}")
        if a.out:
            print(f"report -> {a.out}")
    sys.stderr.write(f"{hard} hard issue(s), {sum(v['count'] for v in rep.values()) - hard} warning(s)\n")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
