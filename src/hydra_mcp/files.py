"""Reading a source file: its text, exactly as the file holds it, and what it is.

The server reads the file itself, so the text the model labels from is the
file's own, not the assistant's copy of it. The archive keeps the file plus a
fingerprint of the extracted text (extractor name and sha1), not the text
itself. Text files, Markdown, HTML, PDF, Word (.docx) and EPUB. A PDF with no text
layer (a scan) has nothing to read: that is an error, never an empty source.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

from hydra_mcp.core import IngestError

TYPES = {".txt": "text/plain", ".text": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown",
         ".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".epub": "application/epub+zip"}


class _Text(HTMLParser):
    SKIP, BLOCK = {"script", "style", "head", "noscript"}, {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4",
                                                              "h5", "h6", "section", "article", "blockquote", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in self.SKIP
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        self.skip -= tag in self.SKIP and self.skip > 0
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _pdf(path: Path) -> tuple[str, int, list[dict]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise IngestError(f"{path.name} is password-protected; ask the person for an unlocked copy")
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except PdfReadError as e:
        raise IngestError(f"{path.name} could not be read as a PDF: {e}") from None
    joined, ranges, pos = [], [], 0
    for idx, p in enumerate(pages, 1):
        cleaned = _tidy(p) if p else ""
        if not cleaned:
            continue
        if joined:
            pos += 2  # "\n\n" separator
        start = pos
        joined.append(cleaned)
        pos += len(cleaned)
        ranges.append({"page": idx, "start": start, "end": pos})
    return "\n\n".join(joined), len(pages), ranges


def _docx(path: Path) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    try:
        d = docx.Document(str(path))
    except (PackageNotFoundError, KeyError, ValueError) as e:
        raise IngestError(f"{path.name} could not be read as a Word document: {e}") from None
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        parts += [" | ".join(c.text.strip() for c in row.cells) for row in t.rows]
    return "\n".join(parts)


def _epub(path: Path) -> str:
    """An EPUB's text in reading order: the zip's container names the package, whose spine orders its XHTML files
    (Archive Workflow G10). Standard library only."""
    import posixpath
    import zipfile
    from xml.etree import ElementTree as ET
    try:
        z = zipfile.ZipFile(str(path))
        cont = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in cont.iter() if e.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(opf_path))
    except (zipfile.BadZipFile, KeyError, StopIteration, ET.ParseError) as e:
        raise IngestError(f"{path.name} could not be read as an EPUB: {e}") from None
    base = posixpath.dirname(opf_path)
    items = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("item")}
    order = [items[e.get("idref")] for e in opf.iter() if e.tag.endswith("itemref") and e.get("idref") in items]
    parts = []
    for href in order:
        try:
            raw = z.read(posixpath.normpath(posixpath.join(base, href)))
        except KeyError:
            continue
        p = _Text()
        p.feed(_decode(raw)[0])
        parts.append("".join(p.out))
    return "\n\n".join(t.strip() for t in parts if t.strip())


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+\n", "\n", text.replace("\r\n", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_BY_CONTENT: dict = {}                    # (sha1 of the bytes, suffix) -> a read, for the life of the process
SLOW = {".pdf", ".docx", ".epub"}
CACHE_ENV = "HYDRA_CACHE_DIR"


def cache_dir() -> Path:
    """This machine's hydra cache: extracted texts and source profiles, by content. `HYDRA_CACHE_DIR` overrides it."""
    import os
    given = os.environ.get(CACHE_ENV, "").strip()
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hydra" / "cache"


def _extractor_version(suffix: str) -> str:
    try:
        if suffix == ".pdf":
            import pypdf
            return f"pypdf-{pypdf.__version__}"
        if suffix == ".epub":
            return "zipfile-1"
        import docx
        return f"docx-{getattr(docx, '__version__', '0')}"
    except ImportError:
        return "none"


def _disk(key: tuple, suffix: str) -> Path:
    return cache_dir() / "text" / f"{key[0]}.{suffix.lstrip('.')}.{_extractor_version(suffix)}.json"


def _from_disk(key: tuple, suffix: str) -> dict | None:
    import json
    f = _disk(key, suffix)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def _to_disk(key: tuple, suffix: str, out: dict) -> None:
    import json
    f = _disk(key, suffix)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        pass                                                     # a cache that cannot be written is no error


def read(path: Path) -> dict:
    """{name, type, size, sha1, extractor, text_sha1, pages, text}: the file, the tool
    that extracted its text, and the sha1 of that extracted text. A PDF or Word file is read once per
    process by its content: the Pollard run (2026-11-21) extracted one 165-page PDF five times, about 20 s
    each, through read_file, save and check_records under two paths (the original and the kept copy)."""
    suffix = path.suffix.lower()
    if suffix not in TYPES:
        raise IngestError(f"{path.name}: hydra reads {', '.join(sorted(TYPES))} files"
                          + ("; save a .doc as .docx first" if suffix == ".doc" else ""))
    raw = path.read_bytes()
    key = (hashlib.sha1(raw).hexdigest(), suffix)
    if suffix in SLOW and key in _BY_CONTENT:
        return {**_BY_CONTENT[key], "name": path.name}        # a fresh dict: callers pop keys from it
    out = _from_disk(key, suffix) if suffix in SLOW else None   # another process read it already: once per machine
    if out is None:
        out = _read(path, suffix, raw)
        if suffix in SLOW:
            _to_disk(key, suffix, out)
    if suffix in SLOW:
        if len(_BY_CONTENT) > 8:
            _BY_CONTENT.clear()
        _BY_CONTENT[key] = out
        return {**out, "name": path.name}                      # the disk copy may carry another copy's file name
    return out


def _read(path: Path, suffix: str, raw: bytes) -> dict:
    pages = None
    page_ranges = None
    if suffix == ".pdf":
        import pypdf
        text, pages, page_ranges = _pdf(path)
        extractor = f"pypdf {pypdf.__version__}"
    elif suffix == ".docx":
        import docx
        text = _docx(path)
        extractor = f"python-docx {docx.__version__}"
    elif suffix == ".epub":
        text = _epub(path)
        extractor = "epub (zipfile, html.parser)"
    elif suffix in (".html", ".htm"):
        p = _Text()
        p.feed(_decode(raw)[0])
        text = "".join(p.out)
        extractor = "html.parser"
    else:
        text, enc = _decode(raw)
        extractor = f"text read ({enc})"
    text = _tidy(text)
    if not text:
        raise IngestError(f"{path.name} has no text to read" + (
            ": it looks like a scan (images of pages, no text layer); it needs OCR first" if suffix == ".pdf" else ""))
    return {"name": path.name, "type": TYPES[suffix], "size": len(raw), "sha1": hashlib.sha1(raw).hexdigest(),
            "extractor": extractor, "text_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            "pages": pages, **({"page_ranges": page_ranges} if page_ranges else {}), "text": text}
