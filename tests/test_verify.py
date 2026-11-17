from ainiee_translate import verify

def test_flags_omission_empty_translation():
    items = [{"text_index": 1, "source_text": "Hello", "translated_text": "", "translation_status": 1}]
    issues = verify.check_items(items, locked={"characters": []})
    assert any(i["kind"] == "empty_translation" and i["text_index"] == 1 for i in issues)

def test_flags_name_not_preserved_via_alias():
    # mirrors real glossary_clean output: render is the long canonical, prose uses the alias
    locked = {"characters": [{"canonical": "James Marlow", "render": "James Marlow",
                              "aliases": ["Marlow"]}]}
    items = [{"text_index": 2, "source_text": "Marlow nodded", "translated_text": "瑞克点头",
              "translation_status": 1}]
    issues = verify.check_items(items, locked=locked)
    assert any(i["kind"] == "name_not_preserved" and "Marlow" in i["detail"] for i in issues)

def test_clean_when_alias_preserved():
    locked = {"characters": [{"canonical": "James Marlow", "render": "James Marlow",
                              "aliases": ["Marlow"]}]}
    items = [{"text_index": 3, "source_text": "Marlow nodded", "translated_text": "Marlow 点头",
              "translation_status": 1}]
    assert verify.check_items(items, locked=locked) == []

def test_clean_when_name_preserved():
    locked = {"characters": [{"canonical": "Marlow", "render": "Marlow", "aliases": []}]}
    items = [{"text_index": 3, "source_text": "Marlow nodded", "translated_text": "Marlow 点头", "translation_status": 1}]
    assert verify.check_items(items, locked=locked) == []

def test_checks_polished_segments_too():
    # status 2 (POLISHED) must be checked, not skipped — polished text lives in translated_text
    locked = {"characters": [{"canonical": "Marlow", "render": "Marlow", "aliases": []}]}
    items = [{"text_index": 5, "source_text": "Marlow nodded", "translated_text": "瑞克点头",
              "translation_status": 2}]
    issues = verify.check_items(items, locked=locked)
    assert any(i["kind"] == "name_not_preserved" and i["text_index"] == 5 for i in issues)

def test_skips_untranslated_and_excluded():
    locked = {"characters": [{"canonical": "Marlow", "render": "Marlow", "aliases": []}]}
    items = [{"text_index": 6, "source_text": "Marlow nodded", "translated_text": "", "translation_status": 0},
             {"text_index": 7, "source_text": "Marlow nodded", "translated_text": "x", "translation_status": 7}]
    assert verify.check_items(items, locked=locked) == []


def _term_locked():
    return {"characters": [], "terms": [
        {"src": "airship", "dst": "飞艇"},
        {"src": "Arden of Vel", "dst": "维尔的阿登"},
        {"src": "Vel", "dst": "薇尔"},
        {"src": "Watchtower", "dst": "瞭望塔/望楼"},
        {"src": "Lieutenant", "dst": "上尉", "category": "rank"},
        {"src": "Highmark", "dst": "Highmark", "keep_source": True},
        {"src": "Corvanian", "dst": "科瓦尼人"},
        {"src": "lancers", "dst": "Lancers"},
    ]}


def _terms(src, tgt):
    items = [{"text_index": 1, "source_text": src, "translated_text": tgt, "translation_status": 1}]
    return [i["detail"] for i in verify.check_items(items, _term_locked()) if i["kind"] == "term_missing"]


def test_term_missing_flags_wrong_rendering():
    assert _terms("Two <i>Airships</i> rose.", "两艘飞船升起。") == ["airship -> 飞艇: term in source, rendering not in translation"]
    assert _terms("Two airships rose.", "两艘飞艇升起。") == []


def test_term_missing_longest_claims_and_alternatives():
    assert _terms("Arden of Vel arrived.", "维尔的阿登到了。") == []        # Vel 被长术语认领
    assert _terms("Arden of Vel left Vel.", "维尔的阿登离开了。") == ["Vel -> 薇尔: term in source, rendering not in translation"]
    assert _terms("The Watchtower stood.", "望楼矗立。") == []               # 备选译法
    assert _terms("The Lieutenant and Highmark.", "中尉与 Highmark。") == []  # 军衔、保留原文不查
    assert _terms("the airshipwright", "造船匠") == []                        # 词边界


def test_term_missing_accepts_modifier_stem():
    assert _terms("Three Corvanian cruisers.", "三艘科瓦尼巡洋舰。") == []   # 科瓦尼人 → 科瓦尼
    assert _terms("The lancers rode.", "Lancers 出发了。") == []              # 只差大小写 = 保留原文
