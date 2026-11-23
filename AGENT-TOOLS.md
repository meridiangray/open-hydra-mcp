# hydra-mcp: which tool, when

A map of every tool: when to reach for it and how. The agent reads the guide through `guide("start")` and `guide("tools")`; this file is the same map for people. The rules on sources, quotes and identity are in `guide("rules")`.

**Conventions.**

- Every tool takes an optional `archive` (the folder); pass it on every call.
- Every write tool previews until `confirm=true`, makes one history step, adds a line to the checked-out task's log, and answers a failure as `{error, why, do}`.
- Confirm only after the person agrees, or when the task's `authorized` names the tool. Tools that are always the person's: package and context installs, `wikidata_purge`, `enrichment_delete`, merges and splits (`answer` on merges), `set_scope`, `publish`, `collection_merge`, `history_restore`.


## Toolsets

A client may load only some tools. Every tool is in one set; `core` is always on. The server starts with `core` (or the sets named by `hydra-mcp --toolsets core,geo` or env `HYDRA_MCP_TOOLSETS`; `all` is everything). If a tool you need is missing, call `toolsets()` to list the sets, then `toolset_enable("<set>")`: the client is told the tool list changed. `task_checkout` switches on the sets its task's route needs and says so in `toolsets_enabled`.

- **`core`**: Always on: guide, tasks, records, sources, schema, recipes. `guide`, `workflows`, `details`, `tasks`, `task`, `task_new`, `task_checkout`, `task_step`, `task_add`, `task_verify`, `task_release`, `task_close`, `contexts`, `context_checkout`, `create_archive`, `describe_schema`, `properties`, `check`, `check_records`, `save`, `preview`, `get_records`, `amend_records`, `find_entities`, `explain_entity`, `read_file`, `source_profile`, `source_outline`, `source_names`, `read_source`, `sources`, `cite`, `labelling_guidelines`, `vocabularies`, `keys`, `collections`, `collection_create`, `recipe`, `paths`, `toolsets`, `toolset_enable`, `extra_fields`, `field_assign`.
- **`enrich`**: Sources fetched and swapped, suggestions, images, stubs, open questions. `fetch_source`, `drop_source`, `swap_source`, `source_report`, `wikipedia_footnotes`, `read_page`, `probe`, `suggestions`, `apply_suggestion`, `dismiss_suggestion`, `suggestions_reset`, `enrichers`, `enrichments`, `enrichment_delete`, `enrichment_hide`, `wikidata_purge`, `link_image`, `link_images`, `stubs`, `graduate_stub`, `pin_upstream`, `open_questions`, `answer`, `decisions`, `open_ends`, `neighbors`, `cast`.
- **`wikidata`**: Link entries to Wikidata as questions for the person; a confirmed match brings its picture. `wikidata_questions`, `wikidata_answer`, `wikidata_status`.
- **`geo`**: Places, features, GeoLinks, layers. `geo_aspects`, `geo_contexts`, `geo_enable`, `geo_locate`, `geo_measure`, `geo_query`, `geo_register_status`, `geo_report`, `geo_resolve`, `geo_summarize`, `draw_feature`, `move_feature`, `delete_feature`, `transform_geometry`, `edit_geolink`, `edit_siting`, `layer_add`, `layer_list`, `layer_remove`, `set_primary`.
- **`shape`**: Labels, collections, views, article sections, the wiki. `label`, `tags`, `badges`, `positions`, `set_positions`, `tree`, `set_collection`, `set_collection_views`, `set_collection_group`, `collection_merge`, `collection_rename`, `collection_delete`, `move_records`, `view_check`, `view_config`, `symbology`, `set_symbology`, `article_sections`, `set_article_section`, `remove_article_section`, `move_article_section`, `site`, `wiki_serve`, `wiki_stop`, `publish`, `wiki_readiness`.
- **`admin`**: Settings, scope, packages, export, history, build. `archive_settings`, `scope`, `set_scope`, `packages`, `package_install`, `pack`, `upgrade`, `export`, `history_log`, `history_diff`, `history_restore`, `universe_build`, `save_changes`.

## The pipeline

```
guide("start") → tasks → task_new → task_checkout
   → per subject: sources / fetch_source / read_file → find_entities → check_records → save
   → stubs → universe_build → open_questions → wiki_readiness
   → suggestions → probe → apply_suggestion          (Enrich)
   → label                                           (parents, places, posts, tags)
   → geo_report → geo_aspects → site / draw_feature  (places)
   → view_check → read_page → wiki_serve → publish
   → task_verify → task_close
```

## 1. Orient

