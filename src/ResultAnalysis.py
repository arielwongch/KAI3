"""Offline, reproducible comparison metrics. Never invoke a model on import."""
from copy import deepcopy
from functools import lru_cache
import math
import re


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
    value = diagnostics.get(phase + '_tokens')
    if value is not None:
        return value
    if diagnostics.get(phase + '_llm_calls') == 0:
        return 0
    prefix = '' if phase == 'answer' else phase + '_'
    return complete_sum(diagnostics.get(prefix + key) for key in ('prompt_tokens', 'completion_tokens'))


def phase_usage(diagnostics, phase):
    """Separate complete totals from known recorded usage; unknown is never zero."""
    total = phase_tokens(diagnostics, phase)
    requests = diagnostics.get('provider_requests')
    records = [r for r in requests if r.get('phase') == phase] if isinstance(requests, list) else []
    missing = [r for r in records if not number(r.get('tokens'))]
    return dict(tokens=total,
        known_recorded_tokens=sum(r['tokens'] for r in records if number(r.get('tokens'))) if records else (total if number(total) else 0),
        missing_request_count=len(missing),
        missing_failed_request_count=sum(r.get('status') == 'error' for r in missing),
        request_count=len(records),
        records_without_ledger=int(not isinstance(requests, list)),
        unknown_record_count=int(not number(total)))


def usage_coverage(usages):
    usages = list(usages)
    result = {key: sum(u[key] for u in usages) for key in (
        'known_recorded_tokens', 'missing_request_count', 'missing_failed_request_count',
        'request_count', 'records_without_ledger', 'unknown_record_count')}
    result['usage_complete'] = bool(usages) and not result['unknown_record_count']
    result['semantics'] = 'known recorded usage; lower bound, not monetary cost'
    return result


@lru_cache(maxsize=1)
def _context_tokenizer():
    """Load only the pinned local tokenizer artifact; never download or call a model."""
    try:
        from huggingface_hub import try_to_load_from_cache
        from tokenizers import Tokenizer
        from MemoryContext import TOKENIZER_REVISION
        from Embeddings import MODEL_NAME
        path = try_to_load_from_cache(MODEL_NAME, 'tokenizer.json', revision=TOKENIZER_REVISION)
    except (ImportError, OSError, ValueError):
        return None
    if not isinstance(path, str):
        return None
    try:
        tokenizer = Tokenizer.from_file(path)
    except Exception:
        # Native tokenizer parsing errors use the base Exception type.
        return None
    # Cached artifacts can enable training-time padding/truncation.
    tokenizer.no_padding()
    tokenizer.no_truncation()
    return tokenizer


def _count_context(text):
    tokenizer = _context_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False).ids) if tokenizer else None


def context_tokens(diagnostics):
    """Count only the actual supplied context, excluding the question and instructions."""
    if 'memory_context_tokens' in diagnostics:
        value = diagnostics['memory_context_tokens']
        return value if type(value) is int and value >= 0 else None
    text = diagnostics.get('supplied_context')
    if text == '':
        return 0
    return _count_context(text) if isinstance(text, str) else None


def question_phase_seconds(diagnostics, phase):
    """Prefer cumulative query work; never subtract a judge estimate from a total."""
    return diagnostics.get('execution_' + phase + '_seconds', diagnostics.get(phase + '_seconds'))


def ingestion_builds(report, module):
    """Deduplicate builds by ID, rejecting conflicting provenance or ownership."""
    builds, seen, conflicts = [], {}, set()
    for memory in [*report.get('previous_ingestions', []), *report.get('memories', [])]:
        if str(memory.get('module', 'unknown')) != module:
            continue
        ingestion = memory.get('ingestion', {})
        identity = ingestion.get('ingestion_id')
        sample = str(memory['sample_id']) if memory.get('sample_id') is not None else None
        value = (sample, ingestion)
        if identity is not None and identity in seen:
            if seen[identity] != value:
                conflicts.update((sample, seen[identity][0]))
            continue
        if identity is not None:
            seen[identity] = value
        builds.append(value)
    return builds, conflicts


