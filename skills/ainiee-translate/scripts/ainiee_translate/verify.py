"""Residual rule checks over translated items (does not need AiNiee).
Checks: empty translation (omission) + verbatim-name preservation.
Language-agnostic: the name check fires for any glossary `render`/alias that
appears verbatim in the source but is missing from the translation (most
effective for Latin-script names; degrades gracefully for other scripts).

SCOPE / KNOWN LIMITS (read before trusting a clean run — see SKILL.md 步骤 7):
- verify is a *glossary enforcer*, not a discovery tool: it only checks names
  present in the locked glossary's `characters`. Names that were never added to
  the glossary (common for secondary characters / places, or when the glossary
  was seeded from a different book) are invisible to it. Use
  `python -m ainiee_translate.scan` to DISCOVER proper nouns missing from the
  glossary, and keep the glossary in sync with the book.
- It checks segments that have been translated OR polished (status 1 and 2).
  (Polished text is stored in `translated_text`, so both are covered.)
- The name check is per-segment membership: if a name appears correctly once in
  a segment AND is transliterated elsewhere in the *same* segment, verify sees
  the name present and stays silent. `scan` re-checks this per occurrence.
- It cannot tell a transliteration apart from an acceptable pronoun-drop or a
  legitimate translation; after expanding the glossary, expect some
  name_not_preserved hits on segments where the name was rightly rendered as a
  pronoun. Eyeball each.
- It does NOT detect: wrong-name substitutions for non-glossary names, OCR/parse
  "merged word" artifacts, or untranslated source fragments left in the target.
  `scan` covers the first two."""
from .helpers import latin_boundary_search

#: Statuses whose text is considered final/exportable and worth checking.
#: 1 = TRANSLATED, 2 = POLISHED (polished text overwrites translated_text).
CHECKED_STATUSES = (1, 2)


def check_items(items: list[dict], locked: dict) -> list[dict]:
    issues = []
    names = []
    for c in locked.get("characters", []):
        for n in [c.get("render", "")] + list(c.get("aliases") or []):
            if n:
                names.append(n)
    names = list(dict.fromkeys(names))  # de-dup, keep order
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
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
