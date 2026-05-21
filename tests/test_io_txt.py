from ainiee_translate import io_dispatch, cache_io


def test_txt_roundtrip(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("Hello\n\nWorld\n", encoding="utf-8")        # blank line between
    proj = io_dispatch.parse_input(str(src))
    assert proj.project_type == "Txt"
    assert proj.count_items() == 2                              # blank line not a segment
    for it in cache_io.iter_items(proj):
        cache_io.set_translation(proj, it.text_index, it.source_text + "!")
    out = tmp_path / "out"
    io_dispatch.export_project(proj, str(out), str(src))
    translated = (out / "a_translated.txt").read_text(encoding="utf-8")
    assert "Hello!" in translated and "World!" in translated
    assert "\n\n" in translated                                # blank-line spacing preserved
    assert (out / "bilingual_txt").is_dir()
