"""sources.py — evidence from the web, kept in the archive, and the text quotes are checked against.

    fetch(root, url)              fetch a page as text and keep it as a source of its own (an Article),
                                  so records cite it by id: `"sources": ["doc-..."]`
    read(root, source, ...)       a kept source's text in parts, or only the sentences with given words
    text_of(root, source_id)      a kept source's text (what `check_records` matches quotes against)
    verbatim(note, texts)         is the note in one of the texts, word for word

`page`, `fetch`, `text_of`, `page_labels_of`, `verbatim` and their helpers live in `hydra.api.sources` (plans/imports.md
I2b) and are re-exported here; what stays is what only the tools use: `citers`, `drop`, `list_sources`, `read` and
Wikipedia's footnotes.

Wikipedia pages are read through the wiki's own raw text (redirects followed, markup stripped, the
infobox kept as `field: value` lines); any other page as the text of its body. Nothing summarizes:
what is kept is what was published. The request carries a generic User-Agent and nothing else.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from hydra.sources import citations as hcite, catalog as hsources
from hydra.archive import layout, resources
from hydra.api.sources import (MAX_BYTES, MENU, PART, UA, _FILE_INFO, _FOLD, _MENU_WORDS, _Text,  # noqa: F401
                               _file_info, _get, _html_text, _kept, _norm, _part, _slug, _wiki_clean, _wiki_text,
                               assess, fetch, page, page_labels_of, page_ranges_of, page_title, pages_of_quote,
                               text_of, verbatim)

from hydra_mcp import core, agent, workflows
from hydra_mcp.core import IngestError


def citers(root: Path, rec: dict) -> list[str]:
    """The records that cite a kept source: by its id in `sources`, by a citation row, or (a relationship) by its URL."""
    local = str(rec["id"]).split(":", 1)[-1]
    urls = {str(u) for u in (rec.get("properties") or {}).get("sourceUrl") or ()}
    out: list[str] = []
    for (rid, src_id) in hcite.load(root):
        if str(src_id).split(":", 1)[-1] == local:
            out.append(str(rid))
    for f in resources.record_files(root)[0]:
        for r in core._load_records(f):
            props = r.get("properties") or {}
            if any(str(x).split(":", 1)[-1] == local for x in props.get("sources") or ()) \
                    or (urls and urls & {str(u) for u in props.get("sourceUrl") or ()}):
                out.append(str(r.get("id") or ""))
    return list(dict.fromkeys(out))


def drop(root: Path, source: str, confirm: bool = False) -> dict:
    """Remove a kept source no record cites (a page fetched by mistake). One a record cites is refused, and
    the records are listed. Without `confirm`: what would go."""
    rec = core._existing_source(root, source)
    cited = citers(root, rec)
    if cited:
        shown = ", ".join(cited[:20]) + (f" and {len(cited) - 20} more" if len(cited) > 20 else "")
        raise IngestError(f"{rec['id']} is cited by {len(cited)} record(s): {shown}. Re-source or `amend_records` "
                          "those first; a cited source is evidence")
    coll = rec["collection"]
    sfile = root / layout.SOURCE_ENTRIES / f"{coll}.json"
    rest = [x for x in core._load_records(sfile) if x.get("id") != rec["id"]]
    folder = root / core.SOURCE_FILES / coll
    props = rec.get("properties") or {}
    out = {"source": rec["id"], "title": (props.get("title") or [""])[0], "url": (props.get("sourceUrl") or [""])[0],
           "collection": coll, "files": list(props.get("fileName") or ())}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    if rest:
        sfile.write_text(json.dumps(rest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        sfile.unlink(missing_ok=True)
    for name in props.get("fileName") or ():
        (folder / name).unlink(missing_ok=True)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    rep = agent._rebuild(root)
    workflows.hook_unsource(root, rec["id"])
    workflows.hook_log(root, f"drop_source {rec['id']}")
    return {**out, "dropped": True, "build": rep, "snapshot": agent._snap(root, f"drop source {rec['id']}")}


def list_sources(root: Path, query: str | None = None, uncited_only: bool = False, offset: int = 0,
                 limit: int = 100, uncited_entities: bool = False) -> dict:
    """List every kept source document in `.hydra/sources/entries/` (and in-data Documents when built),
    with their `doc-...` IDs, URLs, filenames, text availability, who cites them, and uncited sources/entities."""
    entries = core._source_entries(root)
    claims_path = root / layout.CLAIMS_JSONL
    built_rep = hsources.report(root) if claims_path.is_file() else None
    by_id: dict[str, dict] = {}
    if built_rep:
        for group_name in ("entries", "documents"):
            for item in built_rep.get(group_name) or ():
                local = item["id"].split(":", 1)[-1]
                by_id[local] = item
                by_id[item["id"]] = item
    # Also count citations in citations.jsonl and unbuilt collection records
    cited_map: dict[str, set[str]] = {}
    url_to_local: dict[str, set[str]] = {}
    for r in entries:
        loc = str(r["id"]).split(":", 1)[-1]
        for u in (r.get("properties") or {}).get("sourceUrl") or ():
            url_to_local.setdefault(str(u), set()).add(loc)
    for (rec_id, src_id) in hcite.load(root):
        cited_map.setdefault(str(src_id).split(":", 1)[-1], set()).add(rec_id)
    for f in resources.record_files(root)[0]:
        for r in core._load_records(f):
            props = r.get("properties") or {}
            for s in props.get("sources") or ():
                cited_map.setdefault(str(s).split(":", 1)[-1], set()).add(r.get("id") or "")
            for u in props.get("sourceUrl") or ():
                for loc in url_to_local.get(str(u), ()):
                    cited_map.setdefault(loc, set()).add(r.get("id") or "")
    q = (query or "").strip().casefold()
    rows = []
    for r in entries:
        props = r.get("properties") or {}
        sid = str(r["id"])
        local = sid.split(":", 1)[-1]
        binfo = by_id.get(local) or {}
        cited_entities = list(binfo.get("cited_by") or ())
        extra_recs = cited_map.get(local, set())
        cited_count = max(len(cited_entities), len(extra_recs))
        title = ((props.get("title") or props.get("fileName") or [sid])[0])
        url = (props.get("sourceUrl") or [""])[0]
        pub = (props.get("publisher") or [""])[0]
        fname = (props.get("fileName") or [""])[0]
        uncited = cited_count == 0
        if uncited_only and not uncited:
            continue
        if q and not any(q in str(x).casefold() for x in (sid, title, url, pub, fname, r.get("collection", ""))):
            continue
        has_text = bool(props.get("bodyText")) or any(
            (root / core.SOURCE_FILES / r["collection"] / name).is_file()
            for name in props.get("fileName") or ()
        )
        rows.append({
            "source_id": sid,
            "collection": r.get("collection"),
            "schema": r.get("schema"),
            "title": title,
            **({"url": url} if url else {}),
            **({"publisher": pub} if pub else {}),
            **({"fileName": fname} if fname else {}),
            "has_text": has_text,
            "cited_by_count": cited_count,
            "cited_by": [{"id": c["id"], "caption": c["caption"], "schema": c["schema"]} for c in cited_entities[:10]],
            "uncited": uncited,
        })
    rows.sort(key=lambda x: (not x["uncited"], str(x["title"]).casefold(), x["source_id"]))
    uncited_sources = [x["source_id"] for x in rows if x["uncited"]]
    shown, paging = core.page(rows, offset, limit)
    return {
        "count": len(rows),
        **paging,
        "sources": shown,
        "uncited_sources": uncited_sources,
        "uncited_entities_count": len(built_rep.get("unsourced") or ()) if built_rep else 0,
        **({"uncited_entities": (built_rep.get("unsourced") or [])[:50] if built_rep else []} if uncited_entities else {}),
        "next": "call `read_source(source='<source_id>')` to inspect any kept source's full text or search with `find`",
    }


def read(root: Path, source: str, offset: int = 0, find: list[str] | None = None) -> dict:
    """A kept source's text in parts, or (with `find`) every sentence containing one of the words."""
    text = text_of(root, source)
    if text is None:
        raise IngestError(f"no kept source '{source}' with text (fetch_source keeps one; `sources` in get_records)")
    if not find:
        ranges = page_ranges_of(root, source)
        return {"source_id": source, **_part(text, offset), **({"page_ranges": ranges} if ranges else {})}
    words = [w.lower() for w in find if w.strip()]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])|\n+", text)
    hits = [s.strip() for s in sentences if any(w in s.lower() for w in words)]
    return {"source_id": source, "chars": len(text), "matches": hits[:200], "more": max(0, len(hits) - 200)}


