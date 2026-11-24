"""recipe(): the Archive Workflow's read-only recipes, run by name with their JSON back (gap G17)."""
import shutil
import sys

import pytest

from hydra_mcp import core, recipes, server

HAVE_JQ = shutil.which("jq") is not None
def _poppler() -> bool:
    """The recipes are written for poppler's pdftotext; Git Bash's older xpdf one reads pages differently."""
    import subprocess
    exe = shutil.which("pdftotext")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "poppler" in (r.stdout + r.stderr).lower()


HAVE_PDF = _poppler()
SHELL_OK = (shutil.which("powershell.exe") if sys.platform == "win32" else shutil.which("bash")) is not None
try:
    recipes.folder()
    HAVE_RECIPES = True
except core.IngestError:
    HAVE_RECIPES = False

needs_recipes = pytest.mark.skipif(not HAVE_RECIPES, reason="no Archive Workflow recipes folder (HYDRA_RECIPES)")
needs_jq = pytest.mark.skipif(not (HAVE_RECIPES and HAVE_JQ), reason="jq not on the PATH")
needs_pdf = pytest.mark.skipif(not (HAVE_RECIPES and HAVE_JQ and HAVE_PDF and SHELL_OK), reason="poppler not on the PATH")

PAGES = [["Dana Hale met Rob Kerr at the Port Authority.", "Dana Hale said the inquiry would start soon."],
         ["Rob Kerr later told reporters the Port Authority", "had kept every record."]]


def pdf(pages: list[list[str]]) -> bytes:
    """A PDF with one page per list of lines."""
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()]
    font = 3 + 2 * n
    for i, lines in enumerate(pages):
        body = " ".join(f"72 {720 - 20 * j} Td ({t}) Tj 0 0 Td" if j == 0 else f"0 -20 Td ({t}) Tj"
                        for j, t in enumerate(lines))
        stream = f"BT /F1 12 Tf {body} ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
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
def doc(tmp_path):
    f = tmp_path / "a report.pdf"                   # a space in the name, as in real folders
    f.write_bytes(pdf(PAGES))
    return f


