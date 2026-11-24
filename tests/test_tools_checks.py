"""The `checks` toolset: three read-only reviewers and a page image. Nothing is built or written; a stale archive
answers `stale: true` with no findings."""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from hydra.cli import init as hinit
from hydra.universe import build
from hydra_mcp import core, server, toolsets


def P(i, schema, notes=None, **props):
    rec = {"id": i, "schema": schema, "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}
    if notes:
        rec["properties"]["notes"] = [notes]
    return rec


def make(tmp_path, records, built=True) -> Path:
    root = hinit.create(Path(tmp_path) / "chk", name="chk", prefix="chk", universe=True)
    (root / "collections" / "chk.json").write_text(json.dumps(records), encoding="utf-8")
    if built:
        build.build(root)
    return root


def tree(root) -> dict:
    return {os.path.join(d, f): hashlib.sha1(Path(d, f).read_bytes()).hexdigest()
            for d, _, fs in os.walk(root) for f in fs}


def stale(root):
    f = Path(root) / ".hydra" / "rules" / "scope.yaml"
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, time.time_ns() + 20_000_000_000))


def records():
    out = [P("hub", "Person", name="Pat Hub"),
           P("p", "Person", name="Joe Bloggs"), P("o", "Company", name="Acme Ltd"),
           P("e1", "Employment", notes="In March 1986 Joe Bloggs joined Acme Ltd.", employee="p", employer="o",
             startDate="1986-03-19")]
    for i in range(7):
        n = f"Spoke {chr(65 + i)}son"
        out += [P(f"s{i}", "Person", name=n, **({"notes": "Spoke Ason met Spoke Bson in Cairo."} if i == 0 else {})),
                P(f"a{i}", "Associate", notes=f"{n} knew Pat Hub.", person="hub", associate=f"s{i}")]
    return out


def test_the_tools_are_a_checks_set_that_is_off_by_default():
    assert toolsets.TOOLSETS["checks"] == ("check_values", "check_rules", "check_graph", "source_page_image")
    assert "checks" not in toolsets.parse(None)
    assert set(toolsets.TOOLSETS["checks"]) <= set(server.mcp._hydra_toolsets.all)


def test_check_values_finds_and_writes_nothing(tmp_path):
    root = make(tmp_path, records())
    before = tree(root)
    out = _call("check_values", root)
    assert not out["stale"]
    hit = [f for f in out["findings"] if f["rule"] == "date-in-quote"]
    assert [f["records"] for f in hit] == [["e1"]] and hit[0]["check"] == "values" and hit[0]["entity"]
    assert _call("check_values", root, records=["a0"])["findings"] == []
    assert tree(root) == before


def test_check_rules_shape_and_nothing_written(tmp_path):
    recs = [P("marco", "Person", name="Marco Reyes", gender="male", birthDate="1960"),
            P("ana", "Person", name="Ana Reyes", gender="female", birthDate="1990"),
            P("f1", "Family", notes="Marco Reyes is the father of Ana Reyes.", person="marco", relative="ana",
              relationship="father")]
    root = make(tmp_path, recs)
    before = tree(root)
    out = _call("check_rules", root)
    hit = out["findings"][0]
    assert not out["stale"] and hit["records"] == ["f1"] and hit["severity"] == "error" and hit["fix"]
    assert _call("check_rules", root, scope=["marco"])["findings"] == []
    assert tree(root) == before


def test_check_graph_carries_entities_and_a_snapshot_for_since(tmp_path):
    root = make(tmp_path, records())
    before = tree(root)
    out = _call("check_graph", root)
    f = out["findings"][0]
    assert f["measure"] == "spokes-named-together" and len(f["entities"]) == 3 and f["entities"][0] == f["entity"]
    assert all(h.startswith("H-") for h in f["entities"]) and set(f["entity_records"]) == set(f["entities"])
    assert "nodes" not in out["snapshot"] and out["shape"]
    assert "delta" not in out
    again = _call("check_graph", root, since=out["snapshot"])
    assert again["delta"]["entities_added"] == [] and again["findings"] == out["findings"]
    assert tree(root) == before


