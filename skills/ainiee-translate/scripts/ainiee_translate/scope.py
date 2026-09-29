"""Decide which parts of a book get translated: the story (chapters, prologue/
epilogue/interludes, part and date dividers) plus the Historian's Note. Everything
else — praise, copyright, dedication, epigraph, contents page, acknowledgments,
about the author, publisher sign-up pages, previews of other books — is marked
EXCLUDED (status 7): no agent translates it and export keeps the original text.

  scope <cache>                          preview: one row per book file (keep / drop + why)
  scope <cache> --apply                  mark dropped files' untranslated segments EXCLUDED
  scope <cache> --keep ID… --drop ID…    override the call for specific files (item_id)
  scope <cache> --apply --force          also exclude segments already translated

Classification is per book file (epub spine item / source file), from its first
non-empty segment. The table of contents (ncx) is kept: it holds the chapter titles.
"""
import argparse
import re

from . import cache_io, helpers
from .batch import chapters
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus

_TAGS = re.compile(r"</?[a-z]+>", re.I)
_NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
              "sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty")
_STORY = re.compile(
    r"^(?:\d{1,3}|[ivxlc]{1,7}|(?:" + _NUM_WORDS + r")(?:[- ](?:" + _NUM_WORDS + r"))?"
    r"|(?:chapter|part|book|act|section)\b.*|prologue\b.*|epilogue\b.*|interlude\b.*|coda\b.*|afterword\b.*"
    r"|historian[’']s note\b.*)$", re.I)
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_DATE = re.compile(r"^(?:(?:" + _MONTHS + r")\s+)?\d{3,4}(?:\s*(?:ad|ce))?$", re.I)
_FRONT = re.compile(r"^(?:contents|table of contents|acknowledg|about the author|also by|praise for|"
                    r"for |dedicat|copyright|thank you for downloading|we hope you enjoyed|"
                    r"an original publication|pocket books|this book is a work of fiction)", re.I)
KEEP_IDS = {"ncx"}


def _first(items) -> str:
    for it in items:
        t = _TAGS.sub("", it.source_text or "").strip()
        if t:
            return t
    return ""


def classify(key, items) -> tuple[bool, str]:
    """-> (keep, reason)."""
    if key in KEEP_IDS:
        return True, "table of contents"
    first = _first(items)
    words = sum(len((it.source_text or "").split()) for it in items)
    if not first:
        return False, "empty"
    if _FRONT.match(first):
        return False, "front/back matter"
    if _STORY.match(first):
        return True, "chapter / story heading"
    if words <= 6 and (_DATE.match(first) or first.upper() == first):
        return True, "part or date divider"
    return False, "not a chapter"


def plan(project, keep=(), drop=()):
    rows = []
    for key, items in chapters(project):  # one entry per book file, reading order
        ok, why = classify(key, items)
        if key in keep:
            ok, why = True, "kept by --keep"
        if key in drop:
            ok, why = False, "dropped by --drop"
        rows.append({"id": key, "keep": ok, "why": why, "segments": len(items),
                     "words": sum(len((it.source_text or "").split()) for it in items),
                     "first": _first(items)[:50], "items": items})
    return rows


def apply(cache_path: str, keep=(), drop=(), force: bool = False) -> dict:
    with cache_io.locked(cache_path):
        helpers.backup_file(cache_path)
        project = cache_io.load_cache(cache_path)
        rows = plan(project, keep, drop)
        changed = skipped = 0
        for r in rows:
            if r["keep"]:
                continue
            for it in r["items"]:
                if it.translation_status == TranslationStatus.EXCLUDED:
                    continue
                if it.translation_status != TranslationStatus.UNTRANSLATED and not force:
                    skipped += 1
                    continue
                it.translation_status = TranslationStatus.EXCLUDED
                changed += 1
        cache_io.save_cache(project, cache_path)
    return {"excluded": changed, "skipped_translated": skipped, "rows": rows}


def _print(rows):
    kw = sum(r["words"] for r in rows if r["keep"])
    dw = sum(r["words"] for r in rows if not r["keep"])
    for r in rows:
        mark = "keep" if r["keep"] else "DROP"
        print(f"{mark}  {str(r['id'])[:24]:24s} {r['segments']:4d} seg {r['words']:6d} w  {r['why']:24s} | {r['first']}")
    tot = kw + dw
    print(f"\ntranslate {kw} words, skip {dw} words ({dw / max(1, tot):.1%} of {tot})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Translate only the story + Historian's Note; exclude the rest")
    ap.add_argument("cache")
    ap.add_argument("--apply", action="store_true", help="write EXCLUDED to the cache (backup first)")
    ap.add_argument("--keep", nargs="*", default=[], metavar="ID", help="file ids to translate anyway")
    ap.add_argument("--drop", nargs="*", default=[], metavar="ID", help="file ids to exclude anyway")
    ap.add_argument("--force", action="store_true", help="also exclude segments that are already translated (their existing translation stays in the export)")
    a = ap.parse_args(argv)
    if a.apply:
        res = apply(a.cache, set(a.keep), set(a.drop), a.force)
        _print(res["rows"])
        print(f"excluded {res['excluded']} segments"
              + (f"; left {res['skipped_translated']} already-translated ones (use --force)" if res["skipped_translated"] else ""))
    else:
        _print(plan(cache_io.load_cache(a.cache), set(a.keep), set(a.drop)))
        print("preview only — add --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
