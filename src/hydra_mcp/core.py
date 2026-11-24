"""The ingestion logic behind the MCP tools, as plain functions.

The model connected to the server reads the raw text and proposes records; these
functions tell it what the archive accepts, check what it proposes, and only then
write it. Nothing here guesses facts: every check reports, and the one write
(`ingest`) refuses a batch with errors.

Checking and saving moved to hydra (plans/imports.md I2b): `check_records`, `ingest`, `normalize`, `storable`,
`IngestError` and their helpers are `hydra.api.records` (and the kept sources' helpers `hydra.api.sources`); this
module re-exports every name, so the tools and their callers are unchanged. What stays here is the MCP side: which
archive a call works in (`open_archive`), the read tools (`get_records`, `properties`...), images, `read_file`.
What a save writes, and how to undo it: the docstring of hydra.api.records.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from hydra.build import run as build  # noqa: F401  (build: tests patch core.build.build_archive)
from hydra.schema import loader as schema
from hydra.archive import history, layout, resources  # noqa: F401
from hydra.records import entities
from hydra.schema import props as hprops
from hydra.api import sources as _sources
from hydra.api.errors import IngestError
from hydra.api.records import (FACT_PROPS, IMAGE_FIELDS, NAME_PROPS, SLUG, VALID_NAME, _FILE_CACHE,  # noqa: F401
                               _batch_source_text, _built, _cached, _canon_by_member, _canon_row, _canon_rows,
                               _declared, _existing_names, _facts, _facts_of_batch, _h_of, _ids_in, _keyed,
                               _publish_pinned, _slug, _universe_layer, _values, _yaml, basis_errors, basis_of,
                               check_records, ingest, normalize, storable)
from hydra.api.sources import AGENT, SOURCE_FILES, resolve_file  # noqa: F401
from hydra.identity import types
from hydra.shape import rules
from hydra.api.images import ANSI, _read_credit, credit_sidecar, link_image  # noqa: F401  (moved: plans/imports.md I2c)

from hydra_mcp import mint  # noqa: F401
from hydra.cli import init
from hydra.records.ingest import default_prefix, valid_prefix
from hydra.review import todo
from hydra.universe import layer
from hydra.wikidata import catalog
from hydra_mcp import workflows, files, profile as prof

_load_records = _sources.load_records
_source_entries = _sources.source_entries
_source_by_hash = _sources.source_by_hash
_existing_source = _sources.existing_source
_new_source = _sources.new_source

ANSI = re.compile(r"\x1b\[[0-9;]*m")
READ_LIMIT = 30_000                               # characters of a file's text per read_file call: 60k overflowed
                                                  # Claude Code's 25k-token tool-output cap (2026-11-21 Pollard run)


def page(rows: list, offset: int = 0, limit: int = 100) -> tuple[list, dict]:
    """One page of a long list: the rows from `offset`, at most `limit` (1 to 500), and the paging fields to merge
    into the answer (`total`, `offset`, `limit`, and `next_offset` when more follow)."""
    offset, limit = max(0, int(offset or 0)), max(1, min(int(limit or 100), 500))
    out = rows[offset:offset + limit]
    more = offset + limit < len(rows)
    return out, {"total": len(rows), "offset": offset, "limit": limit, **({"next_offset": offset + limit} if more else {})}


class NoArchive(IngestError):
    """No archive was named, none is active, and the server's folder is not one."""


NO_ARCHIVE = ("No hydra archive is selected. Ask the person which archive to use and pass its folder as "
              "`archive` to every tool, or offer `create_archive` to start a new one (it previews first and "
              "writes only with confirm=true once they agree). Don't ingest until there is an archive.")
DEFAULTS_NOTE = ("No archive is selected, so this uses hydra's defaults (its schema, direction.yaml and default "
                 "positions). Links and duplicates are not checked against any archive. " + NO_ARCHIVE)


# ---- the archive -----------------------------------------------------------------


def open_archive(path: str | None = None) -> Path:
    """The archive to work on: `path`, else $HYDRA_ARCHIVE, else the active archive
    or the current folder (as `hydra-ctl` decides). Raises NoArchive when none is
    selected, and IngestError when the one named isn't an archive."""
    named = path or os.environ.get("HYDRA_ARCHIVE") or None
    try:
        root = build.open_archive(named)
    except SystemExit as e:
        msg = str(e.code).removeprefix("hydra: ")
        if named is None and msg.startswith("no archive given"):
            raise NoArchive(NO_ARCHIVE) from None
        raise IngestError(f"{msg}. Ask the person for the folder of an existing archive, or offer "
                          "`create_archive` to start a new one.") from None
    if resources.is_pack(root):
        raise IngestError(f"{root} is a packed archive; open it with `hydra-ctl init {root}` first")
    if Path(root).resolve() == resources.TEMPLATE.resolve():
        raise IngestError("that folder is hydra's own template, not an archive; never write to it")
    schema.load(root=root)
    return Path(root).resolve()


