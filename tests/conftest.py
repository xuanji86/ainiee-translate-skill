import os, sys
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

@pytest.fixture
def ainiee_repo():
    path = os.environ.get("AINIEE_REPO", "/Users/Anji/Desktop/AiNiee")
    if not os.path.isdir(os.path.join(path, "ModuleFolders")):
        pytest.skip(f"AINIEE_REPO not found at {path}")
    return path


@pytest.fixture
def make_project():
    """Build a CacheProject from the vendored types (no AiNiee repo needed).
    make_project(n=3) -> items 1..n with source "line i"; or pass sources=[...]."""
    from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
    from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheFile import CacheFile
    from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem

    def _make(n=3, storage="a.txt", sources=None, **proj_kw):
        srcs = sources if sources is not None else [f"line {i}" for i in range(1, n + 1)]
        f = CacheFile(storage_path=storage)
        f.items = [CacheItem(text_index=i, source_text=s) for i, s in enumerate(srcs, 1)]
        return CacheProject(files={storage: f}, **proj_kw)

    return _make
