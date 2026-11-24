"""The agent's loop after `save`: links by id, identity by pin, questions answered,
records corrected, ladders set, every change in history and undoable."""
import json

import pytest

from hydra.archive import history, layout, resources
from hydra.cli import main as cli
from hydra.universe import table
from hydra_mcp import agent, core

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    return core.open_archive(str(root))


def text(tmp_path, name, body):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return {"file": str(f)}


def persons(root, name):
    return [n for n in resources.declared_nodes(root).values() if n["caption"] == name and n["schema"] == "Person"]


def test_links_are_written_as_ids_and_namesakes_are_asked(archive, tmp_path):
    out = core.ingest(archive, [P("Person", name="Ann Lee", birthDate="1970"), P("Person", name="Ann Lee", birthDate="1990"),
                                P("Company", name="Lee Ltd"),
                                P("Directorship", director="Ann Lee", organization="Lee Ltd", role="director")],
                      text(tmp_path, "a.txt", "Ann Lee directs Lee Ltd."), "a")
    assert out["saved"] and len(out["ambiguous_links"]) == 1
    amb = out["ambiguous_links"][0]
    assert amb["value"] == "Ann Lee" and {c["facts"].get("birthDate", [None])[0] for c in amb["candidates"]} == {"1970", "1990"}
    stored = json.loads((archive / "collections/a.json").read_text(encoding="utf-8"))
    d = next(r for r in stored if r["schema"] == "Directorship")
    company = next(r for r in stored if r["schema"] == "Company")
    assert d["properties"]["organization"] == [company["id"]] and d["properties"]["director"] == ["Ann Lee"]
    assert len(persons(archive, "Ann Lee")) == 2                       # two people, never merged by name


