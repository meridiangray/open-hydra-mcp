"""Tool behaviour found by the acceptance runs: amend previews and scopes its checks, save adds, thin pages are
not kept, a source can be dropped, probe and get_records answer short, task ids hold between preview and create."""
import asyncio
import json

import pytest

from hydra.cli import main as cli
from hydra_mcp import agent, core, server, sources, suggestions, workflows as wf

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    out = core.ingest(root, [P("Person", name="Ann Lee"), P("Person", name="Bo Rue"), P("Company", name="Acme Corp"),
                             P("Directorship", director="Ann Lee", organization="Acme Corp", role="director")],
                      {"text": "Ann Lee and Bo Rue. Ann Lee directs Acme Corp.", "title": "A note"}, "a")
    assert out["saved"], out
    return root


def stored(root, coll="a"):
    return json.loads((root / f"collections/{coll}.json").read_text(encoding="utf-8"))


def call(name, args):
    r = asyncio.run(server.mcp.call_tool(name, args))
    return r


def test_amend_previews_until_confirmed_and_trims(archive):
    ann = next(r for r in stored(archive) if r["properties"].get("name") == ["Ann Lee"])
    rec = {"id": ann["id"], "schema": "Person", "properties": {"name": ["Ann Lee"], "gender": ["female"]}}
    before = (archive / "collections/a.json").read_bytes()
    pre = agent.amend_records(archive, "a", [rec], confirm=False)
    assert pre["saved"] is False and pre["preview"] and pre["diff"][ann["id"]]["gender"]["new"] == ["female"]
    assert (archive / "collections/a.json").read_bytes() == before
    done = agent.amend_records(archive, "a", [rec], confirm=True)
    assert done["saved"] and next(r for r in stored(archive) if r["id"] == ann["id"])["properties"]["gender"] == ["female"]
    assert isinstance(done["ambiguous_links"], int)                      # a count unless details


def test_amend_ignores_problems_in_other_records(archive):
    f = archive / "collections/a.json"
    recs = stored(archive)
    bo = next(r for r in recs if r["properties"].get("name") == ["Bo Rue"])
    bo["properties"]["sources"] = ["doc-gone"]                           # a pre-existing dangling citation, elsewhere
    f.write_text(json.dumps(recs), encoding="utf-8")
    ann = next(r for r in recs if r["properties"].get("name") == ["Ann Lee"])
    out = agent.amend_records(archive, "a", [{"id": ann["id"], "schema": "Person",
                                              "properties": {"name": ["Ann Lee"], "gender": ["female"]}}])
    assert out["saved"] and "elsewhere" in out and "1 error" in out["elsewhere"]
    bad = agent.amend_records(archive, "a", [{"id": ann["id"], "schema": "Person",
                                              "properties": {"name": ["Ann Lee"], "sources": ["doc-nope"]}}])
    assert bad["saved"] is False and any("doc-nope" in e for e in bad["errors"])


def test_unknown_arguments_are_refused_with_error_why_do(archive):
    r = call("amend_records", {"collection": "a", "changes": [], "archive": str(archive)})
    body = json.loads(r.content[0].text)
    assert r.isError and set(body) == {"error", "why", "do"} and "changes" in body["why"]


def test_save_add_appends_and_refuses_an_existing_id(archive):
    have = len(stored(archive))
    out = core.ingest(archive, [P("Person", name="Cy Vale")], {"text": "Cy Vale.", "title": "More"}, "a", mode="add")
    assert out["saved"] and len(stored(archive)) == have + 1
    dup = core.ingest(archive, [{"id": stored(archive)[0]["id"], **P("Person", name="Dee Fox")}],
                      {"text": "Dee Fox.", "title": "Again"}, "a", mode="add")
    assert dup["saved"] is False and any("already used" in e for e in dup["errors"])
    with pytest.raises(core.IngestError):
        core.ingest(archive, [P("Person", name="Eve Ray")], {"text": "Eve Ray."}, "a", replace=True, mode="add")
    with pytest.raises(core.IngestError):
        core.ingest(archive, [P("Person", name="Eve Ray")], {"text": "Eve Ray."}, "nowhere", mode="add")


