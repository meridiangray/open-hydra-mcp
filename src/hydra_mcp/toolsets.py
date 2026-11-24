"""toolsets.py: which tools a client sees. Every tool belongs to exactly one set; `core` is always on, the others
are switched on at start (`--toolsets core,geo`, env `HYDRA_MCP_TOOLSETS`, `all` for everything), by
`toolset_enable`, or by `task_checkout` (the sets the task's route needs).

A tool that is off is taken out of the server's tool list but kept here, so switching it on puts the same tool back
and the write lock and the call log (both wrap the tool manager's call) apply to it as to any other. The server
tells the client the list changed (`notifications/tools/list_changed`) after any call that changed it."""
from __future__ import annotations

import os
import re
import json
from hydra.agents import workflows as hw
from hydra_mcp import config, core
from mcp.server.lowlevel.server import NotificationOptions
from mcp.types import CallToolResult, TextContent

DEFAULT = "core"
ENV = "HYDRA_MCP_TOOLSETS"

TOOLSETS: dict[str, tuple[str, ...]] = {
    "core": (
        "guide", "workflows", "details", "tasks", "task", "task_new", "task_checkout", "task_step", "task_add",
        "task_verify", "task_release", "task_close", "contexts", "context_checkout", "create_archive",
        "describe_schema", "properties", "check", "check_records", "save", "preview", "get_records",
        "amend_records", "find_entities", "explain_entity", "read_file", "source_profile", "source_outline",
        "source_names", "read_source", "sources", "cite",
        "labelling_guidelines", "vocabularies", "keys", "collections", "collection_create", "recipe", "paths",
        "toolsets", "toolset_enable", "toolset_disable", "tool_on", "tool_off", "extra_fields", "field_assign"),
    "enrich": (
        "fetch_source", "drop_source", "swap_source", "source_report", "wikipedia_footnotes", "read_page", "probe",
        "suggestions", "apply_suggestion", "dismiss_suggestion", "suggestions_reset", "enrichers", "enrichments",
        "enrichment_delete", "enrichment_hide", "wikidata_purge", "link_image", "link_images", "stubs",
        "graduate_stub", "pin_upstream", "open_questions", "answer", "decisions", "open_ends", "neighbors", "cast"),
    "wikidata": (                                      # link entries to Wikidata as questions for the person (owner, 2026-11-21)
        "wikidata_questions", "wikidata_answer", "wikidata_status"),
    "checks": (                                        # read-only reviewers for a trailing check (lag-check plan, LC4)
        "check_values", "check_rules", "check_graph", "source_page_image"),
    "geo": (
        "geo_aspects", "geo_contexts", "geo_enable", "geo_locate", "geo_measure", "geo_query",
        "geo_register_status", "geo_report", "geo_resolve", "geo_summarize", "draw_feature", "move_feature",
        "delete_feature", "transform_geometry", "edit_geolink", "edit_siting", "layer_add", "layer_list",
        "layer_remove", "set_primary"),
    "shape": (
        "label", "tags", "badges", "positions", "set_positions", "tree", "set_collection", "set_collection_views",
        "set_collection_group", "collection_merge", "collection_rename", "collection_delete", "move_records", "view_check",
        "view_config", "symbology", "set_symbology", "article_sections", "set_article_section",
        "remove_article_section", "move_article_section", "site", "wiki_serve", "wiki_stop", "publish",
        "wiki_readiness"),
    "admin": (
        "archive_settings", "scope", "set_scope", "packages", "package_install", "pack", "upgrade", "export",
        "history_log", "history_diff", "history_restore", "universe_build", "save_changes"),
}
TOOL_SET: dict[str, str] = {t: s for s, ts in TOOLSETS.items() for t in ts}


def parse(spec: str | None) -> list[str]:
    """`core,geo` or `all` -> set names (core always first). An unknown name raises ValueError."""
    names = [n.strip().lower() for n in re.split(r"[,\s]+", spec or "") if n.strip()]
    if not names:
        names = [DEFAULT]
    if "all" in names:
        return list(TOOLSETS)
    bad = [n for n in names if n not in TOOLSETS]
    if bad:
        raise ValueError(f"unknown toolset {', '.join(bad)}; sets: {', '.join(TOOLSETS)}, all")
    return ["core"] + [n for n in dict.fromkeys(names) if n != "core"]


class _State:
    def __init__(self, mcp):
        self.all = dict(mcp._tool_manager._tools)      # every tool, on or off
        self.version = 0                               # bumped whenever the list changes
        self.flag: str | None = None                   # the start flag (`--toolsets`), which overrides the files
        self.archive: str | None = None                # the last archive a call named: its mcp.yaml is layered on
        self.stamp = config.stamps()                   # the config files as last applied


def _state(mcp) -> _State:
    return mcp._hydra_toolsets


def is_on(mcp, name: str) -> bool:
    return name in mcp._tool_manager._tools


def set_on(mcp, name: str) -> bool:
    mine = [t for t in TOOLSETS[name] if t in _state(mcp).all]
    return bool(mine) and all(is_on(mcp, t) for t in mine)


def status(mcp) -> dict:
    st = _state(mcp)
    return {"toolsets": [{"name": n, "on": set_on(mcp, n), "tools": [t for t in ts if t in st.all]}
                         for n, ts in TOOLSETS.items()]}


