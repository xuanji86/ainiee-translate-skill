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
