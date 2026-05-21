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
