"""Doc drift and the tool contract: the docs, guides and workflows name only real tools; every tool is
documented; every write tool previews first and writes nothing without `confirm`; every tool takes `archive`;
every failure reaches the client as {error, why, do}."""
import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

import hydra
from hydra.cli import main as cli
from hydra_mcp import core, server, workflows as wf

MCP_ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = Path(hydra.__file__).parent / "guides"
WORKFLOW_DIR = Path(hydra.__file__).parent / "workflows"
AGENT_TOOLS = MCP_ROOT / "AGENT-TOOLS.md"

# Tools that legitimately differ from the contract, each with its reason.
NO_ARCHIVE_PARAM = {
    "create_archive": "makes the archive: it takes `path` instead",
    "wiki_stop": "stops a server by port; touches no archive",
}
NO_CONFIRM_BUT_WRITES = {
    "save": "records a source and its records; the save is the unit of work",
    "fetch_source": "keeps a fetched page as a source",
    "universe_build": "rebuilds derived files only",
    "task_checkout": "task bookkeeping, not archive records",
    "task_add": "task bookkeeping",
    "task_step": "task bookkeeping",
    "task_release": "task bookkeeping",
    "task_close": "task bookkeeping",
}
# Names a guide may write like a call that are not MCP tools.
NOT_TOOLS = {"hydra_ctl"}
# Names that were planned or renamed and never shipped: a guide naming one is drift.
GHOSTS = {"geo_set_primary", "set_archive_settings", "get_task", "list_tasks", "geo_draw", "collection_group"}


def tools():
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def params(name):
    return set(tools()[name].inputSchema.get("properties", {}))


def read_all(folder, pattern):
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.glob(pattern))}


def named_in(text, names):
    return {n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)}


def called_in(text):
    """Things written like a tool call: `snake_name(`."""
    return set(re.findall(r"(?<![\w.-])([a-z]+(?:_[a-z]+)+)\(", text))


# ---- docs name every tool, and only real ones ----------------------------------------------------------

def test_every_tool_is_in_agent_tools_and_the_tools_guide():
    names = set(tools())
    agent = AGENT_TOOLS.read_text(encoding="utf-8")
    guide = (GUIDE_DIR / "tools.md").read_text(encoding="utf-8")
    assert not names - named_in(agent, names), f"missing from AGENT-TOOLS.md: {sorted(names - named_in(agent, names))}"
    assert not names - named_in(guide, names), f"missing from guides/tools.md: {sorted(names - named_in(guide, names))}"


def test_guides_and_workflows_name_only_real_tools():
    names = set(tools())
    bad = []
    for path, text in read_all(GUIDE_DIR, "**/*.md").items():
        bad += [(f"guides/{path}", n) for n in called_in(text) - names - NOT_TOOLS]
        bad += [(f"guides/{path}", n) for n in re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text) if n in GHOSTS]
    for path, text in read_all(WORKFLOW_DIR, "*.yaml").items():
        assert yaml.safe_load(text) is not None
        used = set(re.findall(r"^\s*tool:\s*(\w+)", text, re.M)) | called_in(text)
        bad += [(f"workflows/{path}", n) for n in used - names - NOT_TOOLS]
    assert not bad, bad


