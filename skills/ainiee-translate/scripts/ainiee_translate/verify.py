"""Residual rule checks over translated items (does not need AiNiee).
Checks: empty translation (omission) + verbatim-name preservation + term
rendering (`term_missing`: a glossary term with a `dst` occurs in the source,
but none of its renderings appears in the translation).
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
import re
import sys

from .helpers import latin_boundary_search, normalize_apostrophes

#: Statuses whose text is considered final/exportable and worth checking.
#: 1 = TRANSLATED, 2 = POLISHED (polished text overwrites translated_text).
CHECKED_STATUSES = (1, 2)

#: Leading words that are a title, not part of the name: "Lieutenant Haldane" is preserved
#: when "Haldane" is (the title is translated and moved behind it: "Haldane 上尉").
TITLES = {
    "lieutenant", "lt", "commander", "cmdr", "captain", "capt", "ensign", "doctor", "dr", "mr", "mrs", "ms",
    "miss", "admiral", "counselor", "counsellor", "chief", "elder", "hunter", "huntsmaster", "huntsmistress",
    "matriarch", "patriarch", "sir", "lady", "lord", "professor", "prof", "sergeant", "major", "colonel",
    "general", "crewman", "cadet", "nurse", "ambassador", "president", "senator", "praetor", "proconsul",
    "commodore", "subcommander", "centurion", "legate", "gul", "kai", "vedek", "father", "mother", "brother",
    "sister", "master", "mistress", "minister", "chancellor", "governor", "director", "agent", "specialist",
}
_TAGS = re.compile(r"</?[ib]>|⟦/?\d+⟧")
#: Term categories whose rendering legitimately varies by context (a rank depends on who holds it).
_VARYING = {"rank", "title", "role"}
#: "Will you…", "Will we…": a modal verb, not the name Will.
_AUX_NEXT = re.compile(r"\s+(?:you|we|i|they|he|she|it|your|our|this|that|there|the|a|an|not|anyone|someone|everyone)\b", re.I)


def _title_words(locked: dict) -> set[str]:
    extra = {normalize_apostrophes(t["src"]).lower().rstrip(".") for t in locked.get("terms", [])
             if t.get("src") and str(t.get("category", "")).lower() in ("rank", "title", "role")}
    return TITLES | {w for w in extra if " " not in w}


def core_name(name: str, titles: set[str]) -> str:
    """'Elder Maren' -> 'Maren'; 'Arden of Vel' -> 'Arden'; a bare name stays."""
    toks = name.split()
    while len(toks) > 1 and toks[0].lower().rstrip(".") in titles:
        toks = toks[1:]
    core = " ".join(toks)
    if " of " in core:
        core = core.split(" of ", 1)[0]
    return core


def name_in_source(name: str, src: str) -> bool:
    """Occurs as a name: a one-word name followed by a subject pronoun is the modal verb ('Will you')."""
    h = normalize_apostrophes(src)
    t = normalize_apostrophes(name)
    for m in re.finditer(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", h):
        if " " not in t and _AUX_NEXT.match(h, m.end()) and (m.start() == 0 or h[:m.start()].rstrip()[-1:] in ".!?\"“‘—(" ):
            continue
        return True
    return False


def check_items(items: list[dict], locked: dict) -> list[dict]:
    issues = []
    names = []
    for c in locked.get("characters", []):
        for n in [c.get("render", "")] + list(c.get("aliases") or []):
            if n:
                names.append(n)
    names = list(dict.fromkeys(names))  # de-dup, keep order
    titles = _title_words(locked)
    terms = _term_patterns(locked)
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
            continue
        src = _TAGS.sub("", it.get("source_text", "") or "")      # a drop cap "<b>O</b>ssa" is "Ossa"
        tgt = _TAGS.sub("", it.get("translated_text", "") or "")
        if src.strip() and not tgt.strip():
            issues.append({"kind": "empty_translation", "text_index": it["text_index"],
                           "detail": "source non-empty but translation empty"})
            continue
        for name in names:
            if not latin_boundary_search(name, src) or latin_boundary_search(name, tgt):
                continue
            core = core_name(name, titles)
            if core != name and latin_boundary_search(core, tgt):
                continue
            if not name_in_source(name, src):
                continue
            issues.append({"kind": "name_not_preserved", "text_index": it["text_index"],
                           "detail": f"{name} in source, not preserved in translation"})
        for miss in term_issues(src, tgt, terms):
            issues.append({"kind": "term_missing", "text_index": it["text_index"],
                           "detail": f"{miss}: term in source, rendering not in translation"})
    return issues


def _term_patterns(locked: dict) -> list[tuple[str, list[str], re.Pattern]]:
    """Glossary terms that must show up translated: (src, renderings, source pattern), longest
    first so a longer term claims its span before a shorter one inside it ("Arden of Vel" vs "Vel").
    `dst` may list alternatives as "a/b" or "a|b". Lower-case terms match any case and plural -s."""
    out = []
    for t in locked.get("terms", []):
        src, dst = (t.get("src") or "").strip(), (t.get("dst") or "").strip()
        if not src or not dst or t.get("keep_source") or str(t.get("category", "")).lower() in _VARYING:
            continue
        if normalize_apostrophes(src).lower() == normalize_apostrophes(dst).lower():
            continue
        body = re.escape(normalize_apostrophes(src))
        common = src == src.lower()
        pat = re.compile(rf"(?<![A-Za-z]){body}{'(?:e?s)?' if common else ''}(?![A-Za-z])",
                         re.IGNORECASE if common else 0)
        out.append((src, _renderings(dst), pat))
    out.sort(key=lambda x: -len(x[0]))
    return out


_CJK_END = re.compile(r"[\u3400-\u9fff]$")


def split_dst(dst: str) -> list[str]:
    """The alternatives of a `dst` written as "a/b" or "a|b"."""
    return [d for d in (x.strip() for x in re.split(r"[/|]", dst or "")) if d]


def _renderings(dst: str) -> list[str]:
    """Accepted forms of a `dst`: each "/"- or "|"-separated alternative, plus its stem when the
    term works as a modifier ("科瓦尼人" → "科瓦尼" in 科瓦尼巡洋舰, "升降机" → "升降" in 升降台)
    and the last word of a spaced rendering ("王国飞艇 翠鸟号" → "翠鸟号")."""
    out = []
    for d in split_dst(dst):
        out.append(d)
        if len(d) >= 3 and _CJK_END.search(d):
            out.append(d[:-1])
        if " " in d:
            out.append(d.split()[-1])
    return list(dict.fromkeys(out))


def term_issues(src: str, tgt: str, terms) -> list[str]:
    """Terms present in `src` (tags stripped) whose renderings are all absent from `tgt`."""
    h = normalize_apostrophes(src)
    claimed: list[tuple[int, int]] = []
    missing = []
    for term, renders, pat in terms:
        hit = False
        for m in pat.finditer(h):
            if any(a < m.end() and m.start() < b for a, b in claimed):
                continue
            claimed.append(m.span())
            hit = True
        if hit and not any(r in tgt for r in renders):
            missing.append(f"{term} -> {renders[0]}")
    return missing


def _items_for_check(cache_path: str) -> list[dict]:
    from . import cache_io
    proj = cache_io.load_cache(cache_path)
    return [{"text_index": it.text_index, "source_text": it.source_text,
             "translated_text": it.translated_text, "translation_status": it.translation_status}
            for it in cache_io.iter_items(proj)]


def _key(i: dict) -> tuple:
    return (i["kind"], int(i["text_index"]), i["detail"])


def main(argv=None):
    import argparse, json, os
    ap = argparse.ArgumentParser(description="Verify residual rule violations")
    ap.add_argument("cache")
    ap.add_argument("locked")
    ap.add_argument("--json", action="store_true", help="stdout = the issue list as pure JSON")
    ap.add_argument("--out", help="also write the full issue list here")
    ap.add_argument("--baseline", help="hide issues already listed in this JSON file (reviewed false positives)")
    ap.add_argument("--write-baseline", metavar="FILE", help="save the current issues as the baseline")
    a = ap.parse_args(argv)
    with open(a.locked, encoding="utf-8") as f:
        locked = json.load(f)
    issues = check_items(_items_for_check(a.cache), locked)
    if a.write_baseline:
        with open(a.write_baseline, "w", encoding="utf-8") as f:
            json.dump(issues, f, ensure_ascii=False, indent=1)
    hidden = 0
    if a.baseline and os.path.exists(a.baseline):
        with open(a.baseline, encoding="utf-8") as f:
            known = {_key(i) for i in json.load(f)}
        shown = [i for i in issues if _key(i) not in known]
        hidden = len(issues) - len(shown)
        issues = shown
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(issues, f, ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        for i in issues:
            print(f"{i['text_index']:6d}  {i['kind']}  {i['detail']}")
    sys.stderr.write(f"{len(issues)} issue(s)" + (f" ({hidden} known in baseline hidden)" if hidden else "") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
