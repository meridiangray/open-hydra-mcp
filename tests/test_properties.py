"""The properties, extra_fields and field_assign tools: a type's fields by theme with Wikidata codes, fields outside FtM
kept and marked, assigned later. The catalogue is a small fixture; nothing here reaches the network."""
import asyncio
import json

import pytest

from hydra.cli import main as cli
from hydra import layout
from hydra_mcp import core, server

CATALOGUE = {"fetched": "2026-11-21T00:00:00+00:00", "source": "sparql", "count": 3, "properties": {
    "P569": {"label": "date of birth", "description": "when born", "aliases": ["born", "birthday"], "datatype": "time",
             "subject_types": ["Q5"], "equivalents": []},
    "P1449": {"label": "nickname", "description": "informal name", "aliases": [], "datatype": "monolingualtext",
              "subject_types": ["Q5"], "equivalents": []},
    "P856": {"label": "official website", "description": "", "aliases": ["homepage"], "datatype": "url",
             "subject_types": [], "equivalents": []}}}


def call(name, **args):
    out = asyncio.run(server.mcp.call_tool(name, args))
    block = out[0] if isinstance(out, tuple) else out
    content = block[0] if isinstance(block, (list, tuple)) else getattr(block, "content", [block])[0]
    return json.loads(content.text)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path / "config" / "wikidata" / "properties.json"


@pytest.fixture
def catalogue(machine):
    machine.parent.mkdir(parents=True)
    machine.write_text(json.dumps(CATALOGUE), encoding="utf-8")


@pytest.fixture
def archive(tmp_path, machine):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    out = core.ingest(root, [{"schema": "Person", "properties": {"name": "Ann Lee", "nickname": "Annie", "shoeSize": "38"}},
                             {"schema": "Person", "properties": {"name": "Bob Roe", "nickname": "Bobby", "born": "1950-02-03"}}],
                      {"text": "Ann Lee and Bob Roe.", "title": "A note"}, "people")
    assert out["saved"], out
    return root


def test_properties_of_a_type_by_theme_with_codes(archive, catalogue):
    got = call("properties", schema="Person", archive=str(archive))
    by = {r["prop"]: r for r in got["properties"]}
    assert by["birthDate"]["theme"] == "Dates" and by["birthDate"]["wd"] == "P569" and by["birthDate"]["common"]
    assert by["nationality"]["theme"] == "Geography" and by["name"]["required"]
    assert {"schema": "Ownership", "role": "owner", "other": "asset", "range": "Asset", "edge": True} in got["links"]
    dates = call("properties", schema="Person", level="all", theme="Dates", archive=str(archive))
    assert dates["properties"] and all(r["theme"] == "Dates" for r in dates["properties"]) and "links" not in dates
    assert call("properties", archive=str(archive))["themes"][0] == "Geography"
    assert "refused" in call("properties", schema="Persn", archive=str(archive))["error"]


def test_a_search_and_a_code(archive, catalogue):
    got = call("properties", query="birth date", archive=str(archive))
    assert any(f["schema"] == "Person" and f["prop"] == "birthDate" for f in got["fields"])
    assert got["wikidata"][0]["code"] == "P569"
    one = call("properties", code="p569", archive=str(archive))
    assert one["entry"]["label"] == "date of birth" and {"schema": "Person", "prop": "birthDate"} in one["fields"]
    assert call("properties", code="P1449", archive=str(archive))["fields"] == []
    assert "error" in call("properties", code="birth", archive=str(archive))


def test_without_a_catalogue_the_answer_says_what_to_do(archive):
    got = call("properties", query="website", archive=str(archive))
    assert got["wikidata"] == {"catalogue": "missing", "do": "the person runs hydra-ctl wikidata properties --fetch"}
    assert any(f["prop"] == "website" for f in got["fields"])
    assert call("extra_fields", archive=str(archive))["catalogue"]["catalogue"] == "missing"


def test_extra_fields_lists_what_was_kept(archive, catalogue):
    got = call("extra_fields", archive=str(archive))
    by = {f["field"]: f for f in got["fields"]}
    assert by["nickname"]["records"] == 2 and by["nickname"]["candidates"][0]["code"] == "P1449"
    assert by["born"]["candidates"][0]["code"] == "P569" and by["shoeSize"]["candidates"] == []
    assert got["catalogue"]["count"] == 3


def test_field_assign_previews_then_confirms(archive, catalogue):
    f = archive / layout.COLLECTIONS_DIR / "people.json"
    before = f.read_bytes()
    prev = call("field_assign", field="born", schema="Person", to="Person.birthDate", archive=str(archive))
    assert prev["preview"]["records"] == 1 and "confirm" in prev and f.read_bytes() == before
    done = call("field_assign", field="born", schema="Person", to="Person.birthDate", confirm=True, archive=str(archive))
    assert done["saved"] and done.get("undo", "").startswith("history restore")
    bob = next(r for r in json.loads(f.read_text(encoding="utf-8")) if r["properties"]["name"] == ["Bob Roe"])
    assert bob["properties"]["birthDate"] == ["1950-02-03"] and "born" not in bob["_meta"]["extra"]
    refused = call("field_assign", field="shoeSize", schema="Person", to="Person.birthDate", archive=str(archive))
    assert refused["error"] == "refused" and "do not fit" in refused["why"]
    new = call("field_assign", field="nickname", schema="Person", to="new:nickname", wd="P1449", confirm=True,
               archive=str(archive))
    assert new["saved"] and "nickname" in (archive / layout.EXTENSIONS_DIR / "archive.yaml").read_text(encoding="utf-8")
    assert call("extra_fields", archive=str(archive))["fields"][0]["field"] == "shoeSize"
    gone = call("field_assign", field="shoeSize", schema="Person", to="drop", confirm=True, archive=str(archive))
    assert gone["saved"] and call("extra_fields", archive=str(archive))["fields"] == []
    # the new property is an ordinary field now: a save with it checks clean, no finding
    rep = core.check_records(archive, [{"schema": "Person", "properties": {"name": "Cy", "nickname": "C"}}])
    assert rep["ok"] and not rep["extra_fields"]
