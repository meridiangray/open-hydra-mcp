"""The data tools: archive settings, collection shaping, graph questions, tags, image credits, export and pack."""
import json

import pytest

from hydra import collections_io, layout
from hydra.cli import main as cli
from hydra_mcp import core, data, server

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    src = {"text": "Ann Lee is a member of Acme Corp since 2010 until 2015. Acme Corp owns Beta Ltd. Embassy of Utopia in Paris.",
           "title": "A note"}
    out = core.ingest(root, [P("Person", name="Ann Lee"), P("Company", name="Acme Corp"), P("Company", name="Beta Ltd"),
                             P("PublicBody", name="Embassy of Utopia in Paris")], src, "a")
    assert out["saved"], out
    out = core.ingest(root, [P("Membership", member="Ann Lee", organization="Acme Corp", startDate="2010", endDate="2015"),
                             P("Ownership", owner="Acme Corp", asset="Beta Ltd")], src, "b")
    assert out["saved"], out
    return root


def tool_names():
    return {t.name for t in server.mcp._tool_manager.list_tools()}


def test_the_tools_are_registered():
    assert {"archive_settings", "collection_create", "collection_rename", "collection_merge", "move_records",
            "set_collection_group", "neighbors", "paths", "tags", "export", "pack"} <= tool_names()


def test_settings_read_preview_then_write_one_step(archive):
    got = data.archive_settings(archive)
    assert got["settings"]["name"] == "case" and "views" in got
    pre = data.archive_settings(archive, {"about": "A small case", "rail_shape": "circle"})
    assert pre["written"] == 0 and set(pre["changes"]) == {"about", "rail_shape"} and "next" in pre
    assert data.archive_settings(archive)["settings"]["about"] == ""
    done = data.archive_settings(archive, {"about": "A small case", "rail_shape": "circle"}, confirm=True)
    assert done["written"] == 2 and done["snapshot"]
    assert data.archive_settings(archive)["settings"]["rail_shape"] == "circle"
    again = data.archive_settings(archive, {"about": "A small case"}, confirm=True)
    assert again["written"] == 0


def test_settings_errors_use_the_error_shape(archive):
    for bad in ({"colour": "red"}, {"view": "nonsense"}, {"name": ""}, {"about": "x" * 400}):
        out = data.archive_settings(archive, bad, confirm=True)
        assert set(out) == {"error", "why", "do"}, bad


def test_collection_tools_preview_confirm_and_refuse(archive):
    pre = data.collection_rename(archive, "a", "people")
    assert pre["changed"] is False and (archive / layout.COLLECTIONS_DIR / "a.json").is_file()
    done = data.collection_rename(archive, "a", "people", confirm=True)
    assert done["changed"] and collections_io.names(archive) == ["b", "people"]
    out = data.collection_merge(archive, "people", "nope")
    assert set(out) == {"error", "why", "do"}
    first = collections_io.read(collections_io.path(archive, "people"))[0][0]["id"]
    moved = data.move_records(archive, [first], "b", confirm=True)
    assert moved["changed"] and moved["moves"] == 1
    assert data.set_collection_group(archive, "g", ["b", "people"], "Both", confirm=True)["changed"]


def test_neighbors_paths_and_edge_fields(archive):
    from hydra import graphquery as g
    ann = g.neighbors(archive, "Ann Lee")
    assert [n["title"] for n in ann["nodes"]] == ["Ann Lee", "Acme Corp"]
    e = ann["edges"][0]
    assert e["type"] == "Membership" and e["start"] == "2010" and e["end"] == "2015" and e["record"] and e["from"].startswith("H-")
    assert len(g.neighbors(archive, "Ann Lee", depth=2)["nodes"]) == 3
    assert not g.neighbors(archive, "Ann Lee", as_of="2020")["edges"]
    assert g.neighbors(archive, "Ann Lee", as_of="2012")["edges"]
    assert not g.neighbors(archive, "Ann Lee", edges=["Ownership"])["edges"]
    p = g.paths(archive, "Ann Lee", "Beta Ltd")
    assert [x["hops"] for x in p["paths"]] == [2] and [n["title"] for n in p["paths"][0]["nodes"]] == ["Ann Lee", "Acme Corp", "Beta Ltd"]
    assert p["paths"][0]["steps"][1]["links"][0]["type"] == "Ownership"
    assert g.paths(archive, "Ann Lee", "Beta Ltd", max_hops=1)["paths"] == []
    assert g.paths(archive, "Ann Lee", "Embassy of Utopia in Paris")["note"]
    for bad in (lambda: g.neighbors(archive, "Nobody Here"), lambda: g.neighbors(archive, "Ann Lee", depth=9),
                lambda: g.paths(archive, "Ann Lee", "Ann Lee"), lambda: g.neighbors(archive, "Ann Lee", edges=["Nope"])):
        with pytest.raises(g.GraphError) as err:
            bad()
        assert err.value.as_dict().keys() == {"error", "why", "do"}


