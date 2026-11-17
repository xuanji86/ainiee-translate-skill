from ainiee_translate import cache_io, batch


def test_read_batch_returns_untranslated_slice(make_project):
    proj = make_project(n=5, project_id="t")
    b = batch.read_batch(proj, size=3)
    assert [x["text_index"] for x in b] == [1, 2, 3]
    assert b[0]["source_text"] == "line 1"


def test_write_back_applies_and_advances(make_project, tmp_path):
    proj = make_project(n=5, project_id="t")
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    batch.write_back(str(p), [{"text_index": 1, "translated_text": "译1"},
                              {"text_index": 2, "translated_text": "译2"}])
    proj2 = cache_io.load_cache(str(p))
    remaining = batch.read_batch(proj2, size=10)
    assert [x["text_index"] for x in remaining] == [3, 4, 5]
    assert (tmp_path / "cache.json").exists()
    # a timestamped backup was written next to the cache
    assert list(tmp_path.glob("cache.json.bak.*"))


def test_cli_read_prints_json(make_project, tmp_path, capsys):
    import json
    proj = make_project(n=5, project_id="t")
    p = tmp_path / "cache.json"; cache_io.save_cache(proj, str(p))
    batch.main(["read", str(p), "--size", "2"])
    printed = json.loads(capsys.readouterr().out)
    assert [x["text_index"] for x in printed] == [1, 2]


def test_cli_write_applies_from_file(make_project, tmp_path):
    import json
    proj = make_project(n=5, project_id="t")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    tr = tmp_path / "tr.json"
    tr.write_text(json.dumps([{"text_index": 1, "translated_text": "译1"}]), encoding="utf-8")
    batch.main(["write", str(cache), str(tr)])
    proj2 = cache_io.load_cache(str(cache))
    remaining = batch.read_batch(proj2, size=10)
    assert 1 not in [x["text_index"] for x in remaining]   # item 1 now translated


def test_cli_write_missing_file_errors(make_project, tmp_path):
    import pytest
    proj = make_project(n=5, project_id="t")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    with pytest.raises(SystemExit):
        batch.main(["write", str(cache), str(tmp_path / "nope.json")])


def _rows(path, rows):
    import json
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return str(path)


def test_write_rejects_finished_segments_unless_overwrite(make_project, tmp_path, capsys):
    """A stale trans_N.jsonl must not put first-draft text back over a translated/polished segment."""
    from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus as S
    proj = make_project(n=3, project_id="t")
    cache_io.set_translation(proj, 1, "初译1")
    cache_io.set_polish(proj, 2, "润色2")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    stale = _rows(tmp_path / "trans_1.jsonl", [{"text_index": i, "translated_text": f"旧{i}"} for i in (1, 2, 3)])
    assert batch.main(["write", str(cache), stale, "--force"]) == 1          # --force is not the release
    out = capsys.readouterr().out
    assert "rejected #1: already_translated" in out and "rejected #2: already_polished" in out
    assert "batch apply" in out and "--overwrite" in out
    idx = cache_io.index_items(cache_io.load_cache(str(cache)))
    assert idx[1].translated_text == "初译1" and idx[2].translated_text == "润色2"
    assert idx[2].translation_status == S.POLISHED and idx[3].translated_text == "旧3"   # the fresh one landed
    dup = _rows(tmp_path / "dup.jsonl", [{"text_index": 3, "translated_text": "新3"}])
    proj = cache_io.load_cache(str(cache)); idx = cache_io.index_items(proj)
    idx[3].translation_status, idx[3].translated_text = S.UNTRANSLATED, ""
    cache_io.save_cache(proj, str(cache))
    assert batch.main(["write", str(cache), stale, dup, "--force"]) == 1       # #1/#2 still rejected
    assert cache_io.index_items(cache_io.load_cache(str(cache)))[3].translated_text == "新3"   # last one wins
    assert batch.main(["write", str(cache), stale, "--overwrite"]) == 0
    idx = cache_io.index_items(cache_io.load_cache(str(cache)))
    assert idx[2].translated_text == "旧2" and idx[2].translation_status == S.TRANSLATED


def test_write_and_apply_refuse_to_bring_back_a_protected_fix(make_project, tmp_path, capsys):
    proj = make_project(n=1, project_id="t")
    cache_io.set_translation(proj, 1, "他不计一切地冲了出去。")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    fix = _rows(tmp_path / "fix.jsonl", [{"text_index": 1, "translated_text": "他不顾安危地冲了出去。"}])
    assert batch.main(["apply", str(cache), fix, "--source", "user"]) == 0
    back = _rows(tmp_path / "back.jsonl", [{"text_index": 1, "translated_text": "他不计一切地冲出去了。"}])
    for argv in (["write", str(cache), back, "--overwrite", "--force"],
                 ["apply", str(cache), back], ["apply", str(cache), back, "--source", "adversarial"]):
        assert batch.main(argv) == 1
        assert "reverts_fix" in capsys.readouterr().out
    assert cache_io.index_items(cache_io.load_cache(str(cache)))[1].translated_text == "他不顾安危地冲了出去。"
    assert batch.main(["apply", str(cache), back, "--source", "editor"]) == 0      # a protected source may undo it
    assert cache_io.index_items(cache_io.load_cache(str(cache)))[1].translated_text == "他不计一切地冲出去了。"
