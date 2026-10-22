"""Discovery scans that complement `verify` (does not need AiNiee).

Where `verify` *enforces* the locked glossary, `scan` *discovers* what the
glossary is missing — the class of errors that slip past a clean verify run:

- `discover_proper_nouns`: proper nouns (Latin, capitalised, used mid-sentence)
  that appear in the source but are absent from the translation AND are not in
  the glossary. These are the names that were transliterated/dropped but were
  never locked, so verify never knew to check them. Glossary-independent: it
  finds candidates to ADD to the glossary. Output is ranked candidates for
  human review (it cannot tell a real omission from a term you chose to
  translate, e.g. Avalon→阿瓦隆), not hard errors.

- `find_untranslated_terms`: the inverse case — a glossary term that DOES have a
  target translation (e.g. Coastguard→海岸警卫队) but whose English source leaked
  verbatim into some segments untranslated.

- `find_stray_latin`: Latin tokens that appear in the translation but NOT in the
  segment's source — hallucinated insertions that replaced source content
  (e.g. a stray "Lt" written where the source said "the guard").

- `find_merged_tokens`: over-long / camelCase Latin runs in the source
  (e.g. "thenaiskosfragment", "speciesDraco") — lost-space artifacts from
  epub/PDF parsing that routinely leak verbatim into the translation.

Both scan segments with status 1 (TRANSLATED) or 2 (POLISHED), and the name
check is per-occurrence, so it also catches a name that is correct in one spot
of a segment but transliterated in another (which verify's per-segment
membership test misses).
"""
import re

from .helpers import latin_boundary_search, normalize_apostrophes

CHECKED_STATUSES = (1, 2)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]{2,}")

# Capitalised words that are not proper nouns (sentence openers, titles handled
# elsewhere). Kept deliberately small; the mid-sentence test does most of the work.
_STOP = set(
    """the a an and or but if then else when while where why how what who whom whose which that this these those
    he she it they we you i me him her them his hers its their our your my mine ours theirs
    is are was were be been being am do does did done have has had having will would shall should can could may might must
    not no nor yes so as at by for from in into of off on onto out over to up with within without
    about after again against all also although among another any around because before besides both
    despite down during each either enough even ever every few finally first instead just last like
    looking many maybe more moreover most much never next none nothing now once only other others perhaps
    please right same several since some something sometimes soon still such than thanks then there therefore
    though through thus too turning under until very well whatever whatever whenever wherever whether yet
    okay yeah oh ah hey sir madam mister doctor captain commander lieutenant ensign admiral general colonel major chief
    mr mrs ms dr st chapter part one two three four five six seven eight nine ten eleven twelve thirteen
    fourteen fifteen sixteen seventeen eighteen nineteen twenty""".split()
)
_CONTRACTION = re.compile(r"^I['’](?:m|ve|d|ll)$")


def _proper_noun_vocab(items):
    """Tokens that appear capitalised in a mid-sentence position somewhere in the
    corpus — a strong proper-noun signal (a sentence opener is ambiguous)."""
    vocab = set()
    for it in items:
        src = normalize_apostrophes(it.get("source_text") or "")
        for m in _WORD.finditer(src):
            w = m.group()
            if not w[0].isupper() or len(w) < 3:
                continue
            j = m.start() - 1
            if j >= 0 and src[j] == " ":
                j -= 1
            prev = src[j] if j >= 0 else ""
            if prev and (prev.islower() or prev in ",;:-"):
                vocab.add(w)
    return vocab


def _glossary_known(locked):
    known = set()
    if not locked:
        return known
    for c in locked.get("characters", []):
        for n in [c.get("canonical"), c.get("render")] + list(c.get("aliases") or []):
            if n:
                known.add(normalize_apostrophes(n).lower())
    for t in locked.get("terms", []):
        if t.get("src"):
            known.add(normalize_apostrophes(t["src"]).lower())
    return known


def discover_proper_nouns(items, locked=None):
    """Discover non-glossary proper nouns that may have been transliterated/dropped.

    Returns ``{"inconsistent": [...], "never_preserved": [...]}``:

    - ``inconsistent`` — preserved verbatim in the translation of some segments
      but missing in others (the highest-signal class: a name kept in English
      90% of the time but slipped in a few spots is almost always an error —
      this is the Rio Grande / single-slip pattern, and it also catches a name
      transliterated in one segment while correct in another). Act on these.
    - ``never_preserved`` — never kept verbatim anywhere; not in the glossary.
      Lower precision: this bucket also holds terms you legitimately translated
      (e.g. Avalon→阿瓦隆) alongside names transliterated everywhere
      (e.g. Tamsin→塔姆辛). Eyeball, then lock real names into the glossary.

    Per occurrence and across status 1 + 2.
    """
    vocab = _proper_noun_vocab(items)
    known = _glossary_known(locked)
    preserved, missing = {}, {}
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
            continue
        src = it.get("source_text") or ""
        tgt = it.get("translated_text") or ""
        if not tgt.strip():
            continue
        seen = set()
        for m in _WORD.finditer(normalize_apostrophes(src)):
            w = m.group()
            if w in seen or w not in vocab:
                continue
            seen.add(w)
            lw = w.lower()
            if lw in known or lw in _STOP or w.endswith("'s") or w.endswith("’s") or _CONTRACTION.match(w):
                continue
            if latin_boundary_search(w, tgt):
                preserved[w] = preserved.get(w, 0) + 1
            elif latin_boundary_search(w, src):
                missing.setdefault(w, []).append(it["text_index"])
    inconsistent, never = [], []
    for w, idx in missing.items():
        row = {"token": w, "preserved": preserved.get(w, 0), "missing": len(idx), "segments": idx}
        (inconsistent if preserved.get(w) else never).append(row)
    inconsistent.sort(key=lambda r: (-r["preserved"], -r["missing"], r["token"]))
    never.sort(key=lambda r: (-r["missing"], r["token"]))
    return {"inconsistent": inconsistent, "never_preserved": never}


