"""Strict paired, conversation-clustered campaign statistics; no model calls."""
from collections import Counter
from copy import deepcopy
import random

from ExperimentRecording import get, validate, sha256
from ResultAnalysis import percentile

TREATMENTS = {'retain_percent', 'compaction_trigger_tokens', 'compaction_mode', 'modules',
              'max_summary_tokens', 'window_size', 'retrieval_k', 'max_stored_entries',
              'candidate_k', 'hybrid_shares', 'component_options'}
SHARED_FIELDS = ('protocol_version', 'dataset_hash', 'dataset_artifact', 'tokenizer',
                 'answer_prompt_hash', 'judge_prompt_hash', 'answer_model', 'judge_model',
                 'answer_settings', 'judge_settings', 'scoring', 'dependency_versions')


def _condition(reports, vary):
    if not isinstance(reports, list) or not reports:
        raise ValueError('Each condition requires at least one report.')
    repeats, constructions, run_ids = {}, set(), set()
    condition = None
    for report in reports:
        validate(report)
        if (not report.get('recording') or not isinstance(report.get('run_id'), str)
                or report.get('status') not in ('completed', 'failed', 'cancelled', 'interrupted')):
            raise ValueError('Campaign comparisons require stopped, fully archived reports.')
        if report['run_id'] in run_ids:
            raise ValueError('Duplicate run or resumed copy cannot be a new replicate.')
        run_ids.add(report['run_id'])
        campaign = report.get('compaction_campaign') or {}
        repeat = campaign.get('repeat', 1)
        if type(repeat) is not int or repeat < 1 or repeat in repeats:
            raise ValueError('Missing, invalid or duplicate repeat ID; multiple runs need explicit unique repeats.')
        config = report.get('config')
        if not isinstance(config, dict) or len(config.get('modules', [])) != 1:
            raise ValueError('One architecture per campaign report is required.')
        signature = dict(config=config, memory_prompt_hash=report.get('memory_prompt_hash'),
            memory_model=report.get('memory_model'), memory_model_settings=report.get('memory_model_settings'),
            packing_policy=report.get('packing_policy'))
        if condition is None:
            condition = signature
        elif condition != signature:
            raise ValueError('Repeats within a condition must use identical settings and prompts.')
        for field in SHARED_FIELDS:
            if field not in report:
                raise ValueError('Missing compatibility identity: ' + field)
        if not report.get('dataset_hash') or not (report.get('code_identity') or {}).get('source_sha256'):
            raise ValueError('Dataset and source-code identities are required.')
        dataset = get(report['recording'], report['dataset_artifact'], 'dataset')
        samples = {str(s['sample_id']): s for s in dataset}
        manifest, cases, selected = report.get('question_manifest'), {}, {}
        if not isinstance(manifest, list) or not manifest:
            raise ValueError('A nonempty question manifest is required.')
        for item in manifest:
            sample, index = str(item.get('sample_id')), item.get('question_index')
            if sample not in samples or type(index) is not int or not 0 <= index < len(samples[sample]['qa']):
                raise ValueError('Invalid campaign question selection.')
            key = (sample, index)
            if key in selected or item.get('module') != config['modules'][0]:
                raise ValueError('Duplicate question or module mismatch in manifest.')
            qa = samples[sample]['qa'][index]
            if item.get('category') != qa['category']:
                raise ValueError('Manifest category disagrees with archived dataset.')
            selected[key] = dict(category=qa['category'], question=qa['question'],
                answer=qa.get('answer'), evidence=qa.get('evidence', []))
        for case in report.get('cases', []):
            key = (str(case.get('sample_id')), case.get('question_index'))
            if key not in selected or key in cases or case.get('module') != config['modules'][0]:
                raise ValueError('Unselected, duplicate or mismatched campaign case.')
            q = selected[key]
            if any(case.get(k, [] if k == 'evidence' else None) != v for k, v in q.items()):
                raise ValueError('Case question/reference disagrees with archived selection.')
            correct = case.get('correct')
            if correct is not None and (type(correct) not in (int, bool) or correct not in (0, 1)):
                raise ValueError('Invalid binary correctness label.')
            if correct is not None and (not isinstance(case.get('prediction'), str) or not case['prediction'].strip()):
                raise ValueError('A judged case must retain its recorded prediction.')
            cases[key] = case
        latest = {str(m['sample_id']): m for m in
                  [*report.get('previous_ingestions', []), *report.get('memories', [])]
                  if m.get('module') == config['modules'][0]}
        construction_ids, sources = set(), {}
        for sample in {k[0] for k in selected}:
            memory = latest.get(sample)
            if memory is not None:
                ingestion = memory.get('ingestion', {})
                identity = ingestion.get('construction_id', ingestion.get('ingestion_id'))
                if not isinstance(identity, str) or not identity:
                    raise ValueError('Missing memory construction identity.')
                owned = (sample, identity)
                if owned in constructions:
                    raise ValueError('Frozen construction reuse cannot masquerade as an independent repeat.')
                constructions.add(owned)
                construction_ids.add(owned)
                if memory.get('source_artifact'):
                    sources[sample] = memory['source_artifact']
        values = {key: int((cases.get(key) or {}).get('correct') == 1) for key in selected}
        coverage = dict(selected_count=len(selected), judged_count=sum(c.get('correct') is not None for c in cases.values()),
            correct_count=sum(values.values()), missing_case_count=len(selected)-len(cases),
            unjudged_count=len(selected)-sum(c.get('correct') is not None for c in cases.values()),
            case_status_counts=dict(Counter(c.get('case_state', c.get('diagnostics', {}).get('status', 'unknown')) for c in cases.values())))
        repeats[repeat] = dict(report=report, selected=selected, values=values, coverage=coverage,
                               constructions=construction_ids, sources=sources)
    return repeats, condition, run_ids, constructions


