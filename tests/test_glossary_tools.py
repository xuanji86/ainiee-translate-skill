import json
from ainiee_translate import glossary, glossary_clean

LOCKED = {
    "characters": [
        {"canonical": "Kathryn Hollis", "render": "Kathryn Hollis", "aliases": ["Hollis", "Admiral Hollis"]},
        {"canonical": "Aldous", "render": "Aldous", "aliases": ["Prior Aldous"]},
        {"canonical": "Benedek", "render": "Benedek", "aliases": ["Prior Benedek"]},
        {"canonical": "Archer", "render": "Archer", "aliases": ["Jonathan Archer"]},   # given name, NOT a title
        {"canonical": "Valeria Williams", "render": "Williams", "aliases": ["Valeria"]},
        {"canonical": "Marcus Williams", "render": "Williams", "aliases": ["Marcus"]},   # surname render shared: not a collision
        {"canonical": "Tom Ashby", "render": "Tom Ashby", "aliases": ["Ashby"]},
        {"canonical": "Owen Ashby", "render": "Owen Ashby", "aliases": ["Ashby"]},
    ],
    "terms": [
        {"src": "Coastguard", "dst": "海岸警卫队"},
        {"src": "HUD", "dst": "HUD", "keep_source": True},
        {"src": "coastguard", "dst": "星舰"},
        {"src": "Warp core", "dst": ""},
    ],
    "non_translate": [{"marker": "<i>"}],
}


def test_filter_keeps_only_what_the_group_mentions():
    texts = ["Hollis stepped onto the bridge.", "The HUD chimed."]
    out = glossary.filter_locked(LOCKED, texts)
    assert [c["canonical"] for c in out["characters"]] == ["Kathryn Hollis"]
    assert [t["src"] for t in out["terms"]] == ["HUD"]
    assert out["non_translate"] == LOCKED["non_translate"]
    assert out["_meta"]["kept"] == {"characters": 1, "terms": 1}
    assert out["_meta"]["total"]["characters"] == 8


def test_lint_flags_title_alias_collision_shared_surname_and_terms():
    kinds = [i["kind"] for i in glossary.lint_locked(LOCKED)]
    assert "alias_has_title" in kinds        # "Admiral Hollis"
    titled = {i["alias"] for i in glossary.lint_locked(LOCKED) if i["kind"] == "alias_has_title"}
    assert titled == {"Admiral Hollis", "Prior Aldous", "Prior Benedek"}   # "Prior" leads two people; "Jonathan" does not
    assert "alias_collides" in kinds         # "Ashby" claimed by two people
    assert not any(i["kind"] == "alias_collides" and i["alias"] == "Williams" for i in glossary.lint_locked(LOCKED))
    assert "shared_surname" in kinds
    assert "duplicate_term" in kinds         # Coastguard / coastguard
    assert "term_missing_dst" in kinds       # Warp core


def test_merge_newterms_adds_unknown_only():
    locked = json.loads(json.dumps(LOCKED))
    added, skipped = glossary.merge_newterms(locked, ["Vaelith", "hollis", "HUD", "", "# comment", "Corsair-class"])
    assert added == ["Vaelith", "Corsair-class"]
    assert skipped == ["hollis", "HUD"]
    new = {t["src"]: t for t in locked["terms"]}
    assert new["Vaelith"]["keep_source"] is True and new["Vaelith"]["dst"] == "Vaelith"


def test_clean_characters_does_not_merge_two_people_sharing_a_surname():
    raw = [{"source": "Owen Ashby"}, {"source": "Tom Ashby"}, {"source": "Admiral Ashby"},
           {"source": "Captain Hollis"}, {"source": "Kathryn Hollis"}]
    chars = {c["canonical"]: c for c in glossary_clean.clean_characters(raw)}
    assert set(chars) == {"Owen Ashby", "Tom Ashby", "Ashby", "Kathryn Hollis"}
    assert "ambiguous" in chars["Ashby"]["note"]
    assert "Ashby" not in chars["Owen Ashby"]["aliases"] and "Ashby" not in chars["Tom Ashby"]["aliases"]
    assert chars["Kathryn Hollis"]["aliases"] == ["Hollis"]


def test_glossary_cli_legacy_build_still_works(tmp_path):
    import os
    fix = os.path.join(os.path.dirname(__file__), "fixtures")
    out = tmp_path / "g.json"
    glossary.main(["--config", os.path.join(fix, "config.json"), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["terms"]


def test_glossary_cli_filter_and_lint(tmp_path, capsys):
    lk = tmp_path / "locked.json"; lk.write_text(json.dumps(LOCKED), encoding="utf-8")
    src = tmp_path / "grp_1_src.json"
    src.write_text(json.dumps([{"text_index": 1, "source_text": "Tom Ashby grinned at the HUD."}]), encoding="utf-8")
    out = tmp_path / "g1.json"
    glossary.main(["filter", "--locked", str(lk), "--for", str(src), "--out", str(out)])
    got = json.loads(out.read_text(encoding="utf-8"))
    # "Ashby" alias is shared, so both Paris entries come along — lint is what tells you to fix that
    assert {c["canonical"] for c in got["characters"]} == {"Tom Ashby", "Owen Ashby"}
    rc = glossary.main(["lint", "--locked", str(lk)])
    assert rc == 1
