# Adding data to a hydra archive: follow these steps in order

Do the steps in order. Do not skip a step. Do not combine steps. After every step, update your checklist (Part 3). If a step says STOP, stop and tell the person; do not try to work around it.

The longer guides are AGENT-GUIDE.md (rules) and AGENT-TOOLS.md (every tool). You do not need them to follow this one.

## Part 1. Five rules that are never broken

1. **Quote the source exactly.** The `notes` field holds a sentence copied word for word from a source you read with `read_source` or `read_file`. Never write your own words in `notes`. Never copy from a browsing tool's summary.
2. **Write only what the source says.** No guessing, no filling in dates, no working out percentages, no naming something the source only describes.
3. **A name is not proof.** Two things with the same name stay two records. Only an id (a key) or the person's say-so makes them one.
4. **Ask before you change anything big.** Anything with `confirm` needs the person to say yes first. Show them the preview, wait for yes, then call again with `confirm=true`.
5. **Never use an archive you were not given.** Use only the folder the person named, passed as `archive` in every call.

## Part 2. The steps

Each step: **Tool** to call, **Do** what to do, **Done when** you may tick the box, **STOP if** what to do instead.

### A. Before you start (once per session)

**A1. Read the rules.**
- Tool: `labelling_guidelines`. Do: read all of it. Done when: you can say which fields hold owners, offices and family in this archive.
- STOP if: it errors. Tell the person the error text.

**A2. Save the baseline.**
- Tool: `wiki_readiness`. Do: write down the count for every finding in your checklist. Done when: the numbers are written.
- STOP if: it says there is no universe layer. Tell the person; they must add it.

**A3. Check what is allowed.**
- Tools: `scope`, `vocabularies`, `keys`. Do: note the seed collections, the status words, and the key namespaces. Done when: noted.

### B. For each subject (one company, person or asset at a time)

**B1. Get the source text.**
- Web page: `fetch_source` with the URL, then `read_source` (use `find` with words from the fact to get the exact sentences).
- Local file: `read_file` (use `offset` to read to the end).
- Done when: you have read the whole source and copied each sentence you need.
- STOP if: the page will not load. Skip that source; do not try to get around it.

**B2. Find what already exists.**
- Tool: `find_entities` once for every person, company or asset you will name. Do: if a match is the same real thing, use its exact name or id in your records. Done when: every name is looked up.
- STOP if: two matches both look right. Ask the person.

**B3. Write the records on paper first.** For each fact write: the sentence, the type (`describe_schema` with the type name tells you the fields), and the fields. Use this table:

| Fact | Type | Key fields |
|---|---|---|
| Who owns it | `Ownership` | `owner`, `asset`, `percentage`, `startDate`, `endDate`, `status`, `notes` |
| Family | `Family` | `person`, `relative`, `relationship` |
| Runs a company | `Directorship` or `Employment` | `director`/`employee`, `organization`, `role` |
| Holds an office | `Position` + `Occupancy` | `holder`, `post`, dates |
| Member of a group | `Membership` | `member`, `organization`, `role` |
| A sale or deal | `Event` | `name`, `date`, `amount`, `currency`, `description`, `involved` |
| What a thing is | `description` on the entity | one or two plain sentences, no sourcing talk |

- Percent or price only if the source gives an exact number. "About", "estimated", "asking" go in `notes`, not in `percentage` or `amount`.
- `status` only from the words `vocabularies` listed.
- Dates exactly as the source gives them.
- Each record lists the source it came from: `"sources": ["doc-..."]` (the id `fetch_source` returned).
- Done when: every fact has a sentence, a type and fields.

**B4. Check.**
- Tool: `check_records` with your records (add `source` if they all come from one file).
- Do: fix every error. Read every warning. Done when: zero errors and you can explain each warning.
- STOP if: a warning says a key already belongs to another entity, or a link is ambiguous. Ask the person.

**B5. Preview if the batch is big.**
- Tool: `preview`. Do: if it would merge entities or add many questions you did not expect, STOP and ask. Done when: the preview matches what you meant (skip this step for a small batch and tick it "skipped, small").

**B6. Save.**
- Tool: `save` with the same records (and `source` if you used it in B4). Done when: it reports success.
- If a saved record is wrong later: `amend_records` with the same `id`.

**B7. Read it back.**
- Tool: `get_records` with the collection. Do: check every property and link against your paper notes. Done when: all match.

**B8. Look for missing records.**
- Tool: `stubs`. Do: for each name with no record, write the record if the source gives its facts (go back to B3), or leave it red on purpose and write why in the checklist. Done when: every stub is dealt with.

