"""tools/wikidata.py — the `wikidata` tool set: linking entries to Wikidata as questions for the person
(hydra_mcp.wikidataqs)."""
from __future__ import annotations

from hydra_mcp import core, wikidataqs as wdq
from hydra_mcp.app import _run, tool


@tool(name="wikidata_questions")
def wikidata_questions_tool(schema: str | None = None, limit: int = 5, offset: int = 0,
                            archive: str | None = None) -> dict:
    """The Wikidata questions for this archive: each entry with no Wikidata key yet (a Person, an Organization…),
    what the archive itself says about it (dates, country, posts held) and Wikidata's candidates (Q-id, label,
    description). Asks Wikidata once per entry and keeps the answer; writes no records. Put each question to the
    person; their answer goes to `wikidata_answer`. `schema` narrows to one type; page with `offset`."""
    return _run(lambda: wdq.questions(core.open_archive(archive), schema, limit, offset))


@tool(name="wikidata_answer")
def wikidata_answer_tool(entity: str, qid: str, confirm: bool = False, archive: str | None = None) -> dict:
    """The person's answer to one Wikidata question: `qid` is the candidate they confirmed, or `none`. A match pins
    the key to the entry's record and then imports the item's picture when Wikidata names one, with its licence
    and artist (no image is shown here). `none` stops the entry being asked again. A name is never proof: confirm
    only what the person confirmed. Without `confirm` it shows what it would do."""
    return _run(lambda: wdq.answer(core.open_archive(archive), entity, qid, confirm))


@tool(name="wikidata_status")
def wikidata_status_tool(archive: str | None = None) -> dict:
    """How far the archive is linked to Wikidata: its entries, how many are matched, answered "none", or open."""
    return _run(lambda: wdq.status(core.open_archive(archive)))
