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


# --- 行内强调与空格保真 -------------------------------------------------
# 老 EpubReader 用 soup.get_text(strip=True)：逐片段 strip 再无缝拼接，既丢掉
# 斜体/粗体，又把片段间的空格挤掉（"her <i>blade</i> fell" → "herbladefell"）。

RICH_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>
<body>
<p>She gripped her <i>blade</i> and ran.</p>
<p>He read <span class="italic"><span>Moby Dick</span></span> twice.</p>
<p>A <b>loud</b> noise.</p>
<p><span class="italic1">Closer now,</span> she thought.</p>
<p>Plain paragraph.</p>
</body></html>"""


def _make_rich_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF)
        z.writestr("ch1.xhtml", RICH_XHTML)


def test_epub_preserves_inline_marks_and_spaces(tmp_path):
    epub = tmp_path / "rich.epub"
    _make_rich_epub(str(epub))
    proj = io_dispatch.parse_input(str(epub))
    src = [it.source_text for it in cache_io.iter_items(proj)]

    assert "She gripped her <i>blade</i> and ran." in src      # 斜体保留 + 空格未丢
    assert "He read <i>Moby Dick</i> twice." in src            # span class="italic" 也识别
    assert "A <b>loud</b> noise." in src
    assert "<i>Closer now,</i> she thought." in src           # 带编号的类名 italic1 也识别
    assert "Plain paragraph." in src
    assert not any("herblade" in s or "readMoby" in s for s in src)


def test_epub_marks_round_trip_to_original_markup(tmp_path):
    epub = tmp_path / "rich.epub"
    _make_rich_epub(str(epub))
    proj = io_dispatch.parse_input(str(epub))
    for it in cache_io.iter_items(proj):
        cache_io.set_translation(proj, it.text_index, it.source_text.replace("She", "她"))
    out = tmp_path / "out"
    io_dispatch.export_project(proj, str(out), str(epub))

    with zipfile.ZipFile(out / "rich_translated.epub") as z:
        xhtml = z.read("ch1.xhtml").decode("utf-8")
    # 标记还原成真标签，而不是被转义
    assert "&lt;i&gt;" not in xhtml and "&lt;b&gt;" not in xhtml
    assert "<i>blade</i>" in xhtml                                     # 原文用 <i> → 还原 <i>
    assert '<span class="italic"><span>Moby Dick</span></span>' in xhtml  # 原文用 span → 还原 span
    assert "<b>loud</b>" in xhtml
    assert '<span class="italic1">Closer now,</span>' in xhtml       # 带编号类名 → 原样还原


def test_repair_rebuilds_source_from_original_html(tmp_path):
    from ainiee_translate import repair
    epub = tmp_path / "rich.epub"
    _make_rich_epub(str(epub))
    proj = io_dispatch.parse_input(str(epub))
    # 模拟旧版解析结果：source_text 被压成无标记、无空格
    for it in cache_io.iter_items(proj):
        it.source_text = it.source_text.replace("<i>", "").replace("</i>", "") \
                                       .replace("<b>", "").replace("</b>", "") \
                                       .replace(" ", "")
    cache = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(cache))

    assert repair.main([str(cache), "--apply"]) == 0
    fixed = cache_io.load_cache(str(cache))
    src = [it.source_text for it in cache_io.iter_items(fixed)]
    assert "She gripped her <i>blade</i> and ran." in src
    assert "A <b>loud</b> noise." in src


def test_repair_leaves_tokenized_segments_alone(tmp_path, capsys):
    """New-parser segments carry ⟦n⟧ placeholders; re-extracting them would glue the footnote
    number into the text and drop the link."""
    from ainiee_translate import repair
    epub = tmp_path / "links.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF)
        z.writestr("ch1.xhtml", LINK_XHTML)
    proj = io_dispatch.parse_input(str(epub))
    for it in cache_io.iter_items(proj):
        if not it.extra.get("epub_tokens"):
            it.source_text = it.source_text.replace("<i>", "").replace("</i>", "")   # an old-style one
    cache = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(cache))
    before = {it.text_index: it.source_text for it in cache_io.iter_items(proj)}

    assert repair.main([str(cache), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "跳过 2 段" in out and "需改写 1 段" in out
    after = {it.text_index: it.source_text for it in cache_io.iter_items(cache_io.load_cache(str(cache)))}
    changed = {i for i in after if after[i] != before[i]}
    assert [after[i] for i in changed] == ["Plain <i>words</i>."]
    assert any("⟦2⟧" in s for s in after.values())
    assert len(list(tmp_path.glob("cache.json.bak.*"))) == 1


NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<navMap><navPoint id="n1" playOrder="1">
  <navLabel><text>Historian&#x2019;s Note&#x2014;One</text></navLabel>
  <content src="ch1.xhtml"/>
</navPoint></navMap></ncx>"""

OPF_NCX = OPF.replace(
    '<manifest>',
    '<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
).replace('<spine>', '<spine toc="ncx">')


