"""Read/write our own cache.json (a CacheProject serialized with msgspec), and
iterate / mutate items by translation status. The CacheProject / CacheItem types
are vendored from AiNiee under _vendor/ — no external AiNiee repo required.

Write path guarantees (apply_writeback): advisory file lock (so a stray
concurrent writer serializes instead of clobbering), timestamped backup,
O(1) item lookup, gate checks before mutation, atomic save (tmp + os.replace)."""
import json
import os
import types
from contextlib import contextmanager
from dataclasses import dataclass, field

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
    """Atomic: encode to a sibling temp file, then os.replace over the target,
    so a crash mid-write never leaves a truncated cache.json."""
    # Ensure stats_data is never null (its field type is non-Optional in msgspec eyes)
    if project.stats_data is None:
        project.stats_data = CacheProjectStatistics()
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "wb") as w:
            w.write(msgspec.json.encode(project))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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


def index_items(project) -> dict[int, CacheItem]:
    return {it.text_index: it for it in iter_items(project)}


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
    item = index_items(project).get(text_index)
    if item is None:
        return False
    item.translated_text = text
    item.translation_status = status
    return True


def set_translation(project, text_index: int, translated_text: str) -> bool:
    return _set(project, text_index, translated_text, TranslationStatus.TRANSLATED)


def set_polish(project, text_index: int, polished_text: str) -> bool:
    """Overwrite translated_text with the polished text and mark POLISHED
    (mirrors AiNiee's PolisherTask; export reads final_text == translated_text)."""
    return _set(project, text_index, polished_text, TranslationStatus.POLISHED)


@contextmanager
def locked(cache_path: str):
    """Exclusive advisory lock on <cache>.lock for the duration of a write.
    A second writer blocks until the first finishes instead of racing on the
    read-modify-write. No-op where fcntl is unavailable (Windows)."""
    try:
        import fcntl
    except ImportError:          # pragma: no cover
        yield
        return
    with open(cache_path + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@dataclass
class WriteResult:
    total: int = 0
    applied: int = 0
    rejected: list = field(default_factory=list)   # [{"text_index", "reason"}]
    warnings: dict = field(default_factory=dict)   # soft-lint category -> count (applied items)

    def summary(self, verb: str = "applied") -> str:
        s = f"{verb} {self.applied} of {self.total}"
        if self.rejected:
            s += f"; rejected {len(self.rejected)}"
        return s


def apply_writeback(cache_path: str, items: list[dict], status: int, get_text,
                    check=None, force: bool = False) -> WriteResult:
    """Lock → backup → load → for each item: gate → mutate → atomic save.

    `check(cache_item, text) -> (hard: list[str], soft: list[str])` is the write
    gate: any hard reason rejects the item (unless force=True); soft reasons are
    tallied into WriteResult.warnings. Unknown text_index is always rejected."""
    res = WriteResult(total=len(items))
    with locked(cache_path):
        helpers.backup_file(cache_path)
        project = load_cache(cache_path)
        idx = index_items(project)
        for it in items:
            ti = int(it["text_index"])
            text = get_text(it)
            item = idx.get(ti)
            if item is None:
                res.rejected.append({"text_index": ti, "reason": "unknown_index"})
                continue
            if check is not None:
                hard, soft = check(item, text)
                if hard and not force:
                    res.rejected.append({"text_index": ti, "reason": ",".join(hard)})
                    continue
                for c in soft:
                    res.warnings[c] = res.warnings.get(c, 0) + 1
            item.translated_text = text
            item.translation_status = status
            res.applied += 1
        save_cache(project, cache_path)
    _log_event(cache_path, {"event": "write", "status": int(status), "applied": res.applied,
                            "rejected": len(res.rejected), "total": res.total})
    return res


def _log_event(cache_path: str, event: dict) -> None:
    """Append one line to <work>/progress.jsonl so `progress` can show write-back history."""
    import time
    path = os.path.join(os.path.dirname(os.path.abspath(cache_path)), "progress.jsonl")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **event}, ensure_ascii=False) + "\n")
    except OSError:
        pass
