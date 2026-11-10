"""Defined, offline compaction cohorts. Token ratios never measure fact survival."""
from collections import Counter, defaultdict
from ExperimentRecording import sha256
from ResultAnalysis import number, percentile


def _ratios(events):
    eligible = [e for e in events if e.get('committed') is True
                and e.get('status') in ('completed', 'noop')]
    measured = [e for e in eligible if number(e.get('before_tokens')) and e['before_tokens'] > 0
                and number(e.get('after_tokens'))]
    before = sum(e['before_tokens'] for e in measured)
    after = sum(e['after_tokens'] for e in measured)
    complete = len(measured) == len(eligible) and bool(eligible)
    return dict(event_count=len(events), eligible_event_count=len(eligible), measured_event_count=len(measured),
        missing_or_empty_count=len(eligible)-len(measured), counts_complete=complete,
        before_tokens=before if complete else None, after_tokens=after if complete else None,
        known_before_tokens=before, known_after_tokens=after,
        aggregate_compression_factor=before/after if complete and after > 0 else None,
        weighted_retained_percent=100*after/before if complete and before > 0 else None,
        mean_retained_percent=(sum(100*e['after_tokens']/e['before_tokens'] for e in measured)/len(measured)
                               if complete else None))


def compaction_summary(report):
    memories = [m for m in [*report.get('previous_ingestions', []), *report.get('memories', [])]
                if m.get('module') == 'compaction']
    latest = {str(m['sample_id']): m for m in memories if m.get('sample_id') is not None}
    events, conflicts, missing_ids = {}, set(), 0
    for memory in memories:
        for group in (memory.get('memory', {}).get('compaction_events', []),
                      memory.get('ingestion', {}).get('compaction_events', [])):
            for event in group:
                identity = event.get('event_id')
                if not isinstance(identity, str) or not identity:
                    missing_ids += 1
                    continue
                owned = (str(memory.get('sample_id')), event)
                if identity in events and sha256(events[identity]) != sha256(owned):
                    conflicts.add(identity)
                events[identity] = owned
    history = [e for key, (_, e) in events.items() if key not in conflicts]
    current, by_sample, depths = [], {}, defaultdict(list)
    for sample, memory in latest.items():
        selected, seen = [], set()
        for event in memory.get('memory', {}).get('compaction_events', []):
            identity = event.get('event_id')
            if identity and identity not in seen and identity not in conflicts:
                selected.append(event)
                seen.add(identity)
        current.extend(selected)
        by_sample[sample] = _ratios(selected)
        for event in selected:
            depths[str(event.get('depth_after', 'unknown'))].append(event)
    selected_samples = set(map(str, report.get('config', {}).get('sample_ids', [])))
    final_events, incomplete = [], []
    one_shot = report.get('config', {}).get('compaction_mode') == 'one_shot'
    for sample in sorted(selected_samples):
        memory = latest.get(sample, {})
        committed = [e for e in memory.get('memory', {}).get('compaction_events', [])
                     if e.get('committed') is True and e.get('status') in ('completed', 'noop')]
        if (not one_shot or memory.get('formation_complete') is not True or memory.get('error')
                or len(committed) != 1 or committed[0].get('event_id') in conflicts):
            incomplete.append(sample)
        else:
            final_events.append(committed[0])
    final = _ratios(final_events)
    final['cohort_complete'] = one_shot and bool(selected_samples) and not incomplete and final['counts_complete']
    if not final['cohort_complete']:
        final.update(aggregate_compression_factor=None, weighted_retained_percent=None)
    final.update(selected_conversation_count=len(selected_samples), measured_conversation_count=len(final_events),
                 excluded_or_incomplete_sample_ids=incomplete,
                 scope='one final committed operation per selected conversation; only complete one-shot cohorts')
    times = [e.get('seconds') for e in history]
    attempts = [a.get('seconds') for e in history for a in e.get('attempts', [])]
    return dict(version=1, definition='sum(before)/sum(after); weighted retained=100*sum(after)/sum(before)',
        tokenizer=report.get('tokenizer'), scope='current latest snapshots; event-operation ratios, not semantic retention',
        operations=_ratios(current), final_one_shot_cohort=final,
        by_conversation=by_sample, by_depth={d: _ratios(es) for d, es in sorted(depths.items())},
        history=dict(unique_event_count=len(history),
            status_counts=dict(Counter(e.get('status', 'unknown') for e in history)),
            uncommitted_event_count=sum(e.get('committed') is False for e in history),
            unknown_commit_count=sum(type(e.get('committed')) is not bool for e in history),
            conflicting_event_ids=sorted(conflicts), missing_event_identity_count=missing_ids,
            noop_event_count=sum(e.get('status') == 'noop' for e in history),
            event_latency=dict(p50_seconds=percentile(times, .5), p95_seconds=percentile(times, .95),
                measured_count=sum(number(t) for t in times), total_count=len(times)),
            attempt_latency=dict(p50_seconds=percentile(attempts, .5), p95_seconds=percentile(attempts, .95),
                measured_count=sum(number(t) for t in attempts), total_count=len(attempts)),
            latency_scope='all deduplicated builds including failures and rollback; audit overhead included'))