# ---- what Wikipedia itself cites

_REF = re.compile(r"<ref(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</ref>)", re.S | re.I)
_NAME = re.compile(r"""name\s*=\s*["']?([^"'/>]+?)["']?\s*(?:/|$)""", re.I)
_FIELD = re.compile(r"\|\s*([\w-]+)\s*=\s*([^|}]*)")


def _wiki_raw(url: str) -> tuple[str, str]:
    u = urllib.parse.urlsplit(url.strip())
    if not (u.netloc.endswith("wikipedia.org") and u.path.startswith("/wiki/")):
        raise IngestError(f"{url} is not a Wikipedia article")
    title = urllib.parse.unquote(u.path[len("/wiki/"):]).replace("_", " ")
    raw = ""
    for _ in range(4):
        data, _ = _get(f"{u.scheme}://{u.netloc}/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"}))
        raw = data.decode("utf-8", "replace")
        m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", raw, re.I)
        if not m:
            break
        title = m.group(1).strip()
    return raw, f"{u.scheme}://{u.netloc}/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def _ref_source(body: str) -> dict:
    """A <ref>'s contents -> {url, title, publisher, date}: a {{cite ...}} template, or a bare [link]."""
    f = {k.lower(): _wiki_clean(v).strip() for k, v in _FIELD.findall(body or "")}
    url = f.get("url") or next(iter(re.findall(r"https?://[^\s|\]}<]+", body or "")), "")
    pub = next((f[k] for k in ("publisher", "website", "work", "newspaper", "agency", "magazine", "journal") if f.get(k)), "")
    title = f.get("title") or _wiki_clean(re.sub(r"^\s*\[\S+\s*|\]\s*$", "", body or "")).strip()[:200]
    return {"url": url, "title": title, "publisher": pub, "date": f.get("date", ""),
            "archive_url": f.get("archive-url", ""), "text": _wiki_clean(body or "").strip()[:300]}


