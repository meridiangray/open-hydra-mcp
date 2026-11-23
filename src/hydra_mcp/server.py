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

from hydra_mcp import agent, article, calllog, core, geo, guidelines, pipeline, sources as src_mod, toolsets as toolsets_mod, workflows as wf

mcp = FastMCP("hydra", instructions=(
    "Hydra turns sources into a reviewed archive and its wiki. Start every session with `guide(\"start\")` and "
    "follow it: it says how to pick or check out a task (`tasks`, `task_checkout`), which guides to load, and "
    "how to tick each step (`task_step`). Load only the guides your task lists. The rules that never bend: "
    "quote only text you read through `read_source` or `read_file`; record only what a kept source states; a "
    "name is never proof that two records are one entity; every tool with `confirm` previews first, and you "
    "confirm only after the person agrees (or the task's `authorized` list names that tool); work only in the "
    "archive the person gave you, passed as `archive` on every call. If no archive is given, ask, or offer "
    "`create_archive`."))


def _run(fn, *args, **kw):
    try:
        with contextlib.redirect_stdout(sys.stderr):    # stdout carries the MCP messages: a stray print would break them
            return fn(*args, **kw)
    except core.IngestError as e:
        err = ValueError(str(e))
        err.kind = e.kind                               # failure_payload maps the kind to {error, why, do}
        raise err from None
    except SystemExit as e:                             # a hydra command that refused: an Exception the tool layer reports
        err = ValueError(str(e.code).removeprefix("hydra: "))
        err.kind = "SystemExit"
        raise err from None


wf.install_write_lock(mcp)
calllog.install(mcp)


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


@mcp.tool()
def source_profile(path: str, archive: str | None = None) -> dict:
    """A file measured once, no text: pages, characters, words per page, text layer, OCR noise, redaction marks,
    headings, numbered paragraphs, front and back matter, links, and its parts for `read_file(part=n)`, with
    warnings. Kept by the file's content, so asking again is free."""
    def go():
        from hydra_mcp import profile
        return profile.profile(core.resolve_file(None, path))
    return _run(go)


@mcp.tool()
def source_outline(path: str, archive: str | None = None) -> dict:
    """A document's parts and their pages, without reading it: headings with level, character offset in the text
    hydra keeps and page, from a PDF's bookmarks (not scan batches), Word heading styles, Markdown or HTML headings,
    else the heading lines in the text (contents pages left out). `path` is the file's full path. Plan the parts to
    read from it."""
    def go():
        from hydra_mcp import outline
        return outline.outline(core.resolve_file(None, path))
    return _run(go)


@mcp.tool()
def source_names(path: str, from_page: int | None = None, to_page: int | None = None, min_count: int = 1,
                 archive: str | None = None) -> dict:
    """The capitalised names of two words or more in a document (pages `from_page`..`to_page` of a PDF, else all),
    with how often each comes and `in_archive`: the entries already carrying that exact name or alias. A list to
    check that a part's names were all recorded or dropped, never a list to record: a name is no proof."""
    def go():
        from hydra import types
        from hydra_mcp import names
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


@mcp.tool()
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
    from hydra_mcp import recipes
    return _run(recipes.run, name, args, archive, timeout)


@mcp.tool()
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


@mcp.tool()
def explain_entity(entity: str, archive: str | None = None) -> dict:
    """Where every value of one entity came from (`entity`: its H, a record id, or a title only one entry
    has; a shared title is refused with the candidate Hs, never guessed; a record id that is a
    relationship answers with the record and the `collection` it lives in): each
    property's values with the records, collections and documents behind them, its
    canonical id, and the review questions it takes part in. Use it before proposing
    an answer or an `upstream` pin."""
    return _run(lambda: agent.explain_entity(core.open_archive(archive), entity))


@mcp.tool()
def article_sections(entity: str, archive: str | None = None) -> dict:
    """An entity's article text (`entity`: its H, a record id, or a title only one entry has): its sections in order, each with
    `text` (Markdown), and, when imported, `from` (enwiki:Title@revision) and `licence`. An
    imported section is read-only until a person forks it in the wiki."""
    return _run(lambda: article.article_sections(core.open_archive(archive), entity))


@mcp.tool()
def set_article_section(entity: str, heading: str, text: str, from_: str | None = None, confirm: bool = False,
                        archive: str | None = None) -> dict:
    """Add a section to an entity's article, or replace the text of the section with this
    `heading`. `text` is plain Markdown (paragraphs, *emphasis*, [links](https://...), lists); cite
    a kept source in prose as `[^source-id p.23]`. Pass `from_` (enwiki:Title@revision) only for
    text copied from Wikipedia: it stays read-only and keeps its CC BY-SA 4.0 notice. Text a person
    wrote or forked is never replaced by an import. Without `confirm` it only previews; call
    again with confirm=true once the person agrees."""
    return _run(lambda: article.set_article_section(core.open_archive(archive), entity, heading, text, from_, confirm))


