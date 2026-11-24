"""mcp.yaml: layering, never-off tools, locked, unknown names, the `hydra-mcp config` CLI, live pick-up."""
import asyncio
import os
from pathlib import Path

import pytest

from hydra_mcp import config, core, server, toolsets


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    """The owner's real config folder is never touched: HYDRA_CONFIG_DIR is a scratch folder for every test."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(cfg))
    monkeypatch.delenv(toolsets.ENV, raising=False)
    toolsets.enable(server.mcp, "all")
    toolsets._state(server.mcp).stamp = config.stamps()
    toolsets._state(server.mcp).archive = None
    toolsets._state(server.mcp).flag = None
    yield cfg
    # Put the shared server back as other test files expect it: the env as it was, every set on, and the stamp of
    # the config folder they see, so the next tool call does not re-read the files and fall back to core only.
    monkeypatch.undo()
    toolsets.enable(server.mcp, "all")
    st = toolsets._state(server.mcp)
    st.stamp, st.archive, st.flag = config.stamps(), None, None


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def on():
    return set(server.mcp._tool_manager._tools)


def call(name, args=None):
    return asyncio.run(server.mcp._tool_manager.call_tool(name, args or {}))


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bump(path: Path):
    """Make the stamp differ even on a coarse-clock file system."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def test_the_machine_file_lives_in_the_config_folder(scratch):
    assert config.machine_path() == scratch / "mcp.yaml"


def test_no_file_means_core_only(scratch):
    res = config.resolve()
    assert res["toolsets"] == ["core"] and set(res["tools"]) == set(toolsets.TOOLSETS["core"])


def test_layers_machine_then_archive_then_flag(scratch, arch):
    write(scratch / "mcp.yaml", "toolsets: [core, geo]\ntools: {off: [find_entities]}\n")
    assert config.resolve()["toolsets"] == ["core", "geo"]
    assert "find_entities" not in config.resolve()["tools"]
    write(config.archive_path(arch), "toolsets: [core, shape]\ntools: {on: [find_entities], off: [geo_report]}\n")
    res = config.resolve(arch)
    assert res["toolsets"] == ["core", "shape"]                  # the archive replaces the set list
    assert "find_entities" in res["tools"] and "geo_report" not in res["tools"]
    assert "label" in res["tools"] and "geo_locate" not in res["tools"]
    flagged = config.resolve(arch, spec="core,admin")             # flag over both
    assert flagged["toolsets"] == ["core", "admin"]
    assert "label" not in flagged["tools"] and "pack" in flagged["tools"]


def test_env_overrides_the_files_and_the_flag_overrides_env(scratch, monkeypatch):
    write(scratch / "mcp.yaml", "toolsets: [core, geo]\n")
    monkeypatch.setenv(toolsets.ENV, "core,enrich")
    assert config.resolve()["toolsets"] == ["core", "enrich"]
    assert config.resolve(spec="core,admin")["toolsets"] == ["core", "admin"]


def test_the_never_off_tools_stay_on(scratch):
    write(scratch / "mcp.yaml", "tools: {off: [guide, tasks, task_step, find_entities]}\n")
    res = config.resolve()
    for t in config.NEVER_OFF:
        assert t in res["tools"]
    assert "find_entities" not in res["tools"]
    for t in config.NEVER_OFF:
        with pytest.raises(config.ConfigError, match="never be switched off"):
            config.edit("off", t)
    with pytest.raises(config.ConfigError, match="core is always on"):
        config.edit("off", "core")


def test_unknown_names_are_refused_with_the_valid_ones(scratch):
    with pytest.raises(config.ConfigError) as e:
        config.edit("on", "no_such_thing")
    assert "enrich" in str(e.value) and "geo_report" in str(e.value)
    assert not (scratch / "mcp.yaml").exists()
    write(scratch / "mcp.yaml", "toolsets: [core, bogus]\n")
    assert any("bogus" in p for p in config.resolve()["problems"])      # a bad file never stops the server


def test_locked_names_cannot_be_switched_on(scratch, arch):
    write(scratch / "mcp.yaml", "locked: [admin, geo_report]\n")
    with pytest.raises(config.ConfigError, match="locked"):
        config.edit("on", "admin")
    with pytest.raises(config.ConfigError, match="locked"):
        config.edit("on", "pack")                                      # a tool inside a locked set
    with pytest.raises(config.ConfigError, match="locked"):
        config.edit("on", "geo_report")
    config.edit("on", "geo")                                           # the set is not locked
    got = call("toolset_enable", {"name": "admin"})
    assert got["error"] == "locked"
    got = call("tool_on", {"name": "geo_report"})
    assert got["error"] == "refused" and "locked" in got["why"]
    config.edit("reset")
    assert config.resolve()["locked"] == ["admin", "geo_report"]       # reset keeps what the person locked
    write(config.archive_path(arch), "locked: [shape]\n")
    assert config.resolve(arch)["locked"] == ["admin", "geo_report", "shape"]
    with pytest.raises(config.ConfigError, match="locked"):
        config.edit("on", "shape", arch)


