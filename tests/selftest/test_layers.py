"""Self-tests for totto_suite.layers discovery, contract validation, and execution."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from totto_suite import layers

EXPECTED_OFFLINE_LAYERS = (
    "callbacks",
    "config",
    "dates",
    "grader",
    "lint",
    "regrade",
    "selftest",
    "tools",
)


def test_discover_offline_finds_all_eight_offline_layers():
    mods = layers.discover("offline")
    names = [m.name for m in mods]
    assert names == list(EXPECTED_OFFLINE_LAYERS)


def test_run_layer_and_contract_validation_with_temp_package(tmp_path: Path, monkeypatch):
    pkg_dir = tmp_path / "fake_layers_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "offline_demo.py").write_text(
        "def run(ctx):\n"
        "    return [{\n"
        "        'id': 'demo::check_one',\n"
        "        'layer': 'demo',\n"
        "        'status': 'PASS',\n"
        "        'findings': ['TR-01'],\n"
        "    }]\n",
        encoding="utf-8",
    )
    (pkg_dir / "offline_bad.py").write_text(
        "def run(ctx):\n"
        "    return [{'id': 'wrong_prefix', 'layer': 'bad', 'status': 'PASS'}]\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        discovered = layers.discover("offline", directory=pkg_dir, package="fake_layers_pkg")
        assert [m.name for m in discovered] == ["bad", "demo"]

        bad_outcome = layers.run_layer(discovered[0], {})
        assert bad_outcome.crashed is True
        assert "LayerContractError" in (bad_outcome.error or "")

        ok_outcome = layers.run_layer(discovered[1], {})
        assert ok_outcome.crashed is False
        assert len(ok_outcome.results) == 1
        assert ok_outcome.results[0]["id"] == "demo::check_one"
        assert ok_outcome.results[0]["status"] == "PASS"
    finally:
        for k in list(sys.modules):
            if k == "fake_layers_pkg" or k.startswith("fake_layers_pkg."):
                sys.modules.pop(k, None)