@mcp.tool()
def remove_article_section(entity: str, heading: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Take the section with this `heading` out of an entity's article (its own text or an imported one). Without
    `confirm` it shows what would go; call again with confirm=true once the person agrees. One history step."""
    return _run(lambda: article.remove_article_section(core.open_archive(archive), entity, heading, confirm))


@mcp.tool()
def move_article_section(entity: str, heading: str, to: int, confirm: bool = False, archive: str | None = None) -> dict:
    """Move the section with this `heading` to position `to` (1 is first) in an entity's article, and show the new
    order. Without `confirm` it only previews; call again with confirm=true once the person agrees. One history step."""
    return _run(lambda: article.move_article_section(core.open_archive(archive), entity, heading, to, confirm))


@mcp.tool()
def upgrade(confirm: bool = False, archive: str | None = None) -> dict:
    """Bring the archive up to date: an older format, or records still under an old schema name (Siting is now
    GeoLink). Without `confirm` it lists the changes; with it they are made as one history step and the archive is
    rebuilt. `check` says when an archive needs it."""
    from hydra_mcp import upkeep
    return _run(lambda: upkeep.upgrade(core.open_archive(archive), confirm))


@mcp.tool()
def layer_list(archive: str | None = None) -> dict:
    """The archive's map layers: GeoJSON drawn on the Atlas that is not entities (id, name, attribution, licence,
    feature count, bounding box)."""
    from hydra_mcp import upkeep
    return _run(lambda: upkeep.layer_list(core.open_archive(archive)))


@mcp.tool()
def layer_add(file: str, name: str, attribution: str = "", licence: str = "", confirm: bool = False,
              archive: str | None = None) -> dict:
    """Add a GeoJSON file (full path: a FeatureCollection, a Feature or a geometry) as a map layer on the Atlas: not
    entities, never in records. Data in Web Mercator or a WGS 84 UTM zone is converted to lon/lat; another projection
    is refused with its name (ask the person for lon/lat). Give where it comes from and its licence. Without `confirm`
    it shows how many features would be drawn and dropped; call again with confirm=true once the person agrees."""
    from hydra_mcp import upkeep
    return _run(lambda: upkeep.layer_add(core.open_archive(archive), file, name, attribution, licence, confirm))


@mcp.tool()
def layer_remove(layer: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a map layer by its id (layer_list). Without `confirm` it only previews. One history step."""
    from hydra_mcp import upkeep
    return _run(lambda: upkeep.layer_remove(core.open_archive(archive), layer, confirm))


@mcp.tool()
def open_questions(kind: str | None = None, offset: int = 0, limit: int = 30, archive: str | None = None) -> dict:
    """What the last build asks a person to decide: `merges` (are these one entity?),
    `references` (which record does this name mean?), `placements`, `stale`
    decisions, `contradictions`, and problems with `verdicts`. Each question has an
    `id` and its possible answers. Propose an answer to the person; `answer` it only
    with their agreement."""
    return _run(lambda: agent.open_questions(core.open_archive(archive), kind, max(0, offset), max(1, min(limit, 100))))


@mcp.tool()
def open_ends(entity: str | None = None, collection: str | None = None, archive: str | None = None) -> dict:
    """The posts, jobs and memberships (Occupancy, Employment, Membership) with a start and no end date, so a
    position is not held open-ended: each with its candidates for where it stopped (the holder's death, the next
    holder's start in the same post, a dated event involving the holder, another post of theirs that ended, a
    later date in the text) and the sources they come from. `entity` narrows to one entry (its name or H body), `collection` to one collection.
    Propose one to the person, then `answer` the item's `id` with a candidate's `choice`, `holds` or `unknown`
    (confirm=true once they agree). The end is a judgement kept with its evidence, shown as inferred."""
    return _run(lambda: agent.open_ends(core.open_archive(archive), entity, collection))


@mcp.tool()
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


