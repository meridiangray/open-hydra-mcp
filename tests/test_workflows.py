"""MCP workflows, guides, tracked tasks, sources discovery, PDF page ranges, geo/cite verification, and CLI-parity tools."""
import hashlib
import json

import pytest

from hydra import citations as hcitations, layout
from hydra_mcp import core, server


def _pdf_pages(*pages: str) -> bytes:
    """Minimal multi-page PDF with Helvetica text on each page."""
    # Objects: 1=Catalog, 2=Pages, 3=Font, then 2 objs per page (Page, Stream)
    n = len(pages)
    page_ids = [4 + 2 * i for i in range(n)]
    font_id = 3
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + b" ".join(f"{pid} 0 R".encode() for pid in page_ids) + f"] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        pid = page_ids[i]
        sid = pid + 1
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {sid} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


def test_guide_tool_and_resources(arch):
    toc = server.guide()
    topics = [g["topic"] for g in toc["guides"]]
    assert topics[0] == "start"
    assert {"rules", "fields", "tools", "tasks", "views", "workflow/places", "views/map"} <= set(topics)

    sec = server.guide("workflow/places", section="G")
    assert sec["section"].startswith("G.") and "geo_resolve" in sec["content"] and "Stop if" in sec["content"]

    tools_doc = server.guide("tools")["content"]
    assert "## Every tool" in tools_doc
    for name in ("sources", "view_check", "task_checkout", "task_step"):
        assert f"`{name}`:" in tools_doc

    assert server.guide("records")["call"] == "labelling_guidelines"
    assert "quote" in server.guide_resource("rules").lower()
    assert "## G." in server.guide_nested_resource("workflow", "places")


def test_sources_tool_get_records_and_pdf_page_ranges(arch, tmp_path):
    pdf_path = tmp_path / "briefing.pdf"
    pdf_path.write_bytes(_pdf_pages("Port Authority signed contract.", "Dana Hale lives in Riyadh."))

    read_res = server.read_file(str(pdf_path), archive=str(arch))
    assert "Port Authority" in read_res["text"] and "Dana Hale" in read_res["text"]
    ranges = read_res["page_ranges"]
    assert [r["page"] for r in ranges] == [1, 2]
    assert "Port Authority" in read_res["text"][ranges[0]["start"]:ranges[0]["end"]]
    assert "Dana Hale" in read_res["text"][ranges[1]["start"]:ranges[1]["end"]]

    saved = server.save(
        [
            {"schema": "PublicBody", "properties": {"name": "Port Authority"}},
            {"schema": "Person", "properties": {"name": "Dana Hale"}},
        ],
        source={"file": str(pdf_path), "title": "Briefing PDF", "url": "https://example.org/briefing.pdf"},
        collection="main",
        archive=str(arch),
    )
    assert saved["saved"]

    # Add an uncited non-Wikipedia kept source directly in sources/entries
    uncited_id = f"doc-{hashlib.sha1(b'uncited-note').hexdigest()[:12]}"
    (arch / layout.SOURCE_ENTRIES / "extra.json").write_text(
        json.dumps([{
            "id": uncited_id,
            "schema": "Article",
            "properties": {
                "title": ["Field Memo"],
                "bodyText": ["Harbor warehouse was built in 1998."],
                "sourceUrl": ["https://example.org/memo"],
            },
        }]),
        encoding="utf-8",
    )

    all_src = server.sources(archive=str(arch))
    by_id = {s["source_id"]: s for s in all_src["sources"]}
    assert uncited_id in by_id
    assert by_id[uncited_id]["has_text"] and by_id[uncited_id]["uncited"]
    assert uncited_id in all_src["uncited_sources"]

    only_uncited = server.sources(uncited_only=True, archive=str(arch))
    assert [s["source_id"] for s in only_uncited["sources"]] == [uncited_id]

    filtered = server.sources(query="Memo", archive=str(arch))
    assert [s["source_id"] for s in filtered["sources"]] == [uncited_id]

    with pytest.raises(ValueError, match="sources"):
        server.get_records("extra", archive=str(arch))


