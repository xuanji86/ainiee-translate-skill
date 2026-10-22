"""Turn an exported epub into the deliverable: target-language metadata, a FIXED identifier
(re-exports update the copy already in a reader such as Books instead of adding a new book),
XML / link / anchor checks, every translated paragraph present, mimetype stored first.

Settings live in work/export.json (written on first use, so the identifier never changes):
  {"title": "示例书名", "language": "zh-CN",
   "identifier": "<uuid, generated once>", "description": "<p>…</p>",
   "name": "示例书名", "deliver": "/path/to/delivery/示例书名.epub"}
"""
import json
import os
import posixpath
import re
import shutil
import uuid
from urllib.parse import unquote
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree as E

from . import cache_io

NS = {"o": "http://www.idpf.org/2007/opf", "d": "http://purl.org/dc/elements/1.1/"}
_TAG = re.compile(r"<[^>]+>")


def config_path(cache_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(cache_path)), "export.json")


def load_config(cache_path: str, overrides: dict | None = None) -> dict:
    p = config_path(cache_path)
    cfg = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.update({k: v for k, v in (overrides or {}).items() if v})
    changed = False
    if not cfg.get("identifier"):
        cfg["identifier"] = str(uuid.uuid4())
        changed = True
    cfg.setdefault("language", "zh-CN")
    if changed or overrides:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    return cfg


def _metadata(data: dict, cfg: dict) -> None:
    c = E.fromstring(data["META-INF/container.xml"])
    opf = c.xpath('//*[local-name()="rootfile"]/@full-path')[0]
    root = E.fromstring(data[opf])
    base = posixpath.dirname(opf)
    title, lang, uid = cfg.get("title"), cfg["language"], cfg["identifier"]
    meta = root.find("o:metadata", NS)
    for e in meta:
        if not isinstance(e.tag, str):
            continue
        name = E.QName(e).localname
        if name == "title" and title:
            e.text = title
        elif name == "language":
            e.text = lang
        elif name == "identifier" and e.get("id") == root.get("unique-identifier"):
            e.text = uid
        elif name == "meta" and e.get("name") == "calibre:title_sort" and title:
            e.set("content", title)
        elif name == "description" and cfg.get("description"):
            e.text = cfg["description"]
    data[opf] = E.tostring(root, encoding="utf-8", xml_declaration=True)
    sp = root.find("o:spine", NS)
    items = {e.get("id"): e for e in root.find("o:manifest", NS)}
    if sp is not None and sp.get("toc") in items:
        ncxname = posixpath.normpath(posixpath.join(base, items[sp.get("toc")].get("href")))
        ncx = E.fromstring(data[ncxname])
        if title:
            for e in ncx.xpath('//*[local-name()="docTitle"]/*[local-name()="text"]'):
                e.text = title
        for e in ncx.xpath('//*[local-name()="meta" and @name="dtb:uid"]'):
            e.set("content", uid)
        ncx.set("{http://www.w3.org/XML/1998/namespace}lang", lang)
        data[ncxname] = E.tostring(ncx, encoding="utf-8", xml_declaration=True)


def _check(data: dict) -> tuple[list[str], list[str]]:
    """-> (errors, warnings). Broken XML is an error; a dangling link/anchor is a warning
    (source epubs ship with some, e.g. a stylesheet the publisher never packed)."""
    errs, warns = [], []
    parsed = {}
    for n, b in data.items():
        if n.endswith((".xhtml", ".html", ".opf", ".ncx", ".xml")):
            try:
                parsed[n] = E.fromstring(b)
            except E.XMLSyntaxError as e:
                errs.append(f"xml {n}: {e}")
    for n, r in parsed.items():
        if not n.endswith((".xhtml", ".html", ".ncx")):
            continue
        for e in r.iter():
            if not isinstance(e.tag, str):
                continue
            for att in ("href", "src"):
                link = e.get(att)
                if not link or ":" in link:
                    continue
                file, _, frag = unquote(link).partition("#")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(n), file)) if file else n
                if target not in data:
                    warns.append(f"link {n} -> {link}")
                elif frag and target in parsed and not parsed[target].xpath("//*[@id=$id]", id=frag):
                    warns.append(f"anchor {n} -> {link}")
    return errs, warns


def finalize(epub_in: str, epub_out: str, cache_path: str, cfg: dict) -> dict:
    with ZipFile(epub_in) as z:
        data = {n: z.read(n) for n in z.namelist()}
    _metadata(data, cfg)
    errs, warns = _check(data)
    body = "\n".join("".join(E.fromstring(b).itertext()) for n, b in data.items() if n.endswith((".xhtml", ".html")))
    missing, checked = [], 0
    for it in cache_io.iter_items(cache_io.load_cache(cache_path)):
        if int(it.translation_status) in (1, 2) and (it.extra or {}).get("item_id") != "ncx":
            checked += 1
            if _TAG.sub("", it.translated_text or "") not in body:
                missing.append(it.text_index)
    if missing:
        errs.append(f"{len(missing)} translated paragraph(s) not found in the epub: {missing[:20]}")
    if errs:
        raise SystemExit("finalize failed:\n  " + "\n  ".join(errs[:30]))
    os.makedirs(os.path.dirname(os.path.abspath(epub_out)), exist_ok=True)
    tmp = epub_out + ".tmp"
    with ZipFile(tmp, "w") as z:
        z.writestr("mimetype", data.pop("mimetype"), compress_type=ZIP_STORED)
        for n, b in data.items():
            z.writestr(n, b, compress_type=ZIP_DEFLATED)
    os.replace(tmp, epub_out)
    rep = {"output": epub_out, "paragraphs_verified": checked, "identifier": cfg["identifier"]}
    if warns:
        rep["warnings"] = sorted(set(warns))[:20]
    if cfg.get("deliver"):
        os.makedirs(os.path.dirname(os.path.abspath(cfg["deliver"])), exist_ok=True)
        shutil.copy2(epub_out, cfg["deliver"])
        rep["delivered"] = cfg["deliver"]
    return rep
