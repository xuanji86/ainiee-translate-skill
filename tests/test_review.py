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
    ok, why, new, _ = review.check(_f("他也这么说的", "他也这样说的"), SEG, r)
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
    assert r.violation("Mara 上校", "Mara 舰长")[0] == "E_redline"
    assert r.violation("那把火枪", "那把火枪，沉甸甸的")[0] == ""   # term kept
    assert r.violation("那把火枪", "那把枪")[0] == "E_settled_removed"
    assert r.violation("a", "「a」")[0] == ""                    # forbid disabled by config


def test_check_sentence_rewrite_length_guard():
    seg = {"text_index": 1, "source_text": "x",
           "translated_text": "他在剖解通讯面板内存缓冲区里的活动日志时，不喜欢自己看到的东西。"}
    r = _rules()
    off = "他在剖解通讯面板内存缓冲区里的活动日志时，不喜欢自己看到的东西"
    ok, _, new, _ = review.check(_f(off, "他剖解通讯面板内存缓冲区里的活动日志，越看越不喜欢"), seg, r)
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
    review.write_jsonl(paths.f("flags_g1.jsonl"), [{"id": "g1-b1", "text_index": 1, "quote": "二"}])
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
    seg = {"text_index": 1, "source_text": "She was chief medical officer. The Halcyon came, its captain said.",
           "translated_text": "她首先是医生。翠鸟号来了，翠鸟号舰长说。"}
    r = _rules(settled=["翠鸟号", "翠鸟号舰长", "首席医疗官"], _glossary=["医生"])
    # a longer settled rendering that contains the removed one keeps it
    assert review.check(_f("翠鸟号来了", "翠鸟号舰长来了"), seg, r)[0]
    # ... but one already standing in `off` does not cover a dropped shorter one
    assert review.check(_f("翠鸟号来了，翠鸟号舰长说", "他们来了，翠鸟号舰长说"), seg, r)[1] == "E_settled_removed"
    # glossary-only dst: an A finding may drop it (and is then always challenged) ...
    f = _f("她首先是医生", "她首先是首席医疗官", cat="A")
    ok, _, _, override = review.check(f, seg, r)
    assert ok and override == ["医生"] and "_settled_override" not in f      # check() does not mutate
    # ... a B/C finding may not, and nobody may drop a config `settled` rendering
    assert review.check(_f("她首先是医生", "她首先是首席医疗官"), seg, r)[1] == "E_settled_removed"
    assert review.check(_f("翠鸟号来了", "他们来了", cat="A"), seg, r)[1] == "E_settled_removed"


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
    review.write_jsonl(paths.f("flags_g1.jsonl"), [{"id": "g1-b1", "text_index": 1, "quote": "二"},
                                                  {"id": "g1-b2", "text_index": 2, "quote": "六"}])
    good = [
        {"id": "g1-001", "text_index": 1, "category": "B", "severity": 2, "offending": "二", "proposed": "贰",
         "reason": "r", "flags": ["g1-b1"]},
        {"id": "g1-002", "text_index": 2, "category": "C", "severity": 2, "offending": "六", "proposed": "陆",
         "reason": "r", "source_evidence": "six", "flags": ["g1-b2"]},
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
    # a flag that exists but sits on another segment, and a flags field that is not a list
    review.write_jsonl(paths.f("findings_g1.jsonl"), [dict(good[0], flags=["g1-b2"]), dict(good[2], flags="g1-b1")])
    assert review.main(["check", cache, "g1"]) == 1
    out = capsys.readouterr().out
    assert "g1-001: flags of another segment ['g1-b2']" in out and "g1-003: flags must be a list" in out
    # mixed-type severity must be reported, not crash the summary
    with open(paths.f("findings_g1.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(good[0], severity="2"), ensure_ascii=False) + "\n"
                 + json.dumps(good[1], ensure_ascii=False) + "\n")
    assert review.main(["check", cache, "g1"]) == 1
    assert "g1-001: severity must be 1/2/3" in capsys.readouterr().out
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


def test_settled_override_is_always_challenged(tmp_path, make_project, capsys):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    rules = review.Rules({}, ["二"])            # 二 is a glossary-only settled rendering
    review.write_jsonl(paths.f("flags_g1.jsonl"), [{"id": "g1-b1", "text_index": 1, "quote": "二"},
                                                  {"id": "g1-b3", "text_index": 3, "quote": "七"}])
    review.write_jsonl(paths.f("findings_g1.jsonl"), [
        {"id": "g1-001", "text_index": 1, "category": "A", "severity": 2, "offending": "二", "proposed": "两",
         "flags": ["g1-b1"]},
        {"id": "g1-002", "text_index": 3, "category": "C", "severity": 2, "offending": "七", "proposed": "柒",
         "flags": ["g1-b3"]},
    ])
    review.pre(paths, rules, [paths.f("findings_g1.jsonl")])
    f = review.read_jsonl(paths.f("findings_g1.pre.jsonl"))[0]
    assert f["_settled_override"] == ["二"] and f["_force_challenge"]
    for mode in ("tier", "slim"):               # flagged sev2 A would be auto under tier without the override
        review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], mode=mode, sample=0.0)
        assert [x["id"] for x in review.read_jsonl(paths.f("challenge_g1.jsonl"))] == ["g1-001"]
    # a group with nothing to challenge: final must not warn about a missing verdicts file
    review.write_jsonl(paths.f("findings_g1.jsonl"), [review.read_jsonl(paths.f("findings_g1.jsonl"))[1]])
    review.pre(paths, rules, [paths.f("findings_g1.jsonl")])
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], mode="slim")
    assert "no Challenger needed" in capsys.readouterr().out
    res = review.final(paths, rules, ["g1"])[0]
    assert "WARNING" not in capsys.readouterr().out and res["review"] == 1


