"""tools/shape.py — the `shape` tool set: how the archive reads as a wiki: labels and tags, positions and badges,
the placement tree, collections and their views, symbology, articles, sitings, publishing Hs and serving the wiki."""
from __future__ import annotations

from hydra.universe import build as ubuild, layer

from hydra_mcp import agent, article, core, data, geo, labelling, pipeline, workflows as wf
from hydra_mcp.app import _run, tool


@tool()
def article_sections(entity: str, archive: str | None = None) -> dict:
    """An entity's article text (`entity`: its H, a record id, or a title only one entry has): its sections in order, each with
    `text` (Markdown), and, when imported, `from` (enwiki:Title@revision) and `licence`. An
    imported section is read-only until a person forks it in the wiki."""
    return _run(lambda: article.article_sections(core.open_archive(archive), entity))


@tool()
def set_article_section(entity: str, heading: str, text: str, from_: str | None = None, confirm: bool = False,
                        archive: str | None = None) -> dict:
    """Add a section to an entity's article, or replace the text of the section with this
    `heading`. `text` is plain Markdown (paragraphs, *emphasis*, [links](https://...), lists); cite
    a kept source in prose as `[^source-id p.23]`. Pass `from_` (enwiki:Title@revision) only for
    text copied from Wikipedia: it stays read-only and keeps its CC BY-SA 4.0 notice. Text a person
    wrote or forked is never replaced by an import. Without `confirm` it only previews; call
    again with confirm=true once the person agrees."""
    return _run(lambda: article.set_article_section(core.open_archive(archive), entity, heading, text, from_, confirm))


