"""Offline, reproducible comparison metrics. Never invoke a model on import."""
from copy import deepcopy
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def complete_sum(values):
    values = list(values)
    return sum(values) if values and all(number(v) for v in values) else None


def enrich_report(value):
    if not isinstance(value, dict) or not isinstance(value.get('cases'), list):
        raise ValueError('Upload a benchmark results object containing a cases array.')
    report = deepcopy(value)
    for field in ('memories', 'question_manifest'):
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
        rows.append(dict(module=module, overall=metrics, categories=categories))
    report['comparison'] = dict(version=1, added_fields=added, rows=rows,
        definitions=dict(accuracy='Correct / judged questions × 100; unavailable labels are excluded.',
                         tokens='Answer + judge provider tokens per recorded question; excludes ingestion.',
                         runtime='Recorded total seconds per question, including retrieval, answer and judge; excludes ingestion.',
                         storage='Sum of final UTF-8 stored text bytes across memory snapshots; excludes embeddings and runtime overhead.'))
    return report
