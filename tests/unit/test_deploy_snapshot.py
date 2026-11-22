from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPTS = (ROOT / "deploy" / "test", ROOT / "deploy" / "update")

# The deployment snapshot that runs these tests does not carry the scripts themselves.
pytestmark = pytest.mark.skipif(
    not all(script.is_file() for script in SNAPSHOT_SCRIPTS), reason="deploy scripts are not part of this snapshot"
)


class _Project(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    readme: str
    license_files: list[str] = Field(alias="license-files")


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project: _Project


@pytest.mark.parametrize("script", SNAPSHOT_SCRIPTS, ids=lambda script: script.name)
def test_snapshot_copies_every_file_the_package_build_requires(script: Path) -> None:
    project = _Manifest.model_validate(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))).project
    copied = script.read_text(encoding="utf-8").split()
    assert {"pyproject.toml", "uv.lock", project.readme, *project.license_files} <= set(copied)
