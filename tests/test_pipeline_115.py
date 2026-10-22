"""1.15: unified apply + provenance, decisions.json, verify false positives, newterm renderings,
scope (contents / continuation / part subtitle), review run dirs / pick / import / dual-merge /
revert guard, cache helpers, pending-term scan, bundles."""
import json

from ainiee_translate import batch, cache, cache_io, glossary, review, scan, scope, state, verify
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus as S


def _save(tmp_path, proj):
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    return str(p)


def _item(path, i):
    return cache_io.index_items(cache_io.load_cache(path))[i]


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------ apply ----
def test_apply_keeps_status_takes_patches_and_records_provenance(tmp_path, make_project):
    proj = make_project(sources=["a", "b", "c", "d"])
    cache_io.set_translation(proj, 1, "她不恨 Marlow 做的事。")
    cache_io.set_polish(proj, 2, "润色过的句子。")
    p = _save(tmp_path, proj)
    fx = _jsonl(tmp_path / "fix.jsonl", [
        {"text_index": 1, "patches": [["她不恨 Marlow 做的事。", "她并不因此恨 Marlow。"]], "reason": "恨的对象是人"},
        {"text_index": 2, "polished_text": "再润色。"},
        {"text_index": 3, "translated_text": "新译。"},
        {"text_index": 4, "patches": [["不存在", "x"]]},
    ])
    assert batch.main(["apply", p, fx, "--source", "codex"]) == 1          # #4 rejected
    assert _item(p, 1).translated_text == "她并不因此恨 Marlow。" and _item(p, 1).translation_status == S.TRANSLATED
    assert _item(p, 2).translated_text == "再润色。" and _item(p, 2).translation_status == S.POLISHED   # no downgrade
    assert _item(p, 3).translation_status == S.TRANSLATED                                            # 0 -> 1
    assert _item(p, 4).translated_text in (None, "")
    hist = state.history(p)
    assert hist[1][0]["source"] == "codex" and hist[1][0]["reason"] == "恨的对象是人"
    assert any("做的事" in x for x in hist[1][0]["removed"])


def test_decisions_tag_exception_and_lint_rule(tmp_path, make_project):
    proj = make_project(sources=["<i>Halcyon</i> where?"])
    p = _save(tmp_path, proj)
    fx = _jsonl(tmp_path / "t.jsonl", [{"text_index": 1, "translated_text": "<i>翠鸟</i>号<i>在哪</i>？它们说"}])
    assert batch.main(["write", p, fx]) == 1                                # tag mismatch rejected
    state.main(["tag-exception", p, "1", "--reason", "舰名正体拆两段"])
    state.main(["lint-rule", p, "they", "--re", "它们说", "--msg", "demo"])
    res = batch.write_back(p, json.loads(open(fx).read().strip().join(["[", "]"])))
    assert res.applied == 1 and res.warnings.get("rule:they") == 1
    assert "标记数量例外" in state.card(p)


# ----------------------------------------------------------- verify ----
def test_verify_titles_modal_will_and_drop_caps():
    locked = {"characters": [{"render": "Elder Maren"}, {"render": "Will"}, {"render": "Ossa"},
                             {"render": "Arden of Vel"}, {"render": "Hale"}]}
    items = [
        {"text_index": 1, "translation_status": 1, "source_text": "Elder Maren spoke.", "translated_text": "Maren 长老开口了。"},
        {"text_index": 2, "translation_status": 1, "source_text": "“Will you think to it?”", "translated_text": "“你能想给它听吗？”"},
        {"text_index": 3, "translation_status": 1, "source_text": "<b>D</b>r. Ossa had been", "translated_text": "<b>O</b>ssa 医生已经"},
        {"text_index": 4, "translation_status": 1, "source_text": "Arden of Vel", "translated_text": "维尔的 Arden"},
        {"text_index": 5, "translation_status": 1, "source_text": "Hale nodded. Will smiled.", "translated_text": "黑尔点头。威尔笑了。"},
    ]
    got = {(i["text_index"], i["detail"].split(" in ")[0]) for i in verify.check_items(items, locked)}
    assert got == {(5, "Will"), (5, "Hale")}          # real transliterations still caught


def test_verify_baseline_hides_known(tmp_path, make_project, capsys):
    proj = make_project(sources=["Hale nodded."])
    cache_io.set_translation(proj, 1, "黑尔点头。")
    p = _save(tmp_path, proj)
    gl = tmp_path / "g.json"; gl.write_text(json.dumps({"characters": [{"render": "Hale"}]}), encoding="utf-8")
    base = str(tmp_path / "base.json")
    verify.main([p, str(gl), "--write-baseline", base])
    capsys.readouterr()
    verify.main([p, str(gl), "--baseline", base])
    out = capsys.readouterr()
    assert out.out == "" and "1 known in baseline hidden" in out.err


