# For agents

The agent guide is served by this MCP server. Do not look for it in files.

1. Call `guide("start")` at the start of every session and follow it.
2. It sends you to `tasks` / `task_checkout`, and the task lists the guides to load.
3. `guide()` with no topic lists every topic; `guide(topic, section)` loads one part.

For people editing the guide: topics are the Markdown files in `hydra-git/src/hydra/guides/`, and each workflow
(its checklist and its guide) is one YAML file in `hydra-git/src/hydra/workflows/`. The guides name tools and
fields, never code paths; `hydra-git/tests/test_workflows.py` checks that.

The earlier agent documents (AGENT-GUIDE, AGENT-SIMPLE, AGENT-TOOLS and two one-off briefs) are archived in
`hydra-docs/docs/archive/agent-docs/`.
