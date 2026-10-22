"""The translation loop's plumbing, all deterministic:

  read / read-translated   next batch for the agent (translate / polish)
  split                    chapter-aligned, size-balanced groups for parallel agents
                           (+ per-group source files and preceding-context files);
                           --stage polish cuts TRANSLATED segments for a parallel polish pass;
                           --stage review cuts TRANSLATED+POLISHED segments (optionally --range A-B,
                           --prefix g) for an adversarial review pass (see review.py)
  validate                 check one group's output against its source BEFORE writing
  write                    gate + write one or many translation files (JSON or JSONL)
                           in a single lock/backup/load/save
  apply                    the one write path for fixes: rows with translated_text / polished_text
                           / patches [[old, new]…]; keeps each segment's status (no downgrade);
                           --source records provenance (and protects meaning fixes from later passes)
  bundle                   one compact file per group (rule card + glossary TSV + context + source),
                           so a subagent reads once and writes once
"""
import argparse
import json
import math
import os
from collections import Counter

from . import cache_io, audit, state
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus


# ---------------------------------------------------------------- read ----
def read_batch(project, size: int = 100) -> list[dict]:
    out = []
    for item in cache_io.iter_untranslated(project):
        out.append({"text_index": item.text_index, "source_text": item.source_text})
        if len(out) >= size:
            break
    return out


def read_translated_batch(project, size: int = 100) -> list[dict]:
    """Next batch of TRANSLATED-not-yet-polished items, for the polish pass."""
    out = []
    for item in cache_io.iter_translated_unpolished(project):
        out.append({"text_index": item.text_index, "source_text": item.source_text,
                    "translated_text": item.translated_text or ""})
        if len(out) >= size:
            break
    return out


# ------------------------------------------------------- agent output IO ----
def load_translations(path: str) -> list[dict]:
    """A JSON array, a JSON object with "items", or JSONL (one object per line —
    what a subagent should append as it goes, so a crash keeps the prefix)."""
    with open(path, encoding="utf-8") as f:
        if path.endswith(".jsonl"):
            rows = []
            for ln, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{ln}: {e}") from e
            return rows
        data = json.load(f)
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array")
    return data


def load_many(paths: list[str]) -> list[dict]:
    rows = []
    for p in paths:
        rows.extend(load_translations(p))
    return rows


def row_text(r: dict) -> str:
    """The agent's output text: `polished_text` for polish rows, else `translated_text`."""
    return r["polished_text"] if "polished_text" in r else r.get("translated_text", "")


def make_check(allow_tag_mismatch: bool = False, cache_path: str | None = None):
    """Write gate. With `cache_path`, decisions.json next to it adds per-segment tag exceptions
    and the book's lint rules (soft)."""
    d = state.load(cache_path)
    exc, rules = state.tag_exceptions(d), state.lint_rules(d)

    def check(item, text):
        return audit.lint_pair(item.source_text, text, allow_tag_mismatch or item.text_index in exc, rules)
    return check


def write_back(cache_path: str, translations: list[dict], *, force: bool = False,
               allow_tag_mismatch: bool = False) -> cache_io.WriteResult:
    return cache_io.apply_writeback(cache_path, translations, TranslationStatus.TRANSLATED,
                                    lambda t: t.get("translated_text", ""),
                                    check=make_check(allow_tag_mismatch, cache_path), force=force)


def apply_rows(cache_path: str, rows: list[dict], *, source: str | None = None, reason: str | None = None,
               force: bool = False, allow_tag_mismatch: bool = False) -> cache_io.WriteResult:
    """Unified fix write: text from translated_text / polished_text / patches, status kept.
    A row may carry its own `reason`; `source` (e.g. dual, codex, adversarial, user) goes to provenance."""
    res = cache_io.apply_writeback(cache_path, rows, None, row_text,
                                   check=make_check(allow_tag_mismatch, cache_path), force=force)
    if source:
        why = {int(r["text_index"]): r.get("reason") or reason for r in rows}
        state.record(cache_path, [{**c, "source": source, "reason": why.get(c["text_index"])} for c in res.changes])
    return res


