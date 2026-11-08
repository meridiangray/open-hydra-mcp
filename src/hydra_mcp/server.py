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

from hydra_mcp import agent, core, guidelines, pipeline

mcp = FastMCP("hydra", instructions=(
    "Turn files into records for a hydra archive. 1) Call `labelling_guidelines` and follow it exactly: it "
    "is how records must be modelled so hydra reads them correctly. 2) `read_file` the file, or `fetch_source` a "
    "web page (kept as a source records cite by id; never quote a browsing tool's summary). 3) Write one "
    "record per entity and per stated relationship as hydra JSON; use `describe_schema` to confirm the "
    "properties and types of each schema you use, and `find_entities` for every entity: when one it returns is "
    "the same entity (its dates, parents and posts agree), give your record `upstream: [its h]`; a name alone "
    "is never proof, and hydra merges only on proof. When the file gives an id another system assigned (a "
    "Wikidata QID, an LEI, the archive's own key), add it to `upstream` as `namespace:key` (`keys` lists the "
    "namespaces): records holding one key are one entity. 4) `check_records` as a dry run, fixing every error and "
    "answering each `ambiguous_links` entry with the id you mean. 5) `save` the records with source "
    "{\"file\": path}: the file is kept as the evidence every entity cites; links that name one record are "
    "written as its id. If save returns errors, fix them and save again. 6) `get_records` with the saved "
    "collection to read the entities back and confirm each property, type and link is what the file states. "
    "7) `open_questions` lists what the build asks a person (same names, ambiguous links, placements): "
    "explain each with `explain_entity`, propose an answer, and `answer` with confirm=true only once the "
    "person agrees. 8) `read_page` each new entry to confirm every fact reached its section; `wiki_serve` shows the result (it builds the pages and restarts the wiki, and `ok` says "
    "it serves this build); `wiki_readiness` and `stubs` say what the pages still lack; `publish` makes the "
    "ids of finished pages permanent, with the person's agreement. `amend_records` corrects a saved record; `history_log` shows every change and "
    "`history_restore` undoes one. Only record what the file states. If no archive is selected, ask the "
    "person for one or offer `create_archive`."))


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
    """Entities already in the archive closest to a name, best first, each with what
    tells it apart from its namesakes (`facts`: dates, nationality, posts; `links`:
    parents and relationships), its canonical id `h` and the `keys` it holds. A query
    that is a key (`wikidata:Q57340`) returns the one entity holding it. Use it for
    every entity before saving: if one is the same entity as yours, add `"upstream":
    [its h]` to your record; if none is, write the record without one."""
    def go():
        root, real = core.archive_or_defaults(archive)
        if not real or not core._built(root):
            return []
        return agent.find_entities(root, query, schema or "", limit=limit)
    return _run(go)


@mcp.tool()
def explain_entity(entity: str, archive: str | None = None) -> dict:
    """Where every value of one entity came from (`entity`: its id, or a name): each
    property's values with the records, collections and documents behind them, its
    canonical id, and the review questions it takes part in. Use it before proposing
    an answer or an `upstream` pin."""
    return _run(lambda: agent.explain_entity(core.open_archive(archive), entity))


@mcp.tool()
def open_questions(kind: str | None = None, offset: int = 0, limit: int = 30, archive: str | None = None) -> dict:
    """What the last build asks a person to decide: `merges` (are these one entity?),
    `references` (which record does this name mean?), `placements`, `stale`
    decisions, `contradictions`, and problems with `verdicts`. Each question has an
    `id` and its possible answers. Propose an answer to the person; `answer` it only
    with their agreement."""
    return _run(lambda: agent.open_questions(core.open_archive(archive), kind, max(0, offset), max(1, min(limit, 100))))


