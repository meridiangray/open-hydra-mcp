"""Keep the tool tables in the docs equal to the tools server.py registers.

Imports the server and lists its registered tools, builds a Markdown table of
every one, and rewrites the text between

    <!-- tools:start -->  and  <!-- tools:end -->

in each target file. `--check` writes nothing and exits 1 if a file is stale.

    python scripts/gen_tool_table.py [--check] [file ...]
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "src" / "hydra_mcp" / "server.py"
DEFAULT_TARGETS = [ROOT / "README.md", ROOT.parent / "hydra-git" / "guide" / "docs" / "guides" / "mcp.md"]
START, END = "<!-- tools:start -->", "<!-- tools:end -->"


def tools() -> list[tuple[str, list[str], str]]:
    """Every registered tool (server.py and the modules that register onto it), in name order."""
    import asyncio
    sys.path.insert(0, str(ROOT / "src"))
    from hydra_mcp import server
    found = asyncio.run(server.mcp.list_tools())
    return [(t.name, list(t.inputSchema.get("properties", {})), t.description or "")
            for t in sorted(found, key=lambda t: t.name)]


def first_sentence(doc: str) -> str:
    text = " ".join(doc.split())
    m = re.search(r"(?<=[a-z0-9`)])\.(?:\s|$)", text)
    return (text[: m.start() + 1] if m else text).replace("|", "\\|")


def table() -> str:
    from hydra_mcp.toolsets import TOOL_SET
    rows = ["| Tool | Set | Arguments | What it does |", "|---|---|---|---|"]
    for name, args, doc in tools():
        rows.append(f"| `{name}` | {TOOL_SET.get(name, '')} | {', '.join(f'`{a}`' for a in args)} | {first_sentence(doc)} |")
    return "\n".join(rows)


def render(text: str) -> str | None:
    if START not in text or END not in text:
        return None
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{table()}\n{END}{tail}"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    targets = [Path(a) for a in argv if not a.startswith("--")] or DEFAULT_TARGETS
    stale = 0
    for path in targets:
        old = path.read_text(encoding="utf-8")
        new = render(old)
        if new is None:
            print(f"{path}: no {START} / {END} markers, skipped")
            continue
        if new == old:
            print(f"{path}: current")
        elif check:
            print(f"{path}: STALE")
            stale += 1
        else:
            path.write_text(new, encoding="utf-8")
            print(f"{path}: updated")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
