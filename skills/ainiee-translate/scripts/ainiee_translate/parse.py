"""Parse an input folder/file into a CacheProject.

Self-contained by default (vendored readers via io_dispatch). For formats not
shipped natively (e.g. PDF / Office), set AINIEE_REPO to fall back to AiNiee."""
import argparse
import os
from pathlib import Path
from . import cache_io, io_dispatch


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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse input -> cache.json")
    ap.add_argument("--input", required=True)
    ap.add_argument("--type", default="AutoType")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--out", default="cache.json")
    a = ap.parse_args(argv)
    proj = parse_input(a.input, a.type, a.exclude)
    cache_io.save_cache(proj, a.out)
    print(f"parsed {proj.count_items()} items -> {a.out}")


if __name__ == "__main__":
    main()
