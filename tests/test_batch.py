from ainiee_translate import cache_io, batch


def _proj(ainiee_repo):
    from ainiee_translate.ainiee_lib import load
    m = load()
    from ModuleFolders.Service.Cache.CacheFile import CacheFile
    f = CacheFile(storage_path="a.txt")
    f.items = [m.CacheItem(text_index=i, source_text=f"line {i}") for i in range(1, 6)]
    return m.CacheProject(project_id="t", files={"a.txt": f})


def test_read_batch_returns_untranslated_slice(ainiee_repo):
    proj = _proj(ainiee_repo)
    b = batch.read_batch(proj, size=3)
    assert [x["text_index"] for x in b] == [1, 2, 3]
    assert b[0]["source_text"] == "line 1"


def test_write_back_applies_and_advances(ainiee_repo, tmp_path):
    proj = _proj(ainiee_repo)
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


def test_cli_read_prints_json(ainiee_repo, tmp_path, capsys):
    import json
    proj = _proj(ainiee_repo)
    p = tmp_path / "cache.json"; cache_io.save_cache(proj, str(p))
    batch.main(["read", str(p), "--size", "2"])
    printed = json.loads(capsys.readouterr().out)
    assert [x["text_index"] for x in printed] == [1, 2]


def test_cli_write_applies_from_file(ainiee_repo, tmp_path):
    import json
    proj = _proj(ainiee_repo)
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    tr = tmp_path / "tr.json"
    tr.write_text(json.dumps([{"text_index": 1, "translated_text": "译1"}]), encoding="utf-8")
    batch.main(["write", str(cache), str(tr)])
    proj2 = cache_io.load_cache(str(cache))
    remaining = batch.read_batch(proj2, size=10)
    assert 1 not in [x["text_index"] for x in remaining]   # item 1 now translated


def test_cli_write_missing_file_errors(ainiee_repo, tmp_path):
    import pytest
    proj = _proj(ainiee_repo)
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    with pytest.raises(SystemExit):
        batch.main(["write", str(cache), str(tmp_path / "nope.json")])
