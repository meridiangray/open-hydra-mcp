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

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hydra import build, dates, history, layout, resources, schema, standards, vocab
from hydra import ingest as hingest
from hydra import keys as hkeys
from hydra.identity import types
from hydra.shape import rules

from hydra_mcp import mint

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
           "ids": f"records get ids like {prefix}:per-w3v2f7z7pe" if prefix else
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
    nodes = resources.declared_nodes(root)
    by_ref = {rid: nid for nid, n in nodes.items() for rid in (nid, *(n.get("referents") or ()))}

    def resolves(v: str):
        """A link value -> the entities it resolves to: by id (as written, or with its
        collection's prefix, which the build adds) or else by name."""
        nid = by_ref.get(v) or next((by_ref[k] for k in by_ref if k.endswith(":" + v)), None)
        if nid:
            n = nodes[nid]
            return [{"id": nid, "name": n.get("caption"), "schema": n.get("schema")}]
        return [{"id": h["id"], "name": h["caption"], "schema": h["schema"]}
                for h in existing.get(types.norm_text(v), [])[:3]] or None

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
                shown[p] = {"type": t, "values": [{"value": v, "resolves_to": resolves(v)} for v in vs]}
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
    """A collection or source-entry file's records as written: a JSON array (as `save`
    writes it) or one record per line (as `import` does); [] when it does not parse."""
    try:
        return hingest.raw_records(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


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


FACT_PROPS = ("birthDate", "deathDate", "nationality", "country", "position", "gender", "jurisdiction",
              "incorporationDate", "organization")


def _canon_row(root: Path, node_id: str) -> dict | None:
    """A node's row in the last universe build: its H (with state and flags), its keys..."""
    from hydra.universe import layer
    if not layer.is_universe(root):
        return None
    node = resources.declared_nodes(root).get(node_id) or {}
    ids = {node_id, *(node.get("referents") or ())}
    for row in layer.read_parsed(root, "canon.jsonl", missing=[]):
        if not row.get("redirect") and any(m.split("/", 1)[1] in ids for m in row.get("members") or []
                                           if m.startswith(layer.SELF + "/")):
            return row
    return None


def _h_of(root: Path, node_id: str) -> str | None:
    """The canonical id (H) of a node, with its state and flags, from the last universe build."""
    return (_canon_row(root, node_id) or {}).get("h")


def _keyed(root: Path) -> dict[str, dict]:
    """`ns:key` (as compared) -> the canon row of the entity holding it, from the last universe build."""
    from hydra.universe import layer
    if not layer.is_universe(root):
        return {}
    return {k: row for row in layer.read_parsed(root, "canon.jsonl", missing=[])
            if not row.get("redirect") for k in row.get("keys") or ()}


def _facts(root: Path, node_id: str) -> dict:
    """What tells an existing entity apart from its namesakes: its H, dates, nationality,
    the posts it holds and its parents, as the last build has them."""
    n = resources.declared_nodes(root).get(node_id) or {}
    props = n.get("props") or {}
    facts = {p: props[p] for p in FACT_PROPS if props.get(p)}
    rels = [f"{r.get('relationship') or r.get('label') or ''}: {r.get('cap') or r.get('at')}".strip(": ")
            for r in n.get("rels") or []][:6]
    out = {"facts": facts, **({"links": rels} if rels else {})}
    row = _canon_row(root, node_id) or {}
    return {**out, **({"h": row["h"]} if row.get("h") else {}), **({"keys": row["keys"]} if row.get("keys") else {})}


def _facts_of_batch(recs: list[dict], rid: str) -> dict:
    r = next((x for x in recs if x["id"] == rid), {"properties": {}, "schema": ""})
    return {"caption": (r["properties"].get("name") or [rid])[0], "schema": r["schema"],
            "facts": {p: r["properties"][p] for p in FACT_PROPS if r["properties"].get(p)}}


def _ids_in(root: Path, skip: str | None = None) -> dict[str, str]:
    """id -> the collection (or source entry) file holding it, as the files write them."""
    files, entries = resources.record_files(root)
    out = {}
    for f in files + entries:
        if f.stem == skip:
            continue
        for r in _load_records(f):
            out.setdefault(str(r["id"]), f.relative_to(root).as_posix())
    return out


def normalize(records: list[dict], taken_ids=()) -> list[dict]:
    """Records as hydra writes them: `{id, schema, properties: {prop: [str]}}`, with
    a minted id (`per-` and ten random characters, see mint.py) when none is given,
    never one the archive already uses (`taken_ids`). A schema that cannot be minted
    (unknown, abstract, no code) gets a placeholder; `check_records` reports the schema."""
    out, taken = [], set(taken_ids)
    for r in records or []:
        if not isinstance(r, dict):
            raise IngestError("each record must be an object with `schema` and `properties`")
        props = {p: _values(v) for p, v in (r.get("properties") or {}).items()}
        props = {p: v for p, v in props.items() if v}
        rid = str(r.get("id") or "").strip()
        if not rid:
            try:
                rid = mint.mint_id(str(r.get("schema") or "").strip(), taken)
            except mint.MintError:
                rid = f"unmintable_{len(out) + 1}"
        taken.add(rid)
        rec = {"id": rid, "schema": str(r.get("schema") or "").strip(), "properties": props}
        if isinstance(r.get("_meta"), dict) and r["_meta"]:     # a saved record's qualifiers (`approx`) stay
            rec["_meta"] = json.loads(json.dumps(r["_meta"]))
        out.append(rec)
    return out


def storable(records: list[dict]) -> list[dict]:
    """Records as a collection file keeps them: `_meta.cites` only served the quote check."""
    for r in records:
        meta = r.get("_meta") or {}
        meta.pop("cites", None)
        if "_meta" in r and not meta:
            r.pop("_meta")
    return records


def _batch_source_text(root: Path, source: dict | None) -> str | None:
    """The text of the source a batch is saved with (a file, a text, a kept source's id)."""
    if not source:
        return None
    if source.get("id"):
        from hydra_mcp import sources as src
        return src.text_of(root, source["id"])
    if source.get("file"):
        from hydra_mcp import files
        return files.read(resolve_file(root, source["file"]))["text"]
    return str(source.get("text") or "") or None


def check_records(root: Path, records: list[dict], collection: str | None = None, link_by: str = "id",
                  source: dict | None = None) -> dict:
    """Everything wrong or worth knowing about a proposed batch, without writing.
    `errors` block an ingestion; `warnings` and the rest are for the reader.
    `collection`: the one being replaced, whose ids are free to reuse.
    `link_by="id"` (the default): a link written as a name that names exactly one
    record (in this batch or the archive) is written as that record's id, so it
    can never land on a namesake later; a name that names several is kept and
    listed in `ambiguous_links` with each candidate's distinguishing facts, for the
    model to answer with an id. `link_by="name"` keeps every link as written.
    A link must name the kind of entity its field takes (an Event's `involved` a
    legal entity, an Ownership's `asset` an asset). A record's `notes` must be in
    the text of its sources, word for word: the batch's `source` and the kept
    sources the record cites in `sources` (`fetch_source` keeps one)."""
    used = _ids_in(root, skip=collection)
    recs = normalize(records, used)
    errors, warnings = [], []
    for r in recs:
        if r["id"] in used:
            errors.append(f"{r['id']}: this id is already used in {used[r['id']]}; leave `id` out and one is made")
    ids = [r["id"] for r in recs]
    for rid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"{rid}: two records have this id")
    batch_ids = set(ids)
    in_batch: dict[str, str] = {}                                  # normalized name or id -> record id
    batch_names: dict[str, set] = {}                               # normalized name -> every record carrying it
    for r in recs:
        in_batch[types.norm_text(r["id"])] = r["id"]
        for p in NAME_PROPS:
            for v in r["properties"].get(p) or []:
                in_batch.setdefault(types.norm_text(v), r["id"])
                batch_names.setdefault(types.norm_text(v), set()).add(r["id"])
    ambiguous = []
    existing = _existing_names(root)
    existing_ids = set(resources.declared_nodes(root)) | set(used)
    off = resources.defaults_off(root)
    compiled = rules.compile_rules(None if "generic" in off else _yaml(root / layout.DEFAULT_POSITIONS) or None,
                                   None if "hierarchy" in off else _yaml(root / layout.POSITIONS) or None)
    positions = compiled["positions"]
    vocabs = vocab.load(root)
    keyconf, keyed, keyed_out = hkeys.load(root), _keyed(root), []
    std = standards.load(root)
    from hydra_mcp import sources as src
    batch_text = _batch_source_text(root, source)
    kept_text: dict[str, str | None] = {}
    nodes = resources.declared_nodes(root)
    schema_of_id = {i: n.get("schema") for i, n in nodes.items()}
    schema_of_id.update({ref: n.get("schema") for n in nodes.values() for ref in n.get("referents") or ()})
    batch_schema = {r["id"]: r["schema"] for r in recs}

    def fits(target: str | None, rng: str | None) -> bool:
        return not (rng and target and target in schema.SCHEMA and rng in schema.SCHEMA) or schema.is_a(target, rng)
    links, roles, duplicates, cited, cite = [], [], [], [], {}

    for r in recs:
        rid, sname, props = r["id"], r["schema"], r["properties"]
        if sname in schema.SCHEMA and props.get("sources") and "sources" not in schema.resolve(sname)["props"]:
            # a relationship (Ownership, Family...) has no `sources` in FtM: it cites a kept source by its URL,
            # and the source still checks its notes
            cite_ids, urls = list(props.pop("sources")), []
            for sid in cite_ids:
                try:
                    u = (_existing_source(root, sid).get("properties") or {}).get("sourceUrl") or []
                except IngestError:
                    errors.append(f"{rid}.sources: '{sid}' is no source in the archive")
                    continue
                if not u:
                    errors.append(f"{rid}.sources: '{sid}' has no URL, and a {sname} cites by URL; give the batch "
                                  "`source` instead")
                urls += u
            props["sourceUrl"] = list(dict.fromkeys((props.get("sourceUrl") or []) + urls))
            r.setdefault("_meta", {})["cites"] = cite_ids
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
                fixed = []
                for v in vals:                # "c. 1748", "before 1800", "1950s": the date, its qualifier kept
                    d, kind = dates.exact(v)
                    if d is None:
                        errors.append(f"{rid}.{p}: '{v}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD; "
                                      "or c. YYYY, before YYYY, after YYYY, YYYYs, YYYY?)")
                        fixed.append(v)
                        continue
                    fixed.append(d)
                    if kind:
                        r.setdefault("_meta", {}).setdefault("approx", {})[p] = kind
                props[p] = fixed
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
            out_vals = []
            rng = d.get("range")

            def wrong_kind(v, target_schema):
                """A link to the wrong kind of entity: an estate in a deal's `involved`, a person as an asset."""
                if not fits(target_schema, rng):
                    hint = (" (an asset reaches its deal through its Ownership's `transaction`)"
                            if p in ("involved", "organizer") and schema.is_a(target_schema, "Asset") else "")
                    an = lambda w: ("an " if w[:1] in "AEIOU" else "a ") + w
                    errors.append(f"{rid}.{p}: '{v}' is {an(target_schema)}; `{p}` takes {an(rng)}{hint}")
            for v in vals:
                k = types.norm_text(v)
                if v in batch_ids or v in existing_ids:
                    links.append({"record": rid, "field": p, "value": v, "links_to": f"id: {v}"})
                    wrong_kind(v, batch_schema.get(v) or schema_of_id.get(v))
                    out_vals.append(v)
                    continue
                namesakes = batch_names.get(k, set())
                hits = existing.get(k, [])
                if len(namesakes) > 1 or (namesakes and hits) or (not namesakes and len(hits) > 1):
                    cands = [{"id": i, "in": "this batch", **_facts_of_batch(recs, i)} for i in sorted(namesakes)] + \
                            [{"id": h["id"], "in": "archive", "caption": h["caption"], "schema": h["schema"],
                              **_facts(root, h["id"])} for h in hits]
                    ambiguous.append({"record": rid, "field": p, "value": v, "candidates": cands})
                    links.append({"record": rid, "field": p, "value": v, "links_to": f"{len(cands)} records: ambiguous"})
                    warnings.append(f"{rid}.{p}: '{v}' names {len(cands)} records; give the one you mean by its id "
                                    "(see ambiguous_links), or review will ask")
                    out_vals.append(v)
                elif namesakes:
                    target = next(iter(namesakes))
                    links.append({"record": rid, "field": p, "value": v, "links_to": f"this batch: {target}"})
                    wrong_kind(v, batch_schema.get(target))
                    out_vals.append(target if link_by == "id" else v)
                elif hits:
                    h = hits[0]
                    links.append({"record": rid, "field": p, "value": v, "links_to": f"{h['caption']} ({h['id']})"})
                    wrong_kind(v, h.get("schema"))
                    if h["schema"] in schema.SCHEMA and "sources" in schema.resolve(h["schema"])["props"]:
                        cite.setdefault(h["id"], h)                # an existing entity this text names: cite it
                    out_vals.append(h["id"] if link_by == "id" else v)
                else:
                    links.append({"record": rid, "field": p, "value": v, "links_to": None})
                    warnings.append(f"{rid}.{p}: '{v}' is no record in this batch or the archive; it stays "
                                    "a name until a record for it exists (`hydra-ctl stubs` lists these)")
                    out_vals.append(v)
            props[p] = out_vals
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
        # words a vocabulary covers (a status, a capacity): one it does not list is kept, but nothing acts on it
        for p, vals in props.items():
            for v in vals:
                if vocab.outside(vocabs, sname, p, v):
                    name, voc = vocab.lookup(vocabs, sname, p)
                    warnings.append(f"{rid}.{p}: '{v}' is not a {name} word hydra knows ({', '.join(voc['values'])}); "
                                    f"it is shown as typed and nothing acts on it. Use one of those when the source "
                                    f"supports it, or leave `{p}` out; the owner may add the word to {layout.VOCABULARIES}")
        # coded values (ISO country, currency, language): a code the standard lacks is never named
        for p, vals in props.items():
            kind = std.kind_of(sname, p, (pdefs.get(p) or {}).get("type"))
            for v in vals if kind else ():
                if std.valid(kind, v) is False:
                    warnings.append(f"{rid}.{p}: '{v}' is no ISO {kind} code; write the code (country 'sa', currency "
                                    f"'SAR', language 'ara'), not a name or a symbol")
        # upstream: H pins and keys. A key the archive already holds makes this record that entity
        for v in props.get("upstream") or []:
            from hydra.universe import hid
            if not hkeys.parse(v) and hid.pin_key(v) is None:
                errors.append(f"{rid}.upstream: '{v}' is neither an H (H-p0-...) nor a key (namespace:key, "
                              "e.g. wikidata:Q57340 or acme:EMP-0042)")
        for k in sorted(hkeys.of_record(keyconf, props)):
            row = keyed.get(k)
            if row:
                keyed_out.append({"record": rid, "key": k, "entity": row.get("title"), "h": row["h"]})
                warnings.append(f"{rid}: key {k} already belongs to {row.get('title')} ({row['h']}); this record "
                                "will be that entity. If it is not, the key is wrong: correct it or leave it out")
            elif k.split(":", 1)[0] not in keyconf["namespaces"]:
                warnings.append(f"{rid}: key namespace '{k.split(':', 1)[0]}' is not declared in {layout.KEYS}; it "
                                "merges all the same. Check the spelling (a misspelt namespace merges nothing)")
        # sources: every kept source a record cites exists; every note is in its sources, word for word
        texts = [batch_text] if batch_text else []
        for sid in list(props.get("sources") or []) + list((r.get("_meta") or {}).get("cites") or []):
            if sid in batch_ids:
                continue
            if sid not in kept_text:
                kept_text[sid] = src.text_of(root, sid)
            if kept_text[sid] is None:
                try:
                    _existing_source(root, sid)
                except IngestError:
                    errors.append(f"{rid}.sources: '{sid}' is no source in the archive (fetch_source keeps a web "
                                  "page as one; save with source.file keeps a file)")
            else:
                texts.append(kept_text[sid])
        for n in props.get("notes") or []:
            if not texts:
                warnings.append(f"{rid}.notes: no source text to check this note against; give the batch a source "
                                "or cite a kept source in `sources`")
                break
            if not src.verbatim(n, texts):
                errors.append(f"{rid}.notes: '{n[:90]}' is not in the record's sources word for word. Notes are "
                              "printed as the source's quote: copy the sentence exactly (read_source with `find` "
                              "locates it), or leave `notes` out")
        # an entity that may already be in the archive: review will propose the merge
        same = [h for h in existing.get(types.norm_text(props["name"][0]), []) if h["schema"] == sname] \
            if not edge and props.get("name") else []
        if same:                          # its exact name and type: perhaps the same entity, citing this text
            h = _h_of(root, same[0]["id"])
            cited.append({"record": rid, "name": props["name"][0], "existing": same[0]["caption"],
                          "existing_id": same[0]["id"], **({"h": h} if h else {})})
            if h and not props.get("upstream"):
                warnings.append(f"{rid}: '{props['name'][0]}' has the name and type of an entity already here "
                                f"({same[0]['id']}, {h}). A name is no proof: if it is that entity, add "
                                f"\"upstream\": [\"{h}\"]; if not, leave it and review will ask")
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
            "links": links, "ambiguous_links": ambiguous, "roles": roles, "possible_duplicates": duplicates,
            "existing_entities_cited": cited, "will_also_cite": auto, "keyed": keyed_out,
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
        out += [{**r, "collection": f.stem} for r in _load_records(f)]
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
    doc = {"id": mint.document_id(props["contentHash"][0] if props.get("contentHash")
                                  else hashlib.sha1(props["bodyText"][0].encode("utf-8")).hexdigest()),
           "schema": "Article" if source.get("url") else "Document", "properties": props}
    return doc, path, notes