def test_cli_show_on_off_reset(scratch, capsys):
    assert config.cli(["show"]) == 0
    assert "toolsets: core" in capsys.readouterr().out
    assert config.cli(["on", "geo"]) == 0
    out = capsys.readouterr().out
    assert "toolsets: core, geo" in out and "geo_report" in out
    assert "geo" in (scratch / "mcp.yaml").read_text(encoding="utf-8")
    assert config.cli(["off", "find_entities", "--machine"]) == 0
    assert "tools off: find_entities" in capsys.readouterr().out
    assert config.cli(["off", "geo"]) == 0
    assert "toolsets: core\n" in capsys.readouterr().out
    assert config.cli(["on", "find_entities"]) == 0
    assert "tools off: -" in capsys.readouterr().out
    assert config.cli(["reset"]) == 0
    assert not (scratch / "mcp.yaml").exists()
    assert config.cli(["on", "nope"]) == 2
    assert "refused" in capsys.readouterr().err
    assert config.cli(["off", "guide"]) == 2


def test_cli_archive_file_layers_over_the_machine_file(scratch, arch, capsys):
    config.cli(["on", "geo"])
    capsys.readouterr()
    assert config.cli(["off", "geo", "--archive", str(arch)]) == 0
    out = capsys.readouterr().out
    assert "toolsets: core\n" in out
    assert config.load(config.archive_path(arch))["toolsets"] == ["core"]
    assert config.load(config.machine_path())["toolsets"] == ["core", "geo"]
    assert config.cli(["show", "--archive", str(arch)]) == 0
    assert "toolsets: core\n" in capsys.readouterr().out


def test_main_dispatches_config_without_starting_a_server(scratch, capsys):
    with pytest.raises(SystemExit) as e:
        server.main(["config", "show"])
    assert e.value.code == 0
    assert "toolsets:" in capsys.readouterr().out


def test_a_changed_stamp_is_picked_up_on_the_next_call(scratch):
    toolsets.start(server.mcp)
    assert "geo_report" not in on()
    write(scratch / "mcp.yaml", "toolsets: [core, geo]\n")
    v = toolsets._state(server.mcp).version
    call("toolsets")                                                   # any call
    assert "geo_report" in on() and toolsets._state(server.mcp).version == v + 1
    write(scratch / "mcp.yaml", "toolsets: [core]\ntools: {off: [find_entities]}\n")
    bump(scratch / "mcp.yaml")
    call("toolsets")
    assert "geo_report" not in on() and "find_entities" not in on() and "guide" in on()
    res = call("find_entities", {})
    assert res["error"] == "tool not on"


def test_a_call_to_a_tool_the_file_just_switched_on_works(scratch):
    toolsets.start(server.mcp)
    write(scratch / "mcp.yaml", "toolsets: [core, geo]\n")
    got = call("geo_aspects", {})
    assert got.get("error") != "tool not on"


def test_an_archive_file_is_picked_up_when_a_call_names_the_archive(scratch, arch):
    toolsets.start(server.mcp)
    write(config.archive_path(arch), "toolsets: [core, shape]\n")
    call("toolsets", {"archive": str(arch)})
    assert "label" in on() and "geo_report" not in on()


def test_the_flag_stays_over_the_files_on_a_reload(scratch):
    toolsets.start(server.mcp, "core,admin")
    write(scratch / "mcp.yaml", "toolsets: [core, geo]\n")
    call("toolsets")
    assert "pack" in on() and "geo_report" not in on()


def test_the_mcp_tools_edit_the_file_and_apply_at_once(scratch, arch):
    toolsets.start(server.mcp)
    got = call("tool_on", {"name": "geo"})
    assert "geo_report" in on() and got["toolsets"] == ["core", "geo"]
    got = call("toolset_disable", {"name": "geo"})
    assert "geo_report" not in on() and got["toolsets"] == ["core"]
    call("tool_on", {"name": "label"})
    assert "label" in on() and "tags" not in on()
    call("tool_off", {"name": "label"})
    assert "label" not in on()
    got = call("tool_off", {"name": "guide"})
    assert got["error"] == "refused" and "guide" in on()
    got = call("tool_on", {"name": "nope"})
    assert got["error"] == "refused" and "geo_report" in got["why"]
    assert (scratch / "mcp-changes.jsonl").read_text(encoding="utf-8").count("\n") >= 4     # machine changes are logged


def test_an_archive_change_goes_in_the_call_log(scratch, arch):
    toolsets.start(server.mcp)
    call("tool_on", {"name": "geo", "archive": str(arch)})
    assert "geo" in config.load(config.archive_path(arch))["toolsets"]
    logs = list((Path(arch) / ".hydra" / "tasks").glob("*.calls.jsonl"))
    text = "".join(p.read_text(encoding="utf-8") for p in logs)
    assert "config_on" in text and "tool_on" in text


def test_locked_sets_are_listed_for_task_checkout_to_skip(scratch, arch):
    write(scratch / "mcp.yaml", "locked: [geo]\n")
    assert config.locked_sets(arch) == {"geo"}
