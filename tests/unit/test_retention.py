"""Bounded packet retention (``storage.prune_packets``): ordering, limit
enforcement, symlink safety, and path/name containment."""

from __future__ import annotations

import os

import pytest

from evidence_compiler.storage import prune_packets


def _packet_name(i: int) -> str:
    return f"2026-08-{i:02d}T00-00-00Z_0123456789abcdef.json"


def _make_packets(directory, count: int) -> list[str]:
    names = [_packet_name(i) for i in range(1, count + 1)]
    for name in names:
        (directory / name).write_text("{}", encoding="utf-8")
    return names


def test_prunes_oldest_beyond_limit(tmp_path):
    names = _make_packets(tmp_path, 10)
    deleted = prune_packets(str(tmp_path), 4)
    assert deleted == 6
    remaining = sorted(os.listdir(tmp_path))
    assert remaining == names[6:]  # newest 4 by timestamp order survive


def test_at_or_under_limit_deletes_nothing(tmp_path):
    _make_packets(tmp_path, 3)
    assert prune_packets(str(tmp_path), 3) == 0
    assert prune_packets(str(tmp_path), 250) == 0
    assert len(os.listdir(tmp_path)) == 3


def test_zero_or_negative_limit_disables_retention(tmp_path):
    _make_packets(tmp_path, 5)
    assert prune_packets(str(tmp_path), 0) == 0
    assert prune_packets(str(tmp_path), -1) == 0
    assert len(os.listdir(tmp_path)) == 5


def test_missing_directory_is_a_noop(tmp_path):
    assert prune_packets(str(tmp_path / "does-not-exist"), 1) == 0


def test_non_packet_files_are_never_deleted(tmp_path):
    _make_packets(tmp_path, 5)
    keep = ["README.md", "config.yaml", "hook.log", "notes.json",
            _packet_name(1) + ".tmp"]
    for name in keep:
        (tmp_path / name).write_text("keep", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    prune_packets(str(tmp_path), 1)
    survivors = set(os.listdir(tmp_path))
    for name in keep:
        assert name in survivors
    assert "subdir" in survivors
    assert _packet_name(5) in survivors


def test_symlinked_packet_is_neither_followed_nor_deleted(tmp_path):
    target_dir = tmp_path / "elsewhere"
    target_dir.mkdir()
    target = target_dir / _packet_name(1)
    target.write_text("{}", encoding="utf-8")
    packets = tmp_path / "packets"
    packets.mkdir()
    _make_packets(packets, 2)
    link = packets / _packet_name(9)  # sorts newest; would be "kept" if eligible
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        # Windows without symlink privilege: junctions only work for
        # directories, but a directory entry named like a packet exercises the
        # same "reparse point named *.json must survive" guarantee.
        try:
            import _winapi

            target_as_dir = target_dir / "dir-target"
            target_as_dir.mkdir()
            _winapi.CreateJunction(str(target_as_dir), str(link))
        except Exception:  # noqa: BLE001
            pytest.skip("symlinks/junctions not available on this platform")
    prune_packets(str(packets), 1)
    assert os.path.lexists(link)  # symlink untouched
    assert target.exists()  # target untouched

    def is_reparse(path) -> bool:
        return os.path.islink(path) or (
            hasattr(os.path, "isjunction") and os.path.isjunction(path)
        )

    # of the 2 real packets, only the newest survives alongside the link
    real = [n for n in os.listdir(packets) if not is_reparse(os.path.join(str(packets), n))]
    assert real == [_packet_name(2)]


def test_no_recursion_into_subdirectories(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    _make_packets(nested, 3)
    _make_packets(tmp_path, 2)
    prune_packets(str(tmp_path), 1)
    assert len(os.listdir(nested)) == 3  # untouched
