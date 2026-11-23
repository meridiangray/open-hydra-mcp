"""Archive Workflow tooling gaps built 2026-11-22: G16 collection_delete, G14 a fetched page's own title."""
import pytest

from hydra_mcp import core, data, server, sources


@pytest.fixture
def arch(tmp_path):
    out = core.create_archive(str(tmp_path / "case"), name="case", confirm=True)
    return core.open_archive(out["archive"])


# ---- G16 ----
def test_collection_delete_previews_then_removes_an_empty_collection(arch):
    data.collection_create(arch, "oops", "By mistake", confirm=True)
    pre = data.collection_delete(arch, "oops")
    assert pre["changed"] is False and pre["next"]
    assert (arch / "collections" / "oops.json").is_file()
    done = data.collection_delete(arch, "oops", confirm=True)
    assert done["changed"] is True
    assert not (arch / "collections" / "oops.json").exists()


def test_collection_delete_refuses_a_collection_with_records(arch):
    server.save([{"schema": "Person", "properties": {"name": ["Dana Hale"]}}], source={"text": "Dana Hale lives here."},
                collection="people", archive=str(arch))
    got = data.collection_delete(arch, "people", confirm=True)
    assert got["error"] == "not empty" and got["do"]


# ---- G14 ----
@pytest.mark.parametrize("html,want", [
    ('<head><meta property="og:title" content="Real headline"><title>Real headline | Site</title></head><p>x</p>',
     "Real headline"),
    ("<head><title>x</title></head><nav><h1>Site</h1></nav><h1>The story itself</h1><p>Body.</p>", "The story itself"),
    ("<title>New developer Arada targets | The NationalMenu SearchUserUserChevron</title><p>b</p>",
     "New developer Arada targets | The National"),
    ("<title>Open Society Foundations</title><p>b</p>", "Open Society Foundations"),
    ("<title>Search and Rescue in Jeddah</title><p>b</p>", "Search and Rescue in Jeddah"),
])
def test_a_fetched_page_keeps_its_own_title(html, want):
    assert sources._html_text(f"<html>{html}</html>")[1] == want


# ---- G5 outline, G9 names, G10 EPUB ----
POLLARD = "/mnt/e/Documents/development/stable/hydra-mcp-testing/sources/pollard-damage-assessment.pdf"


def _epub(path):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
                   'xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>'
                   '</container>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                   'version="3.0"><manifest><item id="c2" href="ch2.xhtml"/><item id="c1" href="text/ch1.xhtml"/>'
                   '</manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/text/ch1.xhtml", "<html><body><h1>Chapter 1</h1><p>Dana Hale lives in Riyadh.</p></body></html>")
        z.writestr("OEBPS/ch2.xhtml", "<html><body><h1>Chapter 2</h1><p>She moved in 1990.</p></body></html>")
    return path


def test_an_epub_reads_in_spine_order(tmp_path):
    from hydra_mcp import files
    got = files.read(_epub(tmp_path / "book.epub"))
    assert got["text"] == "Chapter 1\n\nDana Hale lives in Riyadh.\n\nChapter 2\n\nShe moved in 1990."
    assert got["type"] == "application/epub+zip"


def test_outline_of_markdown_and_of_an_epub(tmp_path):
    from hydra_mcp import outline
    md = tmp_path / "notes.md"
    md.write_text("# One\n\nText here.\n\n## Two\n\nMore text.\n", encoding="utf-8")
    o = outline.outline(md)
    assert o["from"] == "headings" and [(h["level"], h["title"]) for h in o["headings"]] == [(1, "One"), (2, "Two")]
    assert o["headings"][1]["offset"] > o["headings"][0]["offset"]


@pytest.mark.skipif(not __import__("pathlib").Path(POLLARD).is_file(), reason="the Pollard PDF is not on this machine")
def test_outline_skips_scan_batch_bookmarks_and_contents_pages():
    from hydra_mcp import outline
    o = outline.outline(__import__("pathlib").Path(POLLARD))
    assert o["from"] == "heading lines in the text" and any("scan batches" in w for w in o["warnings"])
    by = {h["title"]: h for h in o["headings"]}
    assert by["I. Introduction"]["page"] == 20 and by["I. Introduction"]["level"] == 1
    assert by["A. Personal History"]["page"] == 23 and by["A. Personal History"]["level"] == 2
    assert not any(h["page"] in (18, 19, 33) for h in o["headings"])


def test_names_in_text_splits_sentences_and_keeps_initials():
    from hydra_mcp import names
    got = [r["name"] for r in names.names_in("He grew up in Middle America. Born in Galveston to Morris Pollard.\n"
                                             "J. Edgar Hoover met the State of Israel's envoy at the University of "
                                             "Notre Dame. The end.")]
    assert "Middle America" in got and "University of Notre Dame" in got and "State of Israel" in got
    assert "J. Edgar Hoover" in got and not any(n.endswith((" Born", " The")) for n in got)
