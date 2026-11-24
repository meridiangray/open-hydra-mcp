"""tools/admin.py — the `admin` tool set: archive settings, scope, packages, upgrades, export and pack, history,
and building the universe."""
from __future__ import annotations

from hydra_mcp import agent, core, data, packages as pk, pipeline, upkeep
from hydra_mcp.app import _run, tool


@tool()
def upgrade(confirm: bool = False, archive: str | None = None) -> dict:
    """Bring the archive up to date: an older format, or records still under an old schema name (Siting is now
    GeoLink). Without `confirm` it lists the changes; with it they are made as one history step and the archive is
    rebuilt. `check` says when an archive needs it."""
    return _run(lambda: upkeep.upgrade(core.open_archive(archive), confirm))


@tool()
def packages(archive: str | None = None) -> dict:
    """Packages (themes, map styles, icon sets, symbology, archetypes, reference layers). Installs are per archive:
    `lock` is what THIS archive uses (.hydra/packages/lock.yaml); `in_store` is what the machine's shared store holds
    (fetched once, used by every archive that locks it); `available` is what the registries offer, each marked
    `installed` when this archive's lock names it."""
    return _run(lambda: pk.packages(core.open_archive(archive)))


@tool()
def package_install(name: str, confirm: bool = False, scope: str = "machine", archive: str | None = None) -> dict:
    """Get a package (owner/name) from the registries for THIS archive: the bytes go once into the machine's shared
    store (`scope` machine) or the universe's backdrop, and a line goes into the archive's lock; only locked packages
    take part in the archive's lookups. Preview shows licence, what it provides, what it replaces, where the bytes
    and the lock line go; call again with confirm=true once the person agrees. Taking a package out of an archive
    (Bazaar Remove, `hydra-ctl package remove`) deletes its lock line only; `hydra-ctl package prune` clears store
    folders no archive uses. Nothing here touches records."""
    return _run(lambda: pk.package_install(core.open_archive(archive), name, confirm, scope))


@tool()
def history_log(limit: int = 20, archive: str | None = None) -> list[dict]:
    """The archive's snapshots, newest first: who changed what (every save, answer and
    amend made here is one, by agent:hydra-mcp)."""
    return _run(lambda: agent.history_log(core.open_archive(archive), max(1, min(limit, 200))))


@tool()
def history_diff(a: str = "HEAD", b: str | None = None, archive: str | None = None) -> list[dict]:
    """What changed between two snapshots (`b` left out: the files as they are now):
    each file, and inside a collection the records added, removed and changed."""
    return _run(lambda: agent.history_diff(core.open_archive(archive), a, b))


@tool()
def save_changes(message: str, description: str = "", confirm: bool = False, archive: str | None = None) -> dict:
    """Save the work as one named change in history: the steps since the last save fold under it, so a
    task reads as one change. Call it at the end of a task. Previews what it covers unless confirm=true."""
    return _run(lambda: agent.save_changes(core.open_archive(archive), message, description, confirm))


@tool()
def history_restore(ref: str, paths: list[str] | None = None, confirm: bool = False,
                    archive: str | None = None) -> dict:
    """Put the archive's files (or just `paths`) back as they were at snapshot `ref`
    (an id, or HEAD~1 for one change back). Nothing is lost: the restore is a new
    snapshot. Previews unless confirm=true."""
    return _run(lambda: agent.history_restore(core.open_archive(archive), ref, paths, confirm))


@tool()
def universe_build(archive: str | None = None) -> dict:
    """Build the universe from the last archive build: which records are one entity, each
    entity's canonical id (H) and the wiki pages. `save` and `amend_records` rebuild the
    archive, not the pages: run this (or `wiki_serve`, which runs it when the pages are
    stale) to see the change. Returns the counts by state and flag, same-name pairs, merges
    a decision blocked, and warnings."""
    return _run(lambda: pipeline.universe_build(core.open_archive(archive)))


@tool()
def scope(entity: str | None = None, archive: str | None = None) -> dict:
    """What the archive is about (.hydra/rules/scope.yaml): how many entries are in scope, the
    context ones (kept in the data, named as text on the pages that mention them, listed
    nowhere), and for `entity` (an H, key, record id or title) whether it is in scope and why
    ("Ownership from <a seed entity>")."""
    return _run(lambda: pipeline.scope(core.open_archive(archive), entity))


@tool()
def set_scope(include: list[str] | None = None, exclude: list[str] | None = None, seeds: list[str] | None = None,
              confirm: bool = False, archive: str | None = None) -> dict:
    """Change what the archive is about: add entries to `include` or `exclude` (Hs, keys, record
    ids, titles, or `collection:<name>`), or set the seed collections. The preview lists what
    would come into scope and what would leave it; confirm=true (with the person's agreement)
    writes scope.yaml and rebuilds the pages."""
    return _run(lambda: pipeline.set_scope(core.open_archive(archive), include, exclude, seeds, confirm))


@tool(name="archive_settings")
def archive_settings_tool(set: dict | None = None, confirm: bool = False, archive: str | None = None) -> dict:
    """The archive's text settings, as the Archive page holds them: name, title, sub, about, description, theme, view, rail_shape and title_style. With no `set` it returns them. With `set` ({"about": "..."}: only what changes) it previews each change as from/to; call again with confirm=true once the person agrees. A name or title change rebuilds the wiki. One history step. More: guide("tools", "archive_settings")"""
    return _run(lambda: data.archive_settings(core.open_archive(archive), set, confirm))


@tool(name="export")
def export_tool(format: str, out: str, folder: str, ids: str = "record", replace: bool = False, confirm: bool = False,
                archive: str | None = None) -> dict:
    """Write the archive's compiled entities to a file: `format` ftm (standard FollowTheMoney lines), hydra-ftm
    (links as names), csv (a folder with nodes.csv and edges.csv) or graphml. `folder` is the folder the person named
    for the output and `out` a path inside it; anything resolving outside it is refused, and an existing file is
    kept unless replace=true. `ids`: record (default) or h (canonical ids). Reads the archive, changes nothing in
    it. Previews the target unless confirm=true. Errors come back as {error, why, do}."""
    return _run(lambda: data.export_(core.open_archive(archive), format, out, folder, ids, replace, confirm))


@tool(name="pack")
def pack_tool(out: str, folder: str, history: bool = True, replace: bool = False, confirm: bool = False,
              archive: str | None = None) -> dict:
    """Pack the archive into one portable .hydra file (a zip with its build and, unless history=false, its history).
    `folder` is the folder the person named for the output and `out` a file name inside it (.hydra is added);
    anything resolving outside the folder is refused, and an existing file is kept unless replace=true. Changes
    nothing in the archive. Previews the target unless confirm=true. Errors come back as {error, why, do}."""
    return _run(lambda: data.pack_(core.open_archive(archive), out, folder, history, replace, confirm))