def find_untranslated_terms(items, locked):
    """The inverse of name-preservation: a glossary term that HAS a target-language
    translation (`dst`, not `keep_source`) but whose English `src` was left
    verbatim in the translation of some segments (e.g. Coastguard→海岸警卫队 applied
    everywhere except a few spots where "Coastguard" leaked through untranslated).

    Returns [{src, dst, count, segments}], status 1 + 2, per occurrence.
    """
    terms = []
    for t in (locked or {}).get("terms", []):
        src, dst = t.get("src", ""), t.get("dst", "")
        if t.get("keep_source") or not src or not dst or normalize_apostrophes(src) == normalize_apostrophes(dst):
            continue
        if re.search(r"[A-Za-z]", src):  # only English-source terms can "leak" as English
            terms.append((src, dst))
    hits = {}
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
            continue
        tgt = it.get("translated_text") or ""
        if not tgt.strip():
            continue
        for src, dst in terms:
            if latin_boundary_search(src, tgt):
                hits.setdefault((src, dst), []).append(it["text_index"])
    out = [{"src": s, "dst": d, "count": len(idx), "segments": idx} for (s, d), idx in hits.items()]
    out.sort(key=lambda r: (-r["count"], r["src"]))
    return out


_LATIN_TOK = re.compile(r"[A-Za-z][A-Za-z'’]*")


def find_stray_latin(items, locked=None, min_len=2):
    """Latin tokens in the TRANSLATION that never occur as a real word ANYWHERE
    in the source — i.e. the model invented English with no basis in the text
    (e.g. the hallucinated "Lt" that replaced "the guard"/a possessive, or stray
    wrong-name fragments "Vic"/"Sef").

    Per segment, case-insensitive: a token is flagged when it is not a word in
    that segment's source. This is the only test that actually catches the
    target class — a wrong-name/garbage token written where the source has
    something else (``Vic``/``Sam``/``Sef`` in a passage about Okafor; ``Lt``
    for "the guard") — because such tokens collide with real source words under
    looser tests (``same`` ⊃ ``sam``), so substring/book-wide whitelists wrongly
    swallow them.

    It is therefore a **review list, not a pass/fail gate** (like
    ``discover.never_preserved``): expect benign entries too — parser lost-space
    artifacts where the word exists but glued (``theRio`` → Rio), and
    alien terms kept consistently in English. Eyeball; the real signal is short
    out-of-place names. Glossary-known names are trusted. Status 1 + 2.

    Returns [{token, count, segments}].
    """
    known = _glossary_known(locked)
    hits = {}
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
            continue
        tgt = it.get("translated_text") or ""
        if not tgt.strip():
            continue
        src_low = normalize_apostrophes(it.get("source_text") or "").lower()
        seen = set()
        for m in _LATIN_TOK.finditer(tgt):
            w = m.group()
            if len(w) < min_len or w in seen:
                continue
            seen.add(w)
            lw = normalize_apostrophes(w).lower()
            if lw not in known and not latin_boundary_search(lw, src_low):
                hits.setdefault(w, []).append(it["text_index"])
    out = [{"token": w, "count": len(idx), "segments": idx} for w, idx in hits.items()]
    out.sort(key=lambda r: (-r["count"], r["token"]))
    return out


def find_merged_tokens(items, min_len=14):
    """Lost-space parse artifacts in the source (e.g. "thenaiskosfragment",
    "speciesDraco"): an unusually long Latin run, or an internal lower→upper
    transition (camelCase) that real prose words don't have. Deliberately strict
    to stay low-noise; lower ``min_len`` to surface shorter merges."""
    camel = re.compile(r"[a-z][A-Z]")
    hits = {}
    for it in items:
        if it.get("translation_status") not in CHECKED_STATUSES:
            continue
        for m in re.finditer(r"[A-Za-z]{2,}", it.get("source_text") or ""):
            w = m.group()
            if len(w) >= min_len or camel.search(w):
                hits.setdefault(w, []).append(it["text_index"])
    out = [{"token": w, "count": len(idx), "segments": idx[:12]} for w, idx in hits.items()]
    out.sort(key=lambda r: (-r["count"], r["token"]))
    return out


