"""Parse an input folder/file into a CacheProject using AiNiee's FileReader."""
import argparse
from .ainiee_lib import load
from . import cache_io


def parse_input(input_path: str, project_type: str = "AutoType", exclude_rule: str = ""):
    reader = load().FileReader()
    return reader.read_files(project_type, input_path, exclude_rule)


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
