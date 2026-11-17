"""Parse an input folder/file into a CacheProject.

Self-contained by default (vendored readers via io_dispatch). For formats not
shipped natively (e.g. PDF / Office), set AINIEE_REPO to fall back to AiNiee."""
import argparse
import os
import sys
from pathlib import Path
from . import cache_io, helpers, io_dispatch
from ._vendor.ModuleFolders.Service.Cache.CacheItem import TranslationStatus


def _needs_ainiee(input_path: str, project_type: str) -> bool:
    """True when the input is a format we don't ship natively (e.g. PDF/Office)."""
    if project_type not in (set(io_dispatch.FORMATS) | {"AutoType"}):
        return True
    p = Path(input_path)
    return p.is_file() and p.suffix.lstrip(".").lower() not in io_dispatch.EXT_CANDIDATES


def parse_input(input_path: str, project_type: str = "AutoType", exclude_rule: str = ""):
    if _needs_ainiee(input_path, project_type) and os.environ.get("AINIEE_REPO"):
        from .ainiee_lib import load
        return load().FileReader().read_files(project_type, input_path, exclude_rule)
    return io_dispatch.parse_input(input_path, project_type, exclude_rule)


def save_parsed(proj, out: str, force: bool = False) -> int:
    """Write a freshly parsed project to `out`. Refuses (rc 1) to write an empty project, or to
    replace a cache that already holds work unless `force` (then the old one is backed up first)."""
    n = proj.count_items()
    if n == 0:
        print(f"parse failed: no translatable items found in {proj.input_path} (unsupported format?) "
              f"— {out} not written", file=sys.stderr)
        return 1
    if os.path.exists(out):
        with cache_io.locked(out):
            done = sum(1 for it in cache_io.iter_items(cache_io.load_cache(out))
                       if it.translation_status in (TranslationStatus.TRANSLATED, TranslationStatus.POLISHED)
                       or (it.translated_text or "").strip())
            if done and not force:
                print(f"parse refused: {out} already has {done} translated segment(s); re-parsing would wipe "
                      "them. Pick another --out, or --force to back it up and replace it.", file=sys.stderr)
                return 1
            if done:
                print(f"backup -> {helpers.backup_file(out)}")
            cache_io.save_cache(proj, out)
    else:
        cache_io.save_cache(proj, out)
    print(f"parsed {n} items -> {out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse input -> cache.json")
    ap.add_argument("--input", required=True)
    ap.add_argument("--type", default="AutoType")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--out", default="cache.json")
    ap.add_argument("--force", action="store_true",
                    help="replace an --out cache that already has translations (backed up first)")
    a = ap.parse_args(argv)
    return save_parsed(parse_input(a.input, a.type, a.exclude), a.out, a.force)


if __name__ == "__main__":
    raise SystemExit(main())
