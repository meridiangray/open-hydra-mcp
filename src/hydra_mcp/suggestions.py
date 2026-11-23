"""suggestions.py — the Suggestions engine (hydra/suggest.py) as MCP tools: the same list a person sees on a page.

Reading (no writes): `suggestions` (local data only), `cast` (one cast's candidates), `enrichers`, and `probe`
(asks the outside source once and keeps the raw answer). Writing: `dismiss_suggestion` (a `not`), and
`apply_suggestion`, which only runs the existing tool the suggestion names, previewing first.
"""
from __future__ import annotations

from pathlib import Path

from hydra_mcp import core
from hydra_mcp.core import IngestError

NEXT = "confirm with the person, then call again with confirm=true"


def _s(fn):
    from hydra import suggest
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
    from hydra_mcp import workflows
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
    from hydra import enrichlog
    body = _body(root, entity)
    from hydra_mcp import core
    shown, paging = core.page(enrichlog.entries(root, body), offset, limit)
    return {"entity": entity, "body": body, **paging, "enrichments": shown,
            "next": "`enrichment_hide` keeps the data and leaves it off the page; `enrichment_delete` removes it"}


def enrichment_hide(root: Path, entity: str, id: str, hidden: bool = True, confirm: bool = False) -> dict:
    from hydra import enrichlog
    body = _body(root, entity)
    row = next((r for r in enrichlog.entries(root, body) if r["id"] == id), None)
    if row is None:
        raise IngestError(f"nothing was added as '{id}' to {entity}: `enrichments` lists the ids")
    if not confirm:
        return {"would_hide" if hidden else "would_show": id, "enricher": row["enricher"], "wrote": row.get("wrote"), "next": NEXT}
    out = _s(lambda m: enrichlog.hide(root, body, id, hidden))
    from hydra_mcp import workflows
    workflows.hook_log(root, f"{'hide' if hidden else 'show'} enrichment {id} on {entity}")
    return out


def enrichment_delete(root: Path, entity: str, id: str, confirm: bool = False) -> dict:
    from hydra import enrichlog
    body = _body(root, entity)
    plan = _s(lambda m: enrichlog.plan(root, body, id))
    if not confirm:
        return {"would_delete": id, "label": plan["label"], "plan": plan, "lines": enrichlog.lines(plan),
                "next": NEXT + "; one history step, undo with `history_restore`"}
    out = _s(lambda m: enrichlog.delete(root, body, id))
    from hydra_mcp import workflows
    workflows.hook_log(root, f"delete enrichment {id} on {entity}")
    return out


def suggestions_reset(root: Path, entity: str, confirm: bool = False) -> dict:
    from hydra import enrichlog
    body = _body(root, entity)
    if not confirm:
        return {"would_forget": enrichlog.reset_plan(root, body), "next": NEXT}
    out = _s(lambda m: enrichlog.reset(root, body))
    from hydra_mcp import workflows
    workflows.hook_log(root, f"reset suggestions on {entity}")
    return {"forgot": out}


def wikidata_purge(root: Path, entity: str, forget_match: bool = True, confirm: bool = False) -> dict:
    """Remove everything Wikidata added to one entry, ledger or not. A preview unless `confirm`."""
    from hydra import enrichlog
    body = _body(root, entity)
    plan = _s(lambda m: enrichlog.purge_plan(root, body, forget_match))
    if enrichlog.purge_empty(plan):
        return {"entity": entity, "nothing": "Wikidata added nothing to this entry"}
    if not confirm:
        return {"would_purge": plan, "lines": enrichlog.purge_lines(plan),
                "next": NEXT + "; one history step, undo with `history_restore`"}
    out = _s(lambda m: enrichlog.purge(root, body, forget_match))
    from hydra_mcp import workflows
    workflows.hook_log(root, f"purge Wikidata from {entity}")
    return {"purged": out, "lines": enrichlog.purge_lines(out)}


def _run_tool(root: Path, tool: str, a: dict):
    from hydra_mcp import agent, geo, sources
    if tool == "site":
        return geo.site(root, a["geolinks"], confirm=True)
    if tool == "answer":
        return agent.answer(root, a["id"], a["choice"], True)
    if tool == "save":
        return core.ingest(root, a["records"], {}, None)
    if tool == "graduate_stub":
        from hydra_mcp import pipeline
        return pipeline.graduate(root, a["name"], a.get("as_schema") or "", True)
    if tool == "fetch_source":
        return sources.fetch(root, a["url"])
    if tool == "link_image":
        return core.link_image(root, a["image"], a["kind"], {"titled": a.get("titled")}, True)
    if tool == "swap_source":
        return agent.swap_source(root, a["collection"], a["record"], a["source"], a["quote"], True)
    if tool == "archetypes.decide":
        from hydra import archetypes
        return {"said": archetypes.decide(root, a["body"], a["archetype"], a["choice"])}
    if tool == "pin_upstream":                         # Match: the chosen Wikidata item becomes a key of the entry's record
        return agent.pin_upstream(root, a["collection"], a["record"], a["h"], True)
    from hydra import suggest
    if tool in suggest.LOCAL:                          # Compare, Lead, Resource: run by the engine itself
        return _s(lambda m: m.run(root, tool, a))
    raise IngestError(f"{tool} is not run from here; call it yourself with {a}")


