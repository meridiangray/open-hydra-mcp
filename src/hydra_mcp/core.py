"""The ingestion logic behind the MCP tools, as plain functions.

The model connected to the server reads the raw text and proposes records; these
functions tell it what the archive accepts, check what it proposes, and only then
write it. Nothing here guesses facts: every check reports, and the one write
(`ingest`) refuses a batch with errors.

What an ingestion writes, and so what undoing it means:
  collections/<collection>.json                   the records
  .hydra/sources/entries/<collection>.json        the source: one document naming the evidence
      (a pasted text keeps it in bodyText; a file keeps fileName/mimeType/contentHash plus
      what extracted the text and the sha1 of that extraction, so re-extraction can be compared)
  .hydra/sources/files/<collection>/<file>        the original file, when the source is one
Every entity cites that document in `sources`, so each value traces back to the
text it came from (`hydra-ctl claims`, `hydra-ctl sources`). An entity already in
the archive that the text names is cited too, by a record with its exact name and
type, which hydra recognizes as the same entity. Relationships have no `sources`
field in FtM: they trace back through their collection. Delete what it wrote and
rebuild to undo it. A later ingestion can cite an earlier source by its id
(`source: {"id": ...}`) and then writes only its collection.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hydra import build, dates, layout, resources, schema
from hydra.identity import types
from hydra.shape import rules

NAME_PROPS = ("name", "alias", "weakAlias", "previousName")
IMAGE_FIELDS = ("thumb", "portrait", "logo", "badge", "icon")
SLUG = re.compile(r"[^a-z0-9]+")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
VALID_NAME =re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SOURCE_FILES = f"{layout.SOURCES_DIR}/files"      # the original files sources were read from
READ_LIMIT = 60_000                               # characters of a file's text per read_file call


class IngestError(ValueError):
    """A request the archive can't take: no archive, a bad name, a batch with errors."""


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
        root = resources.archive(named)
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
    from hydra.ingest import default_prefix, valid_prefix
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
           "ids": f"records get ids like {prefix}:person-dana-hale" if prefix else
                  "each collection gets its own prefix, made from its name"}
    if not confirm:
        return {**out, "next": "confirm the folder, name and prefix with the person, then call again with confirm=true"}
    from hydra.cli import init
    init.create(p, name, prefix)
    root = open_archive(str(p))
    return {**out, "created": True, "archive": str(root), "overview": overview(root),
            "next": f'pass archive="{root}" to every tool from now on (the person can make it the default by '
                    f'setting HYDRA_ARCHIVE={root} in the MCP server\'s configuration), then ingest the text'}


def _yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def _built(root: Path) -> bool:
    return (root / layout.BUILD_YAML).is_file()


def _open_counts(root: Path) -> dict[str, int]:
    if not _built(root):
        return {}
    from hydra.cli import todo
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
           "never_write": ["sources (the evidence is added for you)", "images (linked in hints.yaml)"]}
    if sc.get("edge"):
        out["relationship"] = {"from": sc["edge"]["source"], "to": sc["edge"]["target"]}
    if sc.get("abstract"):
        out["note"] = "abstract: records must use a concrete schema that extends it"
    return out


def get_records(root: Path, collection: str | None = None, name: str | None = None,
                offset: int = 0, limit: int = 50) -> dict:
    """What an archive holds, as stored: with no `collection`, the collections and
    their record counts; with one, its records, each property with its type, each
    link with the entity it resolves to in the last build (None: still a bare name),
    and the same checks `save` runs, repeated on what was written. `name` narrows
    the records to those whose name or any value matches it."""
    files, entries = resources.record_files(root)
    if not collection:
        return {"collections": [{"collection": f.stem, "records": len(_load_records(f))} for f in files],
                "source_entries": [f.stem for f in entries],
                "next": "call again with collection=<name> to read its records back"}
    f = next((f for f in files if f.stem == collection), None)
    if f is None:
        raise IngestError(f"no collection '{collection}'; have: {', '.join(x.stem for x in files) or 'none'}")
    stored = _load_records(f)
    check = check_records(root, [{"schema": r.get("schema"), "id": r.get("id"),
                                  "properties": {p: v for p, v in (r.get("properties") or {}).items() if p != "sources"}}
                                 for r in stored], collection)
    existing = _existing_names(root)
    want = types.norm_text(name) if name else None
    rows = []
    for r in stored:
        props, sname = r.get("properties") or {}, r.get("schema")
        if want and not any(want in types.norm_text(v) for vs in props.values() for v in vs):
            continue
        defs = schema.resolve(sname)["props"] if sname in schema.SCHEMA else {}
        shown = {}
        for p, vs in props.items():
            t = (defs.get(p) or {}).get("type", "unknown property")
            if t == "entity" and p != "sources":
                shown[p] = {"type": t, "values": [{"value": v, "resolves_to": [
                    {"id": h["id"], "name": h["caption"], "schema": h["schema"]}
                    for h in existing.get(types.norm_text(v), [])[:3]] or None} for v in vs]}
            else:
                shown[p] = {"type": t, "values": vs}
        rows.append({"id": r.get("id"), "schema": sname, "properties": shown})
    page = rows[offset:offset + limit]
    return {"collection": collection, "file": f.relative_to(root).as_posix(), "built": _built(root),
            "matching" if want else "records": len(rows), "offset": offset, "returned": len(page),
            "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
            "check": {"ok": check["ok"], "errors": check["errors"], "warnings": check["warnings"],
                      "roles": check["roles"]},
            "entities": page,
            "note": None if _built(root) else "the archive is not built, so links show no resolution"}


