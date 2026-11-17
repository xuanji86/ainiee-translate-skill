import json
from ainiee_translate import cache_io, batch, polish


def test_read_translated_returns_only_translated(make_project, tmp_path):
    proj = make_project(n=3, project_id="t")
    cache_io.set_translation(proj, 1, "译1")
    cache_io.set_translation(proj, 2, "译2")
    got = batch.read_translated_batch(proj, size=10)
    assert [x["text_index"] for x in got] == [1, 2]          # untranslated #3 excluded
    assert got[0]["translated_text"] == "译1"


def test_polish_write_sets_polished_and_resumes(make_project, tmp_path):
    proj = make_project(n=3, project_id="t")
    cache_io.set_translation(proj, 1, "译1")
    cache_io.set_translation(proj, 2, "译2")
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    # polish item 1
    pj = tmp_path / "polished.json"
    pj.write_text(json.dumps([{"text_index": 1, "polished_text": "润色1"}]), encoding="utf-8")
    polish.main(["write", str(p), str(pj)])
    proj2 = cache_io.load_cache(str(p))
    # item 1 now POLISHED (excluded from resume); item 2 still pending polish
    remaining = batch.read_translated_batch(proj2, size=10)
    assert [x["text_index"] for x in remaining] == [2]
    polished_item = next(i for i in cache_io.iter_items(proj2) if i.text_index == 1)
    assert polished_item.translated_text == "润色1"
    assert list(tmp_path.glob("cache.json.bak.*"))           # backup written


def test_polish_write_rejects_reverting_a_protected_fix_even_forced(make_project, tmp_path, capsys):
    """Polish groups cut before a user fix must not write the old wording back over it."""
    proj = make_project(n=2, project_id="t")
    cache_io.set_translation(proj, 1, "她不恨 Marlow 做的事。")
    cache_io.set_translation(proj, 2, "译2")
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    fix = tmp_path / "fix.json"
    fix.write_text(json.dumps([{"text_index": 1, "translated_text": "她并不因此恨 Marlow。"}]), encoding="utf-8")
    assert batch.main(["apply", str(p), str(fix), "--source", "user"]) == 0
    pj = tmp_path / "polished_1.json"
    pj.write_text(json.dumps([{"text_index": 1, "polished_text": "她不恨 Marlow 做的事。"},
                              {"text_index": 2, "polished_text": "润色2"}]), encoding="utf-8")
    assert polish.main(["write", str(p), str(pj), "--force"]) == 1
    assert "rejected #1: reverts_fix" in capsys.readouterr().out
    idx = cache_io.index_items(cache_io.load_cache(str(p)))
    assert idx[1].translated_text == "她并不因此恨 Marlow。" and idx[2].translated_text == "润色2"
