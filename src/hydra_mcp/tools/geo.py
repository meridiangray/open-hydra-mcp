"""tools/geo.py — the `geo` tool set: where entities are (hydra_mcp.geo): reports, lookups, queries and measures,
the boundary register, drawing, moving and changing places and geo links, and the Atlas's map layers."""
from __future__ import annotations

from hydra_mcp import core, geo, upkeep
from hydra_mcp.app import _run, tool


@tool()
def layer_list(archive: str | None = None) -> dict:
    """The archive's map layers: GeoJSON drawn on the Atlas that is not entities (id, name, attribution, licence,
    feature count, bounding box)."""
    return _run(lambda: upkeep.layer_list(core.open_archive(archive)))


@tool()
def layer_add(file: str, name: str, attribution: str = "", licence: str = "", confirm: bool = False,
              archive: str | None = None) -> dict:
    """Add a GeoJSON file (full path: a FeatureCollection, a Feature or a geometry) as a map layer on the Atlas: not
    entities, never in records. Data in Web Mercator or a WGS 84 UTM zone is converted to lon/lat; another projection
    is refused with its name (ask the person for lon/lat). Give where it comes from and its licence. Without `confirm`
    it shows how many features would be drawn and dropped; call again with confirm=true once the person agrees."""
    return _run(lambda: upkeep.layer_add(core.open_archive(archive), file, name, attribution, licence, confirm))


