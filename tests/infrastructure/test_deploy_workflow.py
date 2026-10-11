"""Guards on automatic deploys: production is deployed only after CI passes on main.

Run: uv run --project apps/api pytest tests/infrastructure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    with (WORKFLOWS / name).open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def test_deploy_follows_ci_on_main_only() -> None:
    deploy = _load("deploy.yml")
    triggers = deploy[True]  # PyYAML reads the "on" key as True
    run = triggers["workflow_run"]
    assert run["workflows"] == [_load("ci.yml")["name"]]
    assert run["branches"] == ["main"]
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    condition = deploy["jobs"]["deploy"]["if"]
    assert "conclusion == 'success'" in condition
    assert "event == 'push'" in condition


def test_one_deploy_at_a_time() -> None:
    concurrency = _load("deploy.yml")["concurrency"]
    assert concurrency["cancel-in-progress"] is False


def test_deploy_script_is_executable() -> None:
    for name in ("deploy.sh", "setup-auto-deploy.sh"):
        assert (ROOT / "scripts" / name).stat().st_mode & 0o111, name
