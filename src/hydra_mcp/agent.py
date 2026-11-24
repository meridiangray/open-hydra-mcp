"""agent.py — the tools that close the loop after `save`: see what the build asks,
answer it, correct a record, pin identity, shape the ladder, and look back.

Every tool that writes takes a history snapshot (author `agent:hydra-mcp`), so
`history_log` shows what the agent did and `history_restore` undoes it. A tool
that decides something for the person (an answer, a pin, a ladder, a restore)
previews unless `confirm=true`, which the model passes only once the person agrees.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import yaml

from hydra.build import run as build
from hydra.records import entities
from hydra.sources import citations as hcite, pagelabels
from hydra.schema import loader as schema, keys as hkeys, dates
from hydra.archive import history, layout, resources
from hydra.api.records import _RID, _about, _diff, amend_records  # noqa: F401  (moved: plans/imports.md I2b)
from hydra.api.answers import _evidence, _evidence_file, _keep_evidence, answer  # noqa: F401  (moved: plans/imports.md I2c)
from hydra.api.sources import quote_problem, short_quote
from hydra.api.edits import _WIKI_LINE, _pin_key, _read_collection, _write_collection, pin_upstream, swap_source  # noqa: F401

from hydra_mcp import core, pipeline, workflows, sources as src
from hydra_mcp.core import AGENT, IngestError
from collections import Counter
from hydra.cli import node, todo, export as hexport
from hydra.review import cutoffs, ids
from hydra.shape import rules
from hydra.universe import hid, layer, build as ubuild
from hydra.wiki.views import timelineview
from hydra.wiki.pages import reviewqueue
from hydra.wiki.look import symbology as sym

QUESTION_KINDS = ("merges", "references", "placements", "stale", "contradictions", "verdicts")


def _rebuild(root: Path) -> str:
    return build.report(root, build.build_archive(root), verb="Rebuilt")


def _snap(root: Path, message: str) -> str | None:
    return history.auto(root, f"hydra-mcp {message}", who=AGENT)


# ---- finding -------------------------------------------------------------------------

def find_entities(root: Path, query: str, schema_name: str = "", limit: int = 10) -> list[dict]:
    """node.find, with what tells each hit apart: its H, dates, nationality, posts, parents."""
    k = hkeys.text(hkeys.load(root), query)          # a key (wikidata:Q57340, acme:EMP-0042) names one entity for certain
    row = core._keyed(root).get(k) if k else None
    if row:
        anchor = (row.get("anchor") or "").split("/", 1)[-1]
        return [{"id": anchor, "caption": row.get("title"), "schema": row.get("schema"), "score": 1.0,
                 "matched": f"key {k}", **core._facts(root, anchor), "h": row["h"], "keys": row.get("keys") or []}]
    return [{**h, **core._facts(root, h["id"])} for h in node.find(root, query, schema_name, limit=limit)]


def explain_entity(root: Path, ref: str) -> dict:
    """Where each value of an entity came from: per property and value, the records that
    supplied it, their collections and the documents they cite; its H and flags; and
    the review rows it takes part in. `ref` is an H, a record id or a title exactly one entry has
    (`hydra.records.entities.resolve`: never fuzzy, a shared title is refused with the candidate Hs). A
    record id that is no entity (a relationship: an Occupancy, an Ownership) answers with the
    record itself and the collection it lives in."""
    nodes = core._declared(root)
    ref = str(ref or "").strip()
    if not ref:
        raise IngestError("no entity named: give its H, a record id or its exact title", kind="NotFound")
    nid = ref if ref in nodes else next((i for i, n in nodes.items() if ref in (n.get("referents") or ())), None)
    if nid is None and not hid.is_h(ref):
        tail = ":" + ref                                     # a record id as the collection wrote it, without its prefix
        tails = sorted({i for i, n in nodes.items() if any(r.endswith(tail) for r in (i, *(n.get("referents") or ())))})
        if len(tails) > 1:
            raise IngestError(f"'{ref}' is the id of records in several collections: "
                              + "; ".join(f"{i} ({nodes[i].get('caption')})" for i in tails) + ". Pass one in full.",
                              kind="Ambiguous")
        nid = tails[0] if tails else None
    if nid is None and not hid.is_h(ref):
        where = core._ids_in(root).get(ref)
        if where:
            coll = Path(where).stem
            rec = next((r for r in core._load_records(root / where) if str(r.get("id")) == ref), {})
            return {"record": ref, "collection": coll, "file": where, "schema": rec.get("schema"),
                    "properties": rec.get("properties") or {},
                    "note": "this record is no entity of its own (a relationship); its ends are in `properties`"}
    if nid is None:
        nid = _node_of_entity(root, nodes, ref)
    n = nodes[nid]
    ids = {nid, *(n.get("referents") or ())}
    rows = [r for r in resources.read_jsonl(root / layout.CLAIMS_JSONL) if r["entity"] == nid]
    docs = {d["id"]: d.get("caption") for d in n.get("linked") or []}
    values: dict[str, dict[str, list]] = {}
    for r in rows:
        values.setdefault(r["prop"], {}).setdefault(r["value"], []).append(
            {"record": r["record"], "collection": r["collection"], "source": r.get("source")})
    review = [{"id": r["id"], "rel": r["rel"], "status": r.get("status"), "criteria": r.get("criteria")}
              for r in resources.read_jsonl(root / layout.IDENTICAL_JSONL) + resources.read_jsonl(root / layout.LEDGER_JSONL)
              if ids & {r.get("a"), r.get("b"), r.get("sub"), r.get("sup"), r.get("record")}]
    return {"id": nid, "caption": n.get("caption"), "schema": n.get("schema"), "h": core._h_of(root, nid),
            "collections": sorted({r["collection"] for r in rows if r.get("collection")}),
            "records": sorted(ids), "values": values, "documents": docs, "review": review}


def _node_of_entity(root: Path, nodes: dict, ref: str) -> str:
    """The archive node an H, a key or a unique title names (`core.resolve_entity`): the node holding the
    H's anchor record, else its first member this archive has. Without a universe layer only an exact
    caption one node has is taken."""
    if not layer.is_universe(root):
        got = sorted(i for i, n in nodes.items() if str(n.get("caption") or "").casefold() == ref.casefold())
        if len(got) == 1:
            return got[0]
        if got:
            raise IngestError(f"'{ref}' names {len(got)} entries: "
                              + "; ".join(f"{i} ({nodes[i].get('caption')})" for i in got) + ". Pass one of those ids.",
                              kind="Ambiguous")
        raise IngestError(f"no entity or record '{ref}' in the last build: find_entities looks one up", kind="NotFound")
    hit = core.resolve_entity(root, ref)
    cat = entities.catalog(root)
    node_of = {r: i for i, n in nodes.items() for r in (i, *(n.get("referents") or ()))}
    anchor = (cat.canon.get(hit.body) or {}).get("anchor") or ""
    for m in [anchor, *cat.records_of(hit.body)]:
        universe, _, rid = m.partition("/")
        if universe == layer.SELF and rid in node_of:
            return node_of[rid]
    raise IngestError(f"{hit.h} holds no record of this archive (its records come from other universes)",
                      kind="NotFound")


# ---- questions -----------------------------------------------------------------------

def _question(kind: str, r: dict) -> dict:
    if kind == "merges":
        return {"id": r["id"], "ask": f"Are '{r.get('acap')}' ({r['a']}) and '{r.get('bcap')}' ({r['b']}) one entity?",
                "why": r.get("criteria"), "conflicts": r.get("conflicts"), "answers": ["confirm", "reject"]}
    if kind == "references":
        cands = [{"n": i + 1, "id": c["id"], "caption": c.get("caption")} for i, c in enumerate(r.get("candidates") or [])]
        return {"id": r["id"], "ask": f"In {r['record']}.{r['prop']}, which record is '{r['value']}'?",
                "candidates": cands, "answers": ["<n>", "<record id>", "none"]}
    if kind == "placements":
        return {"id": r["id"], "ask": f"Is '{r.get('subcap')}' under '{r.get('supcap')}'?", "why": r.get("criteria"),
                "answers": ["confirm", "reject"]}
    return {"id": r["id"], "ask": r.get("message") or r.get("criteria") or r["rel"], "status": r.get("status")}


def open_questions(root: Path, kind: str | None = None, offset: int = 0, limit: int = 30) -> dict:
    if not core._built(root):
        raise IngestError("the archive has not been built yet: save something first")
    got = todo.collect(root)
    kinds = [kind] if kind else list(QUESTION_KINDS)
    if kind and kind not in QUESTION_KINDS:
        raise IngestError(f"kind is one of: {', '.join(QUESTION_KINDS)}")
    rows = [(k, r) for k in kinds for r in got.get(k) or []]
    page = rows[offset:offset + limit]
    return {"counts": {k: len(got.get(k) or []) for k in QUESTION_KINDS},
            "questions": [{"kind": k, **_question(k, r)} for k, r in page],
            "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
            "how": "answer(id, choice) previews; answer it again with confirm=true once the person agrees"}


def open_ends(root: Path, entity: str | None = None, collection: str | None = None) -> dict:
    """The Occupancy, Employment and Membership links with a start and no end, each with what could end it (the
    holder's death, the next holder's start, an event, another post that ended, a later date in the text). Answer one
    with `answer(id, choice)`: a candidate's `choice`, `holds` or `unknown`. An end picked here is a judgement, kept
    with its evidence, and drawn as inferred, never as a stated end date."""
    if not core._built(root):
        raise IngestError("the archive has not been built yet: save something first")
    if not ubuild.pages_current(root):
        pipeline._universe(root)
        ubuild.build(root)
    want = (entity or "").strip().lower()
    rows = [x for x in cutoffs.links(root, collection=collection or None) if not x["state"]
            and (not want or want in (x["b"].lower(), x["who"].lower(), x["rec"].lower()))]
    if want and not rows and not any(want in (x["b"].lower(), x["who"].lower()) for x in cutoffs.links(root, collection=collection or None)):
        raise IngestError(f"no open-ended post for '{entity}' (use an entity's H body, its name or the link's record id)")
    return {"count": len(rows),
            "open_ends": [{"id": x["key"], "who": x["who"], "kind": x["kind"], "post": x["post"], "start": x["start"],
                           "candidates": [{"choice": c["choice"], "date": c["date"], "kind": c["kind"], "label": c["label"],
                                           "from": c["src"]} for c in x["cands"]],
                           "answers": ["holds", "unknown"]} for x in rows],
            "how": "answer(id, choice) previews; answer it again with confirm=true once the person agrees"}


def decisions(root: Path, kind: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """Every answer already given (.hydra/review/), as the Review page lists them: its `id`, the question it
    answered, what was said, and whether the build still asks it (`gone`: the records it was about changed)."""
    kinds = ("merge", "place", "ref", "cap", "stub", "end", "hide", "other")
    if kind and kind not in kinds:
        raise IngestError(f"kind is one of {', '.join(kinds)}")
    ev = _evidence(root)
    rows = [{"id": r["key"], "kind": r["g"], "question": r["q"], "answer": r["said"], "gone": r["gone"],
             "stale": r["stale"], **({"evidence": ev[r["key"]]} if r["key"] in ev else {})}
            for r in reviewqueue.decided(root) if not kind or r["g"] == kind]
    shown, paging = core.page(rows, offset, limit)
    return {"count": len(rows), **paging, "decisions": shown,
            "next": "to take one back, `answer` its id with choice `clear` (with the person's agreement)"}


# ---- symbology ---------------------------------------------------------------------------

def symbology(root: Path) -> dict:
    """The Symbology page as data, without its pictures: each entry type's icon, each badge's, each position's
    (a hints.yaml rule), each link type's colour, every image rule and what it reached, and the icons to pick from."""
    m = sym.model(pipeline._wiki(root))
    return {
        "types": [{"key": t["key"], "label": t["label"], "entries": t["n"], "icon": t["icon"], "set": t["set"]}
                  for t in m["types"]],
        "badges": [{"key": b["key"], "label": b["label"], "group": b["group"], "icon": b["icon"], "pages": b["pages"],
                    "examples": b["examples"]} for b in m["badges"]],
        "positions": [{"key": p["key"], "depth": p["depth"], "held": p["n"], "outside": p["outside"],
                       "icon_rule": p["rule"]} for p in m["positions"]],
        "links": [{"key": x["key"], "count": x["n"], "colour": x["colour"], "timeline_mark": x["mark"]} for x in m["links"]],
        "link_types": m["linkTypes"],
        "image_rules": [{"rule": r["i"], "match": r["match"], "set": r["set"], "reached": r["n"]} for r in m["rules"]],
        "icons": [{"token": t, "own": x["own"]} for t, x in m["library"].items()],
        "kinds": {"type-icon": "an entry type's icon (wiki.yaml icons:)",
                  "badge-icon": "a badge rule's icon (wiki.yaml badge_rules:)",
                  "position-icon": "a position's picture (a hints.yaml rule)",
                  "link-colour": "a link type's colour, #rrggbb (wiki.yaml link_colours:)",
                  "link-mark": "what the Timeline draws for a link type with a start and no end: start (a diamond at the "
                               "start), fades (a post: a bar fading out, with a ? cap) or runs (a bar to today) "
                               "(wiki.yaml timeline_marks:)"},
    }