def test_a_known_entity_is_joined_by_its_h_not_its_name(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Bo Grant", birthDate="1960")], text(tmp_path, "a.txt", "Bo Grant."), "a")
    found = agent.find_entities(archive, "Bo Grant", "Person")
    h = found[0]["h"]
    assert h.startswith("H-c0-") and found[0]["facts"]["birthDate"] == ["1960"]
    chk = core.check_records(archive, [P("Person", name="Bo Grant")])
    assert any("upstream" in w and h in w for w in chk["warnings"])     # the pin is suggested, not assumed
    out = core.ingest(archive, [P("Person", name="Bo Grant", nationality="gb", upstream=[h])],
                      text(tmp_path, "b.txt", "Bo Grant is British."), "b")
    assert out["saved"]
    (bo,) = persons(archive, "Bo Grant")                                # one entity
    assert bo["props"]["nationality"] == ["gb"] and bo["props"]["birthDate"] == ["1960"]
    assert table.load(archive)[h[-12:]]["state"] == "p"                 # a pinned H is published
    assert [s["author"] for s in history.log(archive)][:2] == ["agent:hydra-mcp", "agent:hydra-mcp"]


def test_questions_are_answered_only_when_confirmed(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Cy Vale")], text(tmp_path, "a.txt", "Cy Vale."), "a")
    core.ingest(archive, [P("Person", name="Cy Vale", birthDate="1970")], text(tmp_path, "b.txt", "Cy Vale, 1970."), "b")
    q = agent.open_questions(archive, "merges")
    (merge,) = q["questions"]
    assert "Cy Vale" in merge["ask"] and q["counts"]["merges"] == 1
    pre = agent.answer(archive, merge["id"], "confirm")
    assert "next" in pre and len(persons(archive, "Cy Vale")) == 2       # a preview writes nothing
    done = agent.answer(archive, merge["id"], "confirm", confirm=True)
    assert done["snapshot"] and len(persons(archive, "Cy Vale")) == 1
    why = agent.explain_entity(archive, persons(archive, "Cy Vale")[0]["id"])
    assert why["values"]["birthDate"]["1970"][0]["collection"] == "b"


def test_amend_and_undo(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Di Moss", gender="male"), P("Person", name="Ed Rowe")],
                text(tmp_path, "a.txt", "Di Moss and Ed Rowe."), "a")
    stored = json.loads((archive / "collections/a.json").read_text(encoding="utf-8"))
    di = next(r for r in stored if r["properties"]["name"] == ["Di Moss"])
    ed = next(r for r in stored if r["properties"]["name"] == ["Ed Rowe"])
    out = agent.amend_records(archive, "a", [{"id": di["id"], "schema": "Person",
                                              "properties": {"name": ["Di Moss"], "gender": ["female"]}}],
                              remove=[ed["id"]])
    assert out["saved"] and out["changed"] == [di["id"]] and out["removed"] == [ed["id"]]
    now = json.loads((archive / "collections/a.json").read_text(encoding="utf-8"))
    assert len(now) == 1 and now[0]["properties"]["gender"] == ["female"] and now[0]["properties"]["sources"]
    diff = agent.history_diff(archive, "HEAD~1", "HEAD")
    assert diff[0]["records"]["removed"] == [ed["id"]] and diff[0]["records"]["changed"] == [di["id"]]
    assert "next" in agent.history_restore(archive, "HEAD~1")
    agent.history_restore(archive, "HEAD~1", confirm=True)
    assert len(json.loads((archive / "collections/a.json").read_text(encoding="utf-8"))) == 2


def test_a_collection_in_json_lines_is_read_and_amended_in_kind(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Fay Kerr", birthDate="c. 1748"), P("Person", name="Gil Pratt")],
                text(tmp_path, "a.txt", "Fay Kerr and Gil Pratt."), "a")
    f = archive / "collections/a.json"
    stored = json.loads(f.read_text(encoding="utf-8"))
    fay = next(r for r in stored if r["properties"]["name"] == ["Fay Kerr"])
    gil = next(r for r in stored if r["properties"]["name"] == ["Gil Pratt"])
    assert fay["properties"]["birthDate"] == ["1748"] and fay["_meta"] == {"approx": {"birthDate": "circa"}}
    f.write_text("".join(json.dumps(r) + "\n" for r in stored), encoding="utf-8")    # as `import` writes one
    assert core.get_records(archive, "a")["records"] == 2
    assert any("already used" in e for e in core.check_records(archive, [{"id": gil["id"], **P("Person", name="X")}])["errors"])
    out = agent.amend_records(archive, "a", [{"id": gil["id"], "schema": "Person",
                                              "properties": {"name": ["Gil Pratt"], "gender": ["male"]}}])
    assert out["saved"]
    now = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]   # still one per line
    fay_now = next(r for r in now if r["id"] == fay["id"])
    assert fay_now["_meta"] == {"approx": {"birthDate": "circa"}}                  # the untouched record keeps its "c."
    assert not any("cites" in (r.get("_meta") or {}) for r in now)


def test_preview_builds_aside(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Fay Nolan", idNumber="77")], text(tmp_path, "a.txt", "Fay."), "a")
    before = (archive / "collections").glob("*.json")
    pre = agent.preview(archive, [P("Person", name="F. Nolan", idNumber="77"), P("Person", name="Gil Hart")])
    assert pre["ok"] and pre["entities"]["new"] == ["Gil Hart"] and len(pre["would_merge"]) == 1
    assert sorted(p.name for p in (archive / "collections").glob("*.json")) == sorted(p.name for p in before)


def test_set_positions_previews_what_it_ranks(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Hal Ames"), P("Company", name="Ames Co"),
                          P("Directorship", director="Hal Ames", organization="Ames Co", role="chairman")],
                text(tmp_path, "a.txt", "Hal Ames chairs Ames Co."), "a")
    ladder = {"Chair": {"titles": ["chairman"]}, "Director": {"below": ["Chair"], "titles": ["director"]}}
    pre = agent.set_positions(archive, ladder)
    assert pre["roles_ranked"]["Chair"] == 1 and not (archive / layout.POSITIONS).read_text(encoding="utf-8").count("Chair")
    done = agent.set_positions(archive, ladder, confirm=True)
    assert "Chair" in (archive / layout.POSITIONS).read_text(encoding="utf-8") and done["snapshot"]


def test_decisions_list_what_was_answered_and_clear_takes_it_back(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Di Moss")], text(tmp_path, "a.txt", "Di Moss."), "a")
    core.ingest(archive, [P("Person", name="Di Moss", birthDate="1981")], text(tmp_path, "b.txt", "Di Moss, 1981."), "b")
    (merge,) = agent.open_questions(archive, "merges")["questions"]
    assert agent.decisions(archive)["count"] == 0
    agent.answer(archive, merge["id"], "confirm", confirm=True)
    (d,) = agent.decisions(archive)["decisions"]
    assert d["kind"] == "merge" and d["answer"] == "The same entity" and "Di Moss" in d["question"]
    assert agent.decisions(archive, "place")["count"] == 0
    with pytest.raises(core.IngestError):
        agent.decisions(archive, "nonsense")
    agent.answer(archive, d["id"], "clear", confirm=True)
    assert agent.decisions(archive)["count"] == 0 and len(persons(archive, "Di Moss")) == 2


def test_symbology_reads_and_sets_a_link_colour_only_when_confirmed(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Ed Pike"), P("Company", name="Pike Ltd"),
                          P("Directorship", director="Ed Pike", organization="Pike Ltd", role="director")],
                text(tmp_path, "a.txt", "Ed Pike directs Pike Ltd."), "a")
    s = agent.symbology(archive)
    assert {t["key"] for t in s["types"]} >= {"Person", "Company"} and s["icons"]
    assert not any("svg" in i for i in s["icons"])                      # tokens, not pictures
    with pytest.raises(core.IngestError):
        agent.set_symbology(archive, "link-colour", "Directorship", "red")
    with pytest.raises(core.IngestError):
        agent.set_symbology(archive, "type-icon", "Person", "no-such-icon")
    conf = archive / "wiki.yaml"
    said = lambda: conf.read_text(encoding="utf-8") if conf.is_file() else ""
    pre = agent.set_symbology(archive, "link-colour", "Directorship", "#aa3300")
    assert "next" in pre and pre["to"] == "#aa3300" and "aa3300" not in said()      # a preview writes nothing
    done = agent.set_symbology(archive, "link-colour", "Directorship", "#aa3300", confirm=True)
    assert "link_colours" in done["written"]
    assert next(x for x in agent.symbology(archive)["links"] if x["key"] == "Directorship")["colour"] == "#aa3300"
    assert history.log(archive)[0]["author"] == "agent:hydra-mcp"


def test_save_changes_previews_then_saves(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Di Moss")], text(tmp_path, "s.txt", "Di Moss."), "a")
    prev = agent.save_changes(archive, "Add Di Moss")
    assert "next" in prev and prev["steps"] >= 1 and any(e["name"] == "Di Moss" for e in prev["entities"])
    from hydra.archive import history
    assert history.last_save(archive) is None
    done = agent.save_changes(archive, "Add Di Moss", "from s.txt", confirm=True)
    s = history.snap(archive, done["saved"])
    assert s["kind"] == "save" and s["author"].startswith("agent:hydra-mcp") and s["fields"]["description"] == "from s.txt"


def test_open_ends_list_candidates_and_an_answer_is_a_judgement_not_an_endDate(archive, tmp_path):
    core.ingest(archive, [P("Person", name="Ann Lee", birthDate="1930", deathDate="1999-05"),
                          P("Person", name="Ben Roe", birthDate="1950"), P("Position", name="Chair of Lee Ltd"),
                          P("Occupancy", holder="Ann Lee", post="Chair of Lee Ltd", startDate="1980"),
                          P("Occupancy", holder="Ben Roe", post="Chair of Lee Ltd", startDate="1990")],
                text(tmp_path, "a.txt", "Ann Lee chaired Lee Ltd from 1980; Ben Roe from 1990."), "a")
    got = agent.open_ends(archive)
    ann = next(x for x in got["open_ends"] if x["who"] == "Ann Lee")
    assert {c["kind"] for c in ann["candidates"]} == {"death", "successor"} and ann["answers"] == ["holds", "unknown"]
    assert {x["who"] for x in agent.open_ends(archive, "Ben Roe")["open_ends"]} == {"Ben Roe"}
    with pytest.raises(core.IngestError):
        agent.open_ends(archive, "Nobody")
    death = next(c for c in ann["candidates"] if c["kind"] == "death")["choice"]
    pre = agent.answer(archive, ann["id"], death)                        # the existing answer tool takes the end- key
    assert pre["writes"][ann["id"]]["end"] == "1999-05" and "next" in pre
    assert not any(k.startswith("end-") for k in (archive / layout.VERDICTS).read_text(encoding="utf-8").split())
    agent.answer(archive, ann["id"], death, confirm=True)
    assert all(x["who"] != "Ann Lee" for x in agent.open_ends(archive)["open_ends"])
    (d,) = [r for r in agent.decisions(archive, "end")["decisions"]]
    assert d["answer"] == "Until 1999-05"
    pages = resources.read_jsonl(archive / layout.UNIVERSE_PARSED / "pages.jsonl")
    rel = next(r for p in pages if p["title"] == "Ann Lee" for r in p["relations"] if r["edge"] == "Occupancy")
    assert rel["inferred"]["endDate"] == "1999-05" and "endDate" not in rel
    agent.answer(archive, ann["id"], "clear", confirm=True)
    assert any(x["who"] == "Ann Lee" for x in agent.open_ends(archive)["open_ends"])