# ------------------------------------------------- verdict -> write-back ----
def _group(tmp_path, make_project, findings, rules=None, flags=None, rejected=0):
    """cache 1 "一 二 三" / 2 "四 <i>五</i> 六" / 3 "七" split into g1; findings through `pre`.
    `flags`: the Blind Reader's flags_g1.jsonl rows (a finding's `flags` only count when they are there)."""
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    os.makedirs(paths.groups)
    batch.main(["split", cache, "--stage", "review", "--prefix", "g", "--target", "10",
                "--out-dir", paths.groups, "--context", "0"])
    rules = rules or review.load_rules(paths)
    if flags:
        review.write_jsonl(paths.f("flags_g1.jsonl"), flags)
    review.write_jsonl(paths.f("findings_g1.jsonl"), findings)
    assert review.pre(paths, rules, [paths.f("findings_g1.jsonl")])[0]["rejected"] == rejected
    return cache, paths, rules


def _fd(n, ti, off, prop, cat="B", sev=2, **kw):
    return {"id": f"g1-00{n}", "text_index": ti, "category": cat, "severity": sev, "offending": off,
            "proposed": prop, **kw}


def _rejects(paths):
    return {r["id"]: r["_reject"] for r in review.read_jsonl(paths.f("rejected_g1.jsonl"))}


def _apply(paths, name="apply_g1.json"):
    return json.load(open(paths.f(name), encoding="utf-8"))


def test_final_without_verdicts_never_auto_applies(tmp_path, make_project, capsys):
    rules = review.Rules({"redline": [{"re": "二|贰", "waivable": True}]})
    cache, paths, _ = _group(tmp_path, make_project, [
        _fd(1, 1, "二", "贰", cat="A", redline_waiver="source: two"),     # forced to the Challenger
        _fd(2, 1, "三", "叁"),
        _fd(3, 2, "六", "陆", cat="C", flags=["g1-b1"])], rules,
        flags=[{"id": "g1-b1", "text_index": 2, "quote": "六"}])
    # no challenge / verdicts file at all (segs never run): human list only, A/B included
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"], res["rejected"]) == (0, 3, 0)
    assert _apply(paths) == [] and review.merge(paths, ["g1"], rules=rules) == 3
    # sent to a Challenger whose verdicts never landed: challenged findings are no_verdict, not applied
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")])
    capsys.readouterr()
    res = review.final(paths, rules, ["g1"])[0]
    assert "WARNING" in capsys.readouterr().out
    assert (res["apply_segments"], res["review"], res["rejected"]) == (0, 0, 3)
    assert set(_rejects(paths).values()) == {"challenger:no_verdict"}
    assert review.merge(paths, ["g1"], rules=rules) == 0
    assert review.pick(paths, rules, ["g1-001", "g1-002"], ["g1"]) == 0
    # slim: the flagged C is auto-accepted (human list), the challenged A/B still need a verdict
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], mode="slim")
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"]) == (0, 1)
    assert [r["id"] for r in review.leftover(paths, rules, ["g1"])] == ["g1-003"]