def report_write(res: cache_io.WriteResult, verb: str = "applied") -> None:
    print(res.summary(verb))
    for r in res.rejected[:50]:
        print(f"  rejected #{r['text_index']}: {r['reason']}")
    if len(res.rejected) > 50:
        print(f"  … {len(res.rejected) - 50} more")
    if res.warnings:
        print("  warnings: " + ", ".join(f"{k}={v}" for k, v in
                                       sorted(res.warnings.items(), key=lambda kv: -kv[1])))


def duplicates(rows: list[dict]) -> list[int]:
    c = Counter(int(r["text_index"]) for r in rows)
    return sorted(i for i, n in c.items() if n > 1)


# --------------------------------------------------------------- split ----
def chapters(project) -> list[tuple]:
    """Ordered runs [(key, [items])] of consecutive items sharing a chapter key:
    the epub spine file (extra.item_id), else the source file when the project
    has several, else None (no structure known)."""
    multi = len(project.files) > 1
    runs: list[tuple] = []
    for cf in project.files.values():
        for it in cf.items:
            k = (it.extra or {}).get("item_id") or (cf.storage_path if multi else None)
            if runs and runs[-1][0] == k:
                runs[-1][1].append(it)
            else:
                runs.append((k, [it]))
    return runs


def _pending(items, status, keep=None):
    """Items at `status` (an int or a tuple of ints) with source text; `keep(item)` narrows further."""
    ok = (lambda st: st in status) if isinstance(status, (tuple, set, frozenset)) else (lambda st: st == status)
    return [it for it in items if ok(it.translation_status) and (it.source_text or "").strip()
            and (keep is None or keep(it))]


def plan_groups(project, target: int = 300, status=TranslationStatus.UNTRANSLATED, keep=None) -> list[dict]:
    """Greedy: accumulate whole chapters until >= target; a chapter larger than
    1.5×target is chunked on its own; a tail under 0.4×target folds into the
    previous group. `status` may be one int or a tuple; `keep(item)` narrows the
    selection (e.g. a text_index range). Returns [{"chapters": [keys], "items": [CacheItem]}]."""
    chs = [(k, _pending(items, status, keep)) for k, items in chapters(project)]
    chs = [(k, td) for k, td in chs if td]
    groups: list[dict] = []
    cur = {"chapters": [], "items": []}

    def close():
        nonlocal cur
        if cur["items"]:
            groups.append(cur)
        cur = {"chapters": [], "items": []}

    for k, td in chs:
        if len(td) > 1.5 * target:
            close()
            n = math.ceil(len(td) / target)
            size = math.ceil(len(td) / n)
            for i in range(n):
                groups.append({"chapters": [k], "items": td[i * size:(i + 1) * size]})
            continue
        if cur["items"] and len(cur["items"]) + len(td) > 1.25 * target:
            close()
        cur["chapters"].append(k)
        cur["items"].extend(td)
        if len(cur["items"]) >= target:
            close()
    close()
    if len(groups) >= 2 and len(groups[-1]["items"]) < 0.4 * target:
        tail = groups.pop()
        groups[-1]["chapters"] += tail["chapters"]
        groups[-1]["items"] += tail["items"]
    return groups


STAGE_STATUS = {"translate": TranslationStatus.UNTRANSLATED, "polish": TranslationStatus.TRANSLATED,
                "review": (TranslationStatus.TRANSLATED, TranslationStatus.POLISHED)}


def parse_range(s: str | None) -> tuple[int, int] | None:
    """'438-719' -> (438, 719); None/'' -> None."""
    if not s:
        return None
    a, b = s.split("-", 1)
    lo, hi = int(a), int(b)
    if lo > hi:
        raise ValueError(f"bad range {s!r}")
    return lo, hi


def changed_indexes(project, baseline_path: str) -> set[int]:
    """Segments whose translation differs from an older cache (re-review only what changed)."""
    old = {it.text_index: it.translated_text or "" for it in cache_io.iter_items(cache_io.load_cache(baseline_path))}
    return {it.text_index for it in cache_io.iter_items(project) if (it.translated_text or "") != old.get(it.text_index, "")}


