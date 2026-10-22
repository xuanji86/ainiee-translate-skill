"""Per-book project state that every stage reads, kept next to cache.json:

  work/decisions.json   settled decisions — one place instead of rules scattered over
                        user_prompt / LESSONS / review prompts / config:
    {"settled":  [{"dst": "飞艇", "src": "airship", "note": "用户定"}…],
     "errata":   {"412": "Ensign 是笔误，统一作上尉"…},     # source typos: don't re-flag
     "tag_exceptions": {"77": "舰名出现两次，都斜体"…},           # <i>/<b> count may differ here
     "lint":     [{"name": "dragon_they", "re": "巨龙[^。]{0,8}他们", "msg": "巨龙用它/它们"}…]}
  work/provenance.jsonl one row per segment change written by `batch apply --source …`
                        (what changed, why, and the snippets a later pass must not bring back)

  state show <cache>                            summary
  state settle <cache> --dst 飞艇 [--src airship] [--note …]
  state errata <cache> IDX --note …
  state tag-exception <cache> IDX --reason …
  state lint-rule <cache> NAME --re REGEX --msg …
  state card <cache> [--range A-B]              compact rule card for an agent prompt
"""
import argparse
import difflib
import json
import os
import re
import time

_HAN = re.compile(r"[一-鿿]")
EMPTY = {"settled": [], "errata": {}, "tag_exceptions": {}, "lint": []}


def work_dir(cache_path: str) -> str:
    return os.path.dirname(os.path.abspath(cache_path))


def decisions_path(cache_path: str) -> str:
    return os.path.join(work_dir(cache_path), "decisions.json")


def provenance_path(cache_path: str) -> str:
    return os.path.join(work_dir(cache_path), "provenance.jsonl")


def load(cache_path: str | None) -> dict:
    d = {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in EMPTY.items()}
    if cache_path and os.path.exists(decisions_path(cache_path)):
        with open(decisions_path(cache_path), encoding="utf-8") as f:
            d.update(json.load(f))
    return d


def save(cache_path: str, d: dict) -> None:
    p = decisions_path(cache_path)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def tag_exceptions(d: dict) -> set[int]:
    return {int(k) for k in (d.get("tag_exceptions") or {})}


def settled_dst(d: dict) -> list[str]:
    return [s["dst"] for s in d.get("settled", []) if (s.get("dst") or "").strip()]


def lint_rules(d: dict) -> list[tuple[str, re.Pattern, str]]:
    return [(r["name"], re.compile(r["re"]), r.get("msg", "")) for r in d.get("lint", [])]