def enable(mcp, name: str) -> list[str]:
    """Switch a set (or `all`) on; returns the tools added."""
    names = list(TOOLSETS) if name == "all" else [name]
    if any(n not in TOOLSETS for n in names):
        raise ValueError(f"unknown toolset {name}; sets: {', '.join(TOOLSETS)}, all")
    st, tools = _state(mcp), mcp._tool_manager._tools
    added = []
    for n in names:
        for t in TOOLSETS[n]:
            if t in st.all and t not in tools:
                tools[t] = st.all[t]
                added.append(t)
    if added:
        st.version += 1
    return added


def apply(mcp, spec: str | None) -> list[str]:
    """Start-up selection: keep only the tools of the named sets; returns the sets on."""
    names = parse(spec)
    st, tools = _state(mcp), mcp._tool_manager._tools
    keep = {t for n in names for t in TOOLSETS[n]}
    for t in list(tools):
        if t not in keep and t in TOOL_SET:
            del tools[t]
    for t in keep:
        if t in st.all:
            tools[t] = st.all[t]
    st.version += 1
    return names


def startup_spec(arg: str | None = None) -> str:
    return arg or os.environ.get(ENV) or DEFAULT


def apply_resolved(mcp, res: dict) -> bool:
    """Make the tool list exactly a resolved configuration's (`config.resolve`); True when it changed."""
    st, tools = _state(mcp), mcp._tool_manager._tools
    keep = set(res["tools"])
    before = set(tools)
    for t in list(tools):
        if t in TOOL_SET and t not in keep:
            del tools[t]
    for t in keep:
        if t in st.all:
            tools[t] = st.all[t]
    changed = set(tools) != before
    if changed:
        st.version += 1
    return changed


def start(mcp, flag: str | None = None) -> dict:
    """Start-up: the files' list, with the flag (else env) over them."""
    st = _state(mcp)
    st.flag = flag
    st.stamp = config.stamps()
    res = config.resolve(spec=flag)
    apply_resolved(mcp, res)
    st.version += 1
    return res


def refresh(mcp, archive=None) -> bool:
    """Before each call: one stat per config file; when a stamp changed (or a call names an archive whose mcp.yaml
    exists), re-resolve and apply, so the tool list follows the file. True when the list changed."""
    st = _state(mcp)
    arch = archive if isinstance(archive, str) and archive else st.archive
    try:
        now = config.stamps(arch)
    except Exception:
        return False
    if now == st.stamp:
        return False
    st.stamp, st.archive = now, arch
    return apply_resolved(mcp, config.resolve(arch, spec=st.flag))


def _changed_result(mcp, res: dict) -> dict:
    return {"toolsets": res["toolsets"], "tools_on": res["on"], "tools_off": res["off"], "locked": res["locked"],
            "tools": res["tools"]}


def change(mcp, action: str, name: str, archive=None) -> dict:
    """The MCP tools' work: edit the machine file (or the archive's) and apply it now. Raises config.ConfigError."""
    arch = None
    if archive:
        arch = str(core.open_archive(archive))
    res = config.edit(action, name, arch)
    st = _state(mcp)
    st.stamp, st.archive = config.stamps(arch), arch or st.archive
    apply_resolved(mcp, config.resolve(st.archive, spec=st.flag))
    return _changed_result(mcp, res)


def sets_for_tools(tools) -> list[str]:
    return list(dict.fromkeys(TOOL_SET[t] for t in tools if t in TOOL_SET))


def route_tools(root, task: dict) -> list[str]:
    """The tools a task's route needs: each step's `tool` in its workflows, plus its views' blocks."""
    out: list[str] = []
    views = list(task.get("views") or ())
    for i, name in enumerate(task.get("route") or ([task["workflow"]] if task.get("workflow") else []), 1):
        try:
            wf = hw.load_workflow(name, root)
            blocks, _ = hw.expand_blocks(wf, views=views if i == 1 else ())
        except Exception:
            continue
        out += [s["tool"] for b in blocks for s in b["steps"] if s.get("tool")]
    return list(dict.fromkeys(out))


def enable_for_task(mcp, root, task: dict) -> list[str]:
    """Switch on the sets a task's route needs; returns the set names that were switched on now."""
    newly = []
    locked = config.locked_sets(root)
    for s in sets_for_tools(route_tools(root, task)):
        if s not in locked and not set_on(mcp, s) and enable(mcp, s):
            newly.append(s)
    return newly


def install(mcp) -> None:
    """Call last, after every tool is registered. Keeps the full tool table, makes the server announce that its tool
    list can change, answers a call to a tool that is off, and tells the client when a call changed the list."""
    mcp._hydra_toolsets = _State(mcp)
    mgr = mcp._tool_manager
    inner = mgr.call_tool

    low = mcp._mcp_server
    make = low.create_initialization_options

    def init_options(notification_options=None, *a, **kw):
        if notification_options is None:
            notification_options = NotificationOptions(tools_changed=True)
        return make(notification_options, *a, **kw)
    low.create_initialization_options = init_options

    async def call_tool(name, arguments, *a, **kw):
        before = mcp._hydra_toolsets.version
        refresh(mcp, (arguments or {}).get("archive"))      # a config file changed: apply it before this call
        try:
            if name not in mgr._tools and name in TOOL_SET:
                s = TOOL_SET[name]
                payload = {"error": "tool not on", "why": f"{name} is in the {s} toolset, which is off",
                           "do": f'toolset_enable("{s}")'}
                if not kw.get("convert_result"):
                    return payload
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, indent=2))],
                                      isError=True)
            return await inner(name, arguments, *a, **kw)
        finally:
            if mcp._hydra_toolsets.version != before:
                ctx = kw.get("context") or (a[0] if a else None)
                try:
                    await ctx.session.send_tool_list_changed()
                except Exception:                      # no live client (a direct call, a test)
                    pass

    mgr.call_tool = call_tool