@tool()
def layer_remove(layer: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a map layer by its id (layer_list). Without `confirm` it only previews. One history step."""
    return _run(lambda: upkeep.layer_remove(core.open_archive(archive), layer, confirm))


@tool()
def geo_report(top: int = 25, include_entities: bool = False, archive: str | None = None) -> dict:
    """How much of the archive has a place, per entry type and finding count. With
    `include_entities=true`, also returns `country_only_entities`, `unplaced_entities`,
    and `place_reference_items` (`birthPlace`, `address`, `Event.location`, `registrationPort`)."""
    return _run(lambda: geo.geo_report(core.open_archive(archive), top, include_entities))


@tool()
def geo_locate(entity: str, as_of: str | None = None, archive: str | None = None) -> dict:
    """Where one entity is (by H, key such as wikidata:Q… or osm:way/…, record id or title): its primary
    places (`how`: chosen by a person, or inferred from geo.yaml's role order) with shape, centre, extent
    and area; every geo link (role, `via`: geolink, coordinates, address, country), its members (what sits
    under it), its reach (places it is linked to by ownership, office...), and the places that contain
    it. `as_of` ("2000", "2000-06") keeps only the geo links and reach that held then."""
    return _run(lambda: geo.geo_locate(core.open_archive(archive), entity, as_of))


@tool()
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


@tool()
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


@tool()
def geo_measure(a: str | list | dict, b: str | list | dict | None = None, archive: str | None = None) -> dict:
    """Measure on the sphere. With `a` and `b` (entities, [lon, lat] points or GeoJSON geometries): the
    distance between their centres and between their nearest parts, in km. With `a` alone: its area
    (km², ha), length for a line, centre and extent."""
    return _run(lambda: geo.geo_measure(core.open_archive(archive), a, b))


@tool()
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


@tool()
def geo_enable(confirm: bool = False, archive: str | None = None) -> dict:
    """Install the geo types (Place, Feature, GeoLink), their matching rules and .hydra/rules/geo.yaml in an
    archive made before them. Files it already has are kept. Preview; call again with confirm=true once
    the person agrees."""
    return _run(lambda: geo.geo_enable(core.open_archive(archive), confirm))


@tool()
def set_primary(entity: str, locations: list[str] | str, confirm: bool = False, archive: str | None = None) -> dict:
    """Choose the places an entity is drawn by first (its pin, its map's extent), in order: `locations` are
    entities with a geometry (by H, key, record id or title), normally ones it is linked to; "auto" puts
    geo.yaml's order back. Kept as a review decision (geo-H-<body>): `decisions` lists it. Preview; call
    again with confirm=true once the person agrees."""
    return _run(lambda: geo.set_primary(core.open_archive(archive), entity, locations, confirm))


@tool()
def edit_geolink(geolink: str, changes: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Change one geo link (its record id, as `geo_locate` lists under `records`): {"role": …, "startDate": …,
    "endDate": … ("" clears), "entity": …, "location": … (any entity), "notes": …} or {"remove": true}.
    Preview; call again with confirm=true once the person agrees."""
    return _run(lambda: geo.edit_geolink(core.open_archive(archive), geolink, changes, confirm))


@tool()
def edit_siting(siting: str, changes: dict, confirm: bool = False, archive: str | None = None) -> dict:
    """Old name of edit_geolink; use edit_geolink."""
    return edit_geolink(siting, changes, confirm, archive)


@tool()
def transform_geometry(feature: str, op: str, args: dict | None = None, as_new: bool = False,
                       confirm: bool = False, archive: str | None = None) -> dict:
    """One operation on a geometry (a Feature, by H, key or record id): `simplify` {"metres": n} (fewer
    points, none moved more than n), `to_point` (its centre), `to_bbox` (its extent, as an area),
    `circle` {"metres": n} (a point to an approximate area), `fix` (close rings, wind them, round, swap
    [lat, lon] written the wrong way round). Replaces the geometry (the old one stays in history), or
    with `as_new` makes a new geometry that cites it. Preview; call again with confirm=true."""
    return _run(lambda: geo.transform_geometry(core.open_archive(archive), feature, op, args,
                                               "new" if as_new else "replace", confirm))


@tool()
def draw_feature(geometry: dict, archetype: str | None = None, entity: str | None = None, new: dict | None = None,
                 name: str | None = None, aspect: str | None = None, kind: str | None = None, confirm: bool = False,
                 archive: str | None = None) -> dict:
    """Draw a place the way the Atlas's + Feature does: a Feature (`geometry`, GeoJSON [lon, lat]; precision `drawn`) and a GeoLink at `aspect`. Say what it is with an `archetype` id of the archive's archetypes.yaml that carries a geometry, or `kind` point | line | area. Site it at an existing entry (`entity`) or make a new one (`new`: {"name": …, "schema"?: …}). `name` names the Feature; `aspect` is a role of geo.yaml. A new location is a point unless the archetype is an area or line: never box a point. Preview shows the lines, warnings and the OSM tag; call again with confirm=true once the person agrees. More: guide("geo-drawing", "draw_feature")"""
    return _run(lambda: geo.draw_feature(core.open_archive(archive), geometry, archetype, entity, new, name, aspect, kind, confirm))


@tool()
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


@tool()
def delete_feature(feature: str, confirm: bool = False, archive: str | None = None) -> dict:
    """Remove a drawn Feature (by H, key or record id) and the GeoLinks that use it. Only shapes drawn or given as
    GeoJSON here are deleted, never ones read from OSM or the register. The entries that used it lose that place;
    nothing else is touched, and history keeps it all (`history_restore`). The preview lists each entry that loses
    a place; call again with confirm=true once the person agrees."""
    return _run(lambda: geo.delete_feature(core.open_archive(archive), feature, confirm))


@tool()
def geo_contexts(archive: str | None = None) -> dict:
    """The geographic contexts installed in this archive (Bazaar packages that carry boundary or feature layers, such as
    districts or a front line): per package its version and licence, and per layer its name, label, feature
    count, levels and attribution. Use a layer's name in `geo_summarize by="context:<name>"` and
    `geo_query within={"context": <name or key>}`. Read-only; installing one needs the person (`package_install`)."""
    return _run(lambda: geo.geo_contexts(core.open_archive(archive)))


@tool()
def geo_summarize(by: str, schema: str | None = None, tag: str | None = None, as_of: str | None = None,
                  limit: int = 100, archive: str | None = None) -> dict:
    """How many entries lie in each area: `by` "country", "admin1" (region) or "context:<name>" (the features of a
    context layer, from `geo_contexts`). Each row gives the area's `name`, `key`, `count` and three example entries,
    biggest first; `unplaced` counts entries with no place. An entry counts under its primary place, and where that
    is a point it is placed by the area that holds it. Filter by `schema`, by `tag` (an archetype id: entries that
    fit it or were confirmed as it) and by `as_of` (a date: only geo links in force then). Read-only."""
    return _run(lambda: geo.geo_summarize(core.open_archive(archive), by, schema, tag, as_of, limit))


@tool()
def geo_register_status(archive: str | None = None) -> dict:
    """The boundary layers kept on this machine (what `hydra-ctl geo register status` prints): per layer its label,
    version, licence, whether it is installed or packed with hydra, size and whether it is critical, plus
    `missing_critical` (layers the Atlas needs that are absent). Read-only; installing a layer downloads, so ask the person."""
    return _run(lambda: geo.geo_register_status(core.open_archive(archive)))
