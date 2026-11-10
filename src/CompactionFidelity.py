"""Offline annotations of frozen outputs. Never imported by memory formation."""
from collections import Counter, defaultdict
from copy import deepcopy
import re

from ExperimentRecording import new_archive, put, get, validate, sha256
from AuditProvenance import digest

LABELS = ('preserved', 'lost', 'contradicted', 'uncertain')


def _manifest(report, propositions):
    validate(report)
    if not report.get('recording'):
        raise ValueError('Fidelity evaluation requires a complete recording archive.')
    if (not isinstance(propositions, dict) or propositions.get('version') != 1 or propositions.get('dataset_hash') != report.get('dataset_hash')
            or not isinstance(propositions.get('author'), str) or not propositions['author'].strip()
            or not isinstance(propositions.get('samples'), list)):
        raise ValueError('Propositions require version 1, matching dataset_hash, author and samples.')
    dataset = get(report['recording'], report.get('dataset_artifact'), 'dataset')
    ids = {str(s['sample_id']): {t['dia_id'] for k, turns in s['conversation'].items()
           if re.fullmatch(r'session_\d+', k) for t in turns} for s in dataset}
    prepared, sample_ids = {}, set()
    for sample in propositions['samples']:
        if not isinstance(sample, dict):
            raise ValueError('Proposition samples must be objects.')
        sample_id = str(sample.get('sample_id'))
        if sample_id not in ids or sample_id in sample_ids:
            raise ValueError('Unknown or duplicate proposition sample ID.')
        sample_ids.add(sample_id)
        props, seen = sample.get('propositions'), set()
        if not isinstance(props, list) or not props:
            raise ValueError('Each sample needs nonempty propositions.')
        for p in props:
            if not isinstance(p, dict):
                raise ValueError('Each proposition must be an object.')
            identity, sources = p.get('id'), p.get('source_ids')
            if (not isinstance(identity, str) or not identity or identity in seen
                    or not isinstance(p.get('text'), str) or not p['text'].strip()
                    or p.get('source_verified') is not True or not isinstance(sources, list) or not sources
                    or any(not isinstance(s, str) or s not in ids[sample_id] for s in sources)
                    or len(set(sources)) != len(sources) or not isinstance(p.get('kind', 'fact'), str)):
                raise ValueError('Invalid proposition: unique ID/text, verified source IDs and kind required.')
            seen.add(identity)
        prepared[sample_id] = props
    latest = {str(m['sample_id']): m for m in
              [*report.get('previous_ingestions', []), *report.get('memories', [])]
              if m.get('module') == 'compaction'}
    targets, seen_events = [], set()
    for sample_id, props in sorted(prepared.items()):
        memory = latest.get(sample_id)
        if not memory or not memory.get('memory_state_artifact'):
            raise ValueError('No frozen compaction memory for proposition sample ' + sample_id)
        get(report['recording'], memory['memory_state_artifact'], 'memory-state')
        for event in memory.get('memory', {}).get('compaction_events', []):
            if event.get('committed') is not True or event.get('status') not in ('completed', 'noop'):
                continue
            if not isinstance(event.get('event_id'), str) or event['event_id'] in seen_events:
                raise ValueError('Missing or duplicate compaction event identity.')
            seen_events.add(event['event_id'])
            source = get(report['recording'], event.get('source_artifact'), 'compaction-source')
            output_ref = event.get('replacement_artifact') if event['status'] == 'completed' else event['source_artifact']
            output = get(report['recording'], output_ref,
                         'compaction-replacement' if event['status'] == 'completed' else 'compaction-source')
            entries = output if event['status'] == 'completed' else output['entries']
            if digest(source['entries']) != event.get('source_sha256') or digest(entries) != event.get('output_sha256'):
                raise ValueError('Compaction event source/output hash mismatch.')
            actual_ids = {s for entry in source['entries'] for s in
                          ([entry['metadata']['dialogue_id']] if entry['metadata'].get('dialogue_id') else
                           entry['metadata'].get('source_ids', []))}
            if actual_ids != set(event.get('source_ids', [])) or source['rendered_text'] != '\n\n'.join(e['text'] for e in source['entries']):
                raise ValueError('Compaction source lineage/rendering mismatch.')
            source_ids = set(event.get('source_ids', []))
            eligible = [p['id'] for p in props if set(p['source_ids']) <= source_ids]
            target = dict(sample_id=sample_id, event_id=event['event_id'], depth=event.get('depth_after'),
                status=event['status'], tokenizer=event.get('tokenizer'),
                memory_snapshot_sha256=memory['memory_state_artifact']['artifact_sha256'],
                source_artifact_sha256=event['source_artifact']['artifact_sha256'],
                output_artifact_sha256=output_ref['artifact_sha256'],
                source_text=source['rendered_text'], output_text='\n\n'.join(e['text'] for e in entries),
                eligible_proposition_ids=eligible,
                excluded_proposition_ids=[p['id'] for p in props if p['id'] not in eligible])
            target['target_id'] = sha256(target)
            targets.append(target)
    if not targets:
        raise ValueError('No committed compaction/no-op outputs are available to evaluate.')
    return dict(version=1, run_id=report['run_id'], dataset_hash=report['dataset_hash'],
                proposition_set=deepcopy(propositions), targets=targets,
                scope='committed outputs in latest recorded construction per proposition sample; source lineage determines eligibility only')