def register(mcp, run) -> None:
    @mcp.tool(name="suggestions")
    def suggestions_tool(entity: str, archive: str | None = None) -> dict:
        """What could be done for one entry (by H, key, record id or title), from local data only, as the wiki's
        Suggestions drawer lists it. Graduate: Locate, Appoint, Affiliate, Identify, Classify (a value in the
        entry cast to a typed entity by a rule in casts.yaml, offered only when its lookup finds something).
        Enrich: Compare, Match, Lead, Portrait, Resource (probes declared in enrichers.yaml). Link: Merge, Resolve.
        Each has an `id`, a `tip`, a `preview` and `apply`: the existing tool that writes it (null when none does)."""
        return run(lambda: suggestions(core.open_archive(archive), entity))

    @mcp.tool(name="cast")
    def cast_tool(entity: str, rule: str, value: str, archive: str | None = None) -> dict:
        """One Graduate cast for a value (the entry's own, or one you give): the candidates the rule's lookups
        return (archive, universe, the local register), each with its source. Local data only; writes nothing."""
        return run(lambda: cast(core.open_archive(archive), entity, rule, value))

    @mcp.tool(name="enrichers")
    def enrichers_tool(archive: str | None = None) -> dict:
        """The enrichers this archive declares (.hydra/rules/enrichers.yaml): id, label, what an entry needs, source."""
        return run(lambda: enrichers(core.open_archive(archive)))

    @mcp.tool(name="probe")
    def probe_tool(entity: str, enricher: str, refresh: bool = False, query: str | None = None,
                   archive: str | None = None, raw: bool = False) -> dict:
        """Run one enricher on one entry: ask its outside source (Wikidata, Wikipedia, Commons) once, keep the
        raw answer in .hydra/cache/probes/, and return it mapped onto fields (Compare: one row per field, what
        the entry has now and Wikidata's value). Match lists Wikidata candidates; `query` searches those words
        instead of the entry's name and context. Returns the mapped `rows` (field, now, new, reference), not the
        raw answer; `raw=true` adds it. Writes no records; `apply_suggestion` does."""
        return run(lambda: probe(core.open_archive(archive), entity, enricher, refresh, query, raw))

    @mcp.tool(name="apply_suggestion")
    def apply_tool(entity: str, id: str, picks: dict | None = None, confirm: bool = False,
                   archive: str | None = None) -> dict:
        """Write one suggestion through the tool it names (site, answer, save, fetch_source, link_image, portrait_import (downloads the Commons file, credits it),
        swap_source, graduate_stub, pin_upstream). `picks`: {"candidate": n} for a cast, Resolve or Match (the
        Wikidata item to key the entry by), {"rows": [...]} to keep
        some rows of a Compare. Previews the call unless confirm=true; confirm only with the person's agreement."""
        return run(lambda: apply(core.open_archive(archive), entity, id, picks, confirm))

    @mcp.tool(name="dismiss_suggestion")
    def dismiss_tool(entity: str, id: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Record that a suggestion is not wanted (`sug-<body>.<id>: rejected` in verdicts.yaml), so it is not
        offered again. Previews unless confirm=true."""
        return run(lambda: dismiss(core.open_archive(archive), entity, id, confirm))


    @mcp.tool(name="enrichments")
    def enrichments_tool(entity: str, archive: str | None = None, offset: int = 0, limit: int = 100) -> dict:
        """What Enrich added to one entry (H, key, record id or title), from its ledger (.hydra/enrich/<H>.jsonl): per
        apply, the id, enricher (Compare, Lead, Portrait, Match, Footnotes), source (Wikidata item, file page, article
        revision), time, who, whether it is hidden, and exactly what it wrote (record values, records, files, rules,
        sections). Applies made before the ledger existed are not listed. Paged: `offset`, `limit`. Reads only."""
        return run(lambda: enrichments(core.open_archive(archive), entity, offset, limit))

    @mcp.tool(name="enrichment_hide")
    def enrichment_hide_tool(entity: str, id: str, hidden: bool = True, confirm: bool = False,
                             archive: str | None = None) -> dict:
        """Leave what one enrichment added off the entry's page, keeping the data (a verdict `hide-<H body>.<id>`
        in verdicts.yaml; `hidden=false` shows it again). `id` is from `enrichments`. Previews unless confirm=true."""
        return run(lambda: enrichment_hide(core.open_archive(archive), entity, id, hidden, confirm))

    @mcp.tool(name="enrichment_delete")
    def enrichment_delete_tool(entity: str, id: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Remove exactly what one enrichment wrote: its record values or records, image file with its credit and
        rule, article section. A value another enrichment also wrote stays. The preview lists each removal; confirming
        takes one history step (undo with `history_restore`). `id` is from `enrichments`."""
        return run(lambda: enrichment_delete(core.open_archive(archive), entity, id, confirm))

    @mcp.tool(name="suggestions_reset")
    def suggestions_reset_tool(entity: str, confirm: bool = False, archive: str | None = None) -> dict:
        """Forget one entry's dismissed suggestions and kept probe answers, so every suggestion and enricher asks
        again. Writes nothing to records. Previews what would be forgotten unless confirm=true."""
        return run(lambda: suggestions_reset(core.open_archive(archive), entity, confirm))

    @mcp.tool(name="wikidata_purge")
    def wikidata_purge_tool(entity: str, forget_match: bool = True, confirm: bool = False,
                            archive: str | None = None) -> dict:
        """Start over from Wikidata: remove everything Wikidata added to one entry, whether or not the Enrich ledger
        lists it. Its records and claims in the `wikidata` collection (found by the entry's key and H, never by name),
        the values Compare and Match wrote, the source documents the import created when nothing else cites them,
        the `wikidata:Q...` key pin when `forget_match` (so Match is offered again), the Wikidata probe cache,
        dismissals, ledger lines and hides. Facts an own source states, a Commons portrait and a Wikipedia lead stay.
        The preview lists exactly what goes; confirming takes one history step (undo with `history_restore`)."""
        return run(lambda: wikidata_purge(core.open_archive(archive), entity, forget_match, confirm))
