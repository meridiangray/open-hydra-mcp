"""The geo tools as an agent uses them: save research records, say where they are, ask, and correct."""
import pytest

from hydra.archive import history, resources
from hydra.cli import main as cli
from hydra_mcp import core, geo, guidelines

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    src = tmp_path / "a.txt"
    src.write_text("Bandar bin Sultan bought Glympton Park in 1992 and sold it in 2021. "
                   "The Plaza Hotel stands at 768 Fifth Avenue.", encoding="utf-8")
    core.ingest(root, [P("RealEstate", name="Glympton Park", country="gb"),
                       P("Person", name="Bandar bin Sultan"),
                       P("Ownership", owner="Bandar bin Sultan", asset="Glympton Park", startDate="1992", endDate="2021"),
                       P("RealEstate", name="Plaza Hotel", country="us")], {"file": str(src)}, "a")
    return root


ESTATE = {"bbox": [-1.40, 51.86, -1.36, 51.89]}


def test_site_then_ask_where(archive):
    item = {"entity": "Glympton Park", "role": "boundary", "location": ESTATE}
    pre = geo.site(archive, [item])
    assert pre["next"] and pre["written"] == 0 and pre["geolinks"][0]["feature"]["area_ha"] == pytest.approx(916, rel=0.01)
    done = geo.site(archive, [item, {"entity": "Plaza Hotel", "location": {"point": [-73.9743, 40.7645]},
                                     "role": "footprint"}], confirm=True)
    assert done["written"] == 4 and history.log(archive)[0]["author"] == "agent:hydra-mcp"
    where = geo.geo_locate(archive, "Glympton Park")
    assert where["how"] == "inferred" and where["primary"][0]["role"] == "boundary"
    assert geo.geo_locate(archive, "Bandar bin Sultan", as_of="2000")["reach"][0]["title"] == "Glympton Park"
    assert not geo.geo_locate(archive, "Bandar bin Sultan", as_of="1980")["reach"]
    near = geo.geo_query(archive, near={"point": [-1.38, 51.875], "km": 1})
    assert [h["title"] for h in near["results"]] == ["Glympton Park"]
    within = geo.geo_query(archive, within=[-80, 35, -70, 45])
    assert [h["title"] for h in within["results"]] == ["Plaza Hotel"]
    assert geo.geo_measure(archive, "Glympton Park", "Plaza Hotel")["km_centres"] == pytest.approx(5470, rel=0.01)
    rep = geo.geo_report(archive)
    assert rep["coverage"]["RealEstate"]["primary"] == 2 and "geo.role-shape" in rep["findings"]   # a point footprint


def test_errors_say_what_to_do(archive):
    out = geo.site(archive, [{"entity": "Glympton Park", "location": {"point": [-1.38, 95]}}])   # no latitude 95
    assert "lat, lon" in out["errors"][0]["error"] and "next" in out                            # but [95, -1.38] is
    with pytest.raises(core.IngestError, match="ask one of"):
        geo.geo_query(archive)
    with pytest.raises(core.IngestError, match="no entity"):
        geo.geo_locate(archive, "Atlantis")


def test_primary_choice_edit_and_remove(archive):
    geo.site(archive, [{"entity": "Glympton Park", "role": "boundary", "location": ESTATE},
                       {"entity": "Glympton Park", "role": "building", "location": {"point": [-1.381, 51.875]},
                        "name": "Glympton House"}], confirm=True)
    house = geo.geo_locate(archive, "Glympton House")["entity"]["body"]
    pre = geo.set_primary(archive, "Glympton Park", [house])
    assert pre["next"] and pre["how_now"] == "inferred"
    done = geo.set_primary(archive, "Glympton Park", [house], confirm=True)
    assert done["how_after"] == "chosen" and done["primary_after"][0]["title"] == "Glympton House"
    assert geo.set_primary(archive, "Glympton Park", "auto", confirm=True)["how_after"] == "inferred"
    geolink = next(s for s in geo.geo_locate(archive, "Glympton Park")["geolinks"] if s["role"] == "building")
    geo.edit_geolink(archive, geolink["records"][0], {"role": "entrance"}, confirm=True)
    roles = {s["role"] for s in geo.geo_locate(archive, "Glympton Park")["geolinks"]}
    assert "entrance" in roles and "building" not in roles
    geo.edit_geolink(archive, geolink["records"][0], {"remove": True}, confirm=True)
    assert "entrance" not in {s["role"] for s in geo.geo_locate(archive, "Glympton Park")["geolinks"]}


