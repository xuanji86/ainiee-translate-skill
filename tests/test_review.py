import json
import os
from ainiee_translate import cache_io, batch, review


def _rules(**cfg):
    return review.Rules(cfg, cfg.pop("_glossary", []))


SEG = {"text_index": 1, "source_text": "The <i>Meridian</i> ran. Mara said so.",
       "translated_text": "<i>Meridian</i> 号跑了。Mara 上校这么说的。他也这么说的。"}


def _f(off, prop, cat="B", **kw):
    return {"id": "t-1", "text_index": 1, "category": cat, "severity": 2, "offending": off, "proposed": prop, **kw}


def test_check_offending_must_occur_once():
    r = _rules()
    assert review.check(_f("这么说的", "这样说的"), SEG, r)[1].startswith("ambiguous(2)")
    ok, why, new = review.check(_f("他也这么说的", "他也这样说的"), SEG, r)
    assert ok and new.endswith("他也这样说的。")


def test_check_redline_change_forbidden_mention_allowed():
    r = _rules(redline=[r"上校|舰长"])
    assert review.check(_f("Mara 上校这么说的", "Mara 舰长这么说的"), SEG, r)[1] == "E_redline"
    assert review.check(_f("Mara 上校这么说的", "Mara 上校是这么说的"), SEG, r)[0]


def test_check_settled_may_be_added_not_removed():
    r = _rules(settled=["号"], _glossary=["上校"])
    assert review.check(_f("<i>Meridian</i> 号跑了", "<i>Meridian</i> 跑了"), SEG, r)[1] == "E_settled_removed"
    assert review.check(_f("Mara 上校这么说的", "Mara 这么说的"), SEG, r)[1] == "E_settled_removed"   # glossary dst
    assert review.check(_f("他也这么说的", "他这位上校也这么说的"), SEG, r)[0]                       # adding is fine


def test_check_tags_latin_and_forbidden_chars():
    r = _rules()
    assert review.check(_f("<i>Meridian</i> 号", "Meridian 号"), SEG, r)[1] == "tag:tag_mismatch"
    assert review.check(_f("Mara 上校", "Venn 上校"), SEG, r)[1] == "name_touch"
    assert review.check(_f("Mara 上校", "Mara Venn 上校", cat="A", latin_change=True), SEG, r)[0]
    assert review.check(_f("Mara 上校", "Mara Venn 上校", cat="C", latin_change=True), SEG, r)[1] == "name_touch"
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
    json.dump({"terms": [{"src": "musket", "dst": "火枪"}, {"src": "Ops", "dst": "", "keep_source": True}]},
              open(os.path.join(os.path.dirname(cache), "glossary.locked.json"), "w"))
    r = review.load_rules(paths)
    assert r.violation("Mara 上校", "Mara 舰长") == "E_redline"
    assert r.violation("那把火枪", "那把火枪，沉甸甸的") == ""   # term kept
    assert r.violation("那把火枪", "那把枪") == "E_settled_removed"
    assert r.violation("a", "「a」") == ""                    # forbid disabled by config


def test_check_sentence_rewrite_length_guard():
    seg = {"text_index": 1, "source_text": "x",
           "translated_text": "他在剖解通讯面板内存缓冲区里的活动日志时，不喜欢自己看到的东西。"}
    r = _rules()
    off = "他在剖解通讯面板内存缓冲区里的活动日志时，不喜欢自己看到的东西"
    ok, _, new = review.check(_f(off, "他剖解通讯面板内存缓冲区里的活动日志，越看越不喜欢"), seg, r)
    assert ok and new.startswith("他剖解")
    assert review.check(_f(off, "他不喜欢"), seg, r)[1].startswith("rewrite_length")          # content dropped
    assert review.check(_f("不喜欢", "一点也不喜欢啊呀"), seg, r)[0]                           # short edits unguarded


