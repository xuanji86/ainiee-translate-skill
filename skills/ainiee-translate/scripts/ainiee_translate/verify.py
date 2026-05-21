"""Residual rule checks over translated items (does not need AiNiee).
Checks: empty translation (omission) + verbatim-name preservation.
Language-agnostic: the name check fires for any glossary `render`/alias that
appears verbatim in the source but is missing from the translation (most
effective for Latin-script names; degrades gracefully for other scripts)."""
from .helpers import latin_boundary_search


def check_items(items: list[dict], locked: dict) -> list[dict]:
    issues = []
    names = []
    for c in locked.get("characters", []):
        for n in [c.get("render", "")] + list(c.get("aliases") or []):
            if n:
                names.append(n)
    names = list(dict.fromkeys(names))  # de-dup, keep order
    for it in items:
        if it.get("translation_status") != 1:
            continue
        src, tgt = it.get("source_text", ""), it.get("translated_text", "") or ""
        if src.strip() and not tgt.strip():
            issues.append({"kind": "empty_translation", "text_index": it["text_index"],
                           "detail": "source non-empty but translation empty"})
            continue
        for name in names:
            if latin_boundary_search(name, src) and not latin_boundary_search(name, tgt):
                issues.append({"kind": "name_not_preserved", "text_index": it["text_index"],
                               "detail": f"{name} in source, not preserved in translation"})
    return issues


def _items_for_check(cache_path: str) -> list[dict]:
    from . import cache_io
    proj = cache_io.load_cache(cache_path)
    return [{"text_index": it.text_index, "source_text": it.source_text,
             "translated_text": it.translated_text, "translation_status": it.translation_status}
            for it in cache_io.iter_items(proj)]


def main(argv=None):
    import argparse, json
    ap = argparse.ArgumentParser(description="Verify residual rule violations")
    ap.add_argument("cache")
    ap.add_argument("locked")
    a = ap.parse_args(argv)
    with open(a.locked, encoding="utf-8") as f:
        locked = json.load(f)
    issues = check_items(_items_for_check(a.cache), locked)
    print(json.dumps(issues, ensure_ascii=False, indent=2))
    print(f"\n{len(issues)} issue(s)")


if __name__ == "__main__":
    main()
