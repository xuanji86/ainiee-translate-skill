"""export --finalize on a real parse -> write -> export round trip (no hand-built cache):
inline links, a footnote number, id anchors, an inline image and an ncx whose manifest id is
`toc` must all pass the paragraph check; untranslated leftovers and broken XML fail cleanly."""
import json
import zipfile

import pytest

from ainiee_translate import batch, cache_io, export, finalize, parse, scope

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Halcyon</dc:title>
    <dc:language>en</dc:language><dc:identifier id="uid">x-1</dc:identifier></metadata>
  <manifest>
    <item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/>
    <item id="map" href="map.png" media-type="image/png"/>
  </manifest>
  <spine toc="toc"><itemref idref="ch1"/><itemref idref="notes"/></spine>
</package>"""
NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="x-1"/></head>
  <docTitle><text>Halcyon</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1"><navLabel><text>The Airship Log</text></navLabel><content src="ch1.xhtml"/></navPoint>
    <navPoint id="n2" playOrder="2"><navLabel><text>Notes</text></navLabel><content src="notes.xhtml"/></navPoint>
  </navMap>
</ncx>"""
CH1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter One</title></head>
<body>
<h1 id="c1">Chapter One</h1>
<p id="p1"><a id="page5"></a>Marlow swore<sup><a href="notes.xhtml#n1" id="r1">1</a></sup> to return to <a href="notes.xhtml">Highmark</a>.</p>
<p>A map of Korin: <img src="map.png" alt="map"/> drawn by Hale.</p>
<p>  The airship rose.</p>
<p>Plain <i>words</i> here.</p>
</body></html>"""
NOTES = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Notes</title></head>
<body><p id="n1"><a href="ch1.xhtml#r1">1</a> Highmark is a port.</p></body></html>"""

ZH = {
    "The Airship Log": "飞艇日志", "Notes": "注释", "Chapter One": "第一章", "Halcyon": "翠鸟号",
    "⟦1⟧Marlow swore⟦2⟧ to return to ⟦3⟧Highmark⟦/3⟧.": "⟦1⟧Marlow 发誓⟦2⟧要回到⟦3⟧Highmark⟦/3⟧。",
    "A map of Korin: ⟦1⟧ drawn by Hale.": "Korin 的地图：⟦1⟧，Hale 绘。",
    "The airship rose.": "  飞艇升起。 ",                       # leading/trailing blanks the writer strips
    "Plain <i>words</i> here.": "平常的<i>字</i>。",
    "⟦1⟧ Highmark is a port.": "⟦1⟧ Highmark 是个港口。",
}


def _epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/toc.ncx", NCX)
        z.writestr("OEBPS/ch1.xhtml", CH1)
        z.writestr("OEBPS/notes.xhtml", NOTES)
        z.writestr("OEBPS/map.png", b"\x89PNG\r\n\x1a\n")
    return str(path)


def _project(tmp_path, skip=()):
    """parse -> batch write every segment except the sources in `skip` -> cache path."""
    epub = _epub(tmp_path / "book.epub")
    cache = str(tmp_path / "cache.json")
    assert parse.main(["--input", epub, "--out", cache]) == 0
    rows = [{"text_index": it.text_index, "translated_text": ZH[it.source_text]}
            for it in cache_io.iter_items(cache_io.load_cache(cache)) if it.source_text not in skip]
    tr = tmp_path / "trans.jsonl"
    tr.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    assert batch.main(["write", cache, str(tr)]) == 0
    return epub, cache


def test_parse_marks_ncx_by_tag_type_not_manifest_id(tmp_path):
    epub, cache = _project(tmp_path)
    ncx = [it for it in cache_io.iter_items(cache_io.load_cache(cache)) if it.extra.get("item_id") == "toc"]
    assert ncx and all(it.extra["tag_type"] == "ncx_text" for it in ncx)
    rows = {r["id"]: r for r in scope.plan(cache_io.load_cache(cache))}
    assert rows["toc"]["keep"] and rows["toc"]["why"] == "table of contents"


def test_finalize_roundtrip_with_tokens_ncx_and_blanks(tmp_path, capsys):
    epub, cache = _project(tmp_path)
    out = tmp_path / "out"
    assert export.main(["--cache", cache, "--output", str(out), "--input", epub, "--finalize"]) == 0
    rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rep["paragraphs_verified"] == 6                          # 9 segments minus 3 ncx labels
    with zipfile.ZipFile(rep["output"]) as z:
        ch1 = z.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert '<sup><a href="notes.xhtml#n1" id="r1">1</a></sup>要回到' in ch1   # the "1" is on the page


def test_finalize_flags_a_paragraph_missing_from_the_epub(tmp_path):
    epub, cache = _project(tmp_path)
    proj = cache_io.load_cache(cache)
    for it in cache_io.iter_items(proj):
        if it.source_text == "Plain <i>words</i> here.":
            it.extra["original_html"] = "<p>not in the book</p>"        # writer finds nothing to replace
    cache_io.save_cache(proj, cache)
    with pytest.raises(SystemExit) as e:
        export.main(["--cache", cache, "--output", str(tmp_path / "out"), "--input", epub, "--finalize"])
    assert "1 translated paragraph(s) not found" in str(e.value)


def test_untranslated_warns_on_export_and_blocks_finalize_unless_allowed(tmp_path, capsys):
    epub, cache = _project(tmp_path, skip={"Plain <i>words</i> here."})
    pending = [it.text_index for it in cache_io.iter_items(cache_io.load_cache(cache))
               if it.source_text == "Plain <i>words</i> here."]
    out = str(tmp_path / "out")
    assert export.main(["--cache", cache, "--output", out, "--input", epub]) == 0
    assert f"warning: 1 untranslated segment(s) stay in the source language: {pending}" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        export.main(["--cache", cache, "--output", out, "--input", epub, "--finalize"])
    assert "finalize failed" in str(e.value) and f"1 segment(s) still untranslated" in str(e.value)
    assert export.main(["--cache", cache, "--output", out, "--input", epub, "--finalize", "--allow-partial"]) == 0


def test_finalize_reports_broken_xml_instead_of_a_traceback(tmp_path):
    epub, cache = _project(tmp_path)
    out = tmp_path / "out"
    assert export.main(["--cache", cache, "--output", str(out), "--input", epub]) == 0
    raw, bad = out / "book_translated.epub", tmp_path / "bad.epub"
    with zipfile.ZipFile(raw) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, b"<html><body><p>unclosed</body></html>" if n.endswith("notes.xhtml") else zi.read(n))
    with pytest.raises(SystemExit) as e:
        finalize.finalize(str(bad), str(tmp_path / "final.epub"), cache, finalize.load_config(cache))
    assert str(e.value).startswith("finalize failed") and "xml OEBPS/notes.xhtml" in str(e.value)


def test_export_fails_when_a_file_has_no_writer(tmp_path, make_project, monkeypatch, capsys):
    monkeypatch.delenv("AINIEE_REPO", raising=False)
    cache = str(tmp_path / "cache.json")
    cache_io.save_cache(make_project(n=1, storage="scan.pdf"), cache)
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4")
    assert export.main(["--cache", cache, "--output", str(tmp_path / "out"), "--input",
                        str(tmp_path / "scan.pdf")]) == 1
    err = capsys.readouterr().err
    assert "NOT exported" in err and "scan.pdf" in err
