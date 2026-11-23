"""The MCP call log (G19): one row per call in the task this server holds, summarised, never breaking a call."""
import asyncio
import json

import pytest

from hydra import tasks as htasks
from hydra_mcp import calllog, core, server


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def _call(name, args):
    return asyncio.run(server.mcp.call_tool(name, args))


def _rows(arch, tid):
    p = htasks.tasks_dir(arch) / f"{tid}.calls.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _new_task(arch):
    made = server.task_new("Log test", workflow="enrich", confirm=True, archive=str(arch))
    return made["id"]


def test_row_written_while_task_held_and_numbered(arch):
    tid = _new_task(arch)
    _call("task_checkout", {"id": tid, "archive": str(arch)})
    _call("tasks", {"archive": str(arch)})
    rows = _rows(arch, tid)
    assert [r["n"] for r in rows] == [1, 2]
    assert [r["tool"] for r in rows] == ["task_checkout", "tasks"]
    row = rows[1]
    assert set(row) == {"n", "at", "tool", "args", "ok", "error", "ms", "step", "holder"}
    assert row["ok"] is True and row["error"] is None and row["at"].endswith("Z")
    assert row["holder"] in htasks.MCP_HOLDER and "archive" in row["args"]
    print("EXAMPLE ROW:", json.dumps(row))


def test_calls_without_a_held_task_go_to_the_untasked_log(arch):
    tid = _new_task(arch)
    _call("tasks", {"archive": str(arch)})
    assert _rows(arch, tid) == []
    rows = _rows(arch, calllog.UNTASKED)
    assert [r["tool"] for r in rows] == ["tasks"] and rows[0]["holder"] is None and rows[0]["step"] is None


def test_two_held_tasks_log_to_the_one_checked_out_last(arch):
    first, second = _new_task(arch), _new_task(arch)
    _call("task_checkout", {"id": first, "archive": str(arch)})
    _call("task_checkout", {"id": second, "archive": str(arch)})
    _call("tasks", {"archive": str(arch)})
    assert [r["tool"] for r in _rows(arch, second)] == ["task_checkout", "tasks"]
    assert [r["tool"] for r in _rows(arch, first)] == ["task_checkout"]


def test_text_and_records_are_summarised_never_copied(arch):
    tid = _new_task(arch)
    _call("task_checkout", {"id": tid, "archive": str(arch)})
    secret = "Alpha Beta Gamma " * 20
    records = [{"schema": "Person", "properties": {"name": "Zed Unique"}},
               {"schema": "Person", "properties": {"name": "Yan Unique"}},
               {"schema": "Organization", "properties": {"name": "Xo Unique"}}]
    _call("save", {"records": records, "collection": "c", "source": {"title": "t" + secret},
                   "api_key": "sk-123", "archive": str(arch)})
    row = _rows(arch, tid)[-1]
    blob = json.dumps(row)
    assert "Unique" not in blob and "Alpha Beta" not in blob and "sk-123" not in blob
    assert row["args"]["records"] == {"n": "<3 items>", "schemas": {"Person": 2, "Organization": 1}}
    assert row["args"]["api_key"] == "<hidden>"
    assert summarise_long()["x"] == f"<{len('q' * 200)} chars>"
    assert calllog.summarise({"notes": ["a", "b"], "text": "hello"}) == {"notes": "<2 items>", "text": "<5 chars>"}


def summarise_long():
    return calllog.summarise({"x": "q" * 200})


def test_error_call_is_not_ok(arch):
    tid = _new_task(arch)
    _call("task_checkout", {"id": tid, "archive": str(arch)})
    _call("guide", {"topic": "no-such-guide", "archive": str(arch)})
    row = _rows(arch, tid)[-1]
    assert row["tool"] == "guide" and row["ok"] is False
    assert row["error"]["error"] and len(row["error"]["why"]) <= 160


def test_logging_failure_leaves_reply_unchanged(arch, monkeypatch):
    tid = _new_task(arch)
    _call("task_checkout", {"id": tid, "archive": str(arch)})
    good = _call("workflows", {"archive": str(arch)})          # a reply with no clock in it, so the two compare exactly

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(calllog, "_append", boom)
    again = _call("workflows", {"archive": str(arch)})
    assert json.dumps(again, default=str, sort_keys=True) == json.dumps(good, default=str, sort_keys=True)
    assert len(_rows(arch, tid)) == 2