def prepare_review(report, propositions):
    manifest = _manifest(report, propositions)
    archive = new_archive()
    ref = put(archive, 'fidelity-manifest', manifest)
    return dict(schema_version=1, kind='compaction-fidelity-review', recording=archive,
        manifest_artifact=ref, items=[dict(target_id=t['target_id'], proposition_id=p, label=None, rationale='')
            for t in manifest['targets'] for p in t['eligible_proposition_ids']])


def _label_summary(labels):
    counts = Counter(labels)
    total = len(labels)
    unknown = counts[None] + counts['uncertain']
    return dict(total=total, counts={k: counts[k] for k in LABELS}, unreviewed_count=counts[None],
        complete=bool(total) and unknown == 0,
        proposition_recall=counts['preserved']/total if total and not unknown else None,
        recall_bounds=[counts['preserved']/total, (counts['preserved']+unknown)/total] if total else None)


def _evaluator(archive, evaluator, item_keys):
    if not isinstance(evaluator, dict):
        raise ValueError('Explicit human or external-model evaluator provenance is required.')
    if evaluator.get('type') == 'human':
        if set(evaluator) != {'type', 'name'} or not isinstance(evaluator.get('name'), str) or not evaluator['name'].strip():
            raise ValueError('Human evaluator requires type and nonempty name only.')
        return deepcopy(evaluator)
    if evaluator.get('type') != 'external_model' or set(evaluator) != {'type', 'model', 'requests'}:
        raise ValueError('External evaluator requires type, model and exact imported requests; no API is called.')
    if not isinstance(evaluator['model'], str) or not evaluator['model'] or not isinstance(evaluator['requests'], list):
        raise ValueError('Invalid external model provenance.')
    requests, covered = [], set()
    allowed = {'model', 'messages', 'temperature', 'top_p', 'seed', 'max_tokens', 'reasoning_effort', 'response_format', 'extra_body', 'stream'}
    for r in evaluator['requests']:
        if not isinstance(r, dict) or set(r) != {'item_keys', 'request', 'response'}:
            raise ValueError('Each external request needs item_keys, request and response.')
        payload, response = r['request'], r['response']
        if (not isinstance(payload, dict) or payload.keys()-allowed or payload.get('model') != evaluator['model']
                or not isinstance(payload.get('messages'), list) or not payload['messages']
                or any(not isinstance(m, dict) or set(m) != {'role', 'content'}
                       or not isinstance(m['role'], str) or not isinstance(m['content'], str) for m in payload['messages'])
                or not isinstance(response, dict) or response.keys()-{'content', 'model', 'usage', 'finish_reason', 'id'}
                or response.get('usage') is not None and not isinstance(response.get('usage'), dict)
                or not isinstance(response.get('content'), str) or not isinstance(r['item_keys'], list)):
            raise ValueError('Invalid or unsafe external request/response fields.')
        if 'extra_body' in payload and (not isinstance(payload['extra_body'], dict)
                or set(payload['extra_body']) != {'thinking'}
                or not isinstance(payload['extra_body']['thinking'], dict)
                or set(payload['extra_body']['thinking']) != {'type'}
                or payload['extra_body']['thinking']['type'] not in ('enabled', 'disabled')):
            raise ValueError('Imported extra_body may contain only the thinking type.')
        for key in r['item_keys']:
            if not isinstance(key, list) or len(key) != 2 or any(not isinstance(x, str) for x in key):
                raise ValueError('External item keys must be [target_id, proposition_id].')
            pair = tuple(key)
            if pair not in item_keys:
                raise ValueError('External request names an unknown review item.')
            covered.add(pair)
        requests.append(dict(item_keys=deepcopy(r['item_keys']),
            request_artifact=put(archive, 'fidelity-judge-request', payload),
            response_artifact=put(archive, 'fidelity-judge-response', response),
            request_sha256=sha256(payload), usage_complete=(response.get('usage') or {}).get('total_tokens') is not None,
            provider_defaults=[k for k in ('temperature', 'top_p', 'seed', 'max_tokens') if k not in payload]))
    if covered != item_keys:
        raise ValueError('Every labelled item must link to an external judge request.')
    return dict(type='external_model', model=evaluator['model'], requests=requests,
                semantics='imported annotations; reported responses are not independently verified')


