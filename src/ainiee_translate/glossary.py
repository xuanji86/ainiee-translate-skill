"""Assemble the locked working table from a seed, and persist it."""
import argparse
import json
from . import glossary_seed, glossary_clean
from .helpers import normalize_apostrophes


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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build locked glossary")
    ap.add_argument("--config", required=True)
    ap.add_argument("--analysis", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    seed = glossary_seed.load_seed(a.config, a.analysis)
    write_locked(build_locked(seed), a.out)
    print(f"locked glossary -> {a.out}")


if __name__ == "__main__":
    main()
