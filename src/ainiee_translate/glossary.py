"""Locked glossary tooling.

  build          seed (AiNiee public table + optional analysis cache) -> locked table
  filter         subset of a locked table that actually occurs in given source files
                 (what a parallel subagent needs to read: ~10% of the table, not 66 KB)
  lint           structural problems that cause verify false positives / merged people
  merge-newterms fold the newterms_N.txt files parallel agents emit into the table
"""
import argparse
import json
import re
import sys

from . import glossary_seed, glossary_clean
from .glossary_clean import _HON_BARE
from .helpers import normalize_apostrophes, backup_file


# ---------------------------------------------------------------- build ----
def _annotate_terms(terms: list[dict]) -> list[dict]:
    """Mark a term `keep_source` (leave it untranslated) when its translation
    is absent or equals its source. Language-agnostic — works for any
    source/target pair, not just English→Chinese."""
    result = []
    for t in terms:
        t = dict(t)
        src = normalize_apostrophes(str(t.get("src", ""))).strip()
        dst = normalize_apostrophes(str(t.get("dst", ""))).strip()
        if not dst or dst == src:
            t["keep_source"] = True
        result.append(t)
    return result


def build_locked(seed: dict) -> dict:
    return {
        "characters": glossary_clean.clean_characters(seed.get("characters", [])),
        "terms": _annotate_terms(seed.get("terms", [])),
        "non_translate": seed.get("non_translate", []),
    }


