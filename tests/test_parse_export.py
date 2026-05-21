def test_ainiee_lib_imports_types(ainiee_repo):
    from ainiee_translate import ainiee_lib
    mod = ainiee_lib.load()
    assert mod.FileReader is not None
    assert mod.FileOutputer is not None
    assert mod.TranslationStatus.TRANSLATED == 1
    assert mod.TranslationStatus.UNTRANSLATED == 0


import os
from ainiee_translate import parse, export, cache_io

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "input_txt")

MARKER = "译:"


def test_txt_parse_translate_export_roundtrip(ainiee_repo, tmp_path):
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


def test_export_seeds_writer_config_when_missing(ainiee_repo):
    """export._ensure_writer_config() must set keep_original_encoding even when
    no ambient config.json exists — the round-trip must be self-sufficient."""
    import sys
    from ainiee_translate.ainiee_lib import repo_path
    repo = repo_path()
    if repo not in sys.path:
        sys.path.insert(0, repo)

    from ModuleFolders.Domain.FileOutputer import WriterUtil

    # Reset the singleton so we get a clean slate for this test
    WriterUtil.release_ainiee_config()
    cfg = WriterUtil.get_ainiee_config()

    # Simulate a clean machine: wipe the attribute if it was loaded from disk
    cfg.keep_original_encoding = None

    # Now call the helper — it must seed the attribute
    export._ensure_writer_config()

    cfg_after = WriterUtil.get_ainiee_config()
    assert hasattr(cfg_after, "keep_original_encoding"), \
        "_ensure_writer_config did not set keep_original_encoding"
    assert cfg_after.keep_original_encoding is not None, \
        "keep_original_encoding is still None after _ensure_writer_config"
