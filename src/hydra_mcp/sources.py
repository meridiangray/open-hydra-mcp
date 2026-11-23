"""sources.py — evidence from the web, kept in the archive, and the text quotes are checked against.

    fetch(root, url)              fetch a page as text and keep it as a source of its own (an Article),
                                  so records cite it by id: `"sources": ["doc-..."]`
    read(root, source, ...)       a kept source's text in parts, or only the sentences with given words
    text_of(root, source_id)      a kept source's text (what `check_records` matches quotes against)
    verbatim(note, texts)         is the note in one of the texts, word for word

Wikipedia pages are read through the wiki's own raw text (redirects followed, markup stripped, the
infobox kept as `field: value` lines); any other page as the text of its body. Nothing summarizes:
what is kept is what was published. The request carries a generic User-Agent and nothing else.
"""
from __future__ import annotations

import html
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from hydra import layout

from hydra_mcp import core
from hydra_mcp.core import IngestError

UA = {"User-Agent": "hydra-mcp (source fetch)"}
MAX_BYTES = 8_000_000
PART = 20_000


# ---- text from a page

def _wiki_clean(t: str) -> str:
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>/]*/>", "", t)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"\{\{\s*(?:snd|spnd|sndash|spaced ndash|ndash|nbsp)\s*\}\}", " – ", t, flags=re.I)
    for _ in range(4):
        t = re.sub(r"\{\{(?:convert|cvt)\|([\d.,]+)\|(\w+)[^{}]*\}\}", r"\1 \2", t)
        t = re.sub(r"\{\{(?:lang|nowrap)\|(?:[a-z-]+\|)?([^{}|]*)\}\}", r"\1", t)
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", t)
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
    t = re.sub(r"'''?", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


def _wiki_text(raw: str) -> str:
    """Wikitext -> its infobox as `field: value` lines, then the article's text."""
    lines, rest = [], raw
    box = re.search(r"\{\{Infobox(.*?)\n\}\}", raw, re.S)
    if box:
        for line in box.group(1).splitlines():
            m = re.match(r"\s*\|\s*([\w ]+?)\s*=\s*(.+)", line)
            value = re.sub(r"\s+", " ", _wiki_clean(m.group(2))).strip() if m else ""
            if value:                                   # (kept out of the f-string: Python 3.11 has no backslash there)
                lines.append(f"{m.group(1)}: {value}")
        rest = raw[:box.start()] + raw[box.end():]
    body = _wiki_clean(rest)
    body = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\n\1\n", body, flags=re.M)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return ("\n".join(lines) + "\n\n" if lines else "") + body


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "form", "svg"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "section", "article", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._in_title, self._titled = [], 0, "", False, False
        self.og, self.h1, self._in_h1 = "", "", 0                      # og:title and the first <h1>, a page's own title

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.og:
            a = {k.lower(): v for k, v in attrs if k}
            if (a.get("property") or a.get("name") or "").lower() == "og:title" and a.get("content"):
                self.og = a["content"]
        if tag in self.SKIP:
            self.skip += 1
        if tag == "h1" and not self.skip and not self.h1:
            self._in_h1 += 1
        if tag == "title" and not self.skip and not self._titled:      # an <svg><title>Chevron</title></svg> is an icon's name, not the page's
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title" and self._in_title:
            self._in_title, self._titled = False, True
        if tag == "h1" and self._in_h1:
            self._in_h1 = 0
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)
            if self._in_h1:
                self.h1 += data


