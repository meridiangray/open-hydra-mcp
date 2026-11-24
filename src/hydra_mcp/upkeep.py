"""upkeep.py — keeping an archive current: `upgrade` (old formats and old names, previewed), and the Atlas's archive
layers (`layer_add`, `layer_list`, `layer_remove`): GeoJSON drawn on the map that is not entities (hydra/geo/layers.py)."""
from __future__ import annotations

from pathlib import Path

from hydra_mcp.core import IngestError
from hydra.build import run as build
from hydra.archive import upgrade as up
from hydra.geo import layers
from hydra.universe import build as ubuild
from hydra_mcp import workflows

NEXT = "confirm with the person, then call again with confirm=true"


def upgrade(root: Path, confirm: bool = False) -> dict:
    """What `hydra-ctl upgrade` would change (an older format, records under an old schema name), or, confirmed, the
    changes as one history step and a rebuild."""
    lines: list[str] = []
    up.run(root, confirm, say=lines.append)
    steps = [l.strip()[2:] for l in lines if l.strip().startswith("- ")]
    if not steps:
        return {"changes": [], "written": False, "note": lines[0] if lines else "nothing to do"}
    if not confirm:
        return {"changes": steps, "written": False, "next": NEXT}
    build.build_archive(root)
    ubuild.build(root)
    workflows.hook_log(root, f"upgrade: {len(steps)} change(s)")
    return {"changes": steps, "written": True, "result": lines, "note": "rebuilt; the wiki shows the change after wiki_serve reloads"}


def layer_list(root: Path) -> dict:
    return {"layers": layers.listing(root)}


def layer_add(root: Path, file: str, name: str, attribution: str = "", licence: str = "", confirm: bool = False) -> dict:
    """Read a GeoJSON file (a FeatureCollection, a Feature or a geometry; a projection hydra converts is converted to
    lon/lat), report what would be drawn, and, confirmed, add it as an archive layer: one history step."""
    f = Path(str(file or "").strip())
    if not f.is_file():
        raise IngestError(f"{f} not found: give the file's full path")
    try:
        doc, dropped, why = layers.clean(f.read_bytes())
    except layers.Refused as e:
        raise IngestError(str(e)) from None
    out = {"file": str(f), "name": name, "features": len(doc.get("features") or ()), "dropped": dropped,
           **({"converted": why} if why else {}), "attribution": attribution, "licence": licence, "written": False}
    if not attribution or not licence:
        out["warning"] = "say where the data comes from and its licence (attribution, licence): the map credits it"
    if not confirm:
        return {**out, "next": NEXT}
    try:
        got = layers.add(root, f.read_bytes(), name, attribution, licence)
    except layers.Refused as e:
        raise IngestError(str(e)) from None
    workflows.hook_log(root, f"layer_add {got.get('id')}")
    return {**out, "written": True, "layer": got}


def layer_remove(root: Path, layer: str, confirm: bool = False) -> dict:
    have = {x["id"]: x for x in layers.listing(root)}
    if layer not in have:
        raise IngestError(f"no layer '{layer}' (layer_list lists them: {', '.join(have) or 'none'})")
    out = {"layer": layer, "name": have[layer]["name"], "count": have[layer].get("count"), "written": False}
    if not confirm:
        return {**out, "next": NEXT}
    try:
        layers.remove(root, layer)
    except layers.Refused as e:
        raise IngestError(str(e)) from None
    return {**out, "written": True}
