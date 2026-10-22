from ainiee_translate import scan


def test_inconsistent_flags_single_slip():
    # 'Hale' kept English in two segments, transliterated in a third -> highest-signal bucket.
    items = [
        {"text_index": 1, "source_text": "Hale waited.", "translated_text": "Hale 在等。", "translation_status": 1},
        {"text_index": 2, "source_text": "Then Hale spoke.", "translated_text": "然后 Hale 开口。", "translation_status": 2},
        {"text_index": 3, "source_text": "Hale left.", "translated_text": "黑尔离开了。", "translation_status": 1},
    ]
    out = scan.discover_proper_nouns(items, locked={"characters": [{"render": "Pell"}]})
    inc = {r["token"]: r for r in out["inconsistent"]}
    assert "Hale" in inc and inc["Hale"]["segments"] == [3] and inc["Hale"]["preserved"] == 2


def test_never_preserved_bucket_for_always_transliterated():
    items = [{"text_index": 5, "source_text": "When Tamsin arrived.",
              "translated_text": "塔姆辛到来时。", "translation_status": 2}]
    out = scan.discover_proper_nouns(items, locked=None)
    assert any(r["token"] == "Tamsin" for r in out["never_preserved"])
    assert out["inconsistent"] == []


def test_glossary_known_names_are_ignored():
    items = [{"text_index": 6, "source_text": "Pell nodded.", "translated_text": "萨姆点头。",
              "translation_status": 1}]
    out = scan.discover_proper_nouns(items, locked={"characters": [{"render": "Pell"}]})
    assert all(r["token"] != "Pell" for r in out["inconsistent"] + out["never_preserved"])


def test_possessives_are_skipped():
    items = [{"text_index": 7, "source_text": "Benedek's order.", "translated_text": "命令。",
              "translation_status": 1}]
    out = scan.discover_proper_nouns(items, locked=None)
    assert all("'" not in r["token"] and "’" not in r["token"]
               for r in out["inconsistent"] + out["never_preserved"])


def test_finds_merged_source_tokens_low_noise():
    items = [{"text_index": 4,
              "source_text": "She dropped thenaiskosfragment near speciesDraco; another one.",
              "translated_text": "她放下了它。", "translation_status": 1}]
    tokens = {r["token"] for r in scan.find_merged_tokens(items)}
    assert "thenaiskosfragment" in tokens  # long run
    assert "speciesDraco" in tokens        # camelCase transition
    assert "another" not in tokens         # ordinary word must NOT be flagged


def test_finds_untranslated_glossary_term_left_in_english():
    # Coastguard→海岸警卫队 applied in one segment, left as English in another.
    locked = {"terms": [{"src": "Coastguard", "dst": "海岸警卫队", "category": "org"},
                        {"src": "Highmark", "dst": "Highmark", "keep_source": True}]}
    items = [
        {"text_index": 1, "source_text": "loyal to Coastguard", "translated_text": "忠于海岸警卫队", "translation_status": 1},
        {"text_index": 2, "source_text": "loyal to Coastguard", "translated_text": "忠于的是 Coastguard", "translation_status": 2},
        {"text_index": 3, "source_text": "from Highmark", "translated_text": "来自 Highmark", "translation_status": 1},
    ]
    out = scan.find_untranslated_terms(items, locked)
    rows = {r["src"]: r for r in out}
    assert "Coastguard" in rows and rows["Coastguard"]["segments"] == [2]  # only the leaked one
    assert "Highmark" not in rows  # keep_source term must NOT be flagged


def test_finds_stray_latin_hallucinated_token():
    # "Lt" appears in the translation but nowhere in the source -> hallucinated insertion.
    items = [
        {"text_index": 1, "source_text": "the guard turned briskly",
         "translated_text": "Lt 迅速转身", "translation_status": 2},
        {"text_index": 2, "source_text": "Okafor reached for it",
         "translated_text": "Okafor 伸手去拿", "translation_status": 1},  # Okafor IS in source -> not stray
    ]
    out = scan.find_stray_latin(items, locked=None)
    tokens = {r["token"] for r in out}
    assert "Lt" in tokens
    assert "Okafor" not in tokens


def test_stray_latin_case_insensitive_and_glossary_aware():
    items = [
        # HUD vs hud: case difference must NOT be flagged
        {"text_index": 3, "source_text": "she held the hud", "translated_text": "她举着 HUD",
         "translation_status": 1},
        # glossary-known name absent from this segment's source is trusted (not flagged)
        {"text_index": 4, "source_text": "she nodded", "translated_text": "Mara 点头",
         "translation_status": 1},
    ]
    out = scan.find_stray_latin(items, locked={"characters": [{"render": "Mara"}]})
    tokens = {r["token"] for r in out}
    assert "HUD" not in tokens
    assert "Mara" not in tokens


def test_merges_skip_untranslated():
    items = [{"text_index": 5, "source_text": "thenaiskosfragment",
              "translated_text": "", "translation_status": 0}]
    assert scan.find_merged_tokens(items) == []
