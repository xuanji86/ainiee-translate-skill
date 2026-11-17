"""`cache fill-dupes` with epub link/anchor placeholders: a contents entry `⟦1⟧Chapter One⟦/1⟧⟦2⟧`, the ncx
label `Chapter One` and the body heading `⟦1⟧Chapter One` are the same title; the copy keeps each
target's own placeholders so it passes the write gate and the exported contents links survive."""
import json
import zipfile

from ainiee_translate import audit, batch, cache, cache_io, export, parse
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus as S

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Halcyon</dc:title>
    <dc:language>en</dc:language><dc:identifier id="uid">x-1</dc:identifier></metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="contents" href="contents.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="contents"/><itemref idref="ch1"/></spine>
</package>"""
NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="x-1"/></head>
  <docTitle><text>Halcyon</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1"><navLabel><text>Chapter One</text></navLabel><content src="ch1.xhtml"/></navPoint>
  </navMap>
</ncx>"""
CONTENTS = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Contents</title></head>
<body><p><a href="ch1.xhtml">Chapter One</a></p>
<p><a href="ch1.xhtml">Chapter One</a><sup><a href="ch1.xhtml#n1" id="r1">1</a></sup></p></body></html>"""
CH1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter One</title></head>
<body><h1><a id="c1"></a>Chapter One</h1><p>Marlow sailed.</p></body></html>"""


def _epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/toc.ncx", NCX)
        z.writestr("OEBPS/contents.xhtml", CONTENTS)
        z.writestr("OEBPS/ch1.xhtml", CH1)
    return str(path)


def _rows(path):
    return [(it.source_text, it.translated_text, it.translation_status) for it in cache_io.iter_items(cache_io.load_cache(path))]


def test_fill_dupes_copies_a_title_across_ncx_contents_page_and_anchored_heading(tmp_path, capsys):
    epub = _epub(tmp_path / "book.epub")
    cache_path = str(tmp_path / "cache.json")
    assert parse.main(["--input", epub, "--out", cache_path]) == 0
    src = {it.source_text: it for it in cache_io.iter_items(cache_io.load_cache(cache_path))}
    # what the parser emits for the same title in four places (ncx and the plain link entry are both bare)
    assert [r[0] for r in _rows(cache_path)] == ["Halcyon", "Chapter One", "Chapter One", "⟦1⟧Chapter One⟦/1⟧⟦2⟧",
                                                 "⟦1⟧Chapter One", "Marlow sailed."]

    # translate only the body heading and the paragraph
    tr = tmp_path / "t.jsonl"
    tr.write_text("\n".join(json.dumps({"text_index": src[s].text_index, "translated_text": z}, ensure_ascii=False)
                            for s, z in {"Halcyon": "翠鸟号", "⟦1⟧Chapter One": "⟦1⟧第一章", "Marlow sailed.": "Marlow 起航了。"}.items()),
                  encoding="utf-8")
    assert batch.main(["write", cache_path, str(tr)]) == 0

    assert cache.main(["fill-dupes", cache_path]) == 0
    assert "3 segment(s) would be filled, 0 skipped" in capsys.readouterr().out
    assert cache.main(["fill-dupes", cache_path, "--apply"]) == 0
    assert "filled 3 segment(s)" in capsys.readouterr().out

    assert [(r[1], r[2]) for r in _rows(cache_path)] == [
        ("翠鸟号", S.TRANSLATED), ("第一章", S.TRANSLATED), ("第一章", S.TRANSLATED),
        ("⟦1⟧第一章⟦/1⟧⟦2⟧", S.TRANSLATED),                           # the entry's own link pair + footnote atom
        ("⟦1⟧第一章", S.TRANSLATED), ("Marlow 起航了。", S.TRANSLATED)]   # donor untouched
    assert not any(audit.hard_checks(s_, t) for s_, t, _ in _rows(cache_path))   # no token_mismatch

    out = tmp_path / "out"
    assert export.main(["--cache", cache_path, "--output", str(out), "--input", epub, "--finalize"]) == 0
    with zipfile.ZipFile(out / "book_translated.epub") as z:
        contents = z.read("OEBPS/contents.xhtml").decode("utf-8")
        ncx = z.read("OEBPS/toc.ncx").decode("utf-8")
    assert contents.count('<a href="ch1.xhtml">第一章</a>') == 2             # the link survives on both entries
    assert '<a href="ch1.xhtml#n1" id="r1">1</a>' in contents
    assert "<text>第一章</text>" in ncx


def test_fill_dupes_skips_a_target_whose_placeholder_sits_mid_text(tmp_path, make_project, capsys):
    proj = make_project(sources=["See note here", "See ⟦1⟧note⟦/1⟧ here", "⟦1⟧⟦2⟧Ship⟦/2⟧", "Ship"])
    cache_io.set_translation(proj, 1, "见此注")
    cache_io.set_translation(proj, 4, "舟")
    p = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(p))

    found, skipped = cache.fill_dupes(cache_io.load_cache(str(p)))
    assert found == [(3, 4, "⟦1⟧⟦2⟧舟⟦/2⟧")] and skipped == [(2, 1)]   # both ends kept; the mid-text one is listed

    assert cache.main(["fill-dupes", str(p)]) == 0
    out = capsys.readouterr().out
    assert "2 <- " in out and "skipped, placeholder mid-text" in out
    assert cache.main(["fill-dupes", str(p), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "filled 1 segment(s)" in out and "skipped 1 (placeholder mid-text" in out and "[2]" in out
    items = cache_io.index_items(cache_io.load_cache(str(p)))
    assert items[2].translation_status == S.UNTRANSLATED and not items[2].translated_text