# ---------------------------------------------------------- provenance ----
def removed_snippets(old: str, new: str, min_han: int = 2, ctx: int = 2) -> list[str]:
    """What a fix took out: each dropped chunk of `old` (>= min_han Han chars) with `ctx` chars of
    its surroundings, so "不计一切" -> "不计前嫌" records "不计一切", not just "一切"."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out = []
    for op, a1, a2, _, _ in sm.get_opcodes():
        if op in ("replace", "delete") and len(_HAN.findall(old[a1:a2])) >= min_han:
            out.append(old[max(0, a1 - ctx):a2 + ctx].strip())
    return out


def record(cache_path: str, rows: list[dict]) -> None:
    """rows: {text_index, source, reason?, before, after}. Appends with `removed` snippets."""
    if not rows:
        return
    with open(provenance_path(cache_path), "a", encoding="utf-8") as f:
        for r in rows:
            r = dict(r)
            r.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
            r["removed"] = removed_snippets(r.get("before") or "", r.get("after") or "")
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def history(cache_path: str | None) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    p = provenance_path(cache_path) if cache_path else ""
    if p and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out.setdefault(int(r["text_index"]), []).append(r)
    return out


def protected_removals(cache_path: str | None, protect=("dual", "codex", "user", "editor")) -> dict[int, set[str]]:
    """Snippets that a meaning fix removed, per segment: a later pass must not reintroduce them."""
    out: dict[int, set[str]] = {}
    for idx, rows in history(cache_path).items():
        for r in rows:
            if str(r.get("source", "")).split(":")[0] in protect:
                out.setdefault(idx, set()).update(s for s in r.get("removed", []) if len(_HAN.findall(s)) >= 2)
    return out


# ---------------------------------------------------------------- card ----
def card(cache_path: str, lo: int | None = None, hi: int | None = None) -> str:
    """Compact rule card for an agent prompt (settled renderings, errata and fixes in range)."""
    d = load(cache_path)
    inr = (lambda i: True) if lo is None else (lambda i: lo <= i <= hi)
    L = []
    if d["settled"]:
        L.append("## 已定口径（不要改，也不要报）")
        L += [f"- {s.get('src') + ' → ' if s.get('src') else ''}{s['dst']}" + (f"（{s['note']}）" if s.get("note") else "")
              for s in d["settled"]]
    err = {int(k): v for k, v in d["errata"].items() if inr(int(k))}
    if err:
        L.append("## 原文笔误（已按本意处理，不要再报）")
        L += [f"- {k}: {v}" for k, v in sorted(err.items())]
    tex = {int(k): v for k, v in d["tag_exceptions"].items() if inr(int(k))}
    if tex:
        L.append("## 标记数量例外（不是错误）")
        L += [f"- {k}: {v}" for k, v in sorted(tex.items())]
    fixed = {i: rs for i, rs in history(cache_path).items() if inr(i)}
    prot = [(i, r) for i, rs in sorted(fixed.items()) for r in rs
            if str(r.get("source", "")).split(":")[0] in ("dual", "codex", "user", "editor") and r.get("reason")]
    if prot:
        L.append("## 已修过的语义问题（不要改回去）")
        L += [f"- {i}: {r['reason']}" for i, r in prot]
    return "\n".join(L) + ("\n" if L else "")


# ----------------------------------------------------------------- CLI ----
def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-book decisions / errata / tag exceptions / provenance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").add_argument("cache")
    s = sub.add_parser("settle"); s.add_argument("cache"); s.add_argument("--dst", required=True)
    s.add_argument("--src"); s.add_argument("--note")
    e = sub.add_parser("errata"); e.add_argument("cache"); e.add_argument("index", type=int)
    e.add_argument("--note", required=True)
    t = sub.add_parser("tag-exception"); t.add_argument("cache"); t.add_argument("index", type=int)
    t.add_argument("--reason", required=True)
    lr = sub.add_parser("lint-rule"); lr.add_argument("cache"); lr.add_argument("name")
    lr.add_argument("--re", required=True); lr.add_argument("--msg", default="")
    c = sub.add_parser("card"); c.add_argument("cache"); c.add_argument("--range", metavar="A-B")
    a = ap.parse_args(argv)
    d = load(a.cache)
    if a.cmd == "show":
        print(f"settled {len(d['settled'])}, errata {len(d['errata'])}, tag_exceptions {len(d['tag_exceptions'])}, "
              f"lint {len(d['lint'])}, provenance segments {len(history(a.cache))}")
        return 0
    if a.cmd == "card":
        lo = hi = None
        if a.range:
            lo, hi = (int(x) for x in a.range.split("-", 1))
        print(card(a.cache, lo, hi), end="")
        return 0
    if a.cmd == "settle":
        d["settled"] = [x for x in d["settled"] if x.get("dst") != a.dst]
        d["settled"].append({k: v for k, v in (("dst", a.dst), ("src", a.src), ("note", a.note)) if v})
    elif a.cmd == "errata":
        d["errata"][str(a.index)] = a.note
    elif a.cmd == "tag-exception":
        d["tag_exceptions"][str(a.index)] = a.reason
    elif a.cmd == "lint-rule":
        re.compile(a.re)
        d["lint"] = [x for x in d["lint"] if x["name"] != a.name] + [{"name": a.name, "re": a.re, "msg": a.msg}]
    save(a.cache, d)
    print(f"saved -> {decisions_path(a.cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
