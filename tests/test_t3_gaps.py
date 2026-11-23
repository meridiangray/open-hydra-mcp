"""Gaps the second acceptance runs found: prefixed ids, wiki_serve and other servers, scope(entity), answer evidence,
the step refusal's `do`, the checkout summary, and the task_verify cited list."""
import json

import pytest

from hydra.cli import main as cli
from hydra_mcp import agent, core, pipeline, server, workflows as wf
from hydra_mcp.core import IngestError

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    assert core.ingest(root, [P("Person", name="Ann Lee"), P("Person", name="Bo Rue")],
                       {"text": "Ann Lee and Bo Rue.", "title": "A note"}, "a")["saved"]
    return root


def stored(root):
    return json.loads((root / "collections/a.json").read_text(encoding="utf-8"))


def test_amend_takes_the_collections_own_prefix_and_refuses_another(archive):
    from hydra import collectionops
    pre = collectionops.prefix_of(archive, "a")
    ann = next(r for r in stored(archive) if r["properties"].get("name") == ["Ann Lee"])
    rec = {"id": f"{pre}:{ann['id']}", "schema": "Person", "properties": {"name": ["Ann Lee"], "gender": ["female"]}}
    out = agent.amend_records(archive, "a", [rec], confirm=False)
    assert out["changed"] == [ann["id"]] and out["added"] == 0
    bad = {**rec, "id": "zzz:nobody"}
    with pytest.raises(IngestError, match="no record 'zzz:nobody'"):
        agent.amend_records(archive, "a", [bad], confirm=False)


def test_wiki_serve_never_stops_another_archives_server(archive, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "STATE", tmp_path / "state")
    pipeline.STATE.mkdir()
    pipeline._state(8099).write_text(json.dumps({"pid": 4242, "root": str(tmp_path / "other"), "port": 8099}))
    monkeypatch.setattr(pipeline, "_alive", lambda pid: True)
    killed = []
    monkeypatch.setattr(pipeline, "_kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(pipeline, "_universe", lambda root: None)
    monkeypatch.setattr(pipeline, "_built_pages", lambda root: [])
    from hydra.universe import build as ubuild
    monkeypatch.setattr(ubuild, "pages_current", lambda root: True)
    with pytest.raises(IngestError, match="replace_other"):
        pipeline.wiki_serve(archive, port=8099)
    assert not killed


def test_scope_with_an_entity_answers_for_it(archive):
    out = pipeline.scope(archive, "Ann Lee")
    assert out["entity"][0]["title"] == "Ann Lee" and "context_entries" not in out
    assert pipeline.scope(archive, "Nobody")["error"] == "no such entity"


def test_answer_keeps_its_evidence_and_decisions_show_it(archive):
    agent._keep_evidence(archive, "end-x", "he left in 1990", "doc-1")
    assert agent._evidence(archive)["end-x"] == {"quote": "he left in 1990", "source": "doc-1"}
    agent._keep_evidence(archive, "end-x", None, None)
    assert "end-x" not in agent._evidence(archive)
    assert "quote" in server.answer.__code__.co_varnames


def test_step_refusal_do_names_the_reason(archive, monkeypatch):
    from hydra import tasks
    def refuse(*a, **k):
        raise tasks.TaskError("step A1 is checked by x y, which still finds: w (2). Fix them")
    monkeypatch.setattr(tasks, "step_task", refuse)
    monkeypatch.setattr(wf, "_task_id", lambda root, tid: "t")
    with pytest.raises(IngestError) as e:
        wf.task_step(archive, "A1", result="r")
    pay = wf.failure_payload(e.value)
    assert "reason" in pay["do"] and "tasks()" not in pay["do"]


def test_checkout_is_a_short_summary_unless_details(archive, monkeypatch):
    made = wf.task_new(archive, "Check", "enrich", None, None, ["Ann Lee"], True)
    monkeypatch.setattr(wf, "details", lambda root: {"name": "case", "built": "now", "schemas": {"Person": 2},
                                                     "reads": {"a": 1}, "issues": {"x": 1}})
    out = wf.task_checkout(archive, made["id"])
    assert set(out["archive_details"]) == {"name", "built", "more"}
    wf.task_release(archive)
    assert "schemas" in wf.task_checkout(archive, made["id"], details=True)["archive_details"]