def _load_records(f: Path) -> list[dict]:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


# ---- images ------------------------------------------------------------------------------


def link_image(root: Path, image: str, kind: str, match: dict, confirm: bool = False) -> dict:
    """Preview (default) or add a hints.yaml rule giving every entity `match` picks
    an image: `kind` is portrait, thumb (an icon) or logo. Images are never in
    records; this is the one way they get in, and only the archive's owner approves."""
    from hydra.cli import hints
    if kind not in hints.FOLDER:
        raise IngestError(f"kind must be one of: {', '.join(hints.FOLDER)} (thumb is an icon)")
    match = {k: v for k, v in (match or {}).items() if v}
    if not match:
        raise IngestError("say which entities: schema, position, titled and/or name")
    path = Path(str(image or "").strip())
    if not str(image or "").strip():
        raise IngestError("give the image's full path")
    out = {"image": str(path), "kind": kind, "match": match, "added": False}
    if not confirm:
        try:
            if not path.is_file() and not (root / layout.RESOURCES_DIR / path).is_file():
                raise IngestError(f"{path} not found")
            if path.suffix.lower() not in hints.IMAGE_TYPES:
                raise IngestError(f"{path.name} is not an image ({', '.join(hints.IMAGE_TYPES)})")
        except OSError as e:
            raise IngestError(str(e)) from None
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    lines: list[str] = []
    try:
        hints.set_rule(root, kind, path, {**match, **({"titled": {"contains": match["titled"]}} if "titled" in match else {})},
                       not _built(root), lines.append)    # an archive with nothing built has nothing to rebuild
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: ")) from None
    return {**out, "added": True, "result": [ANSI.sub("", l) for l in lines]}


# ---- checking a batch ----------------------------------------------------------------


def _slug(text: str) -> str:
    return SLUG.sub("-", types.norm_text(text)).strip("-")[:40] or "x"


def _values(v) -> list[str]:
    vals = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in vals if x is not None and str(x).strip()]


def _existing_names(root: Path) -> dict[str, list[dict]]:
    """normalized name -> the existing nodes carrying it (caption, names, aliases)."""
    out: dict[str, list[dict]] = {}
    for rid, n in resources.declared_nodes(root).items():
        names = {n.get("caption") or ""} | {v for p in NAME_PROPS for v in (n.get("props") or {}).get(p) or []}
        for v in names:
            k = types.norm_text(v)
            if k:
                out.setdefault(k, []).append({"id": rid, "caption": n.get("caption"), "schema": n.get("schema")})
    return out


def _ids_in(root: Path, skip: str | None = None) -> dict[str, str]:
    """id -> the collection (or source entry) file holding it, as the files write them."""
    files, entries = resources.record_files(root)
    out = {}
    for f in files + entries:
        if f.stem == skip:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for r in data if isinstance(data, list) else []:
            if isinstance(r, dict) and r.get("id"):
                out.setdefault(str(r["id"]), f.relative_to(root).as_posix())
    return out


def normalize(records: list[dict], taken_ids=()) -> list[dict]:
    """Records as hydra writes them: `{id, schema, properties: {prop: [str]}}`, with
    a readable id made from the schema and name when none is given, never one the
    archive already uses (`taken_ids`)."""
    out, taken = [], set(taken_ids)
    for r in records or []:
        if not isinstance(r, dict):
            raise IngestError("each record must be an object with `schema` and `properties`")
        props = {p: _values(v) for p, v in (r.get("properties") or {}).items()}
        props = {p: v for p, v in props.items() if v}
        rid = str(r.get("id") or "").strip()
        if not rid:
            label = (props.get("name") or props.get("role") or [r.get("schema") or "record"])[0]
            base = f"{_slug(str(r.get('schema') or 'record'))}-{_slug(label)}"
            rid, k = base, 2
            while rid in taken:
                rid, k = f"{base}-{k}", k + 1
        taken.add(rid)
        out.append({"id": rid, "schema": str(r.get("schema") or "").strip(), "properties": props})
    return out


