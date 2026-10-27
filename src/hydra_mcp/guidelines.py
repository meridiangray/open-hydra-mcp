"""The labelling guidelines the model follows before it proposes a record.

The rules are fixed; the relationship table and the position ladder are read from
the archive (its schema, direction.yaml and hierarchy), so they always match what
hydra will do with the records. Nothing here validates: it says how to write
records that hydra places correctly the first time.
"""
from __future__ import annotations

from pathlib import Path

from hydra import layout, schema

from hydra_mcp import core

# the relationships text usually states, in the order the table shows them
RELATIONSHIPS = ("Membership", "Employment", "Directorship", "Ownership", "Occupancy", "Representation",
                 "ProjectParticipant", "Family", "Associate", "Succession")

RULES = """\
# Labelling guidelines

Follow these exactly. They keep the data faithful to the file and keep hydra from building a wrong
hierarchy out of it.

## Record format
Records are FollowTheMoney JSON, a list of objects, every value a list of strings:

```json
[
  {"schema": "PublicBody", "properties": {"name": ["Port Authority"]}},
  {"schema": "Person", "properties": {"name": ["Robert J. Kerr"], "weakAlias": ["Kerr"]}},
  {"schema": "Employment", "properties": {"employee": ["Robert J. Kerr"], "employer": ["Port Authority"],
                                          "role": ["deputy"], "startDate": ["2019"]}}
]
```

- `schema` is an FtM type; `properties` only that type's fields. Leave `id` out: one is made.
- A link (a relationship's two ends, `organization`, `involved`...) is the linked entity's exact
  `name`, as written in its own record or in the archive. Never an id.
- No `sources` (the evidence is added for you), no images, no empty values.

## Only what the text states
- Record facts the text states. Never add what you know from elsewhere, and never infer a
  relationship the text doesn't state: two people in the same organization are not Associates
  unless the text says so.
- The whole text (or file) is stored and cited as the source of every entity. You don't need to add it.
  When there is a file, extract from the text `read_file` returns, all of it.
- When it helps a reviewer, put the sentence that states a relationship in that record's `notes`,
  quoted exactly.

## Entities
- One record per real-world entity. Write the `name` exactly as the text writes it, in its fullest
  form ("Robert J. Kerr", not "Kerr").
- Other full names for the same entity go in `alias`: another spelling, another script, a former or
  married name ("Robert Kerr", "Роберт Керр"). Hydra matches on these as strongly as on the name.
- Short or partial references go in `weakAlias`: a surname alone, a nickname, a code name ("Kerr",
  "Bobby"). Hydra only ever proposes a merge on these, never makes one, because many people share them.
- A job title is a `role` on a relationship (or a person's `position`), never `title`: in FtM, `title`
  is an honorific such as "Dr." or "Sir".
- If you can't tell whether two mentions are the same entity, make two records. Hydra proposes the
  merge and a person decides; a wrong merge is much harder to undo than a missed one.
- Before creating an entity, call `find_entities`. If it already exists, write its record with exactly
  its existing name and type, and only facts this text states: hydra treats it as the same entity,
  and that is how it cites this source. In relationships, use that same exact name.
- Pick the most specific type the text supports: Company for a business, PublicBody for a state or
  public institution, Organization when you can't tell.

## Relationships
- One relationship record per relationship the text states. Write both ends as the exact names of
  the entities (from this batch or the archive), in the right field: see the table below.
- Each end must be the kind of entity the field expects (an `employer` is an organization, never a
  person). Never make a relationship point at itself.
- `role` is the title or function the text gives, in the text's own words ("deputy administrator",
  "VP of Operations"). Don't shorten it, translate it, or change it to match a position in the
  hierarchy. If the text gives no title, leave `role` out. Never invent one.
- Family and Associate records take `relationship`, not `role`. For Family, the word describes the
  **relative** from the **person's** side: person "Walter White Jr.", relative "Walter White",
  relationship "father". Hydra reads the direction from that word, so get the sides right.
- Organizations inside organizations: a crew, unit or branch belonging to a larger organization is a
  Membership with a role such as "affiliate", "unit" or "branch", or with no role. Never give an
  organization a person's rank ("member", "leader", "deputy"): hydra would rank it under a person.
- A company owned by another company or a person is an Ownership (owner, asset), not a Membership.
- ProjectParticipant draws the participant under the project in the tree. Use it for people working
  on a project; for an organization, only when the text says it sits inside the project.

## Offices, events and places
- A public or named office ("Mayor of Springfield", "Minister of Finance") is a Position record, named
  as the text names the office, with `organization` set to the body it belongs to when the text says,
  plus an Occupancy (holder, post) for each person who holds it, with their dates. Hydra draws the
  holder under that organization, with the office's name as their title (it ranks them when a
  position lists it); the office itself is no box in the tree. Use Employment instead when the text
  describes a job with an employer rather than an office.
- An event the text describes (a meeting, a raid, a trial) is an Event with its `name`, `date` and
  `location` as given; the people and organizations taking part go in `involved`, whoever arranged it
  in `organizer`. Events are linked to those entities, not drawn in the hierarchy; never turn one into
  a relationship between its participants.
- An address goes in the entity's `address`, as written. Make an Address record (its `name` and `full`
  set to the address as written, linked through `addressEntity`) only when several entities share it.

## Dates
- Only dates the text gives, as `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. "In 2019" is `2019`; don't
  expand it to a full date.
- `startDate` is when a relationship began, `endDate` when it ended ("until 2010", "left in 2010").
  The start is never after the end.

## Leave to the archive's owner
- Images: never in records. They are linked in `.hydra/rules/hints.yaml`.
- The hierarchy: never change a role to fit it. When `save` warns that a role takes no position, say
  so in your summary; the owner may add it to `.hydra/rules/positions.yaml`.
- Merges, ambiguous links and placements: hydra turns them into questions for `hydra-ctl review`.
  Mention them; don't try to settle them by changing the data.
"""


