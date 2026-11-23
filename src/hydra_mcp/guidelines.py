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
- No `sources` when you give `save` a `source` (file, text or kept id): that evidence is added for you. A batch from several fetched pages gives no `source` and cites on each record `"sources": ["doc-..."]`. No images, no empty values.

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
- Before creating an entity, call `find_entities`. Each hit comes with what tells it apart (dates,
  nationality, posts, parents) and its canonical id `h`. If one is the same entity as yours, add
  `"upstream": ["<its h>"]` to your record, with only facts this text states: hydra treats it as that
  entity, and that is how it cites this source. A name alone is never proof, and hydra merges only on
  proof: two records with one name and no pin stay two, and review asks.
- When the text gives an id that some system assigned the entity (a Wikidata QID, an LEI, an IMO
  number, a registry or case number, the archive's own key), add it to `upstream` as `namespace:key`,
  exactly as the text writes the key: `"upstream": ["wikidata:Q57340"]`. Records holding one key are
  one entity, so only write a key the text states for this entity. Use the namespaces listed below;
  an id the text gives in an FtM property (`wikidataId`, `leiCode`) counts as that key too.
- Never put a disambiguator in a name ("Saud bin Abdulaziz (son of ...)", "Bazza #2"): write the
  name as the text does. Two people with one name are two records; their ids keep them apart, and
  the wiki tells them apart by their dates and parents.
- Pick the most specific type the text supports: Company for a business, PublicBody for a state or
  public institution, Organization when you can't tell.

## Relationships
- One relationship record per relationship the text states. Write both ends as the exact names of
  the entities (from this batch or the archive), in the right field: see the table below. `save`
  writes a name that names exactly one record as that record's id. When a name names several
  (`check_records` lists them under `ambiguous_links`, with their facts), write the id you mean.
- Each end must be the kind of entity the field expects (an `employer` is an organization, never a
  person). Never make a relationship point at itself.
- `role` is the title or function the text gives, in the text's own words ("deputy administrator",
  "VP of Operations"). Don't shorten it, translate it, or change it to match a position in the
  hierarchy. If the text gives no title, leave `role` out. Never invent one.
- Family and Associate records take `relationship`, not `role`. For Family, the word describes the
  **relative** from the **person's** side: person "Ana Reyes", relative "Marco Reyes",
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
- Countries, currencies and languages are ISO codes, whatever the text writes: `nationality`,
  `country`, `jurisdiction` or a vessel's `flag` as ISO 3166 (`sa`, `gb`; a former country as its
  ISO 3166-3 code, `suhh` for the Soviet Union), `currency` as ISO 4217 (`SAR`, `USD`, never "$" or
  "riyals"), `language` as ISO 639-3 (`ara`). The wiki names them; `check_records` flags a code ISO
  lacks. Only when the text says which country, currency or language: never guess one from a name.
- An address goes in the entity's `address`, as written. Make an Address record (its `name` and `full`
  set to the address as written, linked through `addressEntity`) only when several entities share it.

## Where things are (geo)
- Where an entity is, is never a field you add to it: no coordinates, OSM ids or shapes on a person,
  company or property. Say where it is with `site`: it writes a geometry (a Feature) and a GeoLink that
  links the entity to it, with a `role` (footprint, boundary, building, grounds, entrance, access,
  location, seat, jurisdiction, home, posting, base, route, residence, born, died, buried, event, label) and dates.
- An OSM id (`osm:way/123`) belongs to a geometry only; a Wikidata id to the entity. OSM tags are copied
  as written (`building=house`), and OSM's own `wikidata=` tag stays a tag.
