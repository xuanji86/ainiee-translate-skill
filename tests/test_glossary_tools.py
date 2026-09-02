import json
from ainiee_translate import glossary, glossary_clean

LOCKED = {
    "characters": [
        {"canonical": "Kathryn Janeway", "render": "Kathryn Janeway", "aliases": ["Janeway", "Admiral Janeway"]},
        {"canonical": "Capril", "render": "Capril", "aliases": ["Vedek Capril"]},
        {"canonical": "Yevir", "render": "Yevir", "aliases": ["Vedek Yevir"]},
        {"canonical": "Archer", "render": "Archer", "aliases": ["Jonathan Archer"]},   # given name, NOT a title
        {"canonical": "Tom Paris", "render": "Tom Paris", "aliases": ["Paris"]},
        {"canonical": "Owen Paris", "render": "Owen Paris", "aliases": ["Paris"]},
    ],
    "terms": [
        {"src": "Starfleet", "dst": "星际舰队"},
        {"src": "PADD", "dst": "PADD", "keep_source": True},
        {"src": "starfleet", "dst": "星舰"},
        {"src": "Warp core", "dst": ""},
    ],
    "non_translate": [{"marker": "<i>"}],
}


def test_filter_keeps_only_what_the_group_mentions():
    texts = ["Janeway stepped onto the bridge.", "The PADD chimed."]
    out = glossary.filter_locked(LOCKED, texts)
    assert [c["canonical"] for c in out["characters"]] == ["Kathryn Janeway"]
    assert [t["src"] for t in out["terms"]] == ["PADD"]
    assert out["non_translate"] == LOCKED["non_translate"]
    assert out["_meta"]["kept"] == {"characters": 1, "terms": 1}
    assert out["_meta"]["total"]["characters"] == 6


def test_lint_flags_title_alias_collision_shared_surname_and_terms():
    kinds = [i["kind"] for i in glossary.lint_locked(LOCKED)]
    assert "alias_has_title" in kinds        # "Admiral Janeway"
    titled = {i["alias"] for i in glossary.lint_locked(LOCKED) if i["kind"] == "alias_has_title"}
    assert titled == {"Admiral Janeway", "Vedek Capril", "Vedek Yevir"}   # "Vedek" leads two people; "Jonathan" does not
    assert "alias_collides" in kinds         # "Paris" claimed by two people
    assert "shared_surname" in kinds
    assert "duplicate_term" in kinds         # Starfleet / starfleet
    assert "term_missing_dst" in kinds       # Warp core


def test_merge_newterms_adds_unknown_only():
    locked = json.loads(json.dumps(LOCKED))
    added, skipped = glossary.merge_newterms(locked, ["Caeliar", "janeway", "PADD", "", "# comment", "Vesta-class"])
    assert added == ["Caeliar", "Vesta-class"]
    assert skipped == ["janeway", "PADD"]
    new = {t["src"]: t for t in locked["terms"]}
    assert new["Caeliar"]["keep_source"] is True and new["Caeliar"]["dst"] == "Caeliar"


def test_clean_characters_does_not_merge_two_people_sharing_a_surname():
    raw = [{"source": "Owen Paris"}, {"source": "Tom Paris"}, {"source": "Admiral Paris"},
           {"source": "Captain Janeway"}, {"source": "Kathryn Janeway"}]
    chars = {c["canonical"]: c for c in glossary_clean.clean_characters(raw)}
    assert set(chars) == {"Owen Paris", "Tom Paris", "Paris", "Kathryn Janeway"}
    assert "ambiguous" in chars["Paris"]["note"]
    assert "Paris" not in chars["Owen Paris"]["aliases"] and "Paris" not in chars["Tom Paris"]["aliases"]
    assert chars["Kathryn Janeway"]["aliases"] == ["Janeway"]


def test_glossary_cli_legacy_build_still_works(tmp_path):
    import os
    fix = os.path.join(os.path.dirname(__file__), "fixtures")
    out = tmp_path / "g.json"
    glossary.main(["--config", os.path.join(fix, "config.json"), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["terms"]


def test_glossary_cli_filter_and_lint(tmp_path, capsys):
    lk = tmp_path / "locked.json"; lk.write_text(json.dumps(LOCKED), encoding="utf-8")
    src = tmp_path / "grp_1_src.json"
    src.write_text(json.dumps([{"text_index": 1, "source_text": "Tom Paris grinned at the PADD."}]), encoding="utf-8")
    out = tmp_path / "g1.json"
    glossary.main(["filter", "--locked", str(lk), "--for", str(src), "--out", str(out)])
    got = json.loads(out.read_text(encoding="utf-8"))
    # "Paris" alias is shared, so both Paris entries come along — lint is what tells you to fix that
    assert {c["canonical"] for c in got["characters"]} == {"Tom Paris", "Owen Paris"}
    rc = glossary.main(["lint", "--locked", str(lk)])
    assert rc == 1