### C. Build and check the pages (after each subject or small group)

**C1. Build.**
- Tool: `universe_build`. Done when: it returns counts. Write them down.

**C2. Questions.**
- Tool: `open_questions`. Do: for each question, write down what you would answer and why, and show the person. Do NOT call `answer` until the person says yes to that question.
- After a yes: `answer` (preview), then again with `confirm=true`, then `universe_build` again. Done when: every question is answered or handed to the person.

**C3. Compare to the baseline.**
- Tool: `wiki_readiness`. Do: compare every number with A2. Every increase must be something you meant. Done when: every difference is explained in the checklist.
- STOP if: a red link, a raw status word, a code that is not ISO, or a big jump appears that you cannot explain.

**C4. Scope.**
- Tool: `scope` with `entity` set to each main thing you researched. Done when: each is in scope.
- STOP if: one is not. A relationship is missing: add it if the source gives it. Do not call `set_scope` without the person's yes.

**C5. Read the new pages.**
- Tool: `read_page` for every new entry. Check: does the lead say what it is; is each fact in the right section; do the References quote the source's own words; is there anything that reads like a guess. Done when: every page passes. A failure sends you back to B3.

**C6. Serve.**
- Tool: `wiki_serve`. Done when: it returns `ok: true`.
- STOP if: another server holds the port. Do not use `replace_other` without the person's yes. If `ok` is false, run `universe_build` and `wiki_serve` once more; if still false, STOP.

### D. Finish

**D1. Outside ids (only if the source gave one).**
- Tool: `pin_upstream` (`collection`, `record`, and `h` or a key like `wikidata:Q57340`). Never guess a Q-number. Preview, show the person, then `confirm=true`.

**D2. Images and icons (only if the person gave you image files).**
- Tool: `link_image` (`image` = full path, `kind` = `portrait`, `thumb` or `logo`, and who gets it with `schema`, `position`, `titled` or `name`). Preview shows who matches: show the person. After yes: `confirm=true`, then `wiki_serve` and look at one page.

**D3. Publish.**
- Tool: `publish` with `collections=[your collection]`. Preview, show the person, wait for yes, then `confirm=true`. Done when: it reports published.

**D4. Undo if needed.**
- Tools: `history_log`, then `history_diff`, then `history_restore` (preview, then `confirm=true` with the person's yes). Run `universe_build` after.

### Things you cannot do: tell the person

Importing a file (FtM, CSV, GraphML); adding universe members; merging, splitting or rejecting across the universe; Wikidata search; editing rules files other than positions and scope; wiki export; history branches. Write "needs the person" in the checklist and move on.

## Part 3. The checklist (how to keep it)

1. At the start, ask the person where to keep it. If they do not say, create `CHECKLIST-<subject>.md` in the folder you are working in, not inside the archive.
2. Create it by copying the block below. Fill in the header.
3. After every step, use the Edit tool to change `[ ]` to `[x]` on that line and add the result after `=>` (a count, a name, "skipped, small"). Do this before starting the next step.
4. If a step is blocked, change `[ ]` to `[!]`, write the reason after `=>`, stop, and tell the person.
5. When you finish or stop, tell the person the path to the file and what is ticked.

```markdown
# Checklist: <subject>
Archive: <full path>    Collection: <name>    Started: <date>    Agent: <name>

## A. Before
- [ ] A1 labelling_guidelines read =>
- [ ] A2 wiki_readiness baseline saved => (write the counts)
- [ ] A3 scope / vocabularies / keys noted =>

## B. Subject: <name> (repeat this block per subject)
- [ ] B1 source read to the end => (id / file)
- [ ] B2 find_entities done for every name =>
- [ ] B3 records written on paper =>
- [ ] B4 check_records: 0 errors, warnings explained =>
- [ ] B5 preview (or "skipped, small") =>
- [ ] B6 save =>
- [ ] B7 get_records matches the source =>
- [ ] B8 stubs dealt with =>

## C. Pages
- [ ] C1 universe_build => (counts)
- [ ] C2 open_questions: all answered or handed to the person =>
- [ ] C3 wiki_readiness compared; every difference explained =>
- [ ] C4 scope: researched entities are in scope =>
- [ ] C5 read_page on every new entry =>
- [ ] C6 wiki_serve ok =>

## D. Finish
- [ ] D1 outside ids pinned (or "none given") =>
- [ ] D2 images linked (or "none given") =>
- [ ] D3 publish confirmed by the person =>

## Stopped / blocked
(date, step, reason, what the person must decide)
```
