"""data.py: the archive, collection, graph and file tools (alpha plan, stream D).

    archive_settings(set?)                          the Archive page's text settings: read, or preview and write
    collection_create / _rename / _merge            shaping collections (hydra.collectionops); record ids and Hs never change
    move_records / set_collection_group
    neighbors / paths                               the relationship graph the Graph and Radial views draw (hydra.graphquery)
    tags(entity)                                    each tag's fit, reasons and decision (hydra.archetypes)
    export / pack                                   the archive as FtM, CSV, GraphML or one .hydra file, inside a named folder

Every write previews unless `confirm=true`, publishes the Hs involved before records move, takes one history step by
`agent:hydra-mcp`, and logs to the checked-out task. A refusal comes back as `{error, why, do}`, never a traceback.
"""
from __future__ import annotations

from pathlib import Path

from hydra import collectionops, graphquery
from hydra_mcp import core, workflows
from hydra_mcp.core import AGENT

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
    from hydra.wiki import archiveconf as ac
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
    from hydra import history
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
    from hydra.cli import export as ex
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
    from hydra.cli import pack as pk
    target.parent.mkdir(parents=True, exist_ok=True)
    got = _guard(lambda: pk.pack(root, target, with_history=history, force=replace))
    if isinstance(got, dict):
        return got
    f, n, links = got
    workflows.hook_log(root, f"pack -> {f.name}")
    return {**info, "written": True, "files": n, "bytes": f.stat().st_size, **({"links_skipped": links} if links else {})}


# ---- registering ---------------------------------------------------------------------------

