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
