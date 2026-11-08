"""agent.py — the tools that close the loop after `save`: see what the build asks,
answer it, correct a record, pin identity, shape the ladder, and look back.

Every tool that writes takes a history snapshot (author `agent:hydra-mcp`), so
`history_log` shows what the agent did and `history_restore` undoes it. A tool
that decides something for the person (an answer, a pin, a ladder, a restore)
previews unless `confirm=true`, which the model passes only once the person agrees.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from hydra import build, history, layout, resources, schema
from hydra.identity import types

from hydra_mcp import core
from hydra_mcp.core import AGENT, IngestError

QUESTION_KINDS = ("merges", "references", "placements", "stale", "contradictions", "verdicts")


def _rebuild(root: Path) -> str:
    return build.report(root, build.build_archive(root), verb="Rebuilt")


def _snap(root: Path, message: str) -> str | None:
    return history.auto(root, f"hydra-mcp {message}", who=AGENT)


# ---- finding -------------------------------------------------------------------------

def find_entities(root: Path, query: str, schema_name: str = "", limit: int = 10) -> list[dict]:
    """node.find, with what tells each hit apart: its H, dates, nationality, posts, parents."""
    from hydra import keys as hkeys
    from hydra.cli import node
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
    the review rows it takes part in."""
    nodes = resources.declared_nodes(root)
    nid = ref if ref in nodes else next((i for i, n in nodes.items() if ref in (n.get("referents") or ())), None)
    if nid is None:
        from hydra.cli import node
        hit = next(iter(node.find(root, ref, limit=1)), None)
        if not hit:
            raise IngestError(f"no entity '{ref}' in the last build")
        nid = hit["id"]
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
            "records": sorted(ids), "values": values, "documents": docs, "review": review}


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
    from hydra.cli import todo
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


def answer(root: Path, key: str, choice: str, confirm: bool = False) -> dict:
    from hydra.cli import answer as hanswer
    try:
        value = hanswer.value_for(root, key, choice)
    except SystemExit as e:
        raise IngestError(str(e.code).removeprefix("hydra: ")) from None
    target = hanswer.h_key(root, key)
    out = {"id": key, "choice": choice, "writes": {target: value}}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    if target != key and value is None:
        hanswer.set_verdict(root / layout.VERDICTS, key, None)
    line = hanswer.set_verdict(root / layout.VERDICTS, target, value)
    rep = _rebuild(root)
    return {**out, "recorded": line, "build": rep, "snapshot": _snap(root, f"answer {key}: {choice}")}


# ---- correcting --------------------------------------------------------------------------

def amend_records(root: Path, collection: str, records: list[dict] | None = None,
                  remove: list[str] | None = None, link_by: str = "id") -> dict:
    """Change an existing collection record by record: each of `records` with an `id`
    already in it replaces that record (the whole record: give every property it keeps);
    one with a new or no id is added; `remove` drops records by id. Checked as `save`
    checks; nothing is written if the result has errors."""
    f = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    stored, lines = _read_collection(f)
    if stored is None:
        raise IngestError(f"no collection '{collection}'")
    by_id = {r["id"]: r for r in stored}
    remove = set(remove or [])
    missing = sorted(remove - set(by_id))
    if missing:
        raise IngestError(f"no record {', '.join(missing)} in {collection}")
    changed, added = [], []
    merged = [r for r in stored if r["id"] not in remove]
    for r in records or []:
        rid = str(r.get("id") or "")
        if rid in by_id:
            keep_sources = (by_id[rid].get("properties") or {}).get("sources") or []
            props = {p: core._values(v) for p, v in (r.get("properties") or {}).items()}
            if keep_sources and "sources" not in props:
                props["sources"] = keep_sources                # the evidence it was saved with stays cited
            old = by_id[rid]
            approx = {p: q for p, q in ((old.get("_meta") or {}).get("approx") or {}).items()
                      if props.get(p) == (old.get("properties") or {}).get(p)}   # a date given again keeps its "c."
            new = {"id": rid, "schema": r.get("schema") or old["schema"], "properties": props}
            if approx:
                new["_meta"] = {"approx": approx}
            merged = [new if x["id"] == rid else x for x in merged]
            changed.append(rid)
        else:
            added.append(r)
    report = core.check_records(root, [*[{k: v for k, v in x.items() if k in ("id", "schema", "properties", "_meta")}
                                          for x in merged], *added], collection, link_by=link_by)
    if not report["ok"]:
        return {"saved": False, "errors": report["errors"], "warnings": report["warnings"]}
    before = f.read_bytes()
    out_recs = core.storable(report["records"])
    old_sources = {r["id"]: (r.get("properties") or {}).get("sources") for r in stored}
    for r in out_recs:                                          # new records cite what the collection cites
        if not r["properties"].get("sources") and old_sources:
            first = next((s for s in old_sources.values() if s), None)
            if first and "sources" in schema.resolve(r["schema"])["props"]:
                r["properties"]["sources"] = list(first)
    _write_collection(f, out_recs, lines)
    try:
        rep = _rebuild(root)
    except Exception as e:
        f.write_bytes(before)
        raise IngestError(f"the build failed, so nothing was kept: {e}") from None
    snap = _snap(root, f"amend {collection}: {len(changed)} changed, {len(added)} added, {len(remove)} removed")
    return {"saved": True, "collection": collection, "changed": changed, "added": len(added),
            "removed": sorted(remove), "warnings": report["warnings"], "ambiguous_links": report["ambiguous_links"],
            "build": rep, "snapshot": snap, "undo": f"history_restore {snap[:12]}~1" if snap else None}


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
    from hydra.cli import export as hexport
    from hydra.review import ids
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


