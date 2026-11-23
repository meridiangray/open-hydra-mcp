"""article.py — an entry's article sections (D11), read and written through the same store the wiki's editor uses."""
from __future__ import annotations

from pathlib import Path

from hydra import articles

from hydra_mcp import core
from hydra_mcp.core import IngestError


def body_of(root: Path, entity: str) -> str:
    """The H body an entity's article is kept under: from an H (a merged one's survivor), a key, a record id, or a
    title only one entry has (`core.resolve_entity`; a shared title is refused with its Hs)."""
    return core.resolve_entity(root, entity).body


def _view(s: dict) -> dict:
    return {"id": s["id"], "heading": s["heading"], "text": s["text"], "imported": articles.is_imported(s),
            **{k: s[k] for k in ("from", "licence", "forked") if s.get(k)}}


def article_sections(root: Path, entity: str) -> dict:
    body = body_of(root, entity)
    return {"entity": entity, "h_body": body, "sections": [_view(s) for s in articles.load(root, body)]}


def set_article_section(root: Path, entity: str, heading: str, text: str, from_: str | None = None,
                        confirm: bool = False) -> dict:
    """Add a section, or replace the text of the one with this heading. Imported text (`from`) stays read-only in
    the wiki; a person's own text is never replaced by an import."""
    body = body_of(root, entity)
    sections = articles.load(root, body)
    sid = articles.heading_id(sections, heading)
    cur = next((s for s in sections if s["id"] == sid), None)
    if cur is None:
        action = "add"
    elif from_ and articles.is_imported(cur):
        action = "re-import"
    elif from_:
        raise IngestError("This section is the archive's own text; an import does not replace it.")
    elif articles.is_imported(cur):
        raise IngestError("This section is imported and read-only. A person forks it with Edit in the wiki first.")
    else:
        action = "replace"
    out = {"entity": entity, "h_body": body, "heading": heading, "action": action, "from": from_ or None, "written": False}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    try:
        if action == "add":
            s = articles.add(root, body, heading, text, from_)
        elif action == "re-import":
            s = articles.replace_import(root, body, sid, text, from_)
        else:
            s = articles.edit(root, body, sid, heading, text)
    except articles.Refused as e:
        raise IngestError(str(e)) from None
    return {**out, "written": True, "section": _view(s)}


def _section(root: Path, entity: str, heading: str) -> tuple[str, list[dict], dict]:
    body = body_of(root, entity)
    sections = articles.load(root, body)
    sid = articles.heading_id(sections, heading)
    if not sid:
        have = ", ".join(s["heading"] for s in sections) or "none"
        raise IngestError(f"No section headed '{heading}' (the sections: {have}).")
    return body, sections, next(s for s in sections if s["id"] == sid)


def remove_article_section(root: Path, entity: str, heading: str, confirm: bool = False) -> dict:
    """Take a section out of an entity's article (imported or the archive's own); one history step."""
    body, sections, s = _section(root, entity, heading)
    out = {"entity": entity, "h_body": body, "heading": s["heading"], "imported": articles.is_imported(s),
           "chars": len(s.get("text") or ""), "written": False}
    if not confirm:
        return {**out, "next": "confirm with the person, then call again with confirm=true"}
    articles.delete(root, body, s["id"])
    return {**out, "written": True, "sections": [x["heading"] for x in articles.load(root, body)]}


def move_article_section(root: Path, entity: str, heading: str, to: int, confirm: bool = False) -> dict:
    """Move a section to position `to` (1 is first) in an entity's article; one history step."""
    body, sections, s = _section(root, entity, heading)
    if not isinstance(to, int) or not 1 <= to <= len(sections):
        raise IngestError(f"`to` is a position from 1 to {len(sections)}.")
    now = sections.index(s) + 1
    order = [x["heading"] for x in sections]
    order.insert(to - 1, order.pop(now - 1))
    out = {"entity": entity, "h_body": body, "heading": s["heading"], "from": now, "to": to, "order": order, "written": False}
    if not confirm or now == to:
        return {**out, **({} if now == to else {"next": "confirm with the person, then call again with confirm=true"})}
    sections.insert(to - 1, sections.pop(now - 1))
    articles.save(root, body, sections, f"Article section moved: {s['heading']}")
    return {**out, "written": True, "order": [x["heading"] for x in articles.load(root, body)]}
