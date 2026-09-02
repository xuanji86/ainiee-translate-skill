import json
import os
import pytest
from ainiee_translate import cache_io, batch
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheFile import CacheFile
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem


def _epub_like(chapter_sizes, translated_prefix=0):
    """One CacheFile, items tagged with extra.item_id per chapter (like EpubReader)."""
    f = CacheFile(storage_path="book.epub")
    idx = 1
    for ch, n in enumerate(chapter_sizes, 1):
        for _ in range(n):
            it = CacheItem(text_index=idx, source_text=f"ch{ch} line {idx}", extra={"item_id": f"ch{ch:02d}.xhtml"})
            if idx <= translated_prefix:
                it.translated_text, it.translation_status = f"译{idx}", 1
            f.items.append(it)
            idx += 1
    return CacheProject(files={"book.epub": f}, project_id="t")


def test_plan_groups_respects_chapter_boundaries_and_target():
    proj = _epub_like([150, 150, 150, 50])
    groups = batch.plan_groups(proj, target=300)
    assert [len(g["items"]) for g in groups] == [300, 200]
    assert groups[0]["chapters"] == ["ch01.xhtml", "ch02.xhtml"]
    assert groups[1]["chapters"] == ["ch03.xhtml", "ch04.xhtml"]


def test_plan_groups_chunks_oversized_chapter_and_skips_translated():
    proj = _epub_like([700], translated_prefix=100)
    groups = batch.plan_groups(proj, target=300)
    assert sum(len(g["items"]) for g in groups) == 600           # 100 already translated
    assert all(len(g["items"]) <= 300 for g in groups)
    assert groups[0]["items"][0].text_index == 101


def test_plan_groups_without_structure_uses_fixed_chunks(make_project):
    proj = make_project(n=250, project_id="t")                     # txt: no item_id, single file
    groups = batch.plan_groups(proj, target=100)
    sizes = [len(g["items"]) for g in groups]
    assert len(sizes) == 3 and sum(sizes) == 250 and max(sizes) <= 100


def test_split_cli_writes_src_and_ctx_files(tmp_path, capsys):
    proj = _epub_like([40, 40], translated_prefix=40)
    cache = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(cache))
    out = tmp_path / "par"
    batch.main(["split", str(cache), "--target", "30", "--out-dir", str(out), "--context", "5"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["pending"] == 40 and len(plan["groups"]) == 1
    src = json.load(open(out / "grp_1_src.json", encoding="utf-8"))
    assert [r["text_index"] for r in src] == list(range(41, 81))
    ctx = json.load(open(out / "grp_1_ctx.json", encoding="utf-8"))
    assert [r["text_index"] for r in ctx] == [36, 37, 38, 39, 40]
    assert ctx[-1]["translated_text"] == "译40"


def test_split_ctx_prefers_translated_segments_behind_a_pending_group(tmp_path, capsys):
    # ch1 translated, ch2 + ch3 pending: ch3's context must reach back past ch2 to ch1's translations
    proj = _epub_like([30, 30, 30], translated_prefix=30)
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    out = tmp_path / "par"
    batch.main(["split", str(cache), "--target", "30", "--out-dir", str(out), "--context", "5"])
    capsys.readouterr()
    ctx3 = json.load(open(out / "grp_2_ctx.json", encoding="utf-8"))
    assert [r["text_index"] for r in ctx3] == [26, 27, 28, 29, 30]
    assert all(r["translated_text"] for r in ctx3)


def test_validate_reports_missing_and_tag_mismatch():
    src = [{"text_index": 1, "source_text": "<i>A</i> b"}, {"text_index": 2, "source_text": "c"}]
    good = [{"text_index": 1, "translated_text": "<i>甲</i> 乙"}, {"text_index": 2, "translated_text": "丙"}]
    assert batch.validate(src, good)["ok"]
    bad = [{"text_index": 1, "translated_text": "甲 乙"}]
    rep = batch.validate(src, bad)
    kinds = {h["kind"] for h in rep["hard"]}
    assert kinds == {"missing_index", "segment"}
    assert not rep["ok"]


def test_write_many_files_jsonl_gate_and_single_backup(make_project, tmp_path):
    proj = make_project(sources=["<i>one</i> two", "three", "four", "five"], project_id="t")
    cache = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(cache))
    a = tmp_path / "a.json"
    a.write_text(json.dumps([{"text_index": 1, "translated_text": "一 二"},          # tag mismatch -> rejected
                             {"text_index": 2, "translated_text": ""}]), encoding="utf-8")   # empty -> rejected
    b = tmp_path / "b.jsonl"
    b.write_text('{"text_index": 3, "translated_text": "三"}\n\n{"text_index": 99, "translated_text": "x"}\n',
                 encoding="utf-8")
    rc = batch.main(["write", str(cache), str(a), str(b)])
    assert rc == 1
    proj2 = cache_io.load_cache(str(cache))
    assert [x["text_index"] for x in batch.read_batch(proj2, size=10)] == [1, 2, 4]
    assert len(list(tmp_path.glob("cache.json.bak.*"))) == 1        # one backup for the whole write
    assert not list(tmp_path.glob("cache.json.tmp.*"))              # atomic save left no temp file
    # --force writes the tag-mismatch item, still never an unknown index
    rc = batch.main(["write", str(cache), str(a), "--force"])
    proj3 = cache_io.load_cache(str(cache))
    assert [x["text_index"] for x in batch.read_batch(proj3, size=10)] == [4]   # item 2 (empty) forced through too


def test_write_rejects_duplicate_index_across_files(make_project, tmp_path):
    proj = make_project(n=2, project_id="t")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    a = tmp_path / "a.json"; a.write_text(json.dumps([{"text_index": 1, "translated_text": "甲"}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        batch.main(["write", str(cache), str(a), str(a)])


def test_backup_retention(make_project, tmp_path, monkeypatch):
    monkeypatch.setenv("AINIEE_BACKUP_KEEP", "2")
    proj = make_project(n=6, project_id="t")
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    (tmp_path / "cache.json.pre_manual").write_text("keep me", encoding="utf-8")
    for i in range(1, 5):
        batch.write_back(str(cache), [{"text_index": i, "translated_text": f"译{i}"}])
    assert len(list(tmp_path.glob("cache.json.bak.*"))) == 2
    assert (tmp_path / "cache.json.pre_manual").exists()            # manual backups untouched


def test_split_polish_stage_carries_translation_and_stage_marker(tmp_path, capsys):
    proj = _epub_like([30, 30], translated_prefix=30)          # ch1 translated, ch2 pending
    cache = tmp_path / "cache.json"; cache_io.save_cache(proj, str(cache))
    out = tmp_path / "pol"
    batch.main(["split", str(cache), "--stage", "polish", "--target", "30", "--out-dir", str(out), "--context", "0"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["stage"] == "polish" and plan["pending"] == 30           # only the translated chapter
    rows = json.load(open(out / "grp_1_src.json", encoding="utf-8"))
    assert rows[0]["text_index"] == 1 and rows[0]["translated_text"] == "译1"
    assert json.load(open(out / "_stage.json", encoding="utf-8"))["stage"] == "polish"


def test_validate_accepts_polished_text_rows():
    src = [{"text_index": 1, "source_text": "<i>A</i> b", "translated_text": "<i>甲</i> 乙"}]
    assert batch.validate(src, [{"text_index": 1, "polished_text": "<i>甲</i>乙。"}])["ok"]
    rep = batch.validate(src, [{"text_index": 1, "polished_text": "甲乙。"}])
    assert not rep["ok"] and rep["hard"][0]["kind"] == "segment"
