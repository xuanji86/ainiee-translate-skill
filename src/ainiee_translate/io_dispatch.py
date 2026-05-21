"""Self-contained parse/export dispatcher built on the vendored AiNiee readers
and writers (no external AiNiee repo). Replaces AiNiee's FileReader / FileOutputer
/ DirectoryReader / DirectoryWriter for all light formats — without the app
framework (PyQt / mediapipe / babeldoc / CacheManager / Office COM).

parse_input(input)  -> CacheProject   (walk files, read, assign text_index)
export_project(...)  -> writes <out>/<name>_translated.<ext> + bilingual_<ext>/

Ambiguous extensions (.json, .xlsx map to several formats) are disambiguated by
each reader's content check (can_read(fast=False)), most-specific first.
"""
import argparse
import fnmatch
import uuid
from datetime import datetime
from pathlib import Path

from . import cache_io
from ._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
from ._vendor.ModuleFolders.Domain.FileReader.BaseReader import InputConfig
from ._vendor.ModuleFolders.Domain.FileReader.TxtReader import TxtReader
from ._vendor.ModuleFolders.Domain.FileReader.MdReader import MdReader
from ._vendor.ModuleFolders.Domain.FileReader.EpubReader import EpubReader
from ._vendor.ModuleFolders.Domain.FileReader.AssReader import AssReader
from ._vendor.ModuleFolders.Domain.FileReader.CsvReader import CsvReader
from ._vendor.ModuleFolders.Domain.FileReader.DocxReader import DocxReader
from ._vendor.ModuleFolders.Domain.FileReader.I18nextReader import I18nextReader
from ._vendor.ModuleFolders.Domain.FileReader.LrcReader import LrcReader
from ._vendor.ModuleFolders.Domain.FileReader.MToolReader import MToolReader
from ._vendor.ModuleFolders.Domain.FileReader.ParatranzReader import ParatranzReader
from ._vendor.ModuleFolders.Domain.FileReader.PoReader import PoReader
from ._vendor.ModuleFolders.Domain.FileReader.PptxReader import PptxReader
from ._vendor.ModuleFolders.Domain.FileReader.RenpyReader import RenpyReader
from ._vendor.ModuleFolders.Domain.FileReader.SrtReader import SrtReader
from ._vendor.ModuleFolders.Domain.FileReader.TPPReader import TPPReader
from ._vendor.ModuleFolders.Domain.FileReader.TransReader import TransReader
from ._vendor.ModuleFolders.Domain.FileReader.VntReader import VntReader
from ._vendor.ModuleFolders.Domain.FileReader.VttReader import VttReader
from ._vendor.ModuleFolders.Domain.FileReader.WolfXlsxReader import WolfXlsxReader
from ._vendor.ModuleFolders.Domain.FileReader.XlsxReader import XlsxReader
from ._vendor.ModuleFolders.Domain.FileOutputer.BaseWriter import (
    BaseTranslationWriter, OutputConfig, TranslationOutputConfig, BilingualOrder)
from ._vendor.ModuleFolders.Domain.FileOutputer.TxtWriter import TxtWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.MdWriter import MdWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.EpubWriter import EpubWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.AssWriter import AssWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.CsvWriter import CsvWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.DocxWriter import DocxWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.I18nextWriter import I18nextWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.LrcWriter import LrcWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.MToolWriter import MToolWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.ParatranzWriter import ParatranzWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.PoWriter import PoWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.PptxWriter import PptxWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.RenpyWriter import RenpyWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.SrtWriter import SrtWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.TPPWriter import TPPWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.TransWriter import TransWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.VntWriter import VntWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.VttWriter import VttWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.WolfXlsxWriter import WolfXlsxWriter
from ._vendor.ModuleFolders.Domain.FileOutputer.XlsxWriter import XlsxWriter

_READERS = [TxtReader, MdReader, EpubReader, AssReader, CsvReader, DocxReader, I18nextReader,
            LrcReader, MToolReader, ParatranzReader, PoReader, PptxReader, RenpyReader, SrtReader,
            TPPReader, TransReader, VntReader, VttReader, WolfXlsxReader, XlsxReader]
_WRITERS = [TxtWriter, MdWriter, EpubWriter, AssWriter, CsvWriter, DocxWriter, I18nextWriter,
            LrcWriter, MToolWriter, ParatranzWriter, PoWriter, PptxWriter, RenpyWriter, SrtWriter,
            TPPWriter, TransWriter, VntWriter, VttWriter, WolfXlsxWriter, XlsxWriter]

# project_type -> (ReaderClass, WriterClass)
_WRITER_BY_TYPE = {w.get_project_type(): w for w in _WRITERS}
FORMATS = {r.get_project_type(): (r, _WRITER_BY_TYPE.get(r.get_project_type())) for r in _READERS}

# file extension -> ordered project_types to try (most specific first for ambiguous exts)
EXT_CANDIDATES = {
    "txt": ["Txt"], "md": ["Md"], "epub": ["Epub"], "ass": ["Ass"], "csv": ["Csv"],
    "docx": ["Docx"], "lrc": ["Lrc"], "po": ["Po"], "pptx": ["Pptx"], "rpy": ["Renpy"],
    "srt": ["Srt"], "trans": ["Trans"], "vtt": ["Vtt"],
    "json": ["Mtool", "Paratranz", "I18next", "Vnt"],   # content-detected
    "xlsx": ["WolfXlsx", "Tpp", "Xlsx"],                # WolfXlsx/Tpp specific, Xlsx generic last
}