def check_records(root: Path, records: list[dict], collection: str | None = None) -> dict:
    """Everything wrong or worth knowing about a proposed batch, without writing.
    `errors` block an ingestion; `warnings` and the rest are for the reader.
    `collection`: the one being replaced, whose ids are free to reuse."""
    used = _ids_in(root, skip=collection)
    recs = normalize(records, used)
    errors, warnings = [], []
    for r in recs:
        if r["id"] in used:
            errors.append(f"{r['id']}: this id is already used in {used[r['id']]}; leave `id` out and one is made")
    ids = [r["id"] for r in recs]
    for rid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"{rid}: two records have this id")
    in_batch: dict[str, str] = {}                                  # normalized name or id -> record id
    for r in recs:
        in_batch[types.norm_text(r["id"])] = r["id"]
        for p in NAME_PROPS:
            for v in r["properties"].get(p) or []:
                in_batch.setdefault(types.norm_text(v), r["id"])
    existing = _existing_names(root)
    off = resources.defaults_off(root)
    compiled = rules.compile_rules(None if "generic" in off else _yaml(root / layout.DEFAULT_POSITIONS) or None,
                                   None if "hierarchy" in off else _yaml(root / layout.POSITIONS) or None)
    positions = compiled["positions"]
    links, roles, duplicates, cited, cite = [], [], [], [], {}

    for r in recs:
        rid, sname, props = r["id"], r["schema"], r["properties"]
        if not VALID_NAME.match(rid):
            errors.append(f"{rid}: an id may hold letters, digits, - and _ only")
        if sname not in schema.SCHEMA:
            errors.append(f"{rid}: no schema '{sname}' (FtM types: Person, Company, Membership...)")
            continue
        if schema.SCHEMA[sname].get("abstract"):
            errors.append(f"{rid}: {sname} is abstract; use a concrete kind (Person, Company, Membership...)")
        pdefs = schema.resolve(sname)["props"]
        edge = schema.SCHEMA[sname].get("edge") or {}
        for p, vals in props.items():
            if p in IMAGE_FIELDS:
                errors.append(f"{rid}.{p}: records never carry images; they are linked in .hydra/rules/hints.yaml")
            elif p not in pdefs and p != "proof":
                errors.append(f"{rid}.{p}: {sname} has no property '{p}'")
            elif (pdefs.get(p) or {}).get("type") == "date":
                errors += [f"{rid}.{p}: '{v}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD)"
                           for v in vals if dates.bounds(v) is None]
        if edge:
            for end in (edge["source"], edge["target"]):
                if not props.get(end):
                    errors.append(f"{rid}: a {sname} needs `{end}`")
        elif "name" in pdefs and not props.get("name"):
            errors.append(f"{rid}: a {sname} needs a `name`")
        # links: to this batch, to the archive, or a new name hydra will ask about
        for p, vals in props.items():
            d = pdefs.get(p) or {}
            if d.get("type") != "entity" or p in ("sources", "proof"):
                continue
            for v in vals:
                k = types.norm_text(v)
                if k in in_batch:
                    links.append({"record": rid, "field": p, "value": v, "links_to": f"this batch: {in_batch[k]}"})
                elif k in existing:
                    hits = existing[k]
                    links.append({"record": rid, "field": p, "value": v,
                                  "links_to": ", ".join(f"{h['caption']} ({h['id']})" for h in hits[:3])})
                    if len(hits) > 1:
                        warnings.append(f"{rid}.{p}: '{v}' names {len(hits)} existing records; review will ask which")
                    elif hits[0]["schema"] in schema.SCHEMA and "sources" in schema.resolve(hits[0]["schema"])["props"]:
                        cite.setdefault(hits[0]["id"], hits[0])   # an existing entity this text names: cite it
                else:
                    links.append({"record": rid, "field": p, "value": v, "links_to": None})
                    warnings.append(f"{rid}.{p}: '{v}' is no record in this batch or the archive; it stays "
                                    "a name until a record for it exists (`hydra-ctl stubs` lists these)")
        # roles: what each one ranks as under the hierarchy in effect
        for p in ("role", "position"):
            if p not in pdefs:
                continue
            for v in props.get(p) or []:
                pos = rules.canonical(v, positions)
                roles.append({"record": rid, "field": p, "value": v, "position": pos})
                if pos is None:
                    warnings.append(f"{rid}.{p}: '{v}' takes no position, so it ranks no one; to rank it, add "
                                    f"'{types.norm_text(v)}' to a position's titles in .hydra/rules/positions.yaml")
        # an entity that may already be in the archive: review will propose the merge
        same = [h for h in existing.get(types.norm_text(props["name"][0]), []) if h["schema"] == sname] \
            if not edge and props.get("name") else []
        if same:                          # its exact name and type: the same entity, citing this text
            cited.append({"record": rid, "name": props["name"][0], "existing": same[0]["caption"],
                          "existing_id": same[0]["id"]})
        elif not edge and props.get("name") and _built(root):
            from hydra.cli import node
            hit = next((h for h in node.find(root, props["name"][0], sname, field="name", limit=1)
                        if h["score"] >= 0.9), None)
            if hit:
                duplicates.append({"record": rid, "name": props["name"][0], "existing": hit["caption"],
                                   "existing_id": hit["id"], "score": hit["score"]})

    named = {types.norm_text(c["existing"]) for c in cited}
    auto = [{"schema": h["schema"], "name": h["caption"], "existing_id": i} for i, h in cite.items()
            if types.norm_text(h["caption"] or "") not in named and types.norm_text(h["caption"] or "") not in in_batch]
    return {"ok": not errors, "errors": errors, "warnings": warnings, "records": recs,
            "links": links, "roles": roles, "possible_duplicates": duplicates,
            "existing_entities_cited": cited, "will_also_cite": auto,
            "note": ("possible_duplicates are not errors: if they are the same entity, the build proposes "
                     "the merge and the archive's owner confirms it in review.") if duplicates else None}


