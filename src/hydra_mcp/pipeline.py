"""pipeline.py — the rest of the loop, after records are saved: universe, Hs, stubs, the wiki.

    universe_build(root)                 the universe's identity and pages, from the last archive build
    publish(root, hs, collections, ...)  computed Hs -> published: their ids and page addresses hold
    stubs(root) / graduate(...)          names links hold that no record has; making one an entity
    wiki_serve(root, port, ...)          (re)start the wiki on a port and check it serves this build
    wiki_stop(port)                      stop the wiki this tool started on a port

`save` rebuilds the archive; the universe build makes the pages; the wiki loads the pages once,
when it starts, so it is restarted after every build that should show. `wiki_serve` does all
three: it builds the pages when they are older than their inputs, stops the server it started
before on that port, starts a new one, and compares the entries it serves with the pages built.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from hydra.records import scope as sc, entities, stubs as st
from hydra.schema import loader as schema
from hydra.archive import layout

from hydra.api.stubs import graduate  # noqa: F401  (moved: plans/imports.md I2c)
from hydra_mcp import core, agent, workflows
from hydra_mcp.core import IngestError
import html
import signal
from hydra.geo import query as gquery
from hydra.review import stubs as rstubs
from hydra.universe import layer, build as ubuild, review
import yaml

STATE = Path(tempfile.gettempdir()) / "hydra-mcp-wiki"       # which server this tool started on which port
ENTRIES = re.compile(r"([\d,]+) entries")


def _universe(root: Path):
    if not layer.is_universe(root):
        raise IngestError("this archive has no universe layer: `hydra-ctl universe init` adds one")


# ---- universe ------------------------------------------------------------------------

def universe_build(root: Path) -> dict:
    """Build the universe: which records are one entity, each one's H, and the pages."""
    _universe(root)
    r = ubuild.build(root)
    c = r["counts"]
    return {"pages": c["pages"], "in_scope": c.get("in_scope"), "hs": c["hs"], "by_state": c["by_state"], "by_flag": c["by_flag"],
            "same_name_pairs": c["proposed"], "blocked_merges": len(r.get("blocked") or []),
            "warnings": (r.get("warnings") or [])[:20], "more_warnings": max(0, len(r.get("warnings") or []) - 20),
            "members": {k: v for k, v in r["members"].items() if v.get("problem")} or "all loaded",
            "next": "wiki_readiness for what the pages lack; wiki_serve to show this build"}


def _built_pages(root: Path) -> list[dict]:
    return layer.read_parsed(root, "pages.jsonl", missing=[])


def publish(root: Path, hs: list[str] | None = None, collections: list[str] | None = None,
            confirm: bool = False) -> dict:
    """Preview (default) or publish computed Hs: `hs` by H, body or record id; or every computed
    H whose records all come from `collections` (an entity drawing on any other collection is
    left for its owner to decide)."""
    _universe(root)
    built = {r["body"]: r for r in layer.read_parsed(root, "canon.jsonl", missing=[])}
    if not built:
        raise IngestError("no universe build yet: universe_build first")
    if not hs and not collections:
        raise IngestError("give `hs` (Hs, bodies or record ids) or `collections`")
    chosen, left = set(), []
    for h in hs or []:
        try:
            chosen.add(review.resolve(built, h))
        except SystemExit as e:
            raise IngestError(str(e).removeprefix("hydra: ")) from None
    if collections:
        want = set(collections)
        for p in _built_pages(root):
            if p["state"] != "c":
                continue
            colls = {c["collection"] for c in p["citations"] if c.get("collection")
                     and not c["collection"].startswith(layout.SOURCE_COLLECTION)}
            if colls and colls <= want:
                chosen.add(p["body"])
            elif colls & want:
                left.append(f"{p['title']} (also from {', '.join(sorted(colls - want))})")
    todo = sorted(b for b in chosen if built.get(b, {}).get("state") == "c" and not built[b].get("redirect"))
    out = {"to_publish": len(todo), "examples": [built[b]["title"] for b in todo[:12]],
           "already_kept": len(chosen) - len(todo), **({"left_out": left[:12], "left_out_count": len(left)} if left else {})}
    if not confirm:
        return {**out, "next": "publishing is a promise these ids and page addresses hold; confirm with the "
                               "person, then call again with confirm=true"}
    n = review.publish(root, todo, by=core.AGENT)
    ubuild.build(root)
    workflows.hook_log(root, f"publish {n} H(s)")
    return {**out, "published": n, "snapshot": agent._snap(root, f"publish {n} Hs")}


# ---- reading a page ------------------------------------------------------------------

