"""Export a translated CacheProject to output files using AiNiee's FileOutputer.

Note: some AiNiee writers read config.json via WriterUtil.get_ainiee_config().
We pass an explicit output config; if a writer still needs config.json and none
exists, surface the error rather than silently producing nothing."""
import argparse
from .ainiee_lib import load, repo_path
from . import cache_io

DEFAULT_CONFIG = {
    "translated_suffix": "_translated",
    "bilingual_suffix": "_bilingual",
    "bilingual_order": "translation_first",
}

# Attributes that BaseWriter reads from the global WriterUtil config singleton,
# and the safe defaults to use when no config.json is present on this machine.
_WRITER_CONFIG_DEFAULTS = {
    "keep_original_encoding": False,  # False → always write UTF-8 output
}


def _ensure_writer_config() -> None:
    """Seed required WriterUtil config attributes so export never depends on an
    ambient config.json.  Safe to call multiple times; only sets attributes that
    are genuinely missing or None."""
    import sys
    repo = repo_path()
    if repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        from ModuleFolders.Domain.FileOutputer import WriterUtil
        cfg = WriterUtil.get_ainiee_config()
        for attr, default in _WRITER_CONFIG_DEFAULTS.items():
            if getattr(cfg, attr, None) is None:
                setattr(cfg, attr, default)
    except Exception:
        # If AiNiee internals change or the import fails, don't block export —
        # the underlying writer will surface its own error with full context.
        pass


def export_project(project, output_path: str, input_path: str, config: dict | None = None) -> None:
    _ensure_writer_config()
    outputer = load().FileOutputer()
    outputer.output_translated_content(project, output_path, input_path, config or DEFAULT_CONFIG)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export cache.json -> output files")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--input", required=True)
    a = ap.parse_args(argv)
    proj = cache_io.load_cache(a.cache)
    export_project(proj, a.output, a.input)
    print(f"exported -> {a.output}")


if __name__ == "__main__":
    main()
