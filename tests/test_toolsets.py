"""Toolsets: every tool in one set, the start-up choice, live enabling, the `tool not on` answer, task_checkout."""
import asyncio
import json
import re

import pytest
import yaml
from pathlib import Path

import hydra
from hydra.agents import tasks as htasks
from hydra.archive import writelock
from hydra_mcp import core, server, toolsets

CORE = (
    "guide workflows details tasks task task_new task_checkout task_step task_add task_verify task_release task_close "
    "contexts context_checkout create_archive describe_schema properties check check_records save preview get_records "
    "amend_records find_entities explain_entity read_file source_profile source_outline source_names read_source sources cite labelling_guidelines vocabularies "
    "keys collections collection_create recipe paths toolsets toolset_enable toolset_disable tool_on tool_off extra_fields field_assign").split()
WORKFLOW_DIR = Path(hydra.__file__).parent / "workflows"


@pytest.fixture(autouse=True)
def all_on():
    """The server module is shared: leave every tool on after each test."""
    toolsets.enable(server.mcp, "all")
    yield
    toolsets.enable(server.mcp, "all")


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def on():
    return set(server.mcp._tool_manager._tools)


def call(name, args=None):
    return asyncio.run(server.mcp._tool_manager.call_tool(name, args or {}))


def test_every_tool_is_in_exactly_one_set():
    registered = on()
    assert registered == set(toolsets.TOOL_SET)
    flat = [t for ts in toolsets.TOOLSETS.values() for t in ts]
    assert len(flat) == len(set(flat)) == len(registered)


def test_each_tool_is_defined_in_the_module_of_its_set():
    st = toolsets._state(server.mcp)
    wrong = {n: t.fn.__module__ for n, t in st.all.items() if t.fn.__module__ != f"hydra_mcp.tools.{toolsets.TOOL_SET[n]}"}
    assert not wrong, f"move these to hydra_mcp/tools/<their set>.py: {wrong}"


def test_every_tool_function_is_still_a_name_of_server():
    for t in toolsets._state(server.mcp).all.values():
        assert getattr(server, t.fn.__name__) is t.fn, t.name


def test_core_holds_the_listed_tools():
    assert set(toolsets.TOOLSETS["core"]) == set(CORE)


def test_every_workflow_step_tool_and_view_block_resolves_to_a_set():
    used = set()
    for p in WORKFLOW_DIR.glob("*.yaml"):
        used |= set(re.findall(r"^\s*tool:\s*(\w+)", p.read_text(encoding="utf-8"), re.M))
    assert used and all(t in toolsets.TOOL_SET for t in used), sorted(used - set(toolsets.TOOL_SET))
    views = yaml.safe_load((WORKFLOW_DIR / "_views.yaml").read_text(encoding="utf-8"))["views"]
    for v, spec in views.items():
        for s in spec.get("steps") or ():
            if isinstance(s, dict) and s.get("tool"):
                assert s["tool"] in toolsets.TOOL_SET, (v, s["tool"])


def test_descriptions_are_under_900_characters():
    long = {n: len(t.description) for n, t in server.mcp._tool_manager._tools.items() if len(t.description) > 900}
    assert not long, long


def test_default_start_exposes_only_core(monkeypatch):
    monkeypatch.delenv(toolsets.ENV, raising=False)
    assert toolsets.apply(server.mcp, toolsets.startup_spec(None)) == ["core"]
    assert on() == set(CORE)


def test_start_up_choice_from_the_argument_and_the_environment(monkeypatch):
    toolsets.apply(server.mcp, "core,geo")
    assert on() == set(CORE) | set(toolsets.TOOLSETS["geo"])
    monkeypatch.setenv(toolsets.ENV, "all")
    toolsets.apply(server.mcp, toolsets.startup_spec(None))
    assert len(on()) == len(toolsets.TOOL_SET)
    with pytest.raises(ValueError):
        toolsets.parse("core,nope")


