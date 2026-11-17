from ainiee_translate import cache_io


def test_save_then_load_roundtrip(make_project, tmp_path):
    proj = make_project(sources=["Hello", "World"], project_id="t1",
                        project_type="Txt", project_name="demo")
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    loaded = cache_io.load_cache(str(p))
    items = list(cache_io.iter_items(loaded))
    assert [it.text_index for it in items] == [1, 2]
    assert items[0].source_text == "Hello"


def test_iter_untranslated_and_set_translation(make_project, tmp_path):
    proj = make_project(sources=["Hello", "World"], project_id="t1",
                        project_type="Txt", project_name="demo")
    todo = list(cache_io.iter_untranslated(proj))
    assert len(todo) == 2
    cache_io.set_translation(proj, 1, "你好")
    todo = list(cache_io.iter_untranslated(proj))
    assert [it.text_index for it in todo] == [2]   # 1 now TRANSLATED
    done = next(cache_io.iter_items(proj))
    assert done.translated_text == "你好" and done.translation_status == 1


def test_rejected_or_unchanged_write_leaves_backups_alone(make_project, tmp_path, monkeypatch):
    from ainiee_translate import batch
    monkeypatch.setenv("AINIEE_BACKUP_KEEP", "2")
    proj = make_project(sources=["<i>one</i> two", "three"], project_id="t")
    p = str(tmp_path / "cache.json")
    cache_io.save_cache(proj, p)
    assert batch.write_back(p, [{"text_index": 2, "translated_text": "三"}]).applied == 1
    good = sorted(tmp_path.glob("cache.json.bak.*"))
    assert len(good) == 1                                       # the restore point: before anything was written
    before = (tmp_path / "cache.json").read_bytes()
    for _ in range(5):                                          # a bad file retried: the gate rejects every row
        res = batch.write_back(p, [{"text_index": 1, "translated_text": "一 二"}])
        assert res.applied == 0 and res.rejected[0]["reason"] == "tag_mismatch"
    assert batch.apply_rows(p, [{"text_index": 2, "translated_text": "三"}]).applied == 1   # same text again
    assert sorted(tmp_path.glob("cache.json.bak.*")) == good    # nothing rotated the restore point away
    assert (tmp_path / "cache.json").read_bytes() == before


def test_import_takes_the_cache_lock(make_project, tmp_path):
    import threading
    import time
    from ainiee_translate import project
    proj = make_project(n=2, project_id="t")
    src = tmp_path / "src.json"
    cache_io.save_cache(proj, str(src))
    project.import_cache(str(src), str(tmp_path / "proj"))
    dst = str(tmp_path / "proj" / "work" / "cache.json")
    done = []
    with cache_io.locked(dst):                                  # a write-back in flight
        t = threading.Thread(target=lambda: done.append(project.import_cache(str(src), str(tmp_path / "proj"))))
        t.start()
        time.sleep(0.3)
        assert not done                                         # import waits for it
    t.join(5)
    assert done and done[0]["total"] == 2
