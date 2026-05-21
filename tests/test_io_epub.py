import zipfile
from ainiee_translate import io_dispatch, cache_io

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata/>
  <manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""
XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>
<body><h1>Chapter One</h1><p>The quick brown fox.</p><p>Jumped over.</p></body></html>"""


def _make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF)
        z.writestr("ch1.xhtml", XHTML)


def test_epub_roundtrip(tmp_path):
    epub = tmp_path / "book.epub"
    _make_epub(str(epub))
    proj = io_dispatch.parse_input(str(epub))
    assert proj.project_type == "Epub"
    assert proj.count_items() == 3                      # h1 + 2 p

    for it in cache_io.iter_items(proj):
        cache_io.set_translation(proj, it.text_index, "T:" + it.source_text)
    out = tmp_path / "out"
    io_dispatch.export_project(proj, str(out), str(epub))

    out_epub = out / "book_translated.epub"
    assert out_epub.is_file()
    with zipfile.ZipFile(out_epub) as z:
        xhtml = z.read("ch1.xhtml").decode("utf-8")
        assert "T:Chapter One" in xhtml and "T:The quick brown fox." in xhtml
        # all original files preserved (zip round-trip, not rebuild)
        assert set(z.namelist()) == {"mimetype", "META-INF/container.xml", "content.opf", "ch1.xhtml"}
    assert (out / "bilingual_epub").is_dir()