| Tool | Use when | How |
|---|---|---|
| `guide` | Start of a session; any rule or field name | No topic: the list and the hydra version. `guide("start")` first. Topics `workflow/<name>` and `views/<name>` too |
| `workflows` | Choosing a workflow | The built-in ones and the archive's own |
| `create_archive` | The person wants a new archive | `path`, `name`, `prefix`; preview, then `confirm`. Then pass the folder as `archive` |
| `details` | An unfamiliar archive | Records, types, collections, tree roots, open questions in one call |
| `check` | Structural problems | Rules files, records and sources, by level; builds nothing |
| `labelling_guidelines` | First call on an archive, and before writing records | Record format, vocabularies, keys, rank ladder |
| `describe_schema` | Before writing a type | No `schema`: the types. With one: its properties and what each link takes |
| `properties` | Which fields a type takes, and a Wikidata code for one | `schema` (`level` common or all, `theme`): the fields by theme with codes and the links the type takes. `query`: fields of every schema, and Wikidata matches. `code`: one property |
| `extra_fields` | After a save that found fields outside FtM | Each kept field, its records, its code, the closest Wikidata properties |
| `vocabularies` | Before a `status` or `capacity` word | A word not listed is shown raw |
| `keys` | Before an outside id | Namespaces, which is primary, counts |
| `scope` | What the archive is about | No argument: counts. `entity`: in scope or out, and why |
| `collections` | The collections | Id, title, record count, views and their handles |
| `view_config` | What each view starts with | Hidden types, map settings, panel buttons |
| `archive_settings` | Read or change name, title, sub, about, description, theme, view, rail shape, title style | `set` (only what changes) and `confirm`; the preview shows from/to |

## 2. Tasks

| Tool | Use when | How |
|---|---|---|
| `tasks` | Before any work | Each task's `holder`, `idle`, `stale`; `current_task` is yours; `offset`, `limit` |
| `contexts` | Choosing what a task keeps and drops | `task` ranks them for it, or `words`; without, the list with `use_when`. Read one with `guide("context/<name>")` |
| `task_new` | Starting tracked work | `title`, `workflow` (a list is a route), `context`, `collection`, `views`, `subjects`, `authorized`; preview, then `confirm` |
| `task_checkout` | Claiming a task | `id`; says why it refused; takes a lock idle past `tasks.stale_after` (2 h); `force` with `reason` only for your own earlier lock; `model`, `client`; returns `brief`, or `needs_context` |
| `context_checkout` | A task has no context | `id`, `name`, `reason`; preview, then `confirm`; fixed after the first write |
| `task` | Reading the steps, sources, claims, log | `id` defaults to yours |
| `task_step` | Right after each step | `step`, `status`, `result` or `reason`, `claim` + `evidence`, `exit` |
| `task_add` | Another subject or step | `subject`, or `code` and `step` |
| `task_verify` | Before closing | Open steps, uncited sources, view checks |
| `task_release` | Stopping early | Hands the task back with its steps and log |
| `task_close` | Finishing | Runs `task_verify` first |
| `save_changes` | End of a task | Names the work as one change in history |

## 3. Sources

| Tool | Use when | How |
|---|---|---|
| `sources` | Which sources are kept | `query`, `uncited_only`; each with its id, URL or file, citations |
| `fetch_source` | The fact is on a web page | Keeps it; describe it with `title`, `author`, `publisher`, `published`, `summary`. A refusing page stays out; a thin page (front page, menus) is not kept without `keep=true` |
| `drop_source` | A page was kept by mistake | Removes a kept source no record cites; one that is cited is refused, with the records listed |
| `read_source` | After fetching, or from `sources` | The text in parts; `find` returns the sentences holding your words: your quotes |
| `read_file` | The source is a local file | A short file whole. A long one: first its profile and parts (no text), then `part=n` one at a time |
| `source_profile` | Before reading a long file, or at Gate 1 | Pages, OCR noise, redactions, headings, front and back matter, parts, warnings; kept by content |
| `source_outline` | Planning the parts of a document | Headings with level, offset and page: PDF bookmarks (not scan batches), Word styles, Markdown/HTML headings, else heading lines; contents pages left out |
| `source_names` | Checking a part's coverage | Capitalised names in pages `from_page`..`to_page` with counts and the entries already carrying each; never a list to record |
| `recipe` | A long document or an archive needs a quick pass | By `name` with `args`; no name lists them. intake, outline (parts with pages), names (to look up), findquote (pages for `cite`), table and tsv2records (a PDF table to records for `check_records`), audit (fix lists). Reads only; leads, not quotes |
| `source_report` | How much rests on Wikipedia alone | Entries and the records to re-source |
| `wikipedia_footnotes` | One record cites Wikipedia | What Wikipedia cites for that sentence |
| `swap_source` | You read a better source | The record, the new source, its sentence; read the returned check |
| `cite` | You know where in a kept source a fact is | `[{record, source, pages, pdfPages, locator, quote}]`: `pages` as printed on the document, `pdfPages` the page of the PDF file; a quote is checked verbatim and gives the PDF page (and the printed one when readable) |
| `article_sections`, `set_article_section` | An entry's prose | Read first; then add or replace one section |
| `remove_article_section`, `move_article_section` | Tidy an article | By heading; `to` is a position, 1 first; preview, then `confirm` |

