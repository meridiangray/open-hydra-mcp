"""Source profiles and chunked reading, wave 1 (owner, 2026-11-21): a long file is measured once and read by part."""
import json

import pytest

from hydra_mcp import core, files, profile, server


def _report(tmp_path, sections=6, paras=14):
    """A long plain-text report: a contents page, numbered paragraphs under roman-numeral sections, a running head."""
    out = ["CENTRAL REVIEW BOARD", "Contents", *(f"{r}. Section {r} . . . . . {i * 3 + 1}" for i, r in enumerate("I II III IV V VI".split()[:sections])), ""]
    n = 1
    for i, r in enumerate("I II III IV V VI".split()[:sections]):
        out += ["CENTRAL REVIEW BOARD", "", f"{r}. Section {r} of the Findings", ""]
        for _ in range(paras):
            out += [f"{n}. In 1985 the board found that the office kept its files in order and reported each loss "
                    f"to the director without delay, as the rules required at the time of paragraph {n}." * 3, ""]
            n += 1
    out += ["Index", "", "board, 1-4"]
    f = tmp_path / "report.txt"
    f.write_text("\n".join(out), encoding="utf-8")
    return f


def test_a_long_file_gives_its_profile_first_then_reads_by_part(tmp_path):
    f = _report(tmp_path)
    first = server.read_file(str(f))
    assert "text" not in first and len(first["parts"]) > 1 and first["next"].startswith("take the parts")
    assert all(p["chars"] <= profile.PART for p in first["parts"])
    assert first["structure"]["numbered_paragraphs"]["last"] == 84
    assert "CENTRAL REVIEW BOARD" not in {h["text"] for h in first["structure"]["headings"]}      # a running head
    assert any(h["text"].startswith("II. Section II") for h in first["structure"]["headings"])
    text = f.read_text(encoding="utf-8")
    got, n = "", len(first["parts"])
    for k in range(1, n + 1):
        part = server.read_file(str(f), part=k)
        assert part["part"] == k and part["parts"] == n and len(part["text"]) <= profile.PART
        got += text[len(got):part["start"]] + part["text"]                                     # parts cover the text in order
        assert part["next"].startswith("all parts read" if k == n else f"read_file(path, part={k + 1})")
    assert files.read(f)["text"].endswith(got[-200:])
    with pytest.raises(ValueError, match="part 1 to"):
        server.read_file(str(f), part=n + 1)


def test_a_short_file_comes_back_whole(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("A short note about Bo Grant.", encoding="utf-8")
    out = server.read_file(str(f))
    assert out["text"] == "A short note about Bo Grant." and out["next_offset"] is None


def test_the_profile_is_kept_by_content_and_source_profile_matches(tmp_path):
    f = _report(tmp_path)
    p = server.source_profile(str(f))
    cached = list((files.cache_dir() / "profiles").glob(f"{p['sha1']}.v{profile.VERSION}.json"))
    assert cached and json.loads(cached[0].read_text(encoding="utf-8"))["parts"] == p["parts"]
    copy = tmp_path / "copy.txt"
    copy.write_bytes(f.read_bytes())
    again = server.source_profile(str(copy))
    assert again["parts"] == p["parts"] and again["name"] == "copy.txt"
    assert any("numbered paragraphs" in w for w in p["warnings"]) and any("parts of about" in w for w in p["warnings"])


def test_a_pdf_text_is_extracted_once_per_machine(tmp_path, monkeypatch):
    """The disk copy is read when this process has none: another process's extraction is reused."""
    f = tmp_path / "x.txt"
    f.write_text("plain", encoding="utf-8")
    key = ("abc", ".pdf")
    files._to_disk(key, ".pdf", {"text": "kept", "type": "application/pdf"})
    assert files._from_disk(key, ".pdf")["text"] == "kept"


def test_checkout_sends_a_one_line_checklist(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    arch = out["archive"]
    tid = server.task_new("Short checkout", workflow="enrich", confirm=True, context="general", archive=arch)["id"]
    co = server.task_checkout(tid, archive=arch)
    assert co["steps"] and all(isinstance(s, str) for s in co["steps"]) and co["next_step"]
    full = server.task_checkout(tid, archive=arch, force=True, details=True)
    assert isinstance(full["steps"][0], dict)