@mcp.tool()
def decisions(kind: str | None = None, archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """The answers already given, as the wiki's Review page lists them: each one's `id`, the
    question it answered, the answer, and `gone` when the records it was about have changed so
    the build no longer asks it. `kind` narrows to merge, place, ref, cap, stub or other. To
    take one back, `answer` its id with `clear`, with the person's agreement. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: agent.decisions(core.open_archive(archive), kind, offset, limit))


@mcp.tool()
def symbology(archive: str | None = None) -> dict:
    """What the wiki draws with, as the Symbology page shows it: each entry type's icon and how
    many entries it marks, each badge rule's icon and reach, each position's picture rule, each
    link type's colour in the Radial and Org Chart, every image rule (hints.yaml) and what it
    reached, and the icon tokens there are to choose from."""
    return _run(lambda: agent.symbology(core.open_archive(archive)))


@mcp.tool()
def set_symbology(kind: str, key: str, value: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Change one thing the wiki draws with: `kind` is `type-icon` (an entry type, `key` its
    schema), `badge-icon` (a badge rule's key), `position-icon` (a position's name; writes a
    hints.yaml rule), `link-colour` (a link type, `value` #rrggbb) or `link-mark` (a link type: what
    the Timeline draws when it has a start and no end, `value` start, fades or runs). `value` is an icon token
    from `symbology`, or "" to put the default back. Without `confirm` it shows the current
    choice and the new one; call again with confirm=true once the person agrees. A wiki.yaml
    with comments is never rewritten: edit it by hand then."""
    return _run(lambda: agent.set_symbology(core.open_archive(archive), kind, key, value, confirm))


# ---- geo: where entities are -----------------------------------------------------------------------

@mcp.tool()
def geo_report(top: int = 25, include_entities: bool = False, archive: str | None = None) -> dict:
    """How much of the archive has a place, per entry type and finding count. With
    `include_entities=true`, also returns `country_only_entities`, `unplaced_entities`,
    and `place_reference_items` (`birthPlace`, `address`, `Event.location`, `registrationPort`)."""
    return _run(lambda: geo.geo_report(core.open_archive(archive), top, include_entities))


@mcp.tool()
def geo_locate(entity: str, as_of: str | None = None, archive: str | None = None) -> dict:
    """Where one entity is (by H, key such as wikidata:Q… or osm:way/…, record id or title): its primary
    places (`how`: chosen by a person, or inferred from geo.yaml's role order) with shape, centre, extent
    and area; every geo link (role, `via`: geolink, coordinates, address, country), its members (what sits
    under it), its reach (places it is linked to by ownership, office...), and the places that contain
    it. `as_of` ("2000", "2000-06") keeps only the geo links and reach that held then."""
    return _run(lambda: geo.geo_locate(core.open_archive(archive), entity, as_of))


@mcp.tool()
def geo_aspects(entity: str, archive: str | None = None) -> dict:
    """The places of one entry (H, key, record id or title), one per aspect the Atlas card shows: `home` (whose
    post it is), `posting` (the host country), `seat` (the building), `jurisdiction` (a region, then a district),
    or a person's born, residence, died. Each aspect says its `state` (filled, derived from the entry's country,
    or empty), `fills` (the place, its register `key`, `level`, the geo link `record`, whether it is `primary`) and,
    for an empty one, `candidates` the register offers (from the entry's title, at most three, a region before a
    district). Then assign one aspect at a time the way the person does in the Atlas: `site` with `role` and
    `{"register": key}` (a new place the person clicks is `{"point": [lon, lat]}`, never a box), `edit_geolink`
    to change or remove one, `set_primary` to choose the main place. Names are matched on this machine only."""
    return _run(lambda: geo.geo_aspects(core.open_archive(archive), entity))


@mcp.tool()
def geo_query(within: dict | list | None = None, near: dict | None = None, containing: dict | list | None = None,
              schema: str | None = None, role: str | None = None, via: str | None = None, primary_only: bool = True,
              as_of: str | None = None, include_context: bool | None = None, limit: int = 50, offset: int = 0,
              archive: str | None = None) -> dict:
    """Which entities are where. Ask exactly one of:
    `within`: {"bbox": [west, south, east, north]}, {"geometry": GeoJSON polygon}, {"place": …} or
    {"entity": …} (its area); `near`: {"point": [lon, lat]} or {"entity": …}, with "km"; nearest first;
    `containing`: {"point": [lon, lat]} or {"entity": …}: the areas that hold it, places included.
    Points are [longitude, latitude]. `schema` (and its subtypes), `role`, `via` narrow it; `as_of` keeps
    geo links that held then; `primary_only=false` asks of every geo link, not just the primary places.
    Places and geometries themselves are left out unless `include_context`."""
    return _run(lambda: geo.geo_query(core.open_archive(archive), within, near, containing, schema, role, via,
                                      primary_only, as_of, include_context, limit, offset))


@mcp.tool()
def geo_measure(a: str | list | dict, b: str | list | dict | None = None, archive: str | None = None) -> dict:
    """Measure on the sphere. With `a` and `b` (entities, [lon, lat] points or GeoJSON geometries): the
    distance between their centres and between their nearest parts, in km. With `a` alone: its area
    (km², ha), length for a line, centre and extent."""
    return _run(lambda: geo.geo_measure(core.open_archive(archive), a, b))


@mcp.tool()
def geo_resolve(point: list | None = None, entity: str | None = None, name: str | None = None, scope: str | None = None,
                level: str | None = None, archive: str | None = None) -> dict:
    """Which real places hold a point, or which a name may be, from boundary and town data kept on this
    machine (nothing is sent anywhere). `point` [lon, lat] (or `entity`: its own centre): the chain holding
    it, coarsest first: country (adm0), region (adm1), district (adm2), then the town whose reach covers it
    (level `settlement`), each with its `key` (iso3166:SA-01, geoboundaries:…, geonames:…) and, when the
    archive already has it, the Place (`place`). `name`: at most three candidates with scores; anything
    finer than a country only inside `scope`, a key of a country, region or district (an entity's country
    is used when `entity` is given); `level` narrows (adm0, adm1, adm2, settlement). A city and the region
    of the same name are different places: say which the source means. Then `site` with
    {"register": key}."""
    return _run(lambda: geo.geo_resolve(core.open_archive(archive), point, entity, name, scope, level))


@mcp.tool()
def geo_enable(confirm: bool = False, archive: str | None = None) -> dict:
    """Install the geo types (Place, Feature, GeoLink), their matching rules and .hydra/rules/geo.yaml in an
    archive made before them. Files it already has are kept. Preview; call again with confirm=true once
    the person agrees."""
    return _run(lambda: geo.geo_enable(core.open_archive(archive), confirm))


@mcp.tool()
def packages(archive: str | None = None) -> dict:
    """Packages (themes, map styles, icon sets, symbology, archetypes, reference layers). Installs are per archive:
    `lock` is what THIS archive uses (.hydra/packages/lock.yaml); `in_store` is what the machine's shared store holds
    (fetched once, used by every archive that locks it); `available` is what the registries offer, each marked
    `installed` when this archive's lock names it."""
    from hydra_mcp import packages as pk
    return _run(lambda: pk.packages(core.open_archive(archive)))


@mcp.tool()
def package_install(name: str, confirm: bool = False, scope: str = "machine", archive: str | None = None) -> dict:
    """Get a package (owner/name) from the registries for THIS archive: the bytes go once into the machine's shared
    store (`scope` machine) or the universe's backdrop, and a line goes into the archive's lock; only locked packages
    take part in the archive's lookups. Preview shows licence, what it provides, what it replaces, where the bytes
    and the lock line go; call again with confirm=true once the person agrees. Taking a package out of an archive
    (Bazaar Remove, `hydra-ctl package remove`) deletes its lock line only; `hydra-ctl package prune` clears store
    folders no archive uses. Nothing here touches records."""
    from hydra_mcp import packages as pk
    return _run(lambda: pk.package_install(core.open_archive(archive), name, confirm, scope))


@mcp.tool()
def site(geolinks: list[dict], collection: str = "geo", confirm: bool = False, archive: str | None = None) -> dict:
    """Say where an entity is: [{entity, location, role?, startDate?, endDate?, primary?, precision?, radius?, sources?, notes?, pages?, locator?, name?}]. `location` is {"place": …}, {"feature": …}, {"entity": …}, {"address": …}, {"osm": "way/123"}, {"point": [lon, lat]}, {"bbox": …}, {"geometry": GeoJSON} or {"register": key from geo_resolve}; points are [longitude, latitude]. `sources` (kept source IDs) and `notes` are checked against those sources. Never put an OSM id or a geometry on the entity itself: this writes a Feature and a GeoLink. Preview shows the records, the checks and the primary place; call again with confirm=true once the person agrees. More: guide("geo-drawing", "site")"""
    return _run(lambda: geo.site(core.open_archive(archive), geolinks, collection, confirm))


@mcp.tool()
def set_primary(entity: str, locations: list[str] | str, confirm: bool = False, archive: str | None = None) -> dict:
    """Choose the places an entity is drawn by first (its pin, its map's extent), in order: `locations` are
    entities with a geometry (by H, key, record id or title), normally ones it is linked to; "auto" puts
    geo.yaml's order back. Kept as a review decision (geo-H-<body>): `decisions` lists it. Preview; call
    again with confirm=true once the person agrees."""
    return _run(lambda: geo.set_primary(core.open_archive(archive), entity, locations, confirm))


@mcp.tool()
def edit_geolink(geolink: str, changes: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Change one geo link (its record id, as `geo_locate` lists under `records`): {"role": …, "startDate": …,
    "endDate": … ("" clears), "entity": …, "location": … (any entity), "notes": …} or {"remove": true}.
    Preview; call again with confirm=true once the person agrees."""
    return _run(lambda: geo.edit_geolink(core.open_archive(archive), geolink, changes, confirm))


@mcp.tool()
def edit_siting(siting: str, changes: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Old name of edit_geolink; use edit_geolink."""
    return edit_geolink(siting, changes, confirm, archive)


@mcp.tool()
def transform_geometry(feature: str, op: str, args: dict | None = None, as_new: bool = False,
                       confirm: bool = False, archive: str | None = None) -> dict:
    """One operation on a geometry (a Feature, by H, key or record id): `simplify` {"metres": n} (fewer
    points, none moved more than n), `to_point` (its centre), `to_bbox` (its extent, as an area),
    `circle` {"metres": n} (a point to an approximate area), `fix` (close rings, wind them, round, swap
    [lat, lon] written the wrong way round). Replaces the geometry (the old one stays in history), or
    with `as_new` makes a new geometry that cites it. Preview; call again with confirm=true."""
    return _run(lambda: geo.transform_geometry(core.open_archive(archive), feature, op, args,
                                               "new" if as_new else "replace", confirm))


@mcp.tool()
def draw_feature(geometry: dict, archetype: str | None = None, entity: str | None = None, new: dict | None = None,
                 name: str | None = None, aspect: str | None = None, kind: str | None = None, confirm: bool = False,
                 archive: str | None = None) -> dict:
    """Draw a place the way the Atlas's + Feature does: a Feature (`geometry`, GeoJSON [lon, lat]; precision `drawn`) and a GeoLink at `aspect`. Say what it is with an `archetype` id of the archive's archetypes.yaml that carries a geometry, or `kind` point | line | area. Site it at an existing entry (`entity`) or make a new one (`new`: {"name": …, "schema"?: …}). `name` names the Feature; `aspect` is a role of geo.yaml. A new location is a point unless the archetype is an area or line: never box a point. Preview shows the lines, warnings and the OSM tag; call again with confirm=true once the person agrees. More: guide("geo-drawing", "draw_feature")"""
    return _run(lambda: geo.draw_feature(core.open_archive(archive), geometry, archetype, entity, new, name, aspect, kind, confirm))


@mcp.tool()
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
    """`link_image` for many images at once: [{image, kind, entity | name, schema, ..., credit: {author, licence, url}}, ...].
    Previews unless confirm=true; one history step for all."""
    return _run(lambda: agent.link_images(core.open_archive(archive), images, confirm))


@mcp.tool()
def wiki_readiness(archive: str | None = None) -> dict:
    """What keeps the archive's wiki pages from being complete, each as something to
    record or decide: terms with no years, names that link to no record, links that
    name several records, same-name pairs, facts only in notes, people with no dates,
    unsourced pages, facts that contradict each other. Each finding has examples and
    a `do`. Use it to plan what to record next; propose, then save. One document:
    `{count, findings: [...]}`."""
    def go():
        from hydra.universe import build as ubuild, layer
        from hydra.wiki import readiness
        root = core.open_archive(archive)
        if not layer.is_universe(root):
            raise core.IngestError("this archive has no universe layer: `hydra-ctl universe init` adds one")
        if not ubuild.pages_current(root):
            ubuild.build(root)
        found = readiness.check(root)
        return {"count": len(found), "findings": found}
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
def save_changes(message: str, description: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Save the work as one named change in history: the steps since the last save fold under it, so a
    task reads as one change. Call it at the end of a task. Previews what it covers unless confirm=true."""
    return _run(lambda: agent.save_changes(core.open_archive(archive), message, description, confirm))


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
    writing records of it, and again to double-check a record you wrote. For themes,
    the fields worth filling in and Wikidata codes, use `properties`."""
    def go():
        core.archive_or_defaults(archive)
        return core.describe_schema(schema)
    return _run(go)


@mcp.tool()
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


@mcp.tool()
def extra_fields(archive: str | None = None) -> dict:
    """The fields records carry that FtM does not have (kept in `_meta.extra` when a save finds one, or a key
    like `P1449`): each with its type, how many records hold it, its Wikidata code if marked, and the closest
    Wikidata properties. Assign them with `field_assign`."""
    return _run(lambda: core.extra_fields(core.open_archive(archive)))


@mcp.tool()
def field_assign(field: str, schema: str, to: str, wd: str | None = None, confirm: bool = False,
                 archive: str | None = None) -> dict:
    """Move an extra field's values on, for the records of `schema` that hold `field`. `to` is `Schema.prop` (an
    FtM field; refused when a value does not fit its type), `new:<name>` (a property of this archive's own, in
    .hydra/schema/extensions/archive.yaml; needs `wd`, the Wikidata code P…) or `drop` (the values are listed, then
    removed). Without `confirm` it previews and writes nothing; call again with confirm=true once the person
    agrees. One history step; the result says how to undo it."""
    return _run(lambda: core.field_assign(core.open_archive(archive), field, schema, to, wd, confirm))


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
                 publisher: str | None = None, summary: str | None = None, language: str | None = None,
                 keywords: list[str] | None = None, archive: str | None = None,
                 keep: bool = False) -> dict:
    """Fetch a web page and keep its text in the archive as a source of its own, so records can cite it: `"sources": ["<source_id>"]`, with their `notes` quoting it word for word. Nothing is summarized. Returns the first part of the text; `read_source` gives the rest. Fill what the page states and leave out what it does not: `title`, `author`, `publisher`, `published`, `language`, `keywords`, and `summary` (your own short account, never a quote). A page that looks useless comes back with `quality: "thin"` and is NOT kept unless you pass `keep=true`. A page that refuses the fetch stays out: ask the person to save it and use `read_file`. A page kept by mistake: `drop_source`. More: guide("sources", "fetch_source")"""
    def go():
        from hydra import writelock
        from hydra_mcp import sources, workflows
        root = core.open_archive(archive)
        got = sources.page(url)                              # the network first, outside the write lock
        with writelock.hold(root, workflows._holder(root)):
            return sources.fetch(root, url, title, published, author, publisher, summary,
                                 language, keywords, prefetched=got, keep_thin=keep)
    return _run(go)


@mcp.tool()
def drop_source(source: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a kept source (`source`: its `doc-...` id) that no record cites, such as a page
    fetched by mistake: its entry and its stored file go and the archive is rebuilt. A source a
    record cites is refused, with the records listed; re-source those first. Previews unless
    confirm=true; call again once the person agrees."""
    return _run(lambda: src_mod.drop(core.open_archive(archive), source, confirm))


@mcp.tool()
def read_source(source: str, offset: int = 0, find: list[str] | None = None, archive: str | None = None) -> dict:
    """A kept source's text (by its id, from `fetch_source` or `save`), in parts from
    `offset` (for a kept PDF with `page_ranges`: each page's start and end in the text); or, with `find` (words), every sentence containing one of them: the
    sentences to quote in `notes`."""
    def go():
        from hydra_mcp import sources
        return sources.read(core.open_archive(archive), source, offset, find)
    return _run(go)


@mcp.tool()
def sources(query: str | None = None, uncited_only: bool = False, archive: str | None = None,
            offset: int = 0, limit: int = 100, uncited_entities: bool = False) -> dict:
    """List every kept source (`doc-...` ID, title, URL, filename, `has_text`, citations)
    plus `uncited_sources` and `uncited_entities_count`; the first 50 entities that cite no source
    are listed as `uncited_entities` only with `uncited_entities=true`. Works across all sources (web and
    local files), unlike `source_report` which lists only Wikipedia-backed citations. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: src_mod.list_sources(core.open_archive(archive), query, uncited_only, offset, limit,
                                          uncited_entities))


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
def wikipedia_footnotes(url: str, quote: str, archive: str | None = None) -> dict:
    """What Wikipedia itself cites for a sentence: given the article `url` a record cites
    and the `quote` it took from it, the references attached to that sentence (url, title,
    publisher, date). Those are the sources to fetch, read and cite instead; the fact must
    then be quoted in their own words. `archive` is accepted for uniformity and not used."""
    def go():
        from hydra_mcp import sources
        return sources.footnotes(url, quote)
    return _run(go)


@mcp.tool()
def cite(citations: list[dict] | None = None, confirm: bool = False, archive: str | None = None,
         sources: list[dict] | None = None) -> dict:
    """Say where in a kept source a saved record's facts are: a list of {record, source, pages?, pdfPages?, locator?, quote?}. `record` is a record id (as `get_records` shows it); `source` the source document's id; `pages` the number printed on the document ("14", "I-16"); `pdfPages` the page of the PDF file ("20"); a scan's two differ (PDF p. 20 prints "1"); give either or both; `locator` anything else that finds it; `quote` the words, exactly as the source has them (gives `pdfPages`, and `pages` too when readable). A row with only record and source removes that citation. `sources` says what a kept source is: a list of {source, title?, author?, publisher?, published?, url?, summary?, language?, keywords?, duration?, pictured?, call_number?}. Without `confirm` it shows the rows resolved and any problem; call again with confirm=true to write them. More: guide("sources", "cite")"""
    return _run(lambda: agent.cite(core.open_archive(archive), citations, confirm, sources))


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


@mcp.tool()
def save(records: list[dict], source: dict | None = None, collection: str | None = None,
         archive: str | None = None, replace: bool = False, mode: str = "new") -> dict:
    """Check and save records as a new collection, with their evidence, then rebuild. `records`: [{"schema": "Person", "properties": {"name": ["..."]}}, ...]. `source`: {"file": full path}, {"text": "..."} or {"id": "..."} (evidence already saved), with "title", "url", "publisher", "author", "published" when known; a batch from several sources leaves `source` out and cites `"sources": ["doc-..."]` on each record. A record with `"upstream": [an h from find_entities]` is that entity. If anything breaks the modelling rules, nothing is saved and `errors` says what to fix. `mode="add"` appends to an existing `collection`; `mode="new"` (default) makes one, or with `replace=true` replaces one. More: guide("fields", "save")"""
    return _run(lambda: core.ingest(core.open_archive(archive), records, source or {}, collection, replace,
                                    mode=mode))


@mcp.tool()
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


@mcp.tool()
def create_archive(path: str, name: str | None = None, prefix: str | None = None, confirm: bool = False) -> dict:
    """Start a new, empty hydra archive in a new or empty folder (full path, chosen
    by the person). `prefix` is the id prefix every collection uses (default: one
    made from the name; "none" gives each collection its own). Without confirm it
    only shows what it would create; call again with confirm=true once the person
    agrees. Then pass the folder as `archive`."""
    return _run(lambda: core.create_archive(path, name, prefix, confirm))


# ---- guides, tasks, views & archive orientation -----------------------------------------------------


@mcp.resource("hydra://guide/{topic}")
def guide_resource(topic: str) -> str:
    """A hydra guide topic in Markdown (`start`, `rules`, `tasks`, ...)."""
    return wf.guide(topic)["content"]


@mcp.resource("hydra://guide/{group}/{name}")
def guide_nested_resource(group: str, name: str) -> str:
    """A nested hydra guide in Markdown (`workflow/<name>` or `views/<name>`)."""
    return wf.guide(f"{group}/{name}")["content"]


@mcp.tool()
def guide(topic: str | None = None, section: str | None = None, archive: str | None = None) -> dict:
    """Read the hydra guide: with no `topic`, the list of topics; `guide("start")` first in every session.
    A `topic` returns that guide (`rules`, `sources`, `identity`, `fields`, `tasks`, `views`, `views/org`,
    `workflow/enrich`...); `section` returns one `##` part of it (by its number, letter or words), to keep
    what you load small. A task's checkout lists the guides it needs."""
    return _run(lambda: wf.guide(topic, section, archive))


@mcp.tool()
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


@mcp.tool()
def tasks(status: str | None = None, workflow: str | None = None, collection: str | None = None,
          archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """List the archive's tasks (status `open`, `checked-out`, `blocked` or `done`) with steps done of
    total, and `current_task`, the one this session has checked out. A checked-out task shows its `holder`,
    how long it has been `idle` and whether it is `stale` (a stale one can be taken without `force`). Pick an
    open task, or ask the person before making a new one with `task_new`. Paged: `offset`, `limit` (100 by default; `next_offset` starts the next page)."""
    return _run(lambda: wf.list_tasks(core.open_archive(archive), status, workflow, collection, offset, limit))


@mcp.tool()
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


@mcp.tool()
def contexts(task: str | None = None, words: str = "", archive: str | None = None) -> dict:
    """List the contexts a task can work in (the brief that says what to keep and what to drop), as
    `{contexts: [...]}`. With a `task` id (or `words` describing the work) they are ranked, best first, each
    with a `score` and `why`; without, every context with `use_when`. Read one in full with
    `guide("context/<name>")`; set it with `context_checkout`."""
    return _run(lambda: wf.contexts_list(core.open_archive(archive), task, words))


@mcp.tool()
def context_checkout(id: str, name: str, reason: str, confirm: bool = False,
                     archive: str | None = None) -> dict:
    """Set the context of task `id` to `name`, with a `reason`. Previews unless confirm=true: show the person
    the preview (the context's keep and drop, route and charts) first; with `general` when working unattended.
    Fixed after the task's first write: for another context, start a new task."""
    return _run(lambda: wf.context_checkout(core.open_archive(archive), id, name, reason, confirm))


@mcp.tool()
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


@mcp.tool()
def task(id: str | None = None, archive: str | None = None) -> dict:
    """Show a task as it stands: every step with its status and result, `next_step` with its
    instructions, the sources kept for it (`uncited_sources`: kept but cited by no record yet), claims and
    the last log lines. `id` defaults to this session's task."""
    return _run(lambda: wf.task_show(core.open_archive(archive), id))


@mcp.tool()
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


@mcp.tool()
def task_add(subject: str | None = None, step: str | None = None, block: str | None = None,
             code: str | None = None, id: str | None = None, archive: str | None = None) -> dict:
    """Add to your task: `subject` adds another block of the workflow's per-subject steps; or `code` +
    `step` (its text) adds one step to the block whose title contains `block` (default: the last)."""
    return _run(lambda: wf.task_add(core.open_archive(archive), subject, step, block, code, id))


@mcp.tool()
def task_verify(id: str | None = None, archive: str | None = None) -> dict:
    """Check a task before closing it: open steps, claims, sources kept vs cited, what changed since
    checkout, and each of its views' checks. `ready_to_close` is true when no step is open."""
    return _run(lambda: wf.task_verify(core.open_archive(archive), id))


@mcp.tool()
def task_release(id: str | None = None, force: bool = False, archive: str | None = None) -> dict:
    """Hand a task back unfinished (it becomes `open`, its steps and log kept) so another session can take
    it. Tick or block the step you were on first."""
    return _run(lambda: wf.task_release(core.open_archive(archive), id, force))


@mcp.tool()
def task_close(status: str = "done", summary: str = "", id: str | None = None,
               force: bool = False, archive: str | None = None) -> dict:
    """Finish your task: `done` (refused while a step is open) or `blocked` (with a `summary` of what the
    person must decide). Snapshots the archive, tags `task/<id>/done`, and returns `task_verify`'s report.
    `history_diff` from `task/<id>/start` to `task/<id>/done` shows everything the task changed."""
    return _run(lambda: wf.task_close(core.open_archive(archive), status, summary, id, force))


@mcp.tool()
def collections(archive: str | None = None) -> dict:
    """List the collections: id, title (the name readers see), id prefix, record count, and which views each is prepared for (`views`, with its handles in `view_specs`)."""
    return _run(lambda: wf.collections(core.open_archive(archive)))


@mcp.tool()
def set_collection_views(collection: str, views: dict | list[str] | None = None, confirm: bool = False,
                         archive: str | None = None, title: str | None = None) -> dict:
    """Name a collection and say which views it is prepared for. `title`: the name readers see (take it from
    the source's own title). `views`: {"org": true, "map": false, "graph": {"focus": "<record id>", "depth": 2}}
    (org, links, radial, map, timeline, graph); a list of names, ["org", "map"], switches those views on.
    A view is true, false, a spec or a list of specs; spec keys
    (all optional): focus (a record or H id), depth, edges (list of relationship schemas), from, to (years),
    within (collection or universe), title (the handle's label); a focus that names nothing is refused. Each
    spec is a handle on the Collections page. New tasks on the collection add those views' steps. Previews
    unless confirm=true."""
    return _run(lambda: wf.set_collection_views(core.open_archive(archive), collection, views, confirm, title))


@mcp.tool()
def set_collection(collection: str, views: dict | list[str] | None = None, confirm: bool = False,
                   archive: str | None = None, title: str | None = None) -> dict:
    """Same as set_collection_views: set a collection's `title` and its view handles (specs). Previews unless confirm=true."""
    return set_collection_views(collection, views, confirm, archive, title)


@mcp.tool()
def view_config(collection: str | None = None, archive: str | None = None) -> dict:
    """What each view starts with: entry and link types hidden, map settings, the entry panel's buttons,
    icons and badge rules, as the wiki applies them (with a collection's own overrides)."""
    return _run(lambda: wf.view_config(core.open_archive(archive), collection))


@mcp.tool()
def view_check(view: str, collection: str | None = None, archive: str | None = None) -> dict:
    """What one view cannot draw, or draws poorly, for a collection (or the whole archive). `view`: org,
    links, radial, map, timeline, graph or panel. Also reports the collection's view specs that name an
    entity that does not exist, or use a key a spec may not. Each finding has a code, count, examples and what to do; `ok`
    is false while any warning remains. Run it after `universe_build`."""
    return _run(lambda: wf.view_check(core.open_archive(archive), view, collection))


@mcp.tool()
def tree(kind: str | None = None, search: str | None = None, read: str = "declared",
         format: str = "text", archive: str | None = None) -> dict:
    """The placement tree: which entry sits under which (the Org Chart and Radial are drawn from it).
    `kind` (a type such as PublicBody) and `search` (words) pick where to start; `format` text or json."""
    return _run(lambda: wf.tree(core.open_archive(archive), kind, search, read, format))


@mcp.tool()
def positions(mode: str = "both", with_nodes: bool = False, read: str = "declared",
              archive: str | None = None) -> dict:
    """The rank ladder as a tree, and the role titles no position takes (`unplaced_titles`). `mode`: both,
    tree or unplaced. Propose `set_positions` to the person when many titles are unplaced."""
    return _run(lambda: wf.positions(core.open_archive(archive), mode, with_nodes, read))


@mcp.tool()
def badges(archive: str | None = None) -> dict:
    """The badge rules and how many entries each matches, and the post titles no role rule matches
    (`unmatched_post_titles`): those posts get no rank icon on the Org Chart."""
    return _run(lambda: wf.badges(core.open_archive(archive)))


@mcp.tool()
def details(archive: str | None = None) -> dict:
    """One-call overview of the archive: records, types, collections, the tree's roots, open questions."""
    return _run(lambda: wf.details(core.open_archive(archive)))


@mcp.tool()
def check(archive: str | None = None) -> dict:
    """Problems in the archive's files without building (rules files, records, sources), by level."""
    return _run(lambda: wf.check(core.open_archive(archive)))


from hydra_mcp import suggestions as _suggestions  # noqa: E402

_suggestions.register(mcp, _run)

from hydra_mcp import wikidataqs as _wikidataqs  # noqa: E402

_wikidataqs.register(mcp, _run)


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="hydra-mcp")
    ap.add_argument("--toolsets", default=None,
                    help="tool sets to switch on, comma separated: core,enrich,geo,shape,admin or all "
                         f"(default: env {toolsets_mod.ENV}, else core)")
    args = ap.parse_args(argv)
    toolsets_mod.apply(mcp, toolsets_mod.startup_spec(args.toolsets))
    mcp.run()


from hydra_mcp import labelling as _labelling  # noqa: E402

_labelling.register(mcp, _run)


# ---- geo, stream C: move, delete, contexts, summaries, register ---------------------------------------

@mcp.tool()
def move_feature(entity: str | None = None, feature: str | None = None, geometry: dict | None = None,
                 delta_m: list | None = None, confirm: bool = False, archive: str | None = None) -> dict:
    """Move or reshape a place the way the Atlas's Move does. Name one `entity` (its own place: H, key, record id or
    title) or one drawn `feature`, and give the new place as `geometry` (GeoJSON, [lon, lat]) or as `delta_m`
    [metres east, metres north] to shift what is there. An entry's own drawn shape is redrawn in place; a point or a
    shape read from a source is not touched: the entry gets its own point or copy at the new spot and it becomes
    its place (the old one stays in history). Register countries and regions are not moved; an entry with several
    primary places is moved shape by shape with `feature`. Returns {error, why, do} when it cannot. Preview shows
    before and after; call again with confirm=true once the person agrees."""
    return _run(lambda: geo.move_feature(core.open_archive(archive), entity, feature, geometry, delta_m, confirm))


@mcp.tool()
def delete_feature(feature: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a drawn Feature (by H, key or record id) and the GeoLinks that use it. Only shapes drawn or given as
    GeoJSON here are deleted, never ones read from OSM or the register. The entries that used it lose that place;
    nothing else is touched, and history keeps it all (`history_restore`). The preview lists each entry that loses
    a place; call again with confirm=true once the person agrees."""
    return _run(lambda: geo.delete_feature(core.open_archive(archive), feature, confirm))


@mcp.tool()
def geo_contexts(archive: str | None = None) -> dict:
    """The geographic contexts installed in this archive (Bazaar packages that carry boundary or feature layers, such as
    districts or a front line): per package its version and licence, and per layer its name, label, feature
    count, levels and attribution. Use a layer's name in `geo_summarize by="context:<name>"` and
    `geo_query within={"context": <name or key>}`. Read-only; installing one needs the person (`package_install`)."""
    return _run(lambda: geo.geo_contexts(core.open_archive(archive)))


@mcp.tool()
def geo_summarize(by: str, schema: str | None = None, tag: str | None = None, as_of: str | None = None,
                  limit: int = 100, archive: str | None = None) -> dict:
    """How many entries lie in each area: `by` "country", "admin1" (region) or "context:<name>" (the features of a
    context layer, from `geo_contexts`). Each row gives the area's `name`, `key`, `count` and three example entries,
    biggest first; `unplaced` counts entries with no place. An entry counts under its primary place, and where that
    is a point it is placed by the area that holds it. Filter by `schema`, by `tag` (an archetype id: entries that
    fit it or were confirmed as it) and by `as_of` (a date: only geo links in force then). Read-only."""
    return _run(lambda: geo.geo_summarize(core.open_archive(archive), by, schema, tag, as_of, limit))


@mcp.tool()
def geo_register_status(archive: str | None = None) -> dict:
    """The boundary layers kept on this machine (what `hydra-ctl geo register status` prints): per layer its label,
    version, licence, whether it is installed or packed with hydra, size and whether it is critical, plus
    `missing_critical` (layers the Atlas needs that are absent). Read-only; installing a layer downloads, so ask the person."""
    return _run(lambda: geo.geo_register_status(core.open_archive(archive)))

from hydra_mcp import data as _data  # noqa: E402

_data.register(mcp, _run)


# ---- toolsets: which tools a client sees (last, so every tool above is in the table) ------------------------

@mcp.tool()
def toolsets(archive: str | None = None) -> dict:
    """The tool sets and whether each is on, with the tools in it: `core` is always on; `enrich`, `geo`, `shape`
    and `admin` are switched on with `toolset_enable`. Use it when a tool you need is not in your list."""
    return _run(lambda: toolsets_mod.status(mcp))


@mcp.tool()
def toolset_enable(name: str, archive: str | None = None) -> dict:
    """Switch a tool set on (`enrich`, `geo`, `shape`, `admin`, or `all`) and tell the client its tool list changed.
    Returns `added` (the tools now available) and the sets that are on. A task's checkout already switches on the
    sets its route needs."""
    def go():
        added = toolsets_mod.enable(mcp, name.strip().lower())
        return {"enabled": name, "added": added,
                "on": [s["name"] for s in toolsets_mod.status(mcp)["toolsets"] if s["on"]]}
    return _run(go)


toolsets_mod.install(mcp)


if __name__ == "__main__":
    main()
