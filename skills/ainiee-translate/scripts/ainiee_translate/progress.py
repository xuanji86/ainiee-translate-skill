"""Live translation progress, multi-agent aware. Read-only over work/.

What is observable on disk while agents run (v1.6+ contract):
  work/cache.json            book-level status counts; changes only on `batch write`
  work/par/grp_N_src.json    what each parallel group was handed
  work/par/trans_N.jsonl     grows as the agent appends (every 10-50 segments)
  work/par/newterms_N.txt    new proper nouns the agent kept verbatim
  work/progress.jsonl        write-back events appended by apply_writeback

Per-group state machine:
  written   every index of the group is already non-UNTRANSLATED in the cache
  pending   no trans file yet
  running   trans file incomplete, modified within --stall seconds
  stalled   trans file incomplete, silent longer than --stall seconds
  ready     complete, no segment-level hard problems -> safe to `batch write`
  needs_fix complete but validate would reject rows (empty / tag mismatch / dups / extra)

    progress work/cache.json --watch          rich live panel (2s refresh)
    progress work/cache.json --once           render the panel once
    progress work/cache.json --line           one line for a status bar (also written to
                                              ~/.ainiee-translate/progress.line)
    progress work/cache.json --json           full snapshot
"""
import argparse
import glob
import json
import os
import re
import time

from . import cache_io, batch, audit
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus

STALL_SEC = 180
LINE_FILE = os.path.join(os.path.expanduser(os.environ.get("AINIEE_TRANSLATE_HOME", "~/.ainiee-translate")), "progress.line")
STATE_FILE = LINE_FILE.replace("progress.line", "progress.state.json")
_ICON = {"running": "▶", "stalled": "⏸", "ready": "✓", "needs_fix": "✗", "pending": "·", "written": "■"}


def _read_rows_tolerant(path: str) -> tuple[list[dict], int]:
    """JSONL/JSON rows; a truncated last line (agent mid-append) is skipped, not fatal."""
    rows, bad = [], 0
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".jsonl"):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    else:
        try:
            data = json.loads(text)
            rows = data.get("items", data) if isinstance(data, dict) else data
        except json.JSONDecodeError:
            bad = 1
    return [r for r in rows if isinstance(r, dict) and "text_index" in r], bad


def _group_number(path: str) -> int:
    m = re.search(r"grp_(\d+)_src\.json$", path)
    return int(m.group(1)) if m else 0


def snapshot(cache_path: str, par_dir: str | None = None, stall_sec: int = STALL_SEC) -> dict:
    now = time.time()
    work = os.path.dirname(os.path.abspath(cache_path))
    par_dir = par_dir or os.path.join(work, "par")
    proj = cache_io.load_cache(cache_path)
    items = list(cache_io.iter_items(proj))
    by_idx = {it.text_index: it for it in items}
    counts = {"all": len(items), "excluded": 0, "untranslated": 0, "translated": 0, "polished": 0}
    for it in items:
        s = it.translation_status
        if s == TranslationStatus.EXCLUDED:
            counts["excluded"] += 1
        elif s == TranslationStatus.POLISHED:
            counts["polished"] += 1
        elif s == TranslationStatus.TRANSLATED:
            counts["translated"] += 1
        elif (it.source_text or "").strip():
            counts["untranslated"] += 1
    workable = counts["all"] - counts["excluded"]
    done = counts["translated"] + counts["polished"]
    counts["workable"] = workable
    counts["done"] = done
    counts["done_pct"] = round(100.0 * done / workable, 1) if workable else 100.0

    groups = []
    for src_path in sorted(glob.glob(os.path.join(par_dir, "grp_*_src.json")), key=_group_number):
        n = _group_number(src_path)
        try:
            with open(src_path, encoding="utf-8") as f:
                src_rows = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        src_idx = [int(r["text_index"]) for r in src_rows]
        chapters = []
        for i in src_idx:
            k = (by_idx[i].extra or {}).get("item_id") if i in by_idx else None
            if k and (not chapters or chapters[-1] != k):
                chapters.append(str(k))
        trans_path = next((p for p in (os.path.join(par_dir, f"trans_{n}.jsonl"),
                                       os.path.join(par_dir, f"trans_{n}.json")) if os.path.exists(p)), None)
        g = {"group": n, "src": len(src_idx), "first_index": src_idx[0] if src_idx else None,
             "last_index": src_idx[-1] if src_idx else None, "chapters": chapters,
             "lines": 0, "bad_lines": 0, "age_sec": None, "seg_hard": 0, "dups": 0, "extra": 0,
             "warnings": {}, "newterms": 0, "trans_file": trans_path}
        nt = os.path.join(par_dir, f"newterms_{n}.txt")
        if os.path.exists(nt):
            with open(nt, encoding="utf-8") as f:
                g["newterms"] = sum(1 for l in f if l.strip() and not l.startswith("#"))
        written = bool(src_idx) and all(
            i in by_idx and by_idx[i].translation_status != TranslationStatus.UNTRANSLATED for i in src_idx)
        if written:
            g["state"] = "written"
            g["lines"] = len(src_idx)
        elif trans_path is None:
            g["state"] = "pending"
        else:
            rows, bad = _read_rows_tolerant(trans_path)
            g["lines"], g["bad_lines"] = len(rows), bad
            g["age_sec"] = int(now - os.path.getmtime(trans_path))
            rep = batch.validate(src_rows, rows)
            for h in rep["hard"]:
                if h["kind"] == "segment":
                    g["seg_hard"] = h["count"]
                elif h["kind"] == "duplicate_index":
                    g["dups"] = h["count"]
                elif h["kind"] == "extra_index":
                    g["extra"] = h["count"]
            g["warnings"] = {k: v["count"] for k, v in rep["warnings"].items()}
            complete = len({int(r["text_index"]) for r in rows} & set(src_idx)) >= len(src_idx)
            if complete:
                g["state"] = "needs_fix" if (g["seg_hard"] or g["dups"] or g["extra"]) else "ready"
            else:
                g["state"] = "stalled" if g["age_sec"] > stall_sec else "running"
        g["pct"] = round(100.0 * min(g["lines"], g["src"]) / g["src"], 1) if g["src"] else 100.0
        groups.append(g)

    events = []
    ev_path = os.path.join(work, "progress.jsonl")
    if os.path.exists(ev_path):
        with open(ev_path, encoding="utf-8") as f:
            tail = f.read().splitlines()[-8:]
        for line in tail:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return {"ts": now, "project": proj.project_name or os.path.basename(os.path.dirname(work)),
            "work": work, "stall_sec": stall_sec, "total": counts, "groups": groups, "events": events}