def _range(sname: str, field: str) -> str:
    return (schema.resolve(sname)["props"].get(field) or {}).get("range") or "Thing"


def relationship_table(root: Path) -> str:
    """Each relationship's two fields, the kind of entity each takes, the text field
    for the title, and which end hydra draws above (from direction.yaml)."""
    d = core._yaml(root / layout.DIRECTION)
    above, lateral, dual = set(d.get("above") or ()), set(d.get("lateral") or ()), set(d.get("dual") or ())
    rows = ["| Relationship | From (kind) | To (kind) | Title field | In the tree |", "|---|---|---|---|---|"]
    for s in RELATIONSHIPS:
        if s not in schema.SCHEMA or not schema.SCHEMA[s].get("edge"):
            continue
        e = schema.SCHEMA[s]["edge"]
        src, tgt = e["source"], e["target"]
        props = schema.resolve(s)["props"]
        title = "relationship" if "relationship" in props else "role" if "role" in props else "-"
        if s == "Occupancy":            # the Position folds into its holder: no node of its own
            drawn = f"`{src}` under the {tgt}'s `organization`, with the {tgt}'s name as their title"
        elif s in lateral:
            drawn = ("side by side in the main tree; `hydra-ctl tree family` reads the word to put the "
                     "parent above the child" if s == "Family" else "side by side, never parent and child")
        else:
            up, down = (tgt, src) if tgt in above else (src, tgt) if src in above else (None, None)
            drawn = f"`{down}` under `{up}`" if up else "not drawn as a hierarchy"
            if s in dual:
                drawn += ", and a side link"
        rows.append(f"| {s} | `{src}` ({_range(s, src)}) | `{tgt}` ({_range(s, tgt)}) | `{title}` | {drawn} |")
    return "## Relationship fields\n\n" + "\n".join(rows) + "\n"


def hierarchy_section(root: Path) -> str:
    h = core.hierarchy(root)
    lines = [f"## This archive's hierarchy: {h['mode']}", "",
             "A role ranks a person inside their organization only when it equals one of these, whole "
             "(case and accents ignored). Write roles as the text does anyway: this list shows what will "
             "rank, not what to write.", ""]
    for p in h["positions"]:
        where = "outside the organization" if p["outside"] else (f"below {', '.join(p['below'])}" if p["below"] else "top")
        lines.append(f"- **{p['position']}** ({where}): {', '.join(p['titles']) or 'its name only'}")
    if h["issues"]:
        lines += ["", "The hierarchy itself has problems, so rankings may be off: " + "; ".join(h["issues"])]
    return "\n".join(lines) + "\n"


def render(root: Path) -> str:
    """The full guidelines for this archive."""
    return "\n".join([RULES, relationship_table(root), hierarchy_section(root)])
