"""test_layers.py: hydra-mcp builds on hydra's lower layers only (hydra-docs plans/imports.md §2, §7).

hydra-mcp may import hydra's base, model and engine modules and `hydra.api`, never the front ends: `hydra.cli.*`
(except `hydra.cli.style`), `hydra.wiki.*` (the desktop app is its own project, hydra-desktop). Scans every import
in src/hydra_mcp, including imports inside functions. `ALLOWED` lists today's front-end imports; it only shrinks: the test fails on a new one and on a
listed one that is gone (delete its row in the same change)."""
from __future__ import annotations

import ast
import functools
import warnings
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "hydra_mcp"
FRONT = ("hydra.cli", "hydra.wiki")
PACKAGES = FRONT + tuple(f"hydra.wiki.{s}" for s in ("look", "labels", "pages", "views"))   # wiki's subfolders: `from <one> import x` names x
OK = {"hydra.cli.style"}


def _front(name: str) -> bool:
    return name not in OK and any(name == f or name.startswith(f + ".") or name.startswith(f + "_") for f in FRONT)


@functools.lru_cache(maxsize=1)
def scan() -> frozenset[tuple[str, str]]:
    """(hydra_mcp module, hydra front-end module) for every import of a front end."""
    out = set()
    for p in SRC.rglob("*.py"):
        parts = ["hydra_mcp", *p.relative_to(SRC).with_suffix("").parts]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mod = ".".join(parts)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                # `from hydra.cli import node` names the module node; `from hydra.cli.node import x` names its module
                names = [f"{node.module}.{a.name}" if node.module in PACKAGES or node.module == "hydra" else node.module
                         for a in node.names]
            else:
                continue
            for n in names:
                if _front(n):
                    out.add((mod, n))
    return frozenset(out)


# Today's front-end imports (2026-11-23). Remove a row when its import moves to `hydra.api`; never add one.
ALLOWED = {
    ("hydra_mcp.agent", "hydra.cli.export"),
    ("hydra_mcp.agent", "hydra.cli.node"),
    ("hydra_mcp.agent", "hydra.cli.todo"),
    ("hydra_mcp.agent", "hydra.wiki.pages.reviewqueue"),
    ("hydra_mcp.agent", "hydra.wiki.look.symbology"),
    ("hydra_mcp.agent", "hydra.wiki.views.timelineview"),
    ("hydra_mcp.core", "hydra.cli.init"),
    ("hydra_mcp.data", "hydra.cli.export"),
    ("hydra_mcp.data", "hydra.cli.pack"),
    ("hydra_mcp.data", "hydra.wiki.pages.archiveconf"),
    ("hydra_mcp.guidelines", "hydra.wiki.pages.readiness"),
    ("hydra_mcp.packages", "hydra.wiki.look.bazaar"),
    ("hydra_mcp.pipeline", "hydra.wiki.site"),
    ("hydra_mcp.tools.shape", "hydra.wiki.pages.readiness"),          # moved from hydra_mcp.server with wiki_readiness (M1)
    ("hydra_mcp.workflows", "hydra.cli.check"),
    ("hydra_mcp.workflows", "hydra.cli.details"),
    ("hydra_mcp.workflows", "hydra.cli.positions"),
    ("hydra_mcp.workflows", "hydra.wiki.manage"),
    ("hydra_mcp.workflows", "hydra.wiki.views.org"),
    ("hydra_mcp.workflows", "hydra.wiki.views.viewcheck"),
}


def test_no_new_front_end_imports():
    new = sorted(scan() - ALLOWED)
    assert not new, ("hydra-mcp imports a hydra front end; call hydra.api or a lower module instead "
                     "(plans/imports.md):\n" + "\n".join(f"  {a} -> {b}" for a, b in new))


def test_allowed_list_only_shrinks():
    gone = sorted(ALLOWED - scan())
    assert not gone, "fixed, so delete these rows from ALLOWED:\n" + "\n".join(f"  {a} -> {b}" for a, b in gone)
