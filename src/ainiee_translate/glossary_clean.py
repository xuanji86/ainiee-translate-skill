"""Clean the raw seed into a locked working authority table:
- strip leading honorifics/titles to get canonical bare names
- merge name variants + apostrophe variants under one entry — but only when a
  short form (e.g. "Paris") points at exactly ONE longer form; if two people
  share the surname (Owen Paris / Tom Paris) the bare surname becomes its own
  entry flagged ambiguous instead of being silently merged into one of them
- persons keep their `render` (English by default; how a name is actually
  translated is the user's call, via the glossary or their own prompt)."""
from .helpers import normalize_apostrophes

# Leading honorifics/titles stripped purely to dedup name variants
# ("Captain Marlow" / "Marlow" -> one entry). This is name-normalization,
# not a translation rule — title handling lives in the user's own prompt.
_HONORIFICS = {"Dr.", "Dr", "Mr.", "Mr", "Mrs.", "Ms.", "Miss", "Sir", "Lady",
               "Captain", "Commander", "Lieutenant", "Major", "Colonel", "General",
               "Admiral", "Ensign", "Sergeant", "Governor", "President", "Senator",
               "Ambassador", "Minister", "Chancellor", "Councillor", "Archpriest",
               "Bishop", "Reverend", "Father", "Abbot"}
_HON_BARE = {h.rstrip(".") for h in _HONORIFICS}


def _strip_title(source: str) -> str:
    words = normalize_apostrophes(source).split()
    while words and words[0].rstrip(".") in _HON_BARE:
        words = words[1:]
    return " ".join(words)


def _is_suffix(short: str, long_: str) -> bool:
    st, lt = short.split(), long_.split()
    return 0 < len(st) < len(lt) and lt[-len(st):] == st


def clean_characters(raw: list[dict]) -> list[dict]:
    forms: dict[str, dict] = {}           # bare form -> {gender, note, order}
    for i, c in enumerate(raw):
        bare = _strip_title(c.get("source", ""))
        if not bare:
            continue
        g = forms.setdefault(bare, {"gender": "", "note": "", "order": i})
        g["gender"] = g["gender"] or c.get("gender", "")
        g["note"] = g["note"] or c.get("note", "")

    # Resolve each form to a canonical, longest forms first.
    canonicals: list[str] = []
    canonical_of: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    for n in sorted(forms, key=lambda s: (-len(s.split()), -len(s), s)):
        parents = [c for c in canonicals if _is_suffix(n, c)]
        if len(parents) == 1:
            canonical_of[n] = parents[0]
        else:
            canonicals.append(n)
            canonical_of[n] = n
            if len(parents) > 1:
                ambiguous[n] = parents

    out = []
    for c in sorted(canonicals, key=lambda s: forms[s]["order"]):
        aliases = {a for a, p in canonical_of.items() if p == c and a != c}
        toks = c.split()
        # Surname alias, only when no other character claims that surname.
        if len(toks) > 1 and toks[-1] not in canonical_of:
            aliases.add(toks[-1])
        members = [c] + sorted(aliases & set(forms))
        gender = next((forms[m]["gender"] for m in members if forms[m]["gender"]), "")
        note = next((forms[m]["note"] for m in members if forms[m]["note"]), "")
        if c in ambiguous:
            note = (note + " " if note else "") + f"[ambiguous: shared by {', '.join(ambiguous[c])}]"
        out.append({"canonical": c, "render": c, "aliases": sorted(aliases),
                    "gender": gender, "note": note})
    return out
