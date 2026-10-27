"""hydra-mcp's ingestion logic, on fresh archives: what it reports, what it refuses,
and what it writes."""
import json

import pytest

from hydra import cli, layout
from hydra_mcp import core

TEXT = ("ACME TIMES, 3 May 2021. Dana Hale, administrator of the Port Authority, said her deputy "
        "Rob Kerr would lead the inquiry. Kerr was appointed VP of Operations at Harbor Coop in 2019.")

BATCH = [
    {"schema": "PublicBody", "properties": {"name": "Port Authority"}},
    {"schema": "Company", "properties": {"name": "Harbor Coop"}},
    {"schema": "Person", "properties": {"name": "Dana Hale"}},
    {"schema": "Person", "properties": {"name": ["Rob Kerr"], "weakAlias": ["Kerr"]}},
    {"schema": "Employment", "properties": {"employee": "Dana Hale", "employer": "Port Authority", "role": "administrator"}},
    {"schema": "Employment", "properties": {"employee": "Rob Kerr", "employer": "Port Authority", "role": "deputy"}},
    {"schema": "Employment", "properties": {"employee": "Rob Kerr", "employer": "Harbor Coop",
                                            "role": "VP of Operations", "startDate": "2019"}},
]


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli.main(["init", str(root), "--name", "case", "--prefix", "c"])
    return core.open_archive(str(root))


def test_the_hierarchy_in_effect_is_reported_with_or_without_a_custom_one(archive):
    assert core.hierarchy(archive)["mode"] == "defaults only"
    (archive / layout.POSITIONS).write_text("Vice president: {titles: [vp of operations]}\n", encoding="utf-8")
    assert core.hierarchy(archive)["mode"] == "custom and defaults"
    cli.main(["defaults", "off", str(archive), "generic"])
    h = core.hierarchy(archive)
    assert h["mode"] == "custom only" and [p["position"] for p in h["positions"]] == ["Vice president"]


def test_roles_rank_by_the_hierarchy_and_unranked_ones_are_reported_not_changed(archive):
    rep = core.check_records(archive, BATCH)
    assert rep["ok"], rep["errors"]
    ranks = {r["value"]: r["position"] for r in rep["roles"]}
    assert ranks == {"administrator": None, "deputy": "Second-in-command", "VP of Operations": None}
    assert any("'VP of Operations' takes no position" in w for w in rep["warnings"])
    assert rep["records"][6]["properties"]["role"] == ["VP of Operations"]          # kept as the text wrote it
    (archive / layout.POSITIONS).write_text(
        "Agency head: {titles: [administrator]}\nVice president: {titles: [vp of operations]}\n", encoding="utf-8")
    ranks = {r["value"]: r["position"] for r in core.check_records(archive, BATCH)["roles"]}
    assert ranks == {"administrator": "Agency head", "deputy": "Second-in-command", "VP of Operations": "Vice president"}


def test_errors_block_and_name_the_problem(archive):
    bad = [{"schema": "Persn", "properties": {"name": "X"}},
           {"schema": "Person", "properties": {"name": "Y", "colour": "red", "birthDate": "circa 1990", "portrait": "y.jpg"}},
           {"schema": "Membership", "properties": {"member": "Y"}},
           {"schema": "Thing", "properties": {"name": "Z"}},
           {"schema": "Person", "properties": {"alias": "No Name"}}]
    errs = " | ".join(core.check_records(archive, bad)["errors"])
    for part in ("no schema 'Persn'", "has no property 'colour'", "'circa 1990' is not a date",
                 "records never carry images", "a Membership needs `organization`", "Thing is abstract",
                 "a Person needs a `name`"):
        assert part in errs, part
    out = core.ingest(archive, bad, {"text": "x"}, "bad")
    assert out["saved"] is False and not (archive / layout.COLLECTIONS_DIR / "bad.json").exists()


def test_links_point_into_the_batch_the_archive_or_nowhere(archive):
    core.ingest(archive, BATCH[:3], {"text": TEXT}, "first")
    rep = core.check_records(archive, [
        {"schema": "Membership", "properties": {"member": "Dana Hale", "organization": "Port Authority"}},
        {"schema": "Membership", "properties": {"member": "Newcomer", "organization": "Port Authority"}}])
    where = {(l["value"], l["record"]): l["links_to"] for l in rep["links"]}
    assert "Dana Hale" in where[("Dana Hale", rep["records"][0]["id"])]          # an existing entity
    assert where[("Newcomer", rep["records"][1]["id"])] is None
    assert any("'Newcomer' is no record" in w for w in rep["warnings"])


