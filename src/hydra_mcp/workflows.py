"""workflows.py — guides, tracked tasks, views, and CLI orientation tools for hydra-mcp.

Thin over `hydra.guides`, `hydra.workflows`, `hydra.tasks`, `hydra.wiki.viewcheck`, `hydra.tree`,
`hydra.wiki.manage`, `hydra.cli.details`, and `hydra.cli.check`.

Each server process is one session with its own holder name (`agent:hydra-mcp#k3f9`, or
`agent:<name>#k3f9` when the agent names itself at checkout). `_CURRENT_TASK[archive]` is the task this
session checked out: write tools append a log line to it and `fetch_source` / `save` / `site` add the
sources they keep. A task held by another holder refuses this session's steps.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from hydra_mcp import core
from hydra_mcp.core import AGENT, IngestError

from hydra import tasks as _tasks

SESSION = _tasks.PROCESS_ID                       # 4 hex per server process
_CURRENT_TASK: dict[str, str] = {}
_CURRENT_HOLDER: dict[str, str] = {}


def client_name() -> str | None:
    """The MCP client's name from its initialize message (`clientInfo.name`), when a request is running."""
    global _CLIENT
    if _CLIENT is None:
        try:
            from hydra_mcp import server
            _CLIENT = server.mcp.get_context().session.client_params.clientInfo.name or None
        except Exception:
            return None
    return _CLIENT


_CLIENT: str | None = None


def _holder(root: Path, name: str | None = None) -> str:
    """This session's holder name for `root`: a name the agent gave, else the one it checked out as, else
    `<client>·<4 hex>` (`$HYDRA_HOLDER` overrides; never a user name)."""
    if name and str(name).strip():
        return str(name).strip()
    return _CURRENT_HOLDER.get(str(Path(root).resolve())) or _tasks.process_holder(client_name() or "mcp")


def _warned(got, msg: str):
    """A read-only tool's answer with a top-level `warning`: in the structured result, and in its text."""
    from mcp.types import TextContent
    if isinstance(got, dict):
        return {**got, "warning": msg}
    if isinstance(got, tuple) and len(got) == 2 and isinstance(got[1], dict):
        blocks, structured = list(got[0]), {**got[1], "warning": msg}
        if len(blocks) == 1 and isinstance(blocks[0], TextContent):
            try:
                body = json.loads(blocks[0].text)
            except ValueError:
                body = None
            if isinstance(body, dict):
                return [TextContent(type="text", text=json.dumps({**body, "warning": msg}, indent=2))], structured
        return [TextContent(type="text", text=json.dumps({"warning": msg}))] + blocks, structured
    if isinstance(got, (list, tuple)):
        return [TextContent(type="text", text=json.dumps({"warning": msg}))] + list(got)
    return got


def install_write_lock(mcp) -> None:
    """Wrap every tool call: a call that writes takes the archive's write lock (one writer at a time; a second
    waits a few seconds, then gets {error: "busy", why, do}), and every failure of any tool reaches the client as
    `{error, why, do}` (see `failure_payload`). This is the one place the error shape is made."""
    from hydra import writelock
    from hydra_mcp import core, stale                  # stale notes the code this server starts with
    mgr = mcp._tool_manager
    inner = mgr.call_tool

    def reply(payload, kw):
        if not kw.get("convert_result"):
            return payload
        from mcp.types import CallToolResult, TextContent
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, indent=2))], isError=True)

    async def call_tool(name, arguments, *a, **kw):
        args = arguments or {}
        try:
            tool = mgr.get_tool(name)
            known = set((getattr(tool, "parameters", None) or {}).get("properties") or {}) if tool else None
            unknown = sorted(set(args) - known) if known is not None else []
            if unknown:                                    # a misspelt or guessed argument is never silently dropped
                return reply({"error": "unknown argument" + ("s" if len(unknown) > 1 else ""),
                              "why": f"{name} has no argument {', '.join(unknown)}; it takes {', '.join(sorted(known))}",
                              "do": "call again with only those arguments; nothing was changed"}, kw)
            old = stale.message()
            writes = name in ALWAYS_WRITES or args.get("confirm") is True
            if old and (writes or name in BUILDS):                             # the loaded code is not the code on disk: refuse before a build fails
                return reply(stale.refusal(old), kw)

            async def run():
                got = await inner(name, arguments, *a, **kw)
                return _warned(got, old) if old else got
            if name in LOCKS_ITSELF or not writes:
                return await run()
            try:
                root = core.open_archive(args.get("archive"))
            except Exception:                              # no archive yet (create_archive): nothing to lock
                return await run()
            with writelock.hold(root, _holder(root)):
                return await run()
        except writelock.Busy as e:
            return reply(e.payload, kw)
        except (Exception, SystemExit) as e:
            return reply(failure_payload(e), kw)

    mgr.call_tool = call_tool


