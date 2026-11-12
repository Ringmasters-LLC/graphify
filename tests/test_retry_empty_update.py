import json
import graphify.extract as extraction
import graphify.watch as watch


def test_unrepresented_failures_retry_without_reconciling_and_can_heal(tmp_path, monkeypatch):
    (tmp_path/'good.py').write_text('def good(): return 1\n')
    (tmp_path/'recover.py').write_text('def recovered(): return 2\n')
    real = extraction._safe_extract_with_xaml_root
    def fail(extractor, path, root):
        return {'nodes': [], 'edges': [], 'error': 'transient'} if path.name == 'recover.py' else real(extractor,path,root)
    monkeypatch.setattr(extraction, '_safe_extract_with_xaml_root', fail)
    assert watch._rebuild_code(tmp_path, no_cluster=True, acquire_lock=False)
    graph=tmp_path/'graphify-out/graph.json'
    before=graph.read_bytes()
    reconcile=watch._reconcile_existing_graph
    def forbidden(*args,**kwargs):
        raise AssertionError('empty retry must not reconcile')
    monkeypatch.setattr(watch, '_reconcile_existing_graph', forbidden)
    assert watch._rebuild_code(tmp_path, incremental=True, no_cluster=True, acquire_lock=False)
    assert graph.read_bytes() == before
    monkeypatch.setattr(watch, '_reconcile_existing_graph', reconcile)
    monkeypatch.setattr(extraction, '_safe_extract_with_xaml_root', real)
    assert watch._rebuild_code(tmp_path, incremental=True, no_cluster=True, acquire_lock=False)
    assert any(n.get('label')=='recovered()' for n in json.loads(graph.read_text())['nodes'])
