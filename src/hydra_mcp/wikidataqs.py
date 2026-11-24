"""wikidataqs.py — the `wikidata` toolset: link the archive's entries to Wikidata as a set of questions for the person
(owner, 2026-11-21).

    wikidata_questions   entries with no Wikidata key, each with what the archive itself says about it and Wikidata's
                         candidates (the Match probe, kept in .hydra/cache/probes/wikidata-find/). Writes no records.
    wikidata_answer      the person's answer to one question. A candidate: its key is pinned to the entry's record
                         (the Match suggestion's `pin_upstream`, logged in the entry's ledger), then the item's picture
                         is imported when Wikidata names one (the Portrait probe: file, licence, artist), so a confirmed
                         match brings its picture without anyone viewing images here. `none`: the Match suggestion is
                         dismissed, so the entry is not asked again. A preview unless `confirm`.
    wikidata_status      how many entries are matched, still to ask, or answered "none".

It drives the same engine as the wiki's Suggestions drawer (hydra/suggest.py): one probe cache, one ledger, so a
person sees in the wiki exactly what an agent did here. The tools themselves are in `tools/wikidata.py`.
"""
from __future__ import annotations

from pathlib import Path

from hydra_mcp import core, workflows, suggestions
from hydra_mcp.core import IngestError
from hydra.enrich import suggest
from hydra.records import entities

MATCH, PORTRAIT = "wikidata-find", "commons"
NEXT = "put each question to the person (an entry, what the archive says, the candidates); call wikidata_answer with their pick"
FACTS = ("birthDate", "deathDate", "incorporationDate", "dissolutionDate", "date", "startDate", "endDate",
         "nationality", "country", "jurisdiction", "gender", "position", "description")


def _s(fn):
    try:
        return fn(suggest)
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: ")) from None


def _pages_current(root: Path) -> None:
    """The universe pages brought up to date first, as every reader of them does (`entities.catalog`)."""
    entities.catalog(root)


def _open(root: Path) -> list[dict]:
    """The archive's own entries Match is offered for: no Wikidata key yet, a record here to hold one, not answered
    "none" before."""
    _pages_current(root)

    def go(m):
        ctx = m._ctx(root)
        e = (m._enrichers(root) or {}).get(MATCH)
        if not e:
            raise SystemExit(f"hydra: this archive declares no '{MATCH}' enricher (.hydra/rules/enrichers.yaml)")
        out = []
        for body, page in sorted(ctx["pages"].items(), key=lambda kv: kv[1].get("title") or ""):
            if not m._record_id(page) or not m._needs(page, ctx, e.get("needs") or {}):
                continue
            if m._is(page, "Document"):                     # a kept source (a document, an article) is no entity to match
                continue
            if MATCH in m.dismissed(root, body):
                continue
            out.append(page)
        return out
    return _s(go)


def _facts(root: Path, page: dict) -> dict:
    """What the archive itself states about the entry, to tell it from a namesake: dates, country, posts held."""
    def go(m):
        vals = {p: m._values(page, p) for p in FACTS}
        return {"type": page.get("schema"), **{p: v for p, v in vals.items() if v},
                "context": m._context(page, m._ctx(root))[:6]}
    return _s(go)


def questions(root: Path, schema: str | None = None, limit: int = 5, offset: int = 0) -> dict:
    """Up to `limit` open questions (from `offset`), each asked of Wikidata once and kept."""
    pages = [p for p in _open(root) if not schema or p.get("schema") == schema]
    shown = pages[offset:offset + max(1, min(int(limit or 5), 20))]
    out = []
    for page in shown:
        try:
            got = _s(lambda m: m.probe(root, page["body"], MATCH))
            cands = (got.get("mapped") or {}).get("candidates") or []
        except IngestError as e:
            out.append({"entity": page["title"], "h": page["h"], "error": str(e)})
            continue
        out.append({"entity": page["title"], "h": page["h"], "archive_says": _facts(root, page),
                    "candidates": [{"n": i, "qid": c["qid"], "label": c.get("label"), "description": c.get("description"),
                                    "also": c.get("also") or []} for i, c in enumerate(cands)],
                    "asked": got.get("request", {}).get("query") or page["title"]})
    nxt = offset + len(shown)
    return {"open": len(pages), "offset": offset, "questions": out,
            "next_offset": nxt if nxt < len(pages) else None,
            "next": NEXT + ("; no candidate fits: wikidata_answer(entity, 'none')"
                            "; a candidate needs a closer look: probe(entity, 'wikidata-find', query=...) searches other words")}