# ---- identity ------------------------------------------------------------------------

def pin_upstream(root: Path, collection: str, record: str, h: str, confirm: bool = False) -> dict:
    """Pin a saved record to a canonical id: it is that entity from now on (and that H is
    published: its body holds), or give it a key (`wikidata:Q57340`, `acme:EMP-0042`): every
    record holding that key is one entity. The pin goes in the record's `upstream`."""
    from hydra import keys as hkeys
    from hydra.universe import hid
    if hkeys.parse(h):
        return _pin_key(root, collection, record, h, confirm)
    try:
        _, body = hid.split_pin(h)
    except ValueError:
        raise IngestError(f"'{h}' is neither an H (H-<state><flags>-<12 characters>, or H-<12 characters>) "
                          "nor a key (namespace:key)") from None
    from hydra.universe import layer
    known = {r["body"]: r for r in layer.read_parsed(root, "canon.jsonl", missing=[])}
    if body not in known:
        raise IngestError(f"no H {h} in this archive's universe (build first, or check `find_entities`)")
    f = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    stored, lines = _read_collection(f)
    rec = next((r for r in stored or [] if r.get("id") == record), None)
    if rec is None:
        raise IngestError(f"no record '{record}' in collection '{collection}'")
    out = {"record": record, "h": known[body]["h"], "entity": known[body].get("title")}
    if not confirm:
        return {**out, "next": "confirm with the person that this record is that entity, then call again with confirm=true"}
    pins = list(dict.fromkeys([*core._values((rec.get("properties") or {}).get("upstream") or []), "H-" + body]))
    rec.setdefault("properties", {})["upstream"] = pins
    _write_collection(f, stored, lines)
    core._publish_pinned(root, [rec])
    rep = _rebuild(root)
    return {**out, "pinned": True, "build": rep, "snapshot": _snap(root, f"pin {record} to H-{body}")}


def _read_collection(f: Path) -> tuple[list | None, bool]:
    """A collection file's records, and whether it is one record per line (as `import` writes it)
    rather than a JSON array (as `save` does); (None, False) when there is no such file."""
    if not f.is_file():
        return None, False
    text = f.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        return (data if isinstance(data, list) else [data]), False
    except ValueError:
        return [json.loads(l) for l in text.splitlines() if l.strip()], True


def _write_collection(f: Path, records: list, lines: bool) -> None:
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records) if lines
                 else json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _pin_key(root: Path, collection: str, record: str, key: str, confirm: bool) -> dict:
    """Add a key to a saved record's `upstream`: it is one entity with every record holding that key."""
    from hydra import keys as hkeys
    conf = hkeys.load(root)
    k = hkeys.text(conf, key)
    f = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    stored, lines = _read_collection(f)
    rec = next((r for r in stored or [] if r.get("id") == record), None)
    if rec is None:
        raise IngestError(f"no record '{record}' in collection '{collection}'")
    row = core._keyed(root).get(k)
    ns = k.split(":", 1)[0]
    out = {"record": record, "key": k, **({"joins": row.get("title"), "h": row["h"]} if row else {}),
           **({} if ns in conf["namespaces"] else
              {"note": f"namespace '{ns}' is not declared in {layout.KEYS}; it merges all the same"})}
    if not confirm:
        return {**out, "next": ("confirm with the person that this record is " + (f"{row.get('title')}" if row else
                                "the entity that key names") + ", then call again with confirm=true")}
    pins = list(dict.fromkeys([*core._values((rec.get("properties") or {}).get("upstream") or []), key.strip()]))
    rec.setdefault("properties", {})["upstream"] = pins
    _write_collection(f, stored, lines)
    rep = _rebuild(root)
    return {**out, "pinned": True, "build": rep, "snapshot": _snap(root, f"key {record} as {k}")}


_WIKI_LINE = re.compile(r"^\s*Source:\s*https?://\S*wikipedia\.org\S*\s*$", re.I | re.M)


