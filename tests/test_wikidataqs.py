"""The `wikidata` toolset (owner, 2026-11-21): the archive's entries put to the person as Wikidata questions; a confirmed
match pins its key and brings its picture; "none" stops asking. Wikidata itself is faked: no network."""
import socket

import pytest

from hydra.cli import main as cli
from hydra_mcp import core, server, toolsets, wikidataqs as W

P = lambda s, **p: {"schema": s, "properties": p}
HITS = {"Bo Grant": [{"qid": "Q1", "label": "Bo Grant", "description": "American rancher"},
                     {"qid": "Q2", "label": "Bo Grant", "description": "Texas politician (1950-2010)"}],
        "Ann Lee": [{"qid": "Q7", "label": "Ann Lee", "description": "religious leader (1736-1784)"}]}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    from hydra.enrich import suggest
    monkeypatch.setattr(suggest, "places_for", lambda root, text, countries: [])
    monkeypatch.setitem(suggest.SOURCES, "wikidata.search",
                        lambda page, req: {"query": page["title"], "hits": HITS.get(page["title"], [])})
    monkeypatch.setitem(suggest.SOURCES, "wikidata.P18",
                        lambda page, req: {"qid": "Q2", "file": "Bo Grant 1990.jpg", "licence": "CC BY-SA 4.0",
                                           "artist": "A. Photographer", "licence_url": "https://creativecommons.org/licenses/by-sa/4.0"})
    monkeypatch.setattr(suggest, "_get_image", lambda url: (b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg"))
    real = socket.socket.connect

    def refuse(self, addr, *a, **k):            # Wikidata is faked; only loopback is allowed
        if isinstance(addr, tuple) and str(addr[0]) not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"network used: {addr}")
        return real(self, addr, *a, **k)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    src = tmp_path / "a.txt"
    src.write_text("Bo Grant was born in Texas in 1950. Ann Lee led the meeting.", encoding="utf-8")
    core.ingest(root, [P("Person", name="Bo Grant", birthDate="1950", nationality="us"), P("Person", name="Ann Lee")],
                {"file": str(src)}, "a")
    return root


def test_the_toolset_is_registered_and_off_by_default():
    names = {t.name for t in server.mcp._tool_manager.list_tools()} | set(toolsets._state(server.mcp).all)
    assert {"wikidata_questions", "wikidata_answer", "wikidata_status"} <= names
    assert toolsets.TOOL_SET["wikidata_answer"] == "wikidata"


def test_questions_carry_what_the_archive_says_and_the_candidates(archive):
    out = W.questions(archive)
    assert out["open"] == 2 and out["next_offset"] is None
    bo = next(q for q in out["questions"] if q["entity"] == "Bo Grant")
    assert bo["archive_says"]["birthDate"] == ["1950"] and bo["archive_says"]["type"] == "Person"
    assert [c["qid"] for c in bo["candidates"]] == ["Q1", "Q2"] and bo["candidates"][1]["n"] == 1
    assert len(W.questions(archive, limit=1)["questions"]) == 1 and W.questions(archive, limit=1)["next_offset"] == 1


def test_a_confirmed_match_pins_the_key_and_brings_the_picture(archive):
    W.questions(archive)
    pre = W.answer(archive, "Bo Grant", "Q2")
    assert "matched" not in pre and pre["match"]["qid"] == "Q2" and "pin wikidata:Q2" in pre["would"][0]
    assert W.status(archive)["matched"] == 0                                    # a preview writes nothing
    done = W.answer(archive, "Bo Grant", "q2", confirm=True)
    assert done["matched"] == "Q2" and done["pinned"]["key"] == "wikidata:Q2"
    assert done["picture"]["imported"] is True, done["picture"]
    assert done["picture"]["licence"] == "CC BY-SA 4.0"
    st = W.status(archive)
    assert st["matched"] == 1 and st["open"] == 1
    with pytest.raises(core.IngestError, match="not among"):
        W.answer(archive, "Ann Lee", "Q99")


def test_none_stops_the_entry_being_asked(archive):
    W.questions(archive)
    assert "would" in W.answer(archive, "Ann Lee", "none")
    W.answer(archive, "Ann Lee", "none", confirm=True)
    st = W.status(archive)
    assert st["answered_none"] == 1 and st["open"] == 1
    assert [q["entity"] for q in W.questions(archive)["questions"]] == ["Bo Grant"]