def construction_accounting(report, module, cases):
    """Distinct construction work, reuse, and provider phases; no invented cost."""
    builds, conflicts = ingestion_builds(report, module)
    constructed = [(s, d) for s, d in builds if d.get('construction_action') != 'frozen_reuse']
    unique = {}
    for sample, d in constructed:
        unique.setdefault(d.get('construction_id', d.get('ingestion_id')), (sample, d))
    ledger_complete = not conflicts and all(d.get('memory_llm_calls') == 0 or
        isinstance(d.get('provider_requests'), list) for _, d in builds)
    requests = [r for _, d in builds for r in d.get('provider_requests', []) if r.get('phase') == 'memory']

    def usage(records, complete=True):
        return dict(tokens=(sum(r['tokens'] for r in records) if complete and all(number(r.get('tokens')) for r in records) else None),
                    known_token_lower_bound=sum(r['tokens'] for r in records if number(r.get('tokens'))),
                    request_count=len(records), missing_usage_count=sum(not number(r.get('tokens')) for r in records),
                    ledger_complete=complete)

    return dict(scope='this report plus retained resume history; not other campaign files',
        unique_construction_count=len(unique), construction_attempt_count=len(constructed),
        rebuild_count=max(0, len(constructed)-len({s for s, _ in constructed})),
        frozen_reuse_count=sum(d.get('construction_action') == 'frozen_reuse' for _, d in builds),
        unique_construction_usage=usage_coverage([phase_usage(d, 'memory') for _, d in unique.values()]),
        formation=usage([r for r in requests if (r.get('operation') or {}).get('type') != 'compaction'], ledger_complete),
        compaction=usage([r for r in requests if (r.get('operation') or {}).get('type') == 'compaction'], ledger_complete),
        answering=usage_coverage([phase_usage(c.get('diagnostics', {}), 'answer') for c in cases]),
        judging=usage_coverage([phase_usage(c.get('diagnostics', {}), 'judge') for c in cases]),
        semantics='known usage is a lower bound; no monetary estimate; amortized campaign costs remain in token_usage/runtime')


def token_records(report, module, cases):
    """Memory + answering cost; allocate shared memory before category filtering."""
    retained, conflicts = ingestion_builds(report, module)
    build_usage = [phase_usage(d, 'memory') for _, d in retained]
    builds = [(sample, usage['tokens']) for (sample, _), usage in zip(retained, build_usage)]
    memory_totals, counts = {}, {}
    for sample, tokens in builds:
        memory_totals.setdefault(sample, []).append(tokens)
    memory_totals = {sample: complete_sum(values) if sample not in conflicts else None
                     for sample, values in memory_totals.items()}
    for case in cases:
        sample = str(case['sample_id']) if case.get('sample_id') is not None else None
        counts[sample] = counts.get(sample, 0) + 1
    baseline = module in ('full_context', 'question_only', 'no_memory')
    records, answers = {}, []
    for case in cases:
        sample = str(case['sample_id']) if case.get('sample_id') is not None else None
        memory = memory_totals.get(sample, 0 if baseline and not builds else None)
        if sample is None and not (baseline and not builds):
            memory = None
        answer = phase_tokens(case.get('diagnostics', {}), 'answer')
        answers.append(answer)
        records[id(case)] = complete_sum([memory / counts[sample] if number(memory) else None, answer])
    memory = complete_sum(value for _, value in builds) if builds else (0 if baseline else None)
    if conflicts:
        memory = None
    answer = complete_sum(answers)
    total = complete_sum([memory, answer])
    coverage = usage_coverage([*build_usage,
        *(phase_usage(c.get('diagnostics', {}), 'answer') for c in cases)])
    coverage['usage_complete'] = number(total)
    if conflicts:
        coverage.update(known_recorded_tokens=None, usage_complete=False)
    return records, dict(memory_tokens=memory, answer_tokens=answer, total_tokens=total,
                         **coverage,
                         mean_tokens=total / len(cases) if number(total) and cases else None,
                         count=sum(number(value) for value in records.values()),
                         question_count=len(cases), conflicting_ingestion_ids=bool(conflicts))