def test_cite_verbatim_and_site_provenance_and_geo_report_entities(arch, tmp_path):
    assert "geo" in (server.geo_enable(confirm=True, archive=str(arch)).get("note") or "")

    txt = tmp_path / "dossier.txt"
    txt.write_text(
        "Bandar bin Sultan was born in Taif.\n"
        "Desert Holdings keeps an office at King Fahd Rd, Riyadh.\n"
        "The summit met in Jeddah in 2020.\n",
        encoding="utf-8",
    )
    s1 = server.save(
        [
            {"id": "per1", "schema": "Person", "properties": {"name": "Bandar bin Sultan", "birthPlace": "Taif", "country": "sa"}},
            {"id": "pa1", "schema": "PublicBody", "properties": {"name": "Port Authority", "country": "sa"}},
            {"id": "pos1", "schema": "Position", "properties": {"name": "Director", "organization": "pa1"}},
            {"id": "occ1", "schema": "Occupancy", "properties": {"holder": "per1", "post": "pos1"}},
            {"id": "co1", "schema": "Company", "properties": {"name": "Desert Holdings", "address": "King Fahd Rd, Riyadh", "country": "sa"}},
            {"id": "own1", "schema": "Ownership", "properties": {"owner": "per1", "asset": "co1"}},
            {"id": "evt1", "schema": "Event", "properties": {"name": "Jeddah Summit", "location": "Jeddah", "involved": "co1"}},
            {"id": "ves1", "schema": "Vessel", "properties": {"name": "MV Horizon", "registrationPort": "Jeddah Port"}},
        ],
        source={"file": str(txt), "title": "Regional Dossier", "url": "https://example.org/dossier"},
        collection="main",
        archive=str(arch),
    )
    assert s1["saved"], s1["errors"]
    sid = json.loads((arch / layout.SOURCE_ENTRIES / "main.json").read_text(encoding="utf-8"))[0]["id"]

    rep = server.geo_report(include_entities=True, archive=str(arch))
    assert rep["place_references"] >= 4
    props = {item["prop"] for item in rep["place_reference_items"]}
    assert {"birthPlace", "address", "location", "registrationPort"} <= props
    assert rep["country_only_entities"] and rep["unplaced_entities"]

    # cite: rejects non-verbatim quote even if confirm=True
    bad_cite = server.cite(
        [{"record": "case:per1", "source": sid, "pages": "1", "quote": "Invented sentence not in dossier."}],
        confirm=True,
        archive=str(arch),
    )
    assert bad_cite["errors"] and not (arch / hcitations.PATH).exists()

    good_cite = server.cite(
        [{"record": "case:per1", "source": sid, "pages": "1", "quote": "Bandar bin Sultan was born in Taif."}],
        confirm=True,
        archive=str(arch),
    )
    assert not good_cite["errors"] and good_cite["written"] == 1

    # cite: `sources` says what a kept source is (reader fields), previewed first; machine fields are refused
    fields = {"source": sid, "author": "Staff", "publisher": "The Gazette", "published": "2020-05-01",
              "summary": "A dossier on Saudi officials.", "keywords": ["saudi", "dossier"]}
    shown = server.cite(sources=[fields], archive=str(arch))
    assert not shown["errors"] and shown["sources"][0]["after"]["publishedAt"] == ["2020-05-01"]
    assert "author" not in json.loads((arch / layout.SOURCE_ENTRIES / "main.json").read_text(encoding="utf-8"))[0]["properties"]
    assert server.cite(sources=[{"source": sid, "contentHash": "x"}], archive=str(arch))["errors"]
    assert server.cite(sources=[{"source": sid, "published": "soon"}], archive=str(arch))["errors"]
    done = server.cite(sources=[fields], confirm=True, archive=str(arch))
    assert not done["errors"] and done["written"] == 0
    props = json.loads((arch / layout.SOURCE_ENTRIES / "main.json").read_text(encoding="utf-8"))[0]["properties"]
    assert props["author"] == ["Staff"] and props["publisher"] == ["The Gazette"] and props["keywords"] == ["saudi", "dossier"]
    assert props["summary"] == ["A dossier on Saudi officials."] and "contentHash" in props

    # site: pre-validates dates and verbatim notes when sources are supplied
    bad_date = server.site(
        [{"entity": "case:co1", "location": {"point": [46.72, 24.63]}, "startDate": "bad-date"}],
        confirm=True,
        archive=str(arch),
    )
    assert bad_date["errors"] and bad_date["written"] == 0

    bad_note = server.site(
        [{
            "entity": "case:co1",
            "location": {"point": [46.72, 24.63]},
            "sources": [sid],
            "notes": "Not actually written in the file.",
        }],
        confirm=True,
        archive=str(arch),
    )
    assert bad_note["errors"] and bad_note["written"] == 0

    ok_site = server.site(
        [{
            "entity": "case:co1",
            "location": {"point": [46.72, 24.63]},
            "precision": "approximate",
            "radius": 150,
            "role": "seat",
            "startDate": "2020",
            "sources": [sid],
            "pages": "1",
            "notes": "Desert Holdings keeps an office at King Fahd Rd, Riyadh.",
        }],
        confirm=True,
        archive=str(arch),
    )
    assert not ok_site["errors"] and ok_site["written"] >= 2
    geolink_rec = next(r for r in ok_site["records"] if r["schema"] == "GeoLink")
    assert "sources" not in geolink_rec["properties"]
    assert geolink_rec["properties"]["sourceUrl"] == ["https://example.org/dossier"]

    # read_page strips widget/tabbar/scripts/navboxes and includes geo for located entity
    ub = server.universe_build(archive=str(arch))
    assert ub["pages"] >= 1
    co_page = server.read_page("Desert Holdings", archive=str(arch))
    assert "Actions" not in co_page["lead"]
    assert "function" not in " ".join(s["text"] for s in co_page["sections"])
    assert co_page["geo"]["centroid"] == [46.72, 24.63]

    per_page = server.read_page("Bandar bin Sultan", archive=str(arch))
    assert "Actions" not in per_page["lead"]
    for s in [*co_page["sections"], *per_page["sections"]]:
        assert not s["heading"].endswith(" i") and "\n" not in s["heading"]      # the heading's tooltip mark is not its text
    for s in per_page["sections"]:
        assert "Categories:" not in s["text"] and "function " not in s["text"]


