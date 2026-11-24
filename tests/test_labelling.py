"""The `label` tool: the Labelling page's tokens for an agent, previewing every entry first."""
import json

import pytest

from hydra.cli import main as cli
from hydra_mcp import core, labelling, server

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    out = core.ingest(root, [P("PublicBody", name="Consulate New York"), P("PublicBody", name="Embassy Washington"),
                             P("Person", name="Ann Lee")],
                      {"text": "The Consulate New York and the Embassy Washington are missions. Ann Lee works there.",
                       "title": "A note"}, "a")
    assert out["saved"]
    return root


def test_the_tool_is_registered():
    assert "label" in {t.name for t in server.mcp._tool_manager.list_tools()}


def test_a_judgement_previews_then_writes_only_on_confirm(archive):
    pre = labelling.label(archive, ["Consulate New York", "Embassy Washington"], "tag:diplomatic-mission")
    assert pre["ok"] and pre["written"] == 0 and pre["next"] and not pre["needs_source"]
    assert [e["entry"] for e in pre["entries"]] == ["Consulate New York", "Embassy Washington"]
    assert pre["entries"][0]["labels"][0]["would"].startswith("Diplomatic mission: is one")
    from hydra.shape import archetypes
    assert not archetypes.decisions(archive)
    done = labelling.label(archive, ["Consulate New York", "Embassy Washington"], "tag:diplomatic-mission", confirm=True)
    assert done["written"] == 1 and len(archetypes.decisions(archive)) == 2


def test_a_fact_needs_a_kept_source_and_names_the_choices(archive):
    pre = labelling.label(archive, ["Ann Lee"], "country:nationality@us")
    assert not pre["ok"] and pre["needs_source"] and pre["sources"][0]["title"] == "A note"
    assert pre["entries"][0]["labels"][0]["error"].startswith("needs a kept source")
    refused = labelling.label(archive, ["Ann Lee"], "country:nationality@us", confirm=True)     # confirm never skips the rule
    assert not refused["ok"] and refused["written"] == 0
    sid = pre["sources"][0]["id"]
    ok = labelling.label(archive, ["Ann Lee"], "country:nationality@us", source=sid)
    assert ok["ok"] and ok["entries"][0]["labels"][0]["would"].startswith("Nationality")
    done = labelling.label(archive, ["Ann Lee"], "country:nationality@us", confirm=True, source=sid)
    assert done["written"] == 1
    recs = json.loads((archive / "collections" / "a.json").read_text(encoding="utf-8"))
    assert next(r for r in recs if r["properties"].get("name") == ["Ann Lee"])["properties"]["nationality"] == ["us"]


def test_errors_say_what_to_fix_and_nothing_is_written(archive):
    out = labelling.label(archive, ["Ann Lee", "Consulate New York"], "tag:diplomatic-mission drop:rec@nonesuch")
    assert not out["ok"] and out["written"] == 0 and "next" in out
    with pytest.raises(core.IngestError, match="not a token"):
        labelling.label(archive, ["Ann Lee"], "nonsense")
    with pytest.raises(core.IngestError, match="no entry"):
        labelling.label(archive, ["Nobody"], "tag:diplomatic-mission")
