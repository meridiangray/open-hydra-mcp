"""`cite` with a quote: in the cited source's own text (a short quote is warned); refused when the source has no text
(health-check M8)."""
import json

import pytest


from hydra.build import run as build
from hydra.sources import citations as hcitations
from hydra.archive import layout
from hydra_mcp import core, server

TEXT = "Bandar bin Sultan was born in Taif.\nHe later served as ambassador to Washington for many years.\n"


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    root = core.open_archive(out["archive"])
    txt = tmp_path / "dossier.txt"
    txt.write_text(TEXT, encoding="utf-8")
    saved = server.save([{"id": "per1", "schema": "Person", "properties": {"name": "Bandar bin Sultan"}}],
                        source={"file": str(txt), "title": "Dossier", "url": "https://example.org/d"},
                        collection="main", archive=str(root))
    assert saved["saved"], saved
    return root


def _sid(root):
    return json.loads((root / layout.SOURCE_ENTRIES / "main.json").read_text(encoding="utf-8"))[0]["id"]


def _cite(root, quote, sid=None, confirm=True):
    return server.cite([{"record": "case:per1", "source": sid or _sid(root), "pages": "1", "quote": quote}],
                       confirm=confirm, archive=str(root))


def test_cite_warns_on_a_quote_that_is_not_a_full_clause(arch):
    got = _cite(arch, "born in Taif")
    assert not got["errors"] and "at least 6 words" in got["warnings"][0]
    assert got["written"] == 1


def test_cite_accepts_a_full_clause_and_a_sentence(arch):
    assert not _cite(arch, "He later served as ambassador to Washington", confirm=False)["errors"]
    assert _cite(arch, "Bandar bin Sultan was born in Taif.")["written"] == 1


def test_cite_refuses_a_quote_from_another_source(arch, tmp_path):
    other = tmp_path / "other.txt"
    other.write_text("The harbour opened in the spring of that year.\n", encoding="utf-8")
    server.save([{"id": "per2", "schema": "Person", "properties": {"name": "Dana Hale"}}],
                source={"file": str(other), "title": "Other", "url": "https://example.org/o"},
                collection="second", archive=str(arch))
    got = _cite(arch, "The harbour opened in the spring of that year.")          # the first source has the dossier text
    assert got["errors"] and "word for word" in got["errors"][0]
    assert not (arch / hcitations.PATH).exists()


def test_cite_with_a_quote_refuses_when_the_source_has_no_text(arch):
    (arch / layout.SOURCE_ENTRIES / "extra.json").write_text(
        json.dumps([{"id": "doc-notext00001", "schema": "Article",
                     "properties": {"title": ["Bare entry"], "sourceUrl": ["https://example.org/bare"]}}]),
        encoding="utf-8")
    build.build_archive(arch)
    got = _cite(arch, "Bandar bin Sultan was born in Taif.", sid="doc-notext00001")
    assert got["errors"] and "no text" in " ".join(got["errors"])
    assert not (arch / hcitations.PATH).exists()