@mcp.tool()
def answer(id: str, choice: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Answer one open question (`id` from `open_questions`): `confirm` or `reject` a
    merge or placement, a candidate's number, a record id or `none` for a
    reference, a name for a caption (`cap-<id>`), or `clear` to take an answer back.
    Without `confirm` it only shows what it would write; call again with
    confirm=true once the person agrees. Then the archive is rebuilt."""
    return _run(lambda: agent.answer(core.open_archive(archive), id, choice, confirm))


@mcp.tool()
def amend_records(collection: str, records: list[dict] | None = None, remove: list[str] | None = None,
                  archive: str | None = None) -> dict:
    """Correct a saved collection: each record with an `id` already in it replaces
    that record whole (give every property it should keep; its evidence stays
    cited); a record with a new or no id is added; `remove` drops records by id.
    Checked as `save` checks; nothing is written if there are errors. The result
    says how to undo it."""
    return _run(lambda: agent.amend_records(core.open_archive(archive), collection, records, remove))


@mcp.tool()
def preview(records: list[dict], archive: str | None = None) -> dict:
    """What saving a batch would change, built aside, writing nothing: the entities it
    adds, the merges it would make, the questions it would raise, and links that
    would stay names. Use it on a large or uncertain batch before `save`."""
    return _run(lambda: agent.preview(core.open_archive(archive), records))


@mcp.tool()
def pin_upstream(collection: str, record: str, h: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Pin a saved record to an entity's canonical id `h` (from `find_entities`): the
    record is that entity from now on. `h` may also be a key (`wikidata:Q57340`,
    `acme:EMP-0042`): the record then holds that key, and every record holding it is
    one entity. Without `confirm` it shows what it would pin (and which entity the key
    already belongs to); call again with confirm=true once the person agrees."""
    return _run(lambda: agent.pin_upstream(core.open_archive(archive), collection, record, h, confirm))


@mcp.tool()
def set_positions(positions: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Write this archive's rank ladder (.hydra/rules/positions.yaml): {name: {below:
    [the positions above it], titles: [the role words that mean it], outside: false}}.
    The preview says how many of the archive's roles each position ranks and which
    roles none takes. Call again with confirm=true once the person agrees."""
    return _run(lambda: agent.set_positions(core.open_archive(archive), positions, confirm))


@mcp.tool()
def link_images(images: list[dict], confirm: bool = False, archive: str | None = None) -> dict:
    """`link_image` for many images at once: [{image, kind, name, schema, ...}, ...].
    Previews unless confirm=true."""
    return _run(lambda: agent.link_images(core.open_archive(archive), images, confirm))


@mcp.tool()
def wiki_readiness(archive: str | None = None) -> list[dict]:
    """What keeps the archive's wiki pages from being complete, each as something to
    record or decide: terms with no years, names that link to no record, links that
    name several records, same-name pairs, facts only in notes, people with no dates,
    unsourced pages, facts that contradict each other. Each finding has examples and
    a `do`. Use it to plan what to record next; propose, then save."""
    def go():
        from hydra.universe import build as ubuild, layer
        from hydra.wiki import readiness
        root = core.open_archive(archive)
        if not layer.is_universe(root):
            raise core.IngestError("this archive has no universe layer: `hydra-ctl universe init` adds one")
        if not ubuild.pages_current(root):
            ubuild.build(root)
        return readiness.check(root)
    return _run(go)


@mcp.tool()
def history_log(limit: int = 20, archive: str | None = None) -> list[dict]:
    """The archive's snapshots, newest first: who changed what (every save, answer and
    amend made here is one, by agent:hydra-mcp)."""
    return _run(lambda: agent.history_log(core.open_archive(archive), max(1, min(limit, 200))))


@mcp.tool()
def history_diff(a: str = "HEAD", b: str | None = None, archive: str | None = None) -> list[dict]:
    """What changed between two snapshots (`b` left out: the files as they are now):
    each file, and inside a collection the records added, removed and changed."""
    return _run(lambda: agent.history_diff(core.open_archive(archive), a, b))


@mcp.tool()
def history_restore(ref: str, paths: list[str] | None = None, confirm: bool = False,
                    archive: str | None = None) -> dict:
    """Put the archive's files (or just `paths`) back as they were at snapshot `ref`
    (an id, or HEAD~1 for one change back). Nothing is lost: the restore is a new
    snapshot. Previews unless confirm=true."""
    return _run(lambda: agent.history_restore(core.open_archive(archive), ref, paths, confirm))


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
def universe_build(archive: str | None = None) -> dict:
    """Build the universe from the last archive build: which records are one entity, each
    entity's canonical id (H) and the wiki pages. `save` and `amend_records` rebuild the
    archive, not the pages: run this (or `wiki_serve`, which runs it when the pages are
    stale) to see the change. Returns the counts by state and flag, same-name pairs, merges
    a decision blocked, and warnings."""
    return _run(lambda: pipeline.universe_build(core.open_archive(archive)))


@mcp.tool()
def publish(hs: list[str] | None = None, collections: list[str] | None = None, confirm: bool = False,
            archive: str | None = None) -> dict:
    """Make computed Hs published, so their ids and page addresses hold from now on: `hs`
    (Hs, bodies or record ids), or every computed H whose records all come from
    `collections` (entities that also draw on other collections are listed, not
    published). Without `confirm` it shows what it would publish; call again with
    confirm=true once the person agrees."""
    return _run(lambda: pipeline.publish(core.open_archive(archive), hs, collections, confirm))


@mcp.tool()
def scope(entity: str | None = None, archive: str | None = None) -> dict:
    """What the archive is about (.hydra/rules/scope.yaml): how many entries are in scope, the
    context ones (kept in the data, named as text on the pages that mention them, listed
    nowhere), and for `entity` (an H, key, record id or title) whether it is in scope and why
    ("Ownership from <a seed entity>")."""
    return _run(lambda: pipeline.scope(core.open_archive(archive), entity))


@mcp.tool()
def set_scope(include: list[str] | None = None, exclude: list[str] | None = None, seeds: list[str] | None = None,
              confirm: bool = False, archive: str | None = None) -> dict:
    """Change what the archive is about: add entries to `include` or `exclude` (Hs, keys, record
    ids, titles, or `collection:<name>`), or set the seed collections. The preview lists what
    would come into scope and what would leave it; confirm=true (with the person's agreement)
    writes scope.yaml and rebuilds the pages."""
    return _run(lambda: pipeline.set_scope(core.open_archive(archive), include, exclude, seeds, confirm))


@mcp.tool()
def stubs(archive: str | None = None) -> dict:
    """Names that links hold but no record has (the wiki's red links): how many links name
    each, from which fields, and what kind of entity they fit; and those already
    graduated. Write a record for a stub when the source gives its facts."""
    return _run(lambda: pipeline.stubs(core.open_archive(archive)))


@mcp.tool()
def graduate_stub(name: str, as_schema: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Make a stub (see `stubs`) a bare entity every link naming it points at, as
    `as_schema` (default: what its links fit). Previews unless confirm=true; prefer a real
    record when the source has the entity's facts."""
    return _run(lambda: pipeline.graduate(core.open_archive(archive), name, as_schema, confirm))


@mcp.tool()
def wiki_serve(port: int = 8080, theme: str | None = None, replace_other: bool = False, archive: str | None = None) -> dict:
    """Show the archive as a wiki at http://127.0.0.1:<port>/, current: builds the pages when
    they are older than their inputs, stops the wiki this tool started on that port, starts
    a new one and checks it serves as many entries as the build made pages (`ok`). The wiki
    reads its pages once, at start, so call this after every change that should show.
    Refuses when another server holds the port; `replace_other=true` stops it (ask first)."""
    return _run(lambda: pipeline.wiki_serve(core.open_archive(archive), port, theme, replace_other))


@mcp.tool()
def wiki_stop(port: int = 8080) -> dict:
    """Stop the wiki this tool started on `port`. Servers it did not start are left alone."""
    return _run(lambda: pipeline.wiki_stop(port))


@mcp.tool()
def keys(archive: str | None = None) -> dict:
    """The key namespaces of this archive (.hydra/rules/keys.yaml): for each, its label,
    link, the FtM property holding the same key, whether an entity may hold only one
    (`unique`); `primary`, the namespaces an entity is keyed by first (its H comes from
    that key); and how many entities hold a key of each namespace, undeclared ones
    listed. Write a key in a record's `upstream` as `namespace:key`."""
    def go():
        root, _ = core.archive_or_defaults(archive)
        return agent.keys_in_use(root)
    return _run(go)


@mcp.tool()
def vocabularies(archive: str | None = None) -> dict:
    """The words a status or capacity field takes in this archive, and what hydra does
    with each: {name: {applies_to: ["Interest.status", ...], values: {word: {label, why,
    ended, caveat, beneficiary}}}}. `ended` means the record counts as over, `caveat`
    that it is flagged wherever the fact is shown. A word not listed is kept as typed,
    but nothing acts on it."""
    def go():
        from hydra import vocab
        root, _ = core.archive_or_defaults(archive)
        return {"file": str(vocab.path(root)), "vocabularies": vocab.load(root)}
    return _run(go)


@mcp.tool()
def check_records(records: list[dict], collection: str | None = None, source: dict | None = None,
                  archive: str | None = None) -> dict:
    """Dry run of `save`: checks proposed records and writes nothing. Returns `errors`
    (they would block a save), `warnings`, how each link resolves (this batch, the
    archive, or a bare name), the position each role ranks as, and possible
    duplicates. It also refuses a link to the wrong kind of entity (an estate in an
    Event's `involved`) and a note that is not, word for word, in the record's
    sources: give `source` as you will to `save`, and/or cite kept sources on the
    records (`"sources": ["doc-..."]`). Use it to fix a batch before saving."""
    def go():
        root, real = core.archive_or_defaults(archive)
        rep = core.check_records(root, records, collection, source=source)
        return rep if real else {**rep, "note": core.DEFAULTS_NOTE}
    return _run(go)


@mcp.tool()
def fetch_source(url: str, title: str | None = None, published: str | None = None, author: str | None = None,
                 archive: str | None = None) -> dict:
    """Fetch a web page and keep its text in the archive as a source of its own (an
    Article), so records can cite it: `"sources": ["<source_id>"]`, with their
    `notes` quoting it word for word. Wikipedia pages are read from their raw text
    (redirects followed; the infobox kept as `field: value` lines); other pages as
    the text of their body. Nothing is summarized. `url` in the result is the one to
    cite. Returns the first part of the text; `read_source` gives the rest, or the
    sentences with given words. A page that refuses the fetch stays out: ask the
    person to save it and use `read_file`."""
    def go():
        from hydra_mcp import sources
        return sources.fetch(core.open_archive(archive), url, title, published, author)
    return _run(go)


@mcp.tool()
def read_source(source: str, offset: int = 0, find: list[str] | None = None, archive: str | None = None) -> dict:
    """A kept source's text (by its id, from `fetch_source` or `save`), in parts from
    `offset`; or, with `find` (words), every sentence containing one of them: the
    sentences to quote in `notes`."""
    def go():
        from hydra_mcp import sources
        return sources.read(core.open_archive(archive), source, offset, find)
    return _run(go)


@mcp.tool()
def source_report(top: int = 25, archive: str | None = None) -> dict:
    """Where the archive's facts come from: citations counted by origin (the site a URL
    belongs to), the W-factor (of the citations that cite anything, the share resting on
    Wikipedia alone) for the archive and each collection, how many cite nothing, and the
    entries that rest most on Wikipedia, each with the records to re-source (record,
    collection, Wikipedia URL, the quote). Work down that list with
    `wikipedia_footnotes`, `fetch_source` and `swap_source`."""
    def go():
        from hydra import provenance
        root = core.open_archive(archive)
        pipeline._universe(root)
        return provenance.report(root, top=max(1, min(top, 200)))
    return _run(go)


@mcp.tool()
def wikipedia_footnotes(url: str, quote: str) -> dict:
    """What Wikipedia itself cites for a sentence: given the article `url` a record cites
    and the `quote` it took from it, the references attached to that sentence (url, title,
    publisher, date). Those are the sources to fetch, read and cite instead; the fact must
    then be quoted in their own words."""
    def go():
        from hydra_mcp import sources
        return sources.footnotes(url, quote)
    return _run(go)


@mcp.tool()
def swap_source(collection: str, record: str, source: str, quote: str, confirm: bool = False,
                archive: str | None = None) -> dict:
    """Re-source a saved record: its Wikipedia citation out, the kept source `source` (from
    `fetch_source`) in, with `quote` (word for word in that source, checked) as its note.
    Wikipedia URLs and the notes quoting the Wikipedia article go; other notes stay.
    Without `confirm` it shows the record before and after; call again with confirm=true
    once the person agrees."""
    return _run(lambda: agent.swap_source(core.open_archive(archive), collection, record, source, quote, confirm))


@mcp.tool()
def read_page(entity: str, archive: str | None = None) -> dict:
    """An entry's wiki page as a reader sees it (by H, key, record id or title):
    whether it is in scope, the infobox rows, the lead, every section's text in order,
    and the footnotes [n] resolved to the record, collection, source and quote behind
    each. Use it after a batch to confirm each fact reached the section it should
    (an owner in Owners, a price in Deals, a key in Identifiers)."""
    return _run(lambda: pipeline.read_page(core.open_archive(archive), entity))


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
def save(records: list[dict], source: dict | None = None, collection: str | None = None,
         archive: str | None = None, replace: bool = False) -> dict:
    """Check and save records as a new collection, with their evidence, then rebuild.
    `records`: [{"schema": "Person", "properties": {"name": ["..."]}}, ...] (an
    "id" is optional). `source`: {"file": its full path} for a file, which is kept
    as the evidence; or {"text": "..."} for pasted text; or {"id": "..."} for more
    records from evidence already saved. Add "title", "url", "publisher",
    "author", "published" (a date) when known. Every entity cites the evidence.
    A batch drawn from several sources leaves `source` out and cites, on each
    record, the kept sources it rests on (`"sources": ["doc-..."]`, from
    `fetch_source`); every note is checked against those sources' text.
    A link written as a name that names exactly one record is saved as its id;
    one that names several is kept and listed in `ambiguous_links`. A record with
    `"upstream": [an h from find_entities]` is that entity (and the H is published).
    If anything breaks the modelling rules, nothing is saved and `errors` says
    what to fix. The result names its history snapshot and how to undo it."""
    return _run(lambda: core.ingest(core.open_archive(archive), records, source or {}, collection, replace))


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