def test_blind_and_hints(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    review.blind(paths, ["g1"])
    b = json.load(open(os.path.join(paths.groups, "blind_g1.json"), encoding="utf-8"))
    assert all(set(r) == {"text_index", "translated_text"} for r in b["segments"])     # no source leaks through
    review.write_jsonl(paths.f("flags_g1.jsonl"), [
        {"id": "g1-b001", "text_index": 2, "quote": "<i>五</i>", "why": "读着绊"},
        {"id": "g1-b002", "text_index": 2, "quote": "不存在", "why": "x"},
        {"id": "g1-b003", "text_index": 99, "quote": "七", "why": "x"}])
    res = review.hints(paths, [paths.f("flags_g1.jsonl")])[0]
    assert (res["flags"], res["segments"], res["rejected"]) == (1, 1, 2)
    h = json.load(open(paths.f("hints_g1.json"), encoding="utf-8"))
    assert h[0]["source_text"] == "four <i>five</i> six" and h[0]["flags"][0]["id"] == "g1-b001"


def test_redline_waivable_entry():
    r = _rules(redline=[{"re": r"上校|舰长", "waivable": True}, "号"])
    f = _f("Mara 上校这么说的", "Mara 舰长这么说的", cat="D")
    assert review.check(f, SEG, r)[1] == "E_redline"                                  # no waiver -> still a redline
    assert review.check(dict(f, redline_waiver="source: Captain of her ship"), SEG, r)[0]
    # a non-waivable entry stays hard even with a waiver
    assert review.check(_f("<i>Meridian</i> 号跑了", "<i>Meridian</i> 跑了", redline_waiver="x"), SEG, r)[1] == "E_redline"


def test_needs_challenge_tiers():
    assert review.needs_challenge({"id": "a", "flags": ["b1"], "severity": 2}) == ""
    assert review.needs_challenge({"id": "a", "severity": 1}) == "unflagged"
    assert review.needs_challenge({"id": "a", "flags": ["b1"], "severity": 3}) == "severity"
    assert review.needs_challenge({"id": "a", "flags": ["b1"], "severity": 1, "latin_change": True}) == "latin"
    assert review.needs_challenge({"id": "a", "flags": ["b1"], "severity": 1, "redline_waiver": "x"}) == "waiver"
    assert review.needs_challenge({"id": "a", "flags": ["b1"], "severity": 1}, sample=1.0) == "sample"


def test_segs_tier_auto_verdicts_and_final(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    review.write_jsonl(paths.f("findings_g1.jsonl"), [
        {"id": "g1-001", "text_index": 1, "category": "B", "severity": 2, "offending": "二", "proposed": "贰", "flags": ["g1-b1"]},
        {"id": "g1-002", "text_index": 2, "category": "B", "severity": 2, "offending": "六", "proposed": "陆"},
    ])
    rules = review.load_rules(paths)
    review.pre(paths, rules, [paths.f("findings_g1.jsonl")])
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], tier=True, sample=0.0)
    assert [f["id"] for f in review.read_jsonl(paths.f("challenge_g1.jsonl"))] == ["g1-002"]
    assert [v["id"] for v in review.read_jsonl(paths.f("verdicts_g1.auto.jsonl"))] == ["g1-001"]
    assert [r["text_index"] for r in json.load(open(paths.f("segs_g1.json"), encoding="utf-8"))] == [2]
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [{"id": "g1-002", "verdict": "reject", "reason": "fine"}])
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["rejected"]) == (1, 1)
    assert json.load(open(paths.f("apply_g1.json"), encoding="utf-8")) == [{"text_index": 1, "polished_text": "一 贰 三"}]
    # without --tier everything is challenged and a stale auto file is removed
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")])
    assert len(review.read_jsonl(paths.f("challenge_g1.jsonl"))) == 2
    assert not os.path.exists(paths.f("verdicts_g1.auto.jsonl"))
    txt = review.stats(paths, ["g1"])
    assert "| noflag | B | 2 | 1 | 1 | 100.0% |" in txt


