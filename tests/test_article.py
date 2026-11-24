"""article_sections and set_article_section: preview first, imported text read-only, the person's text kept."""
import pytest

from hydra.records import articles
from hydra.archive import history
from hydra.cli import main as cli
from hydra_mcp import article, core, server

P = lambda s, **p: {"schema": s, "properties": p}


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    core.ingest(root, [P("Person", name="Test Person")], {"text": "Test Person is a test.", "title": "t"}, "a")
    return root


def h_of(root):
    return article.body_of(root, "Test Person")


def test_preview_writes_nothing_then_confirm_writes(archive):
    b = h_of(archive)
    out = article.set_article_section(archive, "Test Person", "Test heading", "Test text.")
    assert out["action"] == "add" and not out["written"] and articles.load(archive, b) == []
    n = len(history.log(archive))
    out = article.set_article_section(archive, "Test Person", "Test heading", "Test text.", confirm=True)
    assert out["written"] and len(history.log(archive)) > n
    got = article.article_sections(archive, "Test Person")
    assert got["h_body"] == b and [s["heading"] for s in got["sections"]] == ["Test heading"]
    assert article.set_article_section(archive, "Test Person", "test heading", "Changed.", confirm=True)["action"] == "replace"


def test_imported_is_read_only_and_never_overwrites_own_text(archive):
    src = "enwiki:Test_page@5"
    article.set_article_section(archive, "Test Person", "Lead", "Test import.", src, True)
    s = article.article_sections(archive, "Test Person")["sections"][0]
    assert s["imported"] and s["licence"] == "CC BY-SA 4.0"
    with pytest.raises(core.IngestError):
        article.set_article_section(archive, "Test Person", "Lead", "Own words.", confirm=True)
    assert article.set_article_section(archive, "Test Person", "Lead", "Newer.", "enwiki:Test_page@6")["action"] == "re-import"
    articles.edit(archive, article.body_of(archive, "Test Person"), s["id"], "Lead", "Own words.")
    with pytest.raises(core.IngestError):
        article.set_article_section(archive, "Test Person", "Lead", "Newer.", "enwiki:Test_page@7")


def test_the_tools_are_registered():
    assert callable(server.article_sections) and callable(server.set_article_section)
