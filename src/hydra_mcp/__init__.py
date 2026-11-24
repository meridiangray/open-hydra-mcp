"""hydra-mcp: raw text in, records a hydra archive accepts out."""
from hydra.api import hooks

from hydra_mcp import workflows


def _listen() -> None:
    """hydra.api's record and source functions (save, amend, fetch) tell their hooks what they wrote; the session's
    checked-out task logs it (workflows.hook_source / hook_log), as when those functions lived here."""

    def source(root, source_id, note=""):
        workflows.hook_source(root, source_id, note)

    def log(root, message):
        workflows.hook_log(root, message)

    hooks.on("source", "hydra_mcp", source)
    hooks.on("log", "hydra_mcp", log)


_listen()
