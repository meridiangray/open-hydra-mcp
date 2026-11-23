"""The tools behind the entry-page, upkeep and map-layer workflows: article sections removed and moved, one entry's
picture pinned to its records, `upgrade` previewed, and map layers added, listed and removed. Every write previews."""
import base64
import json

import pytest

from hydra import articles, history, layout
from hydra.cli import main as cli
from hydra_mcp import agent, article, core, upkeep

P = lambda s, **p: {"schema": s, "properties": p}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    core.ingest(root, [P("Company", name="Test Company"), P("Company", name="Test Company", country="fr")],
                {"text": "Test Company is a test.", "title": "t"}, "a")
    return root


def _one(root, title):
    """The H of the first of the namesakes: a shared title is refused, so a tool is given an H."""
    from hydra import entities
    with pytest.raises(core.IngestError, match="names 2 entries"):
        article.body_of(root, title)
    return sorted(c["h"] for c in entities.catalog(root).search(title) if c["title"] == title)[0]


def test_sections_are_removed_and_moved_after_a_preview(archive):
    tc = _one(archive, "Test Company")
    for h in ("One", "Two", "Three"):
        article.set_article_section(archive, tc, h, f"{h} text.", confirm=True)
    b = article.body_of(archive, tc)
    out = article.move_article_section(archive, tc, "Three", 1)
    assert not out["written"] and out["order"] == ["Three", "One", "Two"]
    assert [s["heading"] for s in articles.load(archive, b)] == ["One", "Two", "Three"]
    n = len(history.log(archive))
    assert article.move_article_section(archive, tc, "three", 1, confirm=True)["order"] == ["Three", "One", "Two"]
    assert len(history.log(archive)) == n + 1                                 # one step, however far it moves
    with pytest.raises(core.IngestError):
        article.move_article_section(archive, tc, "One", 9)
    out = article.remove_article_section(archive, tc, "Two")
    assert not out["written"] and len(articles.load(archive, b)) == 3
    assert article.remove_article_section(archive, tc, "Two", confirm=True)["sections"] == ["Three", "One"]
    with pytest.raises(core.IngestError):
        article.remove_article_section(archive, tc, "Nope")


def test_one_entrys_logo_is_pinned_to_its_records(archive, tmp_path):
    img = tmp_path / "logo.png"
    img.write_bytes(PNG)
    tc = _one(archive, "Test Company")
    ids = agent.records_of(archive, tc)
    assert ids
    out = core.link_image(archive, str(img), "logo", {"record": ids})
    assert not out["added"] and out["match"] == {"record": ids}
    core.link_image(archive, str(img), "logo", {"record": ids}, confirm=True)
    hints = (archive / layout.HINTS).read_text(encoding="utf-8")
    assert "record:" in hints and "logo:" in hints and "Test Company" not in hints
    with pytest.raises(core.IngestError):
        agent.records_of(archive, "Nobody Here")


def test_upgrade_on_a_current_archive_has_nothing_to_do(archive):
    out = upkeep.upgrade(archive)
    assert out["changes"] == [] and not out["written"]


def test_layers_preview_add_list_and_remove(archive, tmp_path):
    f = tmp_path / "zone.geojson"
    f.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Test zone"},
         "geometry": {"type": "Polygon", "coordinates": [[[44, 36], [45, 36], [45, 37], [44, 36]]]}}]}), encoding="utf-8")
    out = upkeep.layer_add(archive, str(f), "Test zone")
    assert not out["written"] and out["features"] == 1 and "warning" in out             # no attribution or licence given
    assert upkeep.layer_list(archive)["layers"] == []
    got = upkeep.layer_add(archive, str(f), "Test zone", "Test source", "CC0 1.0", confirm=True)
    lid = got["layer"]["id"]
    assert [x["id"] for x in upkeep.layer_list(archive)["layers"]] == [lid]
    assert not upkeep.layer_remove(archive, lid)["written"]
    assert upkeep.layer_remove(archive, lid, confirm=True)["written"] and upkeep.layer_list(archive)["layers"] == []
    with pytest.raises(core.IngestError):
        upkeep.layer_add(archive, str(tmp_path / "missing.geojson"), "x")
    with pytest.raises(core.IngestError):
        upkeep.layer_remove(archive, "nope")