def test_transform_geometry(archive):
    geo.site(archive, [{"entity": "Glympton Park", "role": "boundary", "location": ESTATE}], confirm=True)
    outline = geo.geo_locate(archive, "Glympton Park")["primary"][0]["location"]
    pt = geo.transform_geometry(archive, outline, "to_point", as_="new", confirm=True)
    assert pt["after"]["points"] == 1 and pt["new_feature"]
    with pytest.raises(core.IngestError, match="op is one of"):
        geo.transform_geometry(archive, outline, "buffer")


def test_geo_enable_installs_it_in_an_older_archive(archive):
    for rel in resources.DEFAULTS["geo"]:
        (archive / rel).unlink()
    with pytest.raises(core.IngestError, match="geo_enable"):
        geo.site(archive, [{"entity": "Glympton Park", "location": ESTATE}])
    pre = geo.geo_enable(archive)
    assert pre["next"] and len(pre["installs"]) == len(resources.DEFAULTS["geo"])
    geo.geo_enable(archive, confirm=True)
    assert geo.geo_enable(archive)["note"] == "geo is installed"
    assert not geo.site(archive, [{"entity": "Glympton Park", "location": ESTATE}])["errors"]


def test_the_guidelines_say_where_things_are_go(archive):
    text = guidelines.text(archive) if hasattr(guidelines, "text") else guidelines.RULES
    assert "## Where things are (geo)" in text and "never a field you add" in text


def test_resolve_a_point_then_site_at_the_country_it_names(archive, tmp_path, monkeypatch):
    import json
    from hydra.geo import registerdata
    sq = lambda w, s, e, n: {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    raw = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": sq(-8, 50, 2, 59), "properties": {
        "NAME": "United Kingdom", "NAME_EN": "United Kingdom", "ADM0_A3": "GBR", "ISO_A2_EH": "GB", "ISO_A3_EH": "GBR",
        "WIKIDATAID": "Q145", "LABEL_X": -2, "LABEL_Y": 53}}]}).encode()
    (tmp_path / "reg").mkdir()
    (tmp_path / "reg" / "adm0.json.gz").write_bytes(registerdata.pack_adm0(raw))
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(tmp_path / "reg"))
    monkeypatch.setattr(registerdata, "PACKAGED", tmp_path / "none")
    out = geo.geo_resolve(archive, point=[-1.38, 51.87])
    assert out["chain"][0]["key"] == "iso3166:GB" and "boundaries" in out["note"]
    assert geo.geo_resolve(archive, name="United Kingdom")["candidates"][0]["key"] == "iso3166:GB"
    done = geo.site(archive, [{"entity": "Glympton Park", "role": "location", "location": {"register": "iso3166:GB"}}],
                    confirm=True)
    assert done["written"] == 2 and done["geolinks"][0]["place"]["new"]
    assert geo.geo_resolve(archive, point=[-1.38, 51.87])["chain"][0]["place"]["title"] == "United Kingdom"


def test_geo_aspects_shows_each_aspect_and_the_register_candidates(archive, tmp_path, monkeypatch):
    import json
    from hydra.geo import register, registerdata
    box = lambda w, s, e, n: {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    raw = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": box(0, 0, 10, 10), "properties": {
            "NAME": "Westland", "NAME_EN": "Westland", "ADM0_A3": "WST", "ISO_A2_EH": "WL", "ISO_A3_EH": "WST",
            "WIKIDATAID": "Q1", "LABEL_X": 5, "LABEL_Y": 5}},
        {"type": "Feature", "geometry": box(10, 0, 20, 10), "properties": {
            "NAME": "Eastland", "NAME_EN": "Eastland", "ADM0_A3": "EST", "ISO_A2_EH": "EL", "ISO_A3_EH": "EST",
            "WIKIDATAID": "Q4", "LABEL_X": 15, "LABEL_Y": 5}}]}).encode()
    home = tmp_path / "register"
    home.mkdir()
    (home / "adm0.json.gz").write_bytes(registerdata.pack_adm0(raw))
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(home))
    monkeypatch.setattr(register, "_STORE", None)
    src = tmp_path / "b.txt"
    src.write_text("The Ambassador to Eastland is a post of Westland.", encoding="utf-8")
    core.ingest(archive, [P("Position", name="Ambassador to Eastland", country="wl")], {"file": str(src)}, "b")
    out = geo.geo_aspects(archive, "Ambassador to Eastland")
    by = {a["role"]: a for a in out["aspects"]}
    assert list(by) == ["home", "posting", "seat", "jurisdiction"] and out["entity"]["schema"] == "Position"
    assert by["home"]["state"] == "derived" and by["home"]["fills"][0]["title"] == "Westland"
    assert by["posting"]["state"] == "empty" and by["posting"]["candidates"][0]["key"] == "iso3166:EL"
    geo.site(archive, [{"entity": "Ambassador to Eastland", "role": "posting", "location": {"register": "iso3166:EL"}}],
             confirm=True)
    after = {a["role"]: a for a in geo.geo_aspects(archive, "Ambassador to Eastland")["aspects"]}
    assert after["posting"]["state"] == "filled" and after["posting"]["fills"][0]["primary"] and "next" in out
    with pytest.raises(core.IngestError, match="no entity"):
        geo.geo_aspects(archive, "Atlantis")


