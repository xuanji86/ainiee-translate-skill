"""Write a polish pass back to the cache: overwrite translated_text with the
polished text and mark items POLISHED (status 2), mirroring AiNiee's
PolisherTask. Read the batch to polish with `batch read-translated`."""
import argparse
import json
from . import cache_io


def write_polished(cache_path: str, polished: list[dict]) -> int:
    return cache_io.apply_writeback(
        cache_path, polished, cache_io.set_polish,
        lambda p: p.get("polished_text", p.get("translated_text", "")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a polish pass back to the cache (status -> POLISHED)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="Apply polished text from a JSON file")
    w.add_argument("cache_path")
    w.add_argument("polished_json_path")
    a = ap.parse_args(argv)
    if a.cmd == "write":
        try:
            with open(a.polished_json_path, encoding="utf-8") as f:
                polished = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            ap.error(f"cannot read polished file: {e}")
        total = len(polished)
        applied = write_polished(a.cache_path, polished)
        if applied < total:
            print(f"polished {applied} of {total} item(s) ({total - applied} unmatched)")
        else:
            print(f"polished {applied} item(s)")


if __name__ == "__main__":
    main()
