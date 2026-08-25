"""Guard: the version has exactly one source of truth.

``pyproject.toml`` declares ``dynamic = ["version"]`` resolved from
``evidence_compiler.__version__``, so installed distribution metadata must
always match the in-package constant. A mismatch means the dynamic-version
wiring broke (e.g. the attr was moved or the static literal became a
computed expression setuptools cannot read).
"""

from __future__ import annotations

import importlib.metadata

import evidence_compiler


def test_distribution_version_matches_package_constant() -> None:
    try:
        dist_version = importlib.metadata.version("evidence-compiler")
    except importlib.metadata.PackageNotFoundError:
        # Running from a source tree without an install (e.g. PYTHONPATH-only
        # worktree runs); there is no second copy to drift, nothing to check.
        return
    assert dist_version == evidence_compiler.__version__
