from ainiee_translate import audit


def test_hard_empty_and_tag_mismatch():
    assert audit.hard_checks("Hello there.", "") == ["empty"]
    assert audit.hard_checks("<i>Closer,</i> he said.", "更近了。他说。") == ["tag_mismatch"]
    assert audit.hard_checks("<i>Closer,</i> he said.", "<i>更近了。</i>他说。") == []
    assert audit.hard_checks("<i>Closer,</i> he said.", "更近了。他说。", allow_tag_mismatch=True) == []


def test_soft_cjk_checks_only_fire_for_cjk_targets():
    src = "The room fell silent, and Marlow studied the letter for a long time."
    assert "halfwidth_punct" in audit.soft_checks(src, "房间里一片寂静,Marlow 端详着那封信。")
    assert "cjk_corner_quote" in audit.soft_checks(src, "「安静」他说。")
    assert "inner_space" in audit.soft_checks(src, "房间 里一片寂静。")
    # latin target: none of the CJK style checks apply
    assert audit.soft_checks(src, "La salle devint silencieuse, et Marlow étudia la lettre.") == []


def test_soft_identical_and_markup_leak():
    src = "The quick brown fox jumps over the lazy dog again today."
    assert "identical_untranslated" in audit.soft_checks(src, src)
    assert "markup_leak" in audit.soft_checks("a <b>b</b>", "甲 <b>乙</b> <span>丙</span>")
    assert "markup_leak" not in audit.soft_checks("a <b>b</b>", "甲 <b>乙</b>")   # real marks are fine


def test_lint_pair_skips_soft_when_empty():
    hard, soft = audit.lint_pair("Some source text here.", "")
    assert hard == ["empty"] and soft == []


def test_audit_items_groups_by_category():
    items = [{"text_index": 1, "source_text": "Hello.", "translated_text": "", "translation_status": 1},
             {"text_index": 2, "source_text": "Hi, there.", "translated_text": "你好,那边。", "translation_status": 1},
             {"text_index": 3, "source_text": "skip", "translated_text": "", "translation_status": 0}]
    rep = audit.audit_items(items)
    assert rep["empty"]["segments"] == [1]
    assert rep["halfwidth_punct"]["segments"] == [2]
