from ainiee_translate import precedents

ITEMS = [
    {"source_text": "Captain Mara looked at Corin.", "translated_text": "Mara 舰长看着 Corin。", "translation_status": 1},
    {"source_text": "Corin nodded; Mara sighed.", "translated_text": "Corin 点点头；Mara 叹了口气。", "translation_status": 1},
    {"source_text": "The Vor'tash fell silent.", "translated_text": "沃塔什沉默了。", "translation_status": 1},
    {"source_text": "Then Mara and Corin left for Halden.", "translated_text": "", "translation_status": 0},
]
LOCKED = {"characters": [{"canonical": "Mara", "render": "Mara", "aliases": []}],
          "terms": [{"src": "Halden", "dst": "Halden", "keep_source": True}]}


def test_precedents_reports_glossary_kept_and_translated_cases():
    md = precedents.build(ITEMS, ["Mara and Corin met a Vor'tash on Halden."], LOCKED)
    assert "| Mara (1) | 词汇表角色：**Mara**" in md
    assert "| Corin (1) | 已译 2 处全部保留原文" in md
    assert "全部译成目标语言" in md          # Vor'tash
    assert "Halden（保留原文）" in md