def runtime_records(report, module, cases):
    """Allocate each conversation's recorded formation builds before filtering."""
    builds, seen, conflicts = [], {}, set()
    for memory in [*report.get('previous_ingestions', []), *report.get('memories', [])]:
        if str(memory.get('module', 'unknown')) != module:
            continue
        ingestion = memory.get('ingestion', {})
        identity = ingestion.get('ingestion_id')
        seconds = ingestion.get('preparation_seconds', ingestion.get('total_seconds'))
        sample = str(memory['sample_id']) if memory.get('sample_id') is not None else None
        if identity is not None and identity in seen:
            previous_sample, previous_seconds = seen[identity]
            if (sample, seconds) != (previous_sample, previous_seconds):
                conflicts.update((sample, previous_sample))
            continue
        if identity is not None:
            seen[identity] = (sample, seconds)
        builds.append((sample, seconds))
    formation = {}
    for sample, seconds in builds:
        formation.setdefault(sample, []).append(seconds)
    formation = {sample: complete_sum(seconds) if sample not in conflicts else None
                 for sample, seconds in formation.items()}
    counts = {}
    for case in cases:
        sample = str(case['sample_id']) if case.get('sample_id') is not None else None
        counts[sample] = counts.get(sample, 0) + 1
    records = {}
    for case in cases:
        sample = str(case['sample_id']) if case.get('sample_id') is not None else None
        seconds = formation.get(sample) if sample is not None else None
        share = seconds / counts[sample] if number(seconds) else None
        diagnostics = case.get('diagnostics', {})
        retrieval = question_phase_seconds(diagnostics, 'retrieval')
        answer = question_phase_seconds(diagnostics, 'answer')
        records[id(case)] = dict(formation_seconds=share, retrieval_seconds=retrieval,
                                 answer_seconds=answer, total_seconds=complete_sum([share, retrieval, answer]))
    unallocated = [seconds for sample, seconds in builds if sample is None or sample not in counts]
    return records, dict(total_formation_seconds=complete_sum(seconds for _, seconds in builds) if not conflicts else None,
                         formation_build_count=len(builds),
                         formation_runtime_count=sum(number(seconds) for _, seconds in builds),
                         unallocated_formation_seconds=complete_sum(unallocated) if unallocated else (0 if builds else None),
                         conflicting_ingestion_ids=bool(conflicts))


def runtime_group(records):
    """Each average is a complete total divided by the recorded question count."""
    known = [r for r in records if number(r['total_seconds'])]
    metrics = dict(count=len(known), record_count=len(records))
    for phase in ('formation', 'retrieval', 'answer', 'total'):
        key = phase + '_seconds'
        metrics[key] = complete_sum(r[key] for r in records)
        metrics['mean_' + key] = metrics[key] / len(records) if number(metrics[key]) and records else None
    return metrics


