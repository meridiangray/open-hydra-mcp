"""config.py: which tools a client sees, from files. `mcp.yaml` in hydra's config folder (machine-wide) and an optional
`<archive>/.hydra/mcp.yaml` on top; the start flag or env `HYDRA_MCP_TOOLSETS` over both.

    toolsets: [core, geo]          sets switched on (`all` for every set); `core` is always on
    tools: {on: [...], off: [...]} single tools switched on or off beyond the sets
    locked: [...]                  sets or tools an agent may not switch on; only the person edits this line

Order, later wins: machine file < archive file < flag/env. `toolsets` is replaced by the later layer; `tools.on` and
`tools.off` are merged (a later layer's on removes an earlier off, and the reverse); `locked` is the union of the
files. A few core tools can never be off (NEVER_OFF). This module only reads, merges and edits files; `toolsets.py`
applies a resolved list to the server. The command line is `hydra-mcp config ...` (see `cli`)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hydra_mcp import toolsets as ts, calllog
from hydra.machine.userdirs import config_dir

FILE = "mcp.yaml"
NEVER_OFF = ("guide", "tasks", "task", "task_checkout", "task_step", "toolsets", "toolset_enable",
             "toolset_disable", "tool_on", "tool_off")


class ConfigError(ValueError):
    """A refused change; the message says why and lists the valid names."""


def machine_path() -> Path:
    return config_dir() / FILE


def archive_path(archive) -> Path:
    return Path(archive) / ".hydra" / FILE


def _names(value) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value)
    return [str(v).strip().lower() for v in (value or ()) if str(v).strip()] if isinstance(value, (list, tuple)) else []


def load(path: Path) -> dict:
    """A file's contents as {toolsets: list|None, on, off, locked}; a missing or unreadable file gives the empty one."""
    out: dict = {"toolsets": None, "on": [], "off": [], "locked": []}
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return out
    if not isinstance(data, dict):
        return out
    if "toolsets" in data:
        out["toolsets"] = _names(data["toolsets"])
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    # YAML 1.1 reads a bare `on:` / `off:` key as True / False, so accept both spellings
    out["on"] = _names(tools.get("on", tools.get(True)))
    out["off"] = _names(tools.get("off", tools.get(False)))
    out["locked"] = _names(data.get("locked"))
    return out


def save(path: Path, doc: dict) -> None:
    """Write a file from the same shape `load` returns; empty parts are left out."""
    body: dict = {}
    if doc.get("toolsets") is not None:
        body["toolsets"] = list(doc["toolsets"])
    tools = {k: list(doc[k]) for k in ("on", "off") if doc.get(k)}
    if tools:
        body["tools"] = tools
    if doc.get("locked"):
        body["locked"] = list(doc["locked"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = "# hydra-mcp: which tools a client sees (hydra-mcp config show)\n" + (yaml.safe_dump(body, sort_keys=False) if body else "{}\n")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def valid_sets() -> list[str]:
    return list(ts.TOOLSETS) + ["all"]


def valid_tools() -> list[str]:
    return sorted(ts.TOOL_SET)


def kind(name: str) -> str:
    """`set` or `tool`; an unknown name is refused with the valid names."""
    name = (name or "").strip().lower()
    if name in valid_sets():
        return "set"
    if name in ts.TOOL_SET:
        return "tool"
    raise ConfigError(f"unknown set or tool {name!r}; sets: {', '.join(valid_sets())}; tools: {', '.join(valid_tools())}")


def stamps(archive=None) -> tuple:
    """One stat per existing config file: the cheap test of whether anything changed."""
    out = []
    for p in (machine_path(), archive_path(archive) if archive else None):
        if p is None:
            continue
        try:
            s = p.stat()
            out.append((str(p), s.st_mtime_ns, s.st_size))
        except OSError:
            pass
    return tuple(out)


def resolve(archive=None, spec: str | None = None) -> dict:
    """The resolved configuration: {toolsets, on, off, locked, tools, files, problems}. `spec` is the start flag;
    when None the env `HYDRA_MCP_TOOLSETS` is used. `tools` is the full list of tool names that are on."""
    layers = [("machine", machine_path())] + ([("archive", archive_path(archive))] if archive else [])
    sets: list[str] | None = None
    on: list[str] = []
    off: list[str] = []
    locked: list[str] = []
    files, problems = [], []
    for label, path in layers:
        if not path.is_file():
            continue
        files.append(str(path))
        d = load(path)
        for n in (d["toolsets"] or []) + d["on"] + d["off"] + d["locked"]:
            try:
                kind(n)
            except ConfigError:
                problems.append(f"{path}: unknown name {n!r}")
        if d["toolsets"] is not None:
            sets = [n for n in d["toolsets"] if n in ts.TOOLSETS or n == "all"]
        for n in d["on"]:
            if n in ts.TOOL_SET:
                off = [x for x in off if x != n]
                on = on + [n] if n not in on else on
        for n in d["off"]:
            if n in ts.TOOL_SET:
                on = [x for x in on if x != n]
                off = off + [n] if n not in off else off
        locked = locked + [n for n in d["locked"] if n not in locked]
    override = spec if spec is not None else os.environ.get(ts.ENV)
    if override:
        sets = ts.parse(override)
    names = ts.parse(",".join(sets)) if sets else [ts.DEFAULT]
    tools = {t for n in names for t in ts.TOOLSETS[n]} | set(on)
    tools -= set(off)
    tools |= set(NEVER_OFF)
    return {"toolsets": names, "on": on, "off": [t for t in off if t not in NEVER_OFF], "locked": locked,
            "tools": sorted(tools), "files": files, "problems": problems}


def check_locked(name: str, archive=None) -> None:
    """Refuse to switch a locked set or tool on (a tool inside a locked set is locked too)."""
    name = (name or "").strip().lower()
    locked = resolve(archive)["locked"]
    hit = name if name in locked else next((s for s in locked if s in ts.TOOLSETS and name in ts.TOOLSETS[s]), None)
    if name == "all":
        hit = next((s for s in locked), None)
    if hit:
        raise ConfigError(f"{name} is locked ({hit}): an agent may not switch it on; the person removes it from "
                          f"`locked` in {machine_path()} or the archive's .hydra/{FILE}")


def locked_sets(archive=None) -> set[str]:
    return {s for s in resolve(archive)["locked"] if s in ts.TOOLSETS}


def _log(action: str, name: str, archive) -> None:
    """Every change goes in a log: the archive's call log when there is an archive, else the config folder's."""
    try:
        if archive:
            calllog.record(f"config_{action}", {"archive": str(Path(archive).resolve()), "name": name}, {"ok": True}, 0)
        else:
            p = machine_path().with_name("mcp-changes.jsonl")
            with p.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "action": action, "name": name}) + "\n")
    except Exception:
        pass