def test_verdict_values_are_validated(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 1, "一", "壹"), _fd(2, 1, "二", "贰"), _fd(3, 1, "三", "叁"),
        _fd(4, 2, "四", "肆"), _fd(5, 2, "六", "陆"), _fd(6, 3, "七", "柒")])
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [
        {"id": "g1-001", "verdict": "rejected", "reason": "x"},
        {"id": "g1-002", "verdict": "Reject", "reason": "fine"},
        {"id": "g1-003", "verdict": "否决", "reason": "x"},
        {"id": "g1-004", "verdict": "amend", "reason": "x"},                    # amend without `amended`
        {"id": "g1-005", "verdict": " Accept ", "reason": "ok"},
        {"id": "g1-006", "verdict": "amend", "amended": "  ", "reason": "x"}])
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"], res["rejected"]) == (1, 0, 5)
    assert _apply(paths) == [{"text_index": 2, "polished_text": "四 <i>五</i> 陆"}]
    assert _rejects(paths) == {"g1-001": "bad_verdict:rejected", "g1-002": "challenger:fine",
                               "g1-003": "bad_verdict:否决", "g1-004": "bad_verdict:amend",
                               "g1-006": "bad_verdict:amend"}
    assert review.merge(paths, ["g1"], rules=rules) == 0
    assert review.pick(paths, rules, [f"g1-00{n}" for n in range(1, 7)], ["g1"]) == 1   # only the valid accept
    assert _apply(paths, "apply_pick.json") == [{"text_index": 2, "polished_text": "四 <i>五</i> 陆"}]


def test_amend_failed_and_missing_verdict_not_resurrected(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 3, "七", "柒", cat="C"),
        _fd(2, 1, "二", "贰", cat="C"),
        _fd(3, 1, "三", "叁", cat="C"),
        _fd(4, 2, "六", "陆", cat="B")])
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [
        {"id": "g1-001", "verdict": "amend", "amended": "「柒」", "reason": "x"},   # amended text fails the gate
        {"id": "g1-002", "verdict": "amend", "amended": "两", "reason": "better"},
        {"id": "g1-004", "verdict": "amend", "amended": "Six", "reason": "x"}])     # g1-003: no verdict
    res = review.final(paths, rules, ["g1"])[0]
    assert (res["apply_segments"], res["review"], res["rejected"]) == (0, 1, 3)
    assert _rejects(paths) == {"g1-001": "amend_failed:forbid_char", "g1-003": "challenger:no_verdict",
                               "g1-004": "amend_failed:name_touch"}
    assert review.merge(paths, ["g1"], rules=rules) == 1
    md = open(paths.f("review_ALL.md"), encoding="utf-8").read()
    assert "g1-002" in md and "| 两 |" in md and "g1-001" not in md and "g1-003" not in md
    assert review.pick(paths, rules, ["g1-001", "g1-002", "g1-003", "g1-004"], ["g1"]) == 1
    assert _apply(paths, "apply_pick.json") == [{"text_index": 1, "polished_text": "一 两 三"}]
    assert review.pick(paths, rules, [], ["g1"], min_sev=1) == 1