def supported_extensions() -> list[str]:
    return sorted(EXT_CANDIDATES)


def _pick_reader(fp: Path, base: Path, project_type: str):
    cands = EXT_CANDIDATES.get(fp.suffix.lstrip(".").lower(), [])
    if project_type != "AutoType":
        cands = [project_type] if project_type in cands else []
    for t in cands:
        reader = FORMATS[t][0](InputConfig(input_root=base))
        if len(cands) == 1 or reader.can_read(fp, fast=False):   # content-detect ambiguous exts
            return reader
    return None


def _generate_project_name(project) -> None:
    files = list(project.files.values())
    if not files:
        project.project_name = "EmptyProject"
    elif len(files) == 1:
        project.project_name = Path(files[0].storage_path).stem
    else:
        project.project_name = "&&".join(Path(f.storage_path).stem[:5] for f in files[:4])


def parse_input(input_path: str, project_type: str = "AutoType", exclude_rule: str = "") -> CacheProject:
    root = Path(input_path)
    project = CacheProject()
    project.project_id = uuid.uuid4().hex
    project.project_create_time = datetime.now().isoformat(timespec="seconds")
    project.input_path = str(root)

    if root.is_dir():
        base, files = root, sorted(p for p in root.rglob("*") if p.is_file())
    elif root.is_file():
        base, files = root.parent, [root]
    else:
        raise FileNotFoundError(f"input not found: {input_path}")

    excludes = [r for r in exclude_rule.split(",") if r]
    text_index = 1
    types_seen = set()
    for fp in files:
        if any(fnmatch.fnmatch(fp.name, r) for r in excludes):
            continue
        reader = _pick_reader(fp, base, project_type)
        if reader is None:
            continue
        cache_file = reader.read_source_file(fp)            # pre + on_read + (no-op) post
        if not cache_file or not cache_file.items:
            continue
        cache_file.storage_path = str(fp.relative_to(base))
        cache_file.file_project_type = reader.get_project_type()
        for item in cache_file.items:
            item.text_index = text_index
            item.model = "none"
            text_index += 1
        project.add_file(cache_file)
        types_seen.add(reader.get_project_type())

    if project_type != "AutoType":
        project.project_type = project_type
    elif len(types_seen) == 1:
        project.project_type = next(iter(types_seen))
    else:
        project.project_type = "AutoType"
    _generate_project_name(project)
    return project


def _with_suffix(storage_path: str, name_suffix: str) -> str:
    parts = storage_path.rsplit(".", 1)
    return f"{parts[0]}{name_suffix}.{parts[1]}" if len(parts) == 2 else f"{parts[0]}{name_suffix}"


def _writer_type_for(cache_file, storage_path: str) -> str | None:
    ptype = getattr(cache_file, "file_project_type", None)
    if ptype in FORMATS:
        return ptype
    cands = EXT_CANDIDATES.get(Path(storage_path).suffix.lstrip(".").lower(), [])
    return cands[-1] if cands else None      # generic fallback (e.g. Xlsx) when type unknown


def export_project(project, output_path: str, input_path: str, config: dict | None = None) -> None:
    config = config or {}
    out_root = Path(output_path)
    in_path = Path(input_path)
    source_dir = in_path.parent if in_path.is_file() else in_path   # always a dir
    translated_suffix = config.get("translated_suffix", "_translated")
    bilingual_suffix = config.get("bilingual_suffix", "_bilingual")
    try:
        order = BilingualOrder(config.get("bilingual_order", "translation_first"))
    except ValueError:
        order = BilingualOrder.TRANSLATION_FIRST

    for storage_path, cache_file in project.files.items():
        ptype = _writer_type_for(cache_file, storage_path)
        if ptype is None:
            continue
        ext = Path(storage_path).suffix.lstrip(".").lower() or ptype.lower()
        writer = FORMATS[ptype][1](OutputConfig(
            translated_config=TranslationOutputConfig(True, translated_suffix, out_root),
            bilingual_config=TranslationOutputConfig(True, bilingual_suffix, out_root / f"bilingual_{ext}"),
            input_root=in_path, bilingual_order=order))
        source_file_path = source_dir / storage_path
        for mode in BaseTranslationWriter.TranslationMode:
            if not writer.can_write(mode):
                continue
            tcfg = getattr(writer.output_config, mode.config_attr)
            out_file = tcfg.output_root / _with_suffix(storage_path, tcfg.name_suffix)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            getattr(writer, mode.write_method)(out_file, cache_file, source_file_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Self-contained parse/export")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    p.add_argument("--input", required=True)
    p.add_argument("--type", default="AutoType")
    p.add_argument("--exclude", default="")
    p.add_argument("--out", default="cache.json")
    e = sub.add_parser("export")
    e.add_argument("--cache", required=True)
    e.add_argument("--output", required=True)
    e.add_argument("--input", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "parse":
        proj = parse_input(a.input, a.type, a.exclude)
        cache_io.save_cache(proj, a.out)
        print(f"parsed {proj.count_items()} items -> {a.out}")
    elif a.cmd == "export":
        export_project(cache_io.load_cache(a.cache), a.output, a.input)
        print(f"exported -> {a.output}")


if __name__ == "__main__":
    main()
