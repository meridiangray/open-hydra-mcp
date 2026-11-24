"""tools/enrich.py — the `enrich` tool set: fetching and re-sourcing, Wikipedia's footnotes, Suggestions and
enrichers (hydra_mcp.suggestions), images, stubs, upstream pins, the review questions and their answers, and an
entry's neighbours in the graph."""
from __future__ import annotations

from hydra.sources import provenance
from hydra.archive import layout, writelock

from hydra_mcp import agent, core, data, pipeline, sources as src_mod, suggestions as sug, workflows as wf
from hydra_mcp.app import _run, tool


@tool()
def open_questions(kind: str | None = None, offset: int = 0, limit: int = 30, archive: str | None = None) -> dict:
    """What the last build asks a person to decide: `merges` (are these one entity?),
    `references` (which record does this name mean?), `placements`, `stale`
    decisions, `contradictions`, and problems with `verdicts`. Each question has an
    `id` and its possible answers. Propose an answer to the person; `answer` it only
    with their agreement."""
    return _run(lambda: agent.open_questions(core.open_archive(archive), kind, max(0, offset), max(1, min(limit, 100))))


@tool()
def open_ends(entity: str | None = None, collection: str | None = None, archive: str | None = None) -> dict:
    """The posts, jobs and memberships (Occupancy, Employment, Membership) with a start and no end date, so a
    position is not held open-ended: each with its candidates for where it stopped (the holder's death, the next
    holder's start in the same post, a dated event involving the holder, another post of theirs that ended, a
    later date in the text) and the sources they come from. `entity` narrows to one entry (its name or H body), `collection` to one collection.
    Propose one to the person, then `answer` the item's `id` with a candidate's `choice`, `holds` or `unknown`
    (confirm=true once they agree). The end is a judgement kept with its evidence, shown as inferred."""
    return _run(lambda: agent.open_ends(core.open_archive(archive), entity, collection))


@tool()
def answer(id: str, choice: str, confirm: bool = False, archive: str | None = None,
           quote: str | None = None, source: str | None = None) -> dict:
    """Answer one open question (`id` from `open_questions`): `confirm` or `reject` a
    merge or placement, a candidate's number, a record id or `none` for a
    reference, a name for a caption (`cap-<id>`), `holds`, `unknown` or `<date>@<kind>:<id>` for an
    open end (`open_ends` lists them), or `clear` to take an answer back.
    Without `confirm` it only shows what it would write; call again with
    confirm=true once the person agrees. Then the archive is rebuilt. `quote` (the words, exactly as read)
    and `source` (the document id) are kept with the answer as its evidence, and `decisions` shows them: give
    both for an open end."""
    return _run(lambda: agent.answer(core.open_archive(archive), id, choice, confirm, quote, source))


