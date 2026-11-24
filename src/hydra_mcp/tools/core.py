"""tools/core.py — the `core` tool set, always on: guides, tasks, reading files and sources, checking, saving and
amending records, looking entities up, the schema, collections, and switching tool sets and tools on and off.

`check_records` and `amend_records` are hydra.api operations too (`hydra.api.records`), but stay hand-written here:
the operations' spec and results differ from these tools' (see hydra-docs plans/imports.md §7, M1)."""
from __future__ import annotations

from hydra.schema import vocab
from hydra.identity import types

from hydra_mcp import (agent, config, core, data, guidelines, names, outline, profile, recipes, sources as src_mod,
                       toolsets as toolsets_mod, workflows as wf)
from hydra_mcp.app import _run, mcp, resource, tool


@tool()
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


@tool()
def read_file(path: str, part: int | None = None, offset: int | None = None, whole: bool = False,
              archive: str | None = None) -> dict:
    """The text of a file (.txt, .md, .html, .pdf, .docx), read exactly as it will be stored as evidence. `path` is
    the file's full path. A short file comes back whole. A long one first comes back as its profile (pages, OCR
    noise, redactions, headings, front and back matter, warnings) and its parts, with no text: read them one at a
    time with `part=n`. `offset` reads from that character instead (`next_offset` continues). Says whether the
    archive already holds this file. Extract from this text."""
    def go():
        try:
            root, real = core.archive_or_defaults(archive)
        except core.IngestError:
            root, real = None, False
        return core.read_file(root if real else None, path, offset, part, whole)
    return _run(go)


@tool()
def source_profile(path: str, archive: str | None = None) -> dict:
    """A file measured once, no text: pages, characters, words per page, text layer, OCR noise, redaction marks,
    headings, numbered paragraphs, front and back matter, links, and its parts for `read_file(part=n)`, with
    warnings. Kept by the file's content, so asking again is free."""
    def go():
        return profile.profile(core.resolve_file(None, path))
    return _run(go)


@tool()
def source_outline(path: str, archive: str | None = None) -> dict:
    """A document's parts and their pages, without reading it: headings with level, character offset in the text
    hydra keeps and page, from a PDF's bookmarks (not scan batches), Word heading styles, Markdown or HTML headings,
    else the heading lines in the text (contents pages left out). `path` is the file's full path. Plan the parts to
    read from it."""
    def go():
        return outline.outline(core.resolve_file(None, path))
    return _run(go)


@tool()
def source_names(path: str, from_page: int | None = None, to_page: int | None = None, min_count: int = 1,
                 archive: str | None = None) -> dict:
    """The capitalised names of two words or more in a document (pages `from_page`..`to_page` of a PDF, else all),
    with how often each comes and `in_archive`: the entries already carrying that exact name or alias. A list to
    check that a part's names were all recorded or dropped, never a list to record: a name is no proof."""
    def go():
        lookup = None
        try:
            root, real = core.archive_or_defaults(archive)
        except core.IngestError:
            root, real = None, False
        if real:
            have = core._existing_names(root)
            lookup = lambda n: [{"id": h["id"], "caption": h["caption"], "schema": h["schema"]}  # noqa: E731
                                for h in have.get(types.norm_text(n), [])][:5]
        return names.source_names(core.resolve_file(None, path), from_page, to_page, max(1, min_count), lookup)
    return _run(go)


@tool()
def recipe(name: str | None = None, args: dict | None = None, archive: str | None = None, timeout: int = 120) -> dict:
    """Run one of the Archive Workflow's read-only command-line recipes by name and get its JSON. No `name`
    lists them with their `args`. intake {doc}: hash, pages, text layer, outline. outline {doc, headings}: the
    parts with pages. names {doc, from, to, min}: capitalised names with counts, to look up with find_entities.
    findquote {doc, quotes}: the PDF pages each quote is on, for cite's pdfPages; pages [] means not in the text word for word.
    table {doc, from, to}: a laid-out PDF table as tab-separated rows. tsv2records {tsv, schema, source}: a table
    to records for check_records. audit {check} on `archive`: fix lists (unsourced, nonotes, undated, open,
    status, samename, dangling, names, summary, fill). `doc` is a full path. Nothing is written; the recipe stops
    after `timeout` seconds (at most 600). Names and pages it finds are leads: quotes still come from read_file
    or read_source."""
    return _run(recipes.run, name, args, archive, timeout)


