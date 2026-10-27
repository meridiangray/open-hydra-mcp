# open-hydra-mcp

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/meridiangray)

An MCP server that lets an AI assistant add facts it finds in raw text to a [hydra](https://github.com/meridiangray/open-hydra) archive: an article, a court filing, a press release, notes from an interview. The assistant reads the text and proposes FollowTheMoney records. The server tells it what the archive accepts, checks its proposal, and only then writes it, with the text stored as the source every entity cites.

It doesn't guess. Anything uncertain is left for a person: a name that might be someone already in the archive becomes a merge question in `hydra-ctl review`, a link to someone the archive doesn't know stays a name, and a role the hierarchy doesn't rank is reported, not rewritten.

## What an ingestion writes

Each call to `save` adds one new collection and nothing else:

```
collections/<collection>.json                 the records
.hydra/sources/entries/<collection>.json      the raw text, as one Document (an Article when it has a URL)
```

Every entity (person, organization, company…) cites that document in `sources`, so `hydra-ctl claims` and `hydra-ctl sources` trace each value back to the text. Relationships have no `sources` field in FtM: they trace back through their collection, which holds that one source only.

The archive is rebuilt after writing, and the result reports the new review questions. A batch with errors is never written, an existing collection is never overwritten unless asked, and a build that fails puts the files back as they were. To undo an ingestion, delete its two files and run `hydra-ctl build`.

## Tools

| Tool | What it does |
|---|---|
| `labelling_guidelines` | How to write records so hydra places them correctly, with this archive's relationship fields and position ladder |
| `read_file` | A file's text exactly as it will be stored as evidence, in parts; says whether the archive already holds it |
| `describe_schema` | With no name, the entity types and relationships; with one, every property it accepts, its type, which are required, and what a link takes |
| `find_entities` | Existing entities closest to a name, so new records link instead of duplicating |
| `check_records` | Dry run of `save`: errors, warnings, how links and roles resolve, likely duplicates. Writes nothing |
| `save` | Checks, writes the batch and its evidence, rebuilds, and reports what changed |
| `get_records` | Reads a saved collection back with each property's type, what every link resolved to after the build, and the checks repeated on what was written |
| `link_image` | Previews, then on `confirm` adds, a `hints.yaml` rule giving matching entities a portrait, an icon (`thumb`) or a logo from a local file |
| `create_archive` | Previews, then on `confirm` creates, a new empty archive in a new or empty folder (as `hydra-ctl init`) |

The intended order: guidelines, `read_file`, `describe_schema` and `find_entities` while drafting, `check_records`, `save`, then `get_records` to verify.

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

`id` is optional; one is made from the schema and name (`person-rob-kerr`). Values can be a string or a list. Dates are `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.

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
python3 -m venv .venv && .venv/bin/pip install pytest "mcp>=1.2,<2" -e ../open-hydra -e .
.venv/bin/python -m pytest -q
```

## License

Copyright (c) 2026 Meridian Gray. hydra-mcp is free software under the [GNU Affero General Public License, version 3 only](LICENSE), as is [open-hydra](https://github.com/meridiangray/open-hydra). If you run a modified version as a network service, the AGPL requires you to offer its users the source of your changes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before a pull request can merge, you agree once to the [Contributor Agreement](CLA.md).
