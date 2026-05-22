from ainiee_translate import scan


def test_inconsistent_flags_single_slip():
    # 'Keru' kept English in two segments, transliterated in a third -> highest-signal bucket.
    items = [
        {"text_index": 1, "source_text": "Keru waited.", "translated_text": "Keru 在等。", "translation_status": 1},
        {"text_index": 2, "source_text": "Then Keru spoke.", "translated_text": "然后 Keru 开口。", "translation_status": 2},
        {"text_index": 3, "source_text": "Keru left.", "translated_text": "克鲁离开了。", "translation_status": 1},
    ]
    out = scan.discover_proper_nouns(items, locked={"characters": [{"render": "Dax"}]})
    inc = {r["token"]: r for r in out["inconsistent"]}
    assert "Keru" in inc and inc["Keru"]["segments"] == [3] and inc["Keru"]["preserved"] == 2


def test_never_preserved_bucket_for_always_transliterated():
    items = [{"text_index": 5, "source_text": "When Tenmei arrived.",
              "translated_text": "天明到来时。", "translation_status": 2}]
    out = scan.discover_proper_nouns(items, locked=None)
    assert any(r["token"] == "Tenmei" for r in out["never_preserved"])
    assert out["inconsistent"] == []


def test_glossary_known_names_are_ignored():
    items = [{"text_index": 6, "source_text": "Dax nodded.", "translated_text": "萨姆点头。",
              "translation_status": 1}]
    out = scan.discover_proper_nouns(items, locked={"characters": [{"render": "Dax"}]})
    assert all(r["token"] != "Dax" for r in out["inconsistent"] + out["never_preserved"])


def test_possessives_are_skipped():
    items = [{"text_index": 7, "source_text": "Yevir's order.", "translated_text": "命令。",
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
    # Starfleet→星际舰队 applied in one segment, left as English in another.
    locked = {"terms": [{"src": "Starfleet", "dst": "星际舰队", "category": "org"},
                        {"src": "Highmark", "dst": "Highmark", "keep_source": True}]}
    items = [
        {"text_index": 1, "source_text": "loyal to Starfleet", "translated_text": "忠于星际舰队", "translation_status": 1},
        {"text_index": 2, "source_text": "loyal to Starfleet", "translated_text": "忠于的是 Starfleet", "translation_status": 2},
        {"text_index": 3, "source_text": "from Highmark", "translated_text": "来自 Highmark", "translation_status": 1},
    ]
    out = scan.find_untranslated_terms(items, locked)
    rows = {r["src"]: r for r in out}
    assert "Starfleet" in rows and rows["Starfleet"]["segments"] == [2]  # only the leaked one
    assert "Highmark" not in rows  # keep_source term must NOT be flagged


def test_finds_stray_latin_hallucinated_token():
    # "Lt" appears in the translation but nowhere in the source -> hallucinated insertion.
    items = [
        {"text_index": 1, "source_text": "the guard turned briskly",
         "translated_text": "Lt 迅速转身", "translation_status": 2},
        {"text_index": 2, "source_text": "Bashir reached for it",
         "translated_text": "Bashir 伸手去拿", "translation_status": 1},  # Bashir IS in source -> not stray
    ]
    out = scan.find_stray_latin(items, locked=None)
    tokens = {r["token"] for r in out}
    assert "Lt" in tokens
    assert "Bashir" not in tokens


def test_stray_latin_case_insensitive_and_glossary_aware():
    items = [
        # PADD vs padd: case difference must NOT be flagged
        {"text_index": 3, "source_text": "she held the padd", "translated_text": "她举着 PADD",
         "translation_status": 1},
        # glossary-known name absent from this segment's source is trusted (not flagged)
        {"text_index": 4, "source_text": "she nodded", "translated_text": "Kira 点头",
         "translation_status": 1},
    ]
    out = scan.find_stray_latin(items, locked={"characters": [{"render": "Kira"}]})
    tokens = {r["token"] for r in out}
    assert "PADD" not in tokens
    assert "Kira" not in tokens


def test_merges_skip_untranslated():
    items = [{"text_index": 5, "source_text": "thenaiskosfragment",
              "translated_text": "", "translation_status": 0}]
    assert scan.find_merged_tokens(items) == []