def _base_sets(path: Path, archive) -> list[str]:
    own = load(path)["toolsets"]
    if own is not None:
        return list(own)
    lower = resolve(None) if archive else {"toolsets": [ts.DEFAULT]}
    return list(lower["toolsets"])


def edit(action: str, name: str = "", archive=None) -> dict:
    """`on` / `off` / `reset` on the machine file, or the archive's when `archive` is given. Returns the resolved
    configuration. Refuses unknown names, switching `on` a locked name, and switching off what can never be off."""
    path = archive_path(archive) if archive else machine_path()
    name = (name or "").strip().lower()
    if action == "reset":
        if path.exists():
            doc = load(path)
            save(path, {"locked": doc["locked"]}) if doc["locked"] else path.unlink()
        _log(action, "", archive)
        return resolve(archive)
    k = kind(name)
    if action == "on":
        check_locked(name, archive)
    doc = load(path)
    if k == "set":
        if action == "off" and name in ("core", "all"):
            raise ConfigError(f"{name} cannot be switched off; core is always on. sets: {', '.join(ts.TOOLSETS)}")
        cur = _base_sets(path, archive)
        if name == "all":
            cur = list(ts.TOOLSETS)
        elif action == "on":
            cur = cur + [name] if name not in cur else cur
        else:
            cur = [n for n in (list(ts.TOOLSETS) if "all" in cur else cur) if n != name]
        doc["toolsets"] = cur
    else:
        if action == "off" and name in NEVER_OFF:
            raise ConfigError(f"{name} can never be switched off; the always-on tools are: {', '.join(NEVER_OFF)}")
        add, drop = ("on", "off") if action == "on" else ("off", "on")
        doc[drop] = [x for x in doc[drop] if x != name]
        doc[add] = doc[add] + [name] if name not in doc[add] else doc[add]
    save(path, doc)
    _log(action, name, archive)
    return resolve(archive)


def render(res: dict, archive=None) -> str:
    lines = [f"toolsets: {', '.join(res['toolsets'])}",
             f"tools on: {', '.join(res['on']) or '-'}",
             f"tools off: {', '.join(res['off']) or '-'}",
             f"locked: {', '.join(res['locked']) or '-'}",
             f"tools ({len(res['tools'])}): {', '.join(res['tools'])}",
             f"files: {', '.join(res['files']) or f'none (machine file would be {machine_path()})'}"]
    lines += [f"problem: {p}" for p in res["problems"]]
    return "\n".join(lines)


USAGE = """hydra-mcp config show  [--archive PATH]
hydra-mcp config on    <set|tool> [--machine | --archive PATH]
hydra-mcp config off   <set|tool> [--machine | --archive PATH]
hydra-mcp config reset [--machine | --archive PATH]

Edits mcp.yaml (machine-wide in hydra's config folder, default; or PATH/.hydra/mcp.yaml) and prints the resolved
list. A running server picks the change up before its next tool call. Locked names are refused by `on`."""


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="hydra-mcp config", usage=USAGE, add_help=True)
    ap.add_argument("action", choices=["show", "on", "off", "reset"])
    ap.add_argument("name", nargs="?")
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--machine", action="store_true", help="the machine-wide file (default)")
    where.add_argument("--archive", metavar="PATH", help="the archive's .hydra/mcp.yaml")
    a = ap.parse_args(argv)
    try:
        if a.action in ("on", "off") and not a.name:
            raise ConfigError(f"{a.action} needs a set or tool name; sets: {', '.join(valid_sets())}")
        res = resolve(a.archive) if a.action == "show" else edit(a.action, a.name or "", a.archive)
    except ConfigError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(render(res, a.archive))
    return 0
