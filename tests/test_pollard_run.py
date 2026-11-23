"""What the 2026-11-21 Sonnet Pollard run tripped on: an empty archive refused collection_create, and every
task_step reply carried the whole task (about 6k tokens), so the agent stopped ticking."""
import json

import pytest

from hydra_mcp import core, data, server


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def test_collections_first_then_save_fills_the_empty_one(arch):
    made = data.collection_create(arch, "people", "People", confirm=True)
    assert made.get("changed") and not made.get("error"), made
    out = server.save([{"schema": "Person", "properties": {"name": ["Lia Ortiz"]}}],
                      {"text": "Lia Ortiz signed the lease.", "title": "lease"}, "people", archive=str(arch))
    assert out["saved"] and out["records"] == 1


def test_task_step_reply_is_short_and_task_still_shows_everything(arch):
    tid = server.task_new("Step size", workflow="enrich", confirm=True, context="general", archive=str(arch))["id"]
    server.task_checkout(tid, archive=str(arch))
    full = server.task(tid, archive=str(arch))
    first = full["next_step"]["code"]
    out = server.task_step(first, status="skipped", reason="test", archive=str(arch))
    assert "steps" not in out and out["updated_step"]["status"] == "skipped" and out["next_step"]
    assert len(json.dumps(out, default=str)) < len(json.dumps(full, default=str)) / 2
    assert any(s["code"] == first for s in server.task(tid, archive=str(arch))["steps"])