def test_the_tool_table_in_the_docs_is_current():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(MCP_ROOT / "scripts" / "gen_tool_table.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- the contract ----------------------------------------------------------------------------------------

def test_every_tool_takes_archive_unless_listed():
    missing = {n for n in tools() if "archive" not in params(n)}
    assert missing == set(NO_ARCHIVE_PARAM), f"tools without `archive`: {sorted(missing)}"


def test_the_allow_lists_name_real_tools():
    names = set(tools())
    assert set(NO_ARCHIVE_PARAM) <= names and set(NO_CONFIRM_BUT_WRITES) <= names


def _sample(schema):
    t = schema.get("type") or next((o.get("type") for o in schema.get("anyOf", []) if o.get("type") != "null"), "string")
    return {"string": "x", "array": [], "object": {}, "integer": 1, "number": 1, "boolean": False}.get(t, "x")


def _fingerprint(root: Path):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".parsed" not in p.parts and not p.name.endswith(".calls.jsonl"):
            # derived caches are rebuilt by any read; the call log records every call, a read too
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    root = core.open_archive(str(root))
    P = lambda s, **p: {"schema": s, "properties": p}
    out = core.ingest(root, [P("Person", name="Ann Lee"), P("Company", name="Acme Corp")],
                      {"text": "Ann Lee runs Acme Corp.", "title": "A note"}, "a")
    assert out["saved"], out
    return root


def test_every_write_tool_has_confirm_and_writes_nothing_without_it(archive):
    ts = tools()
    writers = {n for n in ts if "confirm" in params(n)}
    assert writers and not writers & set(NO_CONFIRM_BUT_WRITES)
    before = _fingerprint(archive)
    for name in sorted(writers):
        schema = ts[name].inputSchema
        args = {p: _sample(s) for p, s in schema["properties"].items() if p in schema.get("required", [])}
        if name == "create_archive":
            args["path"] = str(archive.parent / "newplace")
        else:
            args["archive"] = str(archive)
        asyncio.run(server.mcp.call_tool(name, args))               # an error is fine; a write is not
        assert _fingerprint(archive) == before, f"{name} changed the archive without confirm"
    assert not (archive.parent / "newplace").exists()


def test_confirm_defaults_to_false_everywhere():
    for n, t in tools().items():
        if "confirm" in params(n):
            assert t.inputSchema["properties"]["confirm"].get("default") is False, n


def test_the_writers_without_confirm_are_the_always_writes():
    assert set(NO_CONFIRM_BUT_WRITES) == set(wf.ALWAYS_WRITES)


# ---- one error shape ---------------------------------------------------------------------------------------

def test_failures_reach_the_client_as_error_why_do(archive):
    a = str(archive)
    cases = [("guide", {"topic": "nope"}), ("task_checkout", {"id": "zz", "archive": a}),
             ("find_entities", {"query": 3, "archive": a}), ("read_file", {"path": "x"}),
             ("nosuch", {}), ("view_check", {"view": "nope", "archive": a}),
             ("get_records", {"collection": "nope", "archive": a})]
    for name, args in cases:
        r = asyncio.run(server.mcp.call_tool(name, args))
        body = json.loads(r.content[0].text)
        assert r.isError and set(body) == {"error", "why", "do"}, (name, body)
        assert all(isinstance(v, str) and v for v in body.values()), (name, body)


def test_failure_payload_maps_the_exception_types():
    from hydra import tasks
    from hydra.writelock import Busy
    cases = [(core.NoArchive("x"), "no archive"), (tasks.TaskError("t"), None), (SystemExit("hydra: bad"), "hydra refused"),
             (FileNotFoundError("f"), "not found"), (RuntimeError("boom"), "failed"), (ValueError("v"), "refused")]
    for exc, error in cases:
        p = wf.failure_payload(exc)
        assert set(p) == {"error", "why", "do"} and p["why"] and p["do"]
        if error:
            assert p["error"] == error
    assert wf.failure_payload(SystemExit("hydra: bad"))["why"] == "bad"
    b = Busy({"error": "busy", "why": "w", "do": "try again"})
    assert wf.failure_payload(b) == b.payload


# ---- paging --------------------------------------------------------------------------------------------------

PAGED = ["find_entities", "sources", "get_records", "open_questions", "geo_query", "neighbors", "tasks",
         "enrichments", "history_log", "decisions", "paths"]


def test_long_list_tools_page_or_document_a_cap():
    for n in PAGED:
        assert "limit" in params(n) or "at most" in tools()[n].description, f"{n} neither pages nor says its cap"


# ---- named arguments in guides and workflows are real parameters ---------------------------------------------

def _named_args(text):
    """(tool, argument) for each `tool(... name=...)` call; positional mentions are not checked."""
    out = []
    for m in re.finditer(r"(?<![\w.-])([a-z]+(?:_[a-z]+)+)\(([^()]*(?:\([^()]*\)[^()]*)*)\)", text):
        body = re.sub(r"(\"[^\"]*\"|'[^']*')", "", m.group(2))
        out += [(m.group(1), a) for a in re.findall(r"(?<![\w.=])([A-Za-z_]\w*)\s*=(?!=)", body)]
        # a bare lower-case word before the first `=` is a positional placeholder: it must be a real name too
        lead = re.sub(r"\[[^\]]*\]", "", body.split("=")[0])
        out += [(m.group(1), a.strip()) for a in lead.split(",") if re.fullmatch(r"\s*[a-z_]+\s*", a) and a.strip() not in ("true", "false")]
    return out


def test_named_arguments_in_guides_and_workflows_are_real_parameters():
    ts = tools()
    bad = []
    docs = {f"guides/{p}": t for p, t in read_all(GUIDE_DIR, "**/*.md").items()}
    docs |= {f"workflows/{p}": t for p, t in read_all(WORKFLOW_DIR, "*.yaml").items()}
    for path, text in docs.items():
        bad += [(path, tool, a) for tool, a in _named_args(text) if tool in ts and a not in params(tool)]
    assert not bad, bad


def test_the_docs_list_each_tool_under_its_toolset():
    from hydra_mcp import toolsets
    assert set(tools()) == set(toolsets.TOOL_SET)
    for path in (AGENT_TOOLS, GUIDE_DIR / "tools.md"):
        text = path.read_text(encoding="utf-8")
        for name, members in toolsets.TOOLSETS.items():
            line = next(l for l in text.splitlines() if l.startswith(f"- **`{name}`**"))
            assert named_in(line, set(members)) == set(members), (path.name, name)
    assert "toolset_enable" in (GUIDE_DIR / "start.md").read_text(encoding="utf-8")
