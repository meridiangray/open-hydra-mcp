"""A short task_checkout reply, and the cross-process extracted-text cache (disk, by content)."""
import json
import os

import pytest

from hydra_mcp import core, files, server


def _docx(path, text):
    import docx
    d = docx.Document()
    d.add_paragraph(text)
    d.save(str(path))
    return path


def test_checkout_is_short_by_default_and_full_with_details(tmp_path):
    arch = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)["archive"]
    tid = server.task_new("Short", workflow="enrich", confirm=True, context="general", archive=arch)["id"]
    short = server.task_checkout(tid, archive=arch)
    assert short["id"] == tid and short["title"] == "Short" and short["route"] and short["counts"]["total"]
    assert short["next_step"] and all(" " not in s for s in short["steps"])      # codes only
    assert "file" not in short and "start_snapshot" not in short
    full = server.task_checkout(tid, archive=arch, force=True, details=True)
    assert isinstance(full["steps"][0], dict) and "text" in full["steps"][0] and "file" in full
    assert len(json.dumps(short)) < len(json.dumps(full)) * 0.6


def test_task_new_reply_stays_small(tmp_path):
    arch = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)["archive"]
    out = server.task_new("Small", workflow="enrich", confirm=True, context="general", archive=arch)
    assert len(json.dumps(out)) < 2000


def test_cache_hit_across_processes_and_isolation(tmp_path, monkeypatch):
    assert str(files.cache_dir()).startswith(os.environ["HYDRA_CACHE_DIR"])      # tests never use the real folder
    f = _docx(tmp_path / "a.docx", "Bo Grant met Al Ray.")
    first = files.read(f)
    assert list((files.cache_dir() / "text").glob("*.docx.*.json"))
    files._BY_CONTENT.clear()                                                   # a new process
    monkeypatch.setattr(files, "_read", lambda *a: pytest.fail("extracted again"))
    copy = tmp_path / "copy.docx"
    copy.write_bytes(f.read_bytes())
    again = files.read(copy)
    assert again["text"] == first["text"] and again["name"] == "copy.docx"


def test_corrupt_entry_is_rebuilt(tmp_path):
    f = _docx(tmp_path / "b.docx", "Corrupt me.")
    files.read(f)
    key = (files.hashlib.sha256(f.read_bytes()).hexdigest(), ".docx")
    entry = files._disk(key, ".docx")
    assert entry.is_file()
    for bad in ("{not json", json.dumps({"text": ""}), json.dumps([1])):
        entry.write_text(bad, encoding="utf-8")
        files._BY_CONTENT.clear()
        assert files.read(f)["text"] == "Corrupt me."
        assert json.loads(entry.read_text(encoding="utf-8"))["text"] == "Corrupt me."


def test_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "CACHE_KEEP", 3)
    for i in range(6):
        files.read(_docx(tmp_path / f"{i}.docx", f"document number {i}"))
    assert len(list((files.cache_dir() / "text").glob("*.json"))) == 3
    assert not list((files.cache_dir() / "text").glob("*.tmp"))