_TAGS = re.compile(r"</?[ib]>")
_LOWER = re.compile(r"(?<![A-Za-z'’-])[a-z][a-z-]{4,}(?![A-Za-z'’])")


def find_pending_terms(items, locked=None, min_count=3):
    """Before translating the rest of a book: words that recur in the still-UNTRANSLATED source
    but never occur in the already-translated part and are not in the glossary — the new
    creatures/devices/titles the next chapters coin (lowercase ones too, e.g. "skimmers").
    Settle these in the glossary BEFORE splitting into parallel groups, or each group invents
    its own rendering. Returns [{token, count, segments}] ranked by count."""
    known = _glossary_known(locked)
    done, pend = set(), {}
    for it in items:
        src = normalize_apostrophes(it.get("source_text") or "")
        st = it.get("translation_status")
        toks = {m.group().lower() for m in _LOWER.finditer(src)} | \
               {m.group().lower() for m in _WORD.finditer(src) if m.group()[0].isupper()}
        if st in CHECKED_STATUSES:
            done |= toks
        elif st == 0:
            for t in toks:
                pend.setdefault(t, []).append(it["text_index"])
    merged: dict[str, list[int]] = {}
    for t, idx in pend.items():          # skimmer + skimmers -> one row
        base = t[:-1] if t.endswith("s") and t[:-1] in pend else t
        merged.setdefault(base, []).extend(idx)
    out = []
    for t, idx in merged.items():
        idx = sorted(set(idx))
        if len(idx) < min_count or {t, t + "s"} & (done | known | _STOP):
            continue
        # a coined term clusters where its creature/device appears; ordinary vocabulary is spread out
        spread = len({i // 50 for i in idx})
        out.append({"token": t, "count": len(idx), "burst": round(len(idx) / spread, 2), "segments": idx[:12]})
    out.sort(key=lambda r: (-(r["count"] * r["burst"]), r["token"]))
    return out


def _items(cache_path):
    from . import cache_io

    proj = cache_io.load_cache(cache_path)
    # markup is irrelevant here and splits words: a drop cap "<b>O</b>ssa" must read "Ossa"
    return [{"text_index": it.text_index, "source_text": _TAGS.sub("", it.source_text or ""),
             "translated_text": _TAGS.sub("", it.translated_text or ""), "translation_status": it.translation_status}
            for it in cache_io.iter_items(proj)]


def _brief(name, rows, n=15):
    lines = [f"## {name}: {len(rows)}"]
    for r in rows[:n]:
        key = r.get("token") or r.get("src")
        extra = f" -> {r['dst']}" if r.get("dst") else ""
        extra += f" (kept {r['preserved']}x)" if r.get("preserved") else ""
        lines.append(f"  {key}{extra}  x{r.get('count', r.get('missing'))}  {r['segments'][:8]}")
    if len(rows) > n:
        lines.append(f"  … {len(rows) - n} more")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Discover glossary gaps / parse artifacts (complements verify)")
    ap.add_argument("cache")
    ap.add_argument("--locked", help="locked glossary JSON (needed for --mode discover/terms/pending)")
    ap.add_argument("--mode", choices=["discover", "terms", "strays", "merges", "pending", "all"], default="all",
                    help="all = discover+terms+strays+merges; pending = new terms in the untranslated part")
    ap.add_argument("--min-merge-len", type=int, default=18)
    ap.add_argument("--min-count", type=int, default=3, help="pending: minimum occurrences")
    ap.add_argument("--json", action="store_true", help="stdout = full result as pure JSON")
    ap.add_argument("--out", help="also write the full result JSON here")
    ap.add_argument("--top", type=int, default=15, help="rows per section in the brief listing")
    a = ap.parse_args(argv)
    items = _items(a.cache)
    locked = None
    if a.locked:
        with open(a.locked, encoding="utf-8") as f:
            locked = json.load(f)
    result = {}
    if a.mode in ("discover", "all"):
        result["discover"] = discover_proper_nouns(items, locked)
    if a.mode in ("terms", "all"):
        result["untranslated_terms"] = find_untranslated_terms(items, locked)
    if a.mode in ("strays", "all"):
        result["stray_latin"] = find_stray_latin(items, locked)
    if a.mode in ("merges", "all"):
        result["merges"] = find_merged_tokens(items, a.min_merge_len)
    if a.mode == "pending":
        result["pending_terms"] = find_pending_terms(items, locked, a.min_count)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    flat = {}
    for k, v in result.items():
        if isinstance(v, dict):
            flat.update({f"{k}.{kk}": vv for kk, vv in v.items()})
        else:
            flat[k] = v
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_brief(k, v, a.top) for k, v in flat.items()))
    sys.stderr.write("; ".join(f"{k}: {len(v)}" for k, v in flat.items()) + "\n")


if __name__ == "__main__":
    main()