def split_project(project, target: int, out_dir: str | None, context: int, stage: str = "translate",
                  index_range: tuple[int, int] | None = None, prefix: str = "",
                  only: set[int] | None = None) -> dict:
    def keep(it):
        return ((not index_range or index_range[0] <= it.text_index <= index_range[1])
                and (only is None or it.text_index in only))
    groups = plan_groups(project, target, STAGE_STATUS[stage], keep)
    all_items = list(cache_io.iter_items(project))
    pos = {it.text_index: i for i, it in enumerate(all_items)}
    rows = []
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "_stage.json"), "w", encoding="utf-8") as f:
            json.dump({"stage": stage, "target": target, "context": context, "groups": len(groups),
                       "prefix": prefix, "range": list(index_range) if index_range else None}, f)
    for n, g in enumerate(groups, 1):
        items = g["items"]
        gid = f"{prefix}{n}"
        row = {"group": gid if prefix else n, "count": len(items),
               "first_index": items[0].text_index, "last_index": items[-1].text_index,
               "chapters": [str(c) for c in g["chapters"] if c is not None]}
        if out_dir:
            src_path = os.path.join(out_dir, f"grp_{gid}_src.json")
            with open(src_path, "w", encoding="utf-8") as f:
                rows_out = [{"text_index": it.text_index, "source_text": it.source_text} for it in items]
                if stage in ("polish", "review"):           # the polisher/reviewer needs the current translation too
                    for r, it in zip(rows_out, items):
                        r["translated_text"] = it.translated_text or ""
                json.dump(rows_out, f, ensure_ascii=False, indent=1)
            row["src_file"] = src_path
            if context > 0:
                p = pos[items[0].text_index]
                prev = [it for it in all_items[:p] if it.translation_status != TranslationStatus.EXCLUDED]
                # Prefer segments that already carry a translation (the point of the
                # context is to hand the agent the established voice); when the group
                # sits right behind another pending group, reach back past it.
                translated = [it for it in prev if (it.translated_text or "").strip()]
                ctx = (translated if translated else prev)[-context:]
                ctx_path = os.path.join(out_dir, f"grp_{gid}_ctx.json")
                with open(ctx_path, "w", encoding="utf-8") as f:
                    json.dump([{"text_index": it.text_index, "source_text": it.source_text,
                                "translated_text": it.translated_text or "",
                                "translation_status": int(it.translation_status)} for it in ctx],
                              f, ensure_ascii=False, indent=1)
                row["ctx_file"] = ctx_path
        rows.append(row)
    return {"stage": stage, "target": target, "pending": sum(r["count"] for r in rows), "groups": rows}


# ------------------------------------------------------------ validate ----
def validate(src_rows: list[dict], trans_rows: list[dict], allow_tag_mismatch: bool = False,
             cache_path: str | None = None) -> dict:
    src_idx = [int(r["text_index"]) for r in src_rows]
    tr_idx = [int(r["text_index"]) for r in trans_rows]
    src_by = {int(r["text_index"]): r.get("source_text") or "" for r in src_rows}
    hard = []
    missing = sorted(set(src_idx) - set(tr_idx))
    extra = sorted(set(tr_idx) - set(src_idx))
    dups = duplicates(trans_rows)
    if missing:
        hard.append({"kind": "missing_index", "count": len(missing), "indexes": missing[:50]})
    if extra:
        hard.append({"kind": "extra_index", "count": len(extra), "indexes": extra[:50]})
    if dups:
        hard.append({"kind": "duplicate_index", "count": len(dups), "indexes": dups[:50]})
    seg_hard, soft = [], {}
    d = state.load(cache_path)
    exc, rules = state.tag_exceptions(d), state.lint_rules(d)
    for r in trans_rows:
        ti = int(r["text_index"])
        if ti not in src_by:
            continue
        h, s = audit.lint_pair(src_by[ti], row_text(r), allow_tag_mismatch or ti in exc, rules)
        if h:
            seg_hard.append({"text_index": ti, "reasons": h})
        for c in s:
            soft.setdefault(c, []).append(ti)
    if seg_hard:
        hard.append({"kind": "segment", "count": len(seg_hard), "items": seg_hard[:50]})
    common = set(src_idx) & set(tr_idx)
    order_ok = [i for i in tr_idx if i in common] == [i for i in src_idx if i in common]
    return {"ok": not hard, "count_src": len(src_rows), "count_trans": len(trans_rows),
            "order_preserved": order_ok, "hard": hard,
            "warnings": {k: {"count": len(v), "segments": v[:20]} for k, v in
                         sorted(soft.items(), key=lambda kv: -len(kv[1]))}}