def test_an_ingestion_stores_the_text_as_the_source_every_record_cites(archive):
    out = core.ingest(archive, BATCH, {"text": TEXT, "title": "Port inquiry", "url": "https://example.org/a",
                                       "published": "2021-05-03"}, "port-inquiry")
    assert out["saved"] and out["records"] == 7 and out["files"] == [
        "collections/port-inquiry.json", ".hydra/sources/entries/port-inquiry.json"]
    doc = json.loads((archive / out["files"][1]).read_text())[0]
    assert doc["schema"] == "Article" and doc["properties"]["bodyText"] == [TEXT]
    recs = json.loads((archive / out["files"][0]).read_text())
    ents = [r for r in recs if r["schema"] != "Employment"]
    assert all(r["properties"]["sources"] == ["port-inquiry-source"] for r in ents)
    assert not any("sources" in r["properties"] for r in recs if r["schema"] == "Employment")   # no such field
    assert not [i for i in out["issues"] if i["code"] == "records.unknown-property"]
    assert "Rebuilt" in out["build"] and not [i for i in out["issues"] if i["level"] == "error"]
    claims = [json.loads(l) for l in (archive / layout.CLAIMS_JSONL).read_text().splitlines()]
    cited = {c["value"] for c in claims if c["prop"] == "sources"}
    assert cited and all("port-inquiry-source" in v for v in cited)            # each value traces to the text
    with pytest.raises(core.IngestError, match="exists"):
        core.ingest(archive, BATCH, {"text": TEXT}, "port-inquiry")


def test_a_second_report_of_the_same_person_cites_the_existing_one_and_hydra_decides(archive):
    core.ingest(archive, BATCH, {"text": TEXT}, "first")
    rep = core.check_records(archive, [{"schema": "Person", "properties": {"name": "Rob Kerr"}}])
    assert [d["existing"] for d in rep["existing_entities_cited"]] == ["Rob Kerr"] and not rep["possible_duplicates"]
    assert rep["records"][0]["id"] == "person-rob-kerr-2"                       # never an id the archive uses
    out = core.ingest(archive, [{"schema": "Person", "properties": {"name": "Rob Kerr", "nationality": "us"}}],
                      {"text": "Rob Kerr is a US citizen."}, "second")
    assert out["saved"]                                        # hydra decides whether they're the same person
    recs = json.loads((archive / "collections/second.json").read_text())
    assert [r["properties"]["sources"] for r in recs] == [["second-source"]]


def test_schema_is_described_and_unknown_ones_are_refused(archive):
    top = core.describe_schema()
    assert "Person" in {e["schema"] for e in top["entities"]}
    emp = next(r for r in top["relationships"] if r["schema"] == "Employment")
    assert emp["from"] == "employee" and emp["to"] == "employer"
    props = {p["property"]: p for p in core.describe_schema("Employment")["properties"]}
    assert props["employer"]["type"] == "entity" and props["employer"]["required"] and props["employer"]["links_to"]
    assert props["startDate"]["type"] == "date" and "sources" not in props
    assert core.describe_schema("Person")["properties"][0]["property"] == "name"
    with pytest.raises(core.IngestError, match="did you mean 'Person'"):
        core.describe_schema("PERSON")


def test_saved_records_are_read_back_with_types_and_links(archive, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text(TEXT, encoding="utf-8")
    out = core.ingest(archive, BATCH, {"file": str(f)}, "case1")
    assert out["saved"], out
    assert [c["collection"] for c in core.get_records(archive)["collections"]] == ["case1"]
    got = core.get_records(archive, "case1")
    assert got["check"]["ok"], got["check"]
    emp = next(e for e in got["entities"] if e["schema"] == "Employment" and "startDate" in e["properties"])
    assert emp["properties"]["startDate"] == {"type": "date", "values": ["2019"]}
    link = emp["properties"]["employer"]["values"][0]
    assert link["resolves_to"] and link["resolves_to"][0]["schema"] in ("PublicBody", "Company")
    assert core.get_records(archive, "case1", name="harbor")["matching"] >= 1
    with pytest.raises(core.IngestError, match="no collection"):
        core.get_records(archive, "nope")


def test_link_image_previews_then_adds_a_hints_rule(archive, tmp_path):
    img = tmp_path / "harbor-badge.svg"
    img.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    pre = core.link_image(archive, str(img), "thumb", {"schema": "Person", "name": "Dana Hale"})
    assert not pre["added"] and "confirm" in pre["next"]
    assert not (archive / layout.RESOURCES_DIR / "icons" / "harbor-badge.svg").exists()
    done = core.link_image(archive, str(img), "thumb", {"schema": "Person", "name": "Dana Hale"}, confirm=True)
    assert done["added"] and (archive / layout.RESOURCES_DIR / "icons" / "harbor-badge.svg").is_file()
    assert "Dana Hale" in (archive / layout.HINTS).read_text(encoding="utf-8")
    with pytest.raises(core.IngestError, match="which entities"):
        core.link_image(archive, str(img), "thumb", {})
    with pytest.raises(core.IngestError, match="kind must be"):
        core.link_image(archive, str(img), "banner", {"name": "x"})