@tool()
def find_entities(query: str | None = None, schema: str | None = None, archive: str | None = None, limit: int = 10,
                  name: str | None = None) -> dict:
    """Entities already in the archive closest to a name (`query`; `name` is accepted for it), best first, each with what
    tells it apart from its namesakes (`facts`: dates, nationality, posts; `links`:
    parents and relationships), its canonical id `h` and the `keys` it holds. A query
    that is a key (`wikidata:Q57340`) returns the one entity holding it. Use it for
    every entity before saving: if one is the same entity as yours, add `"upstream":
    [its h]` to your record; if none is, write the record without one. One document:
    `{count, entities: [...]}`."""
    def go():
        q = query if query not in (None, "") else name
        if q in (None, ""):
            raise core.IngestError("give `query`, the name or key to look for (`name` is accepted for it)")
        root, real = core.archive_or_defaults(archive)
        if not real or not core._built(root):
            return {"count": 0, "entities": []}
        found = agent.find_entities(root, q, schema or "", limit=limit)
        return {"count": len(found), "entities": found}
    return _run(go)


@tool()
def explain_entity(entity: str, archive: str | None = None) -> dict:
    """Where every value of one entity came from (`entity`: its H, a record id, or a title only one entry
    has; a shared title is refused with the candidate Hs, never guessed; a record id that is a
    relationship answers with the record and the `collection` it lives in): each
    property's values with the records, collections and documents behind them, its
    canonical id, and the review questions it takes part in. Use it before proposing
    an answer or an `upstream` pin."""
    return _run(lambda: agent.explain_entity(core.open_archive(archive), entity))


@tool()
def amend_records(collection: str, records: list[dict] | None = None, remove: list[str] | None = None,
                  confirm: bool = False, details: bool = False, archive: str | None = None) -> dict:
    """Correct a saved collection: each record with an `id` already in it replaces
    that record whole (give every property it should keep; its evidence stays
    cited); a record with a new or no id is added; `remove` drops records by id.
    Only the records you change are checked, as `save` checks; what is wrong with
    the others in the collection is one summary line, never a block. Without `confirm`
    it previews (per changed record, each property now and new) and writes nothing;
    call again with confirm=true once the person agrees. Unknown arguments are
    refused. `details`: every warning and ambiguous link instead of a short list.
    The result says how to undo it."""
    return _run(lambda: agent.amend_records(core.open_archive(archive), collection, records, remove, "id", confirm, details))


@tool()
def preview(records: list[dict], archive: str | None = None) -> dict:
    """What saving a batch would change, built aside, writing nothing: the entities it
    adds, the merges it would make, the questions it would raise, and links that
    would stay names. Use it on a large or uncertain batch before `save`."""
    return _run(lambda: agent.preview(core.open_archive(archive), records))


@tool()
def describe_schema(schema: str | None = None, archive: str | None = None) -> dict:
    """The entity types and relationships records can use. With no `schema`, lists
    them (a relationship shows its two end fields). With one ("Person", "Employment"),
    lists every property it accepts: its type (string, date, entity...), which are
    required, and for a link the kind of entity it takes. Check a type here before
    writing records of it, and again to double-check a record you wrote. For themes,
    the fields worth filling in and Wikidata codes, use `properties`."""
    def go():
        core.archive_or_defaults(archive)
        return core.describe_schema(schema)
    return _run(go)


