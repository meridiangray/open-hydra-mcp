"""names.py: the capitalised names in a stretch of a document, with how often each comes (Archive Workflow G9,
`source_names`), and which already name something in the archive. A list to check coverage against, never a list to
record: nothing is decided from a name. The same rule as the `names` recipe (Archive Workflow recipes/names.sh), done
in Python on hydra's own extracted text, so it needs no shell tools. Nothing is sent anywhere.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from hydra_mcp import files

JOIN = r"(?:of |the |al-|bin |bint |ibn |de |da |di |du |la |le |van |von |der |den )"
NAME = re.compile(rf"[A-Z][A-Za-z'’.-]+(?: {JOIN}*[A-Z][A-Za-z'’.-]+)+")
LEAD = re.compile(r"^(?:The|This|That|These|Those|In|On|At|By|For|From|As|A|An|And|But|When|While|After|Before|"
                  r"During|His|Her|Their|Its|Our|Mr|Mrs|Ms|Dr) ")


def names_in(text: str, min_count: int = 1) -> list[dict]:
    """[{name, count}], most frequent first: runs of two or more capitalised words within a line (a word broken at a
    line end is joined first; "and" never joins two names; a possessive is dropped)."""
    text = re.sub(r"([a-z])-\r?\n([a-z])", r"\1\2", text)
    c = Counter()
    for line in text.splitlines():
        for m in NAME.finditer(line):
            for part in re.split(r"(?<=[a-z]{2})\. ", m.group(0)):   # a sentence's end, not an initial ("J. Edgar")
                n = LEAD.sub("", part).rstrip(".")
                n = re.sub(r"['’]s?$", "", n)
                if " " in n:
                    c[n] += 1
    return [{"name": n, "count": k} for n, k in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) if k >= min_count]


def source_names(path: Path, first: int | None = None, last: int | None = None, min_count: int = 1,
                 lookup=None) -> dict:
    """The names in pages first..last of a PDF (or the whole file), each with `in_archive`: the entries
    `lookup(name)` finds (an exact name or alias only; a near match is no match)."""
    got = files.read(Path(path))
    text, ranges = got["text"], got.get("page_ranges") or []
    if ranges and (first or last):
        lo, hi = first or 1, last or ranges[-1]["page"]
        text = "\n\n".join(got["text"][r["start"]:r["end"]] for r in ranges if lo <= r["page"] <= hi)
    rows = names_in(text, min_count)
    if lookup:
        for r in rows:
            r["in_archive"] = lookup(r["name"])
    return {"file": str(path), "pages": f"{first}-{last}" if (first or last) else "all", "count": len(rows),
            "names": rows,
            "use": "check each name is recorded or dropped with a reason; a name is never proof two records are one"}
