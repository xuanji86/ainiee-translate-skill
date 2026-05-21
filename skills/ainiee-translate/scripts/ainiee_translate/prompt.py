"""Surface the user's OWN translation prompt from AiNiee config.

This is the AiNiee-native way to let users write their own rules instead of
baking them into the skill: a custom system prompt, character profiles,
writing style, world-building and few-shot examples — each gated by its
`*_switch` flag in config.json. The skill applies whatever the user wrote
here ON TOP of the generic native prompt (references/translation_rules.md)
and the locked glossary.
"""
import argparse
import json


def _load_cfg(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt(config_path: str = None, cfg: dict = None) -> str:
    """Assemble the user's active custom-prompt blocks from an AiNiee config.
    Pass an already-parsed `cfg` to avoid re-reading the file."""
    if cfg is None:
        cfg = _load_cfg(config_path)

    blocks: list[str] = []

    # 1. custom system / translation prompt(s) — the user's own rules
    for p in cfg.get("translation_user_prompt_data", []) or []:
        content = (p.get("content") or "").strip()
        if content:
            name = p.get("name") or "自定义"
            blocks.append(f"## 用户自定义翻译提示词（{name}）\n{content}")

    # 2. character profiles (角色介绍)
    if cfg.get("characterization_switch") and cfg.get("characterization_data"):
        lines = []
        for c in cfg["characterization_data"]:
            orig = (c.get("original_name") or "").replace("[Separator]", " ").strip()
            tr = (c.get("translated_name") or "").strip()
            head = f"{orig} → {tr}".strip(" →")
            extra = [f"{k}：{c[k]}" for k in
                     ("gender", "age", "personality", "speech_style", "additional_info")
                     if c.get(k)]
            lines.append("- " + "；".join([head] + extra) if head else "- " + "；".join(extra))
        if lines:
            blocks.append("## 角色介绍\n" + "\n".join(lines))

    # 3. writing style (写作风格)
    if cfg.get("writing_style_switch") and (cfg.get("writing_style_content") or "").strip():
        blocks.append("## 写作风格\n" + cfg["writing_style_content"].strip())

    # 4. world-building (世界观设定)
    if cfg.get("world_building_switch") and (cfg.get("world_building_content") or "").strip():
        blocks.append("## 世界观设定\n" + cfg["world_building_content"].strip())

    # 5. few-shot examples (翻译示例)
    if cfg.get("translation_example_switch") and cfg.get("translation_example_data"):
        ex = []
        for e in cfg["translation_example_data"]:
            src = e.get("src") or e.get("source") or ""
            dst = e.get("dst") or e.get("translation") or ""
            if src or dst:
                ex.append(f"- 原文：{src}\n  译文：{dst}")
        if ex:
            blocks.append("## 翻译示例\n" + "\n".join(ex))

    return "\n\n".join(blocks)


def build_translate_prompt(config_path: str = None, cfg: dict = None) -> str:
    """Return the user's selected translation SYSTEM prompt
    (`translation_prompt_selection.prompt_content`), or "" if none."""
    if cfg is None:
        cfg = _load_cfg(config_path)
    return (cfg.get("translation_prompt_selection", {}) or {}).get("prompt_content", "").strip()


def build_polish_prompt(config_path: str = None, cfg: dict = None) -> str:
    """Assemble the user's POLISH prompt blocks from an AiNiee config/profile:
    the selected polish system prompt, any custom polish prompts, and the
    switch-gated polish style. Returns "" when there is no polish config."""
    if cfg is None:
        cfg = _load_cfg(config_path)

    blocks: list[str] = []
    selected = (cfg.get("polishing_prompt_selection", {}) or {}).get("prompt_content", "").strip()
    if selected:
        blocks.append(selected)
    else:
        for p in cfg.get("polishing_user_prompt_data", []) or []:
            content = (p.get("content") or "").strip()
            if content:
                name = p.get("name") or "自定义"
                blocks.append(f"## 用户自定义润色提示词（{name}）\n{content}")
    if cfg.get("polishing_style_switch") and (cfg.get("polishing_style_content") or "").strip():
        blocks.append("## 润色风格\n" + cfg["polishing_style_content"].strip())
    return "\n\n".join(blocks)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Assemble translation/polish prompts from an AiNiee config.json or profile.json")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None, help="write to file instead of stdout")
    ap.add_argument("--translate-system", action="store_true",
                    help="emit only the selected translation system prompt")
    ap.add_argument("--polish", action="store_true", help="emit the polish prompt instead")
    a = ap.parse_args(argv)
    if a.polish:
        text = build_polish_prompt(a.config)
    elif a.translate_system:
        text = build_translate_prompt(a.config)
    else:
        text = build_user_prompt(a.config)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"prompt -> {a.out} ({len(text)} chars)")
    else:
        print(text if text else "(no matching prompt in config)")


if __name__ == "__main__":
    main()
