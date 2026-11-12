import json
from pathlib import Path
from graphify.structural_index import build, view


def test_projection_preserves_incident_edges_duplicates_and_provenance(tmp_path):
    graph = tmp_path / 'graph.json'
    data = {'nodes': [{'id': str(i), 'label': 'same()' if i < 2 else f'n{i}',
                       'source_file': f'f{i}.ts', 'source_location': 'L1'} for i in range(80)],
            'links': [{'source': str(i), 'target': str((i+1)%80), 'relation': 'calls',
                       'confidence': 'EXTRACTED' if i%2 else 'INFERRED',
                       'source_file': f'f{i}.ts', 'source_location': 'L2'} for i in range(80)]}
    data['links'] += [dict(data['links'][0]), {'source': '3', 'target': '4', 'relation': 'imports', 'confidence': 'EXTRACTED'}]
    graph.write_text(json.dumps(data))
    assert build(graph)
    assert not build(graph)
    assert view(graph)['links'] == [data['links'][-1]]
    for key in ['0', '1', '3', '79']:
        projected = view(graph, key)
        assert [edge for edge in projected['links'] if key in (edge['source'], edge['target'])] == [
            edge for edge in data['links'] if key in (edge['source'], edge['target'])]
    assert {'0', '1'} <= {n['id'] for n in view(graph, 'same')['nodes']}
    assert view(graph, 'missing') == {'nodes': [], 'links': []}
    shard = next((tmp_path / 'structural-index').glob('n*.json'))
    shard.write_text('{}')
    assert build(graph)
    graph.write_text(json.dumps(data) + '\n')
    assert view(graph) is None


def test_selected_corrupt_projection_falls_back(tmp_path):
    graph = tmp_path / 'graph.json'
    graph.write_text(json.dumps({'nodes': [{'id': 'a', 'label': 'a'}], 'links': []}))
    build(graph)
    manifest = json.loads((tmp_path/'structural-index/manifest.json').read_text())
    (tmp_path/'structural-index'/f"n{manifest['ids']['a']:02}.json").write_text('{broken')
    assert view(graph, 'a') is None
    (tmp_path/'structural-index/imports.json').unlink()
    assert view(graph) is None


def test_copied_components_are_reused_only_after_content_verification(tmp_path):
    import shutil
    original=tmp_path/'original';original.mkdir()
    graph=original/'graph.json';graph.write_text(json.dumps({'nodes':[{'id':'a','label':'a'}],'links':[]}))
    build(graph)
    copied=tmp_path/'copied';shutil.copytree(original,copied)
    assert not build(copied/'graph.json')
    assert view(copied/'graph.json','a') == view(graph,'a')
    assert view(graph,'a') is not None


def test_interrupted_projection_build_never_matches_changed_graph(tmp_path, monkeypatch):
    import graphify.structural_index as module
    import pytest
    graph=tmp_path/'graph.json';graph.write_text(json.dumps({'nodes':[{'id':'a','label':'a'}],'links':[]}))
    build(graph)
    graph.write_text(json.dumps({'nodes':[{'id':'b','label':'b'}],'links':[]}))
    original=module.write
    def interrupted(path,data):
        original(path,data)
        raise OSError('interrupted')
    monkeypatch.setattr(module,'write',interrupted)
    with pytest.raises(OSError):build(graph)
    assert view(graph,'b') is None
    monkeypatch.setattr(module,'write',original)
    assert build(graph)
    assert view(graph,'b') is not None


def test_cli_projection_is_explicit_and_preserves_native_graph(tmp_path):
    import os
    import subprocess
    import sys
    source=tmp_path/'source';source.mkdir()
    (source/'a.ts').write_text('export function a() { return 1; }\n')
    output=tmp_path/'output'
    env=dict(os.environ,GRAPHIFY_OUT=str(output),GRAPHIFY_NO_AUTO_REFRESH='1',GRAPHIFY_STRUCTURAL_INDEX='0')
    command=[sys.executable,'-m','graphify','update',str(source),'--no-cluster']
    first=subprocess.run(command,env=env,capture_output=True,text=True)
    assert first.returncode == 0,first.stderr
    original=(output/'graph.json').read_bytes()
    assert not (output/'structural-index').exists()
    env['GRAPHIFY_STRUCTURAL_INDEX']='1'
    second=subprocess.run(command,env=env,capture_output=True,text=True)
    assert second.returncode == 0,second.stderr
    assert (output/'graph.json').read_bytes()==original
    assert view(output/'graph.json','a_a') is not None


def test_unicode_projection_uses_reproducible_utf8_bytes(tmp_path):
    graph=tmp_path/'graph.json'
    graph.write_text(json.dumps({'nodes':[{'id':'日本語','label':'日本語','source_file':'日本語.ts'}],'links':[]}),encoding='utf-8')
    build(graph)
    assert view(graph,'日本語')['nodes'][0]['label']=='日本語'
    for component in (tmp_path/'structural-index').glob('*.json'):
        json.loads(component.read_bytes().decode('utf-8'))
