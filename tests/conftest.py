"""Shared test setup: the machine cache (extracted texts, source profiles) goes to a temp folder, never the user's."""
import os
import tempfile

os.environ["HYDRA_CACHE_DIR"] = tempfile.mkdtemp(prefix="hydra-test-cache-")
