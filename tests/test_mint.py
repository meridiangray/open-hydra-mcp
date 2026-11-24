"""mint.py: the form of a minted id, the code table's coverage, and a remint."""
import random
import re

import pytest

from hydra.schema import loader as schema
from hydra_mcp import mint


def test_a_minted_id_is_a_code_and_ten_random_characters():
    rid = mint.mint_id("Person", rng=random.Random(1))
    assert re.fullmatch(r"per-[0-9a-hjkmnp-tv-z]{10}", rid) and mint.is_minted(rid)
    assert mint.is_minted("pollard:" + rid) and mint.is_minted(rid + "~p4")


def test_old_hand_written_ids_are_not_minted_ones():
    for legacy in ("p-walt", "rel-hb1", "employment-analyst", "person-jonathan-jay-pollard", "doc-bb-casefile~p1"):
        assert not mint.is_minted(legacy)


def test_the_same_name_twice_gets_two_ids_and_a_taken_id_is_never_reused():
    rng = random.Random(7)
    a = mint.mint_id("Person", rng=rng)
    b = mint.mint_id("Person", rng=rng)
    assert a != b
    first = mint.mint_id("Person", rng=random.Random(3))
    assert mint.mint_id("Person", taken=[first], rng=random.Random(3)) != first


def test_a_refinement_keeps_its_parents_code_and_a_relationship_has_its_own():
    assert mint.code_for("Company") == mint.code_for("PublicBody") == mint.code_for("Organization") == "org"
    assert mint.code_for("Article") == mint.code_for("Pages") == "doc"
    assert mint.code_for("Employment") != mint.code_for("Membership")


def test_pages_abstract_and_unknown_schemas_cannot_be_minted():
    for s in ("Page", "Thing", "NotASchema"):
        with pytest.raises(mint.MintError):
            mint.mint_id(s)


def test_the_table_has_no_code_twice_and_no_schema_twice():
    codes = list(mint.KINDS) + list(mint.LINKS)
    assert len(codes) == len(set(codes)) and all(re.fullmatch("[a-z]{3}", c) for c in codes)
    assert not set(codes) & {"cap", "ref", "grp", "cyc"}              # hydra's own decision-key prefixes
    schemas = [s for v in (*mint.KINDS.values(), *mint.LINKS.values()) for s in v]
    assert len(schemas) == len(set(schemas))


def test_every_schema_hydra_ships_has_a_code_or_is_a_page_or_abstract():
    schema.load()
    missing = [s for s in schema.SCHEMA if s not in mint.CODES and s not in mint.SUBPART + mint.ABSTRACT]
    assert not missing, f"add an id code in mint.py for: {missing}"


def test_one_file_is_one_document_id_and_a_page_is_a_locator():
    a, b = mint.document_id("E5ACAF72330A527A867C71615F220E61CB4F148E"), mint.document_id("e5acaf72330a527a867c71615f220e61cb4f148e")
    assert a == b and a.startswith("doc-") and mint.is_minted(a)
    assert mint.page_id(a, 4) == a + "~p4" and mint.is_minted(mint.page_id(a, 4))


def test_remint_moves_every_pointer_with_the_id_and_can_keep_the_old_one():
    recs = [
        {"id": "src", "schema": "Document", "properties": {"title": ["T"], "contentHash": ["abc123"]}},
        {"id": "p-jon", "schema": "Person", "properties": {"name": ["Jon"], "sources": ["src"]}},
        {"id": "m1", "schema": "Membership", "properties": {"member": ["Jon"], "organization": ["Navy"]}},
    ]
    new, ids = mint.remint(recs, rng=random.Random(5), keep_old=True)
    assert ids["src"] == mint.document_id("abc123")
    assert new[1]["id"] == ids["p-jon"] and new[1]["properties"]["sources"] == [ids["src"]]
    assert new[1]["referents"] == ["p-jon"] and new[2]["properties"]["member"] == ["Jon"]
    assert all(mint.is_minted(r["id"]) for r in new) and len({r["id"] for r in new}) == 3
    assert recs[1]["id"] == "p-jon"                                   # the input is not touched
