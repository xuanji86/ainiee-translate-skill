"""Adversarial review pass — the deterministic half. Model-side roles (Reviewer /
Challenger / Consistency auditor) are subagents; this module is everything the
main agent runs between them so that no finding reaches cache.json un-gated:

  benchmark  current cache vs an older snapshot -> which segments a human changed
             (recall denominator; term-only edits excluded via config)
  inventory  term inventory for the Consistency auditor (English term -> segments,
             co-occurrence hints, verbatim repeated source sentences)
  blind      target-language-only copy of each group for the Blind Reader -> groups/blind_X.json
  hints      validate the Blind Reader's flags_X.jsonl -> hints_X.json (flagged segments + source)
             for the Reviewer; bad quotes -> rejected_flags_X.jsonl
  pre        mechanical gate on Reviewer findings -> findings_X.pre.jsonl / rejected_X.jsonl
  segs       the segments a Challenger needs (only those with findings) -> segs_X.json
  final      merge Challenger verdicts -> apply_X.json (A/B, ready for `polish write`)
             + review_X.md (C/D and human-only A) + rejected_X.jsonl
  merge      every group's leftover C/D into one review_ALL.md sorted by severity
  score      recall / precision against benchmark.json (benchmark groups only)
  log        append a provenance row (stage, model, agent, file) to review_log.jsonl

Layout (default DIR = <cache dir>/review): groups/grp_X_src.json from
`batch split --stage review --prefix`, findings_X.jsonl from Reviewers,
verdicts_X.jsonl from Challengers, config.json with the project's rules:

  {"redline": [regex…],     # protected renderings: multiset in offending == proposed
                            # ("change forbidden, mention allowed")
   "settled": [regex…],     # settled renderings: may be added, never removed
   "glossary_settled": true,# also treat every glossary `dst` as settled (default)
   "forbid": "[「」\\"]",    # characters proposed text must never introduce
   "soft_block": [...],     # audit soft kinds that must not newly appear
   "term_only": [[a, b]…],  # benchmark: edits that are only these swaps don't count
   "norm": [[regex, repl]…],# benchmark: extra symmetric normalisation
   "leak_files": [md…]}     # score: files whose table cells are known "answers"

Gate rules (per finding, in order): required fields; category in A-D;
`offending` occurs exactly once in the reviewed text; redline/settled/forbid;
`<i>/<b>` parity via audit.lint_pair; no new soft_block issue; Latin-token
multiset unchanged unless `latin_change` on an A finding (-> human review);
a sentence-scale rewrite (offending >= REWRITE_MIN Han chars) must keep its Han
length within REWRITE_RATIO of the original, so a rewrite cannot silently drop
or pad content.
"""
import argparse
import collections
import datetime
import json
import os
import re

from . import audit, cache_io

LATIN = re.compile(r"[A-Za-z][A-Za-z’'\-]*")
HAN = re.compile(r"[一-鿿]")
NEVER = re.compile(r"(?!x)x")
DEFAULT_SOFT_BLOCK = ["cjk_corner_quote", "odd_ascii_quotes", "halfwidth_punct", "halfwidth_period", "ascii_ellipsis"]
DEFAULT_LEAK_FILES = ["DEFECT_TAXONOMY.md", "AI_FLAVOR_CHECKLIST.md", "EXAMPLES.md"]
CATEGORY_RE = re.compile(r"(?:降为|升为|改为|改|应为|应归|归为|归|reclassif\w* as|as)\s*([ABCD])(?![A-Za-z])")
SEVERITY_RE = re.compile(r"severity\D{0,8}([123])\D{0,6}(?:降为|改为|改|应为|->|→)\s*([123])")
REWRITE_MIN = 12              # Han chars in `offending` from which a finding counts as a sentence rewrite
REWRITE_RATIO = (0.5, 2.0)    # allowed Han(proposed)/Han(offending) for such rewrites


# ------------------------------------------------------------------ IO ----
def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(p, rows):
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def group_of(path: str) -> str:
    m = re.search(r"(?:findings|verdicts|flags)_([A-Za-z0-9]+)", os.path.basename(path))
    if not m:
        raise ValueError(f"cannot infer group id from {path!r} (expected findings_X / flags_X .jsonl)")
    return m.group(1)