def archive_or_defaults(path: str | None = None) -> tuple[Path, bool]:
    """For tools that only read: the archive and True, or, when none is selected,
    hydra's shipped template (its defaults, no records) and False. An archive that
    is named but wrong is still an error: a fallback would hide the mistake."""
    try:
        return open_archive(path), True
    except NoArchive:
        schema.load(root=resources.TEMPLATE)
        return resources.TEMPLATE, False


def create_archive(path: str, name: str | None = None, prefix: str | None = None, confirm: bool = False) -> dict:
    """Preview (default) or create a new, empty archive at `path`, the way
    `hydra-ctl init` does. `prefix` is the id prefix every collection uses
    (default: one made from the name; "none" leaves each collection its own)."""
    p = Path(str(path or "").strip()).expanduser()
    if not str(path or "").strip() or not p.is_absolute():
        raise IngestError("give the full path of the new archive's folder (ask the person where it should go)")
    if p.suffix == ".hydra":
        raise IngestError(f"{p} is a packed archive's name; open a pack with `hydra-ctl init {p}`")
    if resources.is_archive(p):
        raise IngestError(f"{p} is already a hydra archive: pass it as `archive` instead of creating one")
    if p.exists() and not p.is_dir():
        raise IngestError(f"{p} is a file, not a folder")
    if p.is_dir() and any(p.iterdir()):
        raise IngestError(f"{p} exists and is not empty; choose a new or empty folder")
    name = str(name or "").strip() or p.name
    prefix = str(prefix or "").strip()
    if prefix != "none" and prefix and not valid_prefix(prefix):
        raise IngestError(f"'{prefix}' is not a usable prefix: lowercase letters, digits, '.', '_' and '-'")
    prefix = "" if prefix == "none" else prefix or default_prefix(name)
    out = {"created": False, "path": str(p), "folder": "empty" if p.is_dir() else "new", "name": name,
           "prefix": prefix or None,
           "ids": f"records get ids like {prefix}:per-w3v2f7z7pe" if prefix else
                  "each collection gets its own prefix, made from its name"}
    if not confirm:
        return {**out, "next": "confirm the folder, name and prefix with the person, then call again with confirm=true"}
    init.create(p, name, prefix)
    root = open_archive(str(p))
    return {**out, "created": True, "archive": str(root), "overview": overview(root),
            "next": f'pass archive="{root}" to every tool from now on (the person can make it the default by '
                    f'setting HYDRA_ARCHIVE={root} in the MCP server\'s configuration), then ingest the text'}


def _open_counts(root: Path) -> dict[str, int]:
    if not _built(root):
        return {}
    return {k: len(v) for k, v in todo.collect(root).items()}


def overview(root: Path) -> dict:
    """The archive in brief: its name, collections, last build and open questions."""
    meta = _yaml(root / layout.MANIFEST)
    files, entries = resources.record_files(root)
    summary = _yaml(root / layout.BUILD_YAML)
    return {
        "archive": str(root), "name": meta.get("name") or root.name,
        "collections": [f.stem for f in files], "source_entries": [f.stem for f in entries],
        "built": summary.get("built"), "records": summary.get("records"),
        "open_questions": _open_counts(root),
        "hierarchy": hierarchy(root)["mode"],
    }


# ---- what the archive accepts ------------------------------------------------------


def hierarchy(root: Path) -> dict:
    """The position ladder in effect: hydra's defaults, the archive's own
    positions.yaml, or both. Roles are matched to positions by these titles."""
    off = resources.defaults_off(root)
    generic = {} if "generic" in off else _yaml(root / layout.DEFAULT_POSITIONS)
    declared = {} if "hierarchy" in off else _yaml(root / layout.POSITIONS)
    compiled = rules.compile_rules(generic or None, declared or None)
    has_generic = bool(rules._positions_of(generic)) if generic else False
    has_declared = bool(rules._positions_of(declared)) if declared else False
    mode = ("custom and defaults" if has_generic and has_declared else "custom only" if has_declared
            else "defaults only" if has_generic else "none")
    positions = [{"position": name, "below": d.get("uppers") or d.get("below") or [],
                  "titles": d.get("titles") or [], "outside": d.get("outside", False), "from": d.get("source")}
                 for name, d in compiled["positions"].items()]
    return {
        "mode": mode, "positions": positions, "issues": compiled["issues"],
        "how_roles_rank": (
            "A relationship's `role` (or a person's own `position`) ranks the person when it equals a "
            "position's name or one of its titles, whole; case and accents are ignored and punctuation "
            "counts as a space. Write the role exactly as the source says it. Never change it to fit "
            "this list: save warns about roles no position takes, and the archive's owner can add "
            "them as titles in .hydra/rules/positions.yaml. A relationship with no role ranks no one."),
    }


