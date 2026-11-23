"""move_feature and delete_feature as an agent uses them: preview, confirm, one history step, {error, why, do}."""
import json

import pytest

from hydra import history
from hydra.cli import main as cli
from hydra_mcp import core, geo

P = lambda s, **p: {"schema": s, "properties": p}
SQUARE = {"type": "Polygon", "coordinates": [[[-1.40, 51.86], [-1.36, 51.86], [-1.36, 51.89], [-1.40, 51.89], [-1.40, 51.86]]]}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(tmp_path / "reg"))
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    src = tmp_path / "a.txt"
    src.write_text("Glympton Park and the Plaza Hotel.", encoding="utf-8")
    core.ingest(root, [P("RealEstate", name="Glympton Park", country="gb"), P("RealEstate", name="Plaza Hotel", country="us")],
                {"file": str(src)}, "a")
    geo.draw_feature(root, SQUARE, kind="area", entity="Glympton Park", confirm=True)
    return root


def h(root, title):
    """An entry's H (its Feature shares the name)."""
    from hydra.geo import query
    m = query.load(root)
    return next(b for b, p in m.pages.items() if p["title"] == title and p["schema"] != "Feature")


def centre(root, ref):
    return geo.geo_locate(root, h(root, ref))["primary"][0]["centroid"]


def test_move_own_shape_previews_then_moves_once(archive):
    before = centre(archive, "Glympton Park")
    pre = geo.move_feature(archive, entity=h(archive, "Glympton Park"), delta_m=[0, 1000])
    assert pre["written"] == 0 and pre["next"] and pre["mode"] == "redraw"
    assert centre(archive, "Glympton Park") == before                       # a preview writes nothing
    steps = len(history.log(archive))
    done = geo.move_feature(archive, entity=h(archive, "Glympton Park"), delta_m=[0, 1000], confirm=True)
    assert done["written"] == 1 and len(history.log(archive)) == steps + 1
    moved = centre(archive, "Glympton Park")
    assert moved[1] - before[1] == pytest.approx(1000 / 111320, rel=0.01) and moved[0] == pytest.approx(before[0], abs=1e-6)
    assert history.log(archive)[0]["author"] == "agent:hydra-mcp"


def test_move_feature_by_geometry(archive):
    fb = geo.geo_locate(archive, h(archive, "Glympton Park"))["primary"][0]["location"]
    new = {"type": "Polygon", "coordinates": [[[-1.50, 51.80], [-1.46, 51.80], [-1.46, 51.83], [-1.50, 51.83], [-1.50, 51.80]]]}
    assert geo.move_feature(archive, feature=fb, geometry=new, confirm=True)["written"] == 1
    assert centre(archive, "Glympton Park")[0] == pytest.approx(-1.48)


def test_move_gives_a_point_its_own_spot(archive):
    geo.site(archive, [{"entity": "Plaza Hotel", "role": "footprint", "location": {"point": [-73.97, 40.76]}}], confirm=True)
    pre = geo.move_feature(archive, entity="Plaza Hotel", delta_m=[100, 0])
    assert pre["written"] == 0
    steps = len(history.log(archive))
    done = geo.move_feature(archive, entity="Plaza Hotel", delta_m=[100, 0], confirm=True)
    assert done["written"] and len(history.log(archive)) == steps + 1
    assert centre(archive, "Plaza Hotel")[0] > -73.97


def test_move_errors_have_the_shape(archive):
    for out in (geo.move_feature(archive), geo.move_feature(archive, entity="Glympton Park"),
                geo.move_feature(archive, entity="Plaza Hotel", delta_m=[0, 1]),            # no place yet
                geo.move_feature(archive, entity="Atlantis", delta_m=[0, 1])):
        assert set(out) == {"error", "why", "do"} and out["why"]


def test_delete_feature_removes_it_and_its_geolinks(archive):
    fb = geo.geo_locate(archive, h(archive, "Glympton Park"))["primary"][0]["location"]
    pre = geo.delete_feature(archive, fb)
    assert pre["written"] == 0 and pre["next"] and pre["geolinks"][0]["title"] == "Glympton Park"
    assert geo.geo_locate(archive, h(archive, "Glympton Park"))["primary"]
    steps = len(history.log(archive))
    done = geo.delete_feature(archive, fb, confirm=True)
    assert done["written"] == 2 and len(history.log(archive)) == steps + 1
    assert not geo.geo_locate(archive, h(archive, "Glympton Park"))["primary"]
    ids = {r["id"] for r in json.loads((archive / "collections" / "geo.json").read_text(encoding="utf-8"))}
    assert not any(i.startswith(("fea-", "sit-")) for i in ids)
    assert set(geo.delete_feature(archive, fb)) == {"error", "why", "do"}                  # already gone