@pytest.fixture
def archive(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    root = core.open_archive(out["archive"])
    P = lambda s, **p: {"schema": s, "properties": p}
    core.ingest(root, [P("Person", name="Dana Hale"), P("Person", name="Dana Hale"),
                       P("PublicBody", name="Port Authority")],
                {"text": "Dana Hale runs the Port Authority. Another Dana Hale was there.", "title": "A note"}, "a")
    return root


# ---- the list, and refusals -------------------------------------------------------------------------------

@needs_recipes
def test_no_name_lists_the_recipes_with_their_args():
    out = server.recipe()
    assert set(out["recipes"]) == {"intake", "outline", "names", "findquote", "table", "tsv2records", "audit"}
    assert "quotes" in out["recipes"]["findquote"]["args"]


@needs_recipes
def test_an_unknown_recipe_is_refused_with_the_list():
    with pytest.raises(ValueError, match="no recipe 'rm'.*intake"):
        server.recipe("rm", {"doc": "x"})


@needs_recipes
def test_a_document_must_be_a_full_path_to_a_file(tmp_path):
    with pytest.raises(ValueError, match="not a full path"):
        server.recipe("intake", {"doc": "report.pdf"})
    with pytest.raises(ValueError, match="not found"):
        server.recipe("intake", {"doc": str(tmp_path / "missing.pdf")})


@needs_recipes
def test_pdf_only_recipes_refuse_other_files(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a PDF"):
        server.recipe("findquote", {"doc": str(tmp_path / "a.txt"), "quotes": ["x"]})


@needs_recipes
def test_bad_args_are_refused_before_anything_runs(doc):
    with pytest.raises(ValueError, match="give `quotes`"):
        server.recipe("findquote", {"doc": str(doc)})
    with pytest.raises(ValueError, match="whole number"):
        server.recipe("names", {"doc": str(doc), "from": "two"})
    with pytest.raises(ValueError, match="give `from`"):
        server.recipe("table", {"doc": str(doc), "to": 2})
    with pytest.raises(ValueError, match="give `check`.*samename"):
        server.recipe("audit", {"check": "delete"})


def test_the_folder_comes_from_hydra_recipes(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRA_RECIPES", str(tmp_path))
    with pytest.raises(ValueError, match="no recipes folder"):
        server.recipe("audit", {"check": "summary"})


def test_wsl_paths():
    assert recipes.to_wsl(r"E:\Documents\Archive Workflow\x.pdf") == "/mnt/e/Documents/Archive Workflow/x.pdf"
    assert recipes.to_wsl("/home/a/x.pdf") == "/home/a/x.pdf"


def test_an_unknown_shell_is_refused(monkeypatch):
    monkeypatch.setenv("HYDRA_RECIPES_SHELL", "cmd")
    with pytest.raises(core.IngestError, match="powershell, bash or wsl"):
        recipes.shell()


# ---- the jq recipes ---------------------------------------------------------------------------------------

@needs_jq
def test_tsv2records_turns_a_table_into_records():
    tsv = "name\tnationality\tid\nDana Hale\tus; ca\t\nRob Kerr\t\tperson-rk\n"
    out = server.recipe("tsv2records", {"tsv": tsv, "schema": "Person", "source": "doc-1"})
    recs = {r["id"]: r for r in out["result"]}
    assert recs["person-dana-hale"]["properties"]["nationality"] == ["us", "ca"]
    assert recs["person-rk"]["properties"]["name"] == ["Rob Kerr"]
    assert all(r["schema"] == "Person" for r in recs.values())


@needs_jq
def test_audit_reads_the_archive_and_writes_nothing(archive):
    before = sorted((p.as_posix(), p.stat().st_mtime_ns) for p in (archive / "collections").rglob("*") if p.is_file())
    summary = server.recipe("audit", {"check": "summary"}, archive=str(archive))["result"]
    assert summary["records"] >= 3 and summary["schemas"]["Person"] >= 2
    same = server.recipe("audit", {"check": "samename"}, archive=str(archive))["result"]
    assert [s["name"] for s in same] == ["dana hale"] and len(same[0]["ids"]) == 2
    after = sorted((p.as_posix(), p.stat().st_mtime_ns) for p in (archive / "collections").rglob("*") if p.is_file())
    assert before == after


# ---- the document recipes (need poppler) ------------------------------------------------------------------

@needs_pdf
def test_intake_gives_the_hash_and_pages(doc):
    import hashlib
    out = server.recipe("intake", {"doc": str(doc)})["result"]
    assert out["sha256"] == hashlib.sha256(doc.read_bytes()).hexdigest()
    assert int(out["pages"]) == 2


@needs_pdf
def test_names_counts_names_in_a_page_range(doc):
    both = {n["name"]: n["count"] for n in server.recipe("names", {"doc": str(doc), "min": 1})["result"]}
    assert both["Dana Hale"] == 2 and both["Rob Kerr"] == 2
    first = {n["name"] for n in server.recipe("names", {"doc": str(doc), "from": 2, "to": 2, "min": 1})["result"]}
    assert "Rob Kerr" in first and "Dana Hale" not in first


@needs_pdf
def test_findquote_places_quotes_including_ones_with_double_quotes(doc):
    out = server.recipe("findquote", {"doc": str(doc), "quotes": [
        "Dana Hale said the inquiry would start soon.",
        "the Port Authority had kept every record",
        'He said "nothing" happened.']})["result"]
    pages = {r["quote"]: r["pages"] for r in out}
    assert pages["Dana Hale said the inquiry would start soon."] == ["1"]
    assert pages["the Port Authority had kept every record"] == ["2"]
    assert pages['He said "nothing" happened.'] == []


@needs_pdf
def test_table_gives_rows(doc):
    out = server.recipe("table", {"doc": str(doc), "from": 1, "to": 1})["result"]
    assert out["rows"] and "Dana Hale" in out["tsv"]
    with pytest.raises(ValueError, match="comes before"):
        server.recipe("table", {"doc": str(doc), "from": 2, "to": 1})
