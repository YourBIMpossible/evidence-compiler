"""Shared pytest fixtures: a real temp git repo built from the golden fixture."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

GOLDEN = os.path.join(os.path.dirname(__file__), "fixtures", "golden-repo")


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _has_git() -> bool:
    return shutil.which("git") is not None


@pytest.fixture
def golden_repo(tmp_path):
    """Copy the golden fixture to a temp dir and initialize a git repo in it."""
    dest = tmp_path / "golden"
    shutil.copytree(GOLDEN, dest)
    if _has_git():
        _git(["init", "-q"], str(dest))
        _git(["config", "user.email", "test@example.com"], str(dest))
        _git(["config", "user.name", "Test"], str(dest))
        _git(["config", "commit.gpgsign", "false"], str(dest))
        _git(["add", "-A"], str(dest))
        _git(["commit", "-q", "-m", "initial"], str(dest))
    return str(dest)


@pytest.fixture
def dirty_golden_repo(golden_repo):
    """Golden repo with one file mutated after commit (a dirty path)."""
    beta = os.path.join(golden_repo, "src", "beta.py")
    with open(beta, "a", encoding="utf-8") as fh:
        fh.write("\n# local uncommitted edit\n")
    return golden_repo