def _existing_source(root: Path, sid: str) -> dict:
    want = str(sid).strip()
    for r in _source_entries(root):
        if want in (r["id"], r["id"].split(":", 1)[-1]) or want.split(":", 1)[-1] == r["id"]:
            return r
    raise IngestError(f"no source '{sid}' in the archive (`hydra-ctl sources` lists them)")


AGENT = "agent:hydra-mcp"           # who history says made a change through these tools


def _publish_pinned(root: Path, recs: list[dict]) -> int:
    """An `upstream` pin is a promise that the H holds: a computed H pinned becomes published."""
    from hydra.universe import review
    return review.publish_pinned(root, recs, by=AGENT)


def ingest(root: Path, records: list[dict], source: dict, collection: str | None = None,
           replace: bool = False, rebuild: bool = True, link_by: str = "id") -> dict:
    """Check the batch; if it has no errors, write it as a new collection citing its
    source (a file, a text, or an earlier source by id), then rebuild and report
    what changed. Refuses an existing collection unless `replace`."""
    source = source or {}
    per_record = not (source.get("id") or source.get("file") or source.get("text"))   # each record cites its own
    old_src = _existing_source(root, source["id"]) if source.get("id") else None
    stem = (Path(str(source["file"])).stem if source.get("file") else
            old_src["collection"] if old_src else str(source.get("title") or ("batch" if per_record else "text")))
    collection = collection or f"{_slug(str(source.get('title') or stem))}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    if not VALID_NAME.match(collection):
        raise IngestError(f"'{collection}' cannot name a collection (letters, digits, - and _)")
    report = check_records(root, records, collection if replace else None, link_by=link_by,
                           source=None if per_record else source)
    if per_record and report["ok"]:
        bare = [r["id"] for r in report["records"] if "sources" in schema.resolve(r["schema"])["props"]
                and not r["properties"].get("sources")]
        if bare:
            report["ok"] = False
            report["errors"].append(f"no `source` for the batch, and {len(bare)} records cite none of their own "
                                    f"({', '.join(bare[:5])}): give `source`, or `sources` on each record")
    if not report["ok"]:
        return {"saved": False, "errors": report["errors"], "warnings": report["warnings"],
                **({"ambiguous_links": report["ambiguous_links"]} if report["ambiguous_links"] else {})}
    cfile = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    sfile = root / layout.SOURCE_ENTRIES / f"{collection}.json"
    if (cfile.exists() or (sfile.exists() and not old_src)) and not replace:
        raise IngestError(f"collection '{collection}' exists; pass replace=true or another name")
    storable(report["records"])
    if per_record:
        doc, fpath, notes, sid = None, None, [], None
    elif old_src:
        doc, fpath, notes, sid = None, None, [], old_src["id"]
    else:
        doc, fpath, notes = _new_source(root, collection, source)
        sid = doc["id"]
    # an existing entity the text names gets a record citing it, pinned to that entity's H (so it
    # is that entity, not a namesake): hydra-mcp made it from the entity, so the identity is certain
    pins = {a["existing_id"]: _h_of(root, a["existing_id"]) for a in report["will_also_cite"]}
    extra = normalize([{"schema": a["schema"], "properties": {"name": [a["name"]],
                                                              **({"upstream": [pins[a["existing_id"]]]}
                                                                 if pins[a["existing_id"]] else {})}}
                       for a in report["will_also_cite"]],
                      set(_ids_in(root, skip=collection if replace else None)) | {r["id"] for r in report["records"]})
    _publish_pinned(root, [*report["records"], *extra])
    cites = lambda r: "sources" in schema.resolve(r["schema"])["props"]
    recs = [{**r, "properties": {**r["properties"],
                                 "sources": list(dict.fromkeys((r["properties"].get("sources") or []) + [sid]))}}
            if cites(r) and sid else r for r in report["records"] + extra]
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
                "issues": [i for i in summary.get("issues") or [] if i.get("file") in set(rel)
                           or i.get("code", "").startswith("facts.")],
                "ambiguous_links": report["ambiguous_links"]})
    snap = history.auto(root, f"hydra-mcp save: {collection} ({len(recs)} records)", who=AGENT)
    if snap:
        out["snapshot"] = snap
        out["undo"] = f"history restore {snap[:12]}~1 (or: {out['undo']})"
    return out