Quote only text you read through these tools.

## 4. Records

| Tool | Use when | How |
|---|---|---|
| `find_entities` | Before naming any entity | By name or key; each hit has its H, keys and telling facts |
| `explain_entity` | Where a value came from | Records, collections, documents per value |
| `get_records` | After `save` | By collection; compare each property with the source |
| `check_records` | Always before `save` | Fix every error; read every warning. A field FtM lacks is a warning (`extra field`): kept, never dropped |
| `preview` | A big or uncertain batch | Builds aside: what it adds, merges, asks |
| `save` | Records are clean | `source` for one file or text, else each record cites its `sources` |
| `amend_records` | Fixing a saved record | Same `id` replaces it whole; `remove` drops |
| `field_assign` | A field outside FtM should become a real one | `field`, `schema`, `to`: `Schema.prop`, `new:<name>` with `wd` (P…), or `drop`; preview, then `confirm` |
| `stubs` | After saving | Names links hold that no record has |
| `graduate_stub` | The person wants a bare entity for a name | `name`, `as_schema`; preview, then `confirm` |
| `pin_upstream` | A record is a known entity | `collection`, `record`, `h` or a key; check the id's own page first |
| `collection_create`, `collection_rename`, `collection_merge`, `collection_delete`, `move_records` | Shaping collections | `name`, `title`; `old`, `new`; `into`, `from_`; `name` (an empty one only); `ids`, `to`. Previewed; a merge is always the person's |
| `set_collection_group` | Collections that open together in a view | `group`, `collections`, `title`; previewed |

## 5. Build and review

| Tool | Use when | How |
|---|---|---|
| `universe_build` | After `save` or `amend_records` | Counts, same-name pairs, blocked merges, warnings |
| `open_questions` | After every build | `kind`: merges, references, placements, stale, contradictions, verdicts. Propose; never decide |
| `answer` | The person agreed | `id`, `choice`; preview, then `confirm` |
| `decisions` | What was decided, or undoing one | Each answer with its question |
| `wiki_readiness` | Baseline, and after each batch | Findings with examples and a `do` |
| `tree`, `positions`, `badges` | The placement tree, rank ladder, badge rules | Reads; `unplaced_titles` and unmatched post titles |
| `open_ends` | A post, job or membership with a start and no end | A list to settle |
| `read_page` | Every new entry | The page as a reader sees it, footnotes resolved |
| `wiki_serve`, `wiki_stop` | Seeing the wiki | `ok` only when entries served equal pages in scope; ask before `replace_other` |
| `publish` | Entries are final | `collections` or `hs`; preview, then `confirm`; the person's |
| `neighbors`, `paths`, `tags` | Who is near; how two connect; which tags fit and why | `neighbors(entity, depth, edges, as_of)` (at most 200 entries); `paths(a, b, max_hops, edges)` (at most 20 chains); `tags(entity)`. Reads |

## 6. Enrich

| Tool | Use when | How |
|---|---|---|
| `suggestions` | What could be done for an entry | Local data only; each has `id`, `tip`, `preview`, and the tool that writes it |
| `cast` | One value, cast to a typed entity | Candidates with their source |
| `enrichers` | Which outside sources exist | Id, label, what the entry needs |
| `probe` | Ask one outside source once | Match, Compare, Lead, Portrait; writes no records |
| `apply_suggestion` | Write one suggestion | `picks`: `{"candidate": n}` or `{"rows": [...]}`; preview, then `confirm` |
| `dismiss_suggestion` | A suggestion is not wanted | Not offered again |
| `enrichments` | What Enrich added | The ledger: id, source, time, what it wrote |
| `enrichment_hide`, `enrichment_delete` | Keep it off the page; remove it | By the id from `enrichments`; delete is the person's |
| `suggestions_reset`, `wikidata_purge` | Start an entry over | The person's; undo with `history_restore` |
| `wikidata_questions` | Link the archive to Wikidata | Entries with no key, what the archive says, Wikidata's candidates; put them to the person |
| `wikidata_answer` | The person picked a candidate, or none | Pins the key, then imports the item's picture with its licence; `none` stops asking; preview, then `confirm` |
| `wikidata_status` | How far linking has got | Matched, answered none, open |

