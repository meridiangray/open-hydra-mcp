"""The Suggestions tools: the same list as the wiki, local only; applying runs the tool a suggestion names."""
import socket

import pytest

from hydra.cli import main as cli
from hydra_mcp import core, server, suggestions

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture(autouse=True)
def register(monkeypatch):
    """The local register is installed per machine: a fixed answer stands in for it."""
    from hydra import suggest
    monkeypatch.setattr(suggest, "places_for", lambda root, text, countries: [
        {"key": "geonames:4692883", "name": "Galveston", "level": "settlement", "placeType": "city",
         "within": ["iso3166:US"], "score": 1.0}] if text.startswith("Galveston") else [])


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    src = tmp_path / "a.txt"
    src.write_text("Bo Grant was born in Galveston, Texas. Ann Lee is the Prime Minister.", encoding="utf-8")
    core.ingest(root, [P("Person", name="Bo Grant", birthPlace="Galveston, Texas", nationality="us"),
                       P("Person", name="Ann Lee", position="Prime Minister"),
                       P("Position", name="Prime Minister")], {"file": str(src)}, "a")
    return root


def test_tools_are_registered():
    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert {"suggestions", "cast", "enrichers", "probe", "apply_suggestion", "dismiss_suggestion"} <= names


def test_suggestions_are_local_and_name_the_tool_that_writes_them(archive, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    out = suggestions.suggestions(archive, "Bo Grant")
    loc = next(s for s in out["suggestions"] if s["rule"] == "locate")
    assert loc["label"] == "Locate" and loc["apply"]["tool"] == "site"
    assert {s["rule"] for s in out["suggestions"]} >= {"locate", "wikidata-find"}
    assert [s["id"] for s in suggestions.suggestions(archive, "Ann Lee")["suggestions"] if s["rule"] == "appoint"]
    assert suggestions.cast(archive, "Bo Grant", "locate", "Zzyzx Qwerty")["candidates"] == []
    assert {e["label"] for e in suggestions.enrichers(archive)["enrichers"]} >= {"Compare", "Match", "Lead"}


def test_apply_previews_then_writes_through_the_named_tool(archive):
    loc = next(s for s in suggestions.suggestions(archive, "Bo Grant")["suggestions"] if s["rule"] == "locate")
    pre = suggestions.apply(archive, "Bo Grant", loc["id"])
    assert pre["tool"] == "site" and pre["next"] and "result" not in pre
    done = suggestions.apply(archive, "Bo Grant", loc["id"], confirm=True)
    assert done["result"]["written"] >= 1
    with pytest.raises(core.IngestError, match="probe"):
        suggestions.apply(archive, "Bo Grant", "wikidata-find")


def test_dismiss_previews_then_hides(archive):
    assert suggestions.dismiss(archive, "Bo Grant", "wikidata-find")["would_dismiss"] == "wikidata-find"
    assert "wikidata-find" in {s["rule"] for s in suggestions.suggestions(archive, "Bo Grant")["suggestions"]}
    suggestions.dismiss(archive, "Bo Grant", "wikidata-find", confirm=True)
    assert "wikidata-find" not in {s["rule"] for s in suggestions.suggestions(archive, "Bo Grant")["suggestions"]}
    with pytest.raises(core.IngestError, match="not a suggestion"):
        suggestions.dismiss(archive, "Bo Grant", "nope", confirm=True)


def test_match_picks_a_candidate_and_writes_the_key_through_pin_upstream(archive, monkeypatch):
    from hydra import suggest
    hits = [{"qid": "Q1", "label": "Bo Grant", "description": "a"}, {"qid": "Q2", "label": "Bo Grant", "description": "b"}]
    monkeypatch.setitem(suggest.SOURCES, "wikidata.search", lambda page, req: {"query": req.get("query") or "Bo Grant", "hits": hits})
    out = suggestions.probe(archive, "Bo Grant", "wikidata-find", query="Bo Grant Texas", raw=True)
    assert out["raw"]["query"] == "Bo Grant Texas" and len(out["mapped"]["candidates"]) == 2
    pre = suggestions.apply(archive, "Bo Grant", "wikidata-find", {"candidate": 1})
    assert pre["tool"] == "pin_upstream" and pre["args"]["h"] == "wikidata:Q2" and "result" not in pre
    done = suggestions.apply(archive, "Bo Grant", "wikidata-find", {"candidate": 1}, confirm=True)
    assert done["result"]["key"] == "wikidata:Q2" and done["result"]["pinned"] is True
    assert "wikidata" in {s["rule"] for s in suggestions.suggestions(archive, "wikidata:Q2")["suggestions"]}


def test_wikidata_purge_previews_then_removes(archive):
    from hydra import build
    from hydra.universe import build as ubuild
    import json
    f = archive / "collections" / "wikidata.json"
    f.write_text(json.dumps([{"id": "Q9", "schema": "Person", "properties": {
        "name": ["Bo Grant"], "upstream": ["wikidata:Q9"], "birthDate": ["1950"], "sources": ["Q9-wikidata"]}},
        {"id": "Q9-wikidata", "schema": "Article", "properties": {"title": ["Wikidata: Bo Grant (Q9)"]}}]), encoding="utf-8")
    build.build_archive(archive)
    ubuild.build(archive)
    out = suggestions.wikidata_purge(archive, "wikidata:Q9")
    assert out["would_purge"]["records"] and "next" in out and f.is_file()
    done = suggestions.wikidata_purge(archive, "wikidata:Q9", confirm=True)
    assert done["purged"]["docs"] and not f.exists()
    assert "wikidata_purge" in {t.name for t in server.mcp._tool_manager.list_tools()}
