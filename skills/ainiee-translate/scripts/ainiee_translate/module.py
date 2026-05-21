"""Translation modules: reusable per-task bundles (prompts + glossary + style).

A module is a folder under the modules root (default ~/.ainiee-translate/modules/,
overridable via $AINIEE_TRANSLATE_HOME) containing module.json + translate_prompt.md
[+ polish_prompt.md, glossary.locked.json, style.md, examples.json].

`load` copies a module's files into a project's work/ dir under the names the
rest of the pipeline already consumes (glossary.locked.json, user_prompt.md,
polish_prompt.md), so the existing linear workflow is unchanged.
"""
import argparse
import json
import os
import shutil
import time

from . import helpers

SCHEMA_VERSION = 1

# Module-relative filenames (the on-disk schema), defined once to avoid drift
# between write_module_json (which records them) and load_module (which copies them).
TRANSLATE_PROMPT = "translate_prompt.md"
POLISH_PROMPT = "polish_prompt.md"
GLOSSARY_LOCKED = "glossary.locked.json"
STYLE = "style.md"
EXAMPLES = "examples.json"
# Name the translate step consumes inside a project's work/ dir
WORK_USER_PROMPT = "user_prompt.md"


def home() -> str:
    return os.environ.get("AINIEE_TRANSLATE_HOME", os.path.expanduser("~/.ainiee-translate"))


def modules_root() -> str:
    return os.path.join(home(), "modules")


def module_dir(name: str) -> str:
    return os.path.join(modules_root(), name)


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def list_modules() -> list[dict]:
    root = modules_root()
    active = (_read_json(os.path.join(home(), "active.json"), {}) or {}).get("active_module")
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            mj = _read_json(os.path.join(root, name, "module.json"))
            if mj is None:
                continue
            out.append({"name": name, "title": mj.get("title", name),
                        "source_language": mj.get("source_language", ""),
                        "target_language": mj.get("target_language", ""),
                        "has_polish": os.path.exists(os.path.join(root, name, POLISH_PROMPT)),
                        "active": name == active})
    return out


def show_module(name: str) -> dict:
    d = module_dir(name)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"module not found: {name}")
    mj = _read_json(os.path.join(d, "module.json"), {}) or {}
    locked = _read_json(os.path.join(d, GLOSSARY_LOCKED), {}) or {}
    files = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    return {"name": name, "module": mj, "files": files,
            "terms": len(locked.get("terms", [])),
            "characters": len(locked.get("characters", [])),
            "non_translate": len(locked.get("non_translate", []))}


def create_module(name: str, source_language="", target_language="", title="") -> str:
    d = module_dir(name)
    os.makedirs(d, exist_ok=True)
    mj_path = os.path.join(d, "module.json")
    if not os.path.exists(mj_path):
        write_module_json(d, name, source_language=source_language,
                          target_language=target_language, title=title or name,
                          origin={"type": "manual"})
    for fn in (TRANSLATE_PROMPT, POLISH_PROMPT, STYLE):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            open(p, "w", encoding="utf-8").close()
    gl = os.path.join(d, GLOSSARY_LOCKED)
    if not os.path.exists(gl):
        with open(gl, "w", encoding="utf-8") as f:
            json.dump({"characters": [], "terms": [], "non_translate": []}, f, ensure_ascii=False, indent=2)
    return d


def write_module_json(d: str, name: str, *, source_language="", target_language="",
                      title="", switches=None, origin=None) -> None:
    mj = {"schema_version": SCHEMA_VERSION, "name": name, "title": title or name,
          "source_language": source_language, "target_language": target_language,
          "translate_prompt": TRANSLATE_PROMPT, "polish_prompt": POLISH_PROMPT,
          "glossary_locked": GLOSSARY_LOCKED, "style": STYLE,
          "examples": EXAMPLES, "switches": switches or {},
          "origin": origin or {"type": "manual"}}
    with open(os.path.join(d, "module.json"), "w", encoding="utf-8") as f:
        json.dump(mj, f, ensure_ascii=False, indent=2)


def _copy_in(src: str, dst: str) -> bool:
    if not os.path.exists(src):
        return False
    if os.path.exists(dst):
        helpers.backup_file(dst)
    shutil.copy2(src, dst)
    return True


def load_module(name: str, work: str | None = None) -> dict:
    d = module_dir(name)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"module not found: {name}")
    os.makedirs(home(), exist_ok=True)
    with open(os.path.join(home(), "active.json"), "w", encoding="utf-8") as f:
        json.dump({"active_module": name}, f, ensure_ascii=False, indent=2)
    copied = []
    if work:
        wdir = os.path.join(work, "work")
        os.makedirs(wdir, exist_ok=True)
        # module file -> name the existing pipeline steps consume in work/
        mapping = {GLOSSARY_LOCKED: GLOSSARY_LOCKED,
                   TRANSLATE_PROMPT: WORK_USER_PROMPT,
                   POLISH_PROMPT: POLISH_PROMPT}
        for src_name, dst_name in mapping.items():
            if _copy_in(os.path.join(d, src_name), os.path.join(wdir, dst_name)):
                copied.append(dst_name)
        with open(os.path.join(wdir, "active_module.json"), "w", encoding="utf-8") as f:
            json.dump({"module": name, "module_dir": d,
                       "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
    return {"module": name, "module_dir": d, "work": work, "copied": copied}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Manage ainiee-translate modules")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("name")
    create = sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--source-language", default="")
    create.add_argument("--target-language", default="")
    create.add_argument("--title", default="")
    load = sub.add_parser("load")
    load.add_argument("name")
    load.add_argument("--work", default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            print(json.dumps(list_modules(), ensure_ascii=False, indent=2))
        elif a.cmd == "show":
            print(json.dumps(show_module(a.name), ensure_ascii=False, indent=2))
        elif a.cmd == "create":
            d = create_module(a.name, a.source_language, a.target_language, a.title)
            print(f"created module -> {d}")
        elif a.cmd == "load":
            r = load_module(a.name, a.work)
            print(json.dumps(r, ensure_ascii=False))
    except (FileNotFoundError, OSError) as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()