def test_toolsets_and_toolset_enable_report_and_add(arch):
    toolsets.apply(server.mcp, "core")
    listed = call("toolsets")["toolsets"]
    assert [s["name"] for s in listed] == list(toolsets.TOOLSETS)
    assert next(s for s in listed if s["name"] == "core")["on"] is True
    assert next(s for s in listed if s["name"] == "geo")["on"] is False
    got = call("toolset_enable", {"name": "geo"})
    assert set(got["added"]) == set(toolsets.TOOLSETS["geo"]) and "geo" in got["on"]
    assert next(s for s in call("toolsets")["toolsets"] if s["name"] == "geo")["on"] is True
    assert call("toolset_enable", {"name": "geo"})["added"] == []
    assert call("toolset_enable", {"name": "nope"})["error"]


def test_enabled_tools_pass_through_the_write_lock_and_the_call_log(arch):
    toolsets.apply(server.mcp, "core")
    call("toolset_enable", {"name": "geo"})
    # the write lock: a confirm=true call waits for a lock held elsewhere, then answers busy
    import threading
    out = {}

    def other():
        out["r"] = call("delete_feature", {"feature": "x", "confirm": True, "archive": str(arch)})
    old = writelock.WAIT
    writelock.WAIT = 0.2
    try:
        with writelock.hold(arch, "someone-else"):
            t = threading.Thread(target=other)
            t.start()
            t.join()
    finally:
        writelock.WAIT = old
    assert out["r"]["error"] == "busy"
    # the unknown-argument check (also in the write-lock wrapper)
    bad = call("geo_report", {"archive": str(arch), "nonsense": 1})
    assert bad["error"].startswith("unknown argument")
    # the call log
    made = server.task_new("Log", workflow="enrich", confirm=True, archive=str(arch))
    call("task_checkout", {"id": made["id"], "archive": str(arch)})
    call("geo_report", {"archive": str(arch)})
    rows = [json.loads(x) for x in (htasks.tasks_dir(arch) / f"{made['id']}.calls.jsonl").read_text("utf-8").splitlines()]
    assert "geo_report" in [r["tool"] for r in rows]


def test_a_call_to_an_off_tool_says_which_set(arch):
    toolsets.apply(server.mcp, "core")
    got = call("geo_report", {"archive": str(arch)})
    assert got == {"error": "tool not on", "why": "geo_report is in the geo toolset, which is off",
                   "do": 'toolset_enable("geo")'}
    # a tool that does not exist is still unknown
    unknown = call("no_such_tool", {})
    assert unknown["error"] != "tool not on"
    # through the protocol layer it is an error result with the same text
    res = asyncio.run(server.mcp._tool_manager.call_tool("geo_report", {}, convert_result=True))
    assert res.isError and "tool not on" in res.content[0].text


def test_task_checkout_enables_the_sets_its_route_needs(arch):
    made = server.task_new("Place it", workflow="places", confirm=True, archive=str(arch))
    toolsets.apply(server.mcp, "core")
    assert "geo_resolve" not in on()
    out = server.task_checkout(made["id"], archive=str(arch))
    assert "geo" in out["toolsets_enabled"]
    assert set(toolsets.TOOLSETS["geo"]) <= on()
    again = server.task_checkout(made["id"], archive=str(arch))
    assert "toolsets_enabled" not in again


def test_the_server_announces_tool_list_changes_and_tells_the_client():
    opts = server.mcp._mcp_server.create_initialization_options()
    assert opts.capabilities.tools.listChanged is True

    class Session:
        sent = 0

        async def send_tool_list_changed(self):
            Session.sent += 1

    class Ctx:
        session = Session()
    toolsets.apply(server.mcp, "core")
    asyncio.run(server.mcp._tool_manager.call_tool("toolset_enable", {"name": "geo"}, context=Ctx()))
    assert Session.sent == 1
    asyncio.run(server.mcp._tool_manager.call_tool("toolset_enable", {"name": "geo"}, context=Ctx()))
    assert Session.sent == 1