def test_rules_slice(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    ex = tmp_path / "EXAMPLES.md"
    ex.write_text("# x\n\n- 「的」字别扎堆\n- Seven 译「阿七」\n- five 译「伍」\n", encoding="utf-8")
    locked = tmp_path / "work" / "glossary.locked.json"
    locked.write_text(json.dumps({"terms": [{"src": "seven", "dst": "柒"}, {"src": "nine", "dst": "玖"}]}), encoding="utf-8")
    row = review.rules_slice(paths, ["g1"], str(locked), [str(ex)])[0]
    obj = json.load(open(paths.f("rules_g1.json"), encoding="utf-8"))
    assert obj["general"] == ["- 「的」字别扎堆"]
    assert set(obj["rulings"]) == {"- Seven 译「阿七」", "- five 译「伍」"}
    assert [t["src"] for t in obj["glossary"]] == ["seven"] and row["glossary"] == 1


def test_settled_longer_rendering_and_glossary_override():
    seg = {"text_index": 1, "source_text": "She was chief medical officer. The Borg queen.",
           "translated_text": "她首先是医生。博格来了。"}
    r = _rules(settled=["博格", "博格女王", "首席医疗官"], _glossary=["医生"])
    # a longer settled rendering that contains the removed one keeps it
    assert review.check(_f("博格来了", "博格女王来了"), seg, r)[0]
    # glossary-only dst: an A finding may drop it (and is then always challenged) ...
    f = _f("她首先是医生", "她首先是首席医疗官", cat="A")
    assert review.check(f, seg, r)[0] and f["_settled_override"] == ["医生"]
    # ... a B/C finding may not, and nobody may drop a config `settled` rendering
    assert review.check(_f("她首先是医生", "她首先是首席医疗官"), seg, r)[1] == "E_settled_removed"
    assert review.check(_f("博格来了", "他们来了", cat="A"), seg, r)[1] == "E_settled_removed"


def test_needs_challenge_slim_mode():
    nc = lambda **f: review.needs_challenge({"id": "a", **f}, mode="slim")  # noqa: E731
    assert nc(category="A", flags=["b1"], severity=2) == "ab"       # flagged A/B: still challenged
    assert nc(category="B", severity=1) == "ab"
    assert nc(category="C", flags=["b1"], severity=2) == ""         # flagged C: human list anyway
    assert nc(category="C", severity=2) == "unflagged"
    assert nc(category="C", flags=["b1"], severity=2, redline_waiver="x") == "waiver"
    assert nc(category="C", flags=["b1"], severity=2, _force_challenge=True) == "waiver"
    assert nc(category="C", flags=["b1"], severity=2, latin_change=True) == "latin"
    assert review.needs_challenge({"id": "a", "category": "C", "flags": ["b1"]}, mode="all") == "all"


def test_segs_slim_and_check_command(tmp_path, make_project, capsys):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    review.write_jsonl(paths.f("flags_g1.jsonl"), [{"id": "g1-b1", "text_index": 1, "quote": "二"}])
    good = [
        {"id": "g1-001", "text_index": 1, "category": "B", "severity": 2, "offending": "二", "proposed": "贰",
         "reason": "r", "flags": ["g1-b1"]},
        {"id": "g1-002", "text_index": 2, "category": "C", "severity": 2, "offending": "六", "proposed": "陆",
         "reason": "r", "source_evidence": "six", "flags": ["g1-b1"]},
        {"id": "g1-003", "text_index": 3, "category": "C", "severity": 2, "offending": "七", "proposed": "柒",
         "reason": "r", "source_evidence": "seven"},
    ]
    review.write_jsonl(paths.f("findings_g1.jsonl"), good)
    before = sorted(os.listdir(paths.dir))
    assert review.main(["check", cache, "g1"]) == 0
    assert "OK" in capsys.readouterr().out
    assert sorted(os.listdir(paths.dir)) == before          # read-only
    bad = good + [
        {"id": "g1-001", "text_index": 1, "category": "B", "severity": 2, "offending": "一", "proposed": "壹", "reason": "r"},
        {"id": "g1-005", "text_index": 1, "category": "C", "severity": 1, "offending": "三", "proposed": "叁",
         "reason": "r", "source_evidence": "three"},
        {"id": "g1-006", "text_index": 1, "category": "D", "severity": 2, "offending": "三", "proposed": "叁", "reason": "r"},
        {"id": "g1-007", "text_index": 2, "category": "A", "severity": 2, "offending": "四", "proposed": "肆", "reason": "r"},
        {"id": "g1-008", "text_index": 2, "category": "B", "severity": 2, "offending": "九", "proposed": "玖",
         "reason": "r", "flags": ["g1-b9"]},
    ]
    with open(paths.f("findings_g1.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(f, ensure_ascii=False) for f in bad) + "\n{not json\n")
    assert review.main(["check", cache, "g1"]) == 1
    out = capsys.readouterr().out
    for msg in ("g1-001: duplicate id", "g1-005: drop C severity 1", "g1-006: no D findings",
                "g1-007: source_evidence required", "g1-008: unknown flags ['g1-b9']", "g1-008: gate ambiguous(0)",
                "bad JSON"):
        assert msg in out, msg
    # slim assignment: A/B challenged, flagged C auto, unflagged C challenged
    review.write_jsonl(paths.f("findings_g1.jsonl"), good)
    rules = review.load_rules(paths)
    review.pre(paths, rules, [paths.f("findings_g1.jsonl")])
    assert review.main(["segs", cache, "--mode", "slim", paths.f("findings_g1.pre.jsonl")]) == 0
    assert [f["id"] for f in review.read_jsonl(paths.f("challenge_g1.jsonl"))] == ["g1-001", "g1-003"]
    assert [v["id"] for v in review.read_jsonl(paths.f("verdicts_g1.auto.jsonl"))] == ["g1-002"]
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [{"id": "g1-001", "verdict": "accept", "reason": "ok"},
                                                     {"id": "g1-003", "verdict": "reject", "reason": "fine"}])
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"], res["rejected"]) == (1, 1, 1)
