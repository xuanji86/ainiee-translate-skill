"""String helpers shared across the pipeline. Mirrors the proven logic in the
ainiee-cache-fix skill (apostrophe normalization + Latin-only boundaries)."""
import glob
import os
import re
import shutil
import time

_APOS = {"'": "'", "ʼ": "'", "＇": "'", "’": "'"}
_CJK = re.compile(r"[一-鿿]")


def backup_file(path: str, keep: int | None = None) -> str:
    """Timestamped copy alongside the original: path.bak.YYYYMMDD_HHMMSS.

    Only the newest `keep` auto-backups are retained (default: env
    AINIEE_BACKUP_KEEP, else 10; 0 = unlimited). Files with other suffixes
    (e.g. hand-made cache.json.pre_xxx) are never touched."""
    dst = f"{path}.bak.{time.strftime('%Y%m%d_%H%M%S')}"
    n = 0
    while os.path.exists(dst if n == 0 else f"{dst}_{n}"):   # two writes in one second
        n += 1
    if n:
        dst = f"{dst}_{n}"
    shutil.copy2(path, dst)
    if keep is None:
        try:
            keep = int(os.environ.get("AINIEE_BACKUP_KEEP", "10") or 0)
        except ValueError:
            keep = 10
    if keep > 0:
        baks = sorted(glob.glob(glob.escape(path) + ".bak.*"))
        for old in baks[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass
    return dst


def normalize_apostrophes(text: str) -> str:
    for src, dst in _APOS.items():
        text = text.replace(src, dst)
    return text


def latin_boundary_search(term: str, text: str):
    """Find `term` not flanked by Latin letters. Correct in mixed CJK/Latin text
    where \\b is unreliable (CJK counts as a word char under Unicode)."""
    t = normalize_apostrophes(term)
    h = normalize_apostrophes(text)
    return re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", h)


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))
