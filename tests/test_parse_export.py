import os
from ainiee_translate import parse, export, cache_io

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "input_txt")
MARKER = "译:"


def test_txt_parse_translate_export_roundtrip(tmp_path):
    """End-to-end through the public parse/export API — fully self-contained
    (no AINIEE_REPO; uses the vendored TxtReader/TxtWriter)."""
    cache_path = tmp_path / "cache.json"
    proj = parse.parse_input(FIX, "Txt")
    cache_io.save_cache(proj, str(cache_path))
    assert proj.count_items() >= 2

    proj = cache_io.load_cache(str(cache_path))
    for it in cache_io.iter_items(proj):
        cache_io.set_translation(proj, it.text_index, MARKER + it.source_text)

    out = tmp_path / "out"
    out.mkdir()
    export.export_project(proj, str(out), FIX)
    produced = list(out.rglob("*.txt"))
    assert produced, "no output file produced"
    assert any(MARKER in p.read_text(encoding="utf-8") for p in produced), \
        "translation not found in any output file"


def test_parse_refuses_to_wipe_a_cache_with_translations(tmp_path, capsys):
    from ainiee_translate import io_dispatch
    cache = str(tmp_path / "cache.json")
    assert parse.main(["--input", FIX, "--type", "Txt", "--out", cache]) == 0
    assert parse.main(["--input", FIX, "--type", "Txt", "--out", cache]) == 0      # nothing translated yet: fine
    proj = cache_io.load_cache(cache)
    cache_io.set_translation(proj, 1, "译1")
    cache_io.save_cache(proj, cache)
    before = open(cache, "rb").read()
    for main in (parse.main, lambda a: io_dispatch.main(["parse", *a])):
        assert main(["--input", FIX, "--type", "Txt", "--out", cache]) == 1
        assert "already has 1 translated segment(s)" in capsys.readouterr().err
        assert open(cache, "rb").read() == before
    assert parse.main(["--input", FIX, "--type", "Txt", "--out", cache, "--force"]) == 0
    baks = list(tmp_path.glob("cache.json.bak.*"))
    assert len(baks) == 1 and baks[0].read_bytes() == before
    assert cache_io.index_items(cache_io.load_cache(cache))[1].translated_text in (None, "")


def test_parse_with_no_items_fails_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AINIEE_REPO", raising=False)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    cache = tmp_path / "cache.json"
    assert parse.main(["--input", str(pdf), "--out", str(cache)]) == 1
    assert "no translatable items" in capsys.readouterr().err and not cache.exists()
