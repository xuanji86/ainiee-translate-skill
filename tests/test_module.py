import json
import os
import pytest
from ainiee_translate import module


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AINIEE_TRANSLATE_HOME", str(tmp_path))
    return tmp_path


def test_create_then_list_then_show(home):
    module.create_module("demo", source_language="English", target_language="简体中文", title="Demo")
    names = [m["name"] for m in module.list_modules()]
    assert names == ["demo"]
    info = module.show_module("demo")
    assert info["module"]["target_language"] == "简体中文"
    assert info["terms"] == 0 and info["characters"] == 0
    assert "translate_prompt.md" in info["files"]


def test_load_copies_into_work_and_sets_active(home, tmp_path):
    d = module.create_module("demo")
    # give the module some content to copy
    with open(os.path.join(d, "translate_prompt.md"), "w", encoding="utf-8") as f:
        f.write("RULES")
    with open(os.path.join(d, "polish_prompt.md"), "w", encoding="utf-8") as f:
        f.write("POLISH")
    work = tmp_path / "proj"
    r = module.load_module("demo", str(work))
    wdir = work / "work"
    assert (wdir / "glossary.locked.json").exists()
    assert (wdir / "user_prompt.md").read_text(encoding="utf-8") == "RULES"   # translate prompt -> user_prompt.md
    assert (wdir / "polish_prompt.md").read_text(encoding="utf-8") == "POLISH"
    bound = json.loads((wdir / "active_module.json").read_text(encoding="utf-8"))
    assert bound["module"] == "demo"
    # global active.json flipped
    active = json.loads((home / "active.json").read_text(encoding="utf-8"))
    assert active["active_module"] == "demo"
    assert "user_prompt.md" in r["copied"]


def test_load_no_work_only_flips_active(home):
    module.create_module("demo")
    module.load_module("demo", work=None)
    active = json.loads((home / "active.json").read_text(encoding="utf-8"))
    assert active["active_module"] == "demo"


def test_load_missing_module_raises(home):
    with pytest.raises(FileNotFoundError):
        module.load_module("nope")
