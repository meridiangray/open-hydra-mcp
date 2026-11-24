"""data.py: the archive, collection, graph and file tools (alpha plan, stream D).

    archive_settings(set?)                          the Archive page's text settings: read, or preview and write
    collection_create / _rename / _merge            shaping collections (hydra.records.collectionops); record ids and Hs never change
    move_records / set_collection_group
    neighbors / paths                               the relationship graph the Graph and Radial views draw (hydra.structure.graphquery)
    tags(entity)                                    each tag's fit, reasons and decision (hydra.shape.archetypes)
    export / pack                                   the archive as FtM, CSV, GraphML or one .hydra file, inside a named folder

Every write previews unless `confirm=true`, publishes the Hs involved before records move, takes one history step by
`agent:hydra-mcp`, and logs to the checked-out task. A refusal comes back as `{error, why, do}`, never a traceback.
The MCP tools that call these are in `tools/` (core, enrich, shape and admin, by tool set).
"""
from __future__ import annotations

from pathlib import Path

from hydra.structure import graphquery
from hydra.records import collectionops
from hydra.archive import history
from hydra_mcp import workflows
from hydra_mcp.core import AGENT
from hydra.cli import export as ex, pack as pk
from hydra.wiki.pages import archiveconf as ac

NEXT = "confirm with the person, then call again with confirm=true"
SETTINGS = ("name", "title", "sub", "about", "description", "theme", "view", "rail_shape", "title_style")
FORMATS = ("ftm", "hydra-ftm", "csv", "graphml")


def _refuse(error: str, why: str, do: str) -> dict:
    return {"error": error, "why": why, "do": do}


def _guard(fn):
    """Run `fn`; a domain refusal becomes the `{error, why, do}` dict."""
    try:
        return fn()
    except (collectionops.OpError, graphquery.GraphError) as e:
        return e.as_dict()
    except SystemExit as e:
        return _refuse("refused", str(e.code).removeprefix("hydra: "), "fix what it says and call again")


# ---- archive settings ----------------------------------------------------------------------

def archive_settings(root: Path, set: dict | None = None, confirm: bool = False) -> dict:
    cur = ac.read(root)
    now = {k: cur.get(k, "") for k in SETTINGS}
    if not set:
        return {"settings": now, "views": [v for v, _ in ac.VIEWS], "rail_shapes": ["square", "circle"],
                "note": "the rail image and the front-page card are set on the Archive page"}
    if not isinstance(set, dict):
        return _refuse("bad settings", "`set` is a mapping of setting to its new value", f"use keys from: {', '.join(SETTINGS)}")
    unknown = sorted(k for k in set if k not in SETTINGS)
    if unknown:
        return _refuse("unknown setting", f"{', '.join(unknown)}", f"use keys from: {', '.join(SETTINGS)} "
                       "(the rail image and the card stay on the Archive page)")
    new = {k: ("" if v is None else v if k == "title_style" else str(v)) for k, v in set.items()}
    if isinstance(new.get("title_style"), dict):          # keys not given keep what is set now
        new["title_style"] = {**ac.title_style(now["title_style"]), **new["title_style"]}
    bad = ac.check(root, new)
    if bad:
        return _refuse("value refused", "; ".join(bad), "correct the value and call again")
    if "title_style" in new:
        new["title_style"] = ac.title_diff(new["title_style"])          # only what differs from the defaults
    changes = {k: {"from": now[k], "to": v} for k, v in new.items()
               if (v != now[k] if k == "title_style" else v.strip() != str(now[k]).strip())}
    out = {"changes": changes, "settings": now}
    if not changes:
        return {**out, "written": 0, "note": "nothing differs from what is set"}
    if not confirm:
        return {**out, "written": 0, "next": NEXT}
    again = ac.save(root, {k: new[k] for k in changes}, who=AGENT)
    if again:
        ac.rebuild(root, places_unchanged=True)
    workflows.hook_log(root, f"archive_settings: {', '.join(changes)}")
    log = history.log(root, None, 1)
    return {**out, "written": len(changes), "settings": {k: ac.read(root).get(k, "") for k in SETTINGS},
            "snapshot": log[0]["id"] if log else None}


# ---- collections ---------------------------------------------------------------------------

def _op(root: Path, fn, *a, confirm: bool, label: str) -> dict:
    out = _guard(lambda: fn(root, *a, confirm=confirm, who=AGENT))
    if confirm and out.get("changed"):
        workflows.hook_log(root, label)
    return out


def collection_create(root, name: str, title: str | None = None, confirm: bool = False) -> dict:
    return _op(root, collectionops.create, name, title, confirm=confirm, label=f"collection_create {name}")


def collection_rename(root, old: str, new: str, confirm: bool = False) -> dict:
    return _op(root, collectionops.rename, old, new, confirm=confirm, label=f"collection_rename {old} -> {new}")


