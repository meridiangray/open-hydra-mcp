"""geo.py — where entities are, for the agent: thin over hydra.geo (the same functions `hydra-ctl geo` runs).

Reading and asking (no network, no writes): geo_report, geo_locate, geo_aspects, geo_query, geo_measure, geo_resolve
(the machine's register: which country, region, district and town hold a point; which a name may be).
Writing (preview unless `confirm`; snapshot by `agent:hydra-mcp`): geo_enable, site, set_primary,
edit_geolink, transform_geometry, draw_feature. Lookup and enrichment from outside providers come later
(hydra-docs/docs/plans/geo-integration.md, section 3.3).
"""
from __future__ import annotations

from pathlib import Path
from hydra.api.geolinks import _check_geolink_inputs, _fresh, _geo, site  # noqa: F401  (moved: plans/imports.md I2c)

from hydra_mcp.core import AGENT, IngestError
import shutil
from hydra.build import run as build
from hydra.schema import loader as schema
from hydra.archive import layout, resources, history, collections_io
from hydra.geo import query, aspects, bind, draw, ops, register
from hydra.universe import build as ubuild
from hydra_mcp import workflows

NEXT = "confirm with the person, then call again with confirm=true"


def geo_report(root: Path, top: int = 25, include_entities: bool = False) -> dict:
    _fresh(root)
    out = _geo(query.report, root, top, include_entities=include_entities)
    if not _has_schema(root):
        out["note"] = "this archive was made before geo: `geo_enable` installs Place, Feature and GeoLink"
    return out


def geo_locate(root: Path, entity: str, as_of: str | None = None) -> dict:
    _fresh(root)
    return _geo(query.locate, root, entity, as_of)


def geo_query(root: Path, within=None, near=None, containing=None, schema: str | None = None,
              role: str | None = None, via: str | None = None, primary_only: bool = True, as_of: str | None = None,
              include_context: bool | None = None, limit: int = 50, offset: int = 0) -> dict:
    _fresh(root)
    return _geo(query.query, root, within=within, near=near, containing=containing, schema=schema, role=role,
                via=via, primary_only=primary_only, as_of=as_of, include_context=include_context,
                limit=max(1, min(limit, 200)), offset=max(0, offset))


def geo_aspects(root: Path, entity: str) -> dict:
    """The places of one entry, one per aspect (home, posting, seat, jurisdiction...): what fills each, which is primary,
    and what the register offers for the empty ones. Writing stays with `site`, `edit_geolink` and `set_primary`."""
    _fresh(root)
    return _geo(aspects.aspects, root, entity)


def geo_measure(root: Path, a, b=None) -> dict:
    _fresh(root)
    return _geo(query.measure, root, a, b)


def geo_resolve(root: Path, point=None, entity: str | None = None, name: str | None = None, scope: str | None = None,
                level: str | None = None) -> dict:
    _fresh(root)
    out = _geo(bind.resolve, root, point=point, entity=entity, name=name, scope=scope, level=level)
    missing = [k for k, v in out.get("layers", {}).items() if not v]
    if missing:
        out["note"] = (f"not installed on this machine: {', '.join(missing)} (`hydra-ctl geo register install <layer>`, "
                       "with the person's agreement: it downloads)")
    return out


def _has_schema(root: Path) -> bool:
    schema.load(root)
    return all(t in schema.SCHEMA for t in ("Place", "Feature", "GeoLink"))


def geo_enable(root: Path, confirm: bool = False) -> dict:
    """Install the geo schema (Place, Feature, GeoLink), its matching rules and rules/geo.yaml in an archive
    made before them: `hydra-ctl defaults restore geo`. Files the archive already has are kept."""
    files = resources.DEFAULTS["geo"]
    have = [f for f in files if (root / f).is_file()]
    missing = [f for f in files if f not in have]
    out = {"installs": missing, "keeps": have}
    if not missing:
        return {**out, "note": "geo is installed"}
    if not confirm:
        return {**out, "next": NEXT}
    for rel in missing:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resources.TEMPLATE / rel, dest)
    build.build_archive(root)
    ubuild.build(root)
    workflows.hook_log(root, f"geo_enable: installed {len(missing)} type(s)")
    return {**out, "written": len(missing), "snapshot": history.auto(root, "hydra-mcp geo_enable", who=AGENT),
            "note": f"places and roles: {layout.GEO}"}



def _geolink_locations(root: Path, locations):
    """A geolink's record id stands for the place it sites: `locations` with those replaced by their location."""
    if locations in (None, "") or locations in ("auto", "clear"):
        return locations
    refs = locations if isinstance(locations, list) else [x.strip() for x in str(locations).split(",") if x.strip()]
    out = []
    for ref in refs:
        got = [r for _, r in collections_io.find(root, ref) if r.get("schema") == "GeoLink"] if ref not in ("auto", "clear") else []
        loc = ((got[0].get("properties") or {}).get("location") or [None])[0] if got else None
        out.append(loc or ref)
    return out


