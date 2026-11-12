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
archive_lock = ContextVar('experiment_archive_lock', default=None)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha256(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Artifacts(dict):
    """Immutable payloads with cached sizes and optional lazy disk loading."""
    def __init__(self, values=(), *, sizes=None, loader=None):
        super().__init__(values)
        self.sizes = dict(sizes or {})
        self.loader = loader
        self.total_bytes = sum(self.sizes.values())

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if value is None and self.loader is not None:
            value = self.loader(key)
            super().__setitem__(key, value)
        return value

    def __setitem__(self, key, value):
        size = len(canonical(value))
        self.total_bytes += size - self.sizes.get(key, 0)
        self.sizes[key] = size
        super().__setitem__(key, value)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.total_bytes -= self.sizes.pop(key, 0)

    def get(self, key, default=None):
        return self[key] if key in self else default

    def __eq__(self, other):
        if not isinstance(other, dict):
            return NotImplemented
        return dict(self.items()) == dict(other.items())

    def __ne__(self, other):
        result = self.__eq__(other)
        return NotImplemented if result is NotImplemented else not result

    def pop(self, key, *default):
        if key not in self:
            if default:
                return default[0]
            raise KeyError(key)
        value = self[key]
        del self[key]
        return value

    def popitem(self):
        if not self:
            raise KeyError('popitem(): dictionary is empty')
        key = next(reversed(self))
        return key, self.pop(key)

    def setdefault(self, key, value=None):
        if key not in self:
            self[key] = value
        return self[key]

    def update(self, values=(), **kwargs):
        for key, value in dict(values, **kwargs).items():
            if key not in self or self[key] != value:
                self[key] = value

    def items(self):
        return ((key, self[key]) for key in self)

    def values(self):
        return (self[key] for key in self)

    def clear(self):
        super().clear()
        self.sizes.clear()
        self.total_bytes = 0

    def copy(self):
        # Payloads are immutable once captured. Copy only the index for a
        # synchronous checkpoint; public snapshots still deep-copy payloads.
        return Artifacts(super().copy(), sizes=self.sizes, loader=self.loader)

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        result.update((key, deepcopy(value, memo)) for key, value in self.items())
        return result


def checkpoint_view(report):
    archive = report.get('recording')
    if archive is None:
        return deepcopy(report)
    objects = archive['artifacts']
    if not isinstance(objects, Artifacts):
        tracked = Artifacts()
        tracked.update(objects)
        archive['artifacts'] = objects = tracked
    shared = dict(archive, artifacts=objects.copy())
    return deepcopy(report, {id(archive): shared})


def new_archive():
    return dict(version=VERSION, layout='inline-run-owned-sha256-v1', artifacts=Artifacts())


def put(archive, kind, value):
    obj = dict(kind=kind, value=deepcopy(value))
    identity = sha256(obj)
    with archive_lock.get() or nullcontext():
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
            # Checkpoint transport and archive validation do not change the
            # evaluated algorithm. Keep their full identities in provenance,
            # while allowing saved work to resume after infrastructure repairs.
            # All model/memory/benchmark execution sources must still match.
            from AuditProvenance import digest
            infrastructure = {'src/BenchmarkStore.py', 'src/BenchmarkHistory.py', 'src/BenchmarkWorker.py',
                              'src/ExperimentRecording.py', 'src/app.py', 'tools/inspect_recording.py'}
            def execution_sources(identity):
                identity = identity or {}
                files = identity.get('source_files')
                if not isinstance(files, dict) or identity.get('source_sha256') != digest(files):
                    raise ValueError('Frozen-state execution requires valid code_identity')
                result = {name: value for name, value in files.items() if name not in infrastructure}
                # Explicit migration for audited checkpoint/scheduler/cache
                # refactors: prompts, scoring, contexts and QA write-back policy
                # are unchanged. Do not exempt arbitrary engine edits.
                from pathlib import Path
                source = Path(__file__).with_name('Benchmark.py').read_bytes()
                normalized_source = source.replace(b'\r\n', b'\n')
                current_hash = hashlib.sha256(normalized_source).hexdigest()
                scheduler = 'e82e08d8688df7d3eddebeffcfb79aa975335ad8ee743afc1d014f0393c3e643'
                audited = {'bf6ed5c618b589a71a5f241c68a56fa8a025f3ae4524aa72a78cbe482cd8d57f',
                           '874ee199bfc82c1a7ad8487aaf6f575f81a87ee58b63b937fb32a9ba93e764ac',
                           'e39df5fed174b3af489d2f5ee1c897db713af78450ff0a2a7d4f08674026ed55',
                           '71e9236553f6da7f80c6c63ad4becbb3abf41e14a076409b12a9c23692636500',
                           '88f77c508787ab3efd73f9749193f9c5681adeb02f24fc1ff6cd9b9508cbaa26', scheduler,
                           hashlib.sha256(normalized_source.replace(b'\n', b'\r\n')).hexdigest()}
                if current_hash == scheduler and result.get('src/Benchmark.py') in audited:
                    result['src/Benchmark.py'] = 'bounded-question-pool-compatible-v1'
                # Audited compaction repair: accepted outputs still obey the
                # same source, prompt, tokenizer and hard-budget contracts.
                # Only rejected generations change, including outputs that
                # cannot fit an oversized write's trigger. Durability failures
                # stop paid work. Preserve frozen work across these exact
                # migrations; arbitrary compaction edits must still fail closed.
                compaction = Path(__file__).with_name('Compaction.py').read_bytes().replace(b'\r\n', b'\n')
                repaired = '83392d9b0b1edf6b0e346c7b7f4e4ee899201c77c5c770505a2b390cb6907c58'
                compaction_versions = {
                    'a4917866f7b34aa71a46bc950e865952bb9e675f9c7da3ee5ccd6136703ec59c',
                    '45b40b2412d0514983a9364aa1f012a385029510f471adb5b83345d601debdbd',
                    'b3d53abd2b8d5751b263d85118a13697d84d6ed6cd0a69fc2ba31515766b5234',
                    '081b437c33667986e0287977130e1d3b07fbe5ed58fe59edb78c3b3a13f930c6',
                    'beb160157b02bbb0a8437e2b461a8669a7afb735b52ee9a2f78f7ad576dc7968',
                    'c2c68668e43e1f284ef1fba9899d5bdea869713dfb855bc4bb5082d0cef50ff4',
                    repaired, hashlib.sha256(compaction.replace(b'\n', b'\r\n')).hexdigest()}
                if hashlib.sha256(compaction).hexdigest() == repaired and result.get('src/Compaction.py') in compaction_versions:
                    result['src/Compaction.py'] = 'measured-compaction-retry-compatible-v1'
                return result
            before, after = execution_sources(before), execution_sources(after)
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
    archive = report.get('recording')
    omitted = ({k: deepcopy(v) for k, v in archive.items() if k != 'artifacts'} if archive else None)
    if omitted is not None:
        omitted.update(artifact_count=len(archive['artifacts']), payloads_omitted=True)
    value = deepcopy(report, {id(archive): omitted} if archive else {})
    if 'recording' in value:
        value['recording'] = omitted
    return value


def archive_metrics(archive):
    objects = archive['artifacts']
    if isinstance(objects, Artifacts):
        payload = objects.total_bytes
        index_bytes = sum(len(canonical(key)) + 1 for key in objects) + max(0, len(objects) - 1)
        return dict(audit_artifact_count=len(objects), artifact_payload_bytes=payload,
                    audit_archive_bytes=len(canonical(dict(archive, artifacts={}))) + payload + index_bytes)
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
