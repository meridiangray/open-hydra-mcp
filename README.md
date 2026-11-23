# open-hydra-mcp

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/meridiangray)

An MCP server that lets an AI assistant add facts it finds in raw text to a [hydra](https://github.com/meridiangray/open-hydra) archive: an article, a court filing, a press release, notes from an interview. The assistant reads the text and proposes FollowTheMoney records. The server tells it what the archive accepts, checks its proposal, and only then writes it, with the text stored as the source every entity cites.

It doesn't guess. Anything uncertain is left for a person: a name that might be someone already in the archive becomes a merge question in `hydra-ctl review`, a link to someone the archive doesn't know stays a name, and a role the hierarchy doesn't rank is reported, not rewritten.

## What an ingestion writes

Each call to `save` adds one new collection and nothing else:

```
collections/<collection>.json                 the records
.hydra/sources/entries/<collection>.json      the raw text, as one Document (an Article when it has a URL)
.hydra/sources/files/<collection>/<file>      the original file, when the source is one
```

Every entity (person, organization, company…) cites that document in `sources`, so `hydra-ctl claims` and `hydra-ctl sources` trace each value back to the text. Relationships have no `sources` field in FtM: they trace back through their collection, which holds that one source only.

The archive is rebuilt after writing, and the result reports the new review questions. A batch with errors is never written, an existing collection is never overwritten unless asked, and a build that fails puts the files back as they were. To undo a save, use `history_log` and `history_diff` to find it, then `history_restore` (previewed first); then run `universe_build`.

## Tools

<!-- tools:start -->
| Tool | Set | Arguments | What it does |
|---|---|---|---|
| `amend_records` | core | `collection`, `records`, `remove`, `confirm`, `details`, `archive` | Correct a saved collection: each record with an `id` already in it replaces that record whole (give every property it should keep; its evidence stays cited); a record with a new or no id is added; `remove` drops records by id. |
| `answer` | enrich | `id`, `choice`, `confirm`, `archive`, `quote`, `source` | Answer one open question (`id` from `open_questions`): `confirm` or `reject` a merge or placement, a candidate's number, a record id or `none` for a reference, a name for a caption (`cap-<id>`), `holds`, `unknown` or `<date>@<kind>:<id>` for an open end (`open_ends` lists them), or `clear` to take an answer back. |
| `apply_suggestion` | enrich | `entity`, `id`, `picks`, `confirm`, `archive` | Write one suggestion through the tool it names (site, answer, save, fetch_source, link_image, portrait_import (downloads the Commons file, credits it), swap_source, graduate_stub, pin_upstream). |
| `archive_settings` | admin | `set`, `confirm`, `archive` | The archive's text settings, as the Archive page holds them: name, title, sub, about, description, theme, view, rail_shape and title_style. |
| `article_sections` | shape | `entity`, `archive` | An entity's article text (`entity`: its H, a record id, or a title only one entry has): its sections in order, each with `text` (Markdown), and, when imported, `from` (enwiki:Title@revision) and `licence`. |
| `badges` | shape | `archive` | The badge rules and how many entries each matches, and the post titles no role rule matches (`unmatched_post_titles`): those posts get no rank icon on the Org Chart. |
| `cast` | enrich | `entity`, `rule`, `value`, `archive` | One Graduate cast for a value (the entry's own, or one you give): the candidates the rule's lookups return (archive, universe, the local register), each with its source. |
| `check` | core | `archive` | Problems in the archive's files without building (rules files, records, sources), by level. |
| `check_records` | core | `records`, `collection`, `source`, `archive` | Dry run of `save`: checks proposed records and writes nothing. |
| `cite` | core | `citations`, `confirm`, `archive`, `sources` | Say where in a kept source a saved record's facts are: a list of {record, source, pages?, pdfPages?, locator?, quote?}. `record` is a record id (as `get_records` shows it); `source` the source document's id; `pages` the number printed on the document ("14", "I-16"); `pdfPages` the page of the PDF file ("20"); a scan's two differ (PDF p. |
| `collection_create` | core | `name`, `title`, `confirm`, `archive` | Make a new, empty collection `name` (letters, digits, - and _), with an optional display `title`. |
| `collection_delete` | shape | `name`, `confirm`, `archive` | Remove an empty collection made by mistake: its file, its entry in hydra.yaml (title, prefix, view handles) and its place in groups (a group left empty goes too). |
| `collection_merge` | shape | `into`, `from_`, `confirm`, `archive` | Join collection `from_` into `into` and remove `from_`: every record is kept with its id and H. Refused when the two collections have different id prefixes (the ids would change) or a record id clashes with different content. |
| `collection_rename` | shape | `old`, `new`, `confirm`, `archive` | Rename collection `old` to `new` without changing a record: the file, its entry in hydra.yaml (title, prefix, view handles), the groups that list it and open tasks on it all follow. |
| `collections` | core | `archive` | List the collections: id, title (the name readers see), id prefix, record count, and which views each is prepared for (`views`, with its handles in `view_specs`). |
| `context_checkout` | core | `id`, `name`, `reason`, `confirm`, `archive` | Set the context of task `id` to `name`, with a `reason`. |
| `contexts` | core | `task`, `words`, `archive` | List the contexts a task can work in (the brief that says what to keep and what to drop), as `{contexts: [...]}`. |
| `create_archive` | core | `path`, `name`, `prefix`, `confirm` | Start a new, empty hydra archive in a new or empty folder (full path, chosen by the person). |
| `decisions` | enrich | `kind`, `archive`, `offset`, `limit` | The answers already given, as the wiki's Review page lists them: each one's `id`, the question it answered, the answer, and `gone` when the records it was about have changed so the build no longer asks it. |
| `delete_feature` | geo | `feature`, `confirm`, `archive` | Remove a drawn Feature (by H, key or record id) and the GeoLinks that use it. |
| `describe_schema` | core | `schema`, `archive` | The entity types and relationships records can use. |
| `details` | core | `archive` | One-call overview of the archive: records, types, collections, the tree's roots, open questions. |
| `dismiss_suggestion` | enrich | `entity`, `id`, `confirm`, `archive` | Record that a suggestion is not wanted (`sug-<body>.<id>: rejected` in verdicts.yaml), so it is not offered again. |
| `draw_feature` | geo | `geometry`, `archetype`, `entity`, `new`, `name`, `aspect`, `kind`, `confirm`, `archive` | Draw a place the way the Atlas's + Feature does: a Feature (`geometry`, GeoJSON [lon, lat]; precision `drawn`) and a GeoLink at `aspect`. |
| `drop_source` | enrich | `source`, `confirm`, `archive` | Remove a kept source (`source`: its `doc-...` id) that no record cites, such as a page fetched by mistake: its entry and its stored file go and the archive is rebuilt. |
| `edit_geolink` | geo | `geolink`, `changes`, `confirm`, `archive` | Change one geo link (its record id, as `geo_locate` lists under `records`): {"role": …, "startDate": …, "endDate": … ("" clears), "entity": …, "location": … (any entity), "notes": …} or {"remove": true}. Preview; call again with confirm=true once the person agrees. |
| `edit_siting` | geo | `siting`, `changes`, `confirm`, `archive` | Old name of edit_geolink; use edit_geolink. |
| `enrichers` | enrich | `archive` | The enrichers this archive declares (.hydra/rules/enrichers.yaml): id, label, what an entry needs, source. |
| `enrichment_delete` | enrich | `entity`, `id`, `confirm`, `archive` | Remove exactly what one enrichment wrote: its record values or records, image file with its credit and rule, article section. |
| `enrichment_hide` | enrich | `entity`, `id`, `hidden`, `confirm`, `archive` | Leave what one enrichment added off the entry's page, keeping the data (a verdict `hide-<H body>.<id>` in verdicts.yaml; `hidden=false` shows it again). |
| `enrichments` | enrich | `entity`, `archive`, `offset`, `limit` | What Enrich added to one entry (H, key, record id or title), from its ledger (.hydra/enrich/<H>.jsonl): per apply, the id, enricher (Compare, Lead, Portrait, Match, Footnotes), source (Wikidata item, file page, article revision), time, who, whether it is hidden, and exactly what it wrote (record values, records, files, rules, sections). |
| `explain_entity` | core | `entity`, `archive` | Where every value of one entity came from (`entity`: its H, a record id, or a title only one entry has; a shared title is refused with the candidate Hs, never guessed; a record id that is a relationship answers with the record and the `collection` it lives in): each property's values with the records, collections and documents behind them, its canonical id, and the review questions it takes part in. |
| `export` | admin | `format`, `out`, `folder`, `ids`, `replace`, `confirm`, `archive` | Write the archive's compiled entities to a file: `format` ftm (standard FollowTheMoney lines), hydra-ftm (links as names), csv (a folder with nodes.csv and edges.csv) or graphml. |
| `extra_fields` | core | `archive` | The fields records carry that FtM does not have (kept in `_meta.extra` when a save finds one, or a key like `P1449`): each with its type, how many records hold it, its Wikidata code if marked, and the closest Wikidata properties. |
| `fetch_source` | enrich | `url`, `title`, `published`, `author`, `publisher`, `summary`, `language`, `keywords`, `archive`, `keep` | Fetch a web page and keep its text in the archive as a source of its own, so records can cite it: `"sources": ["<source_id>"]`, with their `notes` quoting it word for word. |
| `field_assign` | core | `field`, `schema`, `to`, `wd`, `confirm`, `archive` | Move an extra field's values on, for the records of `schema` that hold `field`. |
| `find_entities` | core | `query`, `schema`, `archive`, `limit`, `name` | Entities already in the archive closest to a name (`query`; `name` is accepted for it), best first, each with what tells it apart from its namesakes (`facts`: dates, nationality, posts; `links`: parents and relationships), its canonical id `h` and the `keys` it holds. |
| `geo_aspects` | geo | `entity`, `archive` | The places of one entry (H, key, record id or title), one per aspect the Atlas card shows: `home` (whose post it is), `posting` (the host country), `seat` (the building), `jurisdiction` (a region, then a district), or a person's born, residence, died. |
| `geo_contexts` | geo | `archive` | The geographic contexts installed in this archive (Bazaar packages that carry boundary or feature layers, such as districts or a front line): per package its version and licence, and per layer its name, label, feature count, levels and attribution. |
| `geo_enable` | geo | `confirm`, `archive` | Install the geo types (Place, Feature, GeoLink), their matching rules and .hydra/rules/geo.yaml in an archive made before them. |
| `geo_locate` | geo | `entity`, `as_of`, `archive` | Where one entity is (by H, key such as wikidata:Q… or osm:way/…, record id or title): its primary places (`how`: chosen by a person, or inferred from geo.yaml's role order) with shape, centre, extent and area; every geo link (role, `via`: geolink, coordinates, address, country), its members (what sits under it), its reach (places it is linked to by ownership, office...), and the places that contain it. |
| `geo_measure` | geo | `a`, `b`, `archive` | Measure on the sphere. |
| `geo_query` | geo | `within`, `near`, `containing`, `schema`, `role`, `via`, `primary_only`, `as_of`, `include_context`, `limit`, `offset`, `archive` | Which entities are where. |
| `geo_register_status` | geo | `archive` | The boundary layers kept on this machine (what `hydra-ctl geo register status` prints): per layer its label, version, licence, whether it is installed or packed with hydra, size and whether it is critical, plus `missing_critical` (layers the Atlas needs that are absent). |
| `geo_report` | geo | `top`, `include_entities`, `archive` | How much of the archive has a place, per entry type and finding count. |
| `geo_resolve` | geo | `point`, `entity`, `name`, `scope`, `level`, `archive` | Which real places hold a point, or which a name may be, from boundary and town data kept on this machine (nothing is sent anywhere). |
| `geo_summarize` | geo | `by`, `schema`, `tag`, `as_of`, `limit`, `archive` | How many entries lie in each area: `by` "country", "admin1" (region) or "context:<name>" (the features of a context layer, from `geo_contexts`). |
| `get_records` | core | `collection`, `name`, `offset`, `limit`, `archive`, `query`, `ids` | Read back what the archive holds. |
| `graduate_stub` | enrich | `name`, `as_schema`, `confirm`, `archive` | Make a stub (see `stubs`) a bare entity every link naming it points at, as `as_schema` (default: what its links fit). |
| `guide` | core | `topic`, `section`, `archive` | Read the hydra guide: with no `topic`, the list of topics; `guide("start")` first in every session. |
| `history_diff` | admin | `a`, `b`, `archive` | What changed between two snapshots (`b` left out: the files as they are now): each file, and inside a collection the records added, removed and changed. |
| `history_log` | admin | `limit`, `archive` | The archive's snapshots, newest first: who changed what (every save, answer and amend made here is one, by agent:hydra-mcp). |
| `history_restore` | admin | `ref`, `paths`, `confirm`, `archive` | Put the archive's files (or just `paths`) back as they were at snapshot `ref` (an id, or HEAD~1 for one change back). |
| `keys` | core | `archive` | The key namespaces of this archive (.hydra/rules/keys.yaml): for each, its label, link, the FtM property holding the same key, whether an entity may hold only one (`unique`); `primary`, the namespaces an entity is keyed by first (its H comes from that key); and how many entities hold a key of each namespace, undeclared ones listed. |
| `label` | shape | `entities`, `tokens`, `confirm`, `source`, `archive` | Attach labels to entries (by H, key, record id or title), the way the wiki's Labelling page does. |
| `labelling_guidelines` | core | `archive` | How to model records so hydra reads them correctly: the record format, one record per entity, which field each end of a relationship goes in, roles in the source's words, Family's direction, organizations inside organizations, offices, dates, and this archive's relationship fields and position ladder. |
| `layer_add` | geo | `file`, `name`, `attribution`, `licence`, `confirm`, `archive` | Add a GeoJSON file (full path: a FeatureCollection, a Feature or a geometry) as a map layer on the Atlas: not entities, never in records. |
| `layer_list` | geo | `archive` | The archive's map layers: GeoJSON drawn on the Atlas that is not entities (id, name, attribution, licence, feature count, bounding box). |
| `layer_remove` | geo | `layer`, `confirm`, `archive` | Remove a map layer by its id (layer_list). |
| `link_image` | enrich | `image`, `kind`, `schema`, `position`, `titled`, `name`, `confirm`, `archive`, `credit`, `entity` | Give entities an image or icon through a rule in hints.yaml (records never carry images). |
| `link_images` | enrich | `images`, `confirm`, `archive` | `link_image` for many images at once: [{image, kind, entity \| name, schema, ..., credit: {author, licence, url}}, ...]. Previews unless confirm=true; one history step for all. |
| `move_article_section` | shape | `entity`, `heading`, `to`, `confirm`, `archive` | Move the section with this `heading` to position `to` (1 is first) in an entity's article, and show the new order. |
| `move_feature` | geo | `entity`, `feature`, `geometry`, `delta_m`, `confirm`, `archive` | Move or reshape a place the way the Atlas's Move does. |
| `move_records` | shape | `ids`, `to`, `confirm`, `archive` | Move records (by record id, as `find_entities` or `get_records` give it) into collection `to`, keeping each record whole, with its id and H. Refused, with nothing moved, when a record is unknown, sits in several collections, has a different id prefix from `to` (the id would change) or its id already exists there. |
| `neighbors` | enrich | `entity`, `depth`, `edges`, `as_of`, `archive` | The entries linked to `entity` (an H, key, record id or title) within `depth` links (1 to 4), from the same graph the Graph and Radial views draw. |
| `open_ends` | enrich | `entity`, `collection`, `archive` | The posts, jobs and memberships (Occupancy, Employment, Membership) with a start and no end date, so a position is not held open-ended: each with its candidates for where it stopped (the holder's death, the next holder's start in the same post, a dated event involving the holder, another post of theirs that ended, a later date in the text) and the sources they come from. |
| `open_questions` | enrich | `kind`, `offset`, `limit`, `archive` | What the last build asks a person to decide: `merges` (are these one entity?), `references` (which record does this name mean?), `placements`, `stale` decisions, `contradictions`, and problems with `verdicts`. |
| `pack` | admin | `out`, `folder`, `history`, `replace`, `confirm`, `archive` | Pack the archive into one portable .hydra file (a zip with its build and, unless history=false, its history). |
| `package_install` | admin | `name`, `confirm`, `scope`, `archive` | Get a package (owner/name) from the registries for THIS archive: the bytes go once into the machine's shared store (`scope` machine) or the universe's backdrop, and a line goes into the archive's lock; only locked packages take part in the archive's lookups. |
| `packages` | admin | `archive` | Packages (themes, map styles, icon sets, symbology, archetypes, reference layers). |
| `paths` | core | `a`, `b`, `max_hops`, `edges`, `archive` | How two entries are connected: the chains of links from `a` to `b` of at most `max_hops` links (1 to 6), shortest first, up to 20, each with its entries and, per step, every link between that pair (type, label, dates, record id). |
| `pin_upstream` | enrich | `collection`, `record`, `h`, `confirm`, `archive` | Pin a saved record to an entity's canonical id `h` (from `find_entities`): the record is that entity from now on. |
| `positions` | shape | `mode`, `with_nodes`, `read`, `archive` | The rank ladder as a tree, and the role titles no position takes (`unplaced_titles`). |
| `preview` | core | `records`, `archive` | What saving a batch would change, built aside, writing nothing: the entities it adds, the merges it would make, the questions it would raise, and links that would stay names. |
| `probe` | enrich | `entity`, `enricher`, `refresh`, `query`, `archive`, `raw` | Run one enricher on one entry: ask its outside source (Wikidata, Wikipedia, Commons) once, keep the raw answer in .hydra/cache/probes/, and return it mapped onto fields (Compare: one row per field, what the entry has now and Wikidata's value). |
| `properties` | core | `schema`, `theme`, `level`, `query`, `code`, `archive` | The fields of a type, grouped in themes (Geography, Names, Dates, Person, Organization, Money, Online, Identifiers, Links, Other), each with its Wikidata code. |
| `publish` | shape | `hs`, `collections`, `confirm`, `archive` | Make computed Hs published, so their ids and page addresses hold from now on: `hs` (Hs, bodies or record ids), or every computed H whose records all come from `collections` (entities that also draw on other collections are listed, not published). |
| `read_file` | core | `path`, `part`, `offset`, `whole`, `archive` | The text of a file (.txt, .md, .html, .pdf, .docx), read exactly as it will be stored as evidence. |
| `read_page` | enrich | `entity`, `archive` | An entry's wiki page as a reader sees it (by H, key, record id or title): whether it is in scope, the infobox rows, the lead, every section's text in order, and the footnotes [n] resolved to the record, collection, source and quote behind each. |
| `read_source` | core | `source`, `offset`, `find`, `archive` | A kept source's text (by its id, from `fetch_source` or `save`), in parts from `offset` (for a kept PDF with `page_ranges`: each page's start and end in the text); or, with `find` (words), every sentence containing one of them: the sentences to quote in `notes`. |
| `recipe` | core | `name`, `args`, `archive`, `timeout` | Run one of the Archive Workflow's read-only command-line recipes by name and get its JSON. No `name` lists them with their `args`. |
| `remove_article_section` | shape | `entity`, `heading`, `confirm`, `archive` | Take the section with this `heading` out of an entity's article (its own text or an imported one). |
| `save` | core | `records`, `source`, `collection`, `archive`, `replace`, `mode` | Check and save records as a new collection, with their evidence, then rebuild. |
| `save_changes` | admin | `message`, `description`, `confirm`, `archive` | Save the work as one named change in history: the steps since the last save fold under it, so a task reads as one change. |
| `scope` | admin | `entity`, `archive` | What the archive is about (.hydra/rules/scope.yaml): how many entries are in scope, the context ones (kept in the data, named as text on the pages that mention them, listed nowhere), and for `entity` (an H, key, record id or title) whether it is in scope and why ("Ownership from <a seed entity>"). |
| `set_article_section` | shape | `entity`, `heading`, `text`, `from_`, `confirm`, `archive` | Add a section to an entity's article, or replace the text of the section with this `heading`. |
| `set_collection` | shape | `collection`, `views`, `confirm`, `archive`, `title` | Same as set_collection_views: set a collection's `title` and its view handles (specs). |
| `set_collection_group` | shape | `group`, `collections`, `title`, `confirm`, `archive` | Make or change a collection group (hydra.yaml `collection_groups.<group>`): a named set of collections that a view handle can open together. |
| `set_collection_views` | shape | `collection`, `views`, `confirm`, `archive`, `title` | Name a collection and say which views it is prepared for. |
| `set_positions` | shape | `positions`, `confirm`, `archive` | Write this archive's rank ladder (.hydra/rules/positions.yaml): {name: {below: [the positions above it], titles: [the role words that mean it], outside: false}}. The preview says how many of the archive's roles each position ranks and which roles none takes. |
| `set_primary` | geo | `entity`, `locations`, `confirm`, `archive` | Choose the places an entity is drawn by first (its pin, its map's extent), in order: `locations` are entities with a geometry (by H, key, record id or title), normally ones it is linked to; "auto" puts geo.yaml's order back. |
| `set_scope` | admin | `include`, `exclude`, `seeds`, `confirm`, `archive` | Change what the archive is about: add entries to `include` or `exclude` (Hs, keys, record ids, titles, or `collection:<name>`), or set the seed collections. |
| `set_symbology` | shape | `kind`, `key`, `value`, `confirm`, `archive` | Change one thing the wiki draws with: `kind` is `type-icon` (an entry type, `key` its schema), `badge-icon` (a badge rule's key), `position-icon` (a position's name; writes a hints.yaml rule), `link-colour` (a link type, `value` #rrggbb) or `link-mark` (a link type: what the Timeline draws when it has a start and no end, `value` start, fades or runs). |
| `site` | shape | `geolinks`, `collection`, `confirm`, `archive` | Say where an entity is: [{entity, location, role?, startDate?, endDate?, primary?, precision?, radius?, sources?, notes?, pages?, locator?, name?}]. `location` is {"place": …}, {"feature": …}, {"entity": …}, {"address": …}, {"osm": "way/123"}, {"point": [lon, lat]}, {"bbox": …}, {"geometry": GeoJSON} or {"register": key from geo_resolve}; points are [longitude, latitude]. `sources` (kept source IDs) and `notes` are checked against those sources. |
| `source_names` | core | `path`, `from_page`, `to_page`, `min_count`, `archive` | The capitalised names of two words or more in a document (pages `from_page`..`to_page` of a PDF, else all), with how often each comes and `in_archive`: the entries already carrying that exact name or alias. |
| `source_outline` | core | `path`, `archive` | A document's parts and their pages, without reading it: headings with level, character offset in the text hydra keeps and page, from a PDF's bookmarks (not scan batches), Word heading styles, Markdown or HTML headings, else the heading lines in the text (contents pages left out). |
| `source_profile` | core | `path`, `archive` | A file measured once, no text: pages, characters, words per page, text layer, OCR noise, redaction marks, headings, numbered paragraphs, front and back matter, links, and its parts for `read_file(part=n)`, with warnings. |
| `source_report` | enrich | `top`, `archive` | Where the archive's facts come from: citations counted by origin (the site a URL belongs to), the W-factor (of the citations that cite anything, the share resting on Wikipedia alone) for the archive and each collection, how many cite nothing, and the entries that rest most on Wikipedia, each with the records to re-source (record, collection, Wikipedia URL, the quote). |
| `sources` | core | `query`, `uncited_only`, `archive`, `offset`, `limit`, `uncited_entities` | List every kept source (`doc-...` ID, title, URL, filename, `has_text`, citations) plus `uncited_sources` and `uncited_entities_count`; the first 50 entities that cite no source are listed as `uncited_entities` only with `uncited_entities=true`. |
| `stubs` | enrich | `archive` | Names that links hold but no record has (the wiki's red links): how many links name each, from which fields, and what kind of entity they fit; and those already graduated. |
| `suggestions` | enrich | `entity`, `archive` | What could be done for one entry (by H, key, record id or title), from local data only, as the wiki's Suggestions drawer lists it. |
| `suggestions_reset` | enrich | `entity`, `confirm`, `archive` | Forget one entry's dismissed suggestions and kept probe answers, so every suggestion and enricher asks again. |
| `swap_source` | enrich | `collection`, `record`, `source`, `quote`, `confirm`, `archive` | Re-source a saved record: its Wikipedia citation out, the kept source `source` (from `fetch_source`) in, with `quote` (word for word in that source, checked) as its note. |
| `symbology` | shape | `archive` | What the wiki draws with, as the Symbology page shows it: each entry type's icon and how many entries it marks, each badge rule's icon and reach, each position's picture rule, each link type's colour in the Radial and Org Chart, every image rule (hints.yaml) and what it reached, and the icon tokens there are to choose from. |
| `tags` | shape | `entity`, `archive` | Each tag (archetype) an entry scores against, as Review and Labelling do: `score` out of 100 against the tag's `fit` line, whether it `fits`, the person's `decision` (confirmed, rejected or undecided), what the entry `shows` and what it `lacks`. |
| `task` | core | `id`, `archive` | Show a task as it stands: every step with its status and result, `next_step` with its instructions, the sources kept for it (`uncited_sources`: kept but cited by no record yet), claims and the last log lines. |
| `task_add` | core | `subject`, `step`, `block`, `code`, `id`, `archive` | Add to your task: `subject` adds another block of the workflow's per-subject steps; or `code` + `step` (its text) adds one step to the block whose title contains `block` (default: the last). |
| `task_checkout` | core | `id`, `holder`, `force`, `archive`, `reason`, `details`, `model`, `client` | Take a task for this session before working on it. |
| `task_close` | core | `status`, `summary`, `id`, `force`, `archive` | Finish your task: `done` (refused while a step is open) or `blocked` (with a `summary` of what the person must decide). |
| `task_new` | core | `title`, `workflow`, `collection`, `views`, `subjects`, `authorized`, `confirm`, `archive`, `context` | Make a task: a checklist from a `workflow` (a list is a route: the workflows in order, each step code prefixed with its position; left out, the context's route, or `enrich`). |
| `task_release` | core | `id`, `force`, `archive` | Hand a task back unfinished (it becomes `open`, its steps and log kept) so another session can take it. |
| `task_step` | core | `step`, `status`, `result`, `reason`, `claim`, `evidence`, `subject`, `id`, `archive`, `exit` | Tick one step of your checked-out task, right after doing it. |
| `task_verify` | core | `id`, `archive` | Check a task before closing it: open steps, claims, sources kept vs cited, what changed since checkout, and each of its views' checks. |
| `tasks` | core | `status`, `workflow`, `collection`, `archive`, `offset`, `limit` | List the archive's tasks (status `open`, `checked-out`, `blocked` or `done`) with steps done of total, and `current_task`, the one this session has checked out. |
| `toolset_enable` | core | `name`, `archive` | Switch a tool set on (`enrich`, `geo`, `shape`, `admin`, or `all`) and tell the client its tool list changed. |
| `toolsets` | core | `archive` | The tool sets and whether each is on, with the tools in it: `core` is always on; `enrich`, `geo`, `shape` and `admin` are switched on with `toolset_enable`. |
| `transform_geometry` | geo | `feature`, `op`, `args`, `as_new`, `confirm`, `archive` | One operation on a geometry (a Feature, by H, key or record id): `simplify` {"metres": n} (fewer points, none moved more than n), `to_point` (its centre), `to_bbox` (its extent, as an area), `circle` {"metres": n} (a point to an approximate area), `fix` (close rings, wind them, round, swap [lat, lon] written the wrong way round). |
| `tree` | shape | `kind`, `search`, `read`, `format`, `archive` | The placement tree: which entry sits under which (the Org Chart and Radial are drawn from it). |
| `universe_build` | admin | `archive` | Build the universe from the last archive build: which records are one entity, each entity's canonical id (H) and the wiki pages. |
| `upgrade` | admin | `confirm`, `archive` | Bring the archive up to date: an older format, or records still under an old schema name (Siting is now GeoLink). |
| `view_check` | shape | `view`, `collection`, `archive` | What one view cannot draw, or draws poorly, for a collection (or the whole archive). |
| `view_config` | shape | `collection`, `archive` | What each view starts with: entry and link types hidden, map settings, the entry panel's buttons, icons and badge rules, as the wiki applies them (with a collection's own overrides). |
| `vocabularies` | core | `archive` | The words a status or capacity field takes in this archive, and what hydra does with each: {name: {applies_to: ["Interest.status", ...], values: {word: {label, why, ended, caveat, beneficiary}}}}. `ended` means the record counts as over, `caveat` that it is flagged wherever the fact is shown. |
| `wiki_readiness` | shape | `archive` | What keeps the archive's wiki pages from being complete, each as something to record or decide: terms with no years, names that link to no record, links that name several records, same-name pairs, facts only in notes, people with no dates, unsourced pages, facts that contradict each other. |
| `wiki_serve` | shape | `port`, `theme`, `replace_other`, `archive` | Show the archive as a wiki at http://127.0.0.1:<port>/, current: builds the pages when they are older than their inputs, stops the wiki this tool started on that port, starts a new one and checks it serves as many entries as the build made pages (`ok`). |
| `wiki_stop` | shape | `port` | Stop the wiki this tool started on `port`. |
| `wikidata_answer` | wikidata | `entity`, `qid`, `confirm`, `archive` | The person's answer to one Wikidata question: `qid` is the candidate they confirmed, or `none`. |
| `wikidata_purge` | enrich | `entity`, `forget_match`, `confirm`, `archive` | Start over from Wikidata: remove everything Wikidata added to one entry, whether or not the Enrich ledger lists it. |
| `wikidata_questions` | wikidata | `schema`, `limit`, `offset`, `archive` | The Wikidata questions for this archive: each entry with no Wikidata key yet (a Person, an Organization…), what the archive itself says about it (dates, country, posts held) and Wikidata's candidates (Q-id, label, description). |
| `wikidata_status` | wikidata | `archive` | How far the archive is linked to Wikidata: its entries, how many are matched, answered "none", or open. |
| `wikipedia_footnotes` | enrich | `url`, `quote`, `archive` | What Wikipedia itself cites for a sentence: given the article `url` a record cites and the `quote` it took from it, the references attached to that sentence (url, title, publisher, date). |
| `workflows` | core | `archive` | List the workflows a task can start from, with when to use each. |
<!-- tools:end -->

## The agent guide and tasks

The guide an assistant follows is served by the server itself, one topic at a time, so it always matches the
version installed: `guide()` lists the topics and `guide("start")` is where every session begins. It covers the
rules, sources, identity, which record holds which fact, each wiki view (Org Chart, Links, Radial, Map, Timeline,
the entry panel), and the workflows. See [AGENTS.md](AGENTS.md).

Work is tracked as tasks kept in the archive: `task_new` makes a checklist from a workflow (`enrich`, `view-prep`, `places`, `label`, `collection-shape`, `geo-analysis`, `review`, `resource`, `country-audit`, `media`, `entry-page`, `close-out`, `stubs`, `map-layer`, `upkeep`), `task_checkout` takes it for a session, `task_step` ticks each step with what it found, and `task_close` finishes it. Every write is logged on the task. `guide()` also returns the version of hydra that wrote the guide.

[AGENT-TOOLS.md](AGENT-TOOLS.md) maps every tool to the stage it belongs to. [Connect a client](../hydra-docs/docs/connect-a-client.md) says how to add the server to Claude Code or Claude Desktop from a dev install or from the desktop app's bundle.

## Labelling guidelines

The server doesn't try to catch every badly structured record after the fact. It tells the assistant how to write good ones in the first place, from the rules in [the hierarchy guide](https://meridiangray.github.io/open-hydra/guides/hierarchy/) and hydra's data model. `labelling_guidelines` returns them, and the server's instructions tell the assistant to read them before proposing a record:

- only what the text states: no facts from memory, no inferred relationships
- one record per entity, its fullest name as written; other full names in `alias`, surnames and nicknames in `weakAlias`; two records when unsure, since review merges them
- each end of a relationship in the right field and of the right kind, never pointing at itself
- roles in the text's own words, left out when the text gives none, never changed to fit the hierarchy
- Family's word describes the relative from the person's side ("father" puts the relative above)
- an organization inside another takes a role like "affiliate", "unit" or "branch", never a person's rank; a subsidiary is an Ownership
- dates only as given, the start never after the end
- a public office is a Position plus an Occupancy: the holder sits under the office's organization, titled by the office; events link their participants through `involved`; addresses stay in `address` unless shared
- images, the hierarchy and review decisions left to the archive's owner

The relationship table (which field is which end, what kind of entity each takes, which end hydra draws above) and the position ladder are read from the archive itself: its schema, `direction.yaml` and hierarchy. With a custom `positions.yaml` the guidelines show its positions; without one, hydra's defaults.

## Records

Records use hydra's FtM dialect: links are written as the linked entity's name, not an id.

```json
[
  {"schema": "Person", "properties": {"name": ["Rob Kerr"], "weakAlias": ["Kerr"]}},
  {"schema": "PublicBody", "properties": {"name": ["Port Authority"]}},
  {"schema": "Employment", "properties": {"employee": ["Rob Kerr"], "employer": ["Port Authority"],
                                          "role": ["deputy"], "startDate": ["2019"]}}
]
```

`id` is optional; one is minted: a three-letter code for the kind of record and ten random characters (`per-w3v2f7z7pe`), never derived from a name, so a corrected name never moves it. Values can be a string or a list. Dates are `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.

`check_records` blocks on: an unknown or abstract schema, a property the schema doesn't have, a malformed date, a relationship missing one of its ends, an entity without a name, an image field (images are linked in `hints.yaml`, never in records), and two records sharing an id.

## With or without a custom hierarchy

Hydra ranks people inside an organization by the `role` on their relationship (or their own `position`), matched against the titles of the positions in effect. `labelling_guidelines` reports which ladder is in effect:

- **defaults only:** hydra's four positions (Leader, Second-in-command, Member, Associate). Only leadership roles rank: "deputy" ranks as Second-in-command, "administrator" ranks no one.
- **custom and defaults:** the archive's `positions.yaml` adds its own positions (a corporate chain, an agency's ranks) to the defaults.
- **custom only:** the defaults are switched off and `positions.yaml` is the whole ladder.

In every mode the assistant keeps each role in the source's own words. `check_records` and `save` report the position each role ranks as, and for a role nothing takes, the title to add to `positions.yaml` if the archive's owner wants it ranked. The data stays faithful to the text, and the hierarchy catches up. See [the hierarchy guide](https://meridiangray.github.io/open-hydra/guides/hierarchy/).

## Changes the owner approves

Images aren't facts from a text, so the assistant never puts them in records. `link_image` adds a rule to `.hydra/rules/hints.yaml` that gives matching entities a `portrait`, an icon (`thumb`) or a `logo`. It works in two calls: without `confirm` it only previews the rule, and the assistant calls it with `confirm=true` only after you approve. The match is `schema`, `position`, `titled` and/or `name`, all of which must hold. Local files only, never a URL; the file is copied into `.hydra/resources/`, a rule that `hydra-ctl check` flags is not kept, and the archive is rebuilt to say how many entities it reached.

The position ladder changes only through `set_positions`, which previews first and which the person confirms. Roles are kept in the source's words, and `save` reports the ones that rank no one.

## Install

`hydra-mcp` needs [open-hydra](https://github.com/meridiangray/open-hydra) (the `open-hydra` package, which gives `hydra-ctl`), and Python 3.11 or later. Neither is on PyPI yet, so install both from GitHub:

```sh
uv tool install git+https://github.com/meridiangray/open-hydra-mcp --with git+https://github.com/meridiangray/open-hydra
```

Or with pip, into any environment:

```sh
pip install git+https://github.com/meridiangray/open-hydra git+https://github.com/meridiangray/open-hydra-mcp
```

To update, run the same command again with `uv tool install --reinstall` or `pip install --force-reinstall`, and restart your client.

## Add it to your client

Every MCP client needs the command `hydra-mcp` and, optionally, `HYDRA_ARCHIVE` set to the archive's folder.

**Claude Code:**

```sh
claude mcp add hydra --env HYDRA_ARCHIVE=/path/to/case -- hydra-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "hydra": {
      "command": "hydra-mcp",
      "env": {"HYDRA_ARCHIVE": "/path/to/case"}
    }
  }
}
```

If the client can't find the command, give its full path (`which hydra-mcp` or `where hydra-mcp` prints it).

**Windows:** give the full path and double every backslash:

```json
"command": "C:\\Users\\you\\.local\\bin\\hydra-mcp.exe",
"env": {"HYDRA_ARCHIVE": "C:\\cases\\case"}
```

**Installed in WSL, client on Windows:**

```json
"command": "wsl",
"args": ["-d", "Debian", "--", "bash", "-lc", "HYDRA_ARCHIVE=/mnt/c/cases/case hydra-mcp"]
```

## Running it

The archive is each tool's `archive` argument, else `HYDRA_ARCHIVE`, else an archive activated (`hydra-ctl activate`) in the folder the server starts in or above it, else that folder if it is an archive.

### With no archive

If none of those gives an archive, nothing is written anywhere:

- Tools that need an archive say none is selected, and tell the assistant to ask you for one or offer `create_archive`.
- `labelling_guidelines`, `describe_schema` and `check_records` still work, on hydra's defaults, and say so. The assistant can read the text and check its records before an archive exists. `find_entities` finds nothing, since there is nothing to find.
- `save` and `get_records` refuse with the same advice.
- `create_archive` takes the full path of a new or empty folder you choose, a name (default: the folder's) and an id prefix (default: made from the name, `none` for one per collection). It previews first and creates the archive only with `confirm=true`. The assistant then passes that folder as `archive`. To make it the default, set `HYDRA_ARCHIVE` in the server's configuration.

An archive that is named but isn't one (a wrong path) is an error, never a quiet fallback to the defaults.

## Tests

```sh
git clone https://github.com/meridiangray/open-hydra
git clone https://github.com/meridiangray/open-hydra-mcp
cd open-hydra-mcp
python3 -m venv .venv && .venv/bin/pip install pytest -e ../open-hydra -e .
.venv/bin/python -m pytest -q
```

## License

Copyright (c) 2026 Meridian Gray. hydra-mcp is free software under the [GNU Affero General Public License, version 3 only](LICENSE), as is [open-hydra](https://github.com/meridiangray/open-hydra). If you run a modified version as a network service, the AGPL requires you to offer its users the source of your changes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before a pull request can merge, you agree once to the [Contributor Agreement](CLA.md).
