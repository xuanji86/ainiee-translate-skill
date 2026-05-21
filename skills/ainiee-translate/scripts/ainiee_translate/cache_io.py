"""Read/write our own cache.json (a CacheProject serialized with msgspec), and
iterate / mutate items by translation status. The CacheProject / CacheItem types
are vendored from AiNiee under _vendor/ — no external AiNiee repo required."""
import json
import types
import msgspec
from . import helpers
from ._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject, CacheProjectStatistics
from ._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem, TranslationStatus


def _m():
    """Back-compat shim: callers used to get these types from ainiee_lib.load()."""
    return types.SimpleNamespace(
        CacheProject=CacheProject, CacheItem=CacheItem,
        CacheProjectStatistics=CacheProjectStatistics, TranslationStatus=TranslationStatus)


def save_cache(project, path: str) -> None:
    # Ensure stats_data is never null (its field type is non-Optional in msgspec eyes)
    if project.stats_data is None:
        project.stats_data = CacheProjectStatistics()
    with open(path, "wb") as w:
        w.write(msgspec.json.encode(project))


def load_cache(path: str):
    with open(path, "rb") as r:
        content_bytes = r.read()
    try:
        return msgspec.json.decode(content_bytes, type=CacheProject)
    except msgspec.ValidationError:
        # CacheItem has nullable-but-non-Optional fields (text_to_detect, translated_text);
        # fall back to CacheProject.from_dict exactly as AiNiee's CacheManager does.
        content = json.loads(content_bytes.decode("utf-8"))
        return CacheProject.from_dict(content)


def iter_items(project):
    for cache_file in project.files.values():
        for item in cache_file.items:
            yield item


def _iter_by_status(project, status):
    for item in iter_items(project):
        if item.translation_status == status and (item.source_text or "").strip():
            yield item


def iter_untranslated(project):
    return _iter_by_status(project, TranslationStatus.UNTRANSLATED)


def iter_translated_unpolished(project):
    """Items eligible for a polish pass (and resume): status == TRANSLATED."""
    return _iter_by_status(project, TranslationStatus.TRANSLATED)


def _set(project, text_index: int, text: str, status) -> bool:
    for item in iter_items(project):
        if item.text_index == text_index:
            item.translated_text = text
            item.translation_status = status
            return True
    return False


def set_translation(project, text_index: int, translated_text: str) -> bool:
    return _set(project, text_index, translated_text, TranslationStatus.TRANSLATED)


def set_polish(project, text_index: int, polished_text: str) -> bool:
    """Overwrite translated_text with the polished text and mark POLISHED
    (mirrors AiNiee's PolisherTask; export reads final_text == translated_text)."""
    return _set(project, text_index, polished_text, TranslationStatus.POLISHED)


def apply_writeback(cache_path: str, items: list[dict], setter, get_text) -> int:
    """Backup, load, apply `setter(project, text_index, get_text(item))` for each
    item, save. Shared by the translate (batch) and polish write paths."""
    helpers.backup_file(cache_path)
    project = load_cache(cache_path)
    applied = 0
    for it in items:
        if setter(project, int(it["text_index"]), get_text(it)):
            applied += 1
    save_cache(project, cache_path)
    return applied
