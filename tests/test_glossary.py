import os
from ainiee_translate import glossary_seed

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def test_load_seed_merges_public_and_analysis():
    seed = glossary_seed.load_seed(
        config_path=os.path.join(FIX, "config.json"),
        analysis_cache_path=os.path.join(FIX, "analysis_cache.json"))
    srcs = {t["src"] for t in seed["terms"]}
    assert "Korin" in srcs and "Highmark" in srcs       # public + analysis terms
    assert len(seed["characters"]) == 4                     # raw, pre-clean (dups still present)
    assert any(c["source"].startswith("Praetor") for c in seed["characters"])


def test_load_seed_reads_exclusion_list_into_non_translate():
    # AiNiee profile exclusion_list_data (plural "markers") -> non_translate (singular "marker")
    seed = glossary_seed.load_seed(config_path=os.path.join(FIX, "profile.json"))
    markers = {n["marker"] for n in seed["non_translate"]}
    assert "Alpha Centauri III" in markers and "Duranium" in markers
    assert all("marker" in n for n in seed["non_translate"])   # normalized shape
    # profile is a config superset: prompt_dictionary_data still becomes terms
    assert {"Korin", "Highmark"} <= {t["src"] for t in seed["terms"]}


from ainiee_translate import glossary_clean

def test_clean_characters_dedups_titles_and_apostrophes():
    raw = [
        {"source": "Captain Marlow", "recommended_translation": "Marlow 舰长", "gender": "M", "note": "船长"},
        {"source": "James Marlow", "recommended_translation": "James Marlow", "gender": "M", "note": ""},
        {"source": "Praetor Da'ren", "recommended_translation": "Da'ren 法务官", "gender": "F", "note": ""},
        {"source": "Praetor Da'ren", "recommended_translation": "Da'ren", "gender": "F", "note": ""},
    ]
    chars = glossary_clean.clean_characters(raw)
    canon = {c["canonical"] for c in chars}
    assert "James Marlow" in canon            # Captain Marlow merged into the full name
    assert sum(1 for c in chars if "Da'ren" in c["canonical"]) == 1   # apostrophe dup merged
    marlow = next(c for c in chars if c["canonical"] == "James Marlow")
    assert "Marlow" in marlow["aliases"]
    assert marlow["render"] == "James Marlow"  # person -> keep English

import json as _json
from ainiee_translate import glossary

def test_build_locked_table_shape(tmp_path):
    seed = {"terms": [{"src": "Korin", "dst": "科林", "category": "race"}],
            "characters": [{"source": "Captain Marlow", "recommended_translation": "Marlow 舰长",
                            "gender": "M", "note": "船长"}],
            "non_translate": [{"marker": "<i>", "category": "tag", "note": ""}]}
    locked = glossary.build_locked(seed)
    assert locked["characters"][0]["render"] == "Marlow"
    assert locked["terms"][0]["dst"] == "科林"
    assert "title_rules" not in locked  # title handling lives in the user's own prompt, not the table
    out = tmp_path / "p.glossary.locked.json"
    glossary.write_locked(locked, str(out))
    assert _json.loads(out.read_text(encoding="utf-8"))["terms"][0]["src"] == "Korin"

def test_build_locked_marks_keep_source_terms():
    # keep_source is language-agnostic: dst == src (or empty) -> leave untranslated
    seed = {"terms": [{"src": "Highmark", "dst": "Highmark", "category": "place"},
                      {"src": "Korin", "dst": "科林", "category": "race"},
                      {"src": "Mont Blanc", "dst": "Mont Blanc", "category": "place"}],
            "characters": [], "non_translate": []}
    locked = glossary.build_locked(seed)
    by_src = {t["src"]: t for t in locked["terms"]}
    assert by_src["Highmark"].get("keep_source") is True
    assert by_src["Mont Blanc"].get("keep_source") is True   # any target language
    assert by_src["Korin"].get("keep_source") is not True    # has a real translation