@tool()
def properties(schema: str | None = None, theme: str | None = None, level: str = "common", query: str | None = None,
               code: str | None = None, archive: str | None = None) -> dict:
    """The fields of a type, grouped in themes (Geography, Names, Dates, Person, Organization, Money, Online,
    Identifiers, Links, Other), each with its Wikidata code. `schema` ("Person"): the fields to fill in
    (`level="common"`) or every one (`"all"`), `theme` to narrow, and the links the type can take. `query` ("birth
    date"): fields of every schema that match, and the Wikidata properties that match the words. `code` ("P569"):
    that property's entry and the fields of this archive that map to it. Wikidata matches come from the catalogue
    on this machine; without one they say so, and the person runs `hydra-ctl wikidata properties --fetch`."""
    def go():
        root, _ = core.archive_or_defaults(archive)
        return core.properties(root, schema, theme, level, query, code)
    return _run(go)


@tool()
def extra_fields(archive: str | None = None) -> dict:
    """The fields records carry that FtM does not have (kept in `_meta.extra` when a save finds one, or a key
    like `P1449`): each with its type, how many records hold it, its Wikidata code if marked, and the closest
    Wikidata properties. Assign them with `field_assign`."""
    return _run(lambda: core.extra_fields(core.open_archive(archive)))


@tool()
def field_assign(field: str, schema: str, to: str, wd: str | None = None, confirm: bool = False,
                 archive: str | None = None) -> dict:
    """Move an extra field's values on, for the records of `schema` that hold `field`. `to` is `Schema.prop` (an
    FtM field; refused when a value does not fit its type), `new:<name>` (a property of this archive's own, in
    .hydra/schema/extensions/archive.yaml; needs `wd`, the Wikidata code P…) or `drop` (the values are listed, then
    removed). Without `confirm` it previews and writes nothing; call again with confirm=true once the person
    agrees. One history step; the result says how to undo it."""
    return _run(lambda: core.field_assign(core.open_archive(archive), field, schema, to, wd, confirm))


@tool()
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


@tool()
def vocabularies(archive: str | None = None) -> dict:
    """The words a status or capacity field takes in this archive, and what hydra does
    with each: {name: {applies_to: ["Interest.status", ...], values: {word: {label, why,
    ended, caveat, beneficiary}}}}. `ended` means the record counts as over, `caveat`
    that it is flagged wherever the fact is shown. A word not listed is kept as typed,
    but nothing acts on it."""
    def go():
        root, _ = core.archive_or_defaults(archive)
        return {"file": str(vocab.path(root)), "vocabularies": vocab.load(root)}
    return _run(go)


@tool()
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


@tool()
def read_source(source: str, offset: int = 0, find: list[str] | None = None, archive: str | None = None) -> dict:
    """A kept source's text (by its id, from `fetch_source` or `save`), in parts from
    `offset` (for a kept PDF with `page_ranges`: each page's start and end in the text); or, with `find` (words), every sentence containing one of them: the
    sentences to quote in `notes`."""
    def go():
        return src_mod.read(core.open_archive(archive), source, offset, find)
    return _run(go)


@tool()
def sources(query: str | None = None, uncited_only: bool = False, archive: str | None = None,
            offset: int = 0, limit: int = 100, uncited_entities: bool = False) -> dict:
    """List every kept source (`doc-...` ID, title, URL, filename, `has_text`, citations)
    plus `uncited_sources` and `uncited_entities_count`; the first 50 entities that cite no source
    are listed as `uncited_entities` only with `uncited_entities=true`. Works across all sources (web and
    local files), unlike `source_report` which lists only Wikipedia-backed citations. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: src_mod.list_sources(core.open_archive(archive), query, uncited_only, offset, limit,
                                          uncited_entities))


@tool()
def cite(citations: list[dict] | None = None, confirm: bool = False, archive: str | None = None,
         sources: list[dict] | None = None) -> dict:
    """Say where in a kept source a saved record's facts are: a list of {record, source, pages?, pdfPages?, locator?, quote?}. `record` is a record id (as `get_records` shows it); `source` the source document's id; `pages` the number printed on the document ("14", "I-16"); `pdfPages` the page of the PDF file ("20"); a scan's two differ (PDF p. 20 prints "1"); give either or both; `locator` anything else that finds it; `quote` the words, exactly as the source has them (gives `pdfPages`, and `pages` too when readable). A row with only record and source removes that citation. `sources` says what a kept source is: a list of {source, title?, author?, publisher?, published?, url?, summary?, language?, keywords?, duration?, pictured?, call_number?}. Without `confirm` it shows the rows resolved and any problem; call again with confirm=true to write them. More: guide("sources", "cite")"""
    return _run(lambda: agent.cite(core.open_archive(archive), citations, confirm, sources))


