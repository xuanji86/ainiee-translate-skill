import json
import os
import time
from ainiee_translate import cache_io, batch, progress
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheProject import CacheProject
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheFile import CacheFile
from ainiee_translate._vendor.ModuleFolders.Service.Cache.CacheItem import CacheItem


def _work(tmp_path):
    f = CacheFile(storage_path="b.epub")
    for i in range(1, 61):
        it = CacheItem(text_index=i, source_text=f"ch{(i - 1) // 20 + 1} line {i}", extra={"item_id": f"ch{(i - 1) // 20 + 1}"})
        if i <= 20:
            it.translated_text, it.translation_status = f"译{i}", 1
        f.items.append(it)
    proj = CacheProject(files={"b.epub": f}, project_id="t", project_name="Demo Book")
    work = tmp_path / "work"; par = work / "par"; par.mkdir(parents=True)
    cache_io.save_cache(proj, str(work / "cache.json"))
    for n, rng in ((1, range(21, 41)), (2, range(41, 61))):
        (par / f"grp_{n}_src.json").write_text(json.dumps([{"text_index": i, "source_text": f"line {i}"} for i in rng]), encoding="utf-8")
    # grp 1 complete + valid; grp 2 partial with a truncated trailing line (agent mid-append)
    (par / "trans_1.jsonl").write_text("".join(json.dumps({"text_index": i, "translated_text": f"译{i}"}) + "\n" for i in range(21, 41)), encoding="utf-8")
    (par / "trans_2.jsonl").write_text("".join(json.dumps({"text_index": i, "translated_text": f"译{i}"}) + "\n" for i in range(41, 48)) + '{"text_index": 48, "transl', encoding="utf-8")
    (par / "newterms_2.txt").write_text("Panora\nshakom-doka\n", encoding="utf-8")
    return work


def test_snapshot_states_and_tolerant_jsonl(tmp_path):
    work = _work(tmp_path)
    snap = progress.snapshot(str(work / "cache.json"))
    assert snap["total"]["done"] == 20 and snap["total"]["untranslated"] == 40
    g1, g2 = snap["groups"]
    assert g1["state"] == "ready" and g1["lines"] == 20 and g1["chapters"] == ["ch2"]
    assert g2["state"] == "running" and g2["lines"] == 7 and g2["bad_lines"] == 1 and g2["newterms"] == 2
    line = progress.one_line(snap)
    assert "20/60" in line and "▶2 7/20" in line and "✓1" in line


def test_stalled_and_written_and_needs_fix(tmp_path):
    work = _work(tmp_path)
    old = time.time() - 1000
    os.utime(work / "par" / "trans_2.jsonl", (old, old))
    snap = progress.snapshot(str(work / "cache.json"), stall_sec=180)
    assert snap["groups"][1]["state"] == "stalled"
    # write grp 1 -> written; break grp 2 into a complete-but-invalid file -> needs_fix
    batch.main(["write", str(work / "cache.json"), str(work / "par" / "trans_1.jsonl")])
    (work / "par" / "trans_2.jsonl").write_text("".join(json.dumps({"text_index": i, "translated_text": ("" if i == 45 else f"译{i}")}) + "\n" for i in range(41, 61)), encoding="utf-8")
    snap = progress.snapshot(str(work / "cache.json"))
    assert snap["groups"][0]["state"] == "written"
    assert snap["groups"][1]["state"] == "needs_fix" and snap["groups"][1]["seg_hard"] == 1
    # apply_writeback logged an event that the snapshot surfaces
    assert snap["events"] and snap["events"][-1]["applied"] == 20 and snap["events"][-1]["event"] == "write"


def test_render_and_rate(tmp_path):
    work = _work(tmp_path)
    s1 = progress.snapshot(str(work / "cache.json"))
    prev = {"ts": s1["ts"] - 60, "lines": progress._in_flight_lines(s1) - 6}
    assert abs(progress.rate_per_min(prev, s1) - 6.0) < 0.01
    from rich.console import Console
    out = Console(record=True, width=120)
    out.print(progress.render(s1, 6.0))
    txt = out.export_text()
    assert "Demo Book" in txt and "running" in txt and "ready" in txt and "ETA" in txt
