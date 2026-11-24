"""files.py — moved to `hydra.api.files` (hydra-docs plans/imports.md I2b). This name is that module itself, so
`hydra_mcp.files.X` and `hydra.api.files.X` are one object (a test that patches `files._read` or `CACHE_KEEP` patches
the reader every caller uses)."""
import sys

from hydra.api import files as _files

sys.modules[__name__] = _files