def set_symbology(root: Path, kind: str, key: str, value: str = "", confirm: bool = False) -> dict:
    """One symbology choice (the Symbology page's Set): `kind` one of hydra.wiki.look.symbology.KINDS, `key` the type,
    badge, position or link type, `value` an icon token, a #rrggbb colour, or a Timeline mark (start, fades, runs)
    ("" puts the default back)."""
    if kind not in sym.KINDS:
        raise IngestError(f"kind is one of {', '.join(sym.KINDS)}")
    if not isinstance(key, str) or not key:
        raise IngestError("say which type, badge, position or link type: `key`")
    value = value or ""
    if kind == "link-colour":
        if value and not sym.COLOUR.fullmatch(value):
            raise IngestError("a colour is written #rrggbb")
    elif kind == "link-mark":
        if value and value not in timelineview.NO_END:
            raise IngestError(f"a Timeline mark is one of: {', '.join(timelineview.NO_END)}")
    elif value and value not in sym.library(root):
        raise IngestError(f"no icon '{value}'; `symbology` lists the icons there are")
    if kind == "position-icon" and not value:
        raise IngestError("a position's icon is a hints.yaml rule: remove it there")
    now = symbology(root)
    table = {"type-icon": ("types", "icon"), "badge-icon": ("badges", "icon"),
             "position-icon": ("positions", "icon_rule"), "link-colour": ("links", "colour"),
             "link-mark": ("links", "timeline_mark")}[kind]
    known = {x["key"]: x[table[1]] for x in now[table[0]]}
    out = {"kind": kind, "key": key, "now": known.get(key), "to": value or "(default)"}
    if key not in known and not (kind in ("link-colour", "link-mark") and key in now["link_types"]):
        out["warning"] = f"no {table[0][:-1]} '{key}' in this archive's pages; the choice is kept but marks nothing yet"
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    try:
        said = sym.set_(root, kind, key, value, who=AGENT)
    except (ValueError, SystemExit) as e:
        raise IngestError(str(e.code if isinstance(e, SystemExit) else e).removeprefix("hydra: ")) from None
    workflows.hook_log(root, f"set_symbology {kind} {key}={value}")
    return {**out, "written": said, "note": "the archive and its pages are rebuilt; wiki_serve shows the change"}


