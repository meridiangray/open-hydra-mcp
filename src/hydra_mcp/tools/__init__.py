"""tools/ — the MCP tools, one module per tool set of `toolsets.TOOLSETS`: core, enrich, wikidata, checks, geo, shape,
admin. Each registers its tools on `hydra_mcp.app.mcp` when imported (`server.py` imports them all, in that order).
A tool is a thin wrapper: it opens the archive and calls the hydra-mcp or hydra function that does the work, inside
`app._run`. A new tool goes in the module of its set, and its name in `toolsets.TOOLSETS`."""