- A named place the text gives (a town, a region) is a Place. Find it with `geo_resolve` (a point, or the
  name inside the entity's country) and site the entity at it with `{"register": key}`: hydra makes the
  Place with its keys and draws its real outline. A city or town is its own Place, never the region of the
  same name ("Riyadh" is the city unless the text says region or province). Only when the register lacks
  it, save a Place keyed by the id the source gives (`upstream: wikidata:Q…`).
- Prefer the finest place the text states: a building or address over a town, a town over a region, a
  region over a country. A country alone draws nothing for most entries.
- Points are [longitude, latitude]. Only places the source states or the person confirms: never place an
  entity by a name alone; when a name could be several places, ask.
- A post has one place per aspect: `home` (whose post it is), `posting` (the host country), `seat` (the
  building), `jurisdiction` (a region, then a district). `geo_aspects` shows what fills each and what the
  register offers for the empty ones; fill one aspect at a time with `site`. A new place the person points at
  is a point, never a box.
- Which place an entity is drawn by first follows geo.yaml; to change it, propose `set_primary` and use it
  only once the person agrees.

## Dates
- Only dates the text gives, as `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. "In 2019" is `2019`; don't
  expand it to a full date. A vague date stays vague: `c. 1748`, `before 1800`, `after 1900`,
  `1950s`, `1748?` (hydra stores the date and keeps the qualifier; pages show it).
- `startDate` is when a relationship began, `endDate` when it ended ("until 2010", "left in 2010").
  The start is never after the end.

## Leave to the archive's owner
- Images: never in records. They are linked in `.hydra/rules/hints.yaml`.
- The hierarchy: never change a role to fit it. When `save` warns that a role takes no position, say
  so in your summary; the owner may add it to `.hydra/rules/positions.yaml`.
- Merges, ambiguous links and placements: hydra turns them into questions (`open_questions`).
  Explain each with `explain_entity` and propose an answer; `answer` only with the person's
  agreement. Don't try to settle them by changing the data.
- A post, job or membership with a start and no end: never guess an end date into the record. `open_ends`
  lists them with candidates and their sources; `answer` one only with the person's agreement.
- The rank ladder: when many roles take no position, propose one with `set_positions` (it previews
  what it would rank) and write it only once the person agrees.
"""

WIKI = """\
## What each record makes on its page
The archive is read as a wiki, a page per entity. What you record is what the page can show:

| Record | On the page |
|---|---|
| `birthDate`, `deathDate`, `birthPlace`, `nationality` | the opening line, the infobox, the age at death, the births and deaths categories, a qualifier when two share a name |
| Family (`relationship` father / mother / ...) | parents, siblings and children, with each one's dates |
| Position + Occupancy with `startDate` / `endDate` | an "offices held" table with predecessor and successor, the post's numbered list of holders, the timeline |
| Membership, Directorship, Employment with dates and `role` | a dated table on both pages |
| Position `organization` | the post listed under its body |
| `sources` (save adds them), `sourceUrl`, `publisherUrl` | footnotes on every value, external links |
| `notes` | shown verbatim; a fact written only there reaches no section, link or category |
| `upstream` keys (`wikidata:Q57340`) | an Identifiers row, linked; the page found by searching the key and at `/k/<namespace>/<key>` |
| Ownership `percentage`, `status`; a deal (Event) in `transaction` | the Owners and Holdings tables, the deal's page, the infobox's owners |
| Representation `capacity` | "Acted for" on the agent's page and Parties on the deal's: never an owner |

A name that names no record is a red link: write the record, and the link finds it.
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


def keys_section(root: Path) -> str:
    """The key namespaces this archive declares, and which one entities are keyed by first."""
    from hydra import keys as hkeys
    conf = hkeys.load(root)
    if not conf["namespaces"] and not conf["primary"]:
        return ""
    lines = ["## Keys: ids other systems give entities", "",
             "Write them in `upstream` as `namespace:key`. A namespace not listed here still works (the "
             f"owner may declare it in `{layout.KEYS}`); check its spelling, since a misspelt one joins nothing.", ""]
    for ns, d in conf["namespaces"].items():
        bits = [f"also read from `{d['property']}`" if d.get("property") else "",
                "one per entity" if d.get("unique") else "",
                "primary" + (f" (#{conf['primary'].index(ns) + 1})" if len(conf["primary"]) > 1 else "")
                if ns in conf["primary"] else ""]
        lines.append(f"- `{ns}:` {d.get('label') or ns}" + (f" ({'; '.join(b for b in bits if b)})" if any(bits) else ""))
    if conf["primary"]:
        lines += ["", f"Entities are keyed first by {', then '.join(f'`{p}`' for p in conf['primary'])}: an entity "
                  "holding such a key keeps one canonical id however its records change."]
    return "\n".join(lines) + "\n"


def vocabulary_section(root: Path) -> str:
    """The words this archive's status and capacity fields take, and what hydra does with each."""
    from hydra import vocab
    vs = vocab.load(root)
    if not vs:
        return ""
    def acts(m):
        return [t for t in ("the record counts as over" if m.get("ended") else "",
                            "flagged wherever the fact is shown" if m.get("caveat") else "",
                            {False: "the one acting is not the one who gains", True: "the one acting gains"}
                            .get(m.get("beneficiary"), "")) if t]
    lines = ["## Words a status or capacity takes", "",
             "Write one of these only when the source supports it; leave the field out otherwise. A word not "
             f"listed is kept as typed, but nothing acts on it. The owner may add words in `{layout.VOCABULARIES}`.", ""]
    for name, v in vs.items():
        lines.append(f"**{name}** ({', '.join(f'`{a}`' for a in v['applies_to'])})")
        for word, m in v["values"].items():
            does = "; ".join(acts(m))
            lines.append(f"- `{word}`: {m.get('why') or m.get('label') or ''}" + (f" ({does})" if does else ""))
        lines.append("")
    return "\n".join(lines)


def readiness_section(root: Path) -> str:
    """What this archive's pages still lack, when its pages have been built."""
    if not (root / layout.UNIVERSE_PARSED / "pages.jsonl").is_file():
        return ""
    from hydra.wiki import readiness
    found = [f for f in readiness.check(root) if f["level"] == "warning"][:6]
    if not found:
        return ""
    return "## What this archive's pages lack now\n\n" + "\n".join(
        f"- {f['count']} {f['what']}. Do: {f['do']}" for f in found) + "\n"


def render(root: Path) -> str:
    """The full guidelines for this archive."""
    return "\n".join(x for x in [RULES, relationship_table(root), hierarchy_section(root), keys_section(root),
                                 vocabulary_section(root), WIKI, readiness_section(root)] if x)
