"""Write a polish pass back to the cache: overwrite translated_text with the
polished text and mark items POLISHED (status 2), mirroring AiNiee's
PolisherTask. Read the batch to polish with `batch read-translated`.
Same gate/lock/backup/atomic-save path as `batch write`; accepts many files."""
import argparse
import json
from . import cache_io, batch
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus


def write_polished(cache_path: str, polished: list[dict], *, force: bool = False,
                   allow_tag_mismatch: bool = False) -> cache_io.WriteResult:
    return cache_io.apply_writeback(
        cache_path, polished, TranslationStatus.POLISHED,
        lambda p: p.get("polished_text", p.get("translated_text", "")),
        check=batch.make_check(allow_tag_mismatch), force=force)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a polish pass back to the cache (status -> POLISHED)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="Apply polished text from one or more JSON/JSONL files")
    w.add_argument("cache_path")
    w.add_argument("polished", nargs="+", metavar="POLISHED_JSON")
    w.add_argument("--force", action="store_true")
    w.add_argument("--allow-tag-mismatch", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "write":
        try:
            rows = batch.load_many(a.polished)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            ap.error(f"cannot read polished file: {e}")
        dups = batch.duplicates(rows)
        if dups and not a.force:
            ap.error(f"duplicate text_index across inputs: {dups[:20]} (use --force)")
        res = write_polished(a.cache_path, rows, force=a.force, allow_tag_mismatch=a.allow_tag_mismatch)
        batch.report_write(res, verb="polished")
        return 1 if res.rejected else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