def test_draw_feature_previews_then_writes_a_feature_and_a_geolink(archive):
    point = {"type": "Point", "coordinates": [-73.9743, 40.7645]}
    pre = geo.draw_feature(archive, point, "embassy", entity="Plaza Hotel")
    assert pre["next"] and pre["written"] == 0 and pre["feature"]["osmTag"] == ["office=diplomatic"] and pre["role"] == "seat"
    done = geo.draw_feature(archive, point, "embassy", entity="Plaza Hotel", name="Chancery", confirm=True)
    assert done["written"] == 2 and history.log(archive)[0]["author"] == "agent:hydra-mcp"
    where = geo.geo_locate(archive, "Plaza Hotel")
    assert any(s["role"] == "seat" for s in where["geolinks"])


def test_draw_feature_makes_a_new_entry_and_says_what_it_cannot_keep(archive):
    line = {"type": "LineString", "coordinates": [[-1.40, 51.86], [-1.36, 51.89]]}
    done = geo.draw_feature(archive, line, "pipeline", new={"name": "Test-only Pipeline"}, confirm=True)
    assert done["entity"]["schema"] == "Asset" and done["written"] == 2
    with pytest.raises(core.IngestError, match="draw a point"):
        geo.draw_feature(archive, line, "embassy", entity="Plaza Hotel")
    with pytest.raises(core.IngestError, match="say what is drawn"):
        geo.draw_feature(archive, line, entity="Plaza Hotel")


def test_draw_feature_is_a_tool():
    from hydra_mcp import server
    assert "draw_feature" in {t.name for t in server.mcp._tool_manager.list_tools()}


def test_verbatim_ignores_unicode_form_quotes_dashes_and_spaces():
    import unicodedata
    from hydra_mcp import sources as src
    text = unicodedata.normalize("NFD", "Paris is in Île-de-France— the region’s “core”.")
    assert src.verbatim("Paris is in Île-de-France- the region's \"core\".", [text])
    assert src.verbatim("Île-de-France", [text])
    assert src.verbatim("Paris is in Île‐de-France", [text])
    assert not src.verbatim("Paris is in Normandy", [text])


def test_resolve_candidates_say_their_region_and_country():
    from hydra.geo import bind
    class Reg:
        def contains(self, at):
            return [{"level": "adm0", "name": "United States"}, {"level": "adm1", "name": "California"},
                    {"level": "settlement", "name": "Newark"}]
    assert bind._where(Reg(), {"name": "Newark", "level": "settlement", "at": [-122, 37]}) == \
        "Newark · California · United States"
    assert bind._where(Reg(), {"name": "Newark", "level": "settlement"}) == "Newark"


def test_edit_siting_is_the_old_name_of_edit_geolink(archive):
    import asyncio
    from hydra_mcp import server
    geo.site(archive, [{"entity": "Glympton Park", "role": "building", "location": {"point": [-1.381, 51.875]},
                        "name": "Glympton House"}], confirm=True)
    link = next(s for s in geo.geo_locate(archive, "Glympton Park")["geolinks"] if s["role"] == "building")
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert "edit_geolink" in tools and tools["edit_siting"].description == "Old name of edit_geolink; use edit_geolink."
    assert "siting" in tools["edit_siting"].inputSchema["properties"] and "geolink" in tools["edit_geolink"].inputSchema["properties"]
    pre = server.edit_siting(link["records"][0], {"role": "entrance"}, archive=str(archive))
    assert pre["next"] and pre["after"]["role"] == ["entrance"]
    done = server.edit_siting(link["records"][0], {"role": "entrance"}, confirm=True, archive=str(archive))
    assert done["written"] and "entrance" in {s["role"] for s in geo.geo_locate(archive, "Glympton Park")["geolinks"]}