def write_locked(locked: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(locked, f, ensure_ascii=False, indent=2)


def load_locked(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------- filter ----
def _present(term: str, corpus_lower: str) -> bool:
    t = normalize_apostrophes(term or "").lower().strip()
    return bool(t) and re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", corpus_lower) is not None


def filter_locked(locked: dict, texts: list[str]) -> dict:
    """Keep only characters/terms whose name (any alias) or `src` occurs in `texts`.
    non_translate markers are always kept. Adds a `_meta` block with the counts."""
    corpus = normalize_apostrophes("\n".join(texts)).lower()
    chars = [c for c in locked.get("characters", [])
             if any(_present(n, corpus)
                    for n in [c.get("canonical"), c.get("render")] + list(c.get("aliases") or []) if n)]
    terms = [t for t in locked.get("terms", []) if _present(t.get("src", ""), corpus)]
    return {
        "characters": chars,
        "terms": terms,
        "non_translate": locked.get("non_translate", []),
        "_meta": {"filtered": True,
                  "kept": {"characters": len(chars), "terms": len(terms)},
                  "total": {"characters": len(locked.get("characters", [])),
                            "terms": len(locked.get("terms", []))}},
    }


def _texts_from_files(paths: list[str]) -> list[str]:
    texts = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("items", []) if isinstance(data, dict) else data
        texts.extend((r.get("source_text") or "") for r in rows if isinstance(r, dict))
    return texts


# ----------------------------------------------------------------- lint ----
def lint_locked(locked: dict) -> list[dict]:
    issues = []
    chars = locked.get("characters", []) or []
    terms = locked.get("terms", []) or []
    owner: dict[str, str] = {}
    for c in chars:
        canon = c.get("canonical") or c.get("render") or ""
        if not (c.get("render") or "").strip():
            issues.append({"kind": "character_missing_render", "character": canon})
        for n in [c.get("canonical"), c.get("render")] + list(c.get("aliases") or []):
            if not n:
                continue
            toks = normalize_apostrophes(n).split()
            if toks and toks[0].rstrip(".") in _HON_BARE:
                issues.append({"kind": "alias_has_title", "character": canon, "alias": n,
                               "hint": "verify demands aliases verbatim; a title that gets translated "
                                       "makes this alias false-positive on every hit"})
            key = normalize_apostrophes(n).lower()
            if key in owner and owner[key] != canon:
                issues.append({"kind": "alias_collides", "alias": n, "characters": [owner[key], canon]})
            owner.setdefault(key, canon)
    by_last: dict[str, list[str]] = {}
    for c in chars:
        toks = normalize_apostrophes(c.get("canonical") or "").split()
        if len(toks) >= 2:
            by_last.setdefault(toks[-1].lower(), []).append(c["canonical"])
    for last, cs in by_last.items():
        if len(cs) > 1:
            issues.append({"kind": "shared_surname", "surname": last, "characters": cs,
                           "hint": "check no alias was merged across these people"})
    seen: dict[str, str] = {}
    for t in terms:
        src = normalize_apostrophes(t.get("src") or "").lower().strip()
        if not src:
            issues.append({"kind": "term_missing_src", "term": t})
            continue
        if src in seen:
            issues.append({"kind": "duplicate_term", "src": t.get("src"), "dst": [seen[src], t.get("dst")]})
        seen.setdefault(src, t.get("dst"))
        if not (t.get("dst") or "").strip() and not t.get("keep_source"):
            issues.append({"kind": "term_missing_dst", "src": t.get("src")})
    return issues


# ------------------------------------------------------- merge-newterms ----
def _known(locked: dict) -> set[str]:
    from .scan import _glossary_known
    return _glossary_known(locked)


def merge_newterms(locked: dict, names: list[str], category: str = "new") -> tuple[list[str], list[str]]:
    """Add each new name as a keep_source term unless already known (any
    character name/alias or term src, apostrophe- and case-insensitive)."""
    known = _known(locked)
    added, skipped = [], []
    for raw in names:
        n = raw.strip().strip(",;")
        if not n or n.startswith("#"):
            continue
        k = normalize_apostrophes(n).lower()
        if k in known:
            skipped.append(n)
            continue
        known.add(k)
        locked.setdefault("terms", []).append(
            {"src": n, "dst": n, "keep_source": True, "category": category,
             "note": "auto: kept verbatim by a parallel agent; review"})
        added.append(n)
    return added, skipped


# ------------------------------------------------------------------ CLI ----
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("-"):          # legacy: glossary --config … --out …
        argv = ["build"] + argv
    ap = argparse.ArgumentParser(description="Locked glossary: build / filter / lint / merge-newterms")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="seed -> locked table")
    b.add_argument("--config", required=True)
    b.add_argument("--analysis", default=None)
    b.add_argument("--out", required=True)

    f = sub.add_parser("filter", help="subset that occurs in the given grp_*_src.json files")
    f.add_argument("--locked", required=True)
    f.add_argument("--for", dest="sources", nargs="+", required=True, metavar="SRC_JSON")
    f.add_argument("--out", required=True)

    l = sub.add_parser("lint", help="structural problems in a locked table")
    l.add_argument("--locked", required=True)

    m = sub.add_parser("merge-newterms", help="fold newterms_*.txt into the table as keep_source terms")
    m.add_argument("--locked", required=True)
    m.add_argument("files", nargs="+")
    m.add_argument("--apply", action="store_true", help="write (default: preview)")
    m.add_argument("--category", default="new")

    a = ap.parse_args(argv)
    if a.cmd == "build":
        seed = glossary_seed.load_seed(a.config, a.analysis)
        write_locked(build_locked(seed), a.out)
        print(f"locked glossary -> {a.out}")
    elif a.cmd == "filter":
        out = filter_locked(load_locked(a.locked), _texts_from_files(a.sources))
        write_locked(out, a.out)
        k, t = out["_meta"]["kept"], out["_meta"]["total"]
        print(f"filtered glossary -> {a.out}: characters {k['characters']}/{t['characters']}, "
              f"terms {k['terms']}/{t['terms']}")
    elif a.cmd == "lint":
        issues = lint_locked(load_locked(a.locked))
        print(json.dumps(issues, ensure_ascii=False, indent=1))
        print(f"\n{len(issues)} issue(s)")
        return 1 if issues else 0
    elif a.cmd == "merge-newterms":
        locked = load_locked(a.locked)
        names = []
        for p in a.files:
            with open(p, encoding="utf-8") as fh:
                names.extend(fh.read().splitlines())
        added, skipped = merge_newterms(locked, names, a.category)
        print(f"new: {len(added)}  already known: {len(skipped)}")
        for n in added:
            print(f"  + {n}")
        if a.apply:
            backup_file(a.locked)
            write_locked(locked, a.locked)
            print(f"written -> {a.locked}")
        elif added:
            print("(preview; add --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
