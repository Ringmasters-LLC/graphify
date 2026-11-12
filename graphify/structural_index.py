"""Disposable, exact read projections of graph.json; no parser or query daemon.

Readers validate graph identity and selected component identities. Any missing,
corrupt or incompatible component means ordinary authoritative-graph fallback.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile

SCHEMA = 2
BUCKETS = 32
IMPORTS = {'imports', 'imports_from', 're_exports'}


def signature(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def bucket(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % BUCKETS


def write(path, data):
    fd, name = tempfile.mkstemp(prefix='.query-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            encoded = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
            target.write(encoded)
        os.replace(name, path)
        return hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    finally:
        Path(name).unlink(missing_ok=True)


def build(graph):
    graph = Path(graph)
    root = graph.parent / 'structural-index'
    root.mkdir(exist_ok=True)
    try:
        previous = json.loads((root / 'manifest.json').read_text())
        expected = {f'n{index:02}.json' for index in range(BUCKETS)} | {'imports.json'}
        if previous['schema'] == SCHEMA and set(previous['files']) == expected:
            if (previous['graph'] == signature(graph)
                    and all(signature(root/name) == row['signature'] for name,row in previous['files'].items())):
                return False
            # Copies into private generations change inode/ctime. Reuse exact
            # component bytes only after content digests prove equivalence.
            graph_before = signature(graph)
            files_before = {name: signature(root/name) for name in previous['files']}
            if (previous['graph_sha256'] == digest(graph)
                    and all(digest(root/name) == row['sha256'] for name,row in previous['files'].items())
                    and signature(graph) == graph_before
                    and all(signature(root/name) == sig for name,sig in files_before.items())):
                previous['graph'] = graph_before
                for name,row in previous['files'].items():
                    row['signature'] = files_before[name]
                write(root/'manifest.json', previous)
                return False
    except (OSError, ValueError, KeyError, TypeError):
        pass
    before = signature(graph)
    encoded = graph.read_bytes()
    graph_checksum = hashlib.sha256(encoded).hexdigest()
    data = json.loads(encoded)
    del encoded
    nodes = {node['id']: {key: node[key] for key in ('id', 'label', 'source_file', 'source_location') if key in node}
             for node in data['nodes']}
    labels, groups = {}, [{'nodes': {}, 'links': []} for _ in range(BUCKETS)]
    for key, node in nodes.items():
        groups[bucket(key)]['nodes'][key] = node
        labels.setdefault(node.get('label', ''), []).append(key)
    imports = []
    for ordinal, edge in enumerate(data['links']):
        if edge.get('relation') in IMPORTS:
            imports.append(edge)
        for index in {bucket(edge['source']), bucket(edge['target'])}:
            group = groups[index]
            group['links'].append([ordinal, edge])
            for key in (edge['source'], edge['target']):
                if key in nodes:
                    group['nodes'][key] = nodes[key]
    files = {}
    for index, group in enumerate(groups):
        name = f'n{index:02}.json'
        checksum = write(root / name, group)
        files[name] = {'signature': signature(root/name), 'sha256': checksum}
    checksum = write(root / 'imports.json', {'nodes': list(nodes.values()), 'links': imports})
    files['imports.json'] = {'signature': signature(root/'imports.json'), 'sha256': checksum}
    if signature(graph) != before:
        raise RuntimeError('graph changed while deriving structural index')
    write(root / 'manifest.json', {'schema': SCHEMA, 'graph': before, 'labels': labels,
                                  'ids': {key: bucket(key) for key in nodes}, 'files': files, 'graph_sha256': graph_checksum})
    return True


def view(graph, symbol=None):
    """Return exact import-only or incident-edge query inputs, otherwise None."""
    graph = Path(graph)
    root = graph.parent / 'structural-index'
    try:
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest['schema'] != SCHEMA or manifest['graph'] != signature(graph):
            return None
        if symbol is None:
            names = ['imports.json']
        else:
            label = symbol.rsplit('::', 1)[-1]
            ids = ([symbol] if symbol in manifest['ids'] else
                   manifest['labels'].get(label, []) + manifest['labels'].get(label + '()', []))
            indexes = {manifest['ids'][key] for key in ids}
            if any(not isinstance(index, int) or not 0 <= index < BUCKETS for index in indexes):
                return None
            names = [f'n{index:02}.json' for index in sorted(indexes)]
        nodes, indexed = {}, {}
        for name in names:
            path = root / name
            if signature(path) != manifest['files'][name]['signature']:
                return None
            data = json.loads(path.read_text())
            if symbol is None:
                return data if signature(path) == manifest['files'][name]['signature'] else None
            nodes.update(data['nodes'])
            # Native ordinals preserve even exact duplicate links while
            # avoiding double-counting one link carried by two buckets.
            for ordinal, edge in data['links']:
                indexed[ordinal] = edge
            if signature(path) != manifest['files'][name]['signature']:
                return None
        return {'nodes': list(nodes.values()), 'links': [indexed[key] for key in sorted(indexed)]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
