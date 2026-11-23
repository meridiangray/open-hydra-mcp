"""CN1: a stale server says so, per-field basis, pages from page_ranges, `sources` without the flood, both argument shapes."""
import asyncio
import json

import pytest

from hydra_mcp import agent, core, server, sources, stale, workflows as wf

P = lambda s, **p: {"schema": s, "properties": p}


def _raw(name, args):
    r = asyncio.run(server.mcp.call_tool(name, args))
    return r


def call(name, args):
    """The structured answer of a tool (or its error payload, read from the text)."""
    r = _raw(name, args)
    if isinstance(r, tuple):
        return r[1]
    return json.loads(r[0].text) if isinstance(r, list) else r


def text_of_call(name, args):
    r = _raw(name, args)
    blocks = r[0] if isinstance(r, tuple) else getattr(r, "content", r)
    return json.loads(blocks[0].text)


def pdf2(*pages: str) -> bytes:
    """A PDF with one line of text on each page."""
    n = len(pages)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(n)) + f"] /Count {n} >>").encode()]
    for i, t in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> >>".encode())
        stream = f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET".encode()
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(tmp_path / "reg"))
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


@pytest.fixture
def saved(archive, tmp_path):
    f = tmp_path / "memo.pdf"
    f.write_bytes(pdf2("Dana Hale joined the Port Authority in 1999.", "Rob Kerr became her deputy in 2004."))
    out = core.ingest(archive, [P("Person", name="Dana Hale"), P("Person", name="Rob Kerr", birthDate="1970")],
                      {"file": str(f)}, "memo")
    assert out["saved"], out
    recs = json.loads((archive / "collections/memo.json").read_text())
    sid = json.loads((archive / ".hydra/sources/entries/memo.json").read_text())[0]["id"]
    return archive, sid, {r["properties"]["name"][0]: r["id"] for r in recs}


# ---- G8

def test_a_stale_server_refuses_writes_and_warns_on_reads(archive, monkeypatch):
    monkeypatch.setattr(stale, "current_id", lambda: "changed-on-disk")
    monkeypatch.setattr(stale, "_last", [0.0, None])
    w = text_of_call("save", {"records": [P("Person", name="Ann")], "archive": str(archive)})
    assert w["error"] == "stale server" and "changed after this server started" in w["why"]
    assert "reconnect" in w["do"] and "nothing was changed" in w["do"]
    assert not list((archive / "collections").glob("*.json"))
    assert text_of_call("details", {"archive": str(archive)})["error"] == "stale server"
    assert text_of_call("preview", {"records": [], "archive": str(archive)})["error"] == "stale server"
    assert text_of_call("save_changes", {"message": "x", "confirm": True, "archive": str(archive)})["error"] == "stale server"
    r = text_of_call("keys", {"archive": str(archive)})            # read-only: answers, with a warning
    assert "error" not in r and "changed after this server started" in r["warning"]
    assert "changed after" in call("keys", {"archive": str(archive)})["warning"]


def test_a_current_server_adds_nothing(archive, monkeypatch):
    monkeypatch.setattr(stale, "_last", [0.0, None])
    assert "warning" not in text_of_call("keys", {"archive": str(archive)})


def test_the_code_id_is_cheap_and_stable():
    import time
    stale.current_id()
    t = time.time()
    for _ in range(5):
        assert stale.current_id() == stale.LOADED
    assert (time.time() - t) / 5 < 0.5


# ---- G3

def test_basis_is_checked_and_kept_as_meta(archive):
    ok = {"schema": "Person", "properties": {"name": ["Ann"], "birthDate": ["1950"]}, "basis": {"birthDate": "recalled"}}
    assert core.check_records(archive, [ok])["ok"]
    for bad, word in (({"birthDate": "believed"}, "not a state"), ({"deathDate": "recalled"}, "no property 'deathDate'")):
        rep = core.check_records(archive, [{**ok, "basis": bad}])
        assert not rep["ok"] and any(word in e for e in rep["errors"]), rep["errors"]
    assert not core.check_records(archive, [{**ok, "basis": "recalled"}])["ok"]
    plain = {k: v for k, v in ok.items() if k != "basis"}
    via_meta = core.check_records(archive, [{**plain, "_meta": {"basis": {"birthDate": "nope"}}}])
    assert not via_meta["ok"] and any("not a state" in e for e in via_meta["errors"])
    out = core.ingest(archive, [ok], {"text": "Ann was born in 1950.", "title": "t"}, "c")
    assert out["saved"], out
    rec = json.loads((archive / "collections/c.json").read_text())[0]
    assert rec["_meta"]["basis"] == {"birthDate": "recalled"} and "basis" not in rec
    bad = core.ingest(archive, [{**ok, "basis": {"birthDate": "zzz"}}], {"text": "Ann was born in 1950.", "title": "t2"}, "d")
    assert not bad["saved"] and bad["errors"]
    assert agent.preview(archive, [{**ok, "basis": {"birthDate": "zzz"}}])["ok"] is False


