from ainiee_translate import cache_io, project


def test_import_places_cache_and_summarizes(make_project, tmp_path):
    proj = make_project(n=3, storage="book.epub", project_id="t",
                        project_name="Demo", input_path="/x/book.epub")
    cache_io.set_translation(proj, 1, "译1")
    src = tmp_path / "AinieeCacheData.json"
    cache_io.save_cache(proj, str(src))

    r = project.import_cache(str(src), str(tmp_path / "proj"))
    assert (tmp_path / "proj" / "work" / "cache.json").is_file()
    assert (r["total"], r["translated"], r["untranslated"]) == (3, 1, 2)
    assert r["input_path"] == "/x/book.epub"
    assert r["project_name"] == "Demo"

    # the imported cache is loadable and still exposes the untranslated remainder
    proj2 = cache_io.load_cache(str(tmp_path / "proj" / "work" / "cache.json"))
    assert sum(1 for _ in cache_io.iter_untranslated(proj2)) == 2


def test_import_backs_up_existing(make_project, tmp_path):
    proj = make_project(n=3, storage="book.epub", project_id="t",
                        project_name="Demo", input_path="/x/book.epub")
    src = tmp_path / "AinieeCacheData.json"
    cache_io.save_cache(proj, str(src))
    work = tmp_path / "proj"
    project.import_cache(str(src), str(work))
    project.import_cache(str(src), str(work))   # second import backs up the first
    assert list((work / "work").glob("cache.json.bak.*"))


def test_list_ainiee_scans_dir(make_project, tmp_path):
    proj = make_project(n=3, storage="book.epub", project_id="t",
                        project_name="Demo", input_path="/x/book.epub")
    pid = "abc123"
    (tmp_path / pid).mkdir()
    cache_io.save_cache(proj, str(tmp_path / pid / "AinieeCacheData.json"))
    got = project.list_ainiee(str(tmp_path))
    assert len(got) == 1
    assert got[0]["project_id"] == pid
    assert got[0]["project_name"] == "Demo"
    assert got[0]["total"] == 3
