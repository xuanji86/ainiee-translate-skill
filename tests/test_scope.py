from ainiee_translate import cache_io, scope
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheFile import CacheFile
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem


def _book(files):
    f = CacheFile(storage_path="b.epub")
    i = 1
    for fid, lines in files:
        for ln in lines:
            f.items.append(CacheItem(text_index=i, source_text=ln, extra={"item_id": fid}))
            i += 1
    return CacheProject(files={"b.epub": f}, project_id="t")


BOOK = [("ncx", ["Warpath", "1"]), ("rev", ["Praise for the Work of X", "great"]), ("ded", ["For my mother."]),
        ("epig", ["What though the field be lost?"]), ("fm_1", ["Historian’s Note", "This story takes place…"]),
        ("part1", ["WHAT FATES IMPOSE"]), ("date1", ["JUNE 2380"]), ("ch_1", ["1", "Kira ran."]),
        ("ch_2", ["Chapter Two", "Vaughn ran."]), ("epi", ["Epilogue", "The end."]),
        ("bm_2", ["Acknowledgments", "Thanks."]), ("bm_3", ["About the Author", "He writes."])]


def test_classify_keeps_story_and_historians_note_only():
    rows = {r["id"]: r["keep"] for r in scope.plan(_book(BOOK))}
    assert [k for k, v in rows.items() if v] == ["ncx", "fm_1", "part1", "date1", "ch_1", "ch_2", "epi"]
    rows = {r["id"]: r["keep"] for r in scope.plan(_book(BOOK), keep={"epig"}, drop={"ncx"})}
    assert rows["epig"] and not rows["ncx"]


def test_apply_excludes_untranslated_only_unless_forced(tmp_path):
    proj = _book(BOOK)
    cache_io.set_translation(proj, 3, "书评已译")                  # rev line 1 already translated
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    res = scope.apply(str(p))
    assert res["skipped_translated"] == 1
    items = {it.text_index: it for it in cache_io.iter_items(cache_io.load_cache(str(p)))}
    assert items[3].translation_status == 1 and items[4].translation_status == 7   # rev: translated kept, rest excluded
    assert items[9].translation_status == 0                                         # Historian's Note untouched
    scope.apply(str(p), force=True)
    items = {it.text_index: it for it in cache_io.iter_items(cache_io.load_cache(str(p)))}
    assert items[3].translation_status == 7 and items[3].final_text == "书评已译"