# ---- schema and saved records, read back ---------------------------------------------


def describe_schema(name: str | None = None) -> dict:
    """With no `name`: the concrete schemas records can use (the relationships first
    in `relationships`, with their two end fields). With one: every property that
    schema accepts, with its type, the kind of entity a link takes, and whether it
    is required. The schema must already be loaded (`archive_or_defaults` does)."""
    if not name:
        rows = lambda edge: [{"schema": s, "label": d["label"], **({"from": d["edge"]["source"], "to": d["edge"]["target"]}
                                                                   if d.get("edge") else {})}
                             for s, d in sorted(schema.SCHEMA.items())
                             if not d.get("abstract") and not d.get("deprecated") and bool(d.get("edge")) == edge]
        return {"entities": rows(False), "relationships": rows(True),
                "next": "call describe_schema with a schema name to see its properties"}
    name = str(name).strip()
    if name not in schema.SCHEMA:
        close = [s for s in schema.SCHEMA if s.lower() == name.lower()]
        raise IngestError(f"no schema '{name}'" + (f"; did you mean '{close[0]}'?" if close else
                                                   "; call describe_schema with no name to list them"))
    sc, res = schema.SCHEMA[name], schema.resolve(name)
    required = {p for a in schema.ancestors(name) for p in schema.SCHEMA[a]["required"]}
    if sc.get("edge"):
        required |= {sc["edge"]["source"], sc["edge"]["target"]}
    elif "name" in res["props"]:
        required.add("name")
    props = []
    for p, d in res["props"].items():
        if p in IMAGE_FIELDS or p == "sources" or d.get("hidden"):
            continue
        row = {"property": p, "label": d["label"], "type": d["type"], "required": p in required,
               "featured": p in res["featured"]}
        if d["type"] == "entity":
            row["links_to"] = d.get("range") or "Thing"
            row["write_as"] = "the linked entity's exact name"
        elif d["type"] == "date":
            row["write_as"] = "YYYY, YYYY-MM or YYYY-MM-DD"
        props.append(row)
    props.sort(key=lambda r: (not r["required"], not r["featured"], r["property"]))
    out = {"schema": name, "label": sc["label"], "abstract": bool(sc.get("abstract")),
           "extends": list(schema.ancestors(name)[1:]), "properties": props,
           "never_write": ["sources, when save is given a `source` (the evidence is added for you; without one, each record cites its kept sources)", "images (linked in hints.yaml)"]}
    if sc.get("edge"):
        out["relationship"] = {"from": sc["edge"]["source"], "to": sc["edge"]["target"]}
    if sc.get("abstract"):
        out["note"] = "abstract: records must use a concrete schema that extends it"
    return out


def properties(root: Path, name: str | None = None, theme: str | None = None, level: str = "common",
               query: str | None = None, code: str | None = None) -> dict:
    """A schema's properties by theme with their Wikidata codes (`name`), a search (`query`), or one code (`code`)."""
    try:
        if code:
            c = str(code).strip().upper()
            if not hprops.PCODE.match(c):
                raise IngestError(f"'{code}' is not a Wikidata property code (P followed by digits)")
            found = catalog.lookup(c)
            fields = [{"schema": sn, "prop": p} for sn, sc in sorted(schema.SCHEMA.items()) for p in sc["properties"]
                      if hprops.code_of(p, sn, root) == c and not sc["properties"][p].get("hidden")]
            return {"code": c, "entry": found if found else (catalog.status() if "catalogue" in catalog.status() else None),
                    "fields": fields[:20] if fields else [],
                    "note": None if fields else "no field of this archive maps to this code; field_assign can add one"}
        if query:
            rows = hprops.search(query, root)
            near = catalog.match(query, limit=5)
            return {"query": query, "fields": rows[:40], "more": max(0, len(rows) - 40) or None,
                    "wikidata": near}
        if name:
            nm = str(name).strip()
            rows = hprops.describe(nm, level=level, theme=theme, root=root)
            out = {"schema": nm, "level": level, "theme": theme, "properties": rows}
            if not theme:
                out["links"] = [{k: r[k] for k in ("schema", "role", "other", "range", "edge")}
                                for r in hprops.relations_for(nm, root)]
            return out
    except hprops.PropsError as e:
        raise IngestError(str(e)) from None
    return {"themes": hprops.themes(), "next": "give `schema` for its properties (level common or all, `theme` to narrow), "
            "`query` to search every schema, or `code` (P…) for one Wikidata property"}


