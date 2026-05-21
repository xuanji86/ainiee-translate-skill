import json
import os
import pytest
from ainiee_translate import profile, module

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AINIEE_TRANSLATE_HOME", str(tmp_path))
    return tmp_path


def test_import_profile_creates_module(home):
    d = profile.import_profile(os.path.join(FIX, "profile.json"), "demo")
    # module.json
    mj = json.loads(open(os.path.join(d, "module.json"), encoding="utf-8").read())
    assert mj["origin"]["type"] == "profile"
    assert mj["source_language"] == "English" and mj["target_language"] == "简体中文"
    assert mj["switches"]["writing_style"] is True
    # glossary: terms + non_translate from exclusion_list_data
    locked = json.loads(open(os.path.join(d, "glossary.locked.json"), encoding="utf-8").read())
    assert {"Korin", "Highmark"} <= {t["src"] for t in locked["terms"]}
    assert "Alpha Centauri III" in {n["marker"] for n in locked["non_translate"]}
    # translate prompt = system prompt + user blocks + writing style
    tp = open(os.path.join(d, "translate_prompt.md"), encoding="utf-8").read()
    assert "军衔后置于姓名" in tp and "写作风格" in tp
    # polish prompt present (profile has one)
    pp = open(os.path.join(d, "polish_prompt.md"), encoding="utf-8").read()
    assert "把初译润色得更自然" in pp
    # importable -> shows up in list
    assert "demo" in [m["name"] for m in module.list_modules()]


def test_import_refuses_overwrite_without_force(home):
    profile.import_profile(os.path.join(FIX, "profile.json"), "dup")
    with pytest.raises(FileExistsError):
        profile.import_profile(os.path.join(FIX, "profile.json"), "dup")
    # --force succeeds (old folder backed up)
    profile.import_profile(os.path.join(FIX, "profile.json"), "dup", force=True)


def test_target_language_override(home):
    d = profile.import_profile(os.path.join(FIX, "profile.json"), "fr", target_language="Français")
    mj = json.loads(open(os.path.join(d, "module.json"), encoding="utf-8").read())
    assert mj["target_language"] == "Français"