def lifecycle_metrics(report, module, cases):
    """Recorded run cost, including previous ingestion attempts exactly once."""
    retained, conflicts = ingestion_builds(report, module)
    builds = [ingestion for _, ingestion in retained]
    conflicting = bool(conflicts)
    ds = [c.get('diagnostics', {}) for c in cases]
    phases = {}
    for phase, diagnostics in (('memory', builds), ('answer', ds), ('judge', ds)):
        values = [phase_tokens(d, phase) for d in diagnostics]
        phases[phase] = dict(tokens=complete_sum(values),
                             **usage_coverage(phase_usage(d, phase) for d in diagnostics),
                             known_count=sum(number(v) for v in values),
                             record_count=len(values))
    ingestion_time = complete_sum(d.get('total_seconds') for d in builds)
    query_times = [d.get('execution_total_seconds', d.get('total_seconds')) for d in ds]
    query_time = complete_sum(query_times)
    if conflicting:
        phases['memory'].update(tokens=None, known_recorded_tokens=None, usage_complete=False)
        ingestion_time = None
    retrieval = [d.get('retrieval_seconds') for d in ds]
    return dict(scope='all recorded ingestion builds and retained question attempts; no amortization',
        ingestion=phases['memory'], answer=phases['answer'], judge=phases['judge'],
        total_provider_tokens=complete_sum(phases[p]['tokens'] for p in ('memory', 'answer', 'judge')),
        known_recorded_provider_tokens=complete_sum(phases[p]['known_recorded_tokens'] for p in ('memory', 'answer', 'judge')),
        missing_failed_request_count=sum(phases[p]['missing_failed_request_count'] for p in ('memory', 'answer', 'judge')),
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


def enrich_report(value, source_name=None):
    if not isinstance(value, dict) or not isinstance(value.get('cases'), list):
        raise ValueError('Upload a benchmark results object containing a cases array.')
    from ExperimentRecording import validate
    validate(value)
    report = deepcopy(value)
    for field in ('memories', 'question_manifest', 'previous_ingestions'):
        if field in report and not isinstance(report[field], list):
            raise ValueError(f'{field} must be an array.')
    for memory in [*report.get('previous_ingestions', []), *report.get('memories', [])]:
        if not isinstance(memory, dict) or not isinstance(memory.get('ingestion', {}), dict):
            raise ValueError('Each memory must be an object with object ingestion.')
        identity = memory.get('ingestion', {}).get('ingestion_id')
        if identity is not None and not isinstance(identity, str):
            raise ValueError('ingestion_id must be a string.')
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

    contexts_by_case, counts_by_text = {}, {}
    for case in report['cases']:
        diagnostics = case.get('diagnostics', {})
        text = diagnostics.get('supplied_context')
        if 'memory_context_tokens' not in diagnostics and isinstance(text, str):
            if text not in counts_by_text:
                counts_by_text[text] = context_tokens(diagnostics)
            count = counts_by_text[text]
        else:
            count = context_tokens(diagnostics)
        contexts_by_case[id(case)] = count

    def group(cases, selected, runtimes, tokens):
        judged = [c['correct'] for c in cases if type(c.get('correct')) in (bool, int, float) and c['correct'] in (0, 1)]
        token_values = [tokens[id(c)] for c in cases]
        times = [c.get('diagnostics', {}).get('total_seconds') for c in cases]
        known_tokens = [v for v in token_values if v is not None]
        known_times = [v for v in times if number(v)]
        contexts = [contexts_by_case[id(c)] for c in cases]
        context_total = complete_sum(contexts)
        return dict(case_count=len(cases), selected_count=selected, judged_count=len(judged),
                    accuracy_percent=100 * sum(judged) / len(judged) if judged else None,
                    completion_percent=100 * len(judged) / selected if selected else None,
                    success_percent=100 * sum(judged) / selected if selected else None,
                    mean_question_tokens=sum(known_tokens)/len(cases) if cases and len(known_tokens) == len(cases) else None,
                    token_count=len(known_tokens), total_question_tokens=complete_sum(token_values),
                    mean_context_tokens=context_total / len(cases) if number(context_total) and cases else None,
                    total_context_tokens=context_total, context_token_count=sum(number(v) for v in contexts),
                    mean_question_seconds=sum(known_times)/len(known_times) if known_times else None,
                    runtime_count=len(known_times), total_question_seconds=complete_sum(times),
                    runtime=runtime_group([runtimes[id(c)] for c in cases]))

    modules = list(dict.fromkeys(str(c.get('module', 'unknown')) for c in [*report['cases'], *manifest]))
    rows = []
    for module in modules:
        cases = [c for c in report['cases'] if str(c.get('module', 'unknown')) == module]
        selected = [c for c in manifest if str(c.get('module', 'unknown')) == module]
        runtimes, formation = runtime_records(report, module, cases)
        tokens, token_totals = token_records(report, module, cases)
        metrics = group(cases, len(selected) if manifest else len(cases), runtimes, tokens)
        metrics.update(mean_question_tokens=token_totals['mean_tokens'], total_question_tokens=token_totals['total_tokens'],
                       token_count=token_totals['count'], token_usage=token_totals)
        if report.get('recording') is not None:
            metrics['construction'] = construction_accounting(report, module, cases)
        metrics['runtime'].update(formation)
        metrics['runtime']['recorded_total_seconds'] = complete_sum([
            formation['total_formation_seconds'], metrics['runtime']['retrieval_seconds'], metrics['runtime']['answer_seconds']])
        runtime = metrics['runtime']
        runtime['allocated_total_seconds'] = runtime['total_seconds']
        runtime['total_seconds'] = runtime['recorded_total_seconds']
        runtime['mean_total_seconds'] = runtime['total_seconds'] / len(cases) if number(runtime['total_seconds']) and cases else None
        runtime['mean_formation_seconds'] = formation['total_formation_seconds'] / len(cases) if number(formation['total_formation_seconds']) and cases else None
        categories = {}
        for category in sorted({str(c.get('category', 'unknown')) for c in [*cases, *selected]}):
            subset = [c for c in cases if str(c.get('category', 'unknown')) == category]
            count = sum(str(c.get('category', 'unknown')) == category for c in selected) if manifest else len(subset)
            categories[category] = group(subset, count, runtimes, tokens)
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
        expected_samples = {str(c['sample_id']) for c in [*cases, *selected] if c.get('sample_id') is not None}
        current_samples = {str(m['sample_id']) for m in memories if m.get('sample_id') is not None}
        metrics['storage_scope'] = 'current snapshots only; not all builds or guaranteed all conversations'
        metrics['storage_conversation_count'] = len(current_samples & expected_samples)
        metrics['expected_conversation_count'] = len(expected_samples)
        metrics['storage_cohort_complete'] = bool(expected_samples) and expected_samples <= current_samples and all(number(v) for v in sizes)
        latest = {}
        for memory in [*report.get('previous_ingestions', []), *memories]:
            if (str(memory.get('module', 'unknown')) == module and 'error' in memory
                    and memory['error'] is None and memory.get('sample_id') is not None):
                latest[str(memory['sample_id'])] = memory.get('ingestion', {}).get('final_storage', {}).get('stored_text_bytes')
        measured = [latest.get(sample) for sample in expected_samples]
        metrics['latest_successful_storage'] = dict(
            scope='latest recorded successful ingestion per selected conversation; may use previous builds',
            stored_text_bytes=complete_sum(measured),
            conversation_count=sum(number(v) for v in measured), expected_conversation_count=len(expected_samples))
        metrics['lifecycle'] = lifecycle_metrics(report, module, cases)
        if module == 'compaction':
            from CompactionAnalysis import compaction_summary
            builds, conflicts = ingestion_builds(report, module)
            events = [e for m in memories for e in m.get('memory', {}).get('compaction_events', [])]
            ratios = [e['actual_retain_percent'] for e in events
                      if e.get('committed') and number(e.get('actual_retain_percent'))]
            attempts = [e for _, ingestion in builds for e in ingestion.get('compaction_events', [])]
            complete = not conflicts and all('compaction_events' in ingestion or
                        ingestion.get('reused_artifact_sha256') for _, ingestion in builds)
            metrics['compaction'] = dict(
                analysis=compaction_summary(report),
                requested_retain_percent=report.get('config', {}).get('retain_percent'),
                mode=report.get('config', {}).get('compaction_mode'),
                mean_actual_retain_percent=sum(ratios)/len(ratios) if ratios else None,
                event_count=len(events), ratio_event_count=len(ratios),
                attempt_count=sum(len(e.get('attempts', [])) for e in attempts) if complete else None,
                total_seconds=complete_sum([e.get('seconds') for e in attempts]) if complete else None,
                failed_event_count=sum(e.get('status') == 'failed' or not e.get('committed') for e in attempts),
                max_depth=max((m.get('memory', {}).get('config', {}).get('depth', 0) for m in memories), default=0),
                overhead_scope='all recorded ingestion builds; excludes artifact reuse; all question types',
                ratio_scope='committed events in current snapshots; not full-history information retention')
        rows.append(dict(module=module, overall=metrics, categories=categories))
    artifact_name = source_name if source_name is not None else (previous.get('source_name') if isinstance(previous, dict) else None)
    warnings = []
    artifact_name = artifact_name if isinstance(artifact_name, str) else None
    match = re.search(r'windowed_summary_k=(\d+)', artifact_name or '', re.IGNORECASE)
    actual_window = (report.get('config') or {}).get('window_size') if isinstance(report.get('config'), dict) else None
    if match and type(actual_window) is int and int(match.group(1)) != actual_window:
        warnings.append(dict(code='filename_config_mismatch', filename_window=int(match.group(1)),
            configured_window=actual_window,
            message=f'Filename window {match.group(1)} differs from configured window {actual_window}; use recorded configuration.'))
    report['comparison'] = dict(version=6, source_name=artifact_name, warnings=warnings, added_fields=added, rows=rows,
        definitions=dict(accuracy='Correct / judged questions × 100; unavailable labels are excluded.',
                         tokens='Total memory + answering provider tokens / recorded question count; excludes judging. Shared conversation memory is allocated before category filtering. Includes reported usage across recorded resumed builds and request attempts. Missing request usage makes complete totals unavailable; known recorded subtotals are lower bounds with explicit coverage. Judging is excluded; rebuild history and recorded query workload affect averages.',
                         failed_request_usage='Missing usage for any request, including failure, is unknown. Known recorded usage counts all reported attempts and is a lower bound; missing-failure counts are exposed. Currency costs remain unknown.',
                         context_tokens='Supplied conversation/memory context only, excluding question, instructions, outputs, and memory preparation. Fixed benchmark WordPiece tokens, not provider usage. Uses recorded memory_context_tokens, or counts saved supplied_context with the pinned local tokenizer without padding/truncation; missing text or tokenizer remains unavailable.',
                         runtime='Total recorded memory preparation + retrieval + answering time / recorded question count; excludes judging and review pauses. Preparation uses preparation_seconds, falling back to legacy ingestion total_seconds. All recorded builds and cumulative query attempts count, including preparation without recorded questions. Category shares are allocated by conversation before filtering. Missing required totals remain unavailable.',
                         legacy_runtime='mean_question_seconds and total_question_seconds retain recorded question time including judging and excluding formation.',
                         lifecycle='All recorded ingestion builds (including resumed builds) + retained question attempts. Unknown usage stays unavailable; legacy data may omit failed attempts. No amortization.',
                         storage='Sum of UTF-8 stored text bytes in current snapshots only, possibly a partial conversation cohort. Latest recorded successful ingestion storage is reported separately with selected-conversation coverage. Excludes embeddings and runtime overhead.'))
    return report