def _html_text(raw: str) -> tuple[str, str]:
    p = _Text()
    p.feed(raw)
    text = re.sub(r"[ \t]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r" *\n *", "\n", text)).strip()
    return text, page_title(p.og, p.h1, p.title)


_MENU_WORDS = r"(?:Menu|Search|Chevron|User|Close|Open|Sign ?[Ii]n|Log ?[Ii]n|Subscribe|Account|Toggle)"
MENU = re.compile(rf"(?<=[a-z]){_MENU_WORDS}|{_MENU_WORDS}(?=[A-Z])")      # glued to the word before, or after


def page_title(og: str, h1: str, title: str) -> str:
    """A fetched page's own title (Archive Workflow G14): its og:title, else its first <h1>, else <title>; and the
    site's menu words glued on after it ("...targets | The NationalMenu SearchUserUserChevron") cut off."""
    for t in (og, h1, title):
        t = re.sub(r"\s+", " ", t or "").strip()
        if not t:
            continue
        m = MENU.search(t)
        if m and m.start() > 0:
            t = t[:m.start()].rstrip(" |-·:")
        return t[:300]
    return ""


def _get(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read(MAX_BYTES + 1)
            final = r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise IngestError(f"{url}: no such page ({e.code}); check the address or the article's exact title") from None
        raise IngestError(f"{url} answered {e.code}: the page cannot be fetched this way. Do not work around the "
                          "refusal; ask the person to save the page and give its file to read_file") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise IngestError(f"{url} could not be reached: {e}") from None
    if len(data) > MAX_BYTES:
        raise IngestError(f"{url} is over {MAX_BYTES:,} bytes; save it and give the file to read_file")
    return data, final


def page(url: str) -> dict:
    """{url (the one to cite), title, text, publisher, kind}: a page's published text."""
    u = urllib.parse.urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise IngestError(f"'{url}' is not a web address (http or https)")
    if u.netloc.endswith("wikipedia.org") and u.path.startswith("/wiki/"):
        title = urllib.parse.unquote(u.path[len("/wiki/"):]).replace("_", " ")
        for _ in range(4):
            raw_url = f"{u.scheme}://{u.netloc}/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
            data, _ = _get(raw_url)
            raw = data.decode("utf-8", "replace")
            m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", raw, re.I)
            if not m:
                break
            title = m.group(1).strip()
        cite = f"{u.scheme}://{u.netloc}/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        return {"url": cite, "title": title, "text": _wiki_text(raw), "publisher": "Wikipedia", "kind": "wikitext"}
    data, final = _get(url)
    text, title = _html_text(data.decode("utf-8", "replace"))
    return {"url": final, "title": title or u.netloc, "text": text, "publisher": u.netloc, "kind": "html"}


# ---- kept sources

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "page"


def assess(got: dict) -> str | None:
    """Why a fetched web page is probably no evidence: a front page, hardly any text, or little but
    navigation. None when it looks like an article. Wikipedia text is never thin."""
    if got.get("kind") != "html":
        return None
    text = got.get("text") or ""
    u = urllib.parse.urlsplit(got.get("url") or "")
    if u.scheme and u.path in ("", "/") and not u.query:
        return f"{u.netloc} is a front page (a root address), not an article"
    if len(text.strip()) < 600:
        return f"very little text ({len(text.strip())} characters)"
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    short = sum(1 for x in lines if len(x.split()) <= 4)
    prose = sum(1 for x in lines if len(x.split()) >= 12)
    if len(lines) >= 10 and short / len(lines) >= 0.8 and prose <= 2:
        return f"mostly navigation: {short} of {len(lines)} lines are menu-sized, {prose} are sentences"
    return None


def fetch(root: Path, url: str, title: str | None = None, published: str | None = None,
          author: str | None = None, publisher: str | None = None, summary: str | None = None,
          language: str | None = None, keywords: list[str] | None = None, prefetched: dict | None = None,
          keep_thin: bool = True) -> dict:
    """Fetch `url` and keep its text as a source of its own; -> its id and the first part of the text.
    `prefetched`: the result of `page(url)` already fetched (a caller that holds the write lock only to write).
    `keep_thin` False: a page that looks useless (see `assess`) is not kept; the result says why."""
    got = prefetched if prefetched is not None else page(url)
    if not got["text"].strip():
        raise IngestError(f"{got['url']} has no text to keep (a page built by scripts?): save it as a file instead")
    with tempfile.TemporaryDirectory(prefix="hydra-fetch-") as tmp:
        f = Path(tmp) / f"{_slug(got['title'])}.txt"
        f.write_text(got["text"], encoding="utf-8")
        from hydra_mcp import files
        have = core._source_by_hash(root).get(files.read(f)["sha1"])
        if have:
            return {"source_id": have["id"], "already_kept": True, "url": got["url"], "title": got["title"],
                    **_part(got["text"], 0)}
        thin = assess(got)
        if thin and not keep_thin:
            return {"kept": False, "quality": "thin", "reason": thin, "url": got["url"], "title": got["title"],
                    "kind": got["kind"], "chars": len(got["text"]), "text": got["text"][:600],
                    "next": "this page is probably no evidence: fetch the article's own address instead; "
                            "to keep it all the same, call again with keep=true"}
        coll, n = f"src-{_slug(got['title'])}", 1
        while (root / layout.SOURCE_ENTRIES / f"{coll}.json").exists():
            n += 1
            coll = f"src-{_slug(got['title'])}-{n}"
        doc, path, _ = core._new_source(root, coll, {"file": str(f), "url": got["url"], "title": title or got["title"],
                                                     "publisher": publisher or got["publisher"],
                                                     "published": published, "author": author,
                                                     "summary": summary, "language": language,
                                                     "keywords": keywords})
        sfile = root / layout.SOURCE_ENTRIES / f"{coll}.json"
        ffile = root / core.SOURCE_FILES / coll / path.name
        for x in (sfile, ffile):
            x.parent.mkdir(parents=True, exist_ok=True)
        sfile.write_text(json.dumps([doc], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        ffile.write_bytes(path.read_bytes())
    from hydra_mcp import agent, workflows
    snap = agent._snap(root, f"fetch {got['url']}")
    workflows.hook_source(root, doc["id"], f"fetch_source {doc['id']} ({got['title']})")
    return {"source_id": doc["id"], "already_kept": False, "kept": True,
            "quality": "thin" if thin else "ok", **({"reason": thin} if thin else {}),
            "url": got["url"], "title": doc["properties"]["title"][0],
            "kind": got["kind"], "kept_as": ffile.relative_to(root).as_posix(), **({"snapshot": snap} if snap else {}),
            **_part(got["text"], 0),
            "next": f'cite it on each record it supports: "sources": ["{doc["id"]}"]; quote it verbatim in `notes`'}


def citers(root: Path, rec: dict) -> list[str]:
    """The records that cite a kept source: by its id in `sources`, by a citation row, or (a relationship) by its URL."""
    from hydra import citations as hcite, resources
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
    from hydra_mcp import agent, workflows
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
    from hydra import citations as hcite, resources, sources as hsources
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


_FILE_INFO: dict = {}


def _file_info(f: Path) -> dict:
    """files.read of a kept file, kept for the process while the file stays as it is (a PDF is slow to read)."""
    from hydra_mcp import files
    st = f.stat()
    key = (str(f), st.st_size, st.st_mtime_ns)
    if key not in _FILE_INFO:
        if len(_FILE_INFO) > 8:
            _FILE_INFO.clear()
        _FILE_INFO[key] = files.read(f)
    return _FILE_INFO[key]


def _kept(root: Path, source_id: str) -> tuple[str, list[dict]] | None:
    """(text, page_ranges) of a kept source: its body text, or its file's text; None when there is none."""
    try:
        r = core._existing_source(root, source_id)
    except IngestError:
        return None
    props = r.get("properties") or {}
    if props.get("bodyText"):
        return "\n".join(props["bodyText"]), []
    for name in props.get("fileName") or ():
        f = root / core.SOURCE_FILES / r["collection"] / name
        if f.is_file():
            info = _file_info(f)
            return info["text"], info.get("page_ranges") or []
    return None


def text_of(root: Path, source_id: str) -> str | None:
    """The text of a kept source (its file's text, or its body text); None when there is none."""
    got = _kept(root, source_id)
    return got[0] if got else None


def page_ranges_of(root: Path, source_id: str) -> list[dict]:
    """[{page, start, end}] over the source's text, for a kept PDF; [] for any other source."""
    got = _kept(root, source_id)
    return got[1] if got else []


def page_labels_of(root: Path, source_id: str) -> dict[int, str]:
    """{PDF page: the page number printed on it} for a kept PDF, confirmed labels only (hydra.pagelabels); {} otherwise."""
    from hydra import pagelabels
    got = _kept(root, source_id)
    return pagelabels.labels(got[0], got[1]) if got and got[1] else {}


def pages_of_quote(text: str, ranges: list[dict], quote: str) -> str | None:
    """The page ("14") or pages ("14-15", when the quote runs over a page break) where `quote` stands, found with
    the normalisation `verbatim` uses; None when it is not found or the source has no pages."""
    q = _norm(quote)
    if not ranges or not q:
        return None
    pages = [(r["page"], _norm(text[r["start"]:r["end"]])) for r in ranges]
    for n, t in pages:
        if q in t:
            return str(n)
    for (n1, t1), (n2, t2) in zip(pages, pages[1:]):
        if q in t1 + " " + t2:
            return f"{n1}-{n2}"
    return None


def _part(text: str, offset: int) -> dict:
    offset = max(0, int(offset or 0))
    part = text[offset:offset + PART]
    nxt = offset + len(part) if offset + len(part) < len(text) else None
    return {"chars": len(text), "offset": offset, "next_offset": nxt, "text": part}


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


# ---- quotes

_FOLD = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201b": "'", "\u02bc": "'", "\u201c": '"', "\u201d": '"',
                       "\u201e": '"', "\u00ab": '"', "\u00bb": '"', "\u2010": "-", "\u2011": "-", "\u2012": "-",
                       "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-", "\u00ad": None,
                       "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u200b": None})


def _norm(s: str) -> str:
    """Comparison form: NFC, typographic quotes/apostrophes and dashes plain, every kind of space one space."""
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s)).translate(_FOLD)).strip()


def verbatim(note: str, texts: list[str]) -> bool:
    """Is `note` in one of `texts` word for word? Spacing, curly quotes and dashes are not counted."""
    n = _norm(note)
    return bool(n) and any(n in _norm(t) for t in texts if t)
