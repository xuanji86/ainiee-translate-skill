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
