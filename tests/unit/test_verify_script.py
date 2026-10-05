from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "connector_verify_script",
    Path(__file__).resolve().parents[2] / "scripts" / "verify.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_VERIFY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VERIFY)
uv_run_prefix = _VERIFY.uv_run_prefix


def test_skip_sync_uses_uv_no_sync_for_every_check() -> None:
    assert uv_run_prefix(skip_sync=True, offline=False) == ("uv", "run", "--no-sync")


def test_offline_adds_uv_offline_mode() -> None:
    assert uv_run_prefix(skip_sync=True, offline=True) == (
        "uv",
        "run",
        "--no-sync",
        "--offline",
    )