_WIKI: dict = {}


def _wiki(root: Path):
    """The wiki of the last universe build, loaded once per build."""
    if not ubuild.pages_current(root):
        ubuild.build(root)
    f = root / layout.UNIVERSE_PARSED / "pages.jsonl"
    key = (str(root), f.stat().st_mtime_ns)
    if key not in _WIKI:
        from hydra.wiki import site  # lazy: startup
        _WIKI.clear()
        _WIKI[key] = site.Wiki(root)
    return _WIKI[key]


def _text(fragment: str) -> str:
    t = re.sub(r"<sup>\s*<a href='#cite-(\d+)'>\[\d+\]</a>\s*</sup>", r"[\1]", fragment)
    t = re.sub(r"</(p|tr|li|div|caption|h\d)>|<br\s*/?>", "\n", t)
    t = re.sub(r"<(td|th)[^>]*>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lines = [re.sub(r"[ \t]+", " ", x).strip(" |") for x in t.splitlines()]
    return "\n".join(x for x in lines if x)


def _strip_divs(html: str, classes: tuple[str, ...]) -> str:
    cls_pat = "|".join(re.escape(c) for c in classes)
    rx = re.compile(rf"<div\b[^>]*\bclass=['\"]?(?:[^'\">\s]*\s+)*(?:{cls_pat})\b[^>]*>", re.I)
    tag_rx = re.compile(r"<(/?)div\b[^>]*>", re.I)
    while True:
        m = rx.search(html)
        if not m:
            break
        depth, pos = 1, m.end()
        while depth > 0:
            tm = tag_rx.search(html, pos)
            if not tm:
                pos = len(html)
                break
            depth += -1 if tm.group(1) else 1
            pos = tm.end()
        html = html[:m.start()] + html[pos:]
    return html


def _link_places(w, page: dict, rows: list[dict]) -> list[dict]:
    """Each infobox row with the entries its values name: `links` [{text, h, title}]. A value that resolved to an entry
    links to it; a place-valued field (birthPlace, address, location, registrationPort) holding the name of a Place
    entry links to that Place's page."""
    places: dict[str, str] = {}
    for b, q in w.pages.items():
        if q.get("schema") == "Place" and b in w.listed:
            for n in [q["title"], *(q.get("aliases") or ())]:
                places.setdefault(str(n).strip().casefold(), b)
    by_label = {}
    for box in page.get("infobox") or ():
        by_label.setdefault({"birthPlace": "Born", "birthDate": "Born"}.get(box["prop"], box.get("label")), []).append(box)
    out = []
    for r in rows:
        links, seen = [], set()
        for box in by_label.get(r["label"], ()):
            for v in box.get("values") or ():
                b = v.get("h") if v.get("h") in w.pages else None
                if not b and box["prop"] in gquery.PLACE_TEXT_PROPS:
                    b = places.get(str(v.get("value") or "").strip().casefold())
                if b and b not in seen and b in w.listed:
                    seen.add(b)
                    links.append({"text": str(v.get("value") or w.title(b)), "h": w.pages[b].get("h"), "title": w.title(b)})
        out.append({**r, **({"links": links} if links else {})})
    return out


def read_page(root: Path, entity: str) -> dict:
    """An entry's page as a reader sees it: title, id, scope, the infobox rows, the lead, each section's
    text in order, and its footnotes [n] resolved to the record, collection, source and quote behind them."""
    _universe(root)
    w = _wiki(root)
    body = core.resolve_entity(root, entity).body          # one page, strictly: a shared title is refused with its Hs
    if body not in w.pages:
        raise IngestError(f"'{entity}' has no page in the wiki's last build: universe_build, then call again")
    p = w.pages[body]
    from hydra.wiki import site  # lazy: startup
    page = w.render_page(site.Links(static=False), body)
    box = re.search(r"<table class=infobox>(.*?)</table>", page, re.S)
    rows = [{"label": _text(th), "value": _text(td)}
            for th, td in re.findall(r"<tr><th>(.*?)</th><td>(.*?)</td></tr>", box.group(1) if box else "", re.S)]
    rows = _link_places(w, p, rows)
    main = page[box.end():] if box else page
    end = re.search(r"<div class=['\"]?(?:navboxes|cats)\b|<footer\b", main)
    if end:
        main = main[:end.start()]
    main = re.sub(r"<script\b[^>]*>.*?</script>", "", main, flags=re.S | re.I)
    main = re.sub(r"<span class=info\b[^>]*>.*?</span>", "", main, flags=re.S)       # a heading's "i" tooltip is no heading text
    parts = re.split(r"<h2[^>]*>(.*?)</h2>", main)
    lead_html = _strip_divs(re.sub(r"<nav class=toc>.*?</nav>", "", parts[0], flags=re.S), ("widget", "tabbar"))
    lead = _text(lead_html)
    sections = [{"heading": _text(parts[i]), "text": _text(parts[i + 1])[:4000]} for i in range(1, len(parts) - 1, 2)
                if _text(parts[i]) not in ("References",)]
    notes = [{"n": c["n"], "record": c["record"], "collection": c.get("collection"),
              "source": [d["title"] for d in c.get("docs") or []] + list(c.get("urls") or []),
              **({"quote": c["quote"]} if c.get("quote") else {})} for c in p["citations"]]
    geo_info = None
    if (root / layout.GEO_PARSED / "located.jsonl").is_file():
        gm = gquery.load(root)
        if body in gm.rows:
            geo_info = gquery.locate(root, body)
    return {"title": p["title"], "h": p["h"], "schema": p["schema"], "scope": p.get("scope") or {"in": True},
            "infobox": rows, "lead": lead, "sections": sections, "footnotes": notes,
            **({"geo": geo_info} if geo_info else {})}


# ---- scope ---------------------------------------------------------------------------

def scope(root: Path, entity: str | None = None) -> dict:
    """What the archive is about (scope.yaml) as the last build computed it: how many entries are
    in scope, the context ones, and for `entity` (an H, key, record id or a title only one entry
    has; a shared title is refused with its Hs) whether it is in scope and why."""
    _universe(root)
    pages = _built_pages(root)
    conf = sc.load(root)
    ctx = sorted(f"{p['title']} ({p['schema']})" for p in pages if not (p.get("scope") or {}).get("in", True))
    out = {"file": conf["file"], "seeds": conf["seeds"], "include": conf["include"], "exclude": conf["exclude"],
           "in_scope": len(pages) - len(ctx), "context": len(ctx), "context_entries": ctx}
    if entity:
        try:
            hit = core.resolve_entity(root, entity)        # one entry, strictly: a shared title is refused with its Hs
        except IngestError as e:
            return workflows.failure_payload(e)
        p = entities.catalog(root).page(hit.body)
        rows = [{"title": p["title"], "h": p["h"], **(p.get("scope") or {"in": True})}]
        return {"entity": rows, "in_scope_here": all(r.get("in", True) for r in rows),
                "archive_scope": {"in_scope": out["in_scope"], "context": out["context"]}}
    return out


def set_scope(root: Path, include: list[str] | None = None, exclude: list[str] | None = None,
              seeds: list[str] | None = None, confirm: bool = False) -> dict:
    """Preview (default) or write the archive's scope.yaml: add to `include` / `exclude` (Hs, keys,
    record ids, titles, `collection:<name>`), or set the seed collections. The preview says which
    entries would come into scope and which would leave it."""
    _universe(root)
    pages = _built_pages(root)
    conf = sc.load(root)
    new = {**conf, "include": list(dict.fromkeys(conf["include"] + list(include or []))),
           "exclude": list(dict.fromkeys(conf["exclude"] + list(exclude or [])))}
    if seeds is not None:
        new["seeds"] = {**conf["seeds"], "collections": list(seeds)}
    schema.ensure()
    ends = {s: (d["edge"]["source"], d["edge"]["target"]) for s, d in schema.SCHEMA.items() if d.get("edge")}
    before, after = sc.compute(pages, conf, ends), sc.compute(pages, new, ends)
    every = {p["body"]: p["title"] for p in pages}
    was = set(every) if before is None else set(before)
    now = set(every) if after is None else set(after)
    names, _ = sc._resolver(pages)
    unknown = [x for x in (include or []) + (exclude or []) if not names(x)]
    out = {"comes_into_scope": sorted(every[b] for b in now - was), "leaves_scope": sorted(every[b] for b in was - now),
           "in_scope_after": len(now), **({"names_nothing": unknown} if unknown else {})}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    f = root / layout.SCOPE
    doc = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}
    doc["seeds"] = new["seeds"]
    if new["include"]:
        doc["include"] = new["include"]
    if new["exclude"]:
        doc["exclude"] = new["exclude"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# .hydra/rules/scope.yaml — what this archive is about (see hydra's template for every key)\n"
                 + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    ubuild.build(root)
    workflows.hook_log(root, f"set_scope {scope}")
    return {**out, "written": str(f), "snapshot": agent._snap(root, "scope")}


# ---- stubs ---------------------------------------------------------------------------

def stubs(root: Path) -> dict:
    """Names that links hold but no record has (red links), and those already graduated."""
    return {"stubs": st.found(root), "graduated": rstubs.graduated(root),
            "next": "write a record for a stub (then its links find it), or graduate it into a bare entity"}



# ---- the wiki ------------------------------------------------------------------------

def _get(port: int, path: str = "/", timeout: float = 2.0) -> str | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)