# -------------------------------------------------------------- bundle ----
def glossary_tsv(locked: dict) -> str:
    """Compact glossary for a prompt: `src<TAB>dst` (dst `=` = keep the source verbatim)."""
    L = []
    for c in locked.get("characters", []):
        names = [c.get("render", "")] + list(c.get("aliases") or [])
        n = [x for x in dict.fromkeys(names) if x]
        if n:
            L.append(f"{n[0]}\t=" + (f"\t(also: {', '.join(n[1:])})" if len(n) > 1 else ""))
    for t in locked.get("terms", []):
        if not t.get("src"):
            continue
        dst = "=" if t.get("keep_source") or not t.get("dst") else t["dst"]
        L.append(f"{t['src']}\t{dst}")
    return "\n".join(L)


def make_bundle(cache_path: str, src_json: str, out_md: str, *, stage: str = "translate",
                locked_path: str | None = None, includes=(), ctx_json: str | None = None,
                out_file: str | None = None, newterms_file: str | None = None) -> dict:
    """One file a subagent reads once: task + output contract, rule card, included rules,
    glossary slice (TSV), context, and the rows to work on (JSON lines, markup intact)."""
    from .glossary import filter_locked
    rows = load_translations(src_json)
    idx = [int(r["text_index"]) for r in rows]
    parts = [f"# {stage} bundle — {os.path.basename(src_json)} ({len(rows)} segments, {min(idx)}–{max(idx)})", ""]
    if stage == "review":
        parts += ["## 交付（一次写完）",
                  "- 逐段对照原文审译文：误译（否定/指代/主被动/数量/语气方向）、漏增译、称谓、术语、中文质量、标点、正典事实。",
                  "- 用一次 Write 写到 prompt 指定的文件，每个问题一行 JSON："
                  "`{\"i\": 段号, \"cat\": \"误译|漏增译|称谓|术语|中文|标点|事实\", \"sev\": 1-3, "
                  "\"issue\": \"一句话（引原文片段）\", \"fix\": \"只改出问题的那部分\"}`；sev 3 = 读者会误解剧情/人物。",
                  "- 规则卡里的已定口径、原文笔误、已修过的语义不要报；两可的措辞偏好不要报。",
                  "- 最终消息只回：各类计数、sev≥2 条数、最严重 5 条（段号+一句话）。", ""]
    elif out_file:
        key = "polished_text" if stage == "polish" else "translated_text"
        parts += ["## 交付（一次写完）",
                  f"- 用一次 Write 把全部结果写到 `{out_file}`：每行一个 JSON "
                  f"`{{\"text_index\": N, \"{key}\": \"…\"}}`，段数、顺序与下面一致，<i>/<b> 成对保留。",
                  "- 写完不要再读回、不要跑校验——主控会校验。"]
        if newterms_file:
            parts.append(f"- 表外新词（词汇表里没有、你自定译法或保留原文的专名/术语/新物种）写到 `{newterms_file}`，"
                         "每行 `原文<TAB>译法`（保留原文就写 `原文<TAB>原文`）。")
        parts += ["- 最终消息只回：段数、新词数、拿不准的 ≤5 条（段号+一句话）。", ""]
    c = state.card(cache_path, min(idx), max(idx))
    if c:
        parts += [c]
    for p in includes:
        with open(p, encoding="utf-8") as f:
            parts += [f"## {os.path.basename(p)}", f.read().strip(), ""]
    if locked_path and os.path.exists(locked_path):
        with open(locked_path, encoding="utf-8") as f:
            sub = filter_locked(json.load(f), [r.get("source_text") or "" for r in rows])
        g = glossary_tsv(sub)
        if g:
            parts += ["## 词汇表（原文<TAB>译法；= 表示保留原文）", "```", g, "```", ""]
    if ctx_json and os.path.exists(ctx_json):
        with open(ctx_json, encoding="utf-8") as f:
            ctx = json.load(f)
        if ctx:
            parts += ["## 前文（只读，对齐语气用）", "```"]
            parts += [json.dumps({"i": r["text_index"], "zh": r.get("translated_text") or ""}, ensure_ascii=False)
                      for r in ctx]
            parts += ["```", ""]
    parts += ["## 待处理段（JSON lines）", "```"]
    keys = ("text_index", "source_text", "translated_text")
    parts += [json.dumps({k: r[k] for k in keys if k in r}, ensure_ascii=False) for r in rows]
    parts += ["```", ""]
    txt = "\n".join(parts)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(txt)
    return {"bundle": out_md, "segments": len(rows), "chars": len(txt)}