# ---- writing ---------------------------------------------------------------------------


def resolve_file(root: Path | None, path: str) -> Path:
    """A file the person gave, by its full path."""
    p = Path(str(path or "").strip()).expanduser()
    if not str(path or "").strip() or not p.is_absolute():
        raise IngestError(f"'{path}' is not a full path: give the file's full path")
    if not p.is_file():
        raise IngestError(f"{p} not found")
    return p


def _source_entries(root: Path) -> list[dict]:
    out = []
    for f in resources.record_files(root)[1]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out += [{**r, "collection": f.stem} for r in data if isinstance(data, list) and isinstance(r, dict)]
    return out


def _source_by_hash(root: Path) -> dict[str, dict]:
    return {h: r for r in _source_entries(root) for h in (r.get("properties") or {}).get("contentHash") or []}


def read_file(root: Path | None, path: str, offset: int = 0) -> dict:
    """A file's text as the archive would store it, in parts of READ_LIMIT
    characters, and whether the archive already holds it."""
    from hydra_mcp import files
    f = resolve_file(root, path)
    info = files.read(f)
    text, offset = info.pop("text"), max(0, int(offset or 0))
    part = text[offset:offset + READ_LIMIT]
    nxt = offset + len(part) if offset + len(part) < len(text) else None
    have = _source_by_hash(root).get(info["sha1"]) if root else None
    return {"file": str(f), **info, "chars": len(text),
            "already_in_archive": {"source": have["id"], "collection": have["collection"]} if have else None,
            "offset": offset, "next_offset": nxt, "text": part,
            "next": ("call read_file again with offset=next_offset for the rest; " if nxt else "") + (
                f"this file is already saved as evidence '{have['id']}': to add records from it, save with "
                f'source={{"id": "{have["id"]}"}}' if have else f'save the records with source={{"file": "{f}"}}')}


def _new_source(root: Path, collection: str, source: dict) -> tuple[dict, Path | None, list[str]]:
    """The source document of a new ingestion, from a file or a text, and the file to copy."""
    from hydra_mcp import files
    notes, path, props = [], None, {}
    if source.get("file"):
        path = resolve_file(root, source["file"])
        info = files.read(path)
        have = _source_by_hash(root).get(info["sha1"])
        if have:
            raise IngestError(f"{path.name} is already saved as evidence '{have['id']}'; to add records from it, "
                              f"save with source={{\"id\": \"{have['id']}\"}}")
        if source.get("text"):
            notes.append("source.text was not used: the file is the evidence")
        title = path.stem
        props = {"fileName": [info["name"]], "mimeType": [info["type"]], "contentHash": [info["sha1"]],
                 "fileSize": [str(info["size"])],
                 "processingAgent": [f"hydra-mcp files.read ({info['extractor']})"],
                 "notes": [f"sha1 of the text extracted from this file: {info['text_sha1']}"]}
    else:
        text = str(source.get("text") or "").strip()
        if not text:
            raise IngestError("the source is empty: pass source.file (a file to read) or source.text (the raw text)")
        title = text.splitlines()[0][:80]
        props = {"bodyText": [text]}
    props = {"title": [str(source.get("title") or "").strip() or title],
             "retrievedAt": [datetime.now(timezone.utc).date().isoformat()], **props}
    for key, prop in (("url", "sourceUrl"), ("publisher", "publisher"), ("author", "author"),
                      ("published", "publishedAt"), ("language", "language")):
        if source.get(key):
            props[prop] = [str(source[key])]
    if props.get("publishedAt") and dates.bounds(props["publishedAt"][0]) is None:
        raise IngestError(f"source.published '{props['publishedAt'][0]}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD)")
    doc = {"id": f"{collection}-source", "schema": "Article" if source.get("url") else "Document", "properties": props}
    return doc, path, notes