## 7. Label

| Tool | Use when | How |
|---|---|---|
| `label` | A parent, place, post or tag for entries | `entities`, `tokens`, `source` for a fact; every label must be ok; preview, then `confirm` |

## 8. Places

Where an entity is, is a GeoLink to a Place or a drawn Feature, with a role and dates; never a field on the entity. Points are `[longitude, latitude]`.

| Tool | Use when | How |
|---|---|---|
| `geo_report` | Before placing, and after | Coverage per type; `include_entities` lists the unplaced and the place references |
| `geo_aspects` | One entry's places | One per aspect (seat, jurisdiction, born...), filled, derived or empty with candidates |
| `geo_resolve` | Which place holds a point, or a name means | `point`, `entity`, or `name` with `scope`; at most three candidates |
| `site` | A source says where an entity is | `[{entity, location, role, ...}]` with `{"register": key}`, `{"point": ...}`; preview, then `confirm` |
| `geo_locate` | Where one entity is | Primary place, geolinks, reach; `as_of` |
| `geo_query` | What is within, near or holding | One of `within`, `near`, `containing`; `within` also takes an ad-hoc shape `{"geometry": GeoJSON}`; `limit`, `offset` |
| `geo_measure` | Distance, or an area | Entities, points or GeoJSON |
| `set_primary`, `edit_geolink` | Another main place; a wrong role, dates, removal | Previewed; `edit_siting` is the old name of `edit_geolink` |
| `transform_geometry` | A shape too detailed, or a point, box or circle | `simplify`, `to_point`, `to_bbox`, `circle`, `fix` |
| `draw_feature` | A source gives a shape | `archetype` or `kind`; `entity` or `new`; GeoJSON `geometry` |
| `move_feature`, `delete_feature` | A drawn place is wrong | `entity` or `feature`, then `geometry` or `delta_m` [east, north in metres]. An entry's own drawn shape is redrawn in place; a source's point or shape gets a copy of its own and the geo link record is not kept. `delete_feature(feature)` removes a drawn shape and its geolinks. Previewed |
| `geo_contexts`, `geo_summarize`, `geo_register_status` | Reference layers; counts by country, region or context; what the register holds | Reads |
| `layer_list`, `layer_add`, `layer_remove` | Map layers: GeoJSON on the Atlas that is not entities | `layer_add`: a file's full path, `name`, `attribution`, `licence`; preview, then `confirm` |
| `geo_enable` | `site` says there are no geo types | Installs Place, Feature, GeoLink; previewed |

## 9. Views and settings

| Tool | Use when | How |
|---|---|---|
| `set_collection_views` (alias `set_collection`) | Naming a collection and its views | `title`, and view handles; preview, then `confirm` |
| `view_check` | Whether a view has what it needs | Findings with `code`, `count`, examples, `do` |
| `set_scope` | The person decides what the archive covers | Previewed; last resort for one entity |
| `set_positions` | The archive has offices or ranks | `{name: {below, titles, outside}}` |
| `symbology`, `set_symbology` | How the wiki draws things | `kind`, `key`, `value`; previewed |
| `link_image`, `link_images` | Images and icons the person gave | `kind` (portrait, logo, thumb); `entity` for one entry's picture, else matchers; `credit` `{author, licence, url, licence_url?}` for a portrait |
| `export`, `pack` | The archive in another format; one file to hand on | `export(format, out, folder)`, `pack(out, folder)`: `folder` is the one the person named, `out` stays inside it; `replace` to overwrite. Previewed |

## 10. Packages and undo

| Tool | Use when | How |
|---|---|---|
| `packages` | What is locked, stored, available | Per archive |
| `package_install` | The person wants a package | `owner/name`; preview shows licence and what it replaces; the person's |
| `history_log`, `history_diff` | What changed, and who | Newest first |
| `history_restore` | Undo | `ref`, `paths`; preview, then `confirm`; then `universe_build`. The person's |
| `upgrade` | An older format, or records under an old schema name | Preview lists the changes; `confirm` makes them in one step and rebuilds |

## Not available as tools

File import (FtM, CSV, GraphML), universe member management, universe merges, splits and captions, editing rules files other than scope, positions and collection views, wiki `define`, history branches and squash, `reset`. Tell the person; `guide("limits")` has the commands. Do not edit files by hand.
