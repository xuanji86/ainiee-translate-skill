from ainiee_translate import cache_io, scope
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheFile import CacheFile
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem


def _book(files):
    f = CacheFile(storage_path="b.epub")
    i = 1
    for fid, lines in files:
        for ln in lines:
            extra = {"item_id": fid, **({"tag_type": "ncx_text"} if fid == "ncx" else {})}
            f.items.append(CacheItem(text_index=i, source_text=ln, extra=extra))
            i += 1
    return CacheProject(files={"b.epub": f}, project_id="t")


BOOK = [("ncx", ["The Long Road", "1"]), ("rev", ["Praise for the Work of X", "great"]), ("ded", ["For my mother."]),
        ("epig", ["What though the field be lost?"]), ("fm_1", ["Historian’s Note", "This story takes place…"]),
        ("part1", ["WHAT THE TIDE BRINGS"]), ("date1", ["JUNE 1897"]), ("ch_1", ["1", "Mara ran."]),
        ("ch_2", ["Chapter Two", "Corin ran."]), ("epi", ["Epilogue", "The end."]),
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


def _prose(first, words):
    return [first + " " + " ".join(["wind"] * (words - len(first.split())))]


def test_for_opening_prose_is_story_and_continuation_looks_past_a_dropped_file():
    book = [("ded", ["For my mother."]), ("ch_1", ["1", "Mara ran."]),
            ("ch_1b", _prose("For a long moment Hale said nothing", 266)),      # prose, not a dedication
            ("ch_1c", _prose("Korin waited", 250)),
            ("ch_2", ["2", "Corin ran."]),
            ("ch_2a", _prose("For three days the", 150)),       # short "For …" — still read as a dedication…
            ("ch_2b", _prose("The airship drifted", 300)),       # …but the long file after it is story
            ("epi", ["Epilogue", "The end."]),
            ("app_1", ["Appendix I", "Ship classes."]),
            ("app_2", _prose("Ship registry", 224)),            # long, but behind back matter: not story
            ("bm_1", ["About the Author", "He writes."]),
            ("bm_2", _prose("Highmark Books presents", 233))]
    rows = {r["id"]: (r["keep"], r["why"]) for r in scope.plan(_book(book))}
    assert rows["ded"] == (False, "dedication")
    assert rows["ch_1b"] == (True, "story continuation") and rows["ch_1c"] == (True, "story continuation")
    assert rows["ch_2a"][0] is False and rows["ch_2b"] == (True, "story continuation")
    assert not any(rows[k][0] for k in ("app_1", "app_2", "bm_1", "bm_2"))


def test_skips_books_without_file_structure_or_latin_source(tmp_path, make_project, capsys):
    for proj, msg in ((make_project(sources=["For my mother.", "Thanks."]), "无文件结构"),   # one txt
                      (_book([("ded", ["献给我的母亲。"]), ("ch_1", ["第一章", "玛拉跑了。"])]), "只适用英文源文")):
        p = tmp_path / "cache.json"
        cache_io.save_cache(proj, str(p))
        before = p.read_bytes()
        assert scope.main([str(p), "--apply"]) == 0 and msg in capsys.readouterr().out
        assert scope.main([str(p)]) == 0 and msg in capsys.readouterr().out
        assert p.read_bytes() == before and not list(tmp_path.glob("cache.json.bak.*"))


def test_apply_keep_restores_excluded_untranslated_segments(tmp_path):
    proj = _book(BOOK)
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))
    scope.apply(str(p))                                                   # rev / ded / epig … excluded
    proj = cache_io.load_cache(str(p))
    rev = [it for it in cache_io.iter_items(proj) if it.extra["item_id"] == "rev"]
    rev[0].translated_text = "书评已译"                                    # an excluded segment that has text
    cache_io.save_cache(proj, str(p))
    res = scope.apply(str(p), keep={"rev"})
    assert res["restored"] == 1
    st = {it.text_index: (it.translation_status, it.translated_text)
          for it in cache_io.iter_items(cache_io.load_cache(str(p))) if it.extra["item_id"] == "rev"}
    assert [s for s, _ in st.values()] == [7, 0]                          # the one with text stays excluded