def test_a_thin_page_is_not_kept_unless_asked_and_a_source_can_be_dropped(archive):
    thin = {"url": "https://example.org/", "title": "Home", "text": "Welcome\nNews\nAbout", "publisher": "example.org",
            "kind": "html"}
    got = sources.fetch(archive, thin["url"], prefetched=thin, keep_thin=False)
    assert got["kept"] is False and got["quality"] == "thin" and got["reason"]
    kept = sources.fetch(archive, thin["url"], prefetched=thin, keep_thin=True)
    assert kept["kept"] and kept["quality"] == "thin"
    sid = kept["source_id"]
    pre = sources.drop(archive, sid)
    assert "next" in pre and sources.citers(archive, core._existing_source(archive, sid)) == []
    sources.drop(archive, sid, confirm=True)
    with pytest.raises(core.IngestError):
        core._existing_source(archive, sid)
    ann = next(r for r in stored(archive) if r["properties"].get("name") == ["Ann Lee"])
    cited = ann["properties"]["sources"][0]
    with pytest.raises(core.IngestError) as e:
        sources.drop(archive, cited, confirm=True)
    assert ann["id"] in str(e.value)


def test_an_article_is_not_thin():
    body = "\n".join("This is a long sentence about the subject that goes on for a good while longer." for _ in range(12))
    assert sources.assess({"kind": "html", "url": "https://example.org/a/b", "text": body}) is None
    assert sources.assess({"kind": "wikitext", "url": "https://en.wikipedia.org/wiki/X", "text": "x"}) is None


def test_get_records_honours_query_ids_and_pages(archive):
    recs = stored(archive)
    ann = next(r for r in recs if r["properties"].get("name") == ["Ann Lee"])
    q = core.get_records(archive, "a", query="acme")
    assert q["matching"] >= 1 and all("acme" in json.dumps(e).lower() for e in q["entities"])
    by = core.get_records(archive, "a", ids=[ann["id"], "zzz"])
    assert [e["id"] for e in by["entities"]] == [ann["id"]] and by["not_found"] == ["zzz"]
    page = core.get_records(archive, "a", limit=1)
    assert page["returned"] == 1 and page["next_offset"] == 1


def test_explain_entity_takes_a_record_id_and_names_its_collection(archive):
    rel = next(r for r in stored(archive) if r["schema"] == "Directorship")
    out = agent.explain_entity(archive, rel["id"])
    assert out["collection"] == "a" and out["record"] == rel["id"]
    ann = next(r for r in stored(archive) if r["properties"].get("name") == ["Ann Lee"])
    assert agent.explain_entity(archive, ann["id"])["collections"] == ["a"]


def test_probe_is_a_summary_unless_raw(archive, monkeypatch):
    fake = {"enricher": "wikidata", "request": {}, "at": "now", "raw": {"huge": "x" * 1000},
            "mapped": {"qid": "Q1", "diff": [{"property": "birthDate", "now": None, "value": "1970", "reference": None}]}}
    monkeypatch.setattr(suggestions, "_body", lambda root, e: "body")
    monkeypatch.setattr(suggestions, "_s", lambda fn: fake)
    short = suggestions.probe(archive, "Ann", "wikidata")
    assert "raw" not in short and short["rows"] == [{"field": "birthDate", "now": None, "new": "1970", "reference": None}]
    assert suggestions.probe(archive, "Ann", "wikidata", raw=True)["raw"]


def test_a_task_preview_id_is_the_created_id(archive):
    pre = wf.task_new(archive, "Check", "enrich", None, None, ["Ann Lee"], False)
    made = wf.task_new(archive, "Check", "enrich", None, None, ["Ann Lee"], True)
    assert pre["id"] == made["id"]


def test_checkout_gives_a_count_not_the_file_list(archive, monkeypatch):
    made = wf.task_new(archive, "Check", "enrich", None, None, ["Ann Lee"], True)
    monkeypatch.setattr(wf, "details", lambda root: {"newer_than_build": ["a", "b", "c"]})
    out = wf.task_checkout(archive, made["id"])
    assert out["archive_details"]["newer_than_build_count"] == 3 and "newer_than_build" not in out["archive_details"]
    wf.task_release(archive)
    full = wf.task_checkout(archive, made["id"], details=True)
    assert full["archive_details"]["newer_than_build"] == ["a", "b", "c"]


def test_find_entities_and_readiness_are_one_document(archive):
    assert set(server.find_entities("Ann Lee", archive=str(archive))) == {"count", "entities"}
