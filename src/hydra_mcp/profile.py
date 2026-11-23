"""profile.py — a source file measured once, and its part plan (design: "Source profiles and chunked reading",
owner 2026-11-21; wave 1).

    profile(path)            -> {file, size, quality, structure, links, parts, warnings, next}; no text
    part_text(path, n)       -> (part, its text)

A long source is never read whole: it is cut into parts that each fit one tool call, at headings where it has them,
never inside a page, and the agent reads one part at a time (`read_file(part=n)`). The profile is kept in the machine
cache by the file's SHA-1, beside the extracted text (`files.read`), so a 165-page PDF costs its extraction once per
machine. Everything here is measured from the text; nothing is guessed about who wrote it or why.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from hydra_mcp import files

PART = 20_000                 # characters a part aims at (~6k tokens): well under a tool reply's cap
MIN_SHARE = 0.4               # a heading ends a part once the part holds this share of PART
VERSION = 4                   # bump when the profile's shape or the part rule changes: old cached profiles are redone

HEADING = re.compile(                                                # numbers are left out: "12. While he ..." is a
    r"^(?:(?:[IVXLC]+|[A-Z])\.\s+[A-Z][^\n]{2,60}"                    # numbered paragraph, counted on its own
                                                                       # (I. Introduction / A. What the Israelis ...)
    r"|(?:Chapter|CHAPTER|Part|PART|Section|SECTION|Annex|ANNEX|Appendix|APPENDIX)\s+[\w.-]+[^\n]{0,70}"
    r"|#{1,4}\s+\S[^\n]{0,80}"                                         # Markdown
    r"|[A-Z][A-Z0-9 ,.'&()-]{3,60}[A-Z)])$"                            # A SHORT LINE IN CAPITALS
)
NUMBERED = re.compile(r"^\s*(\d{1,4})\.\s+[A-Z(\"']", re.M)           # "42. While his cooperation ..."
REDACTION = re.compile(r"\[\s*\]|\(b\)\s*\(\d\)|█+|X{4,}|\[REDACTED\]|\[redacted\]")
URL = re.compile(r"https?://[^\s<>\"')\]]+")
BACK = re.compile(r"^(?:index|bibliography|references|notes|sources|endnotes)\b", re.I)


def _cache_file(sha1: str) -> Path:
    return files.cache_dir() / "profiles" / f"{sha1}.v{VERSION}.json"


_RUNNING: dict[tuple, set] = {}          # a text's key -> lines that repeat on many pages (running heads, stamps)


def _running(text: str) -> set:
    key = (len(text), hash(text[:2000]), hash(text[-2000:]))
    if key not in _RUNNING:
        n = Counter(l.strip() for l in text.split("\n") if 4 <= len(l.strip()) <= 90)
        _RUNNING.clear()
        _RUNNING[key] = {l for l, k in n.items() if k >= 3}
    return _RUNNING[key]


def _headings(text: str, start: int, end: int) -> list[tuple[int, str]]:
    """(offset, heading) of every line in text[start:end] that reads as a heading. A line repeated on three or more
    pages is a running head or a stamp, not a heading."""
    out, pos, skip = [], start, _running(text)
    for line in text[start:end].split("\n"):
        s = line.strip()
        if (4 <= len(s) <= 90 and HEADING.match(s) and not s.endswith((",", ";")) and s not in skip
                and not CONTENTS.search(s) and _wordy(s)):
            out.append((pos + line.find(s), s.lstrip("# ").strip()))
        pos += len(line) + 1
    return out


CONTENTS = re.compile(r"(?:\.\s*){3,}|\t\s*\d{1,3}\s*$|\s{3,}\d{1,3}\s*$")    # a contents line: dot leaders, a page number
STRUCTURAL = re.compile(r"^(?:[IVXLC]+\.\s|Chapter\s|CHAPTER\s|Part\s|PART\s|#)")


def _wordy(s: str) -> bool:
    """A heading in capitals has real words; OCR debris ("L------EJ----1 )", "I 13 I I") does not."""
    if STRUCTURAL.match(s) or re.match(r"^[A-Z]\.\s", s):
        return True
    letters = sum(c.isalpha() for c in s)
    return len(re.findall(r"[A-Z]{3,}", s)) >= 2 and letters >= 0.7 * len(s.replace(" ", ""))


def _paragraph_run(nums: list[int]) -> dict | None:
    """The numbered paragraphs as a run from 1: the largest n such that most of 1..n are present (a year at the start
    of a line, "1987.", is no paragraph number)."""
    have = {n for n in nums if 0 < n < 1000}
    best = 0
    for n in sorted(have):
        if sum(1 for k in range(1, n + 1) if k in have) >= 0.6 * n:
            best = n
    return {"count": sum(1 for k in have if k <= best), "first": 1, "last": best} if best >= 5 else None


def _units(text: str, ranges: list[dict] | None) -> list[dict]:
    """The pieces a part is made of: a PDF's pages, else blocks between blank lines. A piece longer than a part is
    split at blank lines inside it (a page that long is rare)."""
    if ranges:
        units = [{"start": r["start"], "end": r["end"], "page": r["page"]} for r in ranges]
    else:
        units, pos = [], 0
        for m in re.finditer(r"\n\s*\n", text):
            if m.start() > pos:
                units.append({"start": pos, "end": m.start(), "page": None})
            pos = m.end()
        if pos < len(text):
            units.append({"start": pos, "end": len(text), "page": None})
    out = []
    for u in units:
        if u["end"] - u["start"] <= PART:
            out.append(u)
            continue
        s = u["start"]
        while u["end"] - s > PART:                                  # cut at the last blank line before the budget
            cut = text.rfind("\n\n", s, s + PART)
            cut = cut if cut > s + PART // 4 else s + PART
            out.append({"start": s, "end": cut, "page": u["page"]})
            s = cut
        out.append({"start": s, "end": u["end"], "page": u["page"]})
    return out


def plan(text: str, ranges: list[dict] | None) -> list[dict]:
    """The parts: units added in order; a part closes when the next unit would pass PART, or when the next unit
    opens with a heading and the part already holds MIN_SHARE of PART."""
    units = _units(text, ranges)
    parts, cur = [], []

    def close():
        if not cur:
            return
        s, e = cur[0]["start"], cur[-1]["end"]
        pages = [u["page"] for u in cur if u["page"]]
        hs = _headings(text, s, e)
        parts.append({"part": len(parts) + 1, "title": hs[0][1] if hs else None,
                      "pages": (f"{pages[0]}" if pages[0] == pages[-1] else f"{pages[0]}-{pages[-1]}") if pages else None,
                      "start": s, "end": e, "chars": e - s, "tokens": (e - s) // 4})
        cur.clear()

    for u in units:
        size = sum(x["end"] - x["start"] for x in cur)
        opens = bool(_headings(text, u["start"], min(u["end"], u["start"] + 400)))
        if cur and (size + (u["end"] - u["start"]) > PART or (opens and size >= PART * MIN_SHARE)):
            close()
        cur.append(u)
    close()
    return parts


def _quality(text: str, ranges: list[dict] | None, pages: int | None) -> dict:
    letters = sum(c.isalnum() for c in text) or 1
    odd = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in ".,;:'\"!?()-–—/%$&@#*+=[]§°’‘“”…"))
    lines = [l for l in text.splitlines() if l.strip()]
    short = sum(1 for l in lines if len(l.strip()) <= 2)
    filled = len(ranges or [])
    return {"text_layer": "none" if not text.strip() else ("partial" if pages and filled < pages * 0.8 else "full"),
            "empty_pages": (pages - filled) if pages else None,
            "noise": round(odd / letters, 4),
            "garbled_lines": round(short / max(1, len(lines)), 4),
            "redactions": len(REDACTION.findall(text))}


def _structure(text: str, ranges: list[dict] | None) -> dict:
    page_of = lambda off: next((r["page"] for r in ranges or () if r["start"] <= off < r["end"] + 2), None)
    contents = [r["page"] for r in ranges or ()                       # a contents page: three or more contents lines
                if sum(1 for l in text[r["start"]:r["end"]].split("\n") if CONTENTS.search(l.strip())) >= 3]
    hs = [(o, t) for o, t in _headings(text, 0, len(text)) if page_of(o) not in contents]
    first = next((o for o, t in hs if STRUCTURAL.match(t)), hs[0][0] if hs else 0)   # the body opens at "I." / Chapter / Part
    back = [h for h in hs if BACK.match(h[1])]
    return {"headings": [{"text": t, "page": page_of(o)} for o, t in hs[:40]], "contents_pages": contents,
            "numbered_paragraphs": _paragraph_run([int(n) for n in NUMBERED.findall(text)]),
            "front_matter": {"pages": f"1-{page_of(first) - 1}"} if ranges and first and (page_of(first) or 1) > 1 else None,
            "back_matter": [{"text": t, "page": page_of(o)} for o, t in back][:5]}


def _links(text: str) -> dict:
    hosts = Counter(urlsplit(u).netloc.lower().removeprefix("www.") for u in URL.findall(text))
    return {"count": sum(hosts.values()), "by_site": dict(hosts.most_common(10))}


def _warnings(info: dict, q: dict, st: dict, parts: list[dict]) -> list[str]:
    w = []
    if q["text_layer"] == "partial":
        w.append(f"{q['empty_pages']} of {info['pages']} pages have no text layer: those pages need OCR before they can be quoted")
    if q["noise"] > 0.01:
        w.append(f"OCR noise {q['noise']:.1%}: quotes must copy the text as extracted, stray characters included")
    if q["redactions"]:
        w.append(f"{q['redactions']} redaction marks: names may be cut; record only what is legible")
    if st.get("front_matter"):
        w.append(f"pp. {st['front_matter']['pages']} come before the first heading: front matter, by default out of scope")
    if st.get("back_matter"):
        w.append("back matter (" + ", ".join(f"{b['text']} p. {b['page']}" if b["page"] else b["text"] for b in st["back_matter"])
                 + "): by default out of scope")
    if st.get("numbered_paragraphs"):
        n = st["numbered_paragraphs"]
        w.append(f"numbered paragraphs {n['first']}-{n['last']}: cite them with `locator` (\"para 12\")")
    if len(parts) > 1:
        w.append(f"{len(parts)} parts of about {PART:,} characters: read them one at a time with read_file(part=n)")
    return w


def profile(path: Path) -> dict:
    """The profile of one file, from the machine cache when it is there (keyed by the file's SHA-1)."""
    info = files.read(path)
    hit = _cache_file(info["sha1"])
    if hit.is_file():
        try:
            return {**json.loads(hit.read_text(encoding="utf-8")), "file": str(path), "name": path.name}
        except ValueError:
            pass
    text, ranges = info["text"], info.get("page_ranges")
    parts = plan(text, ranges)
    words = len(text.split())
    per_page = [len(text[r["start"]:r["end"]].split()) for r in ranges or ()]
    size = {"pages": info.get("pages"), "chars": len(text), "words": words, "tokens": len(text) // 4,
            "words_per_page": ({"median": int(statistics.median(per_page)), "low": min(per_page), "high": max(per_page)}
                               if per_page else None)}
    q, st = _quality(text, ranges, info.get("pages")), _structure(text, ranges)
    out = {"file": str(path), "name": path.name, "type": info["type"], "bytes": info["size"], "sha1": info["sha1"],
           "extractor": info["extractor"], "size": size, "quality": q, "structure": st, "links": _links(text),
           "parts": [{k: v for k, v in p.items()} for p in parts],
           "warnings": _warnings(info, q, st, parts)}
    out["next"] = ("read_file(path, part=1); read the parts in scope one at a time" if len(parts) > 1
                   else "read_file(path) returns the whole text: it fits one part")
    try:
        hit.parent.mkdir(parents=True, exist_ok=True)
        tmp = hit.with_name(hit.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(hit)
    except OSError:
        pass                                                         # a cache that cannot be written is no error
    return out


def part_text(path: Path, n: int) -> tuple[dict, str, int]:
    """(part n's row, its text, how many parts) of a file."""
    prof = profile(path)
    parts = prof["parts"]
    if not 1 <= int(n) <= len(parts):
        from hydra_mcp.core import IngestError
        raise IngestError(f"{path.name} has {len(parts)} part{'s' if len(parts) != 1 else ''}: ask for part 1 to {len(parts)}")
    p = parts[int(n) - 1]
    text = files.read(path)["text"]
    return p, text[p["start"]:p["end"]], len(parts)
