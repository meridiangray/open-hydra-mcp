"""hydra-mcp: files in, hydra records out.

The connected model reads a file (or pasted text), writes the facts as hydra's
FollowTheMoney JSON following the labelling guidelines, and saves them: the
records as a collection, the file as the evidence every entity cites. Run it with
`hydra-mcp` (stdio). The archive is the `archive` argument of each tool, else
$HYDRA_ARCHIVE, else hydra-ctl's active archive.
"""
from __future__ import annotations

import contextlib
import sys

from mcp.server.fastmcp import FastMCP

from hydra_mcp import core, guidelines

mcp = FastMCP("hydra", instructions=(
    "Turn files into records for a hydra archive. 1) Call `labelling_guidelines` and follow it exactly: it "
    "is how records must be modelled so hydra reads them correctly. 2) `read_file` the file. 3) Write one "
    "record per entity and per stated relationship as hydra JSON; use `describe_schema` to confirm the "
    "properties and types of each schema you use, and `find_entities` to reuse the exact name of anyone "
    "already in the archive. 4) `check_records` as a dry run, fixing every error. 5) `save` the records with "
    "source {\"file\": path}: the file is kept as the evidence every entity cites. If save returns errors, fix "
    "them and save again. 6) `get_records` with the saved collection to read the entities back and confirm "
    "each property, type and link is what the file states. Only record what the file states. If no archive "
    "is selected, ask the person for one or offer `create_archive`."))


def _run(fn, *args, **kw):
    try:
        with contextlib.redirect_stdout(sys.stderr):    # stdout carries the MCP messages: a stray print would break them
            return fn(*args, **kw)
    except core.IngestError as e:
        raise ValueError(str(e)) from None


@mcp.tool()
def labelling_guidelines(archive: str | None = None) -> str:
    """How to model records so hydra reads them correctly: the record format, one
    record per entity, which field each end of a relationship goes in, roles in
    the source's words, Family's direction, organizations inside organizations,
    offices, dates, and this archive's relationship fields and position ladder.
    Read it before writing records, and follow it."""
    def go():
        root, real = core.archive_or_defaults(archive)
        guide = guidelines.render(root)
        return guide if real else f"> {core.DEFAULTS_NOTE}\n\n{guide}"
    return _run(go)


@mcp.tool()
def read_file(path: str, offset: int = 0, archive: str | None = None) -> dict:
    """The text of a file (.txt, .md, .html, .pdf, .docx), read exactly as it will
    be stored as evidence. `path` is the file's full path.
    Long texts come in parts: call again with offset=next_offset. Says whether
    the archive already holds this file. Extract from this text."""
    def go():
        try:
            root, real = core.archive_or_defaults(archive)
        except core.IngestError:
            root, real = None, False
        return core.read_file(root if real else None, path, offset)
    return _run(go)


@mcp.tool()
def find_entities(query: str, schema: str | None = None, archive: str | None = None, limit: int = 10) -> list[dict]:
    """Entities already in the archive closest to a name, best first. Use it for
    every entity before saving: if it exists, write its record with exactly the
    existing name and type, so hydra treats it as the same entity."""
    def go():
        root, real = core.archive_or_defaults(archive)
        if not real or not core._built(root):
            return []
        from hydra.cli import node
        return node.find(root, query, schema or "", limit=limit)
    return _run(go)


@mcp.tool()
def describe_schema(schema: str | None = None, archive: str | None = None) -> dict:
    """The entity types and relationships records can use. With no `schema`, lists
    them (a relationship shows its two end fields). With one ("Person", "Employment"),
    lists every property it accepts: its type (string, date, entity...), which are
    required, and for a link the kind of entity it takes. Check a type here before
    writing records of it, and again to double-check a record you wrote."""
    def go():
        core.archive_or_defaults(archive)
        return core.describe_schema(schema)
    return _run(go)


@mcp.tool()
def check_records(records: list[dict], collection: str | None = None, archive: str | None = None) -> dict:
    """Dry run of `save`: checks proposed records and writes nothing. Returns `errors`
    (they would block a save), `warnings`, how each link resolves (this batch, the
    archive, or a bare name), the position each role ranks as, and possible
    duplicates. Use it to fix a batch before saving."""
    def go():
        root, real = core.archive_or_defaults(archive)
        rep = core.check_records(root, records, collection)
        return rep if real else {**rep, "note": core.DEFAULTS_NOTE}
    return _run(go)


@mcp.tool()
def get_records(collection: str | None = None, name: str | None = None, offset: int = 0, limit: int = 50,
                archive: str | None = None) -> dict:
    """Read back what the archive holds. With no `collection`, lists the collections.
    With one (e.g. the one `save` returned), gives each saved record with the type of
    every property, what each link resolves to after the build (null: still just a
    name), and the save checks repeated on what was written. Use it after `save` to
    verify your work; `name` narrows to records mentioning it."""
    def go():
        root = core.open_archive(archive)
        return core.get_records(root, collection, name, max(0, offset), max(1, min(limit, 200)))
    return _run(go)


@mcp.tool()
def save(records: list[dict], source: dict, collection: str | None = None,
         archive: str | None = None, replace: bool = False) -> dict:
    """Check and save records as a new collection, with their evidence, then rebuild.
    `records`: [{"schema": "Person", "properties": {"name": ["..."]}}, ...] (an
    "id" is optional). `source`: {"file": its full path} for a file, which is kept
    as the evidence; or {"text": "..."} for pasted text; or {"id": "..."} for more
    records from evidence already saved. Add "title", "url", "publisher",
    "author", "published" (a date) when known. Every entity cites the evidence.
    If anything breaks the modelling rules, nothing is saved and `errors` says
    what to fix. The result says how to undo it."""
    return _run(lambda: core.ingest(core.open_archive(archive), records, source, collection, replace))


@mcp.tool()
def link_image(image: str, kind: str, schema: str | None = None, position: str | None = None,
               titled: str | None = None, name: str | None = None, confirm: bool = False,
               archive: str | None = None) -> dict:
    """Give entities an image or icon through a rule in hints.yaml (records never carry
    images). `image`: a local file (full path) or one already in .hydra/resources/.
    `kind`: "portrait", "thumb" (an icon) or "logo". Say which entities with `schema`
    (a type and its subtypes), `position`, `titled` (a title contains this regular
    expression) and/or `name`, all of which must hold. Without `confirm` it only
    previews; call again with confirm=true once the person approves."""
    return _run(lambda: core.link_image(core.open_archive(archive), image, kind,
                                        {"schema": schema, "position": position, "titled": titled, "name": name},
                                        confirm))


@mcp.tool()
def create_archive(path: str, name: str | None = None, prefix: str | None = None, confirm: bool = False) -> dict:
    """Start a new, empty hydra archive in a new or empty folder (full path, chosen
    by the person). `prefix` is the id prefix every collection uses (default: one
    made from the name; "none" gives each collection its own). Without confirm it
    only shows what it would create; call again with confirm=true once the person
    agrees. Then pass the folder as `archive`."""
    return _run(lambda: core.create_archive(path, name, prefix, confirm))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
