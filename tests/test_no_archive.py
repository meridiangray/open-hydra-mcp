"""With no archive selected: the read-only tools work on hydra's defaults and say
so, the tools that write refuse with what to do, and create_archive starts one."""
import json

import pytest

from hydra import layout, resources
from hydra_mcp import core, server

RECORDS = [{"schema": "Person", "properties": {"name": "Dana Hale"}},
           {"schema": "PublicBody", "properties": {"name": "Port Authority"}},
           {"schema": "Employment", "properties": {"employee": "Dana Hale", "employer": "Port Authority", "role": "deputy"}}]


@pytest.fixture
def nowhere(tmp_path, monkeypatch):
    """A server started in an empty folder, with no HYDRA_ARCHIVE and nothing active."""
    monkeypatch.delenv("HYDRA_ARCHIVE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert resources.activated() is None
    return tmp_path


def test_with_no_archive_the_guidelines_and_reading_still_work_and_say_so(nowhere):
    g = server.labelling_guidelines()
    assert g.startswith("> No archive is selected") and "## Record format" in g and "Second-in-command" in g
    assert server.find_entities("Dana Hale") == []
    assert not list(nowhere.iterdir())                                # nothing was written anywhere


def test_with_no_archive_save_refuses_and_says_what_to_do(nowhere):
    with pytest.raises(ValueError, match="No hydra archive is selected.*create_archive"):
        server.save(RECORDS, {"text": "x"})
    assert not list(nowhere.iterdir())
    assert not (resources.TEMPLATE / layout.COLLECTIONS_DIR / "x.json").exists()


def test_a_named_archive_that_is_wrong_is_an_error_not_a_fallback(nowhere):
    with pytest.raises(ValueError, match="is not an archive.*create_archive"):
        server.labelling_guidelines(archive=str(nowhere))
    with pytest.raises(core.IngestError, match="hydra's own template"):
        core.open_archive(str(resources.TEMPLATE))


def test_create_archive_previews_then_creates_and_the_text_can_go_in(nowhere):
    dest = nowhere / "cases" / "port"
    for bad, why in (("cases/port", "full path"), (str(nowhere / "x.hydra"), "packed archive")):
        with pytest.raises(ValueError, match=why):
            server.create_archive(bad)

    p = server.create_archive(str(dest), name="Port inquiry")
    assert not p["created"] and p["folder"] == "new" and not dest.exists()

    out = server.create_archive(str(dest), name="Port inquiry", confirm=True)
    assert out["created"] and out["archive"] == str(dest.resolve()) and resources.is_archive(dest)
    assert out["overview"]["name"] == "Port inquiry" and f"HYDRA_ARCHIVE={dest.resolve()}" in out["next"]
    with pytest.raises(ValueError, match="already a hydra archive"):
        server.create_archive(str(dest))

    got = server.save(RECORDS, {"text": "Dana Hale is the deputy at the Port Authority."}, "first",
                           archive=out["archive"])
    assert got["saved"] and "Rebuilt" in got["build"]
    ids = [r["id"] for r in json.loads((dest / "collections/first.json").read_text())]
    assert ids[0] == "person-dana-hale"
    assert server.find_entities("Dana Hale", archive=out["archive"])[0]["id"] == "port-inquiry:person-dana-hale"


def test_create_archive_refuses_a_folder_with_files(nowhere):
    (nowhere / "full").mkdir()
    (nowhere / "full" / "notes.txt").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        server.create_archive(str(nowhere / "full"))


def test_a_stray_print_during_a_tool_never_reaches_the_mcp_stream(capsys):
    server._run(lambda: print("noise from hydra"))
    out = capsys.readouterr()
    assert "noise from hydra" not in out.out and "noise from hydra" in out.err