def _existing_source(root: Path, sid: str) -> dict:
    want = str(sid).strip()
    for r in _source_entries(root):
        if want in (r["id"], r["id"].split(":", 1)[-1]) or want.split(":", 1)[-1] == r["id"]:
            return r
    raise IngestError(f"no source '{sid}' in the archive (`hydra-ctl sources` lists them)")


def ingest(root: Path, records: list[dict], source: dict, collection: str | None = None,
           replace: bool = False, rebuild: bool = True) -> dict:
    """Check the batch; if it has no errors, write it as a new collection citing its
    source (a file, a text, or an earlier source by id), then rebuild and report
    what changed. Refuses an existing collection unless `replace`."""
    source = source or {}
    old_src = _existing_source(root, source["id"]) if source.get("id") else None
    stem = (Path(str(source["file"])).stem if source.get("file") else
            old_src["collection"] if old_src else str(source.get("title") or "text"))
    collection = collection or f"{_slug(str(source.get('title') or stem))}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    if not VALID_NAME.match(collection):
        raise IngestError(f"'{collection}' cannot name a collection (letters, digits, - and _)")
    report = check_records(root, records, collection if replace else None)
    if not report["ok"]:
        return {"saved": False, "errors": report["errors"], "warnings": report["warnings"]}
    cfile = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    sfile = root / layout.SOURCE_ENTRIES / f"{collection}.json"
    if (cfile.exists() or (sfile.exists() and not old_src)) and not replace:
        raise IngestError(f"collection '{collection}' exists; pass replace=true or another name")
    if old_src:
        doc, fpath, notes, sid = None, None, [], old_src["id"]
    else:
        doc, fpath, notes = _new_source(root, collection, source)
        sid = doc["id"]
    extra = normalize([{"schema": a["schema"], "properties": {"name": [a["name"]]}} for a in report["will_also_cite"]],
                      set(_ids_in(root, skip=collection if replace else None)) | {r["id"] for r in report["records"]})
    cites = lambda r: "sources" in schema.resolve(r["schema"])["props"]
    recs = [{**r, "properties": {**r["properties"],
                                 "sources": list(dict.fromkeys((r["properties"].get("sources") or []) + [sid]))}}
            if cites(r) else r for r in report["records"] + extra]
    ffile = root / SOURCE_FILES / collection / fpath.name if fpath else None
    written = [cfile] + ([sfile] if doc else []) + ([ffile] if ffile else [])
    old = {f: f.read_bytes() for f in written if f.exists()}
    for f in written:
        f.parent.mkdir(parents=True, exist_ok=True)
    cfile.write_text(json.dumps(recs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if doc:
        sfile.write_text(json.dumps([doc], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if ffile:
        ffile.write_bytes(fpath.read_bytes())
    rel = [f.relative_to(root).as_posix() for f in written]
    out = {"saved": True, "collection": collection, "files": rel, "records": len(recs), "source_id": sid,
           "evidence": ffile.relative_to(root).as_posix() if ffile else None,
           "existing_entities_cited": [c["name"] for c in report["existing_entities_cited"]]
                                      + [e["properties"]["name"][0] for e in extra],
           "warnings": report["warnings"] + notes,
           "undo": f"delete {', '.join(rel)}, then `hydra-ctl build`"}
    if not rebuild:
        return out
    try:
        summary = build.build_archive(root)
    except Exception as e:                            # put the archive back as it was
        for f in written:
            f.write_bytes(old[f]) if f in old else f.unlink(missing_ok=True)
        raise IngestError(f"the build failed, so nothing was kept: {e}") from None
    out.update({"build": build.report(root, summary, verb="Rebuilt"),
                "issues": [i for i in summary.get("issues") or [] if i.get("file") in set(rel)]})
    return out