# ---- correcting --------------------------------------------------------------------------

# amend_records moved to hydra.api.records (plans/imports.md I2b); it is imported above.


def preview(root: Path, records: list[dict], collection: str = "preview", link_by: str = "id") -> dict:
    """What saving a batch would change, built aside in a temporary copy: entities added,
    merges it would make, questions it would raise, links that would stay names."""
    report = core.check_records(root, records, link_by=link_by)
    if not report["ok"]:
        return {"ok": False, "errors": report["errors"], "warnings": report["warnings"]}
    with tempfile.TemporaryDirectory(prefix="hydra-preview-") as tmp:
        copy = Path(tmp) / "a"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("history", "cache", "parsed", ".parsed"))
        before = _summary(copy)
        (copy / layout.COLLECTIONS_DIR / f"{collection}.json").write_text(json.dumps(report["records"]), encoding="utf-8")
        after = _summary(copy)
    new = {k: v for k, v in after["entities"].items() if k not in before["entities"]}
    merged_in = sorted(after["merged"] - before["merged"])
    return {"ok": True, "entities": {"before": len(before["entities"]), "after": len(after["entities"]),
                                     "new": sorted(new.values())},
            "would_merge": [sorted(g) for g in merged_in],
            "open_questions": {"before": before["open"], "after": after["open"]},
            "links_left_as_names": [l for l in report["links"] if l["links_to"] is None],
            "ambiguous_links": report["ambiguous_links"], "warnings": report["warnings"]}