@tool()
def get_records(collection: str | None = None, name: str | None = None, offset: int = 0, limit: int = 50,
                archive: str | None = None, query: str | None = None, ids: list[str] | None = None) -> dict:
    """Read back what the archive holds. With no `collection`, lists the collections.
    With one (e.g. the one `save` returned), gives each saved record with the type of
    every property, what each link resolves to after the build (null: still just a
    name), and the save checks repeated on the records returned. `query` narrows to
    records whose id or any value contains it (`name` is the same, older); `ids` to
    those record ids. Paged: `offset`, `limit` (50 by default, 200 at most; `next_offset`
    starts the next page); only the page is checked, so a large collection is quick."""
    def go():
        root = core.open_archive(archive)
        return core.get_records(root, collection, name, max(0, offset), max(1, min(limit, 200)), query, ids)
    return _run(go)


@tool()
def save(records: list[dict], source: dict | None = None, collection: str | None = None,
         archive: str | None = None, replace: bool = False, mode: str = "new") -> dict:
    """Check and save records as a new collection, with their evidence, then rebuild. `records`: [{"schema": "Person", "properties": {"name": ["..."]}}, ...]. `source`: {"file": full path}, {"text": "..."} or {"id": "..."} (evidence already saved), with "title", "url", "publisher", "author", "published" when known; a batch from several sources leaves `source` out and cites `"sources": ["doc-..."]` on each record. A record with `"upstream": [an h from find_entities]` is that entity. If anything breaks the modelling rules, nothing is saved and `errors` says what to fix. `mode="add"` appends to an existing `collection`; `mode="new"` (default) makes one, or with `replace=true` replaces one. More: guide("fields", "save")"""
    return _run(lambda: core.ingest(core.open_archive(archive), records, source or {}, collection, replace,
                                    mode=mode))


@tool()
def create_archive(path: str, name: str | None = None, prefix: str | None = None, confirm: bool = False) -> dict:
    """Start a new, empty hydra archive in a new or empty folder (full path, chosen
    by the person). `prefix` is the id prefix every collection uses (default: one
    made from the name; "none" gives each collection its own). Without confirm it
    only shows what it would create; call again with confirm=true once the person
    agrees. Then pass the folder as `archive`."""
    return _run(lambda: core.create_archive(path, name, prefix, confirm))


@resource("hydra://guide/{topic}")
def guide_resource(topic: str) -> str:
    """A hydra guide topic in Markdown (`start`, `rules`, `tasks`, ...)."""
    return wf.guide(topic)["content"]


@resource("hydra://guide/{group}/{name}")
def guide_nested_resource(group: str, name: str) -> str:
    """A nested hydra guide in Markdown (`workflow/<name>` or `views/<name>`)."""
    return wf.guide(f"{group}/{name}")["content"]



@tool()
def guide(topic: str | None = None, section: str | None = None, archive: str | None = None) -> dict:
    """Read the hydra guide: with no `topic`, the list of topics; `guide("start")` first in every session.
    A `topic` returns that guide (`rules`, `sources`, `identity`, `fields`, `tasks`, `views`, `views/org`,
    `workflow/enrich`...); `section` returns one `##` part of it (by its number, letter or words), to keep
    what you load small. A task's checkout lists the guides it needs."""
    return _run(lambda: wf.guide(topic, section, archive))


