"""Incremental JS barrels/importers must equal clean native full extraction."""
import json
import shutil

import pytest

import graphify.extract as extraction
from graphify.watch import _rebuild_code


def canonical(path):
    graph = json.loads(path.read_text())
    return {key: sorted(json.dumps(row, sort_keys=True) for row in graph.get(key, []))
            for key in ("nodes", "links", "hyperedges")}


@pytest.mark.parametrize("case", ["caller", "exporter", "barrel", "redirect", "addition", "deletion", "rename"])
def test_js_incremental_matches_clean_full(tmp_path, monkeypatch, case):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.ts").write_text('export function alpha() { return 1; }\n')
    (root / "b.ts").write_text('export { alpha } from "./a";\n')
    (root / "c.ts").write_text('import { alpha } from "./b";\nexport function use() { return alpha(); }\n')
    (root / "d.ts").write_text('export function alpha() { return 2; }\n')
    (root / "unrelated.ts").write_text('export const unused = 1;\n')
    assert _rebuild_code(root, acquire_lock=False, no_cluster=True)
    if case == "caller":
        (root / "c.ts").write_text('import { alpha } from "./b";\nexport function use() { return alpha() + 1; }\n')
    elif case == "exporter":
        (root / "a.ts").write_text('export function renamed() { return 3; }\n')
    elif case == "barrel":
        (root / "b.ts").write_text('export { alpha as beta } from "./a";\n')
    elif case == "redirect":
        (root / "b.ts").write_text('export { alpha } from "./d";\n')
    elif case == "addition":
        (root / "new.ts").write_text('export { alpha } from "./b";\n')
    elif case == "deletion":
        (root / "a.ts").unlink()
    else:
        (root / "a.ts").rename(root / "renamed.ts")
    batches = []
    real = extraction.extract
    def spy(paths, **kwargs):
        batches.append([path.name for path in paths])
        return real(paths, **kwargs)
    monkeypatch.setattr(extraction, "extract", spy)
    assert _rebuild_code(root, incremental=True, acquire_lock=False, no_cluster=True)
    incremental = canonical(root / "graphify-out/graph.json")
    if case in ("caller", "exporter", "barrel", "redirect"):
        assert all("unrelated.ts" not in batch for batch in batches)
    shutil.rmtree(root / "graphify-out")
    assert _rebuild_code(root, acquire_lock=False, no_cluster=True)
    assert incremental == canonical(root / "graphify-out/graph.json")
