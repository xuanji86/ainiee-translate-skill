"""Build the raw (pre-clean) seed from AiNiee's public glossary (config.json
prompt_dictionary_data) plus an optional project analysis_v1 cache."""
import json


def load_seed(config_path: str, analysis_cache_path: str | None = None,
              cfg: dict | None = None) -> dict:
    terms, characters, non_translate = [], [], []
    if cfg is None:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    for e in cfg.get("prompt_dictionary_data", []) or []:
        terms.append({"src": e.get("src", ""), "dst": e.get("dst", ""),
                      "category": e.get("info", "")})
    # AiNiee exclusion list (禁翻表) -> non_translate. Profiles use plural "markers";
    # normalize to the singular "marker" shape the rest of the pipeline expects.
    for x in cfg.get("exclusion_list_data", []) or []:
        marker = x.get("markers") or x.get("marker") or ""
        if marker:
            non_translate.append({"marker": marker, "category": x.get("info", ""),
                                  "regex": bool(x.get("regex"))})
    if analysis_cache_path:
        with open(analysis_cache_path, encoding="utf-8") as f:
            a = (json.load(f).get("extra", {}) or {}).get("analysis_v1", {}) or {}
        characters = a.get("characters", []) or []
        for t in a.get("terms", []) or []:
            terms.append({"src": t.get("source", ""), "dst": t.get("recommended_translation", ""),
                          "category": t.get("category_path", "")})
        non_translate.extend(a.get("non_translate", []) or [])
    return {"terms": terms, "characters": characters, "non_translate": non_translate}
