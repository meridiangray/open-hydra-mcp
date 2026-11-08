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
| Tool | Arguments | What it does |
|---|---|---|
| `labelling_guidelines` | `archive` | How to model records so hydra reads them correctly: the record format, one record per entity, which field each end of a relationship goes in, roles in the source's words, Family's direction, organizations inside organizations, offices, dates, and this archive's relationship fields and position ladder. |
| `read_file` | `path`, `offset`, `archive` | The text of a file (.txt, .md, .html, .pdf, .docx), read exactly as it will be stored as evidence. |
| `find_entities` | `query`, `schema`, `archive`, `limit` | Entities already in the archive closest to a name, best first, each with what tells it apart from its namesakes (`facts`: dates, nationality, posts; `links`: parents and relationships), its canonical id `h` and the `keys` it holds. |
| `explain_entity` | `entity`, `archive` | Where every value of one entity came from (`entity`: its id, or a name): each property's values with the records, collections and documents behind them, its canonical id, and the review questions it takes part in. |
| `open_questions` | `kind`, `offset`, `limit`, `archive` | What the last build asks a person to decide: `merges` (are these one entity?), `references` (which record does this name mean?), `placements`, `stale` decisions, `contradictions`, and problems with `verdicts`. |
| `answer` | `id`, `choice`, `confirm`, `archive` | Answer one open question (`id` from `open_questions`): `confirm` or `reject` a merge or placement, a candidate's number, a record id or `none` for a reference, a name for a caption (`cap-<id>`), or `clear` to take an answer back. |
| `amend_records` | `collection`, `records`, `remove`, `archive` | Correct a saved collection: each record with an `id` already in it replaces that record whole (give every property it should keep; its evidence stays cited); a record with a new or no id is added; `remove` drops records by id. |
| `preview` | `records`, `archive` | What saving a batch would change, built aside, writing nothing: the entities it adds, the merges it would make, the questions it would raise, and links that would stay names. |
| `pin_upstream` | `collection`, `record`, `h`, `confirm`, `archive` | Pin a saved record to an entity's canonical id `h` (from `find_entities`): the record is that entity from now on. |
| `set_positions` | `positions`, `confirm`, `archive` | Write this archive's rank ladder (.hydra/rules/positions.yaml): {name: {below: [the positions above it], titles: [the role words that mean it], outside: false}}. The preview says how many of the archive's roles each position ranks and which roles none takes. |
| `link_images` | `images`, `confirm`, `archive` | `link_image` for many images at once: [{image, kind, name, schema, ...}, ...]. Previews unless confirm=true. |
| `wiki_readiness` | `archive` | What keeps the archive's wiki pages from being complete, each as something to record or decide: terms with no years, names that link to no record, links that name several records, same-name pairs, facts only in notes, people with no dates, unsourced pages, facts that contradict each other. |
| `history_log` | `limit`, `archive` | The archive's snapshots, newest first: who changed what (every save, answer and amend made here is one, by agent:hydra-mcp). |
| `history_diff` | `a`, `b`, `archive` | What changed between two snapshots (`b` left out: the files as they are now): each file, and inside a collection the records added, removed and changed. |
| `history_restore` | `ref`, `paths`, `confirm`, `archive` | Put the archive's files (or just `paths`) back as they were at snapshot `ref` (an id, or HEAD~1 for one change back). |
| `describe_schema` | `schema`, `archive` | The entity types and relationships records can use. |
| `universe_build` | `archive` | Build the universe from the last archive build: which records are one entity, each entity's canonical id (H) and the wiki pages. |
| `publish` | `hs`, `collections`, `confirm`, `archive` | Make computed Hs published, so their ids and page addresses hold from now on: `hs` (Hs, bodies or record ids), or every computed H whose records all come from `collections` (entities that also draw on other collections are listed, not published). |
| `scope` | `entity`, `archive` | What the archive is about (.hydra/rules/scope.yaml): how many entries are in scope, the context ones (kept in the data, named as text on the pages that mention them, listed nowhere), and for `entity` (an H, key, record id or title) whether it is in scope and why ("Ownership from <a seed entity>"). |
| `set_scope` | `include`, `exclude`, `seeds`, `confirm`, `archive` | Change what the archive is about: add entries to `include` or `exclude` (Hs, keys, record ids, titles, or `collection:<name>`), or set the seed collections. |
| `stubs` | `archive` | Names that links hold but no record has (the wiki's red links): how many links name each, from which fields, and what kind of entity they fit; and those already graduated. |
| `graduate_stub` | `name`, `as_schema`, `confirm`, `archive` | Make a stub (see `stubs`) a bare entity every link naming it points at, as `as_schema` (default: what its links fit). |
| `wiki_serve` | `port`, `theme`, `replace_other`, `archive` | Show the archive as a wiki at http://127.0.0.1:<port>/, current: builds the pages when they are older than their inputs, stops the wiki this tool started on that port, starts a new one and checks it serves as many entries as the build made pages (`ok`). |
| `wiki_stop` | `port` | Stop the wiki this tool started on `port`. |
| `keys` | `archive` | The key namespaces of this archive (.hydra/rules/keys.yaml): for each, its label, link, the FtM property holding the same key, whether an entity may hold only one (`unique`); `primary`, the namespaces an entity is keyed by first (its H comes from that key); and how many entities hold a key of each namespace, undeclared ones listed. |
| `vocabularies` | `archive` | The words a status or capacity field takes in this archive, and what hydra does with each: {name: {applies_to: ["Interest.status", ...], values: {word: {label, why, ended, caveat, beneficiary}}}}. `ended` means the record counts as over, `caveat` that it is flagged wherever the fact is shown. |
| `check_records` | `records`, `collection`, `source`, `archive` | Dry run of `save`: checks proposed records and writes nothing. |
| `fetch_source` | `url`, `title`, `published`, `author`, `archive` | Fetch a web page and keep its text in the archive as a source of its own (an Article), so records can cite it: `"sources": ["<source_id>"]`, with their `notes` quoting it word for word. |
| `read_source` | `source`, `offset`, `find`, `archive` | A kept source's text (by its id, from `fetch_source` or `save`), in parts from `offset`; or, with `find` (words), every sentence containing one of them: the sentences to quote in `notes`. |
| `source_report` | `top`, `archive` | Where the archive's facts come from: citations counted by origin (the site a URL belongs to), the W-factor (of the citations that cite anything, the share resting on Wikipedia alone) for the archive and each collection, how many cite nothing, and the entries that rest most on Wikipedia, each with the records to re-source (record, collection, Wikipedia URL, the quote). |
| `wikipedia_footnotes` | `url`, `quote` | What Wikipedia itself cites for a sentence: given the article `url` a record cites and the `quote` it took from it, the references attached to that sentence (url, title, publisher, date). |
| `swap_source` | `collection`, `record`, `source`, `quote`, `confirm`, `archive` | Re-source a saved record: its Wikipedia citation out, the kept source `source` (from `fetch_source`) in, with `quote` (word for word in that source, checked) as its note. |
| `read_page` | `entity`, `archive` | An entry's wiki page as a reader sees it (by H, key, record id or title): whether it is in scope, the infobox rows, the lead, every section's text in order, and the footnotes [n] resolved to the record, collection, source and quote behind each. |
| `get_records` | `collection`, `name`, `offset`, `limit`, `archive` | Read back what the archive holds. |
| `save` | `records`, `source`, `collection`, `archive`, `replace` | Check and save records as a new collection, with their evidence, then rebuild. |
| `link_image` | `image`, `kind`, `schema`, `position`, `titled`, `name`, `confirm`, `archive` | Give entities an image or icon through a rule in hints.yaml (records never carry images). |
| `create_archive` | `path`, `name`, `prefix`, `confirm` | Start a new, empty hydra archive in a new or empty folder (full path, chosen by the person). |
<!-- tools:end -->

For the whole workflow, from a source to a checked wiki page, see [AGENT-GUIDE.md](AGENT-GUIDE.md).

The intended order: guidelines, `read_file`, `describe_schema` and `find_entities` while drafting, `check_records`, `save`, then `get_records` to verify; then `wiki_serve` to see the pages, `wiki_readiness` and `stubs` for what they lack, and `publish` once the person agrees they are right.

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

The position ladder is not changed through this server. Roles are kept in the source's words, and `save` reports the ones that rank no one; the owner edits `.hydra/rules/positions.yaml` (see the hierarchy guide).

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