def test_mcp_task_lifecycle_hooks_and_cli_parity_tools(arch, tmp_path):
    from hydra_mcp import workflows as wf
    assert "places" in {w["name"] for w in server.workflows(archive=str(arch))["workflows"]}

    note_file = tmp_path / "src.txt"
    note_file.write_text("Al-Faisal Foundation operated in Jeddah.", encoding="utf-8")
    server.geo_enable(confirm=True, archive=str(arch))
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("Seed Org is an organization.", encoding="utf-8")
    server.save([{"schema": "Organization", "properties": {"name": "Seed Org"}}],
                source={"file": str(seed_file), "title": "Seed"}, collection="main", archive=str(arch))

    pre = server.task_new("Place Jeddah", workflow="places", collection="main", views=["map"],
                          authorized=["site"], archive=str(arch))
    assert not pre["written"] and pre["authorized"] == ["site"]
    created = server.task_new("Place Jeddah", workflow="places", collection="main", views=["map"],
                              authorized=["site"], context="general", confirm=True, archive=str(arch))
    tid = created["id"]
    assert created["written"] and any(t["id"] == tid for t in server.tasks(archive=str(arch))["tasks"])

    # this session's holder is its own; a second session (another holder name) is refused
    co = server.task_checkout(tid, holder="one", archive=str(arch))
    assert co["holder"] == "one" and co["archive_details"]["name"] == "case"
    assert co["next_step"]["code"] == "G1" and co["next_step"]["tool"] == "geo_report" and co["guides_to_load"]
    from hydra import tasks as htasks
    with pytest.raises(htasks.TaskError, match="already checked out"):
        htasks.checkout_task(arch, tid, holder="agent:two")

    # writes and kept sources attach to the session's task
    saved = server.save(
        [{"schema": "Organization", "properties": {"name": "Al-Faisal Foundation", "country": "sa"}}],
        source={"file": str(note_file), "title": "Foundation Brief"}, collection="main2", archive=str(arch))
    assert saved["saved"]
    sid = json.loads((arch / layout.SOURCE_ENTRIES / "main2.json").read_text(encoding="utf-8"))[0]["id"]
    t_state = server.task(archive=str(arch))
    assert sid in t_state["sources"] and any("save main2" in line for line in t_state["log"])

    # steps: the session's holder is used; result required; unknown evidence refused; na is a skip
    with pytest.raises(ValueError, match="result"):
        server.task_step("G1", archive=str(arch))
    with pytest.raises(ValueError, match="unknown archive ID"):
        server.task_step("G1", result="checked", evidence=["doc-missing999"], archive=str(arch))
    step1 = server.task_step("G1", result="1 org known only by a country", evidence=[sid], archive=str(arch))
    assert step1["updated_step"]["status"] == "done"
    assert server.task_step("G2", status="na", reason="no stated places",
                            archive=str(arch))["updated_step"]["status"] == "skipped"
    added = server.task_add(step="Double check port coordinates", code="CUSTOM1", archive=str(arch))
    assert any(s["code"] == "CUSTOM1" for s in added["steps"])

    # view and orientation tools
    server.set_collection_views("main", {"map": True, "org": True}, confirm=True, archive=str(arch))
    colls = {c["collection"]: c for c in server.collections(archive=str(arch))["collections"]}
    assert colls["main"]["views"]["map"] and colls["main"]["views"]["org"]
    assert server.view_check("map", "main", archive=str(arch))["view"] == "map"
    assert server.tree(format="json", archive=str(arch))["roots"] >= 1
    assert "unplaced_titles" in server.positions(archive=str(arch))
    assert "rules" in server.badges(archive=str(arch))
    assert server.details(archive=str(arch))["name"] == "case"
    assert "issues" in server.check(archive=str(arch))

    ver = server.task_verify(archive=str(arch))
    assert not ver["ready_to_close"] and ver["counts"]["open"] > 0
    with pytest.raises(ValueError, match="open step"):
        server.task_close(archive=str(arch))

    # release, then take it back in this session and finish
    assert server.task_release(archive=str(arch))["status"] == "open"
    server.task_checkout(tid, archive=str(arch))
    for s in server.task(tid, archive=str(arch))["steps"]:
        if s["status"] == "open":
            server.task_step(s["code"], status="skipped", reason="test pass", id=tid, archive=str(arch))
    closed = server.task_close(summary="All checks completed.", id=tid, archive=str(arch))
    assert closed["closed"] and closed["changes_since_start"] is not None
    diff = server.history_diff(f"task/{tid}/start", f"task/{tid}/done", archive=str(arch))
    assert isinstance(diff, list) and len(diff) >= 1


