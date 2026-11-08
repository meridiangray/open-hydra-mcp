# Agent guide: adding sourced data to a hydra archive and its wiki

For an agent (or a person) adding facts to any hydra archive through hydra-mcp, so that each fact lands on the right page, in the right section, traceable to the sentence it came from. It assumes nothing about the archive's subject: read the archive's own rules first (section 2). `labelling_guidelines` gives the record format; this guide is the workflow around it.

**Where to start.** A new archive: section 13, then the loop (3). Adding facts to an existing one: the loop. Linking an outside id, resolving same-name pairs, adding images, undoing: sections 14–17. What has no tool yet and must be left to the person: section 18.

## 1. The trip a fact makes

```
source ──► quote ──► record field ──► feature ──► view ──► check
the text   the exact  a valid value    what hydra   the page    the readiness diff,
you read   sentence   in the field     does with    section it  the page read
           in notes   that carries it  it           fills       as a reader
```

- **Source.** The text itself, kept in the archive as evidence, never a summary of it: `fetch_source` keeps a web page (records cite it by id), `read_file` reads a local file (`save` with `source: {"file": ...}` keeps it).
- **Quote.** The sentence that states the fact, copied exactly into the record's `notes`. It is printed in quotation marks and attributed to the source, so it must be the source's words.
- **Record field.** The field whose meaning the fact has (section 5), holding a valid value: a property the schema has, a word the archive's vocabulary lists, an ISO code, an exact figure, a link that resolves to the right kind of entity.
- **Feature.** What hydra does with the field: an Owners table, a deal with its price, a family tree, an Identifiers row, a category, scope.
- **View.** The page section the feature fills. A fact in a field no feature reads is stored but tells the reader nothing.
- **Check.** What the pages lack before and after; the scope of what you added; the new pages read as a reader would.

Hydra keeps the trail backwards for you: every value carries footnotes to the records that state it, each reference names its record and source, and `explain_entity` lists, per value, the records, collections and documents behind it.

## 2. Know the archive before you write

| Ask | Tool | Why |
|---|---|---|
| How records must be written here | `labelling_guidelines` | Relationship fields, the rank ladder, this archive's vocabularies and keys, what its pages lack now |
| What a type accepts | `describe_schema` | Properties, types, which link takes which kind of entity |
| The words a status or capacity takes | `vocabularies` | A word not listed is shown as typed and nothing acts on it (a former stake would count as current) |
| The id namespaces | `keys` | Which outside ids (`wikidata:`, `lei:`, the archive's own) identify entities, and which one is primary |
| What the archive is about | `scope` | Seeds and flow: what will be listed, what will be context |
| What the pages lack | `wiki_readiness` | The baseline you compare against after your batch |
| What waits for a person | `open_questions` | Same-name pairs, ambiguous links, placements: never settle them by changing data |

The archive's rules live in `.hydra/rules/` (an archive without a file uses hydra's template):

| File | What it decides | Read with |
|---|---|---|
| `vocabularies.yaml` | Status and capacity words and what each does (`ended`, `caveat`, `beneficiary`) | `vocabularies` |
| `keys.yaml` | Key namespaces, the FtM property holding the same key, `unique`, `primary` | `keys` |
| `scope.yaml` | Seeds, the relationships scope flows along, `include` / `exclude` | `scope` |
| `groups.yaml` | Which memberships make a group (a house, a party, a regiment): infobox row, category, foot box | (file) |
| `kinship.yaml` | What each Family word says: parent, child, sibling, spouse, gender | (file) |
| `standards.yaml` | Country names and nationality words over ISO's, codes ISO lacks | (file) |
| `capacity.yaml` | When an agent's office makes a client's interest theirs ("by their office") | (file) |
| `positions.yaml` | The rank ladder that places people under their organizations | `labelling_guidelines`, `set_positions` |
| `hints.yaml` | Images and badges | `link_image(s)` |

Change a rules file only with the person's agreement: `set_scope` and `set_positions` preview first; the others are files to edit and then rebuild.

## 3. The loop

