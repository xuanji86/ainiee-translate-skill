"""Query and small fixes on cache.json without ad-hoc scripts.

  cache stats <cache>                              segments per status
  cache show <cache> --range A-B [--status 0 7] [--width 120]
                                                   compact rows: idx  status  en | zh
  cache dump <cache> --range A-B --out seg.json [--changed-since OLD_CACHE] [--status 1 2]
                                                   [{i, en, zh}] for a review / editor agent
  cache set-status <cache> --range A-B --from 7 --to 0 [--apply]
                                                   e.g. bring an excluded interlude back into scope
  cache fill-dupes <cache> [--max-words 8] [--apply]
                                                   copy a translation to untranslated/excluded segments
                                                   with the same short source (contents page ← NCX);
                                                   goes through the write gate like `batch write`;
                                                   epub ⟦n⟧ placeholders are ignored when matching and
                                                   re-wrapped around the copy when they sit at the
                                                   ends of the target (mid-text ones are skipped, listed)
"""
import argparse
import collections
import json
import re

from . import cache_io, helpers
from .batch import parse_range, changed_indexes, make_check
from ._vendor.ModuleFolders.Domain.FileReader.EpubReader import TOKEN_RE
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus

_TAGS = re.compile(r"</?[a-z]+>", re.I)
LABEL = {0: "untranslated", 1: "translated", 2: "polished", 7: "excluded"}


def _sel(project, rng=None, statuses=None, only=None):
    for it in cache_io.iter_items(project):
        if rng and not rng[0] <= it.text_index <= rng[1]:
            continue
        if statuses and int(it.translation_status) not in statuses:
            continue
        if only is not None and it.text_index not in only:
            continue
        yield it


def stats(project) -> dict:
    c = collections.Counter(LABEL.get(int(it.translation_status), str(int(it.translation_status)))
                            for it in cache_io.iter_items(project))
    return dict(c)


def _norm(s: str) -> str:
    return " ".join(_TAGS.sub("", TOKEN_RE.sub("", s or "")).split()).lower()


_ENDS = re.compile(r"((?:\s*⟦/?\d+⟧)*)(.*?)((?:⟦/?\d+⟧\s*)*)", re.S)   # placeholders · text · placeholders


def _rewrap(source: str, bare: str) -> str | None:
    """`bare` inside the placeholders the target source has at its ends; None when one sits mid-text."""
    pre, mid, post = _ENDS.fullmatch(source or "").groups()
    if TOKEN_RE.search(mid):
        return None
    return "".join(TOKEN_RE.findall(pre)) + bare + "".join(TOKEN_RE.findall(post))


