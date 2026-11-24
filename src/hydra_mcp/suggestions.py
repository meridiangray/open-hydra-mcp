"""suggestions.py — the Suggestions engine (hydra/suggest.py) as MCP tools: the same list a person sees on a page.

Reading (no writes): `suggestions` (local data only), `cast` (one cast's candidates), `enrichers`, and `probe`
(asks the outside source once and keeps the raw answer). Writing: `dismiss_suggestion` (a `not`), and
`apply_suggestion`, which only runs the existing tool the suggestion names, previewing first. The tools themselves are
in `tools/enrich.py`.
"""
from __future__ import annotations

from pathlib import Path

from hydra.enrich import enrichlog, suggest
from hydra.api.suggestions import run_tool as _run_tool  # noqa: F401  (moved: plans/imports.md I2c)

from hydra_mcp import core, workflows
from hydra_mcp.core import IngestError

NEXT = "confirm with the person, then call again with confirm=true"


def _s(fn):
    try:
        return fn(suggest)
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: ")) from None


def _body(root: Path, entity: str) -> str:
    """The one page `entity` names (`core.resolve_entity`): a shared title is refused with its Hs, never the first."""
    return core.resolve_entity(root, entity).body


def suggestions(root: Path, entity: str) -> dict:
    body = _body(root, entity)
    return {"entity": entity, "body": body, "suggestions": _s(lambda m: m.suggestions(root, body)),
            "next": "preview a cast with `cast`, a probe with `probe`; `apply_suggestion` writes it with the tool it names"}


def cast(root: Path, entity: str, rule: str, value: str) -> dict:
    body = _body(root, entity)
    return _s(lambda m: m.cast(root, body, rule, value))


def enrichers(root: Path) -> dict:
    return {"enrichers": _s(lambda m: m.enrichers(root))}


def probe(root: Path, entity: str, enricher: str, refresh: bool = False, query: str | None = None,
          raw: bool = False) -> dict:
    """The probe as a short answer: its mapped rows (field, now, new, reference) and the rest of what it mapped;
    the outside source's whole raw answer only with `raw`."""
    body = _body(root, entity)
    got = _s(lambda m: m.probe(root, body, enricher, refresh=refresh, query=query))
    if raw:
        return got
    mapped = dict(got.get("mapped") or {})
    out = {k: v for k, v in got.items() if k not in ("raw", "mapped")}
    if "diff" in mapped:
        out["rows"] = [{"field": r.get("property"), "now": r.get("now"), "new": r.get("value"),
                        "reference": r.get("reference")} for r in mapped.pop("diff")]
    out["mapped"] = mapped
    out["next"] = "`raw=true` returns the outside source's whole answer"
    return out


def dismiss(root: Path, entity: str, id: str, confirm: bool = False) -> dict:
    body = _body(root, entity)
    if not confirm:
        return {"would_dismiss": id, "entity": entity, "next": NEXT}
    out = _s(lambda m: m.dismiss(root, body, id))
    workflows.hook_log(root, f"dismiss suggestion {id} on {entity}")
    return out


def apply(root: Path, entity: str, id: str, picks: dict | None = None, confirm: bool = False) -> dict:
    """Run the tool a suggestion names, its arguments filled from `picks`. A preview unless `confirm`."""
    body = _body(root, entity)
    plan = _s(lambda m: m.apply(root, body, id, picks or {}))
    tool, args = plan.get("tool"), dict(plan.get("args") or {})
    if not tool:
        raise IngestError(plan.get("note") or f"no operation writes '{id}' yet; read it and write the records with `save`")
    missing = [k for k, v in args.items() if v is None and k not in ("source", "quote")]
    if missing:
        raise IngestError(f"'{id}' still needs {', '.join(missing)}: `probe` it first")
    out = {"tool": tool, "args": args}
    if not confirm:
        if tool == "save":
            out["check"] = core.check_records(root, args["records"])
        return {**out, "next": NEXT}
    return {**out, "result": _s(lambda m: m.perform(root, body, id, tool, args, lambda: _run_tool(root, tool, args), by="mcp"))}


def enrichments(root: Path, entity: str, offset: int = 0, limit: int = 100) -> dict:
    """The ledger of one entry: what each Enrich apply wrote, newest first, and whether it is hidden."""
    body = _body(root, entity)
    shown, paging = core.page(enrichlog.entries(root, body), offset, limit)
    return {"entity": entity, "body": body, **paging, "enrichments": shown,
            "next": "`enrichment_hide` keeps the data and leaves it off the page; `enrichment_delete` removes it"}


def enrichment_hide(root: Path, entity: str, id: str, hidden: bool = True, confirm: bool = False) -> dict:
    body = _body(root, entity)
    row = next((r for r in enrichlog.entries(root, body) if r["id"] == id), None)
    if row is None:
        raise IngestError(f"nothing was added as '{id}' to {entity}: `enrichments` lists the ids")
    if not confirm:
        return {"would_hide" if hidden else "would_show": id, "enricher": row["enricher"], "wrote": row.get("wrote"), "next": NEXT}
    out = _s(lambda m: enrichlog.hide(root, body, id, hidden))
    workflows.hook_log(root, f"{'hide' if hidden else 'show'} enrichment {id} on {entity}")
    return out


def enrichment_delete(root: Path, entity: str, id: str, confirm: bool = False) -> dict:
    body = _body(root, entity)
    plan = _s(lambda m: enrichlog.plan(root, body, id))
    if not confirm:
        return {"would_delete": id, "label": plan["label"], "plan": plan, "lines": enrichlog.lines(plan),
                "next": NEXT + "; one history step, undo with `history_restore`"}
    out = _s(lambda m: enrichlog.delete(root, body, id))
    workflows.hook_log(root, f"delete enrichment {id} on {entity}")
    return out


def suggestions_reset(root: Path, entity: str, confirm: bool = False) -> dict:
    body = _body(root, entity)
    if not confirm:
        return {"would_forget": enrichlog.reset_plan(root, body), "next": NEXT}
    out = _s(lambda m: enrichlog.reset(root, body))
    workflows.hook_log(root, f"reset suggestions on {entity}")
    return {"forgot": out}


def wikidata_purge(root: Path, entity: str, forget_match: bool = True, confirm: bool = False) -> dict:
    """Remove everything Wikidata added to one entry, ledger or not. A preview unless `confirm`."""
    body = _body(root, entity)
    plan = _s(lambda m: enrichlog.purge_plan(root, body, forget_match))
    if enrichlog.purge_empty(plan):
        return {"entity": entity, "nothing": "Wikidata added nothing to this entry"}
    if not confirm:
        return {"would_purge": plan, "lines": enrichlog.purge_lines(plan),
                "next": NEXT + "; one history step, undo with `history_restore`"}
    out = _s(lambda m: enrichlog.purge(root, body, forget_match))
    workflows.hook_log(root, f"purge Wikidata from {entity}")
    return {"purged": out, "lines": enrichlog.purge_lines(out)}