def test_mcp_holder_default_and_write_lock_busy(tmp_path, monkeypatch):
    import asyncio
    from hydra import writelock
    from hydra.cli import init as hinit
    from hydra_mcp import server, workflows as wf
    monkeypatch.delenv("HYDRA_HOLDER", raising=False)
    arch = tmp_path / "case"
    hinit.create(arch, name="case", prefix="c")
    h = wf._holder(arch)
    assert h.endswith(f"·{wf.SESSION}") and "agent:" not in h and wf._holder(arch, "me") == "me"
    # a read tool passes; a confirm=true tool waits for a lock held elsewhere, then answers busy
    monkeypatch.setattr(writelock, "WAIT", 0.2)
    import threading
    out = {}

    def other():
        out["r"] = asyncio.run(server.mcp._tool_manager.call_tool("set_scope", {"archive": str(arch), "confirm": True}))
    with writelock.hold(arch, "someone-else"):
        t = threading.Thread(target=other)
        t.start()
        t.join()
    assert out["r"]["error"] == "busy" and out["r"]["do"] == "try again"


# ---- contexts, routes, exits (wave A, part C) -------------------------------------------

def _ctx_task(arch, **kw):
    made = server.task_new("Ctx test", confirm=True, archive=str(arch), **kw)
    assert made["written"]
    return made["id"]


def test_contexts_tool_lists_and_ranks(arch):
    plain = server.contexts(archive=str(arch))
    names = [c["name"] for c in plain["contexts"]]
    assert names[0] == "general" and {"incident", "government", "assets"} <= set(names)
    assert all(c["use_when"] for c in plain["contexts"])
    tid = _ctx_task(arch, workflow="enrich")
    ranked = server.contexts(task=tid, words="arrest and indictment, a leak", archive=str(arch))["contexts"]
    assert ranked[0]["name"] == "incident" and ranked[-1]["name"] == "general" and ranked[0]["why"]