1. **Pick one subject**: an entity and what the sources say about it (a company and its owners, a person and their offices, an asset and its sales).
2. **Get the source text.** A web page: `fetch_source` (Wikipedia from its raw text; other pages as their body text), which keeps it as a source and returns its id and the URL to cite; `read_source` gives the rest of the text, or with `find` the sentences containing given words, the ones you will quote. A local file: `read_file` (all of it, with `offset` for long files). A page that refuses the fetch stays out unless the person saves it for you. Never quote a browsing tool's summary (section 4).
3. **Find what exists.** `find_entities` for every entity you will name, by name or by key (`wikidata:Q42`). Each hit comes with its H, keys and distinguishing facts. Use an existing entity's exact name or id; pin your record with `upstream: [its h]` only when its facts agree (section 6).
4. **Plan each fact**: its sentence, its record and field (section 5), the view it should fill.
5. **Write the records**, each citing the kept sources it rests on (`"sources": ["doc-..."]`; on a relationship record hydra turns that into the source's URL), then `check_records` (with `source` too, if the batch has one). Fix every error: a note not word for word in the record's sources, a link to the wrong kind of entity (an estate in an Event's `involved`, an Organization as an owned asset), a source that is not kept. Read every warning: a word outside the vocabulary, a code ISO lacks, a key that already belongs to someone (`keyed`), an ambiguous link (`ambiguous_links`), a name that resolves to nothing. `preview` builds a large or uncertain batch aside first.
6. **`save`**: with `source` when the whole batch comes from one file or text; without it when each record cites its own kept sources. It writes the collection (and any new evidence), rebuilds, and reports what changed.
7. **`get_records`** with the collection: confirm each property, type and link is what the source states.
8. **`stubs`**: names your links hold that no record has. Write the record, or leave the name a red link on purpose.
9. **`universe_build`**, then **`wiki_readiness`** and compare with the baseline from section 2. Every new finding must be one you meant (an asset whose owner the source does not name; an ownership with no stated share). A red link, a raw status word, a non-ISO code or a sudden jump in any count is a mistake to fix.
10. **`scope`**: everything you researched for this archive should be in scope, with the reason you expect (`why`: "Ownership from …"). If it is not, the relationship that ties it in is missing: record it if the source gives it. `set_scope` `include` is the last resort, with the person's agreement.
11. **`read_page`** every new entry: its scope, infobox, lead, each section's text, and each footnote resolved to its record, source and quote. Then **`wiki_serve`**: it builds stale pages, restarts the wiki, and returns `ok` only when the entries it serves equal the pages in scope (section 8).
12. **`publish`** (preview, then `confirm`) the entries you are keeping, so their ids and addresses hold: `collections=[<your collection>]` takes every computed H built only from it.

Fix a saved record with `amend_records` (same id). Every write is a history snapshot: `history_log`, `history_diff`, `history_restore` undo.

## 4. Sources and quotes

- **The text itself.** A browsing tool's page "summary" is a model's paraphrase: its quotes may not be the source's words. Quote only what you have read in the text.
- **A search snippet is a lead.** Open the page. A page you cannot fetch is a fact you cannot use; never imitate a browser to get past a block, and never put personal data in a request.
- **Read to the end.** The unread part can contradict what you wrote.
- **Rank sources** and cite the best you read: registries and filings; major outlets and trade press; encyclopedias (check their dates and figures against what they cite); aggregators only as leads.
- **The source's confidence is data.** "Reported", "alleged", "according to" → the vocabulary's caveat word (`reported` by default); the sentence naming the outlet goes in `notes`.
- **Two sources disagree:** quote both; one record per source when each gives a different value. Never pick one, never average, never put the disagreement in a lead as commentary; the disputed field stays at what both agree on, or blank.
- **Numbers as given.** "About 15 percent", "an estimated $3m", an asking price or a valuation never go in `percentage` or `amount`: quote them in `notes`.
- **No inference.** No computed stakes, filled-in dates, assumed nationalities, or a named thing made from a description ("his yacht").

## 5. From fact to view

| To show on a page | Record it as | Where it shows | Valid values |
|---|---|---|---|
| What the thing is | `description` | The lead paragraph | One or two plain sentences: what it is, its maker, year, size, role. No sourcing talk, caveats or conflicts |
| The source's words | `notes` | In quotation marks under References; "As recorded" | Verbatim sentences only |
| Who owns it | `Ownership` `owner` → `asset` | Owners on the asset, Holdings on the owner, the infobox's owners, the chain of ownership once two owners have dates | `asset` an Asset type (Company, RealEstate, Vessel, Airplane, Asset), not an Organization or Person |
| The share and period | `percentage`, `startDate`, `endDate` | Share bar and sum; "1992–2021", "since 1994", "until 2007" | Exact figures; dates as given, qualifiers kept (`c. 1748`, `before 1800`, `1950s`, EDTF `1748~`) |
| How sure the source is | `status` | A badge; caveat words also in the infobox; ended words make the record former | Only a `vocabularies` word |
| A deal | `Event` (`name`, `date`, `amount`, `currency`, `description`, `involved`) and its id in `transaction` on each Ownership / Representation of the deal | Deals table with the price on every page the deal's records touch; the deal page: price, parties, who acted for whom, ownership in this deal | `involved` / `organizer` take legal entities only; an asset reaches its deal through its ownership. `amount` a price paid; `currency` ISO 4217. A holding bought in one deal and sold in another names both |
| Someone acting for someone | `Representation` `agent` → `client`, `capacity`, `role` | "Who acted for whom"; "Acted for" on the agent; "by their office" from the agent's post in the client | `capacity` a vocabulary word; never an Ownership |
| Who runs an organization | `Directorship`, `Employment` | Directors, employment tables on both pages | `role` in the source's words |
| An office | `Position` (with `organization`) + `Occupancy` `holder` → `post`, dates | Offices held, numbered holders, succession boxes, time in office; the body's posts | One Position per named office |
| Membership, a unit, a group | `Membership` `member` → `organization`, `role` | Membership tables; with a groups.yaml rule: an infobox row, a category, a foot box | Organizations inside organizations take roles like `unit`, never a person's rank |
| Family | `Family` `person` → `relative`, `relationship` | Parents, siblings, children, ancestors, "son of …" | The word describes the relative from the person's side, and must be a kinship.yaml word to be read |
| Ids from elsewhere | `upstream: ["<namespace>:<key>"]` or the property keys.yaml maps (`wikidataId`, `leiCode`, `imoNumber`) | Identifiers row, linked; `/k/<namespace>/<key>`; search by key | Only an id the source gives for this exact entity: records holding one key are merged |
| Country, nationality, language | `country`, `nationality`, `jurisdiction`, `flag`, `language` | Names in the infobox; the nationality word in the lead | ISO 3166 lower case (`gb`), 639-3 (`eng`) |
| A person's life | `birthDate`, `deathDate`, `birthPlace`, `gender` | Lead, lifespan, age, categories, year pages | As stated |

`summary` is rendered nowhere: an Event's text goes in `description`. A field not in this table may still be stored; check the page before relying on it.

## 6. Identity

- One record per real-world entity, named as the source names it, in full; other full names in `alias`, short or partial ones in `weakAlias`.
- An entity has a proper name or an identifier. Do not mint one from a description ("the company's jet"), a group the source does not name ("the investor consortium"), or a surname alone.
- A name is never proof. Two records with one name stay two until someone decides (`open_questions` → `answer` with the person's agreement). Proof is an identifier, a key, or an `upstream` pin to an H whose facts agree with your source.
- **Keys** (`keys`): write the namespace and key exactly as the source gives it. A key that `check_records` says already belongs to an entity will merge your record into it; if that is wrong, the key is wrong.
- Ids are permanent: a renamed id is a new H and a new address. Correct a record by keeping its id.

## 7. Scope

If the archive's `scope.yaml` has seeds, only what scope reaches is listed: from the seeds along family, membership, offices (and a post's body), what in-scope owners own, the boards and jobs of in-scope people, and the deals in-scope entities take part in. Everything else is context: kept, named as plain text where in-scope pages mention it, listed nowhere, not counted by `wiki_readiness`. No seeds: everything is in scope.

Record a source's other parties (sellers, buyers, co-investors) anyway: scope puts them in context on its own. An entity you researched for the archive that comes out as context is missing the relationship that ties it in.

## 8. Read what you made

`wiki_serve` returning `ok` proves the server shows this build, not that the pages are right. Read each new page (`read_page`, or in the browser) as a stranger would:

- Does the lead say plainly what the thing is?
- Is every planned fact in the section the map in section 5 names (the owner in Owners, the price in Deals, the key in Identifiers)?
- Do the References quote the source's own words?
- Does anything read like commentary, a placeholder, or a guess?

A sentence that would embarrass you in an encyclopedia goes back to step 5 of the loop.

## 9. Re-sourcing: lowering the W-factor

Wikipedia is a lead, not the evidence. The W-factor is the share of an archive's sourced citations that rest on Wikipedia alone (`source_report` gives it, for the archive and each collection; the wiki's Sources page shows each collection's records as Wikipedia only, other or no source; each entry's References end with its citations by origin).

1. `source_report`: the entries that rest most on Wikipedia, each with the records to re-source and the quote each took.
2. `wikipedia_footnotes` with the record's Wikipedia URL and its quote: the references Wikipedia attaches to that sentence. No reference: look for a primary or news source yourself.
3. `fetch_source` each reference; `read_source` with `find` for the fact in that source's own words.
4. `swap_source` (preview, then `confirm`) with the new source and its sentence. Wikipedia's URL and its quotes leave the record; other notes stay.
5. Read the `check` it returns: the original source is often vaguer than Wikipedia ("in the 1990s for about £8m" where Wikipedia says "In 1992 ... for £8 million"; "more than £120m"). Then the record's fields must say less: a blank date or amount, a caveat status, `amend_records`. Never keep a figure only Wikipedia gives under a source that does not.

## 10. Mistakes this workflow has already caught

| Mistake | What it did | Rule |
|---|---|---|
| A server restart that missed a second server | A stale wiki looked current | `wiki_serve`; trust `ok` only with the counts |
| Placeholder entities from a type list ("a 747 and a Hawker") | Pages with no identity | Section 6 |
| Sourcing commentary in `description` | Unreadable leads | Section 5 |
| Agent's words in `notes` | Printed as the source's quote | Section 1 |
| Approximate figures and asking prices in exact fields | False precision | Section 4 |
| Status words outside the vocabulary | Raw tokens; former stakes counted as current | Section 2 |
| Event text in `summary` | Deal pages with no text | Section 5 |
| Assets in an Event's `involved` | Red-link stubs instead of links | Section 5; `check_records` refuses it |
| Quotes taken from a browsing tool's summary | Words the source never wrote | `fetch_source`; `check_records` refuses a note not in the sources |
| One deal per holding when there were two | A sale missing from the asset's page | Section 5 |
| A stake's history as several current records | Shares summing past 100% | Earlier figures get an ended status when the source says the stake changed |
| Only warnings read from the readiness report | Growth in other findings went unnoticed | Compare all of it (step 9) |

## 11. Stop and ask the person when

- A fact rests on one source that is itself unsourced, anonymous, or an aggregator.
- You would make a legal claim (fraud, sanctions, coercion, hidden ownership).
- A merge, a split, or a scope or rules change would affect entries others' data points at.
- The build reports errors, or the archive is not where it was.

## 13. Starting an archive

The person chooses the folder; you never pick one, and you never reuse an archive lying around for a trial.

1. **`create_archive`** with the full path, a `name`, and a `prefix` (the id prefix every collection uses; `"none"` gives each collection its own). Preview, then `confirm` with the person's agreement. Pass the folder as `archive` in every later call.
2. **Read the template rules** (section 2: `vocabularies`, `keys`, `scope`, `labelling_guidelines`). They are hydra's defaults, not this subject's. Propose changes to the person; do not write them unasked.
3. **Scope.** With the person, choose the seed collections (`set_scope` `seeds`): scope flows from them (section 7). An archive with no seeds lists everything. Preview, then `confirm`.
4. **Positions.** If the archive has offices or ranks, `set_positions` writes the ladder: `{name: {below: [the positions above it], titles: [role words that mean it], outside: false}}`. The preview says which of the archive's roles no position takes; settle those before confirming. Without it, people are not placed under their organizations.
5. **First collection.** Run the loop (section 3) on one small subject first, through `universe_build` and `read_page`, before adding more.
6. **Check the universe exists.** `wiki_readiness` and `universe_build` refuse an archive with no universe layer; if they do, tell the person: adding it is `hydra-ctl universe init`, which has no tool.

## 14. Identity: keys, canon links, pins, ids

An entity's canonical id (its H) is computed from its primary key (`keys`) and is a draft until published (step 12 of the loop); published, the id and page address hold (section 6).

**Outside ids (Wikidata, LEI, IMO, the archive's own):**
1. Take an id only from what you read: the source gives it, the source's own page links it, or the person supplies it. There is no search tool: never guess a Q-number from a name, and never take the first search hit.
2. `keys` shows which namespaces are declared and which is primary. An undeclared namespace is a rules change (section 2): ask.
3. Put the id on the record as `upstream: ["wikidata:Q57340"]` or in the property `keys.yaml` maps (`wikidataId`, `leiCode`, `imoNumber`). `check_records` says if the key already belongs to another entity; a key held by two records merges them, so a wrong key is a wrong merge.
4. For an already-saved record: **`pin_upstream`** (`collection`, `record`, and `h` from `find_entities`, or a key such as `wikidata:Q57340`). Preview shows the entity the key already belongs to; `confirm` with the person's agreement.
5. Verify before pinning: fetch the id's own page with `fetch_source` and check that its name, dates and type agree with your source. A disagreement means stop and ask.

**Bare names the links hold (`stubs`):** write a real record when a source gives the entity's facts. `graduate_stub` makes a bare entity from a name only when the person wants the link to resolve with no facts yet (preview, then `confirm`); never use it to hide a red link you have not researched.

## 15. Reviews: what waits for a person

`open_questions` lists what the last build asks a person to decide: `merges`, `references`, `placements`, `stale` decisions, `contradictions`, problems with `verdicts`. Fetch it after every `universe_build`.

1. For each question, read both sides (`explain_entity`, `read_page`), then **propose** an answer with your reasons. A shared name is never a reason (section 6).
2. `answer` (preview first) only with the person's agreement for that question. `clear` takes an answer back.
3. After answers, `universe_build` again: the pairs a decision blocked, and new questions, show in its result.

`open_questions` and `answer` work on the archive's own review file. Same-name pairs the universe proposes across members, and universe merge, reject, split and caption, are not reachable by tool yet (section 18): report them to the person, do not edit files to settle them.

## 16. Media and icons

Records never carry images; a rule in `hints.yaml` gives them to the entities it matches.

1. Use only images the person supplied or that the archive already holds in `.hydra/resources/`, with a licence that allows it. Do not scrape.
2. **`link_image`** (one image) or **`link_images`** (many: `[{image, kind, name, schema, ...}]`). `image` is a full local path or a file already in resources. `kind` is `portrait`, `thumb` (an icon) or `logo`.
3. Say which entities with `schema` (a type and its subtypes), `position`, `titled` (a regular expression on the title) and/or `name`; all must hold. A broad rule (a schema alone) gives one image to every entity of that type: preview shows who matches; read it.
4. Preview, then `confirm` with the person's approval. Then `wiki_serve` and look at a page that should show it and one that should not.

## 17. From archive to the served wiki, and undoing

The order that gets a batch to a correct wiki: `check_records` → `save` → `stubs` → `universe_build` → `open_questions` → `wiki_readiness` against the baseline → `scope` → `read_page` → `wiki_serve` (`ok` only when served entries equal the pages in scope) → `publish`.

- `save`, `answer` and `amend_records` each make a history snapshot (`history_log`). Undo one with `history_diff` to see it, then `history_restore` (`ref` an id or `HEAD~1`; optional `paths`; preview, then `confirm`). A restore is itself a snapshot, so nothing is lost. Rebuild afterwards (`universe_build`).
- `wiki_serve` refuses a port another server holds: ask before `replace_other`. `wiki_stop` stops only a server it started.
- A static export of the wiki is not available by tool (section 18).

## 18. No tool yet: leave these to the person

Say plainly that the step needs the person or `hydra-ctl`; do not approximate by hand-editing files.

| Needed | Why you cannot |
|---|---|
| Importing existing FtM, CSV or GraphML files | Only hand-written records through `save` |
| Universe members (add or remove), `universe link/refresh`, universe merge, reject, split, caption | Not registered |
| Wikidata import, unread-property review, property mapping | Not registered; no id search |
| Rules files other than positions and scope (`keys`, `vocabularies`, `kinship`, `standards`, `capacity`, `groups`, `wiki.yaml`) | Read-only or no tool |
| Wiki `define`, edges, sections, badges, theme, about; `wiki site` export | Not registered |
| History branch, switch, merge, tag, describe, squash, relabel | Only log, diff, restore |
| `check` (lint), `reset`, `export`, `pack` | Not registered |

## 19. Checklist

- [ ] The archive's rules read (section 2); the readiness baseline kept.
- [ ] Every source read as text, to the end; every quote verbatim.
- [ ] Every entity looked up first; existing ones linked by exact name or id; keys only as the source gives them.
- [ ] `check_records` clean; every warning read.
- [ ] `stubs` explained; the readiness diff explained line by line.
- [ ] Researched entities in scope with the expected reason.
- [ ] `wiki_serve` `ok`; every new page read; every planned fact found in its view.
- [ ] The entries published.
- [ ] Outside ids only as sources gave them, verified against the id's own page (section 14).
- [ ] `open_questions` read after the build; nothing answered without the person (section 15).
- [ ] Images linked only from supplied files, previews read (section 16).
- [ ] Anything in section 18 reported to the person, not improvised.