def extra_fields(root: Path) -> dict:
    """Every field kept outside FtM, with the records that hold it and the Wikidata matches."""
    try:
        rows = hprops.extra_fields(root)
    except hprops.PropsError as e:
        raise IngestError(str(e)) from None
    st = catalog.status()
    return {"fields": rows, "catalogue": st if "catalogue" in st else {"count": st["count"], "fetched": st["fetched"]},
            **({"next": "assign one with field_assign (to `Schema.prop`, `new:<name>` with `wd`, or `drop`)"} if rows else {})}


def field_assign(root: Path, field: str, schema_name: str, to: str, wd: str | None = None, confirm: bool = False) -> dict:
    try:
        out = hprops.assign_field(root, field, schema_name, to, wd=wd, confirm=confirm, who=AGENT)
    except hprops.PropsError as e:
        raise IngestError(str(e)) from None
    if out.get("saved"):
        workflows.hook_log(root, f"field_assign {schema_name}.{field} -> {to}")
        if out.get("snapshot"):
            out["undo"] = f"history restore {out['snapshot'][:12]}~1"
    return out


def get_records(root: Path, collection: str | None = None, name: str | None = None,
                offset: int = 0, limit: int = 50, query: str | None = None, ids: list[str] | None = None) -> dict:
    """What an archive holds, as stored: with no `collection`, the collections and
    their record counts; with one, its records, each property with its type, each
    link with the entity it resolves to in the last build (None: still a bare name),
    and the same checks `save` runs, repeated on what was written. `query` (or its
    older name `name`) narrows the records to those whose id or any value matches it,
    `ids` to those ids. Only the page returned is rebuilt and checked, so a
    collection of thousands answers at once."""
    files, entries = resources.record_files(root)
    if not collection:
        return {"collections": [{"collection": f.stem, "records": len(_load_records(f))} for f in files],
                "source_entries": [f.stem for f in entries],
                "next": "call again with collection=<name> to read its records back"}
    f = next((f for f in files if f.stem == collection), None)
    if f is None:
        if any(e.stem == collection for e in entries):
            raise IngestError(f"'{collection}' is a kept source entry, not a records collection: "
                              "call `sources` for its source_id and `read_source` to read its text")
        raise IngestError(f"no collection '{collection}'; have: {', '.join(x.stem for x in files) or 'none'}")
    stored = _load_records(f)
    want = types.norm_text(query or name) if (query or name) else None
    wanted_ids = {str(i).strip() for i in (ids or []) if str(i).strip()}
    if wanted_ids:
        stored = [r for r in stored if str(r.get("id")) in wanted_ids]
    if want:
        stored = [r for r in stored
                  if want in types.norm_text(str(r.get("id") or ""))
                  or any(want in types.norm_text(v) for vs in (r.get("properties") or {}).values() for v in vs)]
    total = len(stored)
    page_recs = stored[offset:offset + limit]
    missing = sorted(wanted_ids - {str(r.get("id")) for r in stored}) if wanted_ids else []
    check = check_records(root, [{"schema": r.get("schema"), "id": r.get("id"), "properties": r.get("properties") or {}}
                                 for r in page_recs], collection) if page_recs else         {"ok": True, "errors": [], "warnings": [], "roles": []}
    existing = _existing_names(root)
    nodes = _declared(root)
    by_ref = {rid: nid for nid, n in nodes.items() for rid in (nid, *(n.get("referents") or ()))}
    by_suffix: dict[str, str] = {}
    for k, nid in by_ref.items():
        if ":" in k:
            by_suffix.setdefault(k.split(":", 1)[1], nid)

    def resolves(v: str):
        """A link value -> the entities it resolves to: by id (as written, or with its
        collection's prefix, which the build adds) or else by name."""
        nid = by_ref.get(v) or by_suffix.get(v)
        if nid:
            n = nodes[nid]
            return [{"id": nid, "name": n.get("caption"), "schema": n.get("schema")}]
        return [{"id": h["id"], "name": h["caption"], "schema": h["schema"]}
                for h in existing.get(types.norm_text(v), [])[:3]] or None

    rows = []
    for r in page_recs:
        props, sname = r.get("properties") or {}, r.get("schema")
        defs = schema.resolve(sname)["props"] if sname in schema.SCHEMA else {}
        shown = {}
        for p, vs in props.items():
            t = (defs.get(p) or {}).get("type", "unknown property")
            if t == "entity" and p != "sources":
                shown[p] = {"type": t, "values": [{"value": v, "resolves_to": resolves(v)} for v in vs]}
            else:
                shown[p] = {"type": t, "values": vs}
        rows.append({"id": r.get("id"), "schema": sname, "properties": shown})
    cap = 30
    return {"collection": collection, "file": f.relative_to(root).as_posix(), "built": _built(root),
            "matching" if (want or wanted_ids) else "records": total, "offset": offset, "returned": len(rows),
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            **({"not_found": missing} if missing else {}),
            "check": {"ok": check["ok"], "errors": check["errors"][:cap], "warnings": check["warnings"][:cap],
                      **({"more": max(len(check["errors"]) - cap, 0) + max(len(check["warnings"]) - cap, 0)}
                         if len(check["errors"]) > cap or len(check["warnings"]) > cap else {}),
                      "roles": check["roles"]},
            "entities": rows,
            "note": None if _built(root) else "the archive is not built, so links show no resolution"}