# kind of failure -> (error, do). `kind` is the exception class name; `_run` and `_wrap` keep it on IngestError.
_FAILURES = {
    "NoArchive": ("no archive", "ask the person which archive to use and pass its folder as `archive`, or offer create_archive"),
    "TaskError": ("task refused", "call tasks() to see each task's holder and state, then check out, release or pick another"),
    "GuideError": ("unknown guide", "call guide() with no topic for the list"),
    "WorkflowError": ("unknown workflow", "call workflows() for the list"),
    "ViewError": ("view refused", "call collections() and view_config() for the names and views that exist"),
    "SystemExit": ("hydra refused", "correct the arguments as `why` says and call again; nothing was changed"),
    "ValidationError": ("bad arguments", "check the tool's parameter names and types"),
    "FileNotFoundError": ("not found", "check the path; read_file and sources list what exists"),
    "MintError": ("refused", "correct the request as `why` says and call again; nothing was changed"),
    "IngestError": ("refused", "correct the request as `why` says and call again; nothing was changed"),
    "ValueError": ("refused", "correct the request as `why` says and call again; nothing was changed"),
    "Ambiguous": ("ambiguous entity", "ask the person which of the Hs `why` lists they mean (read_page or "
                  "explain_entity tells them apart), then call again with that H; nothing was changed"),
    "NotFound": ("no such entity", "find it with find_entities (the `near` Hs in `why` are only hints), "
                 "then call again with its H; nothing was changed"),
}


def failure_payload(exc: BaseException) -> dict:
    """Any exception a tool raised as `{error, why, do}`. The message is kept as `why`; the kind picks `error` and `do`."""
    seen = exc
    while seen is not None:
        pay = getattr(seen, "payload", None)
        if isinstance(pay, dict) and {"error", "why", "do"} <= set(pay):
            return pay
        kind = getattr(seen, "kind", None) or type(seen).__name__
        if kind in _FAILURES:
            break
        seen = seen.__cause__
    else:
        seen = exc
        while seen.__cause__ is not None:
            seen = seen.__cause__
        kind = type(seen).__name__
    error, do = _FAILURES.get(kind, ("failed", "report `why` to the person; do not retry in a loop"))
    why = str(seen).strip() or type(seen).__name__
    if isinstance(seen, SystemExit):
        why = str(seen.code if seen.code is not None else "").removeprefix("hydra: ") or "stopped"
    elif why.startswith("Error executing tool "):
        why = why.split(": ", 1)[-1]
    return {"error": error, "why": why, "do": do}


# tools that fetch over the network first and take the write lock themselves, for the writing only
LOCKS_ITSELF = {"fetch_source"}

# tools that write without a `confirm` argument (the rest write only when confirm=true)
BUILDS = {"details", "preview"}                   # read-only in the archive, but they build: refused too when the server is stale
ALWAYS_WRITES = {"save", "fetch_source", "universe_build", "task_checkout", "task_add",
                 "task_step", "task_release", "task_close"}


def _wrap(fn, *a, **kw):
    from hydra import contexts, guides, tasks, workflows
    from hydra.wiki import viewcheck
    try:
        return fn(*a, **kw)
    except (guides.GuideError, workflows.WorkflowError, tasks.TaskError, viewcheck.ViewError,
            contexts.ContextError) as e:
        raise IngestError(str(e), kind=type(e).__name__) from None
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: "), kind="SystemExit") from None