def set_primary(root: Path, entity: str, locations, confirm: bool = False) -> dict:
    _fresh(root)
    locations = _geolink_locations(root, locations)
    refs = [entity] + ([] if locations in (None, "", "auto", "clear") else
                       locations if isinstance(locations, list) else [x.strip() for x in str(locations).split(",") if x.strip()])
    try:                                              # an entity saved since the last build: build first
        m = query.load(root)
        for ref in refs:
            if ref not in ("auto", "clear"):
                m.resolve(ref)
    except query.GeoError:
        ubuild.build(root)
    out = _geo(bind.set_primary, root, entity, locations, confirm, AGENT)
    if confirm and "written" in out:
        workflows.hook_log(root, f"set_primary {entity} -> {locations}")
    return out


def edit_geolink(root: Path, geolink: str, changes: dict, confirm: bool = False) -> dict:
    _fresh(root)
    out = _geo(bind.edit_geolink, root, geolink, changes, confirm, AGENT)
    if confirm and out.get("written"):
        workflows.hook_log(root, f"edit_geolink {geolink}")
    return out


def transform_geometry(root: Path, feature: str, op: str, args: dict | None = None, as_: str = "replace",
                       confirm: bool = False) -> dict:
    _fresh(root)
    out = _geo(bind.transform, root, feature, op, args, as_, confirm, AGENT)
    if confirm and out.get("written"):
        workflows.hook_log(root, f"transform_geometry {feature}: {op} ({as_})")
    return out


def draw_feature(root: Path, geometry: dict, archetype: str | None = None, entity: str | None = None, new: dict | None = None,
                 name: str | None = None, aspect: str | None = None, kind: str | None = None, confirm: bool = False) -> dict:
    """What the Atlas's + Feature writes: a Feature (GeoJSON geometry, the archetype's OSM tag, precision `drawn`) and a
    GeoLink at `aspect`, for an entry that exists (`entity`) or a new one of the archetype's schema (`new`)."""
    _fresh(root)
    data = {"geometry": geometry, "archetype": archetype, "kind": kind, "entity": entity, "new": new, "name": name,
            "aspect": aspect, "confirm": confirm}
    out = _geo(draw.write, root, {k: v for k, v in data.items() if v not in (None, "")}, AGENT)
    if not confirm:
        return {**out, "next": NEXT}
    workflows.hook_log(root, f"draw_feature {archetype or kind}: {name or (new or {}).get('name') or entity}")
    return out


# ---- move, delete, contexts, summaries, register (stream C) -------------------------------------------

def _fail(tool: str, e: Exception, do: str) -> dict:
    """The one error shape of these tools: {error, why, do}."""
    return {"error": f"{tool} did not run", "why": str(e), "do": do}


def move_feature(root: Path, entity: str | None = None, feature: str | None = None, geometry: dict | None = None,
                 delta_m: list | None = None, confirm: bool = False) -> dict:
    _fresh(root)
    try:
        out = _geo(ops.move, root, entity, feature, geometry, delta_m, confirm, AGENT)
    except IngestError as e:
        return _fail("move_feature", e, "name one entity or feature and give `geometry` or `delta_m`, then call again")
    if not confirm:
        return {**out, "next": NEXT}
    workflows.hook_log(root, f"move_feature {entity or feature}")
    return out


def delete_feature(root: Path, feature: str, confirm: bool = False) -> dict:
    _fresh(root)
    try:
        out = _geo(ops.delete, root, feature, confirm, AGENT)
    except IngestError as e:
        return _fail("delete_feature", e, "give the H or key of a drawn Feature (geo_locate lists an entry's shapes)")
    if not confirm:
        return {**out, "next": NEXT}
    workflows.hook_log(root, f"delete_feature {feature}")
    return out


def geo_contexts(root: Path) -> dict:
    return {"contexts": _geo(ops.contexts, root)}


def geo_summarize(root: Path, by: str, schema: str | None = None, tag: str | None = None, as_of: str | None = None,
                  limit: int = 100) -> dict:
    _fresh(root)
    try:
        return _geo(ops.summarize, root, by, schema, tag, as_of, 3, max(1, min(limit, 500)))
    except IngestError as e:
        return _fail("geo_summarize", e, "by is country, admin1 or context:<name>; geo_contexts lists the names")


def geo_register_status(root: Path) -> dict:
    st = register.store().status()
    layers = st["layers"]
    missing = [k for k, v in layers.items() if v["critical"] and not (v["installed"] or v["packaged"])]
    return {"home": st["home"], "layers": layers, "missing_critical": missing,
            **({"do": "ask the person to run `hydra-ctl geo register install <layer>` (it downloads)"} if missing else {})}
