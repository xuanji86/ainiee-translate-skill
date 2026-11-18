"""An empty id anchor in front of a lone link (`<p><a id="e1"></a><a href>Chapter Two</a></p>`, the usual
shape of a scanned contents page) used to drop the whole paragraph: the reader took the first `<a>` as
the segment root, found no text in it and skipped it. Every shape here must keep its text, and the
anchors and links must come back out of a real parse -> write -> export round trip."""
import json
import zipfile

from ainiee_translate import batch, cache_io, export, parse

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Halcyon</dc:title>
    <dc:language>en</dc:language><dc:identifier id="uid">x-1</dc:identifier></metadata>
  <manifest><item id="pg" href="pg.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="pg"/></spine>
</package>"""
# (xhtml, expected source_text, translation, expected xhtml after export)
SHAPES = [
    ('<p><a id="a1"></a><a href="x1.xhtml">Chapter Two</a></p>', "Chapter Two", "第二章",
     '<p><a id="a1"></a><a href="x1.xhtml">第二章</a></p>'),
    ('<ul><li><a id="a2"></a><a href="x2.xhtml">Chapter Three</a></li></ul>', "Chapter Three", "第三章",
     '<li><a id="a2"></a><a href="x2.xhtml">第三章</a></li>'),
    ('<h2><a id="a3"></a><a href="x3.xhtml">Chapter Four</a></h2>', "Chapter Four", "第四章",
     '<h2><a id="a3"></a><a href="x3.xhtml">第四章</a></h2>'),
    ('<table><tr><td><a id="a4"></a><a href="x4.xhtml">Chapter Five</a></td></tr></table>', "Chapter Five", "第五章",
     '<td><a id="a4"></a><a href="x4.xhtml">第五章</a></td>'),
    ('<p><a id="a5"></a><a id="a6"></a><a href="x6.xhtml">Chapter Six</a></p>', "Chapter Six", "第六章",
     '<p><a id="a5"></a><a id="a6"></a><a href="x6.xhtml">第六章</a></p>'),
    ('<p><a href="x7.xhtml">Chapter Seven</a><a id="a7"></a></p>', "Chapter Seven", "第七章",
     '<p><a href="x7.xhtml">第七章</a><a id="a7"></a></p>'),
    ('<p><a href="x8.xhtml">Chapter Eight</a> <a href="x9.xhtml">Chapter Nine</a></p>',
     "⟦1⟧Chapter Eight⟦/1⟧ ⟦2⟧Chapter Nine⟦/2⟧", "⟦1⟧第八章⟦/1⟧ ⟦2⟧第九章⟦/2⟧",
     '<p><a href="x8.xhtml">第八章</a> <a href="x9.xhtml">第九章</a></p>'),
    ('<p><a href="x10.xhtml">Chapter Ten</a></p>', "Chapter Ten", "第十章",
     '<p><a href="x10.xhtml">第十章</a></p>'),
    ('<p><a id="a8"/>Plain <a href="x11.xhtml">Chapter Eleven</a></p>',
     "⟦1⟧Plain ⟦2⟧Chapter Eleven⟦/2⟧", "⟦1⟧平常的⟦2⟧第十一章⟦/2⟧",
     '<p><a id="a8"></a>平常的<a href="x11.xhtml">第十一章</a></p>'),
    ('<h1><a id="a9"></a>Chapter One</h1>', "⟦1⟧Chapter One", "⟦1⟧第一章",
     '<h1><a id="a9"></a>第一章</h1>'),
    # unchanged behaviour: same-name wrappers around the text stay the segment root
    ('<p><span class="o"><span class="n">Plain words</span></span></p>', "Plain words", "平常的话",
     '<p><span class="o">平常的话</span></p>'),
]


def _book(tmp_path):
    body = "\n".join(s[0] for s in SHAPES)
    path = tmp_path / "book.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/pg.xhtml", '<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml">'
                   f"<head><title>Contents</title></head>\n<body>\n{body}\n</body></html>")
    return str(path)


def test_empty_anchor_before_a_lone_link_keeps_the_paragraph_and_round_trips(tmp_path):
    epub, cache = _book(tmp_path), str(tmp_path / "cache.json")
    assert parse.main(["--input", epub, "--out", cache]) == 0
    items = list(cache_io.iter_items(cache_io.load_cache(cache)))
    assert sorted(it.source_text for it in items) == sorted(s[1] for s in SHAPES)       # nothing dropped

    zh = {s[1]: s[2] for s in SHAPES}
    tr = tmp_path / "t.jsonl"
    tr.write_text("\n".join(json.dumps({"text_index": it.text_index, "translated_text": zh[it.source_text]},
                                       ensure_ascii=False) for it in items), encoding="utf-8")
    assert batch.main(["write", cache, str(tr)]) == 0
    out = tmp_path / "out"
    assert export.main(["--cache", cache, "--output", str(out), "--input", epub, "--finalize"]) == 0
    with zipfile.ZipFile(out / "book_translated.epub") as z:
        page = z.read("OEBPS/pg.xhtml").decode("utf-8")
    for _, src, _, want in SHAPES:
        assert want in page, src                  # anchor and link both still there, around the translation
    assert "Chapter" not in page.split("<body>")[1]