@tool()
def decisions(kind: str | None = None, archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """The answers already given, as the wiki's Review page lists them: each one's `id`, the
    question it answered, the answer, and `gone` when the records it was about have changed so
    the build no longer asks it. `kind` narrows to merge, place, ref, cap, stub or other. To
    take one back, `answer` its id with `clear`, with the person's agreement. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: agent.decisions(core.open_archive(archive), kind, offset, limit))


@tool()
def pin_upstream(collection: str, record: str, h: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Pin a saved record to an entity's canonical id `h` (from `find_entities`): the
    record is that entity from now on. `h` may also be a key (`wikidata:Q57340`,
    `acme:EMP-0042`): the record then holds that key, and every record holding it is
    one entity. Without `confirm` it shows what it would pin (and which entity the key
    already belongs to); call again with confirm=true once the person agrees."""
    return _run(lambda: agent.pin_upstream(core.open_archive(archive), collection, record, h, confirm))


@tool()
def link_images(images: list[dict], confirm: bool = False, archive: str | None = None) -> dict:
    """`link_image` for many images at once: [{image, kind, entity | name, schema, ..., credit: {author, licence, url}}, ...].
    Previews unless confirm=true; one history step for all."""
    return _run(lambda: agent.link_images(core.open_archive(archive), images, confirm))


@tool()
def stubs(archive: str | None = None) -> dict:
    """Names that links hold but no record has (the wiki's red links): how many links name
    each, from which fields, and what kind of entity they fit; and those already
    graduated. Write a record for a stub when the source gives its facts."""
    return _run(lambda: pipeline.stubs(core.open_archive(archive)))


@tool()
def graduate_stub(name: str, as_schema: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Make a stub (see `stubs`) a bare entity every link naming it points at, as
    `as_schema` (default: what its links fit). Previews unless confirm=true; prefer a real
    record when the source has the entity's facts."""
    return _run(lambda: pipeline.graduate(core.open_archive(archive), name, as_schema, confirm))


@tool()
def fetch_source(url: str, title: str | None = None, published: str | None = None, author: str | None = None,
                 publisher: str | None = None, summary: str | None = None, language: str | None = None,
                 keywords: list[str] | None = None, archive: str | None = None,
                 keep: bool = False) -> dict:
    """Fetch a web page and keep its text in the archive as a source of its own, so records can cite it: `"sources": ["<source_id>"]`, with their `notes` quoting it word for word. Nothing is summarized. Returns the first part of the text; `read_source` gives the rest. Fill what the page states and leave out what it does not: `title`, `author`, `publisher`, `published`, `language`, `keywords`, and `summary` (your own short account, never a quote). A page that looks useless comes back with `quality: "thin"` and is NOT kept unless you pass `keep=true`. A page that refuses the fetch stays out: ask the person to save it and use `read_file`. A page kept by mistake: `drop_source`. More: guide("sources", "fetch_source")"""
    def go():
        root = core.open_archive(archive)
        got = src_mod.page(url)                              # the network first, outside the write lock
        with writelock.hold(root, wf._holder(root)):
            return src_mod.fetch(root, url, title, published, author, publisher, summary,
                                 language, keywords, prefetched=got, keep_thin=keep)
    return _run(go)


@tool()
def drop_source(source: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a kept source (`source`: its `doc-...` id) that no record cites, such as a page
    fetched by mistake: its entry and its stored file go and the archive is rebuilt. A source a
    record cites is refused, with the records listed; re-source those first. Previews unless
    confirm=true; call again once the person agrees."""
    return _run(lambda: src_mod.drop(core.open_archive(archive), source, confirm))


@tool()
def source_report(top: int = 25, archive: str | None = None) -> dict:
    """Where the archive's facts come from: citations counted by origin (the site a URL
    belongs to), the W-factor (of the citations that cite anything, the share resting on
    Wikipedia alone) for the archive and each collection, how many cite nothing, and the
    entries that rest most on Wikipedia, each with the records to re-source (record,
    collection, Wikipedia URL, the quote). Work down that list with
    `wikipedia_footnotes`, `fetch_source` and `swap_source`."""
    def go():
        root = core.open_archive(archive)
        pipeline._universe(root)
        if not (root / layout.UNIVERSE_PARSED / "pages.jsonl").is_file():     # never a silent zero (stability audit F6)
            raise core.IngestError("the universe has no pages to count citations on: universe_build, then call again")
        return provenance.report(root, top=max(1, min(top, 200)))
    return _run(go)


@tool()
def wikipedia_footnotes(url: str, quote: str, archive: str | None = None) -> dict:
    """What Wikipedia itself cites for a sentence: given the article `url` a record cites
    and the `quote` it took from it, the references attached to that sentence (url, title,
    publisher, date). Those are the sources to fetch, read and cite instead; the fact must
    then be quoted in their own words. `archive` is accepted for uniformity and not used."""
    def go():
        return src_mod.footnotes(url, quote)
    return _run(go)


@tool()
def swap_source(collection: str, record: str, source: str, quote: str, confirm: bool = False,
                archive: str | None = None) -> dict:
    """Re-source a saved record: its Wikipedia citation out, the kept source `source` (from
    `fetch_source`) in, with `quote` (word for word in that source, checked) as its note.
    Wikipedia URLs and the notes quoting the Wikipedia article go; other notes stay.
    Without `confirm` it shows the record before and after; call again with confirm=true
    once the person agrees."""
    return _run(lambda: agent.swap_source(core.open_archive(archive), collection, record, source, quote, confirm))


@tool()
def read_page(entity: str, archive: str | None = None) -> dict:
    """An entry's wiki page as a reader sees it (by H, key, record id or title):
    whether it is in scope, the infobox rows, the lead, every section's text in order,
    and the footnotes [n] resolved to the record, collection, source and quote behind
    each. Use it after a batch to confirm each fact reached the section it should
    (an owner in Owners, a price in Deals, a key in Identifiers)."""
    return _run(lambda: pipeline.read_page(core.open_archive(archive), entity))


@tool()
def link_image(image: str, kind: str, schema: str | None = None, position: str | None = None,
               titled: str | None = None, name: str | None = None, confirm: bool = False,
               archive: str | None = None, credit: dict | None = None, entity: str | None = None) -> dict:
    """Give entities an image or icon through a rule in hints.yaml (records never carry images). `image`: a local file (full path) or one already in .hydra/resources/. `kind`: "portrait", "thumb" (an icon) or "logo". Say which entities with `schema`, `position`, `titled` and/or `name` (all must hold), or `entity` (an H, a record id, or a title only one entry has) for that one entry. `credit` {author, licence, url} is shown under the picture: give it for any image that is not the archive's own. Without `confirm` it only previews; call again with confirm=true once the person approves. More: guide("views", "link_image")"""
    def go():
        root = core.open_archive(archive)
        match = ({"record": agent.records_of(root, entity)} if entity else
                 {"schema": schema, "position": position, "titled": titled, "name": name})
        return core.link_image(root, image, kind, match, confirm, credit)
    return _run(go)


@tool(name="suggestions")
def suggestions_tool(entity: str, archive: str | None = None) -> dict:
    """What could be done for one entry (by H, key, record id or title), from local data only, as the wiki's
    Suggestions drawer lists it. Graduate: Locate, Appoint, Affiliate, Identify, Classify (a value in the
    entry cast to a typed entity by a rule in casts.yaml, offered only when its lookup finds something).
    Enrich: Compare, Match, Lead, Portrait, Resource (probes declared in enrichers.yaml). Link: Merge, Resolve.
    Each has an `id`, a `tip`, a `preview` and `apply`: the existing tool that writes it (null when none does)."""
    return _run(lambda: sug.suggestions(core.open_archive(archive), entity))


@tool(name="cast")
def cast_tool(entity: str, rule: str, value: str, archive: str | None = None) -> dict:
    """One Graduate cast for a value (the entry's own, or one you give): the candidates the rule's lookups
    return (archive, universe, the local register), each with its source. Local data only; writes nothing."""
    return _run(lambda: sug.cast(core.open_archive(archive), entity, rule, value))


@tool(name="enrichers")
def enrichers_tool(archive: str | None = None) -> dict:
    """The enrichers this archive declares (.hydra/rules/enrichers.yaml): id, label, what an entry needs, source."""
    return _run(lambda: sug.enrichers(core.open_archive(archive)))


@tool(name="probe")
def probe_tool(entity: str, enricher: str, refresh: bool = False, query: str | None = None,
               archive: str | None = None, raw: bool = False) -> dict:
    """Run one enricher on one entry: ask its outside source (Wikidata, Wikipedia, Commons) once, keep the
    raw answer in .hydra/cache/probes/, and return it mapped onto fields (Compare: one row per field, what
    the entry has now and Wikidata's value). Match lists Wikidata candidates; `query` searches those words
    instead of the entry's name and context. Returns the mapped `rows` (field, now, new, reference), not the
    raw answer; `raw=true` adds it. Writes no records; `apply_suggestion` does."""
    return _run(lambda: sug.probe(core.open_archive(archive), entity, enricher, refresh, query, raw))


@tool(name="apply_suggestion")
def apply_tool(entity: str, id: str, picks: dict | None = None, confirm: bool = False,
               archive: str | None = None) -> dict:
    """Write one suggestion through the tool it names (site, answer, save, fetch_source, link_image, portrait_import (downloads the Commons file, credits it),
    swap_source, graduate_stub, pin_upstream). `picks`: {"candidate": n} for a cast, Resolve or Match (the
    Wikidata item to key the entry by), {"rows": [...]} to keep
    some rows of a Compare. Previews the call unless confirm=true; confirm only with the person's agreement."""
    return _run(lambda: sug.apply(core.open_archive(archive), entity, id, picks, confirm))


@tool(name="dismiss_suggestion")
def dismiss_tool(entity: str, id: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Record that a suggestion is not wanted (`sug-<body>.<id>: rejected` in verdicts.yaml), so it is not
    offered again. Previews unless confirm=true."""
    return _run(lambda: sug.dismiss(core.open_archive(archive), entity, id, confirm))


@tool(name="enrichments")
def enrichments_tool(entity: str, archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """What Enrich added to one entry (H, key, record id or title), from its ledger (.hydra/enrich/<H>.jsonl): per
    apply, the id, enricher (Compare, Lead, Portrait, Match, Footnotes), source (Wikidata item, file page, article
    revision), time, who, whether it is hidden, and exactly what it wrote (record values, records, files, rules,
    sections). Applies made before the ledger existed are not listed. Paged: `offset`, `limit`. Reads only."""
    return _run(lambda: sug.enrichments(core.open_archive(archive), entity, offset, limit))


@tool(name="enrichment_hide")
def enrichment_hide_tool(entity: str, id: str, hidden: bool = True, confirm: bool = False,
                         archive: str | None = None) -> dict:
    """Leave what one enrichment added off the entry's page, keeping the data (a verdict `hide-<H body>.<id>`
    in verdicts.yaml; `hidden=false` shows it again). `id` is from `enrichments`. Previews unless confirm=true."""
    return _run(lambda: sug.enrichment_hide(core.open_archive(archive), entity, id, hidden, confirm))


@tool(name="enrichment_delete")
def enrichment_delete_tool(entity: str, id: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove exactly what one enrichment wrote: its record values or records, image file with its credit and
    rule, article section. A value another enrichment also wrote stays. The preview lists each removal; confirming
    takes one history step (undo with `history_restore`). `id` is from `enrichments`."""
    return _run(lambda: sug.enrichment_delete(core.open_archive(archive), entity, id, confirm))


@tool(name="suggestions_reset")
def suggestions_reset_tool(entity: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Forget one entry's dismissed suggestions and kept probe answers, so every suggestion and enricher asks
    again. Writes nothing to records. Previews what would be forgotten unless confirm=true."""
    return _run(lambda: sug.suggestions_reset(core.open_archive(archive), entity, confirm))


@tool(name="wikidata_purge")
def wikidata_purge_tool(entity: str, forget_match: bool = True, confirm: bool = False,
                        archive: str | None = None) -> dict:
    """Start over from Wikidata: remove everything Wikidata added to one entry, whether or not the Enrich ledger
    lists it. Its records and claims in the `wikidata` collection (found by the entry's key and H, never by name),
    the values Compare and Match wrote, the source documents the import created when nothing else cites them,
    the `wikidata:Q...` key pin when `forget_match` (so Match is offered again), the Wikidata probe cache,
    dismissals, ledger lines and hides. Facts an own source states, a Commons portrait and a Wikipedia lead stay.
    The preview lists exactly what goes; confirming takes one history step (undo with `history_restore`)."""
    return _run(lambda: sug.wikidata_purge(core.open_archive(archive), entity, forget_match, confirm))


@tool()
def neighbors(entity: str, depth: int = 1, edges: list[str] | None = None, as_of: str | None = None,
              archive: str | None = None) -> dict:
    """The entries linked to `entity` (an H, key, record id or title) within `depth` links (1 to 4), from the same
    graph the Graph and Radial views draw. Direction is ignored in walking but every edge keeps it: {from, to,
    type, label, start, end, approx, record (the relationship record's id), member}. `edges`: only these
    relationship types (Membership, Ownership, Family...). `as_of` (a year, month or day): only links in force
    then (a link without dates always is). Read-only; at most 200 entries (`truncated` says so). Errors come
    back as {error, why, do}."""
    return _run(lambda: data.neighbors(core.open_archive(archive), entity, depth, edges, as_of))
