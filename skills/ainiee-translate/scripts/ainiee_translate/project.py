"""Import a previous project's cache into a work/ dir so the pipeline can
continue it — translate the remainder, polish, verify, or re-export.

The main source is an AiNiee project cache (`AinieeCacheData.json` under
~/Library/Application Support/AiNiee/ProjectCache/<id>/), but any CacheProject
JSON works (including another ainiee-translate project's cache.json), since
both share AiNiee's CacheProject format. Import = load + normalize + place at
<work>/work/cache.json. The cache carries its own `input_path`, so export can
re-find the source book.
"""
import argparse
import json
import os
from collections import Counter

from . import cache_io, helpers


def ainiee_cache_dir() -> str:
    return os.environ.get("AINIEE_CACHE_DIR") or os.path.expanduser(
        "~/Library/Application Support/AiNiee/ProjectCache")


def _counts(project) -> dict:
    S = cache_io._m().TranslationStatus
    label = {S.UNTRANSLATED: "untranslated", S.TRANSLATED: "translated",
             S.POLISHED: "polished", getattr(S, "EXCLUDED", 7): "excluded"}
    return dict(Counter(label.get(it.translation_status, "other")
                        for it in cache_io.iter_items(project)))


def _summary(project, cache_path: str) -> dict:
    c = _counts(project)
    return {"project_name": getattr(project, "project_name", "") or "",
            "input_path": getattr(project, "input_path", "") or "",
            "cache": cache_path,
            "total": sum(c.values()),
            "untranslated": c.get("untranslated", 0),
            "translated": c.get("translated", 0),
            "polished": c.get("polished", 0),
            "excluded": c.get("excluded", 0)}


def import_cache(cache_path: str, work: str) -> dict:
    project = cache_io.load_cache(cache_path)
    wdir = os.path.join(work, "work")
    os.makedirs(wdir, exist_ok=True)
    dst = os.path.join(wdir, "cache.json")
    if os.path.exists(dst):
        helpers.backup_file(dst)
    cache_io.save_cache(project, dst)
    s = _summary(project, dst)
    s["source"] = cache_path
    return s


def list_ainiee(cache_dir: str | None = None) -> list[dict]:
    """Scan AiNiee's ProjectCache for importable projects."""
    root = cache_dir or ainiee_cache_dir()
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            f = os.path.join(root, name, "AinieeCacheData.json")
            if not os.path.isfile(f):
                continue
            try:
                s = _summary(cache_io.load_cache(f), f)
            except Exception as e:
                s = {"cache": f, "error": str(e)}
            s["project_id"] = name
            out.append(s)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Import a previous project (AiNiee cache or our cache.json) into a work dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("list", help="List importable AiNiee projects (ProjectCache)")
    lp.add_argument("--ainiee-cache-dir", default=None)
    ip = sub.add_parser("import", help="Import a cache into <work>/work/cache.json")
    src = ip.add_mutually_exclusive_group(required=True)
    src.add_argument("--cache", help="path to a cache JSON (AiNiee AinieeCacheData.json or our cache.json)")
    src.add_argument("--ainiee", metavar="PROJECT_ID", help="import AiNiee project by its ProjectCache id")
    ip.add_argument("--work", required=True)
    ip.add_argument("--ainiee-cache-dir", default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            print(json.dumps(list_ainiee(a.ainiee_cache_dir), ensure_ascii=False, indent=2))
        elif a.cmd == "import":
            cache = a.cache or os.path.join(
                a.ainiee_cache_dir or ainiee_cache_dir(), a.ainiee, "AinieeCacheData.json")
            print(json.dumps(import_cache(cache, a.work), ensure_ascii=False, indent=2))
    except (FileNotFoundError, OSError) as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()