def test_amend_records_sets_and_keeps_basis(archive):
    core.ingest(archive, [P("Person", name="Ann", birthDate="1950")], {"text": "Ann was born in 1950.", "title": "t"}, "c")
    rec = json.loads((archive / "collections/c.json").read_text())[0]
    new = {"id": rec["id"], "schema": "Person", "properties": {"name": ["Ann"], "birthDate": ["1950"]},
           "basis": {"birthDate": "estimated"}}
    assert agent.amend_records(archive, "c", [new], confirm=False)["saved"] is False
    done = agent.amend_records(archive, "c", [new], confirm=True)
    assert done["saved"], done
    assert json.loads((archive / "collections/c.json").read_text())[0]["_meta"]["basis"] == {"birthDate": "estimated"}
    more = {"id": rec["id"], "schema": "Person", "properties": {"name": ["Ann"], "birthDate": ["1950"], "gender": ["female"]}}
    assert agent.amend_records(archive, "c", [more], confirm=True)["saved"]
    assert json.loads((archive / "collections/c.json").read_text())[0]["_meta"]["basis"] == {"birthDate": "estimated"}
    bad = agent.amend_records(archive, "c", [{**new, "basis": {"gender": "nope"}}], confirm=True)
    assert bad["saved"] is False and bad["errors"]


def test_the_fields_guide_describes_basis():
    from hydra import guides
    text = guides.read_guide("fields", None, None)["content"]
    assert '"basis"' in text and "recalled" in text


# ---- G7

def test_read_source_gives_page_ranges_for_a_pdf(saved):
    archive, sid, _ = saved
    out = sources.read(archive, sid)
    assert [r["page"] for r in out["page_ranges"]] == [1, 2]
    assert out["text"][out["page_ranges"][1]["start"]:].startswith("Rob Kerr")


def test_cite_fills_the_pdf_page_from_the_quote(saved):
    archive, sid, ids = saved
    rows = [{"record": ids["Dana Hale"], "source": sid, "quote": "joined the  Port Authority in 1999"},
            {"record": ids["Rob Kerr"], "source": sid, "quote": "became her deputy in 2004."}]
    pre = agent.cite(archive, rows)
    assert not pre["errors"] and [c["pdfPages"] for c in pre["citations"]] == ["1", "2"]
    assert all("pages" not in c for c in pre["citations"])          # this PDF prints no page numbers: nothing is guessed
    assert agent.cite(archive, rows, confirm=True)["written"] == 2
    from hydra import citations
    assert {v["pdfPages"] for v in citations.load(archive).values()} == {"1", "2"}
    assert {v["pages"] for v in citations.load(archive).values()} == {""}


def test_cite_fills_the_printed_page_when_it_is_known(saved, monkeypatch):
    archive, sid, ids = saved
    monkeypatch.setattr(sources, "page_labels_of", lambda root, s: {1: "I-16", 2: "I-17"})
    rows = [{"record": ids["Dana Hale"], "source": sid, "quote": "joined the  Port Authority in 1999"},
            {"record": ids["Rob Kerr"], "source": sid, "pages": "I-17"}]
    out = agent.cite(archive, rows)
    assert [(c.get("pages"), c.get("pdfPages")) for c in out["citations"]] == [("I-16", "1"), ("I-17", "2")]
    assert len(out["page_notes"]) == 2
    monkeypatch.setattr(sources, "page_labels_of", lambda root, s: {1: "5", 2: "5"})     # one number on two pages: not located
    out = agent.cite(archive, [{"record": ids["Rob Kerr"], "source": sid, "pages": "5"}])
    assert "pdfPages" not in out["citations"][0]


def test_cite_reports_a_quote_it_cannot_find_and_keeps_given_pages(saved):
    archive, sid, ids = saved
    out = agent.cite(archive, [{"record": ids["Dana Hale"], "source": sid, "quote": "never said this"}])
    assert out["errors"] and "pages" not in out["citations"][0]
    given = agent.cite(archive, [{"record": ids["Dana Hale"], "source": sid, "quote": "became her deputy", "pages": "9"}])
    assert given["citations"][0]["pages"] == "9" and given["citations"][0]["pdfPages"] == "2"


# ---- G13

def test_sources_lists_uncited_entities_only_when_asked(saved):
    archive, _, _ = saved
    out = sources.list_sources(archive, "memo")
    assert "uncited_entities" not in out and isinstance(out["uncited_entities_count"], int)
    assert "uncited_entities" in sources.list_sources(archive, "memo", uncited_entities=True)
    assert "uncited_entities" not in call("sources", {"archive": str(archive)})
    assert "uncited_entities" in call("sources", {"archive": str(archive), "uncited_entities": True})


# ---- G15

def test_views_take_a_map_or_a_list(saved):
    archive, _, _ = saved
    a = call("set_collection_views", {"collection": "memo", "views": ["org", "map"], "archive": str(archive)})
    b = call("set_collection_views", {"collection": "memo", "views": {"org": True, "map": True}, "archive": str(archive)})
    assert "error" not in a and "error" not in b
    assert {k: v for k, v in a.items() if k != "next"} == {k: v for k, v in b.items() if k != "next"}
    t1 = call("task_new", {"title": "t", "collection": "memo", "views": ["org"], "archive": str(archive)})
    t2 = call("task_new", {"title": "t", "collection": "memo", "views": {"org": True, "map": False}, "archive": str(archive)})
    assert "error" not in t1 and "error" not in t2
    assert wf.views_as_map(["org"]) == {"org": True} and wf.views_as_list({"org": True, "map": False}) == ["org"]


def test_find_entities_takes_name_for_query(saved):
    archive, _, _ = saved
    a = call("find_entities", {"query": "Dana Hale", "archive": str(archive)})
    b = call("find_entities", {"name": "Dana Hale", "archive": str(archive)})
    assert a == b and a["count"] >= 1
    assert text_of_call("find_entities", {"archive": str(archive)})["error"]
