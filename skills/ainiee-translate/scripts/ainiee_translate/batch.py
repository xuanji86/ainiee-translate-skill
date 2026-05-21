"""Hand untranslated source segments to the agent, and write its translations back.
The agent fills `translated_text` between read_batch() and write_back()."""
import argparse
import json
from . import cache_io


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


def write_back(cache_path: str, translations: list[dict]) -> int:
    return cache_io.apply_writeback(cache_path, translations,
                                    cache_io.set_translation,
                                    lambda t: t["translated_text"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Batch read/write for the translation loop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read", help="Print next untranslated batch as JSON")
    r.add_argument("cache_path")
    r.add_argument("--size", type=int, default=100)

    rt = sub.add_parser("read-translated", help="Print next translated batch (for polish) as JSON")
    rt.add_argument("cache_path")
    rt.add_argument("--size", type=int, default=100)

    w = sub.add_parser("write", help="Write translations back from a JSON file")
    w.add_argument("cache_path")
    w.add_argument("translations_json_path")

    a = ap.parse_args(argv)
    if a.cmd == "read":
        project = cache_io.load_cache(a.cache_path)
        batch = read_batch(project, size=a.size)
        print(json.dumps(batch, ensure_ascii=False))
    elif a.cmd == "read-translated":
        project = cache_io.load_cache(a.cache_path)
        batch = read_translated_batch(project, size=a.size)
        print(json.dumps(batch, ensure_ascii=False))
    elif a.cmd == "write":
        try:
            with open(a.translations_json_path, encoding="utf-8") as f:
                translations = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            ap.error(f"cannot read translations file: {e}")
        total = len(translations)
        applied = write_back(a.cache_path, translations)
        if applied < total:
            print(f"applied {applied} of {total} translation(s) ({total - applied} unmatched)")
        else:
            print(f"applied {applied} translation(s)")


if __name__ == "__main__":
    main()