def swap_source(root: Path, collection: str, record: str, source: str, quote: str, confirm: bool = False) -> dict:
    """Re-source a saved record: its Wikipedia citation out, a kept source in. `quote` must be in the kept
    source's text word for word. The record's Wikipedia URLs go, and so do the notes that quote the
    Wikipedia article; every other note stays (structured lines such as `House: ...` included). The new
    source's URL goes in `sourceUrl` (and its id in `sources` where the schema has that), the quote in
    `notes`. Without `confirm`: what would change."""
    from hydra_mcp import sources as src
    text = src.text_of(root, source)
    if text is None:
        raise IngestError(f"no kept source '{source}' with text: fetch_source keeps one")
    if not src.verbatim(quote, [text]):
        raise IngestError("the quote is not in the new source's text word for word: copy the sentence exactly "
                          "(read_source with `find` locates it)")
    new_url = (core._existing_source(root, source).get("properties") or {}).get("sourceUrl") or []
    f = root / layout.COLLECTIONS_DIR / f"{collection}.json"
    stored, lines = _read_collection(f)
    rec = next((r for r in stored or [] if r.get("id") == record), None)
    if rec is None:
        raise IngestError(f"no record '{record}' in collection '{collection}'")
    props = rec.setdefault("properties", {})
    before = {k: list(core._values(props.get(k) or [])) for k in ("sourceUrl", "sources", "notes")}
    wiki_urls = [u for u in before["sourceUrl"] if "wikipedia.org" in u]
    wiki_urls += [m for n in before["notes"] for m in re.findall(r"https?://\S*wikipedia\.org\S*", n)]
    wiki_text = []
    for u in dict.fromkeys(wiki_urls):
        try:
            wiki_text.append(src.page(u)["text"])
        except IngestError:
            pass
    notes = []
    for n in before["notes"]:
        n2 = _WIKI_LINE.sub("", n).strip()
        if n2 and not (wiki_text and src.verbatim(n2, wiki_text)):     # a quote of the Wikipedia article goes
            notes.append(n2)
    after = {"sourceUrl": list(dict.fromkeys([u for u in before["sourceUrl"] if "wikipedia.org" not in u] + new_url)),
             "notes": notes + [quote.strip()]}
    if "sources" in schema.resolve(rec.get("schema", ""))["props"]:
        after["sources"] = list(dict.fromkeys(before["sources"] + [source]))
    out = {"record": record, "collection": collection, "wikipedia_removed": list(dict.fromkeys(wiki_urls)),
           "before": before, "after": after}
    # a figure the old quotes gave that the new one does not: the record's own fields may now say more than the source
    num = lambda s: set(re.findall(r"\d[\d,.]*", s.replace("£", " ").replace("$", " ")))
    lost = sorted(num(" ".join(n for n in before["notes"] if n not in notes)) - num(quote))
    if lost:
        out["check"] = (f"the old quotes gave {', '.join(lost)}, the new one does not: check that the record's "
                        "fields (amount, dates, share) and status still say only what the new source states "
                        "(\"more than\", \"reportedly\", \"about\" mean a blank field and a caveat status)")
    if not wiki_urls:
        out["note"] = "this record cites no Wikipedia page; the source is added all the same"
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    for k, v in after.items():
        if v:
            props[k] = v
        else:
            props.pop(k, None)
    _write_collection(f, stored, lines)
    rep = _rebuild(root)
    from hydra import provenance
    origin = provenance.origin(new_url[0]) if new_url else "a kept source"
    return {**out, "swapped": True, "build": rep, "snapshot": _snap(root, f"re-sourced {record}: {origin} instead of Wikipedia")}


def keys_in_use(root: Path) -> dict:
    """keys.yaml as in effect, and how many entities hold a key of each namespace."""
    from collections import Counter
    from hydra import keys as hkeys
    conf = hkeys.load(root)
    held = Counter(k.split(":", 1)[0] for k in core._keyed(root))
    return {"file": str(hkeys.path(root)), "primary": conf["primary"], "namespaces": conf["namespaces"],
            "held": dict(held), "undeclared": sorted(ns for ns in held if ns not in conf["namespaces"])}


# ---- the archive's own rules ---------------------------------------------------------

def set_positions(root: Path, positions: dict, confirm: bool = False) -> dict:
    """Preview (default) or write `.hydra/rules/positions.yaml`: this archive's rank ladder,
    {name: {below: [...], titles: [...], outside: bool}}. The preview says, for each
    position, how many roles in the archive its titles rank, and which roles none takes."""
    from hydra.shape import rules
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
    return {**out, "written": p.relative_to(root).as_posix(), "build": rep,
            "snapshot": _snap(root, f"set_positions: {len(positions)} positions")}


def _all_records(root: Path) -> list[dict]:
    files, _ = resources.record_files(root)
    out = []
    for f in files:
        out += core._load_records(f)
    return out


def link_images(root: Path, images: list[dict], confirm: bool = False) -> dict:
    """Many `link_image` calls at once: [{image, kind, name?, schema?, position?, titled?}, ...]."""
    done, problems = [], []
    for i, item in enumerate(images or []):
        match = {k: item.get(k) for k in ("schema", "position", "titled", "name")}
        try:
            done.append(core.link_image(root, item.get("image", ""), item.get("kind", ""), match, confirm))
        except IngestError as e:
            problems.append({"item": i, "image": item.get("image"), "error": str(e)})
    out = {"images": len(done), "problems": problems,
           "added": sum(1 for d in done if d.get("added"))}
    if confirm and out["added"]:
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
    return {**out, "restored": changed, "snapshot": new, "build": rep}
