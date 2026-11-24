"""labelling.py — `label`: attach what entries lack, as the Labelling page does (hydra/labels.py, designs D9 and D20).

Tokens are `kind:value`: place:seat@geonames:105343 (a register or archive place for an aspect), place:seat@40.7,-73.9,
place:country@iso3166:SA (a country as a Place: the entry's nationality or country field), org:<H>, org:Member@<H>,
org:employer@<H>, post:Governor, post:above@Governor, post:hold@<H> or post:2017..2020@<H> (a person holds a Position),
tag:diplomatic-mission (tag:no@id, tag:clear@id; `arch:` is the old word), drop:rec@<record id> and drop:<prop>@<value>
(a removal), own:"share=85;from=2021-10-07;via=<event H>"@<asset H> (an Ownership; dir=by for the entry being
owned; count, currency, type=beneficial|direct|indirect|ultimate), evt:"role=involved"@<event H> (Event.involved or
organizer; buyer and seller write an Ownership through the deal; evt:"name=..;date=..;place=.."@new makes an event),
kin:mother@<H> (a Family record, the kinship word from the entry's side), drop:evt@<event record id>. Previews every
entry first; writes with `confirm`. A label that states a fact (org, a country, a post held, own, evt, kin) needs
`source`: any kept source of the archive (`sources` lists them, the ones the entry's records cite first); a judgement (place, ladder post, tag, removal) needs
none. Every claim written carries its Wikidata property code in `_meta.wd`; a preview row lists it as `wd`, or
`no_standard_code` when the field has none. The tool itself is in `tools/shape.py`.
"""
from __future__ import annotations

from pathlib import Path

from hydra_mcp import workflows
from hydra_mcp.core import AGENT, IngestError
from hydra.enrich import labels
from hydra.universe import build as ubuild

NEXT = "confirm with the person, then call again with confirm=true"


def label(root: Path, entities: list[str], tokens: str | list[str], confirm: bool = False,
          source: str | None = None) -> dict:
    if isinstance(tokens, list):
        tokens = " ".join(str(t) for t in tokens)
    if isinstance(entities, str):
        entities = [entities]
    try:
        if not ubuild.pages_current(root):
            ubuild.build(root)
        plan = labels.plan(root, entities, tokens, source)
        out = {"ok": plan["ok"], "needs_source": plan["needs_source"], "tokens": plan["tokens"],
               "entries": [{"entry": e["title"], "h": e["h"], "labels": [{"token": r["token"], "ok": r["ok"],
                            **({"would": r["line"], **({"warning": r["warn"]} if r.get("warn") else {}), **({"wd": r["wd"]} if r.get("wd") else {}), **({"no_standard_code": True} if r.get("nocode") else {})}
                               if r["ok"] else {"error": r["error"]})} for r in e["rows"]]}
                           for e in plan["entries"]]}
        if plan["needs_source"]:
            out["sources"] = [{"id": s["id"], "title": s["title"], "cited_by": len(s["cited_by"])} for s in plan["sources"]]
        if plan["errors"]:
            out["errors"] = plan["errors"]
        if not plan["ok"]:
            return {**out, "written": 0, "next": "fix the labels marked with an error (a fact needs `source`) and call again"}
        if not confirm:
            return {**out, "written": 0, "next": NEXT}
        done = labels.apply(root, entities, tokens, source, who=AGENT)
    except labels.LabelError as e:
        raise IngestError(str(e)) from None
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: ")) from None
    workflows.hook_log(root, f"label {tokens} on {len(entities)} entry(ies)")
    if source:
        workflows.hook_source(root, source)
    return {**out, "written": len(done["written"]), "did": done["written"], **({"snapshot": done["snapshot"]} if done.get("snapshot") else {})}