def score_review(report, review, evaluator):
    validate(review)
    if review.get('schema_version') != 1 or review.get('kind') != 'compaction-fidelity-review':
        raise ValueError('Unsupported fidelity review schema.')
    manifest = get(review['recording'], review.get('manifest_artifact'), 'fidelity-manifest')
    if manifest != _manifest(report, manifest['proposition_set']):
        raise ValueError('Review source/output/snapshot identity no longer matches the report.')
    expected = {(t['target_id'], p) for t in manifest['targets'] for p in t['eligible_proposition_ids']}
    items, labels = review.get('items'), {}
    if not isinstance(items, list):
        raise ValueError('Review items must be a list.')
    for item in items:
        if not isinstance(item, dict) or set(item) != {'target_id', 'proposition_id', 'label', 'rationale'}:
            raise ValueError('Invalid fidelity annotation fields.')
        key, label = (item['target_id'], item['proposition_id']), item['label']
        if key not in expected or key in labels or label not in (*LABELS, None) or not isinstance(item['rationale'], str):
            raise ValueError('Unknown, duplicate or invalid fidelity annotation.')
        labels[key] = label
    if set(labels) != expected:
        raise ValueError('Review item cohort changed; use null labels for unreviewed items.')
    archive = deepcopy(review['recording'])
    provenance = _evaluator(archive, evaluator, {k for k, v in labels.items() if v is not None})
    props = {(str(s['sample_id']), p['id']): p for s in manifest['proposition_set']['samples'] for p in s['propositions']}
    targets, kinds, depths = [], defaultdict(list), defaultdict(list)
    for target in manifest['targets']:
        values = [labels[(target['target_id'], p)] for p in target['eligible_proposition_ids']]
        summary = _label_summary(values)
        all_rec = (0 if any(v in ('lost', 'contradicted') for v in values) else
                   1 if values and all(v == 'preserved' for v in values) else None)
        targets.append(dict(target_id=target['target_id'], sample_id=target['sample_id'], depth=target['depth'],
                            all_propositions_preserved=all_rec, **summary))
        depths[str(target['depth'])].extend(values)
        for p in target['eligible_proposition_ids']:
            kinds[props[(target['sample_id'], p)].get('kind', 'fact')].append(labels[(target['target_id'], p)])
    scored = [t['all_propositions_preserved'] for t in targets]
    metrics = dict(version=1, propositions=_label_summary(list(labels.values())), targets=targets,
        all_proposition_recall=sum(scored)/len(scored) if scored and None not in scored else None,
        known_target_count=sum(v is not None for v in scored), target_count=len(scored),
        by_depth={d: _label_summary(v) for d, v in sorted(depths.items())},
        by_kind={k: _label_summary(v) for k, v in sorted(kinds.items())},
        excluded_proposition_count=sum(len(t['excluded_proposition_ids']) for t in manifest['targets']),
        definition='proposition survival in frozen outputs; uncertainty/unreviewed stay unknown; all-recall is per-target conjunction, not QA accuracy')
    evaluation = dict(version=1, manifest_artifact=deepcopy(review['manifest_artifact']),
                      annotations=deepcopy(items), evaluator=provenance, metrics=metrics)
    return dict(schema_version=1, kind='compaction-fidelity-evaluation', recording=archive,
                evaluation_artifact=put(archive, 'fidelity-evaluation', evaluation))


def calibrate(reference, candidate):
    for report in (reference, candidate):
        validate(report)
        if report.get('kind') != 'compaction-fidelity-evaluation':
            raise ValueError('Calibration requires scored fidelity evaluations.')
    left = get(reference['recording'], reference['evaluation_artifact'], 'fidelity-evaluation')
    right = get(candidate['recording'], candidate['evaluation_artifact'], 'fidelity-evaluation')
    if left['manifest_artifact'] != right['manifest_artifact']:
        raise ValueError('Calibration requires identical source/proposition/target manifests.')
    if left['evaluator'].get('type') != 'human':
        raise ValueError('Calibration reference must be human annotations.')
    maps = [{(i['target_id'], i['proposition_id']): i['label'] for i in e['annotations']} for e in (left, right)]
    if set(maps[0]) != set(maps[1]):
        raise ValueError('Calibration item cohorts disagree.')
    paired = [(v, maps[1][k]) for k, v in maps[0].items() if v is not None and maps[1][k] is not None]
    matrix = {a: {b: 0 for b in LABELS} for a in LABELS}
    for a, b in paired:
        matrix[a][b] += 1
    return dict(schema_version=1, kind='compaction-fidelity-calibration',
        reference_evaluation_sha256=sha256(reference), candidate_evaluation_sha256=sha256(candidate),
        manifest_sha256=left['manifest_artifact']['artifact_sha256'],
        item_count=len(maps[0]), paired_count=len(paired), unpaired_count=len(maps[0])-len(paired),
        exact_label_agreement=sum(a == b for a, b in paired)/len(paired) if paired else None,
        confusion_matrix=matrix, semantics='descriptive agreement on supplied annotations; not proof of judge validity')