def collection_delete(root, name: str, confirm: bool = False) -> dict:
    return _op(root, collectionops.delete, name, confirm=confirm, label=f"collection_delete {name}")


def collection_merge(root, into: str, from_: str, confirm: bool = False) -> dict:
    return _op(root, collectionops.merge, into, from_, confirm=confirm, label=f"collection_merge {from_} into {into}")


def move_records(root, ids: list[str], to: str, confirm: bool = False) -> dict:
    return _op(root, collectionops.move, ids, to, confirm=confirm, label=f"move_records -> {to}")


def set_collection_group(root, group: str, collections: list[str], title: str | None = None, confirm: bool = False) -> dict:
    return _op(root, collectionops.set_group, group, collections, title, confirm=confirm, label=f"set_collection_group {group}")


# ---- files out -----------------------------------------------------------------------------

def _inside(folder: str | None, out: str, suffix: str | None = None) -> Path | dict:
    """`out` resolved inside `folder` (the folder the person named), else the refusal."""
    if not folder or not str(folder).strip():
        return _refuse("no folder named", "writing a file needs the folder the person chose for it",
                       "ask the person where the file may go, and pass it as `folder`")
    base = Path(folder).expanduser()
    if not base.is_dir():
        return _refuse("folder not found", f"{base} is not a folder", "ask the person for an existing folder")
    base = base.resolve()
    if not str(out or "").strip():
        return _refuse("no file named", "`out` is empty", "give a file name (or path) inside the folder")
    target = Path(out).expanduser()
    target = (target if target.is_absolute() else base / target).resolve()
    if base != target and base not in target.parents:
        return _refuse("outside the folder", f"{target} is not inside {base}", "choose a path inside the folder the person named")
    if target == base:
        return _refuse("no file named", "`out` is the folder itself", "give a file name inside it")
    if suffix and target.suffix != suffix:
        target = target.with_name(target.name + suffix)
    return target


def export_(root: Path, format: str, out: str, folder: str | None = None, ids: str = "record", replace: bool = False,
            confirm: bool = False) -> dict:
    if format not in FORMATS:
        return _refuse("unknown format", f"{format!r}", f"use one of: {', '.join(FORMATS)}")
    if ids not in ("record", "h"):
        return _refuse("bad ids", f"{ids!r}", "use 'record' or 'h'")
    target = _inside(folder, out)
    if isinstance(target, dict):
        return target
    if target.exists() and not replace:
        return _refuse("file exists", f"{target} is already there", "pick another name, or pass replace=true with the person's agreement")
    if target.exists() and target.is_dir() != (format == "csv"):
        return _refuse("wrong kind of path", f"{target} exists as a {'folder' if target.is_dir() else 'file'}", "pick another name")
    info = {"format": format, "out": str(target), "kind": "folder (nodes.csv, edges.csv)" if format == "csv" else "file", "ids": ids}
    if not confirm:
        return {**info, "written": False, "next": NEXT}
    if not (root / "hydra.yaml").is_file():
        return _refuse("not an archive", str(root), "pass an archive")
    target.parent.mkdir(parents=True, exist_ok=True)
    report = _guard(lambda: ex.export(root, format, target, ids=ids))
    if isinstance(report, dict) and report.get("error"):
        return report
    workflows.hook_log(root, f"export {format} -> {target.name}")
    return {**info, "written": True, "report": {str(k): v for k, v in report.items()}}


def pack_(root: Path, out: str, folder: str | None = None, history: bool = True, replace: bool = False,
          confirm: bool = False) -> dict:
    target = _inside(folder, out, ".hydra")
    if isinstance(target, dict):
        return target
    if target.exists() and not replace:
        return _refuse("file exists", f"{target} is already there", "pick another name, or pass replace=true with the person's agreement")
    info = {"out": str(target), "with_history": bool(history)}
    if not confirm:
        return {**info, "written": False, "next": NEXT}
    target.parent.mkdir(parents=True, exist_ok=True)
    got = _guard(lambda: pk.pack(root, target, with_history=history, force=replace))
    if isinstance(got, dict):
        return got
    f, n, links = got
    workflows.hook_log(root, f"pack -> {f.name}")
    return {**info, "written": True, "files": n, "bytes": f.stat().st_size, **({"links_skipped": links} if links else {})}


# ---- the graph, read-only (the tools `neighbors`, `paths` and `tags`) -----------------------------------------

def neighbors(root: Path, entity: str, depth: int = 1, edges: list[str] | None = None, as_of: str | None = None) -> dict:
    return _guard(lambda: graphquery.neighbors(root, entity, depth, edges, as_of))


def paths(root: Path, a: str, b: str, max_hops: int = 4, edges: list[str] | None = None) -> dict:
    return _guard(lambda: graphquery.paths(root, a, b, max_hops, edges))


def tags(root: Path, entity: str) -> dict:
    return _guard(lambda: graphquery.tags(root, entity))
