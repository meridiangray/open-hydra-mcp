"""tools/checks.py — the `checks` toolset: the lag-check's three reviewers and the page image, all read-only
(hydra-docs plans/lag-check.md §3, §4b; step LC4).

    check_values   dates, amounts, names and basis words against each record's own quote and the archive
    check_rules    each record against the archive's rule files (kinship, capacity, directions, vocabularies)
    check_graph    the shape of the relationship graph and the ties it suggests are missing; with `since`, what changed
    source_page_image   one page of a kept PDF as a picture, to settle an unclear case

None of them builds or writes. When the universe pages are not current they answer `stale: true` and no findings
(`universe_build` brings them up to date); the checks never do it for you.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from hydra.api import sources as hsources
from hydra.checks import graph, rules, values
from mcp.server.fastmcp import Image

from hydra_mcp import core
from hydra_mcp.core import IngestError
from hydra_mcp.app import _run, tool

DPI_MIN, DPI_MAX, DPI_DEFAULT = 72, 200, 150


def check_graph_result(root: Path, scope, since) -> dict:
    out = graph.graph_metrics(root, scope)
    snap = out.pop("snapshot", None)
    if snap:
        snap = {k: v for k, v in snap.items() if k != "nodes"}      # what `since` needs; the per-node table stays out
    if since is not None and not out["stale"]:
        d = graph.graph_delta(root, since, snap, scope)
        out["findings"] = out["findings"] + d["findings"]
        out["delta"] = d["delta"]
    out["snapshot"] = snap
    return out


def page_image(root: Path, source: str, page: int, dpi: int = DPI_DEFAULT) -> list:
    """[caption, Image] for one page of a kept PDF; raises IngestError with a plain message otherwise."""
    rec = hsources.existing_source(root, source)
    names = (rec.get("properties") or {}).get("fileName") or ()
    pdf = next((root / hsources.SOURCE_FILES / rec["collection"] / n for n in names
                if str(n).lower().endswith(".pdf") and (root / hsources.SOURCE_FILES / rec["collection"] / n).is_file()), None)
    if pdf is None:
        raise IngestError(f"source '{source}' is not a kept PDF: only a kept PDF file has pages to show")
    if not isinstance(page, int) or page < 1:
        raise IngestError(f"page {page} is not a page number: pages start at 1")
    tool = shutil.which("pdftoppm")
    if not tool:
        raise IngestError("pdftoppm (poppler) is not installed on this machine, so no page can be drawn")
    dpi = max(DPI_MIN, min(DPI_MAX, int(dpi)))
    with tempfile.TemporaryDirectory(prefix="hydra-page-") as tmp:
        stem = Path(tmp) / "p"
        run = subprocess.run([tool, "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-singlefile",
                              str(pdf), str(stem)], capture_output=True, text=True, timeout=60)
        png = stem.with_suffix(".png")
        if run.returncode or not png.is_file():
            if "range" in (run.stderr or "").lower() or "page" in (run.stderr or "").lower():
                raise IngestError(f"page {page} is out of range for source '{source}'")
            raise IngestError(f"page {page} of source '{source}' could not be drawn: {(run.stderr or '').strip()[:200]}")
        data = png.read_bytes()
    return [f"{source}, PDF page {page}, {dpi} dpi. A picture is for looking: quote only text read through `read_source`.",
            Image(data=data, format="png")]


@tool(name="check_values")
def check_values_tool(records: list[str] | None = None, scope: list[str] | None = None,
                      archive: str | None = None) -> dict:
    """Read-only check of dates, amounts, names and basis words (`reported`, `claimed`, `inferred`) against each record's own quote and the rest of the archive. `records` limits it to those record ids (omit for all); `scope` is the same limit by another name, for the page flow's window (`records` wins). Returns `findings` ({check, severity, entity, records, rule, what, fix}), `counted` and `stale`. Never builds or writes: when the archive's pages are not current it returns `stale: true` and no findings (run `universe_build`)."""
    return _run(lambda: values.value_check(core.open_archive(archive), records if records is not None else scope))


@tool(name="check_rules")
def check_rules_tool(records: list[str] | None = None, scope: list[str] | None = None,
                     archive: str | None = None) -> dict:
    """Read-only check of each record against the archive's own rule files: kinship words and direction, Representation capacity, which entity types a property allows, vocabularies and positions. `records` limits it to those record ids (omit for all); `scope` is the same limit by another name (`records` wins). Returns `findings` ({check, severity, entity, records, rule, what, fix}), `counted` and `stale`. A suggested fix is a suggestion: read the sentence before amending. Never builds or writes: when the archive's pages are not current it returns `stale: true` and no findings."""
    return _run(lambda: rules.rule_check(core.open_archive(archive), records if records is not None else scope))


@tool(name="check_graph")
def check_graph_tool(scope: list[str] | None = None, since: dict | None = None,
                     archive: str | None = None) -> dict:
    """Read-only look at the relationship graph: its `shape` (hubs, stars, core, bridges) and `findings` where a shape plus a sentence says a tie may be missing. A shape alone is never a finding. Each finding names its entities in `entities` (H ids) and `entity_records`. `scope` limits findings to those record ids and the entities they tie. Returns a `snapshot`; pass it back as `since` on a later call to also get `delta` (entities and ties added since) and its findings. Never builds or writes: when the archive's pages are not current it returns `stale: true` and no findings."""
    return _run(lambda: check_graph_result(core.open_archive(archive), scope, since))


@tool(name="source_page_image")
def source_page_image_tool(source: str, page: int, dpi: int = DPI_DEFAULT, archive: str | None = None) -> list:
    """One page of a kept PDF source as a PNG picture, `page` counted from 1 in the PDF file (what `cite` calls `pdfPages`), `dpi` 72 to 200 (150 by default). For settling an unclear case only: a title in a list or a post, which place a name means, a garbled date or amount, a name split across a line, a page the text reads as empty. Say what you saw. The picture is never a quote: quotes come only from `read_source`; text the picture shows and the text layer lacks is a question for the person, never a new note. Read-only; refuses a source that is not a kept PDF and a page out of range."""
    return _run(lambda: page_image(core.open_archive(archive), source, page, dpi))
