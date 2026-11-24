"""stale.py — is the code this server loaded still the code on disk?

The server process imports hydra (and hydra_mcp) once, at start. When their files change afterwards, the loaded
modules and the files disagree and a write fails deep inside a build. This module notes the code id when it loads
and compares it with the files now, at most once every few seconds: the comparison stats the code files (cheap)
and hashes them only when a file's size or time moved."""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from hydra import __version__
from hydra.build import freshness

INTERVAL = 3.0                                    # seconds between two looks at the disk

_cache: list = []                                 # [stamps, id] of the last look
_last = [0.0, None]                               # when the last check ran, and what it found (a message or None)


def _files() -> list[Path]:
    mine = sorted(p for p in Path(__file__).resolve().parent.glob("**/*.py") if "__pycache__" not in p.parts)
    return [*freshness._code_files(), *mine]


WORKERS = 16                                      # files are read in parallel: one by one is slow on a mounted drive


def _stat(f) -> tuple:
    try:
        st = os.stat(f)
        return (str(f), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(f), None, None)


def _read(f) -> bytes | None:
    try:
        return f.read_bytes()
    except OSError:
        return None


def _stamps(files) -> list:
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(_stat, files))


def _hash(files) -> str:
    h = hashlib.blake2b(digest_size=12)
    h.update(str(__version__).encode() + b"\0")
    with ThreadPoolExecutor(WORKERS) as pool:
        for f, data in zip(files, pool.map(_read, files)):          # map keeps the order, so the id is stable
            if data is not None:
                h.update(str(f.name).encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def current_id() -> str:
    """The id of the hydra and hydra_mcp code on disk now; the content is hashed again only after a file moved."""
    files = _files()
    stamps = _stamps(files)
    if not _cache or _cache[0] != stamps:
        _cache[:] = [stamps, _hash(files)]
    return _cache[1]


def changed_at() -> float:
    """The latest modification time among the code files."""
    times = [s[2] for s in (_cache[0] if _cache else []) if s[2]]
    return max(times) / 1e9 if times else time.time()


LOADED = current_id()                             # the code this process started with
LOADED_AT = time.time()


def message() -> str | None:
    """None while the code on disk is the code this server loaded; else the sentence that says it is not."""
    now = time.monotonic()
    if _last[0] and now - _last[0] < INTERVAL:
        return _last[1]
    try:
        stale = current_id() != LOADED
    except Exception:                             # never let this check fail a call
        stale = False
    _last[0] = now
    _last[1] = ("the hydra code changed after this server started (" + time.strftime("%H:%M", time.localtime(changed_at()))
                + ")") if stale else None
    return _last[1]


def refusal(msg: str) -> dict:
    return {"error": "stale server", "why": msg,
            "do": "reconnect the hydra MCP server (/mcp in Claude Code), then call again; nothing was changed"}