def test_tags_report_fit_reasons_and_decision(archive):
    from hydra import graphquery as g
    t = g.tags(archive, "Embassy of Utopia in Paris")
    row = next(r for r in t["tags"] if r["id"] == "diplomatic-mission")
    assert row["score"] > 0 and any("name says" in s for s in row["shows"]) and row["decision"] == "undecided"
    from hydra_mcp import labelling
    labelling.label(archive, ["Embassy of Utopia in Paris"], "tag:diplomatic-mission", confirm=True)
    row = next(r for r in g.tags(archive, "Embassy of Utopia in Paris")["tags"] if r["id"] == "diplomatic-mission")
    assert row["decision"] == "confirmed" and row["fits"]


def test_link_image_writes_the_credit_beside_the_image(archive, tmp_path):
    img = tmp_path / "ann.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    credit = {"author": "A. Photographer", "licence": "CC BY 4.0", "url": "https://example.org/ann"}
    pre = core.link_image(archive, str(img), "portrait", {"name": "Ann Lee"}, False, credit)
    assert pre["credit"] == {"artist": "A. Photographer", "licence": "CC BY 4.0", "commons": "https://example.org/ann"}
    assert not (archive / layout.RESOURCES_DIR / "portraits").exists()
    done = core.link_image(archive, str(img), "portrait", {"name": "Ann Lee"}, True, credit)
    assert done["added"] and done["snapshot"]
    side = archive / layout.RESOURCES_DIR / "portraits" / "ann.png.credit.json"
    assert json.loads(side.read_text(encoding="utf-8")) == pre["credit"]
    for bad in ({"author": "x", "mood": "y"}, {"url": "javascript:alert(1)"}, {"author": " "}):
        with pytest.raises(core.IngestError):
            core.link_image(archive, str(img), "portrait", {"name": "Ann Lee"}, False, bad)


def test_link_images_takes_credits_and_one_step(archive, tmp_path):
    from hydra_mcp import agent
    img = tmp_path / "acme.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 20)
    out = agent.link_images(archive, [{"image": str(img), "kind": "logo", "name": "Acme Corp",
                                       "credit": {"author": "Acme", "licence": "own work"}}], confirm=True)
    assert out["added"] == 1 and out["snapshot"]
    side = archive / layout.RESOURCES_DIR / "logos" / "acme.png.credit.json"
    assert json.loads(side.read_text(encoding="utf-8")) == {"artist": "Acme", "licence": "own work"}


def test_export_and_pack_stay_inside_the_named_folder(archive, tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    pre = data.export_(archive, "ftm", "case.jsonl", str(out_dir))
    assert pre["written"] is False and not (out_dir / "case.jsonl").exists()
    done = data.export_(archive, "ftm", "case.jsonl", str(out_dir), confirm=True)
    assert done["written"] and (out_dir / "case.jsonl").is_file() and done["report"]["entities"] > 0
    again = data.export_(archive, "ftm", "case.jsonl", str(out_dir), confirm=True)
    assert again["error"] == "file exists"
    assert data.export_(archive, "csv", "graph", str(out_dir), confirm=True)["written"] and (out_dir / "graph" / "nodes.csv").is_file()
    for bad in ("../escape.jsonl", str(tmp_path / "elsewhere.jsonl"), "sub/../../x.jsonl", ".."):
        r = data.export_(archive, "ftm", bad, str(out_dir), confirm=True)
        assert r["error"] == "outside the folder" and set(r) == {"error", "why", "do"}, bad
    assert not (tmp_path / "escape.jsonl").exists() and not (tmp_path / "elsewhere.jsonl").exists()
    assert data.export_(archive, "ftm", "x.jsonl", None)["error"] == "no folder named"
    assert data.export_(archive, "pdf", "x", str(out_dir))["error"] == "unknown format"
    p = data.pack_(archive, "case", str(out_dir), confirm=True)
    assert p["written"] and (out_dir / "case.hydra").is_file() and p["files"] > 0
    assert data.pack_(archive, "../case", str(out_dir))["error"] == "outside the folder"
    assert data.pack_(archive, "case", str(out_dir))["error"] == "file exists"


def test_read_page_links_a_place_valued_field_to_its_place_entry():
    from types import SimpleNamespace
    from hydra_mcp import pipeline
    pages = {"p": {"schema": "Person", "title": "Ann", "h": "H-p", "infobox": [
                 {"prop": "birthPlace", "label": "Birth place", "values": [{"value": "Jeddah"}]},
                 {"prop": "spouse", "label": "Spouse", "values": [{"value": "Bo", "h": "b"}]}]},
             "j": {"schema": "Place", "title": "Jeddah", "h": "H-j"}, "b": {"schema": "Person", "title": "Bo", "h": "H-b"}}
    w = SimpleNamespace(pages=pages, listed=set(pages), title=lambda b: pages[b]["title"])
    rows = pipeline._link_places(w, pages["p"], [{"label": "Born", "value": "Jeddah"}, {"label": "Spouse", "value": "Bo"}])
    assert rows[0]["links"] == [{"text": "Jeddah", "h": "H-j", "title": "Jeddah"}]
    assert rows[1]["links"][0]["h"] == "H-b"
