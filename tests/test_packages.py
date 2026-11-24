"""packages and package_install as an agent uses them: list, preview, then install on confirm."""
import importlib.util
from pathlib import Path

import pytest

from hydra.machine import packages as P
from hydra.cli import main as cli
from hydra_mcp import core, packages as pk


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_REGISTER_DIR", str(tmp_path / "reg"))
    root = tmp_path / "case"
    cli(["init", str(root), "--name", "case", "--prefix", "c"])
    spec = importlib.util.spec_from_file_location(
        "build_packages", Path(P.__file__).parents[3] / "scripts" / "build_packages.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    reg = tmp_path / "registry"
    reg.mkdir()
    bp.example_symbols(reg)
    P.write_index(reg)
    P.set_registries([str(reg)])
    return core.open_archive(str(root))


def test_list_preview_then_install(setup):
    root = setup
    out = pk.packages(root)
    assert out["in_store"] == [] and out["lock"] == [] and "example/symbols" in [a["name"] for a in out["available"]]   # beside the built-in registry
    prev = pk.package_install(root, "example/symbols")
    assert prev["next"] and prev["version"] == "1.0.0" and "symbology" in prev["provides"]
    assert not P.installed(root) and prev["lock"].endswith("lock.yaml")   # a preview writes nothing
    done = pk.package_install(root, "example/symbols", confirm=True)
    assert done["installed"] == "example/symbols 1.0.0"
    got = pk.packages(root)
    assert got["in_store"][0]["name"] == "example/symbols" and got["lock"][0]["name"] == "example/symbols"
    assert next(a for a in got["available"] if a["name"] == "example/symbols")["installed"] == ["1.0.0"]


def test_unknown_package_refused(setup):
    with pytest.raises(core.IngestError):
        pk.package_install(setup, "nobody/nothing")