@tool()
def remove_article_section(entity: str, heading: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Take the section with this `heading` out of an entity's article (its own text or an imported one). Without
    `confirm` it shows what would go; call again with confirm=true once the person agrees. One history step."""
    return _run(lambda: article.remove_article_section(core.open_archive(archive), entity, heading, confirm))


@tool()
def move_article_section(entity: str, heading: str, to: int, confirm: bool = False, archive: str | None = None) -> dict:
    """Move the section with this `heading` to position `to` (1 is first) in an entity's article, and show the new
    order. Without `confirm` it only previews; call again with confirm=true once the person agrees. One history step."""
    return _run(lambda: article.move_article_section(core.open_archive(archive), entity, heading, to, confirm))


@tool()
def symbology(archive: str | None = None) -> dict:
    """What the wiki draws with, as the Symbology page shows it: each entry type's icon and how
    many entries it marks, each badge rule's icon and reach, each position's picture rule, each
    link type's colour in the Radial and Org Chart, every image rule (hints.yaml) and what it
    reached, and the icon tokens there are to choose from."""
    return _run(lambda: agent.symbology(core.open_archive(archive)))


@tool()
def set_symbology(kind: str, key: str, value: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Change one thing the wiki draws with: `kind` is `type-icon` (an entry type, `key` its
    schema), `badge-icon` (a badge rule's key), `position-icon` (a position's name; writes a
    hints.yaml rule), `link-colour` (a link type, `value` #rrggbb) or `link-mark` (a link type: what
    the Timeline draws when it has a start and no end, `value` start, fades or runs). `value` is an icon token
    from `symbology`, or "" to put the default back. Without `confirm` it shows the current
    choice and the new one; call again with confirm=true once the person agrees. A wiki.yaml
    with comments is never rewritten: edit it by hand then."""
    return _run(lambda: agent.set_symbology(core.open_archive(archive), kind, key, value, confirm))


@tool()
def site(geolinks: list[dict], collection: str = "geo", confirm: bool = False, archive: str | None = None) -> dict:
    """Say where an entity is: [{entity, location, role?, startDate?, endDate?, primary?, precision?, radius?, sources?, notes?, pages?, locator?, name?}]. `location` is {"place": …}, {"feature": …}, {"entity": …}, {"address": …}, {"osm": "way/123"}, {"point": [lon, lat]}, {"bbox": …}, {"geometry": GeoJSON} or {"register": key from geo_resolve}; points are [longitude, latitude]. `sources` (kept source IDs) and `notes` are checked against those sources. Never put an OSM id or a geometry on the entity itself: this writes a Feature and a GeoLink. Preview shows the records, the checks and the primary place; call again with confirm=true once the person agrees. More: guide("geo-drawing", "site")"""
    return _run(lambda: geo.site(core.open_archive(archive), geolinks, collection, confirm))


@tool()
def set_positions(positions: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Write this archive's rank ladder (.hydra/rules/positions.yaml): {name: {below:
    [the positions above it], titles: [the role words that mean it], outside: false}}.
    The preview says how many of the archive's roles each position ranks and which
    roles none takes. Call again with confirm=true once the person agrees."""
    return _run(lambda: agent.set_positions(core.open_archive(archive), positions, confirm))


@tool()
def wiki_readiness(archive: str | None = None) -> dict:
    """What keeps the archive's wiki pages from being complete, each as something to
    record or decide: terms with no years, names that link to no record, links that
    name several records, same-name pairs, facts only in notes, people with no dates,
    unsourced pages, facts that contradict each other. Each finding has examples and
    a `do`. Use it to plan what to record next; propose, then save. One document:
    `{count, findings: [...]}`."""
    def go():
        root = core.open_archive(archive)
        if not layer.is_universe(root):
            raise core.IngestError("this archive has no universe layer: `hydra-ctl universe init` adds one")
        if not ubuild.pages_current(root):
            ubuild.build(root)
        from hydra.wiki.pages import readiness  # lazy: startup
        found = readiness.check(root)
        return {"count": len(found), "findings": found}
    return _run(go)


@tool()
def publish(hs: list[str] | None = None, collections: list[str] | None = None, confirm: bool = False,
            archive: str | None = None) -> dict:
    """Make computed Hs published, so their ids and page addresses hold from now on: `hs`
    (Hs, bodies or record ids), or every computed H whose records all come from
    `collections` (entities that also draw on other collections are listed, not
    published). Without `confirm` it shows what it would publish; call again with
    confirm=true once the person agrees."""
    return _run(lambda: pipeline.publish(core.open_archive(archive), hs, collections, confirm))


@tool()
def wiki_serve(port: int = 8080, theme: str | None = None, replace_other: bool = False, archive: str | None = None) -> dict:
    """Show the archive as a wiki at http://127.0.0.1:<port>/, current: builds the pages when
    they are older than their inputs, stops the wiki this tool started on that port, starts
    a new one and checks it serves as many entries as the build made pages (`ok`). The wiki
    reads its pages once, at start, so call this after every change that should show.
    Refuses when another server holds the port; `replace_other=true` stops it (ask first)."""
    return _run(lambda: pipeline.wiki_serve(core.open_archive(archive), port, theme, replace_other))


@tool()
def wiki_stop(port: int = 8080) -> dict:
    """Stop the wiki this tool started on `port`. Servers it did not start are left alone."""
    return _run(lambda: pipeline.wiki_stop(port))


@tool()
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


@tool()
def set_collection(collection: str, views: dict | list[str] | None = None, confirm: bool = False,
                   archive: str | None = None, title: str | None = None) -> dict:
    """Same as set_collection_views: set a collection's `title` and its view handles (specs). Previews unless confirm=true."""
    return set_collection_views(collection, views, confirm, archive, title)


@tool()
def view_config(collection: str | None = None, archive: str | None = None) -> dict:
    """What each view starts with: entry and link types hidden, map settings, the entry panel's buttons,
    icons and badge rules, as the wiki applies them (with a collection's own overrides)."""
    return _run(lambda: wf.view_config(core.open_archive(archive), collection))


@tool()
def view_check(view: str, collection: str | None = None, archive: str | None = None) -> dict:
    """What one view cannot draw, or draws poorly, for a collection (or the whole archive). `view`: org,
    links, radial, map, timeline, graph or panel. Also reports the collection's view specs that name an
    entity that does not exist, or use a key a spec may not. Each finding has a code, count, examples and what to do; `ok`
    is false while any warning remains. Run it after `universe_build`."""
    return _run(lambda: wf.view_check(core.open_archive(archive), view, collection))


@tool()
def tree(kind: str | None = None, search: str | None = None, read: str = "declared",
         format: str = "text", archive: str | None = None) -> dict:
    """The placement tree: which entry sits under which (the Org Chart and Radial are drawn from it).
    `kind` (a type such as PublicBody) and `search` (words) pick where to start; `format` text or json."""
    return _run(lambda: wf.tree(core.open_archive(archive), kind, search, read, format))


@tool()
def positions(mode: str = "both", with_nodes: bool = False, read: str = "declared",
              archive: str | None = None) -> dict:
    """The rank ladder as a tree, and the role titles no position takes (`unplaced_titles`). `mode`: both,
    tree or unplaced. Propose `set_positions` to the person when many titles are unplaced."""
    return _run(lambda: wf.positions(core.open_archive(archive), mode, with_nodes, read))