def _listener(port: int) -> int | None:
    """The pid listening on the port, when the system says (netstat on Windows, lsof elsewhere)."""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                f = line.split()
                if len(f) >= 5 and f[1].endswith(f":{port}") and f[3] == "LISTENING":
                    return int(f[4])
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
            return int(out.split()[0]) if out.split() else None
    except (OSError, ValueError):
        return None
    return None


def _state(port: int) -> Path:
    return STATE / f"{port}.json"


def wiki_stop(port: int = 8080) -> dict:
    """Stop the wiki this tool started on `port`. A server it did not start is left alone."""
    f = _state(port)
    if not f.is_file():
        return {"stopped": False, "why": f"this tool started no wiki on port {port}"}
    st = json.loads(f.read_text(encoding="utf-8"))
    was = _alive(st["pid"])
    if was:
        _kill(st["pid"])
        for _ in range(50):
            if not _alive(st["pid"]):
                break
            time.sleep(0.1)
    f.unlink()
    return {"stopped": was, "pid": st["pid"], "archive": st.get("root")}


def wiki_serve(root: Path, port: int = 8080, theme: str | None = None, replace_other: bool = False,
               wait: float = 60.0) -> dict:
    """Show the archive's current build as a wiki on `port`: build the pages if they are stale,
    stop the server this tool started there, start a new one, and check that it serves as many
    entries as the build made pages. `replace_other` also stops a server this tool did not start
    on that port (ask the person first: it may be theirs)."""
    _universe(root)
    rebuilt = False
    if not ubuild.pages_current(root):
        ubuild.build(root)
        rebuilt = True
    built = _built_pages(root)                       # the wiki lists (and its footer counts) the pages in scope
    expected = sum(1 for p in built if (p.get("scope") or {}).get("in", True))
    sf = _state(port)
    if sf.is_file() and not replace_other:             # a wiki this tool started for another archive may be the person's
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except ValueError:
            st = {}
        if st.get("pid") and _alive(st["pid"]) and Path(st.get("root") or "").resolve() != Path(root).resolve():
            raise IngestError(f"a wiki of another archive ({st.get('root')}) is running on port {port}: pick another "
                              "port, or, with the person's agreement, call again with replace_other=true")
    stopped = wiki_stop(port)
    if _get(port) is not None or _listener(port):
        pid = _listener(port)
        if not replace_other:
            raise IngestError(f"something this tool did not start answers on port {port}"
                              + (f" (pid {pid})" if pid else "") + ": pick another port, or, with the person's "
                              "agreement, call again with replace_other=true")
        if pid:
            _kill(pid)
            for _ in range(50):
                if _get(port) is None and not _listener(port):
                    break
                time.sleep(0.1)
    STATE.mkdir(parents=True, exist_ok=True)
    log = STATE / f"{port}.log"
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": log.open("w", encoding="utf-8"), "stderr": subprocess.STDOUT,
                "env": {**os.environ, "PYTHONIOENCODING": "utf-8"}}
    if os.name == "nt":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "hydra", "wiki", str(root), "serve", "--port", str(port),
                             *(["--theme", theme] if theme else [])], **kw)      # no theme: hydra's default
    _state(port).write_text(json.dumps({"pid": proc.pid, "root": str(root), "port": port,
                                        "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}),
                            encoding="utf-8")
    home, deadline = None, time.time() + wait
    while time.time() < deadline and proc.poll() is None:
        home = _get(port)
        if home:
            break
        time.sleep(0.5)
    if not home:
        tail = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.is_file() else ""
        raise IngestError(f"the wiki did not answer on port {port} within {wait:.0f}s; its log ends:\n{tail}")
    m = ENTRIES.search(home)
    entries = int(m.group(1).replace(",", "")) if m else None
    return {"url": f"http://127.0.0.1:{port}/", "pid": proc.pid, "entries": entries, "pages_in_scope": expected,
            "pages_built": len(built),
            "ok": entries == expected, "rebuilt_pages": rebuilt, "stopped_previous": stopped.get("stopped", False),
            "log": str(log),
            **({} if entries == expected else {"why": "the server shows a different number of entries than the "
                                                      "build made pages: another server may be answering"})}
