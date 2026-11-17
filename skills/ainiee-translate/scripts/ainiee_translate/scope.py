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
non-empty segment. A short file right after a "Part One" heading is the part's subtitle: its
title is kept and the all-italic lines after it (the epigraph) are excluded. Both tables of contents (the ncx and the in-book contents page) are kept:
they hold the chapter titles, and translating one but not the other leaves the reader an
English contents page (`cache fill-dupes` copies the titles across). A long prose file after
the last kept story file is kept as a continuation (an interlude body whose first line is a
dateline such as "NORTH WATCH CAMP, DAY 47" is still story). `--keep ID` on an applied book
puts that file's excluded, untranslated segments back to pending.

Only for English (Latin-script) sources with file structure: a single txt, or a book whose
source is mostly non-Latin script, is left untouched.
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
_TOC = re.compile(r"^(?:contents|table of contents)\b", re.I)
_FRONT = re.compile(r"^(?:acknowledg|about the author|also by|praise for|appendix|"
                    r"dedicat|copyright|thank you for downloading|we hope you enjoyed|"
                    r"an original publication|pocket books|this book is a work of fiction)", re.I)
_DEDICATION = re.compile(r"^for\s", re.I)   # "For my mother." — but "For a long moment…" opens prose
_EPIGRAPH = re.compile(r"^<i>.*</i>$", re.S)
_LETTER = re.compile(r"[^\W\d_]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f]")
CONTINUATION_WORDS = 200   # a prose file this long after a story file is story too; a "For …" file
                           # this long is prose, not a dedication


def _first(items) -> str:
    for it in items:
        t = _TAGS.sub("", it.source_text or "").strip()
        if t:
            return t
    return ""


def classify(key, items) -> tuple[bool, str]:
    """-> (keep, reason)."""
    if any((it.extra or {}).get("tag_type") == "ncx_text" for it in items):
        return True, "table of contents"
    first = _first(items)
    words = sum(len((it.source_text or "").split()) for it in items)
    if not first:
        return False, "empty"
    if _TOC.match(first):
        return True, "table of contents"
    if _FRONT.match(first):
        return False, "front/back matter"
    if _DEDICATION.match(first) and words < CONTINUATION_WORDS:
        return False, "dedication"
    if _STORY.match(first):
        return True, "chapter / story heading"
    if words <= 6 and (_DATE.match(first) or first.upper() == first):
        return True, "part or date divider"
    return False, "not a chapter"


def skip_reason(project) -> str | None:
    """Why scope cannot judge this book at all (then it marks nothing), or None."""
    runs = chapters(project)
    if len(runs) == 1 and runs[0][0] is None:
        return "无文件结构（单个 txt 等），跳过 scope"
    text = "\n".join(it.source_text or "" for it in cache_io.iter_items(project))
    if len(_LATIN.findall(text)) < len(_LETTER.findall(text)) / 2:
        return "源文以非拉丁文字为主，scope 目前只适用英文源文，跳过"
    return None


def _story_before(rows):
    """The last kept story file before this one, looking past files dropped for unclear reasons
    (an epigraph page, a short "For …" scene) but not past front/back matter: an appendix or the
    copyright page after the acknowledgments is not a continuation of the epilogue."""
    for r in reversed(rows):
        if r["keep"] and r["why"] != "table of contents":
            return r
        if not r["keep"] and r["why"] == "front/back matter":
            return None
    return None


def plan(project, keep=(), drop=()):
    rows = []
    for key, items in chapters(project):  # one entry per book file, reading order
        ok, why = classify(key, items)
        words = sum(len((it.source_text or "").split()) for it in items)
        prev = _story_before(rows)
        if not ok and why == "not a chapter" and prev:
            last = _TAGS.sub("", next((it.source_text for it in reversed(prev["items"])
                                       if (it.source_text or "").strip()), "")).strip()
            if words >= CONTINUATION_WORDS:
                ok, why = True, "story continuation"
            elif prev is rows[-1] and re.match(r"^part\b", last, re.I):     # right after the part heading
                ok, why = True, "part subtitle"
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
        project = cache_io.load_cache(cache_path)
        why = skip_reason(project)
        if why:
            return {"skipped": why, "excluded": 0, "restored": 0, "skipped_translated": 0, "rows": []}
        helpers.backup_file(cache_path)
        rows = plan(project, keep, drop)
        changed = skipped = restored = 0
        for r in rows:
            if r["id"] in keep:             # --keep also undoes an earlier exclusion (untranslated segments only)
                for it in r["items"]:
                    if it.translation_status == TranslationStatus.EXCLUDED and not (it.translated_text or "").strip():
                        it.translation_status = TranslationStatus.UNTRANSLATED
                        restored += 1
            if r["keep"] and r["why"] != "part subtitle":
                continue
            # a part-subtitle file keeps its title; the all-italic lines after it are the epigraph
            items = [it for it in r["items"][1:] if _EPIGRAPH.match((it.source_text or "").strip())] \
                if r["keep"] else r["items"]
            for it in items:
                if it.translation_status == TranslationStatus.EXCLUDED:
                    continue
                if it.translation_status != TranslationStatus.UNTRANSLATED and not force:
                    skipped += 1
                    continue
                it.translation_status = TranslationStatus.EXCLUDED
                changed += 1
        cache_io.save_cache(project, cache_path)
    return {"excluded": changed, "restored": restored, "skipped_translated": skipped, "rows": rows}


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
        if res.get("skipped"):
            print(res["skipped"])
            return 0
        _print(res["rows"])
        print(f"excluded {res['excluded']} segments"
              + (f"; restored {res['restored']} (--keep)" if res["restored"] else "")
              + (f"; left {res['skipped_translated']} already-translated ones (use --force)" if res["skipped_translated"] else ""))
    else:
        project = cache_io.load_cache(a.cache)
        why = skip_reason(project)
        if why:
            print(why)
            return 0
        _print(plan(project, set(a.keep), set(a.drop)))
        print("preview only — add --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
