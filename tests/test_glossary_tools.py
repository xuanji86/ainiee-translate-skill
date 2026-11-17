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


def test_filter_keeps_a_term_the_group_only_uses_in_the_plural():
    locked = {"characters": [{"canonical": "Hale", "render": "Hale", "aliases": []}],
              "terms": [{"src": "skimmer", "dst": "掠空兽"}, {"src": "airlock", "dst": "气闸"},
                        {"src": "ash", "dst": "灰"}, {"src": "Korin", "dst": "科林人"}]}
    out = glossary.filter_locked(locked, ["Two Skimmers circled the airlocks.", "Hales and Korins? Ashes fell."])
    assert [t["src"] for t in out["terms"]] == ["skimmer", "airlock", "ash"]   # -s / -es, any case
    assert out["characters"] == []                                             # names and capitalised terms: exact form only
    # the same word forms verify checks, so what filter drops verify does not demand
    from ainiee_translate import verify
    items = [{"text_index": 1, "translation_status": 1, "source_text": "Two Skimmers circled the airlocks.",
              "translated_text": "两只飞兽绕着舱门盘旋。"}]
    assert {i["detail"].split(":")[0] for i in verify.check_items(items, locked)} == {"skimmer -> 掠空兽", "airlock -> 气闸"}


def test_merge_newterms_conflicts_with_the_table_case_variants_and_arrow(tmp_path, capsys):
    assert glossary.parse_newterm("Highmark -> 高标镇") == ("Highmark", "高标镇")
    assert glossary.parse_newterm("Highmark → 高标镇") == ("Highmark", "高标镇")
    locked = {"characters": [{"canonical": "Hale", "render": "Hale", "aliases": []}],
              "terms": [{"src": "airship", "dst": "飞艇/飞船"}, {"src": "HUD", "dst": "HUD", "keep_source": True}]}
    per_file = {"n1": [("Airship", "飞船"), ("Hale", "黑尔"), ("airship", "气艇"), ("hud", "抬头显示")],
                "n2": [("kestrel", "kestrel"), ("Marlow", "Marlow")],
                "n3": [("Kestrel", "Kestrel"), ("marlow", "马洛")]}
    c = glossary.newterm_conflicts(per_file, locked)
    assert c == {"hale": {"黑尔": ["n1"], "Hale": ["table"]},                       # the table keeps the name
                 "airship": {"飞船": ["n1"], "气艇": ["n1"], "飞艇": ["table"]},      # 飞船 is a table alternative, 气艇 is not
                 "hud": {"抬头显示": ["n1"], "HUD": ["table"]},
                 "marlow": {"Marlow": ["n2"], "马洛": ["n3"]}}                       # two groups disagree
    # kestrel / Kestrel, both kept verbatim, are one choice: no conflict, merged once
    lk = tmp_path / "locked.json"; lk.write_text(json.dumps(locked), encoding="utf-8")
    files = []
    for name, pairs in per_file.items():
        p = tmp_path / f"newterms_{name}.txt"
        p.write_text("\n".join(f"{s} -> {d}" for s, d in pairs) + "\n", encoding="utf-8")
        files.append(str(p))
    glossary.main(["merge-newterms", "--locked", str(lk), *files, "--apply"])
    out = capsys.readouterr().out
    assert "CONFLICT airship" in out and "(table)" in out and "conflicts (not merged): 4" in out
    terms = {t["src"]: t for t in json.loads(lk.read_text(encoding="utf-8"))["terms"]}
    assert set(terms) == {"airship", "HUD", "kestrel"} and terms["kestrel"]["keep_source"]


def test_title_only_seeds_are_dropped_and_listed_shared_surname_gets_no_alias(tmp_path, capsys):
    raw = [{"source": "Captain"}, {"source": "Father"}, {"source": "Dr."}, {"source": "Father Korin"},
           {"source": "Owen Ashby"}, {"source": "Tom Ashby"}, {"source": "Kathryn Hollis"}]
    chars = {c["canonical"]: c for c in glossary_clean.clean_characters(raw)}
    assert set(chars) == {"Korin", "Owen Ashby", "Tom Ashby", "Kathryn Hollis"}      # a bare title is not a person
    assert glossary_clean.title_only(raw) == ["Captain", "Father", "Dr."]
    assert chars["Owen Ashby"]["aliases"] == [] and chars["Tom Ashby"]["aliases"] == []   # neither owns "Ashby"
    assert chars["Kathryn Hollis"]["aliases"] == ["Hollis"]
    assert "alias_collides" not in {i["kind"] for i in glossary.lint_locked({"characters": list(chars.values()), "terms": []})}
    # `glossary build` says what it dropped instead of losing it silently
    cfg = tmp_path / "config.json"; cfg.write_text("{}", encoding="utf-8")
    ana = tmp_path / "analysis.json"
    ana.write_text(json.dumps({"extra": {"analysis_v1": {"characters": raw}}}), encoding="utf-8")
    out = tmp_path / "g.json"
    glossary.main(["build", "--config", str(cfg), "--analysis", str(ana), "--out", str(out)])
    err = capsys.readouterr().err
    assert "Captain, Father, Dr." in err and "by hand" in err
    assert [c["canonical"] for c in json.loads(out.read_text(encoding="utf-8"))["characters"]] == [
        "Korin", "Owen Ashby", "Tom Ashby", "Kathryn Hollis"]
    glossary.main(["build", "--config", str(cfg), "--out", str(out)])                # nothing dropped: no notice
    assert capsys.readouterr().err == ""


def test_lint_still_flags_a_lone_title_word_alias():
    locked = {"characters": [{"canonical": "James Marlow", "render": "James Marlow", "aliases": ["Captain", "Marlow"]}],
              "terms": []}
    hits = [i["alias"] for i in glossary.lint_locked(locked) if i["kind"] == "alias_has_title"]
    assert hits == ["Captain"]


def test_newterm_tab_wins_over_an_arrow_inside_the_term():
    assert glossary.parse_newterm("Type->B rifle\tB 型步枪") == ("Type->B rifle", "B 型步枪")
    assert glossary.parse_newterm("Highmark\t高标镇 => 旧称") == ("Highmark", "高标镇 => 旧称")
    assert glossary.parse_newterm("Highmark => 高标镇") == ("Highmark", "高标镇")
    assert glossary.parse_newterm("Type->B rifle") == ("Type", "B rifle")           # no TAB: the arrow separates