def register(mcp, run) -> None:
    def root_of(archive):
        return core.open_archive(archive)

    @mcp.tool(name="archive_settings")
    def archive_settings_tool(set: dict | None = None, confirm: bool = False, archive: str | None = None) -> dict:
        """The archive's text settings, as the Archive page holds them: name, title, sub, about, description, theme, view, rail_shape and title_style. With no `set` it returns them. With `set` ({"about": "..."}: only what changes) it previews each change as from/to; call again with confirm=true once the person agrees. A name or title change rebuilds the wiki. One history step. More: guide("tools", "archive_settings")"""
        return run(lambda: archive_settings(root_of(archive), set, confirm))

    @mcp.tool(name="collection_create")
    def collection_create_tool(name: str, title: str | None = None, confirm: bool = False, archive: str | None = None) -> dict:
        """Make a new, empty collection `name` (letters, digits, - and _), with an optional display `title`. Its id
        prefix is pinned with it, so its record ids never change later. Previews unless confirm=true; one history step.
        Add records with `save` or `move_records`. Errors come back as {error, why, do}."""
        return run(lambda: collection_create(root_of(archive), name, title, confirm))

    @mcp.tool(name="collection_rename")
    def collection_rename_tool(old: str, new: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Rename collection `old` to `new` without changing a record: the file, its entry in hydra.yaml (title,
        prefix, view handles), the groups that list it and open tasks on it all follow. Record ids and H bodies stay,
        because the id prefix is pinned to the collection. The Hs of its records are published first. The preview
        names what follows (records, prefix, groups, tasks); call again with confirm=true once the person agrees.
        Rebuilds; one history step. Errors come back as {error, why, do}."""
        return run(lambda: collection_rename(root_of(archive), old, new, confirm))

    @mcp.tool(name="collection_delete")
    def collection_delete_tool(name: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Remove an empty collection made by mistake: its file, its entry in hydra.yaml (title, prefix, view handles)
        and its place in groups (a group left empty goes too). Refused while it holds a record, keeps a source, or an
        open task names it. Previews unless confirm=true; one history step. Errors come back as {error, why, do}."""
        return run(lambda: collection_delete(root_of(archive), name, confirm))

    @mcp.tool(name="collection_merge")
    def collection_merge_tool(into: str, from_: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Join collection `from_` into `into` and remove `from_`: every record is kept with its id and H. Refused when
        the two collections have different id prefixes (the ids would change) or a record id clashes with different
        content. `from_`'s view handles are dropped (the preview lists them); groups and tasks that named it now name
        `into`. A merge is always the person's decision: confirm only after they agree, even on an authorized task.
        Previews unless confirm=true; rebuilds; one history step. Errors come back as {error, why, do}."""
        return run(lambda: collection_merge(root_of(archive), into, from_, confirm))

    @mcp.tool(name="move_records")
    def move_records_tool(ids: list[str], to: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Move records (by record id, as `find_entities` or `get_records` give it) into collection `to`, keeping
        each record whole, with its id and H. Refused, with nothing moved, when a record is unknown, sits in several
        collections, has a different id prefix from `to` (the id would change) or its id already exists there.
        Previews unless confirm=true; rebuilds; one history step. Errors come back as {error, why, do}."""
        return run(lambda: move_records(root_of(archive), ids, to, confirm))

    @mcp.tool(name="set_collection_group")
    def set_collection_group_tool(group: str, collections: list[str], title: str | None = None, confirm: bool = False,
                                  archive: str | None = None) -> dict:
        """Make or change a collection group (hydra.yaml `collection_groups.<group>`): a named set of collections that a
        view handle can open together. `collections` must all exist; an empty list removes the group. `title` is its
        display name (kept when omitted). Previews unless confirm=true; one history step. Errors come back as {error, why, do}."""
        return run(lambda: set_collection_group(root_of(archive), group, collections, title, confirm))

    @mcp.tool()
    def neighbors(entity: str, depth: int = 1, edges: list[str] | None = None, as_of: str | None = None,
                  archive: str | None = None) -> dict:
        """The entries linked to `entity` (an H, key, record id or title) within `depth` links (1 to 4), from the same
        graph the Graph and Radial views draw. Direction is ignored in walking but every edge keeps it: {from, to,
        type, label, start, end, approx, record (the relationship record's id), member}. `edges`: only these
        relationship types (Membership, Ownership, Family...). `as_of` (a year, month or day): only links in force
        then (a link without dates always is). Read-only; at most 200 entries (`truncated` says so). Errors come
        back as {error, why, do}."""
        return run(lambda: _guard(lambda: graphquery.neighbors(root_of(archive), entity, depth, edges, as_of)))

    @mcp.tool()
    def paths(a: str, b: str, max_hops: int = 4, edges: list[str] | None = None, archive: str | None = None) -> dict:
        """How two entries are connected: the chains of links from `a` to `b` of at most `max_hops` links (1 to 6),
        shortest first, up to 20, each with its entries and, per step, every link between that pair (type, label,
        dates, record id). `edges`: only these relationship types. Read-only. Says so when nothing joins them.
        Errors come back as {error, why, do}."""
        return run(lambda: _guard(lambda: graphquery.paths(root_of(archive), a, b, max_hops, edges)))

    @mcp.tool()
    def tags(entity: str, archive: str | None = None) -> dict:
        """Each tag (archetype) an entry scores against, as Review and Labelling do: `score` out of 100 against the tag's
        `fit` line, whether it `fits`, the person's `decision` (confirmed, rejected or undecided), what the entry
        `shows` and what it `lacks`. Read-only; set decisions with `label` (tag:<id>, tag:no@<id>, tag:clear@<id>).
        Errors come back as {error, why, do}."""
        return run(lambda: _guard(lambda: graphquery.tags(root_of(archive), entity)))

    @mcp.tool(name="export")
    def export_tool(format: str, out: str, folder: str, ids: str = "record", replace: bool = False, confirm: bool = False,
                    archive: str | None = None) -> dict:
        """Write the archive's compiled entities to a file: `format` ftm (standard FollowTheMoney lines), hydra-ftm
        (links as names), csv (a folder with nodes.csv and edges.csv) or graphml. `folder` is the folder the person named
        for the output and `out` a path inside it; anything resolving outside it is refused, and an existing file is
        kept unless replace=true. `ids`: record (default) or h (canonical ids). Reads the archive, changes nothing in
        it. Previews the target unless confirm=true. Errors come back as {error, why, do}."""
        return run(lambda: export_(root_of(archive), format, out, folder, ids, replace, confirm))

    @mcp.tool(name="pack")
    def pack_tool(out: str, folder: str, history: bool = True, replace: bool = False, confirm: bool = False,
                  archive: str | None = None) -> dict:
        """Pack the archive into one portable .hydra file (a zip with its build and, unless history=false, its history).
        `folder` is the folder the person named for the output and `out` a file name inside it (.hydra is added);
        anything resolving outside the folder is refused, and an existing file is kept unless replace=true. Changes
        nothing in the archive. Previews the target unless confirm=true. Errors come back as {error, why, do}."""
        return run(lambda: pack_(root_of(archive), out, folder, history, replace, confirm))
