"""app.py — the one FastMCP server, `tool` and `_run`: what every tool module (`tools/<set>.py`) registers with.

`server.py` imports the tool modules, installs the write lock, the call log and the toolsets on `mcp`, and runs it.
`tool` is `mcp.tool` that also keeps the function, so `hydra_mcp.server.<name>` still reaches every tool (tests, the
page flow and run scripts call `server.save(...)`)."""
from __future__ import annotations

import contextlib
import sys
from typing import Callable

from mcp.server.fastmcp import FastMCP

from hydra_mcp import core

mcp = FastMCP("hydra", instructions=(
    "Hydra turns sources into a reviewed archive and its wiki. Start every session with `guide(\"start\")` and "
    "follow it: it says how to pick or check out a task (`tasks`, `task_checkout`), which guides to load, and "
    "how to tick each step (`task_step`). Load only the guides your task lists. The rules that never bend: "
    "quote only text you read through `read_source` or `read_file`; record only what a kept source states; a "
    "name is never proof that two records are one entity; every tool with `confirm` previews first, and you "
    "confirm only after the person agrees (or the task's `authorized` list names that tool); work only in the "
    "archive the person gave you, passed as `archive` on every call. If no archive is given, ask, or offer "
    "`create_archive`."))

FUNCTIONS: dict[str, Callable] = {}             # python name -> each tool and resource function, for server's names


def _keep(fn: Callable) -> Callable:
    if FUNCTIONS.get(fn.__name__, fn) is not fn:
        raise ValueError(f"two tool functions are named {fn.__name__}: {FUNCTIONS[fn.__name__].__module__} and "
                         f"{fn.__module__}")
    FUNCTIONS[fn.__name__] = fn
    return fn


def tool(*args, **kw):
    """`@tool()` / `@tool(name="label")`: `mcp.tool`, keeping the function for `hydra_mcp.server`."""
    register = mcp.tool(*args, **kw)
    return lambda fn: register(_keep(fn))


def resource(*args, **kw):
    """`@resource("hydra://...")`: `mcp.resource`, keeping the function for `hydra_mcp.server`."""
    register = mcp.resource(*args, **kw)
    return lambda fn: register(_keep(fn))


def _run(fn, *args, **kw):
    try:
        with contextlib.redirect_stdout(sys.stderr):    # stdout carries the MCP messages: a stray print would break them
            return fn(*args, **kw)
    except core.IngestError as e:
        err = ValueError(str(e))
        err.kind = e.kind                               # failure_payload maps the kind to {error, why, do}
        raise err from None
    except SystemExit as e:                             # a hydra command that refused: an Exception the tool layer reports
        err = ValueError(str(e.code).removeprefix("hydra: "))
        err.kind = "SystemExit"
        raise err from None