def answer(root: Path, entity: str, qid: str, confirm: bool = False) -> dict:
    """The person's answer for one entry: a Q-id from its candidates, or `none`."""
    page = core.resolve_entity(root, entity)
    body = page.body
    qid = str(qid or "").strip().upper()
    if qid in ("NONE", "NO", ""):
        if not confirm:
            return {"entity": entity, "would": "dismiss the Wikidata match: this entry is not asked again",
                    "next": "confirm with the person, then call again with confirm=true"}
        out = _s(lambda m: m.dismiss(root, body, MATCH))
        workflows.hook_log(root, f"wikidata: no match for {entity}")
        return {"entity": entity, "dismissed": True, "result": out}
    got = _s(lambda m: m._read_probe(root, MATCH, body))
    if got is None:
        raise IngestError(f"no candidates kept for {entity}: call wikidata_questions (or probe it) first")
    cands = (got.get("mapped") or {}).get("candidates") or []
    n = next((i for i, c in enumerate(cands) if str(c.get("qid")).upper() == qid), None)
    if n is None:
        raise IngestError(f"{qid} is not among {entity}'s candidates ({', '.join(c['qid'] for c in cands) or 'none'}): "
                          "probe(entity, 'wikidata-find', query=...) searches other words")
    plan = _s(lambda m: m.apply(root, body, MATCH, {"candidate": n}))
    if not plan.get("tool"):
        raise IngestError(plan.get("note") or "nothing can hold this key")
    pick = cands[n]
    if not confirm:
        return {"entity": entity, "match": {"qid": qid, "label": pick.get("label"), "description": pick.get("description")},
                "would": [f"pin wikidata:{qid} to {plan['args']['collection']}/{plan['args']['record']}",
                          "then import the item's picture, if Wikidata names one, with its licence and artist"],
                "next": "confirm with the person, then call again with confirm=true"}
    pinned = _s(lambda m: m.perform(root, body, MATCH, plan["tool"], plan["args"],
                                    lambda: suggestions._run_tool(root, plan["tool"], plan["args"]), by="mcp"))
    _pages_current(root)                                   # the key on the page before Portrait asks for it
    try:
        body = core.resolve_entity(root, f"wikidata:{qid}").body
    except Exception:
        pass
    out = {"entity": entity, "matched": qid, "pinned": pinned, "picture": _portrait(root, body)}
    workflows.hook_log(root, f"wikidata: {entity} is {qid}")
    return out


def _portrait(root: Path, body: str) -> dict:
    """After a confirmed match: the item's picture (P18) imported with its licence, when there is one. Never shown."""
    try:
        found = _s(lambda m: [s for s in m.suggestions(root, body) if s["id"] == PORTRAIT])
        if not found:
            return {"imported": False, "why": "the entry already has a picture, or is not a kind that takes one"}
        got = _s(lambda m: m.probe(root, body, PORTRAIT))
        mapped = got.get("mapped") or {}
        if not mapped.get("file"):
            return {"imported": False, "why": "Wikidata names no image for this item"}
        plan = _s(lambda m: m.apply(root, body, PORTRAIT, {}))
        if not plan.get("tool"):
            return {"imported": False, "why": plan.get("note")}
        _s(lambda m: m.perform(root, body, PORTRAIT, plan["tool"], plan["args"],
                               lambda: suggestions._run_tool(root, plan["tool"], plan["args"]), by="mcp"))
        return {"imported": True, "file": mapped["file"], "licence": mapped.get("licence"), "artist": mapped.get("artist"),
                "commons": mapped.get("commons")}
    except IngestError as e:
        return {"imported": False, "why": str(e)}


def status(root: Path) -> dict:
    _pages_current(root)

    def go(m):
        ctx = m._ctx(root)
        own = [p for p in ctx["pages"].values() if m._record_id(p)]
        matched = [p for p in own if m._qid(p)]
        refused = [p for p in own if not m._qid(p) and MATCH in m.dismissed(root, p["body"])]
        return {"entries": len(own), "matched": len(matched), "answered_none": len(refused)}
    out = _s(go)
    out["open"] = len(_open(root))
    return out
