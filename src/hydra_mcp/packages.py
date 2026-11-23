"""packages.py — packages of geo layers, icons, archetypes and themes, for the agent: thin over hydra.packages
(the same functions `hydra-ctl package` and the Bazaar page run). Preview unless `confirm`."""
from __future__ import annotations

from pathlib import Path

from hydra_mcp.core import AGENT, IngestError

NEXT = "confirm with the person, then call again with confirm=true"


def packages(root: Path) -> dict:
    """The archive's lock (what it uses), the machine's store (shared bytes), the registries and what they offer."""
    from hydra import packages as P
    try:
        lock = P.read_lock(root)
        offer = P.state(root)
    except P.PackageError as e:
        raise IngestError(str(e)) from None
    return {"in_store": [{k: p[k] for k in ("name", "version", "scope")} | {"sha256": p["sha256"][:12]} for p in P.installed(root)],
            "lock": lock, "registries": P.registries(),
            "available": [{k: r.get(k) for k in ("name", "version", "licence", "provides", "description")}
                          | {"installed": r["installed"], "update": r["update"]} for r in offer]}


def package_install(root: Path, name: str, confirm: bool = False, scope: str = "machine") -> dict:
    """Get `name` from the registries for this archive: bytes into the shared store, a line in its lock (preview:
    licence, what it provides, where it writes)."""
    from hydra import history
    from hydra import packages as P
    from hydra.wiki import bazaar
    try:
        out = bazaar.preview(root, "install", name, scope)
        if out["needs"]:
            raise IngestError(f"{name} needs {', '.join(out['needs'])} installed first")
        if not confirm:
            return {**out, "next": NEXT}
        row = P.install(name, scope, root)
    except P.PackageError as e:
        raise IngestError(str(e)) from None
    return {**out, "installed": f"{row['name']} {row['version']}",
            "snapshot": history.auto(root, "hydra-mcp package_install", who=AGENT)}
