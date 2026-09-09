import json
import os
from ainiee_translate import cache_io, batch, review


def _rules(**cfg):
    return review.Rules(cfg, cfg.pop("_glossary", []))


SEG = {"text_index": 1, "source_text": "The <i>Euphrates</i> ran. Kira said so.",
       "translated_text": "<i>Euphrates</i> 号跑了。Kira 上校这么说的。他也这么说的。"}


def _f(off, prop, cat="B", **kw):
    return {"id": "t-1", "text_index": 1, "category": cat, "severity": 2, "offending": off, "proposed": prop, **kw}


def test_check_offending_must_occur_once():
    r = _rules()
    assert review.check(_f("这么说的", "这样说的"), SEG, r)[1].startswith("ambiguous(2)")
    ok, why, new = review.check(_f("他也这么说的", "他也这样说的"), SEG, r)
    assert ok and new.endswith("他也这样说的。")


def test_check_redline_change_forbidden_mention_allowed():
    r = _rules(redline=[r"上校|舰长"])
    assert review.check(_f("Kira 上校这么说的", "Kira 舰长这么说的"), SEG, r)[1] == "E_redline"
    assert review.check(_f("Kira 上校这么说的", "Kira 上校是这么说的"), SEG, r)[0]


def test_check_settled_may_be_added_not_removed():
    r = _rules(settled=["号"], _glossary=["上校"])
    assert review.check(_f("<i>Euphrates</i> 号跑了", "<i>Euphrates</i> 跑了"), SEG, r)[1] == "E_settled_removed"
    assert review.check(_f("Kira 上校这么说的", "Kira 这么说的"), SEG, r)[1] == "E_settled_removed"   # glossary dst
    assert review.check(_f("他也这么说的", "他这位上校也这么说的"), SEG, r)[0]                       # adding is fine


def test_check_tags_latin_and_forbidden_chars():
    r = _rules()
    assert review.check(_f("<i>Euphrates</i> 号", "Euphrates 号"), SEG, r)[1] == "tag:tag_mismatch"
    assert review.check(_f("Kira 上校", "Nerys 上校"), SEG, r)[1] == "name_touch"
    assert review.check(_f("Kira 上校", "Kira Nerys 上校", cat="A", latin_change=True), SEG, r)[0]
    assert review.check(_f("Kira 上校", "Kira Nerys 上校", cat="C", latin_change=True), SEG, r)[1] == "name_touch"
    assert review.check(_f("他也这么说的", "他也「这么」说的"), SEG, r)[1] == "forbid_char"
    assert review.check(_f("他也这么说的", "他也这么说的,"), SEG, r)[1] == "soft:halfwidth_punct"
    assert review.check({"id": "x", "text_index": 1, "category": "E", "offending": "a", "proposed": "b"}, SEG, r)[1] == "bad_category"


def _project_dir(tmp_path, make_project):
    proj = make_project(sources=["one two three", "four <i>five</i> six", "seven"], project_id="t")
    cache_io.set_translation(proj, 1, "一 二 三")
    cache_io.set_polish(proj, 2, "四 <i>五</i> 六")
    cache_io.set_translation(proj, 3, "七")
    cache = tmp_path / "work" / "cache.json"
    cache.parent.mkdir()
    cache_io.save_cache(proj, str(cache))
    return str(cache)