def test_a_stale_archive_says_so_and_is_not_built(tmp_path):
    root = make(tmp_path, records())
    stale(root)
    before = tree(root)
    assert _call("check_graph", root)["stale"] is True and _call("check_graph", root)["findings"] == []
    for name in ("check_values", "check_rules"):                  # record-level findings still stand, filed by record id
        out = _call(name, root)
        assert out["stale"] is True and out["why"], name
        assert not any(f["entity"].startswith("H-") for f in out["findings"]), name
    assert any(f["rule"] == "date-in-quote" for f in _call("check_values", root)["findings"])
    assert tree(root) == before
    unbuilt = make(tmp_path / "u", records(), built=False)
    assert _call("check_graph", unbuilt)["stale"] is True


def _call(name, root, **kw):
    return server.mcp._hydra_toolsets.all[name].fn(archive=str(root), **kw)       # on or off, the same function


# ---- the page image --------------------------------------------------------------------------------------

def pdf(pages: int = 2) -> bytes:
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(pages)) + f"] /Count {pages} >>").encode()]
    for i in range(pages):
        stream = f"BT /F1 24 Tf 72 700 Td (Page {i + 1} of the dossier) Tj ET".encode()
        objs += [(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                  "/Resources << /Font << /F1 %d 0 R >> >> >>" % (3 + 2 * pages)).encode(),
                 b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@pytest.fixture
def kept(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    root = core.open_archive(out["archive"])
    f = tmp_path / "dossier.pdf"
    f.write_bytes(pdf(2))
    t = tmp_path / "memo.txt"
    t.write_text("Dana Hale led the inquiry into the port.")
    recs = [{"schema": "Person", "properties": {"name": "Dana Hale"}}]
    server.save(recs, {"file": str(f)}, "dossier", archive=str(root))
    server.save(recs, {"file": str(t)}, "memo", archive=str(root))
    sources = {s["title"]: s["source_id"] for s in server.sources(archive=str(root))["sources"]}
    return root, sources


def _png(parts):
    from mcp.server.fastmcp import Image
    img = next(p for p in parts if isinstance(p, Image))
    return img.data


def test_a_page_image_of_a_kept_pdf(kept):
    root, src = kept
    before = tree(root)
    parts = _call("source_page_image", root, source=src["dossier"], page=2)
    data = _png(parts)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and any("read_source" in p for p in parts if isinstance(p, str))
    small = _png(_call("source_page_image", root, source=src["dossier"], page=1, dpi=10))      # capped up to 72
    big = _png(_call("source_page_image", root, source=src["dossier"], page=1, dpi=900))       # capped down to 200
    assert len(small) < len(big) and int.from_bytes(big[16:20], "big") <= 200 * 11
    assert tree(root) == before


def test_the_client_receives_image_content(kept):
    import asyncio
    root, src = kept
    tools = server.mcp._tool_manager._tools
    tools["source_page_image"] = server.mcp._hydra_toolsets.all["source_page_image"]
    try:
        got = asyncio.run(server.mcp.call_tool("source_page_image", {"source": src["dossier"], "page": 1, "archive": str(root)}))
    finally:
        del tools["source_page_image"]
    blocks = got[0] if isinstance(got, tuple) else got
    assert [b.type for b in blocks] == ["text", "image"] and blocks[1].mimeType == "image/png"


def test_a_page_image_refuses_a_bad_page_and_a_source_that_is_not_a_pdf(kept):
    root, src = kept
    for page in (3, 0, -1):
        with pytest.raises(ValueError, match="page"):
            _call("source_page_image", root, source=src["dossier"], page=page)
    with pytest.raises(ValueError, match="not a kept PDF"):
        _call("source_page_image", root, source=src["memo"], page=1)
    with pytest.raises(ValueError, match="no source"):
        _call("source_page_image", root, source="doc-nope", page=1)
