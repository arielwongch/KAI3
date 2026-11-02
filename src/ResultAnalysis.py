"""Offline, reproducible comparison metrics. Never invoke a model on import."""
from copy import deepcopy
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def complete_sum(values):
    values = list(values)
    return sum(values) if values and all(number(v) for v in values) else None


def percentile(values, fraction):
    values = sorted(v for v in values if number(v))
    if not values:
        return None
    position = (len(values)-1)*fraction
    lo = int(position)
    hi = min(lo+1, len(values)-1)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


def phase_tokens(diagnostics, phase):
    requests = diagnostics.get('provider_requests')
    if isinstance(requests, list):
        records = [r for r in requests if r.get('phase') == phase]
        if records:
            return complete_sum(r.get('tokens') for r in records)
        return 0 if diagnostics.get(phase + '_llm_calls') == 0 else None
    return diagnostics.get(phase + '_tokens')


def lifecycle_metrics(report, module, cases):
    """Recorded run cost, including previous ingestion attempts exactly once."""
    builds, seen, conflicting = [], {}, False
    for memory in [*report.get('previous_ingestions', []), *report.get('memories', [])]:
        if str(memory.get('module', 'unknown')) != module:
            continue
        ingestion = memory.get('ingestion', {})
        identity = ingestion.get('ingestion_id')
        if identity is not None and identity in seen:
            conflicting |= seen[identity] != ingestion
            continue
        if identity is not None:
            seen[identity] = ingestion
        builds.append(ingestion)
    ds = [c.get('diagnostics', {}) for c in cases]
    phases = {}
    for phase, diagnostics in (('memory', builds), ('answer', ds), ('judge', ds)):
        values = [phase_tokens(d, phase) for d in diagnostics]
        phases[phase] = dict(tokens=complete_sum(values), known_count=sum(number(v) for v in values),
                             record_count=len(values))
    ingestion_time = complete_sum(d.get('total_seconds') for d in builds)
    query_times = [d.get('execution_total_seconds', d.get('total_seconds')) for d in ds]
    query_time = complete_sum(query_times)
    if conflicting:
        phases['memory']['tokens'] = None
        ingestion_time = None
    retrieval = [d.get('retrieval_seconds') for d in ds]
    return dict(scope='all recorded ingestion builds and retained question attempts; no amortization',
        ingestion=phases['memory'], answer=phases['answer'], judge=phases['judge'],
        total_provider_tokens=complete_sum(phases[p]['tokens'] for p in ('memory', 'answer', 'judge')),
        ingestion_seconds=ingestion_time, query_seconds=query_time,
        total_seconds=complete_sum([ingestion_time, query_time]),
        ingestion_runtime_count=sum(number(d.get('total_seconds')) for d in builds),
        query_runtime_count=sum(number(v) for v in query_times),
        ingestion_count=len(builds), conflicting_ingestion_ids=conflicting,
        request_ledger_complete=bool(ds) and bool(builds) and all(
            isinstance(d.get('provider_requests'), list) or d.get('memory_llm_calls') == 0
            for d in builds) and all(isinstance(d.get('provider_requests'), list) for d in ds),
        retrieval=dict(count=sum(number(v) for v in retrieval),
                       p50_seconds=percentile(retrieval, .5), p95_seconds=percentile(retrieval, .95),
                       scope='recorded retrieval and packing; consult per-case cache state'))


