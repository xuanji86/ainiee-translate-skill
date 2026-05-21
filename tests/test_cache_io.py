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