class Paths:
    def __init__(self, cache: str, dir: str | None = None):
        self.cache = cache
        self.dir = dir or os.path.join(os.path.dirname(os.path.abspath(cache)), "review")
        self.groups = os.path.join(self.dir, "groups")

    def f(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def group_src(self, g: str) -> dict[int, dict]:
        """The text the reviewer actually saw (a benchmark group = old text); falls back to the cache."""
        p = os.path.join(self.groups, f"grp_{g}_src.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return {int(r["text_index"]): r for r in json.load(f)}
        proj = cache_io.load_cache(self.cache)
        return {it.text_index: {"text_index": it.text_index, "source_text": it.source_text or "",
                                "translated_text": it.translated_text or ""}
                for it in cache_io.iter_items(proj) if (it.source_text or "").strip()}


# --------------------------------------------------------------- rules ----
class Rules:
    def __init__(self, cfg: dict, glossary_dst: list[str] = ()):
        red = list(cfg.get("redline", []))
        self.redline = re.compile("|".join(red)) if red else NEVER
        settled = list(cfg.get("settled", []))
        if cfg.get("glossary_settled", True):
            settled += [re.escape(t) for t in sorted(set(glossary_dst), key=len, reverse=True)]
        self.settled = re.compile("|".join(settled)) if settled else NEVER
        forbid = cfg.get("forbid", r"[「」\"]")
        self.forbid = re.compile(forbid) if forbid else NEVER
        self.soft_block = set(cfg.get("soft_block", DEFAULT_SOFT_BLOCK))
        self.term_only = [tuple(x) for x in cfg.get("term_only", [])]
        self.norm = [(re.compile(p), r) for p, r in cfg.get("norm", [])]
        self.leak_files = list(cfg.get("leak_files", DEFAULT_LEAK_FILES))

    def violation(self, off: str, prop: str) -> str:
        if self.forbid.search(prop):
            return "forbid_char"
        if collections.Counter(self.redline.findall(off)) != collections.Counter(self.redline.findall(prop)):
            return "E_redline"
        if set(self.settled.findall(off)) - set(self.settled.findall(prop)):
            return "E_settled_removed"
        return ""

    def normalize(self, s: str) -> str:
        """Symmetric: apply to both old and new text; a diff that vanishes is term-only."""
        for a, b in self.term_only:
            s = s.replace(a, b)
        for rx, r in self.norm:
            s = rx.sub(r, s)
        s = re.sub(r"([一-鿿]) +(?=[一-鿿，。、；：？！“”『』（）—…])", r"\1", s)  # spaces left by de-Latinising
        return s


def load_rules(paths: Paths, locked: str | None = None) -> Rules:
    cfg = {}
    cp = paths.f("config.json")
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            cfg = json.load(f)
    dst: list[str] = []
    locked = locked or cfg.get("glossary") or os.path.join(os.path.dirname(os.path.abspath(paths.cache)),
                                                             "glossary.locked.json")
    if cfg.get("glossary_settled", True) and locked and os.path.exists(locked):
        with open(locked, encoding="utf-8") as f:
            gl = json.load(f)
        dst = [t["dst"].strip() for t in gl.get("terms", []) if (t.get("dst") or "").strip()
               and not t.get("keep_source")]
    return Rules(cfg, dst)


# ---------------------------------------------------------------- gate ----
def check(f: dict, seg: dict | None, rules: Rules) -> tuple[bool, str, str | None]:
    """Gate one finding against the text it was written for. -> (ok, reason, new_text)."""
    req = ("id", "text_index", "category", "offending", "proposed")
    if any(k not in f or f[k] in (None, "") for k in req):
        return False, "missing_field", None
    if f["category"] not in ("A", "B", "C", "D"):
        return False, "bad_category", None
    if seg is None:
        return False, "unknown_index", None
    src, old = seg["source_text"], seg["translated_text"]
    off, prop = f["offending"], f["proposed"]
    n = old.count(off)
    if n != 1:
        return False, f"ambiguous({n})", None
    why = rules.violation(off, prop)
    if why:
        return False, why, None
    h_off, h_prop = len(HAN.findall(off)), len(HAN.findall(prop))
    if h_off >= REWRITE_MIN and not (REWRITE_RATIO[0] <= h_prop / h_off <= REWRITE_RATIO[1]):
        return False, f"rewrite_length({h_prop}/{h_off})", None
    new = old.replace(off, prop, 1)
    hard, soft_new = audit.lint_pair(src, new)
    if hard:
        return False, "tag:" + ",".join(hard), None
    _, soft_old = audit.lint_pair(src, old)
    added = (set(soft_new) - set(soft_old)) & rules.soft_block
    if added:
        return False, "soft:" + ",".join(sorted(added)), None
    if collections.Counter(LATIN.findall(off)) != collections.Counter(LATIN.findall(prop)):
        if not (f.get("latin_change") and f["category"] == "A"):
            return False, "name_touch", None
    return True, "", new


def pre(paths: Paths, rules: Rules, files: list[str]) -> list[dict]:
    out = []
    for p in files:
        g = group_of(p)
        segs = paths.group_src(g)
        ok_rows, bad_rows, stats = [], [], collections.Counter()
        for f in read_jsonl(p):
            ti = f.get("text_index")
            seg = segs.get(int(ti)) if isinstance(ti, int) or (isinstance(ti, str) and ti.isdigit()) else None
            ok, why, new = check(f, seg, rules)
            if ok:
                f["_new_text"] = new
                if f.get("latin_change") and f["category"] == "A":
                    f["_human"] = True
                ok_rows.append(f)
                stats[f["category"]] += 1
            else:
                f["_reject"] = why
                bad_rows.append(f)
                stats["rej:" + why.split("(")[0].split(":")[0]] += 1
        write_jsonl(paths.f(f"findings_{g}.pre.jsonl"), ok_rows)
        write_jsonl(paths.f(f"rejected_{g}.jsonl"), bad_rows)
        row = {"group": g, "in": len(ok_rows) + len(bad_rows), "ok": len(ok_rows), "rejected": len(bad_rows),
               "stats": dict(stats)}
        out.append(row)
        print(f"[{g}] in={row['in']} ok={row['ok']} rejected={row['rejected']}  {row['stats']}")
    return out


def segs_for(paths: Paths, files: list[str]) -> None:
    for p in files:
        g = group_of(p)
        segs = paths.group_src(g)
        idx = sorted({int(f["text_index"]) for f in read_jsonl(p)})
        rows = [{"text_index": i, "source_text": segs[i]["source_text"], "translated_text": segs[i]["translated_text"]}
                for i in idx if i in segs]
        op = paths.f(f"segs_{g}.json")
        write_json(op, rows)
        print(f"[{g}] segs={len(rows)} -> {op}")


def blind(paths: Paths, groups: list[str]) -> None:
    """Strip the source: the Blind Reader must judge the target text the way a reader of the book does."""
    for g in groups:
        segs = paths.group_src(g)
        rows = [{"text_index": i, "translated_text": r["translated_text"]} for i, r in sorted(segs.items())]
        ctx_p = os.path.join(paths.groups, f"grp_{g}_ctx.json")
        ctx = []
        if os.path.exists(ctx_p):
            with open(ctx_p, encoding="utf-8") as f:
                ctx = [{"text_index": r["text_index"], "translated_text": r.get("translated_text") or ""}
                       for r in json.load(f)]
        op = os.path.join(paths.groups, f"blind_{g}.json")
        write_json(op, {"context": ctx, "segments": rows})
        print(f"[{g}] blind segments={len(rows)} context={len(ctx)} -> {op}")


def hints(paths: Paths, files: list[str]) -> list[dict]:
    """flags_X.jsonl rows {id, text_index, quote, why[, severity]} -> hints_X.json grouped per segment,
    with the source attached, for the Reviewer. A flag whose quote is not in the segment is rejected."""
    out = []
    for p in files:
        g = group_of(p)
        segs = paths.group_src(g)
        per, bad = collections.defaultdict(list), []
        for fl in read_jsonl(p):
            ti = fl.get("text_index")
            seg = segs.get(int(ti)) if str(ti).isdigit() else None
            q = (fl.get("quote") or "").strip()
            if seg is None:
                fl["_reject"] = "unknown_index"
            elif not q or q not in seg["translated_text"]:
                fl["_reject"] = "quote_not_found"
            else:
                per[int(ti)].append({k: fl.get(k) for k in ("id", "quote", "why", "severity") if fl.get(k) is not None})
                continue
            bad.append(fl)
        rows = [{"text_index": i, "source_text": segs[i]["source_text"], "translated_text": segs[i]["translated_text"],
                 "flags": fl} for i, fl in sorted(per.items())]
        write_json(paths.f(f"hints_{g}.json"), rows)
        write_jsonl(paths.f(f"rejected_flags_{g}.jsonl"), bad)
        row = {"group": g, "flags": sum(len(v) for v in per.values()), "segments": len(rows), "rejected": len(bad)}
        out.append(row)
        print(f"[{g}] flags={row['flags']} on {row['segments']} segs, rejected={row['rejected']} -> hints_{g}.json")
    return out


def _apply_verdicts(findings: dict, verdicts: dict, segs: dict, rules: Rules):
    """-> (per_seg findings that survived, rejected)."""
    per_seg, rej = collections.defaultdict(list), []
    for fid, f in findings.items():
        v = verdicts.get(fid)
        if not v or v.get("verdict") == "reject":
            f["_reject"] = "challenger:" + (v.get("reason", "") if v else "no_verdict")
            rej.append(f)
            continue
        if v.get("verdict") == "amend" and v.get("amended"):
            f["proposed"] = v["amended"]
            ok, why, _ = check(f, segs.get(int(f["text_index"])), rules)
            if not ok:
                f["_reject"] = "amend_failed:" + why
                rej.append(f)
                continue
        reason = v.get("reason", "") or ""
        f["_verdict_reason"] = reason
        m = CATEGORY_RE.search(reason)
        if m:
            f["category"] = m.group(1)
        m = SEVERITY_RE.search(reason)
        if m:
            f["severity"] = int(m.group(2))
        per_seg[int(f["text_index"])].append(f)
    return per_seg, rej


def final(paths: Paths, rules: Rules, groups: list[str]) -> list[dict]:
    out = []
    for g in groups:
        fp, vp = paths.f(f"findings_{g}.pre.jsonl"), paths.f(f"verdicts_{g}.jsonl")
        if not os.path.exists(fp):
            print(f"[{g}] no {os.path.basename(fp)}, skip (run `pre` first)")
            continue
        findings = {f["id"]: f for f in read_jsonl(fp)}
        if os.path.exists(vp):
            verdicts = {v["id"]: v for v in read_jsonl(vp)}
        else:   # a group without a Challenger (e.g. the consistency auditor): everything goes to the human list
            verdicts = {fid: {"verdict": "accept", "reason": "no challenger"} for fid in findings}
        segs = paths.group_src(g)
        per_seg, rej = _apply_verdicts(findings, verdicts, segs, rules)
        apply_rows, review_rows = [], []
        for idx, fs in per_seg.items():
            seg = segs[idx]
            text = seg["translated_text"]
            auto = [f for f in fs if f["category"] in ("A", "B") and not f.get("_human")]
            manual = [f for f in fs if f not in auto]
            kept = []
            for f in auto:   # several findings on one segment: apply in sequence on the same text
                if text.count(f["offending"]) == 1:
                    text = text.replace(f["offending"], f["proposed"], 1)
                    kept.append(f)
                else:
                    f["_reject"] = "apply_conflict"
                    rej.append(f)
            if kept:
                hard, _ = audit.lint_pair(seg["source_text"], text)
                if hard:
                    for f in kept:
                        f["_reject"] = "combined_tag"
                        rej.append(f)
                else:
                    apply_rows.append({"text_index": idx, "polished_text": text, "_findings": [f["id"] for f in kept]})
            review_rows.extend(manual)
        apply_rows.sort(key=lambda r: r["text_index"])
        review_rows.sort(key=lambda r: (-int(r.get("severity") or 0), int(r["text_index"])))
        write_json(paths.f(f"apply_{g}.json"), [{k: v for k, v in r.items() if not k.startswith("_")} for r in apply_rows])
        write_json(paths.f(f"apply_{g}.meta.json"), apply_rows)
        _write_review_md(paths.f(f"review_{g}.md"), review_rows, f"待过目（{g}）—— C/D 类与需人工的 A 类")
        append_jsonl(paths.f(f"rejected_{g}.jsonl"), rej)
        row = {"group": g, "apply_segments": len(apply_rows), "review": len(review_rows), "rejected": len(rej)}
        out.append(row)
        print(f"[{g}] apply(A/B)={row['apply_segments']} segs  review(C/D/human)={row['review']}  rejected={row['rejected']}")
    return out


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _write_review_md(path: str, rows: list[dict], title: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}，共 {len(rows)} 条，按严重度降序\n\n")
        f.write("勾选方式：把要改的条目 id 列出来，或说「severity 2 以上全改」；主控按 id 生成 apply 文件后 `polish write`。\n\n")
        f.write("| id | 段 | 类/严 | 现译 | 改为 | Reviewer 理由 | Challenger |\n|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['id']} | {r['text_index']} | {r['category']}/{r.get('severity', '')} | "
                    f"{_esc(r['offending'])} | {_esc(r['proposed'])} | {_esc(r.get('reason', ''))[:80]} | "
                    f"{_esc(r.get('_verdict_reason', ''))[:80]} |\n")


def merge(paths: Paths, groups: list[str], out: str | None = None) -> int:
    """Everything that survived the gate + Challenger but was not auto-applied, all groups, one list."""
    rows = []
    for g in groups:
        fp = paths.f(f"findings_{g}.pre.jsonl")
        if not os.path.exists(fp):
            continue
        fs = {f["id"]: f for f in read_jsonl(fp)}
        vp = paths.f(f"verdicts_{g}.jsonl")
        vs = {v["id"]: v for v in read_jsonl(vp)} if os.path.exists(vp) else {}
        mp = paths.f(f"apply_{g}.meta.json")
        applied = set()
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                applied = {i for r in json.load(f) for i in r.get("_findings", [])}
        for fid, f in fs.items():
            v = vs.get(fid, {"verdict": "accept", "reason": "no challenger"})
            if v.get("verdict") == "reject" or fid in applied:
                continue
            f = dict(f)
            if v.get("amended"):
                f["proposed"] = v["amended"]
            f["_verdict_reason"] = v.get("reason", "")
            m = CATEGORY_RE.search(f["_verdict_reason"] or "")
            if m:
                f["category"] = m.group(1)
            rows.append(f)
    rows.sort(key=lambda r: (-int(r.get("severity") or 0), int(r["text_index"])))
    out = out or paths.f("review_ALL.md")
    _write_review_md(out, rows, f"待过目合并清单（{', '.join(groups)}）")
    tally = dict(collections.Counter("%s/%s" % (r["category"], r.get("severity", "")) for r in rows))
    print(f"merged {len(rows)} -> {out}  {tally}")
    return len(rows)


def pick(paths: Paths, rules: Rules, ids: list[str], groups: list[str], out: str | None = None) -> int:
    """Turn the human's chosen finding ids (from review_*.md) into one apply file for `polish write`."""
    want = set(ids)
    chosen = collections.defaultdict(list)
    for g in groups:
        fp = paths.f(f"findings_{g}.pre.jsonl")
        if not os.path.exists(fp):
            continue
        vp = paths.f(f"verdicts_{g}.jsonl")
        vs = {v["id"]: v for v in read_jsonl(vp)} if os.path.exists(vp) else {}
        for f in read_jsonl(fp):
            if f["id"] in want:
                if vs.get(f["id"], {}).get("amended"):
                    f["proposed"] = vs[f["id"]]["amended"]
                chosen[int(f["text_index"])].append(f)
                want.discard(f["id"])
    if want:
        print(f"unknown ids: {sorted(want)}")
    proj = cache_io.load_cache(paths.cache)
    cur = {it.text_index: it for it in cache_io.iter_items(proj)}
    rows, skipped = [], []
    for idx, fs in chosen.items():
        it = cur.get(idx)
        if it is None:
            skipped.append((idx, "unknown_index"))
            continue
        text = it.translated_text or ""
        applied = []
        for f in fs:
            if text.count(f["offending"]) != 1:
                skipped.append((f["id"], "offending not found once in current text"))
                continue
            text = text.replace(f["offending"], f["proposed"], 1)
            applied.append(f["id"])
        if applied:
            hard, _ = audit.lint_pair(it.source_text or "", text)
            if hard:
                skipped.append((idx, "tag:" + ",".join(hard)))
                continue
            rows.append({"text_index": idx, "polished_text": text, "_findings": applied})
    rows.sort(key=lambda r: r["text_index"])
    out = out or paths.f("apply_pick.json")
    write_json(out, [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    write_json(out.replace(".json", ".meta.json"), rows)
    print(f"pick: {len(rows)} segment(s) -> {out}" + (f"; skipped {skipped}" if skipped else ""))
    return len(rows)


# ----------------------------------------------------------- benchmark ----
def benchmark(paths: Paths, rules: Rules, baseline: str, lo: int, hi: int) -> dict:
    cur = {it.text_index: it for it in cache_io.iter_items(cache_io.load_cache(paths.cache))}
    old = {it.text_index: it for it in cache_io.iter_items(cache_io.load_cache(baseline))}
    changed, substantive, term_only = [], [], []
    for i in sorted(cur):
        if not (lo <= i <= hi and i in old):
            continue
        c, o = cur[i].translated_text or "", old[i].translated_text or ""
        if c == o:
            continue
        changed.append(i)
        (term_only if rules.normalize(o) == rules.normalize(c) else substantive).append(i)
    res = {"range": [lo, hi], "baseline": baseline, "changed_all": changed, "term_only": term_only,
           "changed": substantive, "count": len(substantive), "count_all": len(changed)}
    write_json(paths.f("benchmark.json"), res)
    print(json.dumps({k: v for k, v in res.items() if k not in ("changed", "changed_all", "term_only")},
                     ensure_ascii=False))
    print("changed:", substantive)
    return res


def _leaked_examples(paths: Paths, rules: Rules) -> set[str]:
    """Target-language strings (≥4 Han chars) sitting in table cells of the checklist/taxonomy files —
    an old translation containing one of them was effectively handed the answer."""
    files = [paths.f(n) for n in rules.leak_files]
    files.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "references", "review_taxonomy.md"))
    out = set()
    for fn in files:
        if not os.path.exists(fn):
            continue
        with open(fn, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                for cell in line.split("|"):
                    for piece in re.split(r"[／/、；;，,→（）()\s]+", cell):
                        piece = piece.strip("*` ")
                        if len(HAN.findall(piece)) >= 4:
                            out.add(piece)
    return out


def score(paths: Paths, rules: Rules, groups: list[str]) -> str:
    with open(paths.f("benchmark.json"), encoding="utf-8") as f:
        bm = json.load(f)
    changed = set(bm["changed"])
    leak = _leaked_examples(paths, rules)
    lines = []
    for g in groups:
        raw = read_jsonl(paths.f(f"findings_{g}.jsonl"))
        pp = paths.f(f"findings_{g}.pre.jsonl")
        pre_ = read_jsonl(pp) if os.path.exists(pp) else []
        vp = paths.f(f"verdicts_{g}.jsonl")
        verd = {v["id"]: v for v in read_jsonl(vp)} if os.path.exists(vp) else {}
        src = paths.group_src(g)
        in_range = {i for i in changed if i in src}
        leaked = {i for i in in_range if any(ex in src[i]["translated_text"] for ex in leak)}
        clean = in_range - leaked
        found_all = {int(f["text_index"]) for f in raw}
        found_pre = {int(f["text_index"]) for f in pre_}
        acc = lambda f: verd.get(f["id"], {}).get("verdict") in ("accept", "amend")  # noqa: E731
        found_acc = {int(f["text_index"]) for f in pre_ if acc(f)}
        found_ab = {int(f["text_index"]) for f in pre_ if f["category"] in ("A", "B") and acc(f)}
        acc_rate = (sum(1 for f in pre_ if acc(f)) / len(pre_)) if pre_ and verd else None
        fp_ = paths.f(f"flags_{g}.jsonl")
        flagged = {int(x["text_index"]) for x in read_jsonl(fp_)} if os.path.exists(fp_) else None
        pct = lambda a, b: f"{len(a)}/{len(b)} = {len(a) / max(1, len(b)):.0%}"  # noqa: E731
        lines.append(
            f"[{g}] human-changed {len(in_range)} seg ({len(leaked)} leaked via checklist examples) | "
            f"Reviewer {len(raw)} findings/{len(found_all)} seg | gate {len(found_pre)} seg | Challenger {len(found_acc)} seg\n"
            f"     recall(any, gated):      {pct(found_pre & in_range, in_range)}   | leak-free: {pct(found_pre & clean, clean)}\n"
            f"     recall(Challenger ok):   {pct(found_acc & in_range, in_range)}\n"
            f"     recall(A/B ok):          {pct(found_ab & in_range, in_range)}\n"
            f"     Challenger accept rate:  {acc_rate if acc_rate is None else f'{acc_rate:.0%}'} | "
            f"flagged but human left as-is: {len(found_acc - in_range)}\n"
            f"     human-changed, not flagged: {sorted(in_range - found_pre)}"
            + (f"\n     blind-reader flags:      {pct(flagged & in_range, in_range)}   | leak-free: {pct(flagged & clean, clean)}"
               if flagged is not None else ""))
    out = "\n".join(lines)
    print(out)
    with open(paths.f("scores.md"), "a", encoding="utf-8") as f:
        f.write(f"\n## score {datetime.datetime.now():%Y-%m-%d %H:%M}\n```\n{out}\n```\n")
    return out


# ------------------------------------------------------------- inventory ----
_STOP = set("the a an of to in on at for and or but with by from as is was were be been his her its their "
            "he she it they them him this that these those into onto over under out up down off".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z’'\-]+")
_TAGS = re.compile(r"</?[ib]>")


def _han_subs(s, lo=2, hi=6):
    out = set()
    for run in re.findall(r"[一-鿿]+", s):
        for n in range(lo, hi + 1):
            out.update(run[i:i + n] for i in range(len(run) - n + 1))
    return out


def inventory(paths: Paths, lo: int, hi: int, locked: str | None, min_count: int = 2, max_terms: int = 200) -> dict:
    proj = cache_io.load_cache(paths.cache)
    items = [it for it in cache_io.iter_items(proj) if lo <= it.text_index <= hi
             and it.translation_status in (1, 2) and (it.source_text or "").strip()]
    segs = {it.text_index: {"source_text": it.source_text, "translated_text": it.translated_text or ""} for it in items}
    gl = {}
    if locked and os.path.exists(locked):
        with open(locked, encoding="utf-8") as f:
            gl = json.load(f)
    chars = gl.get("characters", [])
    names = {c["canonical"] for c in chars} | {al for c in chars for al in c.get("aliases", [])} | \
            {w for c in chars for w in c["canonical"].split()}
    gl_src = {t["src"] for t in gl.get("terms", []) if t.get("src")} - names
    lower_seen = set()
    for it in items:
        lower_seen.update(w for w in _WORD.findall(_TAGS.sub("", it.source_text)) if w[0].islower())
    name_tokens = {w.lower() for n in names for w in n.split()}
    term_segs = collections.defaultdict(set)
    for it in items:
        s = _TAGS.sub("", it.source_text)
        i = it.text_index
        low = s.lower()
        for t in gl_src:
            if re.search(r"(?<![A-Za-z])" + re.escape(t.lower()) + r"(?![A-Za-z])", low):
                term_segs[t].add(i)
        words = [w.lower() for w in _WORD.findall(s)]
        for n in (2, 3):
            for k in range(len(words) - n + 1):
                ws = words[k:k + n]
                if ws[0] in _STOP or ws[-1] in _STOP or all(w in _STOP for w in ws):
                    continue
                if any(w in name_tokens or w in ("said", "asked", "replied") for w in ws):
                    continue
                term_segs[" ".join(ws)].add(i)
        for w in _WORD.findall(s):
            if (w[0].isupper() and w.lower() not in _STOP and w not in gl_src and w not in names
                    and w.lower() not in lower_seen):
                term_segs[w].add(i)
    terms = sorted(((t, sorted(v)) for t, v in term_segs.items() if len(v) >= min_count),
                   key=lambda kv: (-len(kv[1]), kv[0]))[:max_terms]
    all_subs, seg_subs = collections.Counter(), {}
    for i, sg in segs.items():
        ss = _han_subs(sg["translated_text"])
        seg_subs[i] = ss
        all_subs.update(ss)
    out_terms = []
    for t, idxs in terms:
        cov = collections.Counter()
        for i in idxs:
            cov.update(seg_subs.get(i, ()))
        hints = {sub: [i for i in idxs if sub in seg_subs[i]] for sub, c in cov.most_common(60)
                 if c >= max(2, len(idxs) * 0.5) and c / all_subs[sub] >= 0.6}
        keep = {}
        for sub in sorted(hints, key=len, reverse=True):
            if not any(sub in k and sub != k for k in keep):
                keep[sub] = hints[sub]
        out_terms.append({"src": t, "count": len(idxs), "segments": idxs, "hints": dict(list(keep.items())[:4])})
    sent_segs = collections.defaultdict(list)
    for it in items:
        for sent in re.split(r"(?<=[.!?])\s+", _TAGS.sub("", it.source_text)):
            sent = sent.strip().strip("“”\"")
            if len(_WORD.findall(sent)) >= 6:
                sent_segs[sent].append(it.text_index)
    callbacks = [{"source": s, "segments": [{"text_index": i, "translated_text": segs[i]["translated_text"]} for i in v]}
                 for s, v in sent_segs.items() if len(set(v)) >= 2]
    inv = {"range": [lo, hi], "terms": out_terms, "callbacks": callbacks,
           "segments": {str(k): v for k, v in segs.items()}}
    op = paths.f("inventory.json")
    write_json(op, inv)
    print(json.dumps({"range": [lo, hi], "segments": len(segs), "terms": len(out_terms),
                      "callbacks": len(callbacks), "out": op}, ensure_ascii=False))
    return inv


# ------------------------------------------------------------------ log ----
def log(paths: Paths, stage: str, group: str | None, model: str | None, agent: str | None,
        file: str | None, note: str | None = None) -> dict:
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "stage": stage, "group": group,
           "model": model, "agent": agent, "file": file}
    if file and os.path.exists(file):
        if file.endswith(".jsonl"):
            rows = read_jsonl(file)
        else:
            with open(file, encoding="utf-8") as f:
                rows = json.load(f)
        row["count"] = len(rows)
        if stage in ("apply", "revert"):
            row["finding_ids"] = [i for r in rows for i in r.get("_findings", [])]
    if note:
        row["note"] = note
    os.makedirs(paths.dir, exist_ok=True)
    append_jsonl(paths.f("review_log.jsonl"), [row])
    print(json.dumps(row, ensure_ascii=False))
    return row


# ------------------------------------------------------------------ CLI ----
def main(argv=None):
    ap = argparse.ArgumentParser(description="Adversarial review: gate / merge / score / inventory / benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, files=None, groups=None):
        p.add_argument("cache")
        p.add_argument("--dir", help="review dir (default <cache dir>/review)")
        if files:
            p.add_argument("files", nargs="+", metavar=files)
        if groups:
            p.add_argument("groups", nargs="+", metavar="GROUP")

    b = sub.add_parser("benchmark", help="segments a human changed since a snapshot -> benchmark.json")
    common(b)
    b.add_argument("--baseline", required=True, help="older cache.json (e.g. a .bak.* copy)")
    b.add_argument("--range", required=True, metavar="A-B")

    inv = sub.add_parser("inventory", help="term inventory for the consistency auditor -> inventory.json")
    common(inv)
    inv.add_argument("--range", required=True, metavar="A-B")
    inv.add_argument("--locked", help="glossary.locked.json (default <cache dir>/glossary.locked.json)")
    inv.add_argument("--min-count", type=int, default=2)
    inv.add_argument("--max-terms", type=int, default=200)

    common(sub.add_parser("pre", help="mechanical gate -> findings_X.pre.jsonl + rejected_X.jsonl"), files="FINDINGS_JSONL")
    common(sub.add_parser("segs", help="segments the Challenger needs -> segs_X.json"), files="FINDINGS_PRE_JSONL")
    common(sub.add_parser("blind", help="target-only copy of groups for the Blind Reader -> groups/blind_X.json"), groups=True)
    common(sub.add_parser("hints", help="validate Blind Reader flags -> hints_X.json for the Reviewer"), files="FLAGS_JSONL")
    common(sub.add_parser("final", help="merge verdicts -> apply_X.json (A/B) + review_X.md (C/D)"), groups=True)
    m = sub.add_parser("merge", help="all groups' leftover C/D -> review_ALL.md")
    common(m, groups=True)
    m.add_argument("--out")
    pk = sub.add_parser("pick", help="chosen finding ids -> apply_pick.json for `polish write`")
    common(pk, groups=True)
    pk.add_argument("--ids", nargs="+", required=True)
    pk.add_argument("--out")
    common(sub.add_parser("score", help="recall/precision on benchmark groups"), groups=True)
    lg = sub.add_parser("log", help="append a provenance row to review_log.jsonl")
    common(lg)
    lg.add_argument("--stage", required=True)
    lg.add_argument("--group")
    lg.add_argument("--model")
    lg.add_argument("--agent")
    lg.add_argument("--file")
    lg.add_argument("--note")

    a = ap.parse_args(argv)
    paths = Paths(a.cache, a.dir)
    if a.cmd == "log":
        log(paths, a.stage, a.group, a.model, a.agent, a.file, a.note)
        return 0
    rules = load_rules(paths, getattr(a, "locked", None))
    if a.cmd in ("benchmark", "inventory"):
        try:
            lo, hi = (int(x) for x in a.range.split("-", 1))
        except ValueError:
            ap.error(f"bad --range {a.range!r}")
    os.makedirs(paths.dir, exist_ok=True)
    if a.cmd == "benchmark":
        benchmark(paths, rules, a.baseline, lo, hi)
    elif a.cmd == "inventory":
        locked = a.locked or os.path.join(os.path.dirname(os.path.abspath(a.cache)), "glossary.locked.json")
        inventory(paths, lo, hi, locked, a.min_count, a.max_terms)
    elif a.cmd == "pre":
        pre(paths, rules, a.files)
    elif a.cmd == "segs":
        segs_for(paths, a.files)
    elif a.cmd == "blind":
        blind(paths, a.groups)
    elif a.cmd == "hints":
        hints(paths, a.files)
    elif a.cmd == "final":
        final(paths, rules, a.groups)
    elif a.cmd == "merge":
        merge(paths, a.groups, a.out)
    elif a.cmd == "pick":
        pick(paths, rules, a.ids, a.groups, a.out)
    elif a.cmd == "score":
        score(paths, rules, a.groups)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