@tool()
def workflows(archive: str | None = None) -> dict:
    """List the workflows a task can start from, with when to use each. Read one in full with
    `guide("workflow/<name>")`: every step's tool, what to do, when it is done and when to stop."""
    def go():
        try:
            root = core.open_archive(archive)
        except core.IngestError:
            root = None
        return wf.workflows_list(root)
    return _run(go)


@tool()
def tasks(status: str | None = None, workflow: str | None = None, collection: str | None = None,
          archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """List the archive's tasks (status `open`, `checked-out`, `blocked` or `done`) with steps done of
    total, and `current_task`, the one this session has checked out. A checked-out task shows its `holder`,
    how long it has been `idle` and whether it is `stale` (a stale one can be taken without `force`). Pick an
    open task, or ask the person before making a new one with `task_new`. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: wf.list_tasks(core.open_archive(archive), status, workflow, collection, offset, limit))


@tool()
def task_new(title: str, workflow: str | list[str] | None = None, collection: str | None = None,
             views: list[str] | dict | None = None, subjects: list[str] | None = None,
             authorized: list[str] | None = None, confirm: bool = False, archive: str | None = None,
             context: str | None = None) -> dict:
    """Make a task: a checklist from a `workflow` (a list is a route: the workflows in order, each step code
    prefixed with its position; left out, the context's route, or `enrich`). `context` (see `contexts`)
    is chosen here or later with `context_checkout`, before the first step is ticked. `views` (org, links, radial, map,
    timeline, panel; a map of view to true/false is read as the views set true) add each view's steps; left out, the collection's switched-on views are used.
    `subjects` names the entities to research (one block of steps each; more with `task_add`).
    `authorized` lists tools the person lets you confirm without asking each time (for example
    ["site", "save"]). Previews unless confirm=true: show the person the preview first."""
    return _run(lambda: wf.task_new(core.open_archive(archive), title, workflow, collection, views, subjects,
                                    confirm, authorized, context))


@tool()
def contexts(task: str | None = None, words: str = "", archive: str | None = None) -> dict:
    """List the contexts a task can work in (the brief that says what to keep and what to drop), as
    `{contexts: [...]}`. With a `task` id (or `words` describing the work) they are ranked, best first, each
    with a `score` and `why`; without, every context with `use_when`. Read one in full with
    `guide("context/<name>")`; set it with `context_checkout`."""
    return _run(lambda: wf.contexts_list(core.open_archive(archive), task, words))


@tool()
def context_checkout(id: str, name: str, reason: str, confirm: bool = False,
                     archive: str | None = None) -> dict:
    """Set the context of task `id` to `name`, with a `reason`. Previews unless confirm=true: show the person
    the preview (the context's keep and drop, route and charts) first; with `general` when working unattended.
    Fixed after the task's first write: for another context, start a new task."""
    return _run(lambda: wf.context_checkout(core.open_archive(archive), id, name, reason, confirm))


@tool()
def task_checkout(id: str, holder: str | None = None, force: bool = False,
                  archive: str | None = None, reason: str = "", details: bool = False,
                  model: str | None = None, client: str | None = None) -> dict:
    """Take a task for this session before working on it. Returns its steps, `next_step` (with the tool
    to call, what to do, when it is done, when to stop), `guides_to_load`, `authorized`, and the archive's
    details. From now on every write you make is logged on the task. `holder`: your name (optional).
    A task held by someone else is refused, with who holds it and how long it has been idle; one idle
    past `tasks.stale_after` (default 2 h) is taken over without `force`. `force=true` only when it was
    yours in an earlier session or the person says so, with `reason` saying which. The archive details
    give the count of files newer than the build; `details=true` lists them. `model` and `client`: your
    model and client names, kept on the task. With a context, `brief` holds its text (or points to
    `guide("context/<name>")`); without one, `needs_context` lists the contexts to choose from."""
    def go():
        root = core.open_archive(archive)
        out = wf.task_checkout(root, id, holder, force, reason, details, model, client)
        on = toolsets_mod.enable_for_task(mcp, root, out)
        if on:
            out["toolsets_enabled"] = on
        return out
    return _run(go)


@tool()
def task(id: str | None = None, archive: str | None = None) -> dict:
    """Show a task as it stands: every step with its status and result, `next_step` with its
    instructions, the sources kept for it (`uncited_sources`: kept but cited by no record yet), claims and
    the last log lines. `id` defaults to this session's task."""
    return _run(lambda: wf.task_show(core.open_archive(archive), id))


@tool()
def task_step(step: str, status: str = "done", result: str = "", reason: str = "",
              claim: str | None = None, evidence: list[str] | None = None,
              subject: str | None = None, id: str | None = None, archive: str | None = None,
              exit: str | None = None) -> dict:
    """Tick one step of your checked-out task, right after doing it. `step`: its code (`B4`; `Asir/B4`
    when several subjects have one). `status`: `done` (give `result`: what you found, with counts and
    ids), `blocked` or `skipped` (give `reason`), or `open` to undo. A step with a check runs it: while
    the check finds problems the step stays open, unless `reason` says why each finding is expected.
    `evidence`: ids that back the result (`doc-...`, record ids, Hs); each must exist. `exit`: how the step
    ended, `<kind>:<value>` with kind `skip`, `resume`, `goto`, `fail` or `use` (`skip:no-key`); recorded, not acted on.
    A task with no context refuses the tick: set one with `context_checkout`."""
    return _run(lambda: wf.task_step(core.open_archive(archive), step, status, result, reason,
                                     claim, evidence, subject, id, True, exit))


@tool()
def task_add(subject: str | None = None, step: str | None = None, block: str | None = None,
             code: str | None = None, id: str | None = None, archive: str | None = None) -> dict:
    """Add to your task: `subject` adds another block of the workflow's per-subject steps; or `code` +
    `step` (its text) adds one step to the block whose title contains `block` (default: the last)."""
    return _run(lambda: wf.task_add(core.open_archive(archive), subject, step, block, code, id))


@tool()
def task_verify(id: str | None = None, archive: str | None = None) -> dict:
    """Check a task before closing it: open steps, claims, sources kept vs cited, what changed since
    checkout, and each of its views' checks. `ready_to_close` is true when no step is open."""
    return _run(lambda: wf.task_verify(core.open_archive(archive), id))


@tool()
def task_release(id: str | None = None, force: bool = False, archive: str | None = None) -> dict:
    """Hand a task back unfinished (it becomes `open`, its steps and log kept) so another session can take
    it. Tick or block the step you were on first."""
    return _run(lambda: wf.task_release(core.open_archive(archive), id, force))


@tool()
def task_close(status: str = "done", summary: str = "", id: str | None = None,
               force: bool = False, archive: str | None = None) -> dict:
    """Finish your task: `done` (refused while a step is open) or `blocked` (with a `summary` of what the
    person must decide). Snapshots the archive, tags `task/<id>/done`, and returns `task_verify`'s report.
    `history_diff` from `task/<id>/start` to `task/<id>/done` shows everything the task changed."""
    return _run(lambda: wf.task_close(core.open_archive(archive), status, summary, id, force))


@tool()
def collections(archive: str | None = None) -> dict:
    """List the collections: id, title (the name readers see), id prefix, record count, and which views each is prepared for (`views`, with its handles in `view_specs`)."""
    return _run(lambda: wf.collections(core.open_archive(archive)))


@tool()
def details(archive: str | None = None) -> dict:
    """One-call overview of the archive: records, types, collections, the tree's roots, open questions."""
    return _run(lambda: wf.details(core.open_archive(archive)))


@tool()
def check(archive: str | None = None) -> dict:
    """Problems in the archive's files without building (rules files, records, sources), by level."""
    return _run(lambda: wf.check(core.open_archive(archive)))


@tool(name="collection_create")
def collection_create_tool(name: str, title: str | None = None, confirm: bool = False, archive: str | None = None) -> dict:
    """Make a new, empty collection `name` (letters, digits, - and _), with an optional display `title`. Its id
    prefix is pinned with it, so its record ids never change later. Previews unless confirm=true; one history step.
    Add records with `save` or `move_records`. Errors come back as {error, why, do}."""
    return _run(lambda: data.collection_create(core.open_archive(archive), name, title, confirm))


@tool()
def paths(a: str, b: str, max_hops: int = 4, edges: list[str] | None = None, archive: str | None = None) -> dict:
    """How two entries are connected: the chains of links from `a` to `b` of at most `max_hops` links (1 to 6),
    shortest first, up to 20, each with its entries and, per step, every link between that pair (type, label,
    dates, record id). `edges`: only these relationship types. Read-only. Says so when nothing joins them.
    Errors come back as {error, why, do}."""
    return _run(lambda: data.paths(core.open_archive(archive), a, b, max_hops, edges))


@tool()
def toolsets(archive: str | None = None) -> dict:
    """The tool sets and whether each is on, with the tools in it: `core` is always on; `enrich`, `geo`, `shape`
    and `admin` are switched on with `toolset_enable`. Use it when a tool you need is not in your list."""
    return _run(lambda: toolsets_mod.status(mcp))


@tool()
def toolset_enable(name: str, archive: str | None = None) -> dict:
    """Switch a tool set on (`enrich`, `geo`, `shape`, `admin`, or `all`) and tell the client its tool list changed.
    Returns `added` (the tools now available) and the sets that are on. A task's checkout already switches on the
    sets its route needs. A set the person has locked in mcp.yaml is refused."""
    def go():
        name_ = name.strip().lower()
        try:
            config.check_locked(name_, core.open_archive(archive) if archive else None)
        except config.ConfigError as e:
            return {"error": "locked", "why": str(e)}
        added = toolsets_mod.enable(mcp, name_)
        return {"enabled": name, "added": added,
                "on": [s["name"] for s in toolsets_mod.status(mcp)["toolsets"] if s["on"]]}
    return _run(go)


def _change(action: str, name: str, archive: str | None) -> dict:
    try:
        return toolsets_mod.change(mcp, action, name, archive)
    except config.ConfigError as e:
        return {"error": "refused", "why": str(e)}


@tool()
def toolset_disable(name: str, archive: str | None = None) -> dict:
    """Switch a tool set off (`enrich`, `geo`, `shape`, `admin`; never `core`). Saves the choice in mcp.yaml (the
    machine-wide file, or the archive's when `archive` is given) and tells the client its tool list changed. Returns
    the resolved sets and tools. Same as `hydra-mcp config off <set>` from a shell."""
    return _run(lambda: _change("off", name, archive))


@tool()
def tool_on(name: str, archive: str | None = None) -> dict:
    """Switch one tool on (or a set, by its name) and save it in mcp.yaml (machine-wide, or the archive's when
    `archive` is given); the client's tool list changes. A name the person has locked is refused. Same as
    `hydra-mcp config on <tool>`."""
    return _run(lambda: _change("on", name, archive))


@tool()
def tool_off(name: str, archive: str | None = None) -> dict:
    """Switch one tool off (or a set, by its name) and save it in mcp.yaml (machine-wide, or the archive's when
    `archive` is given); the client's tool list changes. `guide`, `tasks`, `task`, `task_checkout`, `task_step`,
    `toolsets`, `toolset_enable`, `toolset_disable`, `tool_on` and `tool_off` can never be off. Same as
    `hydra-mcp config off <tool>`."""
    return _run(lambda: _change("off", name, archive))

