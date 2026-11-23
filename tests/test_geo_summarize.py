"""geo_contexts, geo_summarize, geo_register_status and an ad-hoc polygon in geo_query, on small fixture archives."""
from pathlib import Path

import pytest

from hydra import packages as P
from hydra.cli import main as cli
from hydra_mcp import core, geo

PK = next((Path(P.__file__).parent / "registry").glob("hydra-context-kurdistan-*.hydrapkg"))
Q = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(tmp_path / "reg"))
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    P.install(str(PK), scope="machine", root=root)
    P.lock(root)
    src = tmp_path / "a.txt"
    src.write_text("Erbil Works, Duhok Mills and Plaza Hotel.", encoding="utf-8")
    core.ingest(root, [Q("Company", name="Erbil Works"), Q("Company", name="Duhok Mills"), Q("RealEstate", name="Plaza Hotel")],
                {"file": str(src)}, "a")
    geo.draw_feature(root, {"type": "Point", "coordinates": [44.01, 36.19]}, kind="point", entity="Erbil Works", confirm=True)
    geo.draw_feature(root, {"type": "Point", "coordinates": [42.95, 36.87]}, kind="point", entity="Duhok Mills", confirm=True)
    geo.draw_feature(root, {"type": "Point", "coordinates": [-73.97, 40.76]}, kind="point", entity="Plaza Hotel", confirm=True)
    return root


def test_contexts_lists_the_installed_package(archive):
    out = geo.geo_contexts(archive)["contexts"]
    assert out[0]["package"] == "hydra/context-kurdistan" and out[0]["licence"]
    gov = next(x for x in out[0]["layers"] if x["name"] == "kurdistan-governorates")
    assert gov["features"] > 0


def test_summarize_by_context_country_and_filters(archive):
    out = geo.geo_summarize(archive, "context:kurdistan-governorates")
    names = {a["name"]: a for a in out["areas"]}
    assert names["Erbil"]["count"] == 1 and names["Erbil"]["examples"][0]["title"] == "Erbil Works"
    assert "Dohuk" in names
    c = {a["key"]: a["count"] for a in geo.geo_summarize(archive, "country")["areas"]}
    assert c["iso3166:IQ"] == 2 and c["iso3166:US"] == 1
    assert [a["key"] for a in geo.geo_summarize(archive, "country", schema="RealEstate")["areas"]] == ["iso3166:US"]


def test_summarize_errors(archive):
    for out in (geo.geo_summarize(archive, "planet"), geo.geo_summarize(archive, "context:nope"),
                geo.geo_summarize(archive, "country", tag="not-an-archetype")):
        assert set(out) == {"error", "why", "do"}


def test_query_within_an_ad_hoc_polygon(archive):
    poly = {"type": "Polygon", "coordinates": [[[43.5, 35.8], [44.5, 35.8], [44.5, 36.6], [43.5, 36.6], [43.5, 35.8]]]}
    got = geo.geo_query(archive, within={"geometry": poly})
    assert [h["title"] for h in got["results"]] == ["Erbil Works"]
    with pytest.raises(core.IngestError, match="needs an area"):
        geo.geo_query(archive, within={"geometry": {"type": "Point", "coordinates": [44, 36]}})


def test_register_status_is_read_only(archive):
    st = geo.geo_register_status(archive)
    assert "adm0" in st["layers"] and all(k in st["layers"] for k in st["missing_critical"])


def test_register_status_names_missing_critical_layers(archive):
    st = geo.geo_register_status(archive)       # the fixture's register folder is empty: only adm0 is packed with hydra
    assert {"admin1", "cities"} <= set(st["missing_critical"]) and "adm0" not in st["missing_critical"] and st["do"]


def test_summarize_tag_filter(archive):
    (archive / ".hydra" / "rules").mkdir(parents=True, exist_ok=True)
    (archive / ".hydra" / "rules" / "archetypes.yaml").write_text(
        "works:\n  label: Works\n  schema: [Company]\n  fit: 50\n  signs:\n    - {kind: name, name: Erbil, weight: 1}\n",
        encoding="utf-8")
    out = geo.geo_summarize(archive, "country", tag="works")
    assert out["entities"] == 1 and out["areas"][0]["key"] == "iso3166:IQ" and out["areas"][0]["count"] == 1