def enrich_report(value):
    if not isinstance(value, dict) or not isinstance(value.get('cases'), list):
        raise ValueError('Upload a benchmark results object containing a cases array.')
    report = deepcopy(value)
    for field in ('memories', 'question_manifest', 'previous_ingestions'):
        if field in report and not isinstance(report[field], list):
            raise ValueError(f'{field} must be an array.')
    previous = report.get('comparison')
    added = list(previous.get('added_fields', [])) if isinstance(previous, dict) and isinstance(previous.get('added_fields'), list) else []
    for index, case in enumerate(report['cases']):
        if not isinstance(case, dict) or not isinstance(case.get('diagnostics', {}), dict):
            raise ValueError('Each case must be an object with object diagnostics.')
        d = case.setdefault('diagnostics', {})
        for total, parts in (('answer_tokens', ('prompt_tokens', 'completion_tokens')),
                             ('judge_tokens', ('judge_prompt_tokens', 'judge_completion_tokens'))):
            if d.get(total) is None:
                result = complete_sum(d.get(p) for p in parts)
                if result is not None:
                    d[total] = result
                    added.append(f'cases[{index}].diagnostics.{total}')
    for index, memory in enumerate(report.get('memories', [])):
        if not isinstance(memory, dict) or not isinstance(memory.get('ingestion', {}), dict):
            raise ValueError('Each memory must be an object with object ingestion.')
        snapshot = memory.get('memory', {})
        ingestion = memory.get('ingestion', {})
        if not isinstance(snapshot, dict) or not isinstance(ingestion.get('final_storage', {}), dict):
            raise ValueError('Memory snapshots and final_storage must be objects.')
        entries = snapshot.get('entries')
        if isinstance(entries, list) and all(isinstance(e, dict) and isinstance(e.get('text'), str) for e in entries):
            storage = memory.setdefault('ingestion', {}).setdefault('final_storage', {})
            for key, result in (('stored_text_bytes', sum(len(e['text'].encode('utf-8')) for e in entries)), ('stored_entries', len(entries))):
                if storage.get(key) is None:
                    storage[key] = result
                    added.append(f'memories[{index}].ingestion.final_storage.{key}')
        if ingestion.get('memory_tokens') is None:
            result = complete_sum(ingestion.get(k) for k in ('memory_prompt_tokens', 'memory_completion_tokens'))
            if result is not None:
                memory.setdefault('ingestion', {})['memory_tokens'] = result
                added.append(f'memories[{index}].ingestion.memory_tokens')
    manifest = report.get('question_manifest', [])
    if any(not isinstance(item, dict) for item in manifest):
        raise ValueError('Each manifest item must be an object.')

    def group(cases, selected):
        judged = [c['correct'] for c in cases if type(c.get('correct')) in (bool, int, float) and c['correct'] in (0, 1)]
        token_values = [complete_sum(c.get('diagnostics', {}).get(k) for k in ('answer_tokens', 'judge_tokens')) for c in cases]
        times = [c.get('diagnostics', {}).get('total_seconds') for c in cases]
        known_tokens = [v for v in token_values if v is not None]
        known_times = [v for v in times if number(v)]
        return dict(case_count=len(cases), selected_count=selected, judged_count=len(judged),
                    accuracy_percent=100 * sum(judged) / len(judged) if judged else None,
                    completion_percent=100 * len(judged) / selected if selected else None,
                    success_percent=100 * sum(judged) / selected if selected else None,
                    mean_question_tokens=sum(known_tokens)/len(known_tokens) if known_tokens else None,
                    token_count=len(known_tokens), total_question_tokens=complete_sum(token_values),
                    mean_question_seconds=sum(known_times)/len(known_times) if known_times else None,
                    runtime_count=len(known_times), total_question_seconds=complete_sum(times))

    modules = list(dict.fromkeys(str(c.get('module', 'unknown')) for c in [*report['cases'], *manifest]))
    rows = []
    for module in modules:
        cases = [c for c in report['cases'] if str(c.get('module', 'unknown')) == module]
        selected = [c for c in manifest if str(c.get('module', 'unknown')) == module]
        metrics = group(cases, len(selected) if manifest else len(cases))
        categories = {}
        for category in sorted({str(c.get('category', 'unknown')) for c in [*cases, *selected]}):
            subset = [c for c in cases if str(c.get('category', 'unknown')) == category]
            count = sum(str(c.get('category', 'unknown')) == category for c in selected) if manifest else len(subset)
            categories[category] = group(subset, count)
        memories = [m for m in report.get('memories', []) if str(m.get('module', 'unknown')) == module]
        sizes = []
        for memory in memories:
            size = memory.get('ingestion', {}).get('final_storage', {}).get('stored_text_bytes')
            if not number(size):
                entries = memory.get('memory', {}).get('entries')
                if isinstance(entries, list) and all(isinstance(e, dict) and isinstance(e.get('text'), str) for e in entries):
                    size = sum(len(e['text'].encode('utf-8')) for e in entries)
            sizes.append(size)
        metrics['stored_text_bytes'] = complete_sum(sizes)
        metrics['storage_count'] = sum(number(v) for v in sizes)
        metrics['memory_count'] = len(memories)
        metrics['lifecycle'] = lifecycle_metrics(report, module, cases)
        rows.append(dict(module=module, overall=metrics, categories=categories))
    report['comparison'] = dict(version=1, added_fields=added, rows=rows,
        definitions=dict(accuracy='Correct / judged questions × 100; unavailable labels are excluded.',
                         tokens='Answer + judge provider tokens per recorded question; excludes ingestion.',
                         runtime='Recorded total seconds per question, including retrieval, answer and judge; excludes ingestion.',
                         lifecycle='All recorded ingestion builds (including resumed builds) + retained question attempts. Unknown usage stays unavailable; legacy data may omit failed attempts. No amortization.',
                         storage='Sum of final UTF-8 stored text bytes across memory snapshots; excludes embeddings and runtime overhead.'))
    return report