@tool()
def badges(archive: str | None = None) -> dict:
    """The badge rules and how many entries each matches, and the post titles no role rule matches
    (`unmatched_post_titles`): those posts get no rank icon on the Org Chart."""
    return _run(lambda: wf.badges(core.open_archive(archive)))


@tool(name="label")
def label_tool(entities: list[str], tokens: str, confirm: bool = False, source: str | None = None,
               archive: str | None = None) -> dict:
    """Attach labels to entries (by H, key, record id or title), the way the wiki's Labelling page does. `tokens` is one command line of `kind:value` words (place, org, post, tag, own, evt, kin, drop). Previews each entry's labels first, each with its Wikidata property code (`wd`) or `no_standard_code`. A fact (org, country, a post held, own, evt, kin) needs `source`, the id of a kept source; judgements need none. Writes only with confirm=true, and only when every label of every entry is ok; confirm only with the person's agreement. More: guide("labelling", "label")"""
    return _run(lambda: labelling.label(core.open_archive(archive), entities, tokens, confirm, source))


@tool(name="collection_rename")
def collection_rename_tool(old: str, new: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Rename collection `old` to `new` without changing a record: the file, its entry in hydra.yaml (title,
    prefix, view handles), the groups that list it and open tasks on it all follow. Record ids and H bodies stay,
    because the id prefix is pinned to the collection. The Hs of its records are published first. The preview
    names what follows (records, prefix, groups, tasks); call again with confirm=true once the person agrees.
    Rebuilds; one history step. Errors come back as {error, why, do}."""
    return _run(lambda: data.collection_rename(core.open_archive(archive), old, new, confirm))


@tool(name="collection_delete")
def collection_delete_tool(name: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove an empty collection made by mistake: its file, its entry in hydra.yaml (title, prefix, view handles)
    and its place in groups (a group left empty goes too). Refused while it holds a record, keeps a source, or an
    open task names it. Previews unless confirm=true; one history step. Errors come back as {error, why, do}."""
    return _run(lambda: data.collection_delete(core.open_archive(archive), name, confirm))


@tool(name="collection_merge")
def collection_merge_tool(into: str, from_: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Join collection `from_` into `into` and remove `from_`: every record is kept with its id and H. Refused when
    the two collections have different id prefixes (the ids would change) or a record id clashes with different
    content. `from_`'s view handles are dropped (the preview lists them); groups and tasks that named it now name
    `into`. A merge is always the person's decision: confirm only after they agree, even on an authorized task.
    Previews unless confirm=true; rebuilds; one history step. Errors come back as {error, why, do}."""
    return _run(lambda: data.collection_merge(core.open_archive(archive), into, from_, confirm))


@tool(name="move_records")
def move_records_tool(ids: list[str], to: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Move records (by record id, as `find_entities` or `get_records` give it) into collection `to`, keeping
    each record whole, with its id and H. Refused, with nothing moved, when a record is unknown, sits in several
    collections, has a different id prefix from `to` (the id would change) or its id already exists there.
    Previews unless confirm=true; rebuilds; one history step. Errors come back as {error, why, do}."""
    return _run(lambda: data.move_records(core.open_archive(archive), ids, to, confirm))


@tool(name="set_collection_group")
def set_collection_group_tool(group: str, collections: list[str], title: str | None = None, confirm: bool = False,
                              archive: str | None = None) -> dict:
    """Make or change a collection group (hydra.yaml `collection_groups.<group>`): a named set of collections that a
    view handle can open together. `collections` must all exist; an empty list removes the group. `title` is its
    display name (kept when omitted). Previews unless confirm=true; one history step. Errors come back as {error, why, do}."""
    return _run(lambda: data.set_collection_group(core.open_archive(archive), group, collections, title, confirm))


@tool()
def tags(entity: str, archive: str | None = None) -> dict:
    """Each tag (archetype) an entry scores against, as Review and Labelling do: `score` out of 100 against the tag's
    `fit` line, whether it `fits`, the person's `decision` (confirmed, rejected or undecided), what the entry
    `shows` and what it `lacks`. Read-only; set decisions with `label` (tag:<id>, tag:no@<id>, tag:clear@<id>).
    Errors come back as {error, why, do}."""
    return _run(lambda: data.tags(core.open_archive(archive), entity))