def _summary(root: Path) -> dict:
    try:
        cap = hexport.compile_(root)
    except Exception:                                   # nothing to build yet
        return {"entities": {}, "merged": set(), "open": 0}
    r = cap["resolved"]
    groups = {}
    for rec in r.records:
        groups.setdefault(ids.survivor(r.survivors, rec["id"]), set()).add(rec["id"])
    return {"entities": {s: r.cap.get(s, s) for s in r.ents},
            "merged": {frozenset(g) for g in groups.values() if len(g) > 1},
            "open": sum(1 for row in cap["ledger"] if row.get("status") in ("proposed", "unresolved", "conflict"))}


# ---- describing sources ---------------------------------------------------------------


# what a reader of a source is told about it: the key `cite` takes -> the property of the source document
SOURCE_FIELDS = {"title": "title", "author": "author", "publisher": "publisher", "published": "publishedAt",
                 "url": "sourceUrl", "summary": "summary", "language": "language", "keywords": "keywords",
                 "duration": "duration", "pictured": "pictured", "call_number": "accessNumber"}
SOURCE_LIMIT = {"summary": 1500, "title": 300}


def describe_sources(root: Path, sources: list[dict]) -> tuple[list[dict], list[str], list[tuple[Path, list[dict]]]]:
    """Check reader fields for kept sources: [{source, title?, author?, publisher?, published?, url?, summary?,
    language?, keywords?, duration?, pictured?, call_number?}]. -> (what each source becomes, errors, the files to
    write). A blank value removes the field. Machine fields (hash, size, type) are not for an agent to set."""
    schema.load(root=root)
    out, errors, files = [], [], {}
    for i, r in enumerate(sources or []):
        at = f"source {i + 1}"
        if not isinstance(r, dict) or not r.get("source"):
            errors.append(f"{at}: give {{source: <id>, title?, author?, publisher?, published?, url?, summary?, ...}}")
            continue
        try:
            rec = core._existing_source(root, r["source"])
        except IngestError as e:
            errors.append(f"{at}: {e}")
            continue
        unknown = set(r) - {"source", *SOURCE_FIELDS}
        if unknown:
            errors.append(f"{at}: unknown field{'s' if len(unknown) > 1 else ''} {', '.join(sorted(unknown))} "
                          f"(a source takes {', '.join(SOURCE_FIELDS)})")
            continue
        allowed = schema.resolve(rec.get("schema") or "Document")["props"]
        changed = {}
        for key, val in r.items():
            if key == "source":
                continue
            prop = SOURCE_FIELDS[key]
            vals = [str(x).strip() for x in (val if isinstance(val, list) else [val]) if x is not None and str(x).strip()]
            if prop not in allowed:
                errors.append(f"{at}: a {rec.get('schema')} has no '{key}'")
            elif key == "published" and vals and dates.bounds(vals[0]) is None:
                errors.append(f"{at}: published '{vals[0]}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD)")
            elif any(len(v) > SOURCE_LIMIT.get(key, 500) for v in vals):
                errors.append(f"{at}: {key} is longer than {SOURCE_LIMIT.get(key, 500)} characters")
            else:
                changed[prop] = vals
        coll = rec["collection"]
        f = root / layout.SOURCE_ENTRIES / f"{coll}.json"
        if f not in files:
            files[f] = core._load_records(f)
        doc = next((x for x in files[f] if x.get("id") == rec["id"]), None)
        if doc is None:
            errors.append(f"{at}: '{r['source']}' is not in a file this tool can write")
            continue
        props = doc.setdefault("properties", {})
        before = {k: props.get(k) for k in changed}
        for prop, vals in changed.items():
            props.pop(prop, None) if not vals else props.__setitem__(prop, vals)
        out.append({"source": rec["id"], "before": before, "after": {k: props.get(k) for k in changed}})
    return out, errors, list(files.items())