def fill_dupes(project, max_words: int = 8) -> tuple[list[tuple[int, int, str]], list[tuple[int, int]]]:
    """-> ([(target_idx, donor_idx, text)], [(target_idx, donor_idx) skipped: placeholder mid-text]).
    The donor's own placeholders are dropped and the target's are put back around the bare translation."""
    done = {}
    for it in cache_io.iter_items(project):
        if it.translation_status in (TranslationStatus.TRANSLATED, TranslationStatus.POLISHED):
            bare = TOKEN_RE.sub("", it.translated_text or "").strip()
            k = _norm(it.source_text)
            if bare and k and len(k.split()) <= max_words:
                done.setdefault(k, (it.text_index, bare))
    out, skipped = [], []
    for it in cache_io.iter_items(project):
        if it.translation_status in (TranslationStatus.UNTRANSLATED, TranslationStatus.EXCLUDED):
            hit = done.get(_norm(it.source_text))
            if hit:
                text = _rewrap(it.source_text, hit[1])
                if text is None:
                    skipped.append((it.text_index, hit[0]))
                else:
                    out.append((it.text_index, hit[0], text))
    return out, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="Query / small fixes on cache.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats").add_argument("cache")
    sh = sub.add_parser("show"); sh.add_argument("cache"); sh.add_argument("--range", required=True)
    sh.add_argument("--status", nargs="*", type=int); sh.add_argument("--width", type=int, default=120)
    du = sub.add_parser("dump"); du.add_argument("cache"); du.add_argument("--range")
    du.add_argument("--out", required=True); du.add_argument("--status", nargs="*", type=int, default=[1, 2])
    du.add_argument("--changed-since", metavar="OLD_CACHE")
    ss = sub.add_parser("set-status"); ss.add_argument("cache"); ss.add_argument("--range", required=True)
    ss.add_argument("--from", dest="frm", type=int, required=True, choices=sorted(LABEL))
    ss.add_argument("--to", type=int, required=True, choices=sorted(LABEL))
    ss.add_argument("--apply", action="store_true")
    fd = sub.add_parser("fill-dupes"); fd.add_argument("cache"); fd.add_argument("--max-words", type=int, default=8)
    fd.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        rng = parse_range(getattr(a, "range", None))
    except ValueError:
        ap.error(f"bad --range {a.range!r} (expected A-B)")

    if a.cmd == "set-status" and a.apply:
        with cache_io.locked(a.cache):
            project = cache_io.load_cache(a.cache)
            hit = [it for it in _sel(project, rng, {a.frm}) if a.to != a.frm]
            for it in hit:
                it.translation_status = a.to
            if hit:
                helpers.backup_file(a.cache)
                cache_io.save_cache(project, a.cache)
        print(f"set {len(hit)} segment(s) {a.frm} -> {a.to}")
        return 0
    if a.cmd == "fill-dupes" and a.apply:
        # the same gate as `batch write`: a donor with <i> must not land on a source without marks
        found, skipped = fill_dupes(cache_io.load_cache(a.cache), a.max_words)
        rows = [{"text_index": ti, "translated_text": text} for ti, _, text in found]
        open_ = (TranslationStatus.UNTRANSLATED, TranslationStatus.EXCLUDED)
        res = cache_io.apply_writeback(
            a.cache, rows, TranslationStatus.TRANSLATED, lambda r: r["translated_text"],
            check=make_check(cache_path=a.cache),
            guard=lambda item, text: None if item.translation_status in open_ else "already_translated")
        print(f"filled {res.applied} segment(s)" + (f"; rejected {len(res.rejected)}: {res.rejected[:20]}" if res.rejected else "")
              + (f"; skipped {len(skipped)} (placeholder mid-text, translate by hand): {[ti for ti, _ in skipped][:20]}" if skipped else ""))
        return 1 if res.rejected else 0

    project = cache_io.load_cache(a.cache)
    if a.cmd == "stats":
        print(json.dumps(stats(project), ensure_ascii=False))
    elif a.cmd == "show":
        w = a.width
        for it in _sel(project, rng, set(a.status) if a.status else None):
            en = " ".join((it.source_text or "").split())[:w]
            zh = " ".join((it.translated_text or "").split())[:w]
            print(f"{it.text_index:5d} {int(it.translation_status)}  {en}\n            {zh}")
    elif a.cmd == "dump":
        only = changed_indexes(project, a.changed_since) if a.changed_since else None
        rows = [{"i": it.text_index, "en": it.source_text or "", "zh": it.translated_text or ""}
                for it in _sel(project, rng, set(a.status) if a.status else None, only)]
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=0)
        print(f"dumped {len(rows)} segment(s) -> {a.out}")
    elif a.cmd == "set-status":
        n = sum(1 for _ in _sel(project, rng, {a.frm}))
        print(f"would set {n} segment(s) {a.frm} -> {a.to} (preview; add --apply)")
    elif a.cmd == "fill-dupes":
        rows, skipped = fill_dupes(project, a.max_words)
        for ti, donor, text in rows[:30]:
            print(f"{ti:5d} <- {donor:5d}  {text}")
        for ti, donor in skipped[:30]:
            print(f"{ti:5d} <- {donor:5d}  skipped, placeholder mid-text")
        print(f"{len(rows)} segment(s) would be filled, {len(skipped)} skipped (placeholder mid-text) (preview; add --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