def test_category_reclassification(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 1, "一", "壹", cat="C"), _fd(2, 1, "二", "贰", cat="C"), _fd(3, 2, "六", "陆", cat="C"),
        _fd(4, 3, "七", "柒", cat="A", sev=3), _fd(5, 2, "四", "肆", cat="C")])
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [
        {"id": "g1-001", "verdict": "accept", "reason": "不应改为 A，维持 C"},      # free text cannot promote
        {"id": "g1-002", "verdict": "accept", "reason": "reclassified as B"},
        {"id": "g1-003", "verdict": "accept", "category": "a", "severity": "3", "reason": "其实是误译"},
        {"id": "g1-004", "verdict": "accept", "category": "C", "severity": 1, "reason": "应为 A 无误"},
        {"id": "g1-005", "verdict": "accept", "category": "E", "reason": "x"}])
    res = review.final(paths, rules, ["g1"])[0]
    assert _apply(paths) == [{"text_index": 2, "polished_text": "四 <i>五</i> 陆"}]   # explicit field: C -> A
    assert _rejects(paths) == {"g1-005": "bad_verdict:category=E"}
    md = open(paths.f("review_g1.md"), encoding="utf-8").read()
    assert "g1-001 | 1 | C/2" in md and "g1-002 | 1 | C/2" in md and "g1-004 | 3 | C/1" in md
    assert res["review"] == 3
    left = {r["id"]: (r["category"], r["severity"]) for r in review.leftover(paths, rules, ["g1"])}
    assert left == {"g1-001": ("C", 2), "g1-002": ("C", 2), "g1-004": ("C", 1)}


def test_pick_out_without_json_suffix(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [_fd(1, 3, "七", "柒", cat="C")])
    out = str(tmp_path / "picked")
    assert review.pick(paths, rules, ["g1-001"], ["g1"], out=out) == 1
    assert json.load(open(out, encoding="utf-8")) == [{"text_index": 3, "polished_text": "柒"}]
    assert json.load(open(out + ".meta.json", encoding="utf-8"))[0]["_findings"] == ["g1-001"]


# ------------------------------------------------- gate hardening (v1.17.2) ----
def test_pre_drops_flags_that_are_missing_or_on_another_segment(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 1, "二", "贰", flags=["g1-b1"]),          # a real flag on its own segment
        _fd(2, 2, "六", "陆", flags=["g1-b1"]),          # the flag belongs to segment 1
        _fd(3, 3, "七", "柒", flags=["g1-b9"]),          # no such flag
        _fd(4, 1, "三", "叁", flags="g1-b1")],           # not a list
        flags=[{"id": "g1-b1", "text_index": 1, "quote": "二"}])
    pre = {f["id"]: f for f in review.read_jsonl(paths.f("findings_g1.pre.jsonl"))}
    assert [pre[f"g1-00{n}"]["flags"] for n in (1, 2, 3, 4)] == [["g1-b1"], [], [], []]
    assert pre["g1-002"]["_flags_dropped"] == ["g1-b1"] and "_flags_dropped" not in pre["g1-001"]
    # only the really corroborated finding may skip the Challenger
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], tier=True, sample=0.0)
    assert [v["id"] for v in review.read_jsonl(paths.f("verdicts_g1.auto.jsonl"))] == ["g1-001"]
    assert [f["id"] for f in review.read_jsonl(paths.f("challenge_g1.jsonl"))] == ["g1-002", "g1-003", "g1-004"]


def test_pre_drops_flags_when_there_is_no_flags_file(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [_fd(1, 1, "二", "贰", flags=["g1-b1"])])
    assert review.read_jsonl(paths.f("findings_g1.pre.jsonl"))[0]["flags"] == []
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")], tier=True, sample=0.0)
    assert not os.path.exists(paths.f("verdicts_g1.auto.jsonl"))