def current_task(root: Path) -> str | None:
    """The checked-out task id for `root` in this MCP session (verified still checked-out)."""
    key = str(Path(root).resolve())
    tid = _CURRENT_TASK.get(key)
    if not tid:
        return None
    from hydra import tasks
    try:
        info = tasks.get_task(root, tid)
    except tasks.TaskError:
        _CURRENT_TASK.pop(key, None)
        return None
    if info["status"] != "checked-out":
        _CURRENT_TASK.pop(key, None)
        return None
    return tid


def hook_source(root: Path, source_id: str, note: str = "") -> None:
    tid = current_task(root)
    if not tid or not source_id:
        return
    from hydra import tasks
    try:
        tasks.record_source(root, tid, source_id, note=note)
    except Exception:
        pass


def hook_unsource(root: Path, source_id: str) -> None:
    """A dropped source leaves the task's list of kept sources."""
    tid = current_task(root)
    if not tid or not source_id:
        return
    from hydra import tasks
    try:
        p, task = tasks._read(root, tid)
        had = list(task["meta"].get("sources") or ())
        if source_id in had:
            task["meta"]["sources"] = [x for x in had if x != source_id]
            tasks._write(p, task)
    except Exception:
        pass


def hook_log(root: Path, message: str) -> None:
    tid = current_task(root)
    if not tid or not message:
        return
    from hydra import tasks
    try:
        tasks.log_action(root, tid, message)
    except Exception:
        pass


# ---- guides & workflows --------------------------------------------------------------

def guide(topic: str | None = None, section: str | None = None, archive: str | None = None) -> dict:
    """The guide, with `hydra_version`: the version of hydra that wrote it."""
    from hydra import __version__
    return {"hydra_version": __version__, **_guide(topic, section, archive)}


def _guide(topic, section, archive) -> dict:
    from hydra import guides
    from hydra_mcp import core
    root = None
    if archive:
        try:
            root = core.open_archive(archive)
        except IngestError:
            root = None
    if not topic:
        listed = _wrap(guides.list_guides, root)
        listed += _context_guides(root)
        return {"start": "guide('start')", "guides": listed}
    if topic.strip().strip("/") == "records":
        return {"topic": "records", "call": "labelling_guidelines",
                "note": "How records are written for this archive comes from `labelling_guidelines`."}
    norm = topic.strip().strip("/").removesuffix(".md")
    if norm.startswith("context/"):
        return _context_guide(norm, section, root)
    out = _wrap(guides.read_guide, topic, section, root)
    if out["topic"] == "tools" and not section:
        out["content"] += chr(10) + _tool_lines()
    return out


def _context_guides(root) -> list[dict]:
    """The contexts as guide topics (`context/<name>`), listed beside the workflows."""
    from hydra import contexts, guides
    out = []
    for c in _wrap(contexts.list_contexts, root):
        d = guides._parse(f"context/{c['name']}", contexts.render_context(c["name"], root))
        out.append({"topic": d["topic"], "title": d["title"], "summary": c.get("use_when") or c["title"],
                    "sections": d["sections"]})
    return out


def _context_guide(norm: str, section, root) -> dict:
    """`guide("context/<name>")`: the context's brief, rendered like a workflow's guide."""
    from hydra import contexts, guides
    name = norm.split("/", 1)[1]
    try:
        parsed = guides._parse(norm, contexts.render_context(name, root))
        if section:
            heading, content = guides._slice(parsed, section)
            return {"topic": norm, "title": parsed["title"], "section": heading,
                    "sections": parsed["sections"], "content": content}
    except (contexts.ContextError, guides.GuideError) as e:
        raise IngestError(str(e), kind=type(e).__name__) from None
    return {"topic": norm, "title": parsed["title"], "summary": parsed["summary"],
            "sections": parsed["sections"], "content": parsed["text"]}


def _tool_lines() -> str:
    """Every registered tool with the first sentence of its description, so this list cannot go stale."""
    from hydra_mcp import server
    mgr = getattr(server.mcp, "_tool_manager", None)
    tools = getattr(mgr, "_tools", {}) if mgr else {}
    lines = ["## Every tool", ""]
    for name in sorted(tools):
        desc = " ".join((getattr(tools[name], "description", "") or "").split())
        first = desc.split(". ")[0].split(": ")[0].rstrip(".")
        lines.append(f"- `{name}`: {first}.")
    return chr(10).join(lines) + chr(10)