def test_ncx_decodes_html_entities(tmp_path):
    epub = tmp_path / "ncx.epub"
    with zipfile.ZipFile(str(epub), "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF_NCX)
        z.writestr("ch1.xhtml", XHTML)
        z.writestr("toc.ncx", NCX)
    proj = io_dispatch.parse_input(str(epub))
    src = [it.source_text for it in cache_io.iter_items(proj)]
    # 旧版会留下字面 &#x2019; / &#x2014;
    assert "Historian’s Note—One" in src
    assert not any("&#x" in s for s in src)


def test_repair_list_marked_finds_stale_translations_after_apply(tmp_path, capsys):
    import json as _json
    from ainiee_translate import repair
    epub = tmp_path / "rich.epub"
    _make_rich_epub(str(epub))
    proj = io_dispatch.parse_input(str(epub))
    for it in cache_io.iter_items(proj):
        # 旧译文：标记被丢掉（正是修复前的译法）
        cache_io.set_translation(proj, it.text_index,
                                 it.source_text.replace("<i>", "").replace("</i>", "")
                                               .replace("<b>", "").replace("</b>", ""))
    cache = tmp_path / "cache.json"
    cache_io.save_cache(proj, str(cache))

    # source_text 已是新版（无需改写），--list-marked 仍须报出陈旧译文
    assert repair.main([str(cache), "--list-marked"]) == 0
    listed = _json.loads(capsys.readouterr().out)
    assert {r["text_index"] for r in listed} == {1, 2, 3, 4}   # 4 段带标记，第 5 段纯文本
    assert all("<i>" in r["source_text"] or "<b>" in r["source_text"] for r in listed)


def test_self_marked_element_not_wrapped_twice():
    from ainiee_translate._vendor.ModuleFolders.Domain.FileOutputer.EpubWriter import EpubWriter
    original = '<span class="italic1">Beneath the arch</span>'
    out = object.__new__(EpubWriter)._rebuild_translated_tag(original, "<i>拱门之下</i>")
    assert out == '<span class="italic1">拱门之下</span>'


# --- 链接 / 锚点占位符 ---------------------------------------------------
LINK_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>
<body>
<p id="p1"><a id="page5"></a>He swore<sup><a href="notes.xhtml#n1" id="r1">1</a></sup> to return, as told in <a href="ch2.xhtml">Part <i>Two</i></a>.</p>
<p>A map: <img src="map.png" alt="map"/> here.</p>
<p><a href="ch3.xhtml">Chapter Three</a></p>
<p>Plain <i>words</i>.</p>
</body></html>"""


def test_epub_link_tokens_roundtrip(tmp_path):
    epub = tmp_path / "links.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF)
        z.writestr("ch1.xhtml", LINK_XHTML)
    proj = io_dispatch.parse_input(str(epub))
    items = list(cache_io.iter_items(proj))
    by_src = {it.source_text: it for it in items}

    s1 = "⟦1⟧He swore⟦2⟧ to return, as told in ⟦3⟧Part <i>Two</i>⟦/3⟧."
    assert s1 in by_src
    toks = by_src[s1].extra["epub_tokens"]
    assert toks["1"] == '<a id="page5"></a>'
    assert toks["2"].startswith("<sup>") and 'href="notes.xhtml#n1"' in toks["2"]
    assert toks["3"] == '<a href="ch2.xhtml">' and toks["/3"] == "</a>"
    assert any(s.startswith("A map: ⟦1⟧") for s in by_src)
    assert "Chapter Three" in by_src                       # 链接是段落根：属性由 writer 复刻，不出占位符
    assert "epub_tokens" not in by_src["Plain <i>words</i>."].extra

    tr = {s1: "⟦1⟧他发誓⟦2⟧要回来，正如⟦3⟧第<i>二</i>部⟦/3⟧所述。",
          "Chapter Three": "第三章", "Plain <i>words</i>.": "平常的<i>字</i>。"}
    for it in items:
        cache_io.set_translation(proj, it.text_index, tr.get(it.source_text, it.source_text.replace("A map:", "地图：")))
    out = tmp_path / "out"
    io_dispatch.export_project(proj, str(out), str(epub))
    with zipfile.ZipFile(out / "links_translated.epub") as z:
        x = z.read("ch1.xhtml").decode("utf-8")
    assert '<p id="p1"><a id="page5"></a>他发誓<sup><a href="notes.xhtml#n1" id="r1">1</a></sup>要回来，正如<a href="ch2.xhtml">第<i>二</i>部</a>所述。</p>' in x
    assert '<img alt="map" src="map.png"/>' in x or '<img src="map.png" alt="map"/>' in x
    assert '<a href="ch3.xhtml">第三章</a>' in x
    assert "⟦" not in x


def test_extract_text_with_marks_unchanged_for_repair():
    from ainiee_translate._vendor.ModuleFolders.Domain.FileReader.EpubReader import extract_text_with_marks
    assert extract_text_with_marks('<p>He swore<sup><a href="#n1">1</a></sup> it.</p>') == "He swore1 it."