def cite(root: Path, citations: list[dict] | None = None, confirm: bool = False,
         sources: list[dict] | None = None) -> dict:
    """Say where in a source each record's facts are (hydra.sources.citations): the source document, its pages (`pages`:
    as printed on the document; `pdfPages`: the page of the file; a kept PDF fills in whichever is missing when the
    printed number can be read and confirmed, else it stays blank), a locator, the words quoted. Any record, relationships included. `sources` also says what a source is
    (title, author, publisher, date, summary...), for the pages that cite it. Without `confirm`: the rows
    resolved against the last build and every problem, writing nothing."""
    citations = citations or []
    rows, errors = hcite.check(root, citations) if citations or not sources else ([], [])
    errors = list(errors)
    described, serr, sfiles = describe_sources(root, sources) if sources else ([], [], [])
    errors += serr
    texts: dict[str, str | None] = {}
    labels: dict[str, dict[int, str]] = {}
    filled: list[str] = []
    warnings: list[str] = []
    for r in rows:
        q = (r.get("quote") or "").strip()
        sid = r["source"]
        if q:
            if sid not in texts:
                texts[sid] = src.text_of(root, sid)
            t = texts[sid]
            why = quote_problem(q, [t]) if t else None
            if not t:
                errors.append(f"{r['record']} ({sid}): the source has no text to check this quote against; "
                              "cite it without a quote")
                continue
            if why:
                errors.append(f"{r['record']} ({sid}): quote '{q[:90]}' is {why} (read_source with `find` locates it)")
                continue
            if short_quote(q):
                warnings.append(f"{r['record']} ({sid}): quote '{q[:90]}' {short_quote(q)}")
            if not (r.get("pdfPages") or "").strip():
                found = src.pages_of_quote(t, src.page_ranges_of(root, sid), q)
                if found:                                         # the quote's own page of the kept PDF (not the printed one)
                    r["pdfPages"] = found
        if not (r.get("pages") or r.get("pdfPages")):
            continue
        if sid not in labels:
            labels[sid] = src.page_labels_of(root, sid)
        lab = labels[sid]
        if not lab:
            continue
        if r.get("pdfPages") and not r.get("pages"):             # the printed page, when the page's own number is read and confirmed
            got = pagelabels.printed_for(r["pdfPages"], lab)
            if got:
                r["pages"] = got
                filled.append(f"{r['record']}: pages {got!r} read off PDF page {r['pdfPages']}")
        elif r.get("pages") and not r.get("pdfPages"):
            got = pagelabels.pdf_for(r["pages"], lab)
            if got:
                r["pdfPages"] = got
                filled.append(f"{r['record']}: pdfPages {got!r} is where printed page {r['pages']} stands")
    have = hcite.load(root)
    out = {"citations": [{**r, "replaces": have[(r["record"], r["source"])]} if (r["record"], r["source"]) in have else r
                         for r in rows], "errors": errors, **({"warnings": warnings} if warnings else {}),
           **({"sources": described} if described else {}), **({"page_notes": filled} if filled else {})}
    if errors or not confirm:
        return {**out, "next": "fix the errors and call again" if errors else
                "check each row says what the source says, then call again with confirm=true"}
    if rows:
        hcite.add(root, rows)                                     # the resolved rows, pages filled in
    for f, recs in sfiles:
        f.write_text(json.dumps(recs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n = len(rows)
    for r in rows:
        workflows.hook_source(root, r["source"])
    workflows.hook_log(root, f"cite: {n} citation(s)")
    what = (f"cited {n} record{'s' if n != 1 else ''} to their pages" if n else "described sources") + (
        f", described {len(described)} source{'s' if len(described) != 1 else ''}" if n and described else "")
    return {**out, "written": n, "snapshot": _snap(root, what),
            "note": "the wiki shows them once its pages are rebuilt (wiki_serve)"}


def keys_in_use(root: Path) -> dict:
    """keys.yaml as in effect, and how many entities hold a key of each namespace."""
    conf = hkeys.load(root)
    held = Counter(k.split(":", 1)[0] for k in core._keyed(root))
    return {"file": str(hkeys.path(root)), "primary": conf["primary"], "namespaces": conf["namespaces"],
            "held": dict(held), "undeclared": sorted(ns for ns in held if ns not in conf["namespaces"])}


# ---- the archive's own rules ---------------------------------------------------------

def set_positions(root: Path, positions: dict, confirm: bool = False) -> dict:
    """Preview (default) or write `.hydra/rules/positions.yaml`: this archive's rank ladder,
    {name: {below: [...], titles: [...], outside: bool}}. The preview says, for each
    position, how many roles in the archive its titles rank, and which roles none takes."""
    if not isinstance(positions, dict) or not positions:
        raise IngestError("positions: {name: {below: [names above it], titles: [the words that mean it]}}")
    bad = [k for k, v in positions.items() if not isinstance(v, dict)
           or set(v) - set(rules.POSITION_KEYS)]
    if bad:
        raise IngestError(f"each position takes only {', '.join(rules.POSITION_KEYS)}: {', '.join(bad)}")
    doc = {"positions": positions}
    compiled = rules.compile_rules(None, doc)
    roles = {}
    for r in _all_records(root):
        for p in ("role", "position"):
            for v in (r.get("properties") or {}).get(p) or []:
                roles.setdefault(v, 0)
                roles[v] += 1
    ranked = {name: sum(n for v, n in roles.items() if rules.canonical(v, {name: d}))
              for name, d in compiled["positions"].items()}
    unranked = sorted((v for v in roles if not rules.canonical(v, compiled["positions"])), key=lambda v: -roles[v])
    out = {"positions": list(compiled["positions"]), "roles_ranked": ranked, "issues": compiled["issues"],
           "roles_no_position_takes": unranked[:40]}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    p = root / layout.POSITIONS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# this archive's rank ladder (written by hydra-mcp set_positions)\n"
                 + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    rep = _rebuild(root)
    workflows.hook_log(root, f"set_positions: {len(positions)} positions")
    return {**out, "written": p.relative_to(root).as_posix(), "build": rep,
            "snapshot": _snap(root, f"set_positions: {len(positions)} positions")}


def _all_records(root: Path) -> list[dict]:
    files, _ = resources.record_files(root)
    out = []
    for f in files:
        out += core._load_records(f)
    return out


def records_of(root, entity: str) -> list[str]:
    """The record ids an entity (its H, a record id, or a title only one entry has) is made of: an image rule matching
    them pins that one entry, not its namesakes, and survives a rename."""
    got = explain_entity(root, entity)
    ids = [str(x) for x in got.get("records") or ([got["id"]] if got.get("id") else [])]
    if not ids:
        raise IngestError(f"'{entity}' is no entry the last build knows: find_entities, or run universe_build first")
    return ids


def link_images(root: Path, images: list[dict], confirm: bool = False) -> dict:
    """Many `link_image` calls at once: [{image, kind, name?, schema?, position?, titled?, credit?}, ...]."""
    done, problems = [], []
    for i, item in enumerate(images or []):
        match = {k: item.get(k) for k in ("schema", "position", "titled", "name")}
        try:
            if item.get("entity"):                     # one entry, strictly: a shared title is refused with its Hs
                match = {"record": records_of(root, item["entity"])}
            done.append(core.link_image(root, item.get("image", ""), item.get("kind", ""), match, confirm,
                                        item.get("credit"), step=False))
        except IngestError as e:
            problems.append({"item": i, "image": item.get("image"), "error": str(e)})
    out = {"images": len(done), "problems": problems,
           "added": sum(1 for d in done if d.get("added"))}
    if confirm and out["added"]:
        workflows.hook_log(root, f"link_images: {out['added']} rule(s)")
        out["snapshot"] = _snap(root, f"link_images: {out['added']} rule(s)")
    elif not confirm:
        out["next"] = "confirm with the person, then call again with confirm=true"
    return out


# ---- history -------------------------------------------------------------------------

def history_log(root: Path, limit: int = 20) -> list[dict]:
    return [{k: v for k, v in s.items() if k != "files"} for s in history.log(root, None, limit)]


def history_diff(root: Path, a: str = "HEAD", b: str | None = None) -> list[dict]:
    rows = history.diff(root, a, b)
    for r in rows:                                     # long id lists cut, counts kept
        for k in ("records", "decisions", "hs"):
            if k in r:
                r[k] = {x: (ids[:20] + [f"... {len(ids) - 20} more"] if len(ids) > 20 else ids) for x, ids in r[k].items()}
    return rows


def history_snapshot(root: Path, message: str) -> dict:
    sid = history.snapshot(root, message, who=AGENT)
    return {"snapshot": sid, "note": None if sid else "nothing changed since the last snapshot"}


def save_changes(root: Path, message: str, description: str = "", confirm: bool = False) -> dict:
    """A history *save*: one named change covering every step since the last save (call it at the end of a task,
    so the work reads as one change). Previews what it would cover; `confirm` writes it."""
    pending = history.since_last_save(root)
    out = {"message": message, "steps": len(pending["steps"]), "covers": pending["summary"],
           "entities": [{k: e[k] for k in ("collection", "id", "name", "change")} for e in pending["entities"][:40]],
           "sources": pending["sources"][:40]}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    return {**out, "saved": history.save(root, message, description, who=AGENT)}


def history_restore(root: Path, ref: str, paths: list[str] | None = None, confirm: bool = False) -> dict:
    sid = history.resolve(root, ref)
    diff = history.diff(root, sid)
    wanted = [p for p in (paths or [])]
    touched = [d["path"] for d in diff if not wanted or any(d["path"] == w or d["path"].startswith(w.rstrip("/") + "/")
                                                            for w in wanted)]
    out = {"to": sid, "files": touched}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    changed, new = history.restore(root, sid, paths or None, message=f"hydra-mcp restore to {sid[:12]}", who=AGENT)
    rep = _rebuild(root) if changed else None
    if changed:
        workflows.hook_log(root, f"history_restore {sid[:12]}")
    return {**out, "restored": changed, "snapshot": new, "build": rep}