def test_pre_rejects_duplicate_ids_and_bad_types(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 1, "二", "贰"),
        _fd(1, 3, "七", "柒"),                           # the same id again
        _fd(2, 1, "三", "叁", sev="high"),
        _fd(3, 1, "三", "叁", sev=5),
        _fd(4, 2, "六", ["陆"]),
        dict(_fd(5, 2, "六", "陆"), id=["x"]),
        "not an object"], rejected=6)
    pre = review.read_jsonl(paths.f("findings_g1.pre.jsonl"))
    assert [(f["id"], f["offending"]) for f in pre] == [("g1-001", "二")]
    assert [r["_reject"] for r in review.read_jsonl(paths.f("rejected_g1.jsonl"))] == [
        "duplicate_id", "bad_severity", "bad_severity", "bad_type", "bad_type", "bad_type"]
    # what survived runs through the later stages without a stack trace
    review.segs_for(paths, [paths.f("findings_g1.pre.jsonl")])
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [{"id": "g1-001", "verdict": "accept", "reason": "ok"}])
    assert review.final(paths, rules, ["g1"])[0]["apply_segments"] == 1
    assert _apply(paths) == [{"text_index": 1, "polished_text": "一 贰 三"}]


def test_glossary_dst_alternatives_are_each_settled(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    with open(os.path.join(os.path.dirname(cache), "glossary.locked.json"), "w", encoding="utf-8") as f:
        json.dump({"terms": [{"src": "two", "dst": "二/贰"}, {"src": "three", "dst": "三 | 叁"}]}, f, ensure_ascii=False)
    rules = review.load_rules(review.Paths(cache))
    seg = {"text_index": 1, "source_text": "one two three", "translated_text": "一 二 三"}
    assert review.check(_fd(1, 1, "二", "两"), seg, rules)[1] == "E_settled_removed"
    assert review.check(_fd(1, 1, "三", "仨"), seg, rules)[1] == "E_settled_removed"
    assert review.check(_fd(1, 1, "一 二", "壹 二"), seg, rules)[0]


def test_redline_whole_match_settled_counted_forbid_only_when_introduced():
    def seg(text):
        return {"text_index": 1, "source_text": "x", "translated_text": text}
    # a redline with a capture group compares the whole match, not the group
    r = _rules(redline=[r"(上|中)[校尉]"])
    assert review.check(_fd(1, 1, "上校", "上尉"), seg("Hale 上校到了。"), r)[1] == "E_redline"
    assert review.check(_fd(1, 1, "到了", "来了"), seg("Hale 上校到了。"), r)[0]
    # a settled rendering used twice may not drop to once
    r = _rules(settled=["翠鸟号"])
    two = seg("翠鸟号起航，翠鸟号返航。")
    assert review.check(_fd(1, 1, "翠鸟号起航，翠鸟号返航", "翠鸟号起航，随后返航"), two, r)[1] == "E_settled_removed"
    assert review.check(_fd(1, 1, "翠鸟号起航，翠鸟号返航", "翠鸟号出港，翠鸟号返航"), two, r)[0]
    # forbid: a character the original already had may stay; a new one may not come in
    r = _rules()
    quoted = seg('他说"好"，然后走了。')
    assert review.check(_fd(1, 1, '他说"好"', '他说"行"'), quoted, r)[0]
    assert review.check(_fd(1, 1, "然后走了", '然后"走"了'), quoted, r)[1] == "forbid_char"


def test_group_id_keeps_hyphen_and_underscore(tmp_path, make_project):
    assert review.group_of("/r/findings_codex-1.jsonl") == "codex-1"
    assert review.group_of("findings_ch11_b.pre.jsonl") == "ch11_b"
    assert review.group_of("verdicts_g1.auto.jsonl") == "g1"
    assert review.group_of("flags_g12.jsonl") == "g12"
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    src = tmp_path / "ext.json"
    src.write_text(json.dumps([{"i": 1, "offending": "二", "proposed": "贰", "sev": 2}], ensure_ascii=False), encoding="utf-8")
    assert review.main(["import", cache, str(src), "--group", "codex-1"]) == 0
    assert review.main(["pre", cache, paths.f("findings_codex-1.jsonl")]) == 0
    assert os.path.exists(paths.f("findings_codex-1.pre.jsonl"))
    assert review.final(paths, review.load_rules(paths), ["codex-1"])[0]["review"] == 1   # no Challenger: human list


def test_final_rerun_does_not_pile_up_rejects(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 1, "二", "贰"), _fd(2, 2, "六", "陆"), _fd(3, 3, "九", "玖")], rejected=1)   # g1-003 fails the gate
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [{"id": "g1-001", "verdict": "reject", "reason": "fine"},
                                                     {"id": "g1-002", "verdict": "accept", "reason": "ok"}])
    for _ in range(3):
        assert review.final(paths, rules, ["g1"])[0]["rejected"] == 1
    rows = review.read_jsonl(paths.f("rejected_g1.jsonl"))
    assert sorted((r["id"], r["_reject"]) for r in rows) == [("g1-001", "challenger:fine"), ("g1-003", "ambiguous(0)")]