# ------------------------------------------------------------------ CLI ----
def main(argv=None):
    ap = argparse.ArgumentParser(description="Batch read/split/validate/write for the translation loop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read", help="Print next untranslated batch as JSON")
    r.add_argument("cache_path")
    r.add_argument("--size", type=int, default=100)

    rt = sub.add_parser("read-translated", help="Print next translated batch (for polish) as JSON")
    rt.add_argument("cache_path")
    rt.add_argument("--size", type=int, default=100)

    sp = sub.add_parser("split", help="Plan chapter-aligned groups of pending segments for parallel agents")
    sp.add_argument("cache_path")
    sp.add_argument("--target", type=int, default=300, help="segments per group (default 300)")
    sp.add_argument("--out-dir", help="also write grp_N_src.json (+ grp_N_ctx.json) here")
    sp.add_argument("--context", type=int, default=20,
                    help="preceding segments to put in grp_N_ctx.json (0 = none)")
    sp.add_argument("--stage", choices=["translate", "polish", "review"], default="translate",
                    help="translate: pending segments (default); polish: TRANSLATED segments, src rows carry "
                         "translated_text; review: TRANSLATED+POLISHED segments for an adversarial review pass")
    sp.add_argument("--range", metavar="A-B", help="only text_index A..B (review/polish of a slice of the book)")
    sp.add_argument("--prefix", default="", help="group id prefix: grp_<prefix><n>_src.json (e.g. g, b)")
    sp.add_argument("--changed-since", metavar="OLD_CACHE",
                    help="only segments whose translation differs from this older cache (re-review a pass's edits)")

    v = sub.add_parser("validate", help="Check a group's translation file against its source file")
    v.add_argument("src_json")
    v.add_argument("trans_json")
    v.add_argument("--allow-tag-mismatch", action="store_true")
    v.add_argument("--cache", help="project cache: apply its decisions.json (tag exceptions, lint rules)")

    w = sub.add_parser("write", help="Gate + write one or more translation files (JSON/JSONL)")
    w.add_argument("cache_path")
    w.add_argument("translations", nargs="+", metavar="TRANS_JSON")
    w.add_argument("--force", action="store_true",
                   help="write despite hard lint failures / duplicate indexes (last wins)")
    w.add_argument("--allow-tag-mismatch", action="store_true",
                   help="do not reject segments whose <i>/<b> counts differ from the source")

    ay = sub.add_parser("apply", help="Write fixes (translated_text / polished_text / patches), keeping each status")
    ay.add_argument("cache_path")
    ay.add_argument("files", nargs="+", metavar="FIX_JSON")
    ay.add_argument("--source", help="provenance label: dual / codex / adversarial / user / editor …")
    ay.add_argument("--reason", help="default reason for rows without one")
    ay.add_argument("--force", action="store_true")
    ay.add_argument("--allow-tag-mismatch", action="store_true")

    bd = sub.add_parser("bundle", help="One read-once file per group for a subagent")
    bd.add_argument("cache_path")
    bd.add_argument("src_json", nargs="+", help="grp_N_src.json files")
    bd.add_argument("--stage", choices=["translate", "polish", "review"], default="translate")
    bd.add_argument("--locked", help="glossary.locked.json (default <cache dir>/glossary.locked.json)")
    bd.add_argument("--include", nargs="*", default=[], metavar="MD", help="rule files to inline (user_prompt, lessons…)")
    bd.add_argument("--out-dir", help="default: next to each src file")

    a = ap.parse_args(argv)
    if a.cmd == "apply":
        try:
            rows = load_many(a.files)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            ap.error(f"cannot read fix file: {e}")
        dups = duplicates(rows)
        if dups and not a.force:
            ap.error(f"duplicate text_index across inputs: {dups[:20]} (merge them, or --force: last wins)")
        res = apply_rows(a.cache_path, rows, source=a.source, reason=a.reason, force=a.force,
                         allow_tag_mismatch=a.allow_tag_mismatch)
        report_write(res)
        print(f"  changed {len(res.changes)} segment(s)" + (f"; provenance: {a.source}" if a.source else ""))
        return 1 if res.rejected else 0
    if a.cmd == "bundle":
        locked = a.locked or os.path.join(os.path.dirname(os.path.abspath(a.cache_path)), "glossary.locked.json")
        for src in a.src_json:
            d = a.out_dir or os.path.dirname(os.path.abspath(src))
            gid = os.path.basename(src).removeprefix("grp_").removesuffix("_src.json")
            ctx = os.path.join(os.path.dirname(os.path.abspath(src)), f"grp_{gid}_ctx.json")
            outf = None if a.stage == "review" else \
                os.path.join(d, f"{'trans' if a.stage == 'translate' else 'polished'}_{gid}.jsonl")
            r = make_bundle(a.cache_path, src, os.path.join(d, f"bundle_{gid}.md"), stage=a.stage,
                            locked_path=locked, includes=a.include, ctx_json=ctx, out_file=outf,
                            newterms_file=os.path.join(d, f"newterms_{gid}.txt") if a.stage == "translate" else None)
            print(f"[{gid}] {r['segments']} segs, {r['chars']} chars -> {r['bundle']}")
        return 0
    if a.cmd == "read":
        project = cache_io.load_cache(a.cache_path)
        print(json.dumps(read_batch(project, size=a.size), ensure_ascii=False))
    elif a.cmd == "read-translated":
        project = cache_io.load_cache(a.cache_path)
        print(json.dumps(read_translated_batch(project, size=a.size), ensure_ascii=False))
    elif a.cmd == "split":
        project = cache_io.load_cache(a.cache_path)
        try:
            rng = parse_range(a.range)
        except ValueError as e:
            ap.error(str(e))
        only = changed_indexes(project, a.changed_since) if a.changed_since else None
        print(json.dumps(split_project(project, a.target, a.out_dir, a.context, a.stage, rng, a.prefix, only),
                         ensure_ascii=False, indent=1))
    elif a.cmd == "validate":
        try:
            src = load_translations(a.src_json)
            tr = load_translations(a.trans_json)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            ap.error(f"cannot read input: {e}")
        rep = validate(src, tr, a.allow_tag_mismatch, a.cache)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["ok"] else 1
    elif a.cmd == "write":
        try:
            rows = load_many(a.translations)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            ap.error(f"cannot read translations file: {e}")
        dups = duplicates(rows)
        if dups and not a.force:
            ap.error(f"duplicate text_index across inputs: {dups[:20]} (use --force to let the last one win)")
        res = write_back(a.cache_path, rows, force=a.force, allow_tag_mismatch=a.allow_tag_mismatch)
        report_write(res)
        return 1 if res.rejected else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
