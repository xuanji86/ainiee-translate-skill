import json
import os
from ainiee_translate.prompt import build_user_prompt, build_translate_prompt, build_polish_prompt

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_build_user_prompt_assembles_active_blocks(tmp_path):
    cfg = {
        "translation_user_prompt_data": [
            {"id": "x", "name": "MyBook", "content": "人名保留英文；军衔后置于姓名。"}
        ],
        "writing_style_switch": True,
        "writing_style_content": "对话简洁直接。",
        "world_building_switch": False,
        "world_building_content": "（关闭，不应出现）",
        "characterization_switch": True,
        "characterization_data": [
            {"original_name": "Jack", "translated_name": "Jack", "gender": "M",
             "personality": "沉稳"}
        ],
        "translation_example_switch": False,
        "translation_example_data": [],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = build_user_prompt(str(p))
    assert "用户自定义翻译提示词（MyBook）" in out
    assert "军衔后置于姓名" in out          # the user's own rule is surfaced
    assert "写作风格" in out and "对话简洁直接" in out
    assert "角色介绍" in out and "Jack" in out
    assert "不应出现" not in out             # switched-off block omitted


def test_build_user_prompt_empty_when_nothing_active(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"translation_user_prompt_data": []}), encoding="utf-8")
    assert build_user_prompt(str(p)) == ""


def test_build_translate_prompt_returns_selected_system_prompt():
    out = build_translate_prompt(os.path.join(FIX, "profile.json"))
    assert "军衔后置于姓名" in out          # from translation_prompt_selection.prompt_content


def test_build_polish_prompt_assembles_polish_blocks():
    out = build_polish_prompt(os.path.join(FIX, "profile.json"))
    assert "把初译润色得更自然" in out      # polishing_prompt_selection.prompt_content
    assert "润色风格" in out and "命令句简洁有力" in out


def test_build_polish_prompt_empty_when_no_polish_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"prompt_dictionary_data": []}), encoding="utf-8")
    assert build_polish_prompt(str(p)) == ""


def test_translate_system_does_not_leak_into_user_prompt():
    # build_user_prompt must stay unchanged: it ignores translation_prompt_selection
    out = build_user_prompt(os.path.join(FIX, "profile.json"))
    assert "用户自定义翻译提示词（MyBook）" in out and "写作风格" in out
    assert "polishing" not in out.lower()
