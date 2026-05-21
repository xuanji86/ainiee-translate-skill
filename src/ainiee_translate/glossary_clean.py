"""Clean the raw seed into a locked working authority table:
- strip leading honorifics/titles to get canonical bare names
- merge name variants + apostrophe variants under one entry
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


def _strip_title(source: str) -> str:
    words = normalize_apostrophes(source).split()
    while words and (words[0].rstrip(".") in {h.rstrip(".") for h in _HONORIFICS}):
        words = words[1:]
    return " ".join(words)


def clean_characters(raw: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for c in raw:
        bare = _strip_title(c.get("source", ""))
        if not bare:
            continue
        key_token = bare.split()[-1]  # surname/last token groups variants
        g = groups.setdefault(key_token, {"forms": [], "gender": "", "note": ""})
        g["forms"].append(bare)
        g["gender"] = g["gender"] or c.get("gender", "")
        g["note"] = g["note"] or c.get("note", "")
    out = []
    for key, g in groups.items():
        forms = sorted(set(g["forms"]), key=len, reverse=True)  # longest = canonical
        canonical = forms[0]
        aliases = sorted(set(forms[1:] + [key]) - {canonical})
        out.append({"canonical": canonical, "render": canonical, "aliases": aliases,
                    "gender": g["gender"], "note": g["note"]})
    return out