# ------------------------------------------------------------- rate/ETA ----
def _in_flight_lines(snap: dict) -> int:
    return sum(min(g["lines"], g["src"]) for g in snap["groups"] if g["state"] in ("running", "stalled", "ready", "needs_fix"))


def _remaining_lines(snap: dict) -> int:
    return sum(g["src"] - min(g["lines"], g["src"]) for g in snap["groups"] if g["state"] not in ("written",))


def rate_per_min(prev: dict | None, snap: dict) -> float | None:
    if not prev or snap["ts"] <= prev["ts"]:
        return None
    dl = _in_flight_lines(snap) - prev.get("lines", 0)
    dt = (snap["ts"] - prev["ts"]) / 60.0
    return max(0.0, dl / dt) if dt > 0 else None


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_state(snap: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ts": snap["ts"], "lines": _in_flight_lines(snap), "work": snap["work"]}, f)


# ---------------------------------------------------------------- line ----
def one_line(snap: dict, rate: float | None = None) -> str:
    t = snap["total"]
    name = re.sub(r"^Star Trek[_:]?\s*", "", snap["project"] or "").split(":")[0].strip() or "book"
    name = re.sub(r"^[A-Za-z ]+_\s*", "", name)[:24]
    parts = [f"📖 {name} {t['done']}/{t['workable']} ({t['done_pct']:.0f}%)"]
    live = [g for g in snap["groups"] if g["state"] in ("running", "stalled")]
    other = {}
    for g in snap["groups"]:
        if g["state"] in ("ready", "needs_fix", "pending"):
            other.setdefault(g["state"], []).append(str(g["group"]))
    if live:
        parts.append(" ".join(f"{_ICON[g['state']]}{g['group']} {g['lines']}/{g['src']}" for g in live[:6]))
    for st in ("ready", "needs_fix", "pending"):
        if st in other:
            parts.append(f"{_ICON[st]}{','.join(other[st])}")
    if rate:
        parts.append(f"{rate:.1f}/min")
    return " · ".join(parts)


def write_line_file(text: str) -> None:
    try:
        os.makedirs(os.path.dirname(LINE_FILE), exist_ok=True)
        with open(LINE_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


# --------------------------------------------------------------- panel ----
def _fmt_age(sec):
    if sec is None:
        return "—"
    return f"{sec}s" if sec < 90 else f"{sec // 60}m"


def render(snap: dict, rate: float | None = None):
    from rich.console import Group as RGroup
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text

    t = snap["total"]
    style = {"running": "green", "stalled": "bold red", "ready": "bold cyan", "needs_fix": "yellow",
             "pending": "dim", "written": "dim green"}
    head = Table.grid(expand=True)
    head.add_column(ratio=3)
    head.add_column(ratio=2, justify="right")
    bar = ProgressBar(total=max(t["workable"], 1), completed=t["done"], width=40)
    last = snap["events"][-1] if snap["events"] else None
    last_txt = (f"last write {int((snap['ts'] - last['ts']) // 60)}m ago: applied {last['applied']}"
                + (f", rejected {last['rejected']}" if last.get("rejected") else "")) if last else "no write logged"
    head.add_row(RGroup(Text(f"{t['done']}/{t['workable']} segments  ({t['done_pct']}%)   pending {t['untranslated']}"), bar),
                 Text(last_txt, style="dim"))

    from rich import box
    tbl = Table(expand=True, box=box.SIMPLE_HEAD, pad_edge=False, collapse_padding=True)
    for col, kw in (("组", {"justify": "right", "width": 3, "no_wrap": True}),
                    ("章节", {"ratio": 1, "min_width": 8, "no_wrap": True, "overflow": "ellipsis"}),
                    ("进度", {"width": 14, "no_wrap": True}), ("段", {"justify": "right", "width": 9, "no_wrap": True}),
                    ("状态", {"width": 11, "no_wrap": True}), ("更新", {"justify": "right", "width": 4, "no_wrap": True}),
                    ("✗", {"justify": "right", "width": 3, "no_wrap": True}), ("⚠", {"justify": "right", "width": 3, "no_wrap": True}),
                    ("词", {"justify": "right", "width": 3, "no_wrap": True})):
        tbl.add_column(col, **kw)
    for g in snap["groups"]:
        st = g["state"]
        warn = sum(g["warnings"].values())
        hard = g["seg_hard"] + g["dups"] + g["extra"]
        tbl.add_row(str(g["group"]), " ".join(g["chapters"]) or f"{g['first_index']}–{g['last_index']}",
                    ProgressBar(total=max(g["src"], 1), completed=min(g["lines"], g["src"]), width=14),
                    f"{min(g['lines'], g['src'])}/{g['src']}" + (f" +{g['bad_lines']}?" if g["bad_lines"] else ""),
                    Text(f"{_ICON[st]} {st}", style=style[st]), _fmt_age(g["age_sec"]),
                    Text(str(hard), style="red" if hard else "dim"), Text(str(warn), style="yellow" if warn else "dim"),
                    str(g["newterms"]) if g["newterms"] else "")
    if not snap["groups"]:
        tbl.add_row("", Text("no parallel groups — serial mode", style="dim"), "", "", "", "", "", "", "")

    foot_parts = []
    rem = _remaining_lines(snap)
    if rate:
        foot_parts.append(f"{rate:.1f} seg/min")
        if rem and rate > 0:
            foot_parts.append(f"ETA ~{int(rem / rate)} min for {rem} in-flight segments")
    elif rem:
        foot_parts.append(f"{rem} in-flight segments remaining")
    stalled = [str(g["group"]) for g in snap["groups"] if g["state"] == "stalled"]
    if stalled:
        foot_parts.append(f"[bold red]stalled: grp {', '.join(stalled)} — silent > {snap.get('stall_sec', STALL_SEC)}s[/]")
    ready = [str(g["group"]) for g in snap["groups"] if g["state"] == "ready"]
    if ready:
        foot_parts.append(f"[bold cyan]ready to write: grp {', '.join(ready)}[/]")
    foot = Text.from_markup("   ".join(foot_parts)) if foot_parts else Text("")
    return Panel(RGroup(head, Text(""), tbl, Text(""), foot), title=f"[bold]{snap['project']}[/]",
                 subtitle=time.strftime("%H:%M:%S", time.localtime(snap["ts"])))


# ------------------------------------------------------------------ CLI ----
def main(argv=None):
    ap = argparse.ArgumentParser(description="Live translation progress (multi-agent aware)")
    ap.add_argument("cache", nargs="?", default="work/cache.json")
    ap.add_argument("--par", help="parallel groups dir (default <work>/par)")
    ap.add_argument("--stall", type=int, default=STALL_SEC, help="seconds of silence before a group counts as stalled")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="live panel, refresh every --interval seconds")
    mode.add_argument("--once", action="store_true", help="render the panel once")
    mode.add_argument("--line", action="store_true", help="one status-bar line (also written to ~/.ainiee-translate/progress.line)")
    mode.add_argument("--json", action="store_true", help="full snapshot as JSON")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)

    if a.watch:
        from rich.console import Console
        from rich.live import Live
        console = Console()
        prev = None
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            while True:
                snap = snapshot(a.cache, a.par, a.stall)
                rate = rate_per_min(prev, snap) if prev else None
                live.update(render(snap, rate))
                write_line_file(one_line(snap, rate))
                prev = {"ts": snap["ts"], "lines": _in_flight_lines(snap)}
                time.sleep(a.interval)
    snap = snapshot(a.cache, a.par, a.stall)
    prev = _load_state()
    rate = rate_per_min(prev, snap) if prev and prev.get("work") == snap["work"] else None
    _save_state(snap)
    if a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
    elif a.line:
        line = one_line(snap, rate)
        write_line_file(line)
        print(line)
    else:
        from rich.console import Console
        Console().print(render(snap, rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