# --------------------------------------------------------- glossary ----
def test_newterms_renderings_and_conflicts():
    assert glossary.parse_newterm("skimmers\t掠空兽") == ("skimmers", "掠空兽")
    assert glossary.parse_newterm("Varn") == ("Varn", "Varn")
    c = glossary.newterm_conflicts({"h4": [("skimmers", "掠空兽")], "h5": [("Skimmers", "掠兽")], "h6": [("Merrow", "Merrow")]})
    assert set(c) == {"skimmers"}
    locked = {"characters": [], "terms": []}
    added, _ = glossary.merge_newterms(locked, [("Karth Prison", "Karth 监狱"), ("Brann", "Brann")])
    t = {x["src"]: x for x in locked["terms"]}
    assert not t["Karth Prison"]["keep_source"] and t["Karth Prison"]["dst"] == "Karth 监狱"
    assert t["Brann"]["keep_source"]


# ------------------------------------------------------------ scope ----
def _book(make_project, files):
    srcs = [s for _, rows in files for s in rows]
    proj = make_project(sources=srcs)
    items = list(cache_io.iter_items(proj))
    k = 0
    for fid, rows in files:
        for _ in rows:
            items[k].extra = {"item_id": fid}
            k += 1
    return proj


def test_scope_contents_continuation_and_part_subtitle(tmp_path, make_project):
    prose = " ".join(["word"] * 250)
    proj = _book(make_project, [
        ("toc", ["Contents", "Chapter One"]),
        ("p1", ["Part One"]),
        ("sub", ["The Long Road", "<i>Beneath the sky’s arch</i>"]),
        ("c1", ["Chapter One", prose]),
        ("body", ["NORTH WATCH CAMP, DAY 47", prose]),
        ("ack", ["Acknowledgments", "Thanks"]),
    ])
    p = _save(tmp_path, proj)
    rows = {r["id"]: (r["keep"], r["why"]) for r in scope.plan(cache_io.load_cache(p))}
    assert rows["toc"] == (True, "table of contents")
    assert rows["sub"] == (True, "part subtitle")
    assert rows["body"] == (True, "story continuation")
    assert rows["ack"][0] is False
    scope.apply(p)
    st = {it.text_index: it.translation_status for it in cache_io.iter_items(cache_io.load_cache(p))}
    assert st[4] == S.UNTRANSLATED and st[5] == S.EXCLUDED          # subtitle kept, epigraph out


# ------------------------------------------------------------ cache ----
def test_cache_fill_dupes_and_set_status(tmp_path, make_project):
    proj = make_project(sources=["Chapter Eleven", "Long prose here.", "Chapter Eleven"])
    cache_io.set_translation(proj, 1, "第十一章")
    items = cache_io.index_items(proj)
    items[3].translation_status = S.EXCLUDED
    items[2].translation_status = S.EXCLUDED
    p = _save(tmp_path, proj)
    cache.main(["fill-dupes", p, "--apply"])
    assert _item(p, 3).translated_text == "第十一章" and _item(p, 3).translation_status == S.TRANSLATED
    cache.main(["set-status", p, "--range", "2-2", "--from", "7", "--to", "0", "--apply"])
    assert _item(p, 2).translation_status == S.UNTRANSLATED


def test_scan_pending_terms_ranks_new_clustered_words():
    items = [{"text_index": i, "translation_status": 1, "source_text": "The ship circled on.", "translated_text": "x"}
             for i in range(1, 60)]
    items += [{"text_index": 100 + i, "translation_status": 0, "source_text": "The skimmers circled the ship.",
               "translated_text": ""} for i in range(6)]                       # clustered: a new creature
    items += [{"text_index": 200 + 60 * i, "translation_status": 0, "source_text": "A proposal, the ship.",
               "translated_text": ""} for i in range(6)]                       # spread out: plain vocabulary
    got = [r["token"] for r in scan.find_pending_terms(items, None, min_count=3)]
    assert got[0] == "skimmers" and "ship" not in got and "circled" not in got


# ----------------------------------------------------------- review ----
def test_review_run_dir_pick_min_sev_exclude_import_and_revert_guard(tmp_path, make_project):
    proj = make_project(sources=["one", "two"])
    cache_io.set_translation(proj, 1, "第一句不计一切地说。")
    cache_io.set_translation(proj, 2, "第二句话的的的。")
    p = _save(tmp_path, proj)
    (tmp_path / "review").mkdir()
    (tmp_path / "review" / "config.json").write_text(json.dumps({"forbid": "X"}), encoding="utf-8")
    paths = review.Paths(p, run="r2")
    assert review.load_rules(paths).forbid.pattern == "X"                # shared root config
    ext = _jsonl(tmp_path / "codex.jsonl", [
        {"text_index": 1, "current": "不计一切", "fix": "不计前嫌", "sev": 2, "issue": "反了"},
        {"text_index": 2, "offending": "的的的", "proposed": "的", "severity": 1}])
    review.import_findings(paths, ext, "x", "codex")
    review.pre(paths, review.load_rules(paths), [paths.f("findings_x.jsonl")])
    review.pick(paths, review.load_rules(paths), [], ["x"], min_sev=1, exclude=["x-002"])
    rows = json.load(open(paths.f("apply_pick.json"), encoding="utf-8"))
    assert [r["text_index"] for r in rows] == [1]
    batch.apply_rows(p, rows, source="codex", reason="in spite of everything")
    # a later pass may not bring the removed wording back
    back = {"id": "y-001", "text_index": 1, "category": "C", "offending": "不计前嫌", "proposed": "不计一切"}
    seg = {"source_text": "one", "translated_text": _item(p, 1).translated_text}
    assert review.check(back, seg, review.load_rules(paths))[1] == "E_reverts_fix"


