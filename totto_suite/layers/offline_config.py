"""Offline layer: config (static PIF XML, instruction rules, and contracts)."""

from __future__ import annotations

from typing import Any

from totto_suite.layers._pytest_runner import run_pytest_layer


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return run_pytest_layer(ctx, "config")