def compare_campaigns(left_reports, right_reports, vary=('retain_percent',), resamples=10000, seed=42, confidence=.95):
    """Right-minus-left operational success, question-weighted, paired by repeat."""
    if (not isinstance(vary, (list, tuple)) or not vary or len(set(vary)) != len(vary)
            or set(vary)-TREATMENTS):
        raise ValueError('Declare valid unique treatment fields explicitly.')
    if type(resamples) is not int or not 100 <= resamples <= 100000:
        raise ValueError('Bootstrap resamples must be an integer from 100 through 100000.')
    if type(seed) is not int or type(confidence) not in (int, float) or not 0 < confidence < 1:
        raise ValueError('Seed must be an integer and confidence must be between zero and one.')
    left, lconfig, lruns, lconstructions = _condition(left_reports, vary)
    right, rconfig, rruns, rconstructions = _condition(right_reports, vary)
    if lruns & rruns or lconstructions & rconstructions:
        raise ValueError('Paired conditions must not reuse the same run/construction identity.')
    if set(left) != set(right):
        raise ValueError('Conditions require the same explicit repeat IDs.')
    lc, rc = deepcopy(lconfig), deepcopy(rconfig)
    for key in vary:
        lc['config'].pop(key, None)
        rc['config'].pop(key, None)
    # Architecture treatment permits its formation prompt/settings/packer to differ;
    # reader/judge/code/tokenizer identities below remain controlled.
    if 'modules' in vary:
        for key in ('memory_prompt_hash', 'memory_model', 'memory_model_settings', 'packing_policy'):
            lc.pop(key)
            rc.pop(key)
    if lc != rc:
        raise ValueError('Undeclared configuration, prompt, model or packing differences.')
    baseline = next(iter(left.values()))
    selected = baseline['selected']
    for entry in [*left.values(), *right.values()]:
        if entry['selected'] != selected:
            raise ValueError('Question/source cohort mismatch; no silent intersection is used.')
        for field in SHARED_FIELDS:
            if entry['report'][field] != baseline['report'][field]:
                raise ValueError('Campaign compatibility mismatch: ' + field)
        if entry['report']['code_identity']['source_sha256'] != baseline['report']['code_identity']['source_sha256']:
            raise ValueError('Campaign source-code mismatch.')
    for repeat in left:
        for sample in left[repeat]['sources'].keys() & right[repeat]['sources'].keys():
            if left[repeat]['sources'][sample] != right[repeat]['sources'][sample]:
                raise ValueError('Ordered source state mismatch.')
    samples = sorted({key[0] for key in selected})
    repeat_ids = sorted(left)
    keys = {sample: [key for key in selected if key[0] == sample] for sample in samples}
    blocks = {(s, r): (sum(right[r]['values'][key]-left[r]['values'][key] for key in keys[s]), len(keys[s]))
              for s in samples for r in repeat_ids}
    total_diff = sum(v[0] for v in blocks.values())
    total_questions = sum(v[1] for v in blocks.values())
    estimate = 100*total_diff/total_questions
    interval = None
    if len(samples) >= 2:
        rng, draws = random.Random(seed), []
        for _ in range(resamples):
            numerator, denominator = 0, 0
            for _ in samples:
                sample = rng.choice(samples)
                for _ in repeat_ids:
                    diff, count = blocks[(sample, rng.choice(repeat_ids))]
                    numerator += diff
                    denominator += count
            draws.append(100*numerator/denominator)
        tail = (1-confidence)/2
        # Existing percentile() accepts nonnegative measurements; deltas may be negative.
        offset = 100
        interval = [percentile([v+offset for v in draws], tail)-offset,
                    percentile([v+offset for v in draws], 1-tail)-offset]
    def condition_metrics(entries):
        selected_count = sum(e['coverage']['selected_count'] for e in entries.values())
        correct = sum(e['coverage']['correct_count'] for e in entries.values())
        judged = sum(e['coverage']['judged_count'] for e in entries.values())
        return dict(end_to_end_success_percent=100*correct/selected_count,
            judged_accuracy_percent=100*correct/judged if judged else None,
            selected_count=selected_count, judged_count=judged,
            unjudged_count=selected_count-judged,
            per_repeat={str(r): e['coverage'] for r, e in sorted(entries.items())},
            run_ids=sorted(e['report']['run_id'] for e in entries.values()))
    return dict(schema_version=1, kind='paired-compaction-campaign-comparison',
        method_version='paired-conversation-nested-repeat-percentile-v1', treatment_fields=list(vary),
        left=condition_metrics(left), right=condition_metrics(right),
        delta_percentage_points=estimate, confidence_interval_percentage_points=interval,
        confidence=confidence, resamples=resamples, seed=seed,
        conversation_count=len(samples), repeat_ids=repeat_ids, question_count_per_repeat=len(selected),
        question_manifest_sha256=sha256([[s, i, selected[(s, i)]] for s, i in sorted(selected)]),
        input_report_sha256=dict(left=[sha256(r) for r in left_reports], right=[sha256(r) for r in right_reports]),
        interval_status='estimated' if interval is not None else 'unavailable: fewer than two independent conversations',
        definition='right minus left; question-weighted end-to-end success over all selected questions; unjudged/missing are unsuccessful',
        resampling_unit='conversations with replacement; paired repeat blocks within each sampled conversation; all its questions retained together',
        limitations=['single-repeat campaigns do not estimate repeated provider-generation variability',
                     'provider aliases/defaults can drift despite matched recorded settings',
                     'descriptive judged accuracy excludes unjudged cases and has no interval here',
                     'intervals do not account for experiment selection or multiple comparisons'])
