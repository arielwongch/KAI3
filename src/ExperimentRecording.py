"""Run-owned, portable audit objects. Archives are never retrieval inputs."""
from collections import deque
from contextlib import nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from MemoryEntry import MemoryEntry

VERSION = 1
active_archive = ContextVar('experiment_archive', default=None)
checkpoint = ContextVar('experiment_checkpoint', default=None)
operation = ContextVar('experiment_operation', default=None)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha256(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def new_archive():
    return dict(version=VERSION, layout='inline-run-owned-sha256-v1', artifacts={})


def put(archive, kind, value):
    obj = dict(kind=kind, value=deepcopy(value))
    identity = sha256(obj)
    existing = archive['artifacts'].setdefault(identity, obj)
    if existing != obj:
        raise ValueError('Artifact identity collision: ' + identity)
    return {'artifact_sha256': identity}


def get(archive, reference, kind=None):
    try:
        identity = reference['artifact_sha256']
        obj = archive['artifacts'][identity]
        if sha256(obj) != identity or (kind is not None and obj['kind'] != kind):
            raise ValueError('Corrupt or incompatible artifact: ' + str(identity))
        return deepcopy(obj['value'])
    except (KeyError, TypeError) as error:
        raise ValueError('Missing or invalid artifact reference: ' + str(reference)) from error


def capture(kind, value):
    archive = active_archive.get()
    return put(archive, kind, value) if archive is not None else None


def check_compatibility(previous, current):
    for field in ('code_identity', 'dependency_versions', 'embedding_identity',
                  'answer_settings', 'judge_settings', 'memory_model_settings'):
        before, after = previous.get(field), current.get(field)
        if field == 'code_identity':
            before, after = (before or {}).get('source_sha256'), (after or {}).get('source_sha256')
        if before != after:
            raise ValueError('Frozen-state execution requires matching ' + field)


def validate(report):
    """Validate all objects and links, including unreferenced failed work."""
    if not isinstance(report, dict):
        raise ValueError('An experiment report must be a JSON object.')
    archive = report.get('recording')
    if archive is None:
        if (report.get('recording_contract') or {}).get('version', 0) >= 1:
            raise ValueError('Missing experiment recording archive; this is not a legacy report.')
        return  # Legacy reports have no exact-reconstruction guarantee.
    if (not isinstance(archive, dict) or archive.get('version') != VERSION
            or archive.get('layout') != 'inline-run-owned-sha256-v1'
            or not isinstance(archive.get('artifacts'), dict)):
        raise ValueError('Unsupported or incomplete experiment recording archive.')
    for identity, obj in archive['artifacts'].items():
        if (not isinstance(obj, dict) or set(obj) != {'kind', 'value'}
                or not isinstance(obj['kind'], str) or sha256(obj) != identity):
            raise ValueError('Corrupt artifact: ' + str(identity))

    def visit(value):
        if isinstance(value, dict):
            if set(value) == {'artifact_sha256'}:
                get(archive, value)
            else:
                for item in value.values():
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(report)
    if (report.get('recording_contract') or {}).get('version') == VERSION:
        for case in report.get('cases', []):
            if case.get('prediction') is None:
                continue
            d = case.get('diagnostics', {})
            context = get(archive, d.get('context_artifact'), 'answer-context')
            prediction = get(archive, case.get('prediction_artifact'), 'prediction')
            if (context.get('memory_state_artifact') != d.get('memory_state_artifact')
                    or context.get('supplied_context') != d.get('supplied_context')
                    or prediction.get('text') != case['prediction']
                    or prediction.get('context_artifact') != d.get('context_artifact')
                    or prediction.get('memory_state_artifact') != d.get('memory_state_artifact')):
                raise ValueError('Prediction, memory and context artifact identities disagree.')
            get(archive, d.get('memory_state_artifact'), 'memory-state')


# State is explicitly bounded to these architectures and fields. Services and
# credentials cannot enter the codec, and incoming JSON never names import paths.
CLASSES = {'NoMemory', 'SlidingWindow', 'Summarization', 'VectorStore',
           'VectorStoreReranker', 'FactStore', 'TemporalFactStore', 'HybridMemory',
           'Alpha', 'Beta', 'Gamma', 'WindowedSummarization', 'WindowedFactStore', 'Compaction'}
SERVICES = {'embedder', 'extractor', 'tokenizer', 'reranker', 'compressor', '_lock'}
CHILDREN = {'components', 'window', 'long_term'}
FIELDS = {'buffer', 'evicted_count', 'summary_limit', 'summary', 'max_summary_tokens',
          'truncated', 'max_stored_entries', '_records', '_facts', '_next_id', '_revision',
          'candidate_k', '_pending', 'mode', 'hybrid_shares', 'component_options',
          'memory_context_tokens', 'component_usage', 'options', '_entries', 'events',
          'depth', 'ingested_entries', 'omitted_source_entries', 'peak_active_tokens'}


def encode(value):
    if isinstance(value, MemoryEntry):
        return {'type': 'entry', 'value': asdict(deepcopy(value))}
    if isinstance(value, deque):
        return {'type': 'deque', 'maxlen': value.maxlen, 'items': [encode(v) for v in value]}
    if isinstance(value, tuple):
        return {'type': 'tuple', 'items': [encode(v) for v in value]}
    if isinstance(value, dict):
        return {'type': 'mapping', 'items': [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError('Unsupported logical state value: ' + type(value).__name__)


def decode(value):
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    tag = value.get('type')
    if tag == 'entry':
        entry = value['value']
        if not isinstance(entry.get('text'), str) or not isinstance(entry.get('metadata'), dict):
            raise ValueError('Invalid memory entry in frozen state.')
        return MemoryEntry(**deepcopy(entry))
    if tag == 'mapping':
        return {decode(k): decode(v) for k, v in value['items']}
    if tag == 'tuple':
        return tuple(decode(v) for v in value['items'])
    if tag == 'deque':
        return deque((decode(v) for v in value['items']), maxlen=value['maxlen'])
    raise ValueError('Unsupported frozen state encoding.')


def freeze(module, archive):
    """Include logical state, vectors, pending buffers and recursive components."""
    name = type(module).__name__
    if name not in CLASSES:
        raise ValueError('Unsupported frozen architecture: ' + name)
    with getattr(module, '_lock', nullcontext()):
        method_overrides = {k for k in vars(module) if callable(getattr(type(module), k, None))}
        unexpected = set(vars(module)) - FIELDS - SERVICES - CHILDREN - {'audit_archive'} - method_overrides
        if unexpected:
            raise ValueError('Unrecorded memory fields: ' + ', '.join(sorted(unexpected)))
        fields = {k: encode(v) for k, v in vars(module).items() if k in FIELDS}
        children = {}
        for key in CHILDREN & vars(module).keys():
            child = getattr(module, key)
            children[key] = ({k: freeze(v, archive) for k, v in child.items()}
                             if key == 'components' else freeze(child, archive))
        audit = getattr(module, 'audit_archive', None)
        if audit:
            archive['artifacts'].update(deepcopy(audit['artifacts']))
        return put(archive, 'memory-state', dict(version=1, architecture=name,
                   fields=fields, children=children))


def restore(module, archive, reference):
    """Validate the complete tree before applying any fields to the module."""
    pending = []

    def stage(target, ref):
        state = get(archive, ref, 'memory-state')
        if state.get('version') != 1 or state.get('architecture') != type(target).__name__:
            raise ValueError('Frozen memory architecture/version mismatch.')
        expected = set(vars(target)) & FIELDS
        if set(state.get('fields', {})) != expected:
            raise ValueError('Frozen memory fields mismatch.')
        if set(state.get('children', {})) != CHILDREN & vars(target).keys():
            raise ValueError('Frozen memory components mismatch.')
        values = {k: decode(v) for k, v in state['fields'].items()}
        for key in ('max_stored_entries', 'summary_limit', 'max_summary_tokens', 'candidate_k',
                    'mode', 'hybrid_shares', 'component_options', 'memory_context_tokens', 'options'):
            if key in values and values[key] != getattr(target, key):
                raise ValueError('Frozen memory settings mismatch: ' + key)
        if 'buffer' in values and (not isinstance(values['buffer'], deque)
                or values['buffer'].maxlen != target.buffer.maxlen):
            raise ValueError('Frozen memory window capacity mismatch.')
        for key in ('_next_id', '_revision', 'evicted_count', 'depth', 'ingested_entries',
                    'omitted_source_entries', 'peak_active_tokens'):
            if key in values and (type(values[key]) is not int or values[key] < 0):
                raise ValueError('Invalid frozen state counter: ' + key)
        for key, child in state['children'].items():
            if key == 'components':
                if set(child) != set(target.components):
                    raise ValueError('Frozen memory component names mismatch.')
                for name, child_ref in child.items():
                    stage(target.components[name], child_ref)
            else:
                stage(getattr(target, key), child)
        pending.append((target, values))

    stage(module, reference)
    for target, values in pending:
        vars(target).update(values)
        if hasattr(target, 'audit_archive'):
            target.audit_archive = new_archive()
            target.audit_archive['artifacts'] = {k: deepcopy(v) for k, v in archive['artifacts'].items()
                if v['kind'].startswith('compaction-')}


def polling_view(report):
    """Keep old diagnostic fields; omit only payloads owned by the archive."""
    value = deepcopy(report)
    if 'recording' in value:
        archive = value['recording']
        archive['artifact_count'] = len(archive['artifacts'])
        archive.pop('artifacts')
        archive['payloads_omitted'] = True
    return value


def archive_metrics(archive):
    objects = archive['artifacts']
    return dict(audit_artifact_count=len(objects),
                audit_archive_bytes=len(canonical(archive)),
                artifact_payload_bytes=sum(len(canonical(v)) for v in objects.values()))


def state_storage(archive, reference):
    """Separate logical serialization from the deduplicated frozen artifact tree."""
    seen = set()

    def logical(ref):
        state = get(archive, ref, 'memory-state')
        seen.add(ref['artifact_sha256'])
        return dict(architecture=state['architecture'],
            fields={k: v for k, v in state['fields'].items() if k not in ('events', 'component_usage')},
            children={key: ({name: logical(child) for name, child in value.items()}
                            if key == 'components' else logical(value))
                      for key, value in state['children'].items()})

    active = len(canonical(logical(reference)))
    return dict(active_logical_state_serialized_bytes=active,
        frozen_snapshot_artifact_bytes=sum(len(canonical(archive['artifacts'][identity])) for identity in seen),
        definitions='active: encoded logical fields/config/children including vectors, excluding events and usage; frozen: deduplicated state envelopes including audit references; neither is resident RAM')
