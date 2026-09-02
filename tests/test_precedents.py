from ainiee_translate import precedents

ITEMS = [
    {"source_text": "Captain Kira looked at Vaughn.", "translated_text": "Kira 舰长看着 Vaughn。", "translation_status": 1},
    {"source_text": "Vaughn nodded; Kira sighed.", "translated_text": "Vaughn 点点头；Kira 叹了口气。", "translation_status": 1},
    {"source_text": "The Jem'Hadar fell silent.", "translated_text": "詹哈达沉默了。", "translation_status": 1},
    {"source_text": "Then Kira and Vaughn left for Harkoum.", "translated_text": "", "translation_status": 0},
]
LOCKED = {"characters": [{"canonical": "Kira", "render": "Kira", "aliases": []}],
          "terms": [{"src": "Harkoum", "dst": "Harkoum", "keep_source": True}]}


def test_precedents_reports_glossary_kept_and_translated_cases():
    md = precedents.build(ITEMS, ["Kira and Vaughn met a Jem'Hadar on Harkoum."], LOCKED)
    assert "| Kira (1) | 词汇表角色：**Kira**" in md
    assert "| Vaughn (1) | 已译 2 处全部保留原文" in md
    assert "全部译成目标语言" in md          # Jem'Hadar
    assert "Harkoum（保留原文）" in md
