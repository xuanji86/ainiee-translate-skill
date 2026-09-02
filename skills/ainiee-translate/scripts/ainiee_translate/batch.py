"""The translation loop's plumbing, all deterministic:

  read / read-translated   next batch for the agent (translate / polish)
  split                    chapter-aligned, size-balanced groups for parallel agents
                           (+ per-group source files and preceding-context files);
                           --stage polish cuts TRANSLATED segments for a parallel polish pass
  validate                 check one group's output against its source BEFORE writing
  write                    gate + write one or many translation files (JSON or JSONL)
                           in a single lock/backup/load/save
"""
import argparse
import json
import math
import os
from collections import Counter

from . import cache_io, audit
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


def make_check(allow_tag_mismatch: bool = False):
    def check(item, text):
        return audit.lint_pair(item.source_text, text, allow_tag_mismatch)
    return check


def write_back(cache_path: str, translations: list[dict], *, force: bool = False,
               allow_tag_mismatch: bool = False) -> cache_io.WriteResult:
    return cache_io.apply_writeback(cache_path, translations, TranslationStatus.TRANSLATED,
                                    lambda t: t.get("translated_text", ""),
                                    check=make_check(allow_tag_mismatch), force=force)


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


def _pending(items, status):
    return [it for it in items if it.translation_status == status and (it.source_text or "").strip()]


def plan_groups(project, target: int = 300, status: int = TranslationStatus.UNTRANSLATED) -> list[dict]:
    """Greedy: accumulate whole chapters until >= target; a chapter larger than
    1.5×target is chunked on its own; a tail under 0.4×target folds into the
    previous group. Returns [{"chapters": [keys], "items": [CacheItem]}]."""
    chs = [(k, _pending(items, status)) for k, items in chapters(project)]
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


STAGE_STATUS = {"translate": TranslationStatus.UNTRANSLATED, "polish": TranslationStatus.TRANSLATED}


def split_project(project, target: int, out_dir: str | None, context: int, stage: str = "translate") -> dict:
    groups = plan_groups(project, target, STAGE_STATUS[stage])
    all_items = list(cache_io.iter_items(project))
    pos = {it.text_index: i for i, it in enumerate(all_items)}
    rows = []
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "_stage.json"), "w", encoding="utf-8") as f:
            json.dump({"stage": stage, "target": target, "context": context, "groups": len(groups)}, f)
    for n, g in enumerate(groups, 1):
        items = g["items"]
        row = {"group": n, "count": len(items),
               "first_index": items[0].text_index, "last_index": items[-1].text_index,
               "chapters": [str(c) for c in g["chapters"] if c is not None]}
        if out_dir:
            src_path = os.path.join(out_dir, f"grp_{n}_src.json")
            with open(src_path, "w", encoding="utf-8") as f:
                rows_out = [{"text_index": it.text_index, "source_text": it.source_text} for it in items]
                if stage == "polish":                       # the polisher needs the current translation too
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
                ctx_path = os.path.join(out_dir, f"grp_{n}_ctx.json")
                with open(ctx_path, "w", encoding="utf-8") as f:
                    json.dump([{"text_index": it.text_index, "source_text": it.source_text,
                                "translated_text": it.translated_text or "",
                                "translation_status": int(it.translation_status)} for it in ctx],
                              f, ensure_ascii=False, indent=1)
                row["ctx_file"] = ctx_path
        rows.append(row)
    return {"stage": stage, "target": target, "pending": sum(r["count"] for r in rows), "groups": rows}


# ------------------------------------------------------------ validate ----
def validate(src_rows: list[dict], trans_rows: list[dict], allow_tag_mismatch: bool = False) -> dict:
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
    for r in trans_rows:
        ti = int(r["text_index"])
        if ti not in src_by:
            continue
        h, s = audit.lint_pair(src_by[ti], row_text(r), allow_tag_mismatch)
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
    sp.add_argument("--stage", choices=["translate", "polish"], default="translate",
                    help="translate: pending segments (default); polish: TRANSLATED segments, src rows carry translated_text")

    v = sub.add_parser("validate", help="Check a group's translation file against its source file")
    v.add_argument("src_json")
    v.add_argument("trans_json")
    v.add_argument("--allow-tag-mismatch", action="store_true")

    w = sub.add_parser("write", help="Gate + write one or more translation files (JSON/JSONL)")
    w.add_argument("cache_path")
    w.add_argument("translations", nargs="+", metavar="TRANS_JSON")
    w.add_argument("--force", action="store_true",
                   help="write despite hard lint failures / duplicate indexes (last wins)")
    w.add_argument("--allow-tag-mismatch", action="store_true",
                   help="do not reject segments whose <i>/<b> counts differ from the source")

    a = ap.parse_args(argv)
    if a.cmd == "read":
        project = cache_io.load_cache(a.cache_path)
        print(json.dumps(read_batch(project, size=a.size), ensure_ascii=False))
    elif a.cmd == "read-translated":
        project = cache_io.load_cache(a.cache_path)
        print(json.dumps(read_translated_batch(project, size=a.size), ensure_ascii=False))
    elif a.cmd == "split":
        project = cache_io.load_cache(a.cache_path)
        print(json.dumps(split_project(project, a.target, a.out_dir, a.context, a.stage), ensure_ascii=False, indent=1))
    elif a.cmd == "validate":
        try:
            src = load_translations(a.src_json)
            tr = load_translations(a.trans_json)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            ap.error(f"cannot read input: {e}")
        rep = validate(src, tr, a.allow_tag_mismatch)
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
