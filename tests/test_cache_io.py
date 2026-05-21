from ainiee_translate import cache_io

def _mini_project(ainiee_repo):
    from ainiee_translate.ainiee_lib import load
    m = load()
    from ModuleFolders.Service.Cache.CacheFile import CacheFile
    proj = m.CacheProject(project_id="t1", project_type="Txt", project_name="demo")
    f = CacheFile(storage_path="a.txt")
    f.items = [m.CacheItem(text_index=1, source_text="Hello"),
               m.CacheItem(text_index=2, source_text="World")]
    proj.files = {"a.txt": f}
    return proj

def test_save_then_load_roundtrip(ainiee_repo, tmp_path):
    proj = _mini_project(ainiee_repo)
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    loaded = cache_io.load_cache(str(p))
    items = list(cache_io.iter_items(loaded))
    assert [it.text_index for it in items] == [1, 2]
    assert items[0].source_text == "Hello"

def test_iter_untranslated_and_set_translation(ainiee_repo, tmp_path):
    proj = _mini_project(ainiee_repo)
    todo = list(cache_io.iter_untranslated(proj))
    assert len(todo) == 2
    cache_io.set_translation(proj, 1, "你好")
    todo = list(cache_io.iter_untranslated(proj))
    assert [it.text_index for it in todo] == [2]   # 1 now TRANSLATED
    done = next(cache_io.iter_items(proj))
    assert done.translated_text == "你好" and done.translation_status == 1
