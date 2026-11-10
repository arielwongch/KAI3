"""Offline identities for experiment provenance; never read environment secrets."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import os
import subprocess


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def code_identity():
    root = Path(__file__).resolve().parents[1]
    files = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted([*(root / 'src').glob('*.py'), *(root / 'tools').glob('*.py'),
                              *root.glob('requirements*.txt')])}
    revision = None
    dirty = None
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                          timeout=3, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root,
                                            timeout=3, stderr=subprocess.DEVNULL))
    except (OSError, subprocess.SubprocessError):
        pass
    return dict(revision=revision, working_tree_dirty=dirty,
                source_sha256=digest(files), source_files=files,
                source_scope='src/*.py; tools/*.py; requirements*.txt; hashes of actual working files')


def hardware_identity():
    return dict(system=platform.system(), machine=platform.machine(),
                processor=platform.processor() or None, logical_cpus=os.cpu_count(),
                python=platform.python_version())


def memory_identity(module):
    """Hash logical snapshots and actual embedding state separately."""
    result = dict(snapshot_sha256=digest(module.inspect()))
    children = getattr(module, 'components', None)
    if children is not None:
        result['components'] = {k: memory_identity(v) for k, v in children.items()}
    if hasattr(module, 'long_term'):
        result['long_term'] = memory_identity(module.long_term)
    records = getattr(module, '_records', getattr(module, '_facts', None))
    if records is not None:
        records = records.values() if isinstance(records, dict) else records
        result['embedded_state_sha256'] = digest([
            dict(entry=asdict(record[0]), vectors=record[1]) for record in records])
    return result
