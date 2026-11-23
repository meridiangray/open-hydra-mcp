"""mint.py — the ids for new records: `<code>-<10 random base32>`.

    per-przeh8pztb        a Person           (the code says what kind of thing; the rest is random)
    emp-zjhqxmf28v        an Employment
    doc-cbn7k1afpq        a Document         (derived from its contentHash: one file, one id)
    doc-cbn7k1afpq~p4     a Page of it       (a locator on the document's id, never an id of its own)

The id carries no name and no hash of a name, so a corrected name never moves it, and the
same entity in two collections gets two ids; hydra's merge questions join them. An id is
minted once and then frozen: nothing here recomputes one. `:` is not minted: the collection
tag in front of an id (`pollard:per-przeh8pztb`) is added by hydra at build time.

The code table is append-only: ids are stored, and decisions are keyed by them.
"""
from __future__ import annotations

import hashlib
import random
import re

ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"          # Crockford base32, lowercase: no i, l, o, u
SIZE = 10                                              # 50 bits
LOCAL = re.compile(rf"^[a-z]{{3}}-[{ALPHABET}]{{{SIZE}}}(~p[0-9]+)?$")

# Things: a refinement of the same entity shares its parent's code (Company -> PublicBody keeps the id).
KINDS = {
    "per": ["Person"], "org": ["Organization", "Company", "PublicBody"], "ent": ["LegalEntity"],
    "adr": ["Address"], "pos": ["Position"], "evt": ["Event", "Trip"], "prj": ["Project"],
    "ast": ["Asset", "RealEstate", "Security", "BankAccount"], "veh": ["Vehicle", "Airplane", "Vessel"],
    "wal": ["CryptoWallet"], "usr": ["UserAccount"], "asm": ["Assessment"], "cct": ["CourtCase"],
    "cft": ["CallForTenders"], "ctr": ["Contract"], "lic": ["License"], "nte": ["Note"],
    "doc": ["Document", "Pages", "Article", "Artifact", "Audio", "Email", "Folder", "HyperText", "Image",
            "Message", "Package", "PlainText", "Table", "Video", "Workbook"],
    "pla": ["Place"], "fea": ["Feature"],             # geo: hydra.geo.bind derives a Feature's from its shape
}
# Relationships: the schema is the fact, so one code each (a refinement shares its parent's).
LINKS = {
    "asc": ["Associate"], "cal": ["Call"], "cta": ["ContractAward"], "ccp": ["CourtCaseParty"], "dbt": ["Debt"],
    "dir": ["Directorship"], "dcm": ["Documentation"], "eca": ["EconomicActivity"], "emp": ["Employment"],
    "fam": ["Family"], "idn": ["Identification", "Passport"], "mem": ["Membership"], "mnt": ["Mention"],
    "occ": ["Occupancy"], "own": ["Ownership"], "pay": ["Payment"], "plc": ["Placement"], "pst": ["Post"],
    "prp": ["ProjectParticipant"], "rep": ["Representation"], "san": ["Sanction"], "sim": ["Similar"],
    "suc": ["Succession"], "txr": ["TaxRoll"], "unk": ["UnknownLink"],
    "sit": ["GeoLink"],
}
SUBPART = ("Page",)                                    # never an id of its own: `<document id>~p3`
ABSTRACT = ("Analyzable", "Interest", "Interval", "Thing", "Value")

CODES = {schema: code for table in (KINDS, LINKS) for code, schemas in table.items() for schema in schemas}


class MintError(ValueError):
    pass


def code_for(schema: str) -> str:
    """The three-letter code of a schema. A schema with none (a custom one) cannot be minted:
    a guessed code would not be stable."""
    if schema in CODES:
        return CODES[schema]
    why = ("is a page: its id is the document's, with `~pN`" if schema in SUBPART
           else "is abstract: no record has it" if schema in ABSTRACT
           else "has no id code: add it to mint.py (the table only ever grows)")
    raise MintError(f"schema {schema!r} {why}")


def is_minted(record_id: str) -> bool:
    """Whether an id (with or without its collection tag) has the minted form."""
    return bool(LOCAL.match(str(record_id).rsplit(":", 1)[-1]))


def _random_part(rng) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(SIZE))


def mint_id(schema: str, taken=(), rng=None) -> str:
    """A new id for a record of `schema`, none of `taken`. `rng`: anything with `.choice`
    (tests pass a seeded `random.Random`; the default is the operating system's)."""
    rng = rng or random.SystemRandom()
    code, used = code_for(schema), set(taken)
    while True:
        rid = f"{code}-{_random_part(rng)}"
        if rid not in used:
            return rid


def document_id(content_hash: str) -> str:
    """The id of a document from the hash of its file, so one file is one id wherever it is ingested."""
    n = int(hashlib.sha1(str(content_hash).strip().lower().encode()).hexdigest(), 16) >> (160 - 5 * SIZE)
    return "doc-" + "".join(ALPHABET[(n >> (5 * i)) & 31] for i in range(SIZE - 1, -1, -1))


def page_id(document: str, number: int) -> str:
    """A page of a document: a locator on its id (PDF's `#page=4` as `~p4`)."""
    return f"{document}~p{int(number)}"


def remint(records: list[dict], taken=(), rng=None, keep_old: bool = False) -> tuple[list[dict], dict[str, str]]:
    """Records under new ids -> (copies, {old id: new id}). Any property value that is an old id
    follows it (the `sources` pointing at a document). `keep_old`: the old id is kept on the
    record as FtM's `referents`, so anything still holding it can find the record. A Document
    with a contentHash takes its content id; a Page keeps its id (it needs its document's)."""
    rng, used, ids = rng or random.SystemRandom(), set(taken), {}
    for r in records:
        old, schema = str(r["id"]), r.get("schema")
        if schema in SUBPART:
            ids[old] = old
            continue
        h = ((r.get("properties") or {}).get("contentHash") or [None])[0]
        new = document_id(h) if h and code_for(schema) == "doc" else mint_id(schema, used, rng)
        if new in used:
            raise MintError(f"{old}: two documents with one contentHash ({h})")
        used.add(new)
        ids[old] = new
    out = []
    for r in records:
        props = {p: [ids.get(v, v) if isinstance(v, str) else v for v in vals]
                 for p, vals in (r.get("properties") or {}).items()}
        rec = {**r, "id": ids[str(r["id"])], "properties": props}
        if keep_old and ids[str(r["id"])] != str(r["id"]):
            rec["referents"] = sorted({*(r.get("referents") or []), str(r["id"])})
        out.append(rec)
    return out, ids
