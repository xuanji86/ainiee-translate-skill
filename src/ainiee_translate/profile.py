"""Import an AiNiee profile JSON (a config superset) into a reusable module.

A profile carries the user's whole task setup: source/target language, the
selected translate & polish prompts, custom prompt blocks, glossary
(prompt_dictionary_data), exclusion list, writing style / world / characters.
This one-shot extracts all of it into ~/.ainiee-translate/modules/<name>/.
"""
import argparse
import json
import os
import shutil
import time

from . import glossary_seed, glossary, prompt, module


def import_profile(profile_path: str, name: str, target_language: str | None = None,
                   force: bool = False) -> str:
    with open(profile_path, encoding="utf-8") as f:
        prof = json.load(f)

    d = module.module_dir(name)
    if os.path.isdir(d) and os.listdir(d):
        if not force:
            raise FileExistsError(f"module '{name}' already exists (use --force to overwrite)")
        shutil.move(d, f"{d}.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(d, exist_ok=True)

    # exclusion_list_data also feeds non_translate (see glossary_seed.load_seed)
    seed = glossary_seed.load_seed(profile_path, cfg=prof)
    locked = glossary.build_locked(seed)
    with open(os.path.join(d, "glossary.locked.json"), "w", encoding="utf-8") as f:
        json.dump(locked, f, ensure_ascii=False, indent=2)

    parts = [p for p in (prompt.build_translate_prompt(cfg=prof),
                         prompt.build_user_prompt(cfg=prof)) if p]
    with open(os.path.join(d, "translate_prompt.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts))

    polish = prompt.build_polish_prompt(cfg=prof)  # only written if the profile has one
    if polish:
        with open(os.path.join(d, "polish_prompt.md"), "w", encoding="utf-8") as f:
            f.write(polish)

    switches = {k: bool(prof.get(f"{k}_switch")) for k in
                ("characterization", "writing_style", "world_building",
                 "translation_example", "polishing_style")}
    module.write_module_json(
        d, name,
        source_language=prof.get("source_language", ""),
        target_language=target_language or prof.get("target_language", ""),
        title=name, switches=switches,
        origin={"type": "profile", "imported_from": os.path.abspath(profile_path),
                "imported_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import an AiNiee profile JSON into a module")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="profile.json -> module")
    imp.add_argument("--profile", required=True)
    imp.add_argument("--name", required=True)
    imp.add_argument("--target-language", default=None)
    imp.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "import":
        try:
            d = import_profile(a.profile, a.name, a.target_language, a.force)
        except (FileExistsError, OSError, json.JSONDecodeError) as e:
            ap.error(str(e))
        print(f"imported profile -> module {a.name} ({d})")


if __name__ == "__main__":
    main()