def workflows_list(root: Path | None = None) -> dict:
    from hydra import workflows
    return {"workflows": _wrap(workflows.list_workflows, root)}


# ---- tasks ---------------------------------------------------------------------------

def list_tasks(root: Path, status: str | None = None, workflow: str | None = None,
               collection: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    from hydra import tasks
    cur = current_task(root)
    rows, paging = core.page(_wrap(tasks.list_tasks, root, status=status, workflow=workflow, collection=collection),
                             offset, limit)
    return {"current_task": cur, **paging, "tasks": rows}


def task_new(root: Path, title: str, workflow: str | list[str] | None = None, collection: str | None = None,
             views: list[str] | None = None, subjects: list[str] | None = None, confirm: bool = False,
             authorized: list[str] | None = None, context: str | None = None) -> dict:
    from hydra import tasks
    return _wrap(tasks.create_task, root, title, workflow, collection, views_as_list(views), subjects, confirm,
                 _holder(root), authorized, context)


def contexts_list(root: Path, task: str | None = None, words: str = "") -> dict:
    """The contexts: ranked for a task (or for `words`), or the plain list with each `use_when`."""
    from hydra import contexts
    if task or words:
        return {"contexts": _wrap(contexts.rank_contexts, root, task, words)}
    return {"contexts": _wrap(contexts.list_contexts, root)}


def context_checkout(root: Path, task_id: str, name: str, reason: str, confirm: bool = False) -> dict:
    from hydra import tasks
    return _wrap(tasks.set_context, root, _task_id(root, task_id), name, reason, confirm, _holder(root))


BRIEF_MAX = 2500                                     # chars of a context's brief sent inline at checkout


def _brief(root: Path, name: str) -> dict:
    from hydra import contexts
    text = contexts.render_context(name, root)
    if len(text) <= BRIEF_MAX:
        return {"brief": text}
    return {"brief": f"long: read it with guide(\"context/{name}\")"}


def task_checkout(root: Path, task_id: str, holder: str | None = None, force: bool = False,
                  reason: str = "", details: bool = False, model: str | None = None,
                  client: str | None = None) -> dict:
    from hydra import tasks
    who = _holder(root, holder)
    out = _wrap(tasks.checkout_task, root, task_id, holder=who, force=force, reason=reason,
                model=model, client=client)
    ctx = out.get("context")
    name = ctx.get("name") if isinstance(ctx, dict) else ctx
    if name:
        try:
            out.update(_brief(root, name))
        except Exception:
            out["brief"] = f"read it with guide(\"context/{name}\")"
    key = str(Path(root).resolve())
    _CURRENT_TASK[key], _CURRENT_HOLDER[key] = out["id"], who
    tasks.MCP_HOLDER[who] = True
    try:
        info = globals()["details"](root)
        newer = info.get("newer_than_build")
        if not details:                              # the full dump only on request: a short summary is what a start needs
            keep = ("name", "subject", "built", "records", "entities", "claims", "open")
            short = {k: info[k] for k in keep if k in info}
            if info.get("collections"):
                short["collections"] = {c: v.get("records") for c, v in info["collections"].items()}
            if newer:
                short["newer_than_build_count"] = len(newer)
                short["newer_than_build_hint"] = "run `universe_build` to bring the pages up to date"
            short["more"] = "task_checkout(details=true) gives the full archive details"
            info = short
        out["archive_details"] = info
    except Exception:
        pass
    out["guides_to_load"] = out["guides"]
    if not details and isinstance(out.get("steps"), list):   # the checklist as one line a step; `task()` has it all
        out["steps"] = [f"{s.get('code')} {s.get('text')}" + (f" [{s['status']}]" if s.get("status") not in (None, "open") else "")
                        for s in out["steps"] if s.get("kind", "step") == "step"]
        if out.get("log"):
            out["log"] = out["log"][-3:]
    if out.get("needs_context"):
        out["next"] = ("this task has no context: call `contexts(task)`, choose one with the person through "
                       "`context_checkout` (or `general` when unattended), then do next_step")
    else:
        out["next"] = ("read each guide in guides_to_load, then do next_step; tick it with task_step "
                       "(code, result) before starting the next")
    return out


def _task_id(root: Path, task_id: str | None) -> str:
    if task_id:
        return task_id
    cur = current_task(root)
    if cur:
        return cur
    from hydra import tasks
    sole = tasks.active_task_id(root)
    if sole:
        return sole
    raise IngestError("no checked-out task in this session: pass `id` or call `task_checkout` first")


def task_show(root: Path, task_id: str | None = None) -> dict:
    from hydra import tasks
    return _wrap(tasks.get_task, root, _task_id(root, task_id))


def _tick_reply(out: dict) -> dict:
    """A tick's reply: the step ticked, the counts and the next step. The whole step list and log came back on
    every tick (about 6k tokens), and a Sonnet run stopped ticking because of it (2026-11-21 Pollard run)."""
    if not isinstance(out, dict) or "steps" not in out:
        return out
    short = {k: v for k, v in out.items() if k not in ("steps", "log")}
    if out.get("log"):
        short["log"] = out["log"][-3:]
    short["more"] = "task() shows every step and the whole log"
    return short


def task_step(root: Path, step: str, status: str = "done", result: str = "", reason: str = "",
              claim: str | None = None, evidence: list[str] | None = None,
              subject: str | None = None, task_id: str | None = None, verify: bool = True,
              exit: str | None = None) -> dict:
    from hydra import tasks
    tid = _task_id(root, task_id)
    try:
        out = _wrap(tasks.step_task, root, tid, step, status=status, result=result, reason=reason,
                    claim=claim, evidence=evidence, subject=subject, holder=_holder(root), verify=verify,
                    exit=exit)
        return _tick_reply(out)
    except IngestError as e:
        if "still finds:" in str(e):                 # the step's check found warnings: say how to go on, not "call tasks()"
            e.payload = {"error": "task refused", "why": str(e),
                         "do": "fix the findings, or tick it again with `reason` explaining why each remaining finding is expected"}
        raise


def task_add(root: Path, subject: str | None = None, step: str | None = None, block: str | None = None,
             code: str | None = None, task_id: str | None = None) -> dict:
    from hydra import tasks
    tid = _task_id(root, task_id)
    return _wrap(tasks.add_to_task, root, tid, subject=subject, step=step, block=block, code=code)


def task_verify(root: Path, task_id: str | None = None) -> dict:
    from hydra import tasks
    return _wrap(tasks.verify_task, root, _task_id(root, task_id))


def task_release(root: Path, task_id: str | None = None, force: bool = False) -> dict:
    from hydra import tasks
    tid = _task_id(root, task_id)
    out = _wrap(tasks.release_task, root, tid, holder=_holder(root), force=force)
    _CURRENT_TASK.pop(str(Path(root).resolve()), None)
    return out


def task_close(root: Path, status: str = "done", summary: str = "", task_id: str | None = None,
               force: bool = False) -> dict:
    from hydra import tasks
    tid = _task_id(root, task_id)
    out = _wrap(tasks.close_task, root, tid, status=status, summary=summary, holder=_holder(root), force=force)
    _CURRENT_TASK.pop(str(Path(root).resolve()), None)
    return out


# ---- views & CLI-parity read tools ---------------------------------------------------

def collections(root: Path) -> dict:
    from hydra.wiki import viewcheck
    return {"collections": _wrap(viewcheck.collections_overview, root)}


def views_as_map(views) -> dict | None:
    """`views` as a map of view to setting: a list of names means those views are on."""
    if isinstance(views, (list, tuple)):
        bad = [v for v in views if not isinstance(v, str) or not v.strip()]
        if bad:
            raise IngestError("a list of views holds view names (org, links, radial, map, timeline, graph); "
                              "give a map {\"org\": true} to set a view's spec")
        return {v.strip(): True for v in views}
    return views


def views_as_list(views) -> list[str] | None:
    """`views` as a list of names: a map means the views it switches on (a spec counts as on)."""
    if isinstance(views, dict):
        return [k for k, v in views.items() if v not in (False, None, "", [], {})]
    return views


def set_collection_views(root: Path, collection: str, views: dict | None = None, confirm: bool = False,
                         title: str | None = None) -> dict:
    from hydra.wiki import viewcheck
    out = _wrap(viewcheck.set_collection_views, root, collection, views_as_map(views), confirm=confirm, who=AGENT, title=title)
    if confirm:
        hook_log(root, f"set_collection_views {collection}: {out['enabled']}")
    return out


def view_config(root: Path, collection: str | None = None) -> dict:
    from hydra.wiki import viewcheck
    return _wrap(viewcheck.view_config, root, collection)


def view_check(root: Path, view: str, collection: str | None = None) -> dict:
    from hydra.wiki import viewcheck
    return _wrap(viewcheck.check_view, root, view, collection)


def tree(root: Path, kind: str | None = None, search: str | None = None,
         read: str = "declared", format: str = "text") -> dict:
    from hydra import query, resources, schema, tree as htree
    if read not in htree.READS:
        raise IngestError(f"read must be one of: {', '.join(htree.READS)}")
    if format not in ("text", "json"):
        raise IngestError("format must be 'text' or 'json'")
    from hydra import layout
    from hydra.review import verdicts as vd
    from hydra.structure import fold
    schema.load(root=root)
    ir, _ = _wrap(htree._load, root, read)
    words = [x for x in (kind, search) if x]
    starts = None
    if words:
        kinds, text = query.split(words)
        starts = htree.starts_of(ir, kinds, text)
        if not starts:
            return {"read": read, "roots": 0, "note": f"no record matches {' '.join(words)!r}"}
    fam = Path(root) / layout.DIRECTION
    direction = fold.load_direction(fam if fam.is_file() else None)
    verdicts, _ = vd.load(root)
    model = htree.record_tree(ir, starts, htree.also_under(ir, direction, verdicts))
    if format == "json":
        return {"read": read, "roots": len(model), "tree": model}
    return {"read": read, "roots": len(model), "text": htree.render(model, ascii=True)}


def positions(root: Path, mode: str = "both", with_nodes: bool = False, read: str = "declared") -> dict:
    from hydra import tree as htree
    from hydra.cli import positions as pcli
    if mode not in ("both", "tree", "unplaced"):
        raise IngestError("mode must be one of: both, tree, unplaced")
    if read not in pcli.READS:
        raise IngestError(f"read must be one of: {', '.join(pcli.READS)}")
    ir, parsed = _wrap(htree._load, root, read)
    model = htree.position_tree(ir, parsed if read == "declared" else None, with_nodes=with_nodes)
    unrelated = (ir.get("report") or {}).get("unrelated_titles") or []
    issues = parsed.get("issues") or []
    return {
        "read": read,
        **({"tree": model} if mode in ("both", "tree") else {}),
        **({"unplaced_titles": unrelated, "unplaced_count": len(unrelated)} if mode in ("both", "unplaced") else {}),
        "issues": issues,
    }


def badges(root: Path) -> dict:
    from hydra.wiki import manage, org as worg
    from hydra_mcp import pipeline
    w = pipeline._wiki(root)
    report = manage.badge_report(w)
    post = w.reg.roles.POST
    unmatched_posts = sorted(
        w.title(b, qualified=False) for b in w.listed
        if w.pages[b]["schema"] == post and worg._role(w.reg, w.title(b, qualified=False)) is None
    )
    return {"rules": report, "unmatched_post_titles": unmatched_posts, "unmatched_count": len(unmatched_posts)}


def details(root: Path) -> dict:
    from hydra.cli import details as hdetails
    return _wrap(hdetails.collect, root)


def check(root: Path) -> dict:
    from hydra.cli import check as hcheck
    issues = _wrap(hcheck.run, root)
    extra, built, stands = _wrap(hcheck.last_build, root, issues)
    return {"issues": issues, "last_build_extra": extra, "build_stands": stands,
            "counts": {lv: sum(1 for i in issues if i["level"] == lv) for lv in ("error", "warning", "info")}}