def test_context_checkout_previews_then_sets_and_is_fixed_after_a_write(arch):
    from hydra import tasks as htasks
    tid = _ctx_task(arch, workflow="enrich")
    pre = server.context_checkout(tid, "incident", "arrest report", archive=str(arch))
    assert pre["written"] is False and pre["context"]["name"] == "incident"
    assert not htasks.get_task(arch, tid).get("context")
    done = server.context_checkout(tid, "incident", "arrest report", confirm=True, archive=str(arch))
    assert done["context"] == "incident" or done["context"].get("name") == "incident"
    server.task_checkout(tid, holder="one", archive=str(arch))
    step = server.task(id=tid, archive=str(arch))["next_step"]["code"]
    server.task_step(step, status="skipped", reason="test", archive=str(arch))
    with pytest.raises(Exception, match="fixed after the first write"):
        server.context_checkout(tid, "general", "changed my mind", confirm=True, archive=str(arch))


def test_context_checkout_refuses_an_empty_reason_and_unknown_name(arch):
    tid = _ctx_task(arch, workflow="enrich")
    with pytest.raises(Exception):
        server.context_checkout(tid, "incident", "", archive=str(arch))
    with pytest.raises(Exception):
        server.context_checkout(tid, "nonesuch", "why", archive=str(arch))


def test_task_new_with_a_route_and_a_context(arch):
    pre = server.task_new("Route", workflow=["enrich", "close-out"], context="general", archive=str(arch))
    assert pre["written"] is False and list(pre["route"]) == ["enrich", "close-out"]
    tid = _ctx_task(arch, workflow=["enrich", "close-out"], context="general")
    got = server.task(id=tid, archive=str(arch))
    codes = [s["code"] for s in got["steps"]] if "steps" in got else []
    assert any(c.startswith("1.") for c in codes) and any(c.startswith("2.") for c in codes)


def test_checkout_gives_a_brief_or_needs_context(arch):
    with_ctx = _ctx_task(arch, workflow="enrich", context="general")
    out = server.task_checkout(with_ctx, holder="one", archive=str(arch))
    assert out["brief"] and "needs_context" not in out and out["next_step"]
    server.task_release(archive=str(arch))
    bare = _ctx_task(arch, workflow="enrich")
    out = server.task_checkout(bare, holder="one", model="m-1", client="test", archive=str(arch))
    assert out["needs_context"]["contexts"] and out["next_step"] is None and "context_checkout" in out["next"]
    assert server.task(id=bare, archive=str(arch))["model"] == "m-1"
    with pytest.raises(Exception, match="context"):
        server.task_step("A1", status="skipped", reason="x", archive=str(arch))


def test_a_long_brief_points_to_the_guide(arch, monkeypatch):
    from hydra_mcp import workflows as wf
    monkeypatch.setattr(wf, "BRIEF_MAX", 10)
    tid = _ctx_task(arch, workflow="enrich", context="incident")
    out = server.task_checkout(tid, holder="one", archive=str(arch))
    assert 'guide("context/incident")' in out["brief"] and len(out["brief"]) < 200


def test_task_step_records_an_exit(arch):
    tid = _ctx_task(arch, workflow="enrich", context="general")
    server.task_checkout(tid, holder="one", archive=str(arch))
    code = server.task(id=tid, archive=str(arch))["next_step"]["code"]
    server.task_step(code, status="skipped", reason="no key", exit="skip:no-key", archive=str(arch))
    text = next((arch / ".hydra" / "tasks").glob(f"{tid}*.md")).read_text(encoding="utf-8")
    assert "skip:no-key" in text
    with pytest.raises(Exception, match="exit"):
        server.task_step(server.task(id=tid, archive=str(arch))["next_step"]["code"], status="skipped",
                         reason="x", exit="bogus:1", archive=str(arch))


def test_the_context_guide_renders_and_is_listed(arch):
    g = server.guide("context/incident")
    assert g["topic"] == "context/incident" and "Keep" in g["content"] or "keep" in g["content"].lower()
    assert "context/incident" in [x["topic"] for x in server.guide()["guides"]]
    with pytest.raises(Exception):
        server.guide("context/nonesuch")
