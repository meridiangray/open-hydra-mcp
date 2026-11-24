"""mint.py — moved to `hydra.api.mint` (hydra-docs plans/imports.md I2b). This name is that module itself, so
`hydra_mcp.mint.X` and `hydra.api.mint.X` are one object (a test that patches one patches the other)."""
import sys

from hydra.api import mint as _mint

sys.modules[__name__] = _mint
