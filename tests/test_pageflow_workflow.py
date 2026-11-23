"""The `pageflow` workflow (H1): a task whose steps are the page-flow driver's passes, P0 preflight to P9 close."""
import pytest

from hydra_mcp import core, server

CODES = [f"P{i}" for i in range(10)]


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def test_pageflow_is_listed_and_renders_as_a_guide(arch):
    names = [w["name"] for w in server.workflows(archive=str(arch))["workflows"]]
    assert "pageflow" in names
    g = server.guide("workflow/pageflow")["content"]
    for code in CODES:
        assert f"{code}." in g or f"**{code}" in g or f"{code} " in g, code


def test_a_pageflow_task_has_the_driver_passes_in_order(arch):
    t = server.task_new("page flow", workflow="pageflow", context="incident", views=[], confirm=True,
                        authorized=["save", "cite", "label"], archive=str(arch))
    assert t["written"] and t["steps"] == 10 and t["authorized"] == ["save", "cite", "label"]
    server.task_checkout(t["id"], holder="pageflow", archive=str(arch))
    shown = server.task(t["id"], archive=str(arch))
    codes = [s["code"] for s in shown["steps"]]
    assert codes == CODES
    assert shown["next_step"]["code"] == "P0" and shown["next_step"]["tool"] == "guide"


def test_the_driver_ticks_a_pass_with_its_counts(arch):
    t = server.task_new("page flow", workflow="pageflow", context="incident", views=[], confirm=True,
                        archive=str(arch))
    server.task_checkout(t["id"], holder="pageflow", archive=str(arch))
    got = server.task_step("P0", result="7 checks passed", archive=str(arch))
    assert got["next_step"]["code"] == "P1"
    v = server.task_verify(t["id"], archive=str(arch))
    assert v["ready_to_close"] is False                           # nine passes still open