def test_split_review_stage_range_prefix(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    out = tmp_path / "work" / "review" / "groups"
    batch.main(["split", cache, "--stage", "review", "--range", "1-2", "--prefix", "g", "--target", "10",
                "--out-dir", str(out), "--context", "0"])
    rows = json.load(open(out / "grp_g1_src.json", encoding="utf-8"))
    assert [r["text_index"] for r in rows] == [1, 2]                  # status 1 and 2 both reviewed; #3 out of range
    assert rows[1]["translated_text"] == "四 <i>五</i> 六"
    assert json.load(open(out / "_stage.json"))["prefix"] == "g"


def test_pre_final_merge_pick_roundtrip(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    findings = [
        {"id": "g1-001", "text_index": 1, "category": "A", "severity": 3, "offending": "二", "proposed": "贰"},
        {"id": "g1-002", "text_index": 1, "category": "B", "severity": 2, "offending": "三", "proposed": "叁"},
        {"id": "g1-003", "text_index": 2, "category": "B", "severity": 2, "offending": "六", "proposed": "陆"},
        {"id": "g1-004", "text_index": 2, "category": "B", "severity": 2, "offending": "四", "proposed": "肆"},
        {"id": "g1-005", "text_index": 3, "category": "C", "severity": 1, "offending": "七", "proposed": "柒"},
        {"id": "g1-006", "text_index": 3, "category": "B", "severity": 2, "offending": "八", "proposed": "捌"},  # not in text
    ]
    review.write_jsonl(paths.f("findings_g1.jsonl"), findings)
    rules = review.load_rules(paths)
    stats = review.pre(paths, rules, [paths.f("findings_g1.jsonl")])[0]
    assert stats["ok"] == 5 and stats["rejected"] == 1
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [
        {"id": "g1-001", "verdict": "accept", "reason": "ok"},
        {"id": "g1-002", "verdict": "amend", "amended": "叄", "reason": "better glyph"},
        {"id": "g1-003", "verdict": "reject", "reason": "original fine"},
        {"id": "g1-004", "verdict": "accept", "reason": "问题是真的，但应降为 C"},
        {"id": "g1-005", "verdict": "accept", "reason": "style"},
    ])
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"], res["rejected"]) == (1, 2, 1)
    apply = json.load(open(paths.f("apply_g1.json"), encoding="utf-8"))
    assert apply == [{"text_index": 1, "polished_text": "一 贰 叄"}]           # two findings applied in sequence
    review_md = open(paths.f("review_g1.md"), encoding="utf-8").read()
    assert "g1-004 | 2 | C/2" in review_md and "g1-005 | 3 | C/1" in review_md
    assert review.merge(paths, ["g1"]) == 2
    # human picks one of the C items -> apply file built from the *current* cache text
    assert review.pick(paths, rules, ["g1-005", "nope"], ["g1"]) == 1
    picked = json.load(open(paths.f("apply_pick.json"), encoding="utf-8"))
    assert picked == [{"text_index": 3, "polished_text": "柒"}]
    # a group with no verdicts file: everything goes to the human list
    review.write_jsonl(paths.f("findings_D.jsonl"), [
        {"id": "D-001", "text_index": 3, "category": "D", "severity": 2, "offending": "七", "proposed": "柒"}])
    review.pre(paths, rules, [paths.f("findings_D.jsonl")])
    assert review.final(paths, rules, ["D"])[0]["review"] == 1


def test_benchmark_excludes_term_only_edits(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    old = tmp_path / "old.json"
    proj = cache_io.load_cache(cache)
    cache_io.set_translation(proj, 1, "一 二 三 舰长")        # will differ only by a term swap
    cache_io.set_translation(proj, 3, "柒")                   # substantive change
    cache_io.save_cache(proj, str(old))
    proj = cache_io.load_cache(cache)
    cache_io.set_translation(proj, 1, "一 二 三 上校")
    cache_io.set_translation(proj, 3, "七")
    cache_io.save_cache(proj, cache)
    paths = review.Paths(cache)
    os.makedirs(paths.dir)
    rules = review.Rules({"term_only": [["舰长", "上校"]]})
    res = review.benchmark(paths, rules, str(old), 1, 3)
    assert res["term_only"] == [1] and res["changed"] == [3]


def test_load_rules_reads_config_and_glossary(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.dir)
    json.dump({"redline": ["上校"], "forbid": ""}, open(paths.f("config.json"), "w"))
    json.dump({"terms": [{"src": "phaser", "dst": "相位枪"}, {"src": "Ops", "dst": "", "keep_source": True}]},
              open(os.path.join(os.path.dirname(cache), "glossary.locked.json"), "w"))
    r = review.load_rules(paths)
    assert r.violation("Kira 上校", "Kira 舰长") == "E_redline"
    assert r.violation("那把相位枪", "那把相位枪，沉甸甸的") == ""   # term kept
    assert r.violation("那把相位枪", "那把枪") == "E_settled_removed"
    assert r.violation("a", "「a」") == ""                    # forbid disabled by config