def footnotes(url: str, quote: str) -> dict:
    """The references Wikipedia attaches to the sentence `quote` came from, in the article at `url`: what
    Wikipedia itself relied on, to fetch, read and cite instead."""
    raw, cite = _wiki_raw(url)
    named = {}
    for m in _REF.finditer(raw):
        n = _NAME.search(m.group("attrs") or "")
        if n and m.group("body"):
            named.setdefault(n.group(1).strip(), m.group("body"))
    acc, marks, pos = "", [], 0
    for m in _REF.finditer(raw):                 # the article's text, with where each reference sits in it
        acc += _wiki_clean(raw[pos:m.start()])
        n = _NAME.search(m.group("attrs") or "")
        body = m.group("body") or (named.get(n.group(1).strip()) if n else None)
        marks.append((len(acc), body))
        pos = m.end()
    acc += _wiki_clean(raw[pos:])
    words = _norm(quote).split()
    tail = words[-12:] if len(words) > 12 else words
    hit = re.search(r"\s+".join(re.escape(w) for w in tail), acc.translate(_FOLD)) if tail else None
    if not hit:
        return {"article": cite, "found": False,
                "why": "the quote is not in the article's current text (it may have been edited since)"}
    end = hit.end()
    near = [b for p, b in marks if end - 3 <= p <= end + 40 and b]            # refs right after the sentence
    if not near:                                                              # else the paragraph's first ref
        stop = acc.find("\n\n", end)
        near = [b for p, b in marks if end <= p <= (stop if stop > 0 else end + 1500) and b][:1]
    found = [s for s in (_ref_source(b) for b in near) if s["url"] or s["title"]]
    return {"article": cite, "found": True, "sentence_end": end, "references": found,
            "next": ("fetch_source each reference's url, find the fact in its own words (read_source with find), "
                     "then swap_source with that quote") if found else
                    "Wikipedia gives no reference for this sentence: look for a primary or news source elsewhere"}


