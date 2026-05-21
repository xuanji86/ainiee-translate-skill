"""String helpers shared across the pipeline. Mirrors the proven logic in the
ainiee-cache-fix skill (apostrophe normalization + Latin-only boundaries)."""
import re
import shutil
import time

_APOS = {"'": "'", "ʼ": "'", "＇": "'", "’": "'"}
_CJK = re.compile(r"[一-鿿]")


def backup_file(path: str) -> str:
    """Timestamped copy alongside the original: path.bak.YYYYMMDD_HHMMSS."""
    dst = f"{path}.bak.{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(path, dst)
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