def test_final_rerun_keeps_a_gate_reject_that_shares_an_id(tmp_path, make_project):
    cache, paths, rules = _group(tmp_path, make_project, [
        _fd(1, 3, "九", "玖"),                           # fails the gate …
        _fd(1, 1, "二", "贰")], rejected=1)              # … and a later finding reuses its id
    review.write_jsonl(paths.f("verdicts_g1.jsonl"), [{"id": "g1-001", "verdict": "reject", "reason": "fine"}])
    for _ in range(3):
        review.final(paths, rules, ["g1"])
    rows = review.read_jsonl(paths.f("rejected_g1.jsonl"))
    assert [(r["id"], r["_reject"]) for r in rows] == [("g1-001", "ambiguous(0)"), ("g1-001", "challenger:fine")]


def test_import_clamps_severity_to_the_gate_scale(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    paths = review.Paths(cache)
    src = tmp_path / "ext.jsonl"
    review.write_jsonl(str(src), [
        {"text_index": 1, "offending": "二", "proposed": "贰", "severity": 5},
        {"text_index": 2, "offending": "六", "proposed": "陆", "sev": "4"},
        {"text_index": 3, "offending": "七", "proposed": "柒", "severity": "critical"},
        {"text_index": 1, "offending": "三", "proposed": "叁", "severity": 0.4}])
    assert review.main(["import", cache, str(src), "--group", "x"]) == 0
    got = review.read_jsonl(paths.f("findings_x.jsonl"))
    assert [(f["severity"], f["category"]) for f in got] == [(3, "A"), (3, "A"), (1, "C"), (1, "C")]
    res = review.pre(paths, review.load_rules(paths), [paths.f("findings_x.jsonl")])[0]
    assert (res["ok"], res["rejected"]) == (4, 0)                 # the gravest findings are not the ones thrown out
    assert review.read_jsonl(paths.f("findings_x.pre.jsonl"))[0]["severity"] == 3
    # dual-merge ranks by the same scale and does not choke on a non-numeric sev
    a = tmp_path / "opus_1.jsonl"
    review.write_jsonl(str(a), [{"i": 1, "sev": 5, "issue": "x"}, {"i": 2, "sev": "high", "issue": "y"}])
    out = tmp_path / "fix_input.json"
    review.dual_merge(cache, [str(a)], str(out))
    assert [(r["i"], r["maxsev"]) for r in json.load(open(out, encoding="utf-8"))] == [(1, 3), (2, 1)]


def test_inventory_with_a_glossary_larger_than_the_regex_cache(tmp_path, make_project):
    cache = _project_dir(tmp_path, make_project)
    locked = os.path.join(os.path.dirname(cache), "glossary.locked.json")
    with open(locked, "w", encoding="utf-8") as f:
        json.dump({"terms": [{"src": f"filler{n}", "dst": "x"} for n in range(600)]
                            + [{"src": "four", "dst": "四"}, {"src": "ve", "dst": "x"}]}, f, ensure_ascii=False)
    paths = review.Paths(cache)
    os.makedirs(paths.dir)
    inv = review.inventory(paths, 1, 3, locked, min_count=1)
    by = {t["src"]: t["segments"] for t in inv["terms"]}
    assert by["four"] == [2] and "ve" not in by and not any(k.startswith("filler") for k in by)   # whole words only
