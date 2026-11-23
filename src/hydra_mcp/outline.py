"""outline.py: a document's parts and their pages, without reading it (Archive Workflow G5, `source_outline`).

From the best structure the file has, in this order: a PDF's bookmarks (unless they are only scan batches, "pollard 1",
"pollard2"…), a Word file's heading styles, Markdown or HTML headings, else the heading lines `profile` finds in the
text ("I. Introduction", "Chapter 3", a short capitalised line). Each heading carries its level, its character offset
in the text hydra extracts (the text quotes are checked against) and, for a PDF, its page. Nothing is sent anywhere.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from hydra_mcp import files, profile

MAX = 400


def _bookmarks(path: Path) -> list[dict]:
    from pypdf import PdfReader
    try:
        r = PdfReader(str(path))
        out = []

        def walk(items, level):
            for it in items:
                if isinstance(it, list):
                    walk(it, level + 1)
                    continue
                try:
                    page = r.get_destination_page_number(it) + 1
                except Exception:                            # noqa: BLE001 - a broken bookmark names no page
                    page = None
                out.append({"level": level, "title": str(it.title or "").strip(), "page": page})
        walk(r.outline or [], 1)
        return [h for h in out if h["title"]]
    except Exception:                                        # noqa: BLE001 - an unreadable outline is no outline
        return []


def _scan_batches(heads: list[dict], stem: str) -> bool:
    """Bookmarks a scanner made ("pollard 1", "pollard2", "Scan 3"): the file's own name or a word, then a number."""
    base = re.sub(r"[^a-z]", "", stem.lower())[:8]
    batchy = [h for h in heads if re.fullmatch(r"[A-Za-z_-]+\s*\d{1,3}", h["title"])
              and (re.sub(r"[^a-z]", "", h["title"].lower()).startswith(base[:5]) or
                   h["title"].lower().startswith(("scan", "batch", "part", "page")))]
    return bool(heads) and len(batchy) >= len(heads) * 0.8


def _docx_heads(path: Path) -> list[dict]:
    import docx
    out = []
    for p in docx.Document(str(path)).paragraphs:
        m = re.match(r"Heading (\d)", p.style.name or "") if p.style is not None else None
        if (m or (p.style is not None and p.style.name == "Title")) and p.text.strip():
            out.append({"level": int(m.group(1)) if m else 0, "title": p.text.strip(), "page": None})
    return out


class _H(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.cur = [], None

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.cur = [int(tag[1]), ""]

    def handle_endtag(self, tag):
        if self.cur and re.fullmatch(r"h[1-6]", tag):
            if self.cur[1].strip():
                self.out.append({"level": self.cur[0], "title": " ".join(self.cur[1].split()), "page": None})
            self.cur = None

    def handle_data(self, data):
        if self.cur:
            self.cur[1] += data


def _markup_heads(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".md", ".markdown"):
        return [{"level": len(m.group(1)), "title": m.group(2).strip(), "page": None}
                for m in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*#*\s*$", raw)]
    p = _H()
    p.feed(raw)
    return p.out


def _place(heads: list[dict], text: str, ranges: list[dict]) -> list[dict]:
    """Each heading's offset in the extracted text (searched in order, so a contents page does not take it) and,
    from the page ranges, its page when the file gave none."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    flat, pos_map, at = [], [], 0
    for i, ch in enumerate(text):                             # a whitespace-folded copy, mapped back to offsets
        if ch.isspace():
            if flat and flat[-1] == " ":
                continue
            ch = " "
        flat.append(ch.lower())
        pos_map.append(i)
    flat = "".join(flat)
    out, cursor = [], 0
    for h in heads:
        k = norm(h["title"])
        i = flat.find(k, cursor) if k else -1
        off = pos_map[i] if i >= 0 else None
        if i >= 0:
            cursor = i + len(k)
        page = h.get("page")
        if page is None and off is not None:
            page = next((r["page"] for r in ranges if r["start"] <= off < r["end"]), None)
        out.append({**h, "offset": off, "page": page})
    return out


def _level(title: str) -> int:
    """"II. Background" 1, "A. Personal History" 2, "1. Scope" 3; anything else 1."""
    if re.match(r"^[IVXLC]+\.\s", title):
        return 1
    if re.match(r"^[A-Z]\.\s", title):
        return 2
    if re.match(r"^\d{1,2}\.\s", title):
        return 3
    return 1


def outline(path: Path) -> dict:
    """{file, from, headings: [{level, title, offset, page}], warnings}: the parts of the document at `path`."""
    path = Path(path)
    got = files.read(path)
    text, ranges, suffix = got["text"], got.get("page_ranges") or [], path.suffix.lower()
    heads, source, warnings = [], "", []
    if suffix == ".pdf":
        bm = _bookmarks(path)
        if bm and not _scan_batches(bm, path.stem):
            heads, source = bm, "bookmarks"
        elif bm:
            warnings.append(f"the PDF's {len(bm)} bookmarks are scan batches, not parts; headings come from the text")
    elif suffix == ".docx":
        heads, source = _docx_heads(path), "heading styles"
    elif suffix in (".md", ".markdown", ".html", ".htm"):
        heads, source = _markup_heads(path), "headings"
    contents = set()
    if not heads:
        heads = [{"level": _level(t), "title": t, "page": None} for _, t in profile._headings(text, 0, len(text))]
        source = "heading lines in the text"
        contents = set(profile.profile(path)["structure"].get("contents_pages") or [])
    placed = [h for h in _place(heads, text, ranges) if h["page"] not in contents or h["page"] is None]
    if contents:
        warnings.append(f"headings on the contents page(s) {sorted(contents)} are left out")
    if len(placed) > MAX:
        warnings.append(f"{len(placed)} headings; the first {MAX} are given")
    if not placed:
        warnings.append("no headings found: read the document in parts (`read_file`)")
    return {"file": str(path), "from": source, "count": len(placed), "headings": placed[:MAX], "warnings": warnings}
