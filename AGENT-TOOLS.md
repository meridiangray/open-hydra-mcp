# hydra-mcp: which tool, when

A short map of every tool: when to reach for it, how to call it, what to do with the result. For the rules on sources, quotes and identity, see AGENT-GUIDE.md.

**Conventions.** Every tool takes an optional `archive` (the folder; pass it every time once you have one). Tools that change things **preview first** and write only with `confirm=true`; confirm only after the person agrees. `save`, `amend_records` and `answer` each make a history snapshot.

## The pipeline

```
create_archive → rules (read, set_scope, set_positions)
   → per subject: fetch_source / read_file → find_entities → check_records → save
   → stubs → universe_build → open_questions → wiki_readiness → scope
   → read_page → wiki_serve → publish
```

## 1. Set up (once per archive)

| Tool | Use when | How |
|---|---|---|
| `create_archive` | The person wants a new archive | `path` (theirs to choose), `name`, `prefix`; preview, then `confirm`. Then pass the folder as `archive` |
| `labelling_guidelines` | First call on any archive, and before writing records | Read it all: record format, vocabularies, keys, rank ladder, what pages lack |
| `vocabularies` | Before using a `status` or `capacity` word | A word not listed is shown raw and nothing acts on it |
| `keys` | Before adding an outside id | Shows namespaces, which is `primary`, and counts. An undeclared namespace needs the person |
| `describe_schema` | Before writing a type, and to re-check a record | No `schema`: list types. With one (`"Ownership"`): its properties, required ones, and which entity kind each link takes |
| `scope` | To see what the archive is about, or why one entity is in or out | No arg: counts. `entity` (H, key, id or title): in scope and why |
| `set_scope` | The person decides what the archive covers | `seeds`, `include`, `exclude` (Hs, keys, ids, titles, `collection:<name>`). Preview lists what enters and leaves. Last resort for a single entity: record the missing relationship instead |
| `set_positions` | The archive has offices or ranks | `{name: {below, titles, outside}}`. The preview names roles no position takes; settle them before `confirm` |
| `wiki_readiness` | Now (baseline) and after each batch | Findings with examples and a `do`. Compare the whole report before and after |

## 2. Get the source

| Tool | Use when | How |
|---|---|---|
| `fetch_source` | The fact is on a web page | Keeps the page as evidence; returns its id and the URL to cite. A page that refuses stays out; do not work around it |
| `read_source` | After fetching | Rest of the text, or with `find` the sentences containing given words: those are your quotes |
| `read_file` | The source is a local file | All of it; `offset` for long files. Save with `source: {"file": ...}` |

Quote only text you read through these tools, never a summary.

## 3. Find what exists

| Tool | Use when | How |
|---|---|---|
| `find_entities` | Before naming any entity in a record | By name or key (`wikidata:Q42`). Returns H, keys, distinguishing facts. Use the exact name or id of a match |
| `explain_entity` | You need the records, collections and documents behind a value | Per value, with footnotes |
| `get_records` | After `save`, or to see what a collection holds | By collection; confirm each property and link says what the source says |

## 4. Write records

| Tool | Use when | How |
|---|---|---|
| `check_records` | Always, before `save` | Add `source` if the batch has one. Fix every error; read every warning (`keyed`, `ambiguous_links`, vocabulary, ISO) |
| `preview` | Large or uncertain batch | Builds aside, writes nothing: entities added, merges, questions raised, links left as names |
| `save` | Records are clean | `source` when the batch is from one file or text; otherwise each record cites its own `sources`. Writes, rebuilds, reports changes |
| `amend_records` | Fix a saved record | Same `id` replaces it whole (give every property to keep); new id adds; `remove` drops. Checked like `save` |
| `stubs` | After saving | Names links hold that no record has. Write the record, or leave the red link |
| `graduate_stub` | The person wants a bare entity for a name, no facts yet | `name`, optional `as_schema`; preview, then `confirm`. Not a substitute for researching it |

## 5. Identity

| Tool | Use when | How |
|---|---|---|
| `pin_upstream` | A saved record is a known entity, or has an outside id | `collection`, `record`, `h` (from `find_entities`) or a key (`wikidata:Q57340`). Preview shows what the key already belongs to. Only an id from the source or the person; verify against the id's own page first |

## 6. Build, review, check

| Tool | Use when | How |
|---|---|---|
| `universe_build` | After `save` or `amend_records` (they rebuild the archive, not the pages) | Returns counts, same-name pairs, blocked merges, warnings |
| `open_questions` | After every build | `kind` filters: `merges`, `references`, `placements`, `stale`, `contradictions`, `verdicts`. Read both sides, propose an answer, never decide it yourself |
| `answer` | The person agreed to an answer | `id` from `open_questions`, `choice`; preview, then `confirm`. `clear` takes one back. Rebuilds |
| `read_page` | For every new entry | Scope, infobox, lead, sections, footnotes resolved to record, source, quote |
| `wiki_serve` | To see the wiki, and after any change that should show | Builds stale pages, restarts, returns `ok` only when entries served equal pages in scope. Ask before `replace_other` |
| `wiki_stop` | Done with the server | Stops only one it started |

## 7. Keep it

| Tool | Use when | How |
|---|---|---|
| `publish` | Entries are final, so ids and addresses hold | `collections=[...]` for every computed H built only from them, or `hs=[...]`. Preview, then `confirm` |
| `history_log` | See what changed and who | Newest first |
| `history_diff` | Before undoing, or to review a batch | `a` (default HEAD), optional `b` |
| `history_restore` | Undo | `ref` (id or `HEAD~1`), optional `paths`; preview, then `confirm`. Run `universe_build` after |

## 8. Media

| Tool | Use when | How |
|---|---|---|
| `link_image` | One image or icon for a class of entities | `image` (full path or file in `.hydra/resources/`), `kind` (`portrait`, `thumb`, `logo`), matchers `schema` / `position` / `titled` / `name` (all must hold). Preview shows who matches |
| `link_images` | Many at once | `[{image, kind, name, schema, ...}]`; same preview rule |

## 9. Re-source away from Wikipedia

| Tool | Use when | How |
|---|---|---|
| `source_report` | To see how much rests on Wikipedia alone | Entries and the records to re-source, with their quotes |
| `wikipedia_footnotes` | One record cites Wikipedia | Its URL and quote: the references Wikipedia attaches to that sentence |
| `swap_source` | You read a better source | New source and its sentence; preview, then `confirm`. Read the returned check: the new source may say less, so blank or caveat the field |

## Not available as tools

File import (FtM/CSV/GraphML), universe member management, universe merge/reject/split/caption, Wikidata import and id search, editing rules files other than positions and scope, wiki `define`/`site`, history branching and squash, `check`, `reset`, `export`. Tell the person; do not edit files by hand.
