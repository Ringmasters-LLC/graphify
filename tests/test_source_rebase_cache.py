"""Repeated nodes share lexical rebasing, never data or reconciliation roots."""
from pathlib import Path
from unittest.mock import patch

import pytest

from graphify.build import _norm_source_file
from graphify.watch import _StoredSourcePaths


def paths(root, out):
    return _StoredSourcePaths({}, out=out, project_root=root, watch_root=root,
                              normalize_source=_norm_source_file)


@pytest.mark.parametrize("name", ["src/a.py", "../outside.py", "", None])
def test_repeated_rebase_matches_uncached(tmp_path, name):
    resolver = paths(tmp_path, tmp_path / "out")
    expected = resolver._rebased_source(name)
    with patch.object(resolver, "_rebased_source", wraps=resolver._rebased_source) as compute:
        for _ in range(100):
            item = {"source_file": name, "confidence": "INFERRED", "origin": "ast"}
            resolver.rebase_preserved(item)
            assert item == {"source_file": expected or name, "confidence": "INFERRED", "origin": "ast"}
        assert compute.call_count == (100 if name is None else 1)


def test_cache_is_scoped_to_reconciliation_roots(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    old = paths(first, tmp_path / "out")
    new = paths(second, tmp_path / "out")
    absolute = str(first / "src/a.py")
    left, right = {"source_file": absolute}, {"source_file": absolute}
    old.rebase_preserved(left)
    new.rebase_preserved(right)
    assert left["source_file"] == "src/a.py"
    assert right["source_file"] != left["source_file"]


def test_legacy_root_rebase_keeps_original_metadata(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / ".graphify_root").write_text(str(tmp_path))
    root = tmp_path / "moved"
    resolver = paths(root, out)
    item = {"source_file": "removed.py", "source_location": "L12", "id": "stable"}
    resolver.rebase_preserved(item)
    assert item == {"source_file": "removed.py", "source_location": "L12", "id": "stable"}
