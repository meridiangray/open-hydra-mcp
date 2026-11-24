"""hydra-mcp: files in, hydra records out.

The connected model reads a file (or pasted text), writes the facts as hydra's
FollowTheMoney JSON following the labelling guidelines, and saves them: the
records as a collection, the file as the evidence every entity cites. Run it with
`hydra-mcp` (stdio). The archive is the `archive` argument of each tool, else
$HYDRA_ARCHIVE, else hydra-ctl's active archive.

The tools are in `tools/<set>.py`, one module per tool set (`toolsets.TOOLSETS`); importing one registers its tools
on the one server, `app.mcp`. This module imports them, installs the write lock, the call log and the tool sets on
that server, and runs it. Every tool function is still `hydra_mcp.server.<name>` (tests, the page flow and run
scripts call `server.save(...)`), as are `server.mcp` and `server._run`.
"""
from __future__ import annotations

import argparse
import sys

from hydra_mcp import app, calllog, config, toolsets as toolsets_mod, workflows as wf
from hydra_mcp.app import _run, mcp  # noqa: F401  (server._run: tests use it)

# Importing a tool module registers its tools; the sets in the order of toolsets.TOOLSETS.
from hydra_mcp.tools import core as _core  # noqa: F401
from hydra_mcp.tools import enrich as _enrich  # noqa: F401
from hydra_mcp.tools import wikidata as _wikidata  # noqa: F401
from hydra_mcp.tools import checks as _checks  # noqa: F401
from hydra_mcp.tools import geo as _geo  # noqa: F401
from hydra_mcp.tools import shape as _shape  # noqa: F401
from hydra_mcp.tools import admin as _admin  # noqa: F401

wf.install_write_lock(mcp)
calllog.install(mcp)
toolsets_mod.install(mcp)                               # after every tool is registered: it keeps the full tool table

_clash = sorted(set(app.FUNCTIONS) & set(globals()))
if _clash:
    raise RuntimeError(f"tool functions named like hydra_mcp.server's own names: {', '.join(_clash)}")
globals().update(app.FUNCTIONS)                         # every tool function as hydra_mcp.server.<name>


def main(argv: list[str] | None = None) -> None:
    args_in = sys.argv[1:] if argv is None else list(argv)
    if args_in and args_in[0] == "config":                 # `hydra-mcp config ...` edits mcp.yaml; no server
        raise SystemExit(config.cli(args_in[1:]))
    ap = argparse.ArgumentParser(prog="hydra-mcp")
    ap.add_argument("--toolsets", default=None,
                    help="tool sets to switch on, comma separated: core,enrich,geo,shape,admin or all "
                         f"(default: env {toolsets_mod.ENV}, else mcp.yaml, else core); `hydra-mcp config` edits mcp.yaml")
    args = ap.parse_args(args_in)
    toolsets_mod.start(mcp, args.toolsets)
    mcp.run()


if __name__ == "__main__":
    main()