def resolve_entity(root: Path, ref: str, kind: str | None = None):
    """The ONE entity a tool's `entity` argument names, through `hydra.records.entities.resolve`: an H or body (following
    redirects), a key, a record id, or a title exactly one page has. Never fuzzy, never the first of several:
    an ambiguous reference is refused with the candidate Hs and titles (kind `Ambiguous`), an unknown one with
    near candidates as hints (kind `NotFound`). -> entities.Hit(body, h, how)."""
    if not layer.is_universe(root):
        raise IngestError("this archive has no universe layer: `hydra-ctl universe init` adds one")
    try:
        return entities.resolve(root, ref, kind, names="unique")
    except entities.Ambiguous as e:
        raise IngestError(str(e), kind="Ambiguous") from None
    except entities.NotFound as e:
        raise IngestError(str(e), kind="NotFound") from None


# ---- reading a file ---------------------------------------------------------------------


def read_file(root: Path | None, path: str, offset: int | None = None, part: int | None = None,
              whole: bool = False) -> dict:
    """A file's text as the archive would store it, and whether the archive already holds it. A long file with no
    `offset` or `part` gives its profile and part plan, not text (chunked reading, owner 2026-11-21); `part=n` gives
    that part; `offset` (or `whole`) reads READ_LIMIT characters from there, as before."""
    f = resolve_file(root, path)
    if part is not None or (offset is None and not whole):
        have = _source_by_hash(root).get(files.read(f)["sha1"]) if root else None
        held = {"source": have["id"], "collection": have["collection"]} if have else None
        p = prof.profile(f)
        if part is None and len(p["parts"]) > 1:
            return {**p, "already_in_archive": held,
                    "next": "take the parts to Gate 1 (which are in scope), then read_file(path, part=n) one at a time; "
                            "the warnings say what to watch for"}
        if part is not None:
            row, text, n = prof.part_text(f, int(part))
            nxt = (f"read_file(path, part={row['part'] + 1})" if row["part"] < n else "all parts read")
            return {"file": str(f), "name": f.name, "type": p["type"], "sha1": p["sha1"], "chars": p["size"]["chars"],
                    "part": row["part"], "parts": n, "pages": row["pages"], "title": row["title"],
                    "start": row["start"], "end": row["end"], "already_in_archive": held, "text": text,
                    "next": nxt + ("; " + (f"this file is already saved as evidence '{have['id']}'" if have
                                           else f'save the records with source={{"file": "{f}"}}'))}
        offset = 0                                              # one part: the whole text, as before
    info = files.read(f)
    text, offset = info.pop("text"), max(0, int(offset or 0))
    part = text[offset:offset + READ_LIMIT]
    nxt = offset + len(part) if offset + len(part) < len(text) else None
    have = _source_by_hash(root).get(info["sha1"]) if root else None
    if root and have:
        workflows.hook_source(root, have["id"])
    page_ranges = info.pop("page_ranges", None)
    return {"file": str(f), **info, "chars": len(text),
            "already_in_archive": {"source": have["id"], "collection": have["collection"]} if have else None,
            "offset": offset, "next_offset": nxt,
            **({"page_ranges": page_ranges} if page_ranges else {}),
            "text": part,
            "next": ("call read_file again with offset=next_offset for the rest; " if nxt else "") + (
                f"this file is already saved as evidence '{have['id']}': to add records from it, save with "
                f'source={{"id": "{have["id"]}"}}' if have else f'save the records with source={{"file": "{f}"}}')}

