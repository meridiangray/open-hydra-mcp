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
        self.out, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def _html_text(raw: str) -> tuple[str, str]:
    p = _Text()
    p.feed(raw)
    text = re.sub(r"[ \t]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r" *\n *", "\n", text)).strip()
    return text, p.title.strip()


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


def fetch(root: Path, url: str, title: str | None = None, published: str | None = None,
          author: str | None = None) -> dict:
    """Fetch `url` and keep its text as a source of its own; -> its id and the first part of the text."""
    got = page(url)
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
        coll, n = f"src-{_slug(got['title'])}", 1
        while (root / layout.SOURCE_ENTRIES / f"{coll}.json").exists():
            n += 1
            coll = f"src-{_slug(got['title'])}-{n}"
        doc, path, _ = core._new_source(root, coll, {"file": str(f), "url": got["url"], "title": title or got["title"],
                                                     "publisher": got["publisher"], "published": published,
                                                     "author": author})
        sfile = root / layout.SOURCE_ENTRIES / f"{coll}.json"
        ffile = root / core.SOURCE_FILES / coll / path.name
        for x in (sfile, ffile):
            x.parent.mkdir(parents=True, exist_ok=True)
        sfile.write_text(json.dumps([doc], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        ffile.write_bytes(path.read_bytes())
    from hydra_mcp import agent
    snap = agent._snap(root, f"fetch {got['url']}")
    return {"source_id": doc["id"], "already_kept": False, "url": got["url"], "title": doc["properties"]["title"][0],
            "kind": got["kind"], "kept_as": ffile.relative_to(root).as_posix(), **({"snapshot": snap} if snap else {}),
            **_part(got["text"], 0),
            "next": f'cite it on each record it supports: "sources": ["{doc["id"]}"]; quote it verbatim in `notes`'}


def text_of(root: Path, source_id: str) -> str | None:
    """The text of a kept source (its file's text, or its body text); None when there is none."""
    try:
        r = core._existing_source(root, source_id)
    except IngestError:
        return None
    props = r.get("properties") or {}
    if props.get("bodyText"):
        return "\n".join(props["bodyText"])
    for name in props.get("fileName") or ():
        f = root / core.SOURCE_FILES / r["collection"] / name
        if f.is_file():
            from hydra_mcp import files
            return files.read(f)["text"]
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
        return {"source_id": source, **_part(text, offset)}
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

_FOLD = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).translate(_FOLD)).strip()


def verbatim(note: str, texts: list[str]) -> bool:
    """Is `note` in one of `texts` word for word? Spacing, curly quotes and dashes are not counted."""
    n = _norm(note)
    return bool(n) and any(n in _norm(t) for t in texts if t)
