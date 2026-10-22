"""Export a translated CacheProject to output files.

Self-contained by default (vendored writers via io_dispatch). For formats not
shipped natively (e.g. PDF / Office), set AINIEE_REPO to fall back to AiNiee."""
import argparse
import os
from pathlib import Path
from . import cache_io, io_dispatch

DEFAULT_CONFIG = {
    "translated_suffix": "_translated",
    "bilingual_suffix": "_bilingual",
    "bilingual_order": "translation_first",
}


def export_project(project, output_path: str, input_path: str, config: dict | None = None) -> None:
    config = config or DEFAULT_CONFIG
    exts = {Path(sp).suffix.lstrip(".").lower() for sp in project.files}
    if not exts <= set(io_dispatch.EXT_CANDIDATES) and os.environ.get("AINIEE_REPO"):
        _export_via_ainiee(project, output_path, input_path, config)   # PDF/Office/etc.
    else:
        io_dispatch.export_project(project, output_path, input_path, config)


def _export_via_ainiee(project, output_path, input_path, config) -> None:
    """Fallback for formats not shipped natively (requires AINIEE_REPO)."""
    import sys
    from .ainiee_lib import load, repo_path
    repo = repo_path()
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        from ModuleFolders.Domain.FileOutputer import WriterUtil
        cfg = WriterUtil.get_ainiee_config()
        if getattr(cfg, "keep_original_encoding", None) is None:
            cfg.keep_original_encoding = False
    except Exception:
        pass
    load().FileOutputer().output_translated_content(project, output_path, input_path, config)


def main(argv=None):
    import json
    ap = argparse.ArgumentParser(description="Export cache.json -> output files")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--finalize", action="store_true",
                    help="epub: target-language metadata, fixed identifier, link/anchor/paragraph checks "
                         "(settings in work/export.json; see finalize.py)")
    ap.add_argument("--title")
    ap.add_argument("--name", help="deliverable file name (no extension); default: <source>_translated")
    ap.add_argument("--deliver", help="also copy the finalized epub here (e.g. the CHN folder)")
    a = ap.parse_args(argv)
    proj = cache_io.load_cache(a.cache)
    export_project(proj, a.output, a.input)
    print(f"exported -> {a.output}")
    if a.finalize:
        from . import finalize
        stem = Path(a.input).stem
        raw = os.path.join(a.output, f"{stem}{DEFAULT_CONFIG['translated_suffix']}.epub")
        if not os.path.exists(raw):
            ap.error(f"--finalize: no exported epub at {raw}")
        cfg = finalize.load_config(a.cache, {"title": a.title, "name": a.name, "deliver": a.deliver})
        out = os.path.join(a.output, f"{cfg['name']}.epub") if cfg.get("name") else raw
        print(json.dumps(finalize.finalize(raw, out, a.cache, cfg), ensure_ascii=False))


if __name__ == "__main__":
    main()