def test_dual_merge_puts_agreed_segments_first(tmp_path, make_project):
    proj = make_project(sources=["a", "b"])
    cache_io.set_translation(proj, 1, "甲"); cache_io.set_translation(proj, 2, "乙")
    p = _save(tmp_path, proj)
    o = _jsonl(tmp_path / "opus_h1.jsonl", [{"i": 1, "sev": 1, "issue": "x"}, {"i": 2, "sev": 2, "issue": "y"}])
    f = _jsonl(tmp_path / "fable_h1.jsonl", [{"i": 2, "sev": 1, "issue": "z"}])
    out = str(tmp_path / "fix_input.json")
    rep = review.dual_merge(p, [o, f], out)
    rows = json.load(open(out, encoding="utf-8"))
    assert rows[0]["i"] == 2 and rows[0]["agree"] == 2 and rep["agree>1"] == 1


# ----------------------------------------------------------- bundle ----
def test_bundle_has_card_glossary_and_rows(tmp_path, make_project):
    proj = make_project(sources=["The airship hummed.", "Hale left."])
    p = _save(tmp_path, proj)
    state.main(["settle", p, "--dst", "飞艇", "--src", "airship"])
    gl = tmp_path / "glossary.locked.json"
    gl.write_text(json.dumps({"characters": [{"render": "Hale"}], "terms": [{"src": "airship", "dst": "飞艇"}]}),
                  encoding="utf-8")
    src = tmp_path / "grp_h1_src.json"
    src.write_text(json.dumps([{"text_index": 1, "source_text": "The airship hummed."}]), encoding="utf-8")
    batch.main(["bundle", p, str(src)])
    txt = (tmp_path / "bundle_h1.md").read_text(encoding="utf-8")
    assert "airship → 飞艇" in txt and "airship\t飞艇" in txt
    assert "Hale" not in txt                                 # glossary sliced to this group's source
    assert "trans_h1.jsonl" in txt and '"text_index": 1' in txt


# --------------------------------------------------------- finalize ----
def test_finalize_sets_metadata_fixed_identifier_and_checks_paragraphs(tmp_path, make_project):
    from zipfile import ZipFile
    from ainiee_translate import finalize
    proj = make_project(sources=["Hello."])
    cache_io.set_translation(proj, 1, "<i>你好</i>。")
    p = _save(tmp_path, proj)
    epub = tmp_path / "in.epub"
    with ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
        z.writestr("OEBPS/c.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Hi</dc:title><dc:language>en</dc:language><dc:identifier id="uid">old</dc:identifier></metadata><manifest><item id="ncx" href="t.ncx"/><item id="a" href="a.xhtml"/></manifest><spine toc="ncx"><itemref idref="a"/></spine></package>')
        z.writestr("OEBPS/t.ncx", '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><head><meta name="dtb:uid" content="old"/></head><docTitle><text>Hi</text></docTitle><navMap><navPoint><content src="a.xhtml#p1"/></navPoint></navMap></ncx>')
        z.writestr("OEBPS/a.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><p id="p1"><span>你好</span>。</p></body></html>')
    cfg = finalize.load_config(p, {"title": "你好书"})
    rep = finalize.finalize(str(epub), str(tmp_path / "out.epub"), p, dict(cfg, deliver=str(tmp_path / "chn" / "x.epub")))
    assert rep["paragraphs_verified"] == 1 and (tmp_path / "chn" / "x.epub").exists()
    with ZipFile(tmp_path / "out.epub") as z:
        assert z.namelist()[0] == "mimetype"
        opf = z.read("OEBPS/c.opf").decode()
    assert "你好书" in opf and "zh-CN" in opf and cfg["identifier"] in opf
    assert finalize.load_config(p)["identifier"] == cfg["identifier"]          # fixed across exports


def test_review_gate_honors_tag_exceptions(tmp_path, make_project):
    proj = make_project(sources=["<i>Halcyon</i> crew"])
    cache_io.set_translation(proj, 1, "<i>翠鸟号</i>和<i>翠鸟号</i>的船员们")
    p = _save(tmp_path, proj)
    f = {"id": "g-1", "text_index": 1, "category": "C", "offending": "的船员们", "proposed": "船员"}
    seg = {"source_text": "<i>Halcyon</i> crew", "translated_text": _item(p, 1).translated_text}
    paths = review.Paths(p)
    assert review.check(f, seg, review.load_rules(paths))[1] == "tag:tag_mismatch"
    state.main(["tag-exception", p, "1", "--reason", "舰名出现两次"])
    assert review.check(f, seg, review.load_rules(paths))[0]
