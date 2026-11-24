"""calllog.py — the MCP call log: one JSON line per tool call, in the task this server holds.

`install(mcp)` wraps `mcp._tool_manager.call_tool` outermost. After each call it finds the archive (the
`archive` argument) and the one `checked-out` task there held by this server (a holder in
`hydra.agents.tasks.MCP_HOLDER`), and appends a row to `.hydra/tasks/<task id>.calls.jsonl`:
`{n, at, tool, args, ok, error, ms, step, holder}`. Arguments are summarised, never copied: long strings
become `"<N chars>"`, text-bearing keys are always reduced, secrets are never written. Logging never breaks a
call: every failure to log is swallowed and the reply goes back unchanged.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from hydra.agents import tasks
from hydra_mcp import workflows, core

LONG = 80                                   # strings longer than this are reduced
CACHE_SECONDS = 2.0
TEXT_KEYS = {"text", "notes", "quote", "quotes", "body", "content", "records"}
SECRET_WORDS = ("key", "token", "secret", "password")
ENDS_TASK = {"task_release", "task_close"}   # after these the task is no longer held: fall back to the cached one

_cache: dict[str, tuple[float, str, str]] = {}      # archive -> (time, task id, holder)
_lock = threading.Lock()


def _size(v) -> str:
    if isinstance(v, str):
        return f"<{len(v)} chars>"
    if isinstance(v, (list, tuple, set)):
        return f"<{len(v)} items>"
    if isinstance(v, dict):
        return f"<{len(v)} keys>"
    return "<1 item>"


def _records(v):
    out: dict = {"n": _size(v)}
    if isinstance(v, (list, tuple)):
        counts: dict[str, int] = {}
        for r in v:
            s = r.get("schema") if isinstance(r, dict) else None
            if isinstance(s, str):
                counts[s] = counts.get(s, 0) + 1
        if counts:
            out["schemas"] = counts
    return out


def summarise(value, key: str = "", depth: int = 0):
    """A short, source-free summary of one argument value."""
    k = key.lower()
    if any(w in k for w in SECRET_WORDS):
        return "<hidden>"
    if k == "records":
        return _records(value)
    if k in TEXT_KEYS:
        return _size(value) if isinstance(value, (str, list, tuple, dict)) else value
    if isinstance(value, str):
        return _size(value) if len(value) > LONG else value
    if isinstance(value, dict):
        if depth >= 3:
            return _size(value)
        return {str(a): summarise(b, str(a), depth + 1) for a, b in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 10 or depth >= 3:
            return _size(value)
        return [summarise(x, key, depth + 1) for x in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _size(str(value))


def _payload(result):
    """The dict an answer carries, if any (a plain dict, a (blocks, structured) pair, or an error result)."""
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    blocks = getattr(result, "content", None)
    if blocks is None and isinstance(result, list):
        blocks = result
    if blocks and len(blocks) == 1 and isinstance(getattr(blocks[0], "text", None), str):
        try:
            body = json.loads(blocks[0].text)
        except ValueError:
            return None
        return body if isinstance(body, dict) else None
    return None


def outcome(result) -> tuple[bool, dict | None]:
    """(ok, error) of an answer: failed when it is an `isError` result or a dict with `error`."""
    pay = _payload(result)
    failed = bool(getattr(result, "isError", False)) or (isinstance(pay, dict) and bool(pay.get("error")))
    if not failed:
        return True, None
    pay = pay or {}
    return False, {"error": str(pay.get("error") or "failed"), "why": str(pay.get("why") or "")[:160]}


def _held(root: Path, tool: str) -> tuple[str, str] | None:
    key = str(root)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if tool.startswith("task_"):
            _cache.pop(key, None)                  # the held task may have changed
    if hit and now - hit[0] < CACHE_SECONDS and tool not in ENDS_TASK and not tool.startswith("task_"):
        return hit[1], hit[2]
    mine = [t for t in tasks.list_tasks(root, status="checked-out") if t.get("holder") in tasks.MCP_HOLDER]
    # the task this session checked out last wins: with two held, the log used to stop altogether
    # (2026-11-21 Pollard run: every call after the second checkout went unlogged)
    cur = workflows._CURRENT_TASK.get(key)
    pick = next((t for t in mine if t["id"] == cur), None) or (mine[0] if len(mine) == 1 else None)
    if pick:
        found = (pick["id"], pick["holder"])
        with _lock:
            _cache[key] = (now, *found)
        return found
    if tool in ENDS_TASK and hit:
        return hit[1], hit[2]
    return None


UNTASKED = "untasked"                        # calls made in an archive while this server holds no task there


def _next_code(root: Path, task_id: str):
    try:
        nxt = tasks.get_task(root, task_id).get("next_step")
    except Exception:
        return None
    return nxt.get("code") if isinstance(nxt, dict) else None


def _append(root: Path, task_id: str, row: dict) -> None:
    path = tasks.tasks_dir(root) / f"{task_id}.calls.jsonl"
    with _lock:
        n = 1
        if path.exists():
            with path.open("rb") as f:
                n = sum(1 for line in f if line.strip()) + 1
        row = {"n": n, **row}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(name: str, args: dict, result, ms: int, raised: BaseException | None = None) -> None:
    """Append the row for one finished call, when this server holds a task in the call's archive."""
    try:
        if not args.get("archive"):
            return
        root = Path(core.open_archive(args.get("archive"))).resolve()
        held = _held(root, name)
        task_id, holder = held if held else (UNTASKED, None)   # kept, not dropped: work before a task is a finding
        if raised is not None:
            ok, error = False, {"error": type(raised).__name__, "why": str(raised)[:160]}
        else:
            ok, error = outcome(result)
        _append(root, task_id, {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "tool": name, "args": summarise(args), "ok": ok, "error": error, "ms": ms,
            "step": _next_code(root, task_id) if held else None, "holder": holder})
    except Exception:
        pass                                       # a failure to log never reaches the caller


def install(mcp) -> None:
    mgr = mcp._tool_manager
    inner = mgr.call_tool

    async def call_tool(name, arguments, *a, **kw):
        t0 = time.perf_counter()
        try:
            result = await inner(name, arguments, *a, **kw)
        except BaseException as e:
            record(name, arguments or {}, None, int((time.perf_counter() - t0) * 1000), raised=e)
            raise
        record(name, arguments or {}, result, int((time.perf_counter() - t0) * 1000))
        return result

    mgr.call_tool = call_tool
