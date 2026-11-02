"""Offline blinded paired-result review. Uses only the Python standard library."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import re

VERSION = 'kai3-adjudication-v1'
STAGES = {'candidate_retrieval', 'reranking', 'packing', 'answering', 'judging', 'unresolved'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()


def indexed(report):
    result = {}
    if len({c.get('module') for c in report['cases']}) != 1:
        raise ValueError('Select exactly one condition per report')
    for case in report['cases']:
        identity = (case['sample_id'], case['question_index'])
        if identity in result:
            raise ValueError('Duplicate question identity; select a single condition per report')
        if case.get('correct') is not None and type(case['correct']) is not int:
            raise ValueError('Automated correctness must be integer 0/1 or null')
        if case.get('correct') not in (0, 1, None):
            raise ValueError('Invalid automated correctness')
        result[identity] = case
    return result


def metadata_warnings(filename, report):
    """Report filename/config discrepancies without renaming or rewriting inputs."""
    match = re.search(r'vector(_reranker)?_k=(\d+)(?:,(\d+))?', filename)
    if not match:
        return []
    config = report.get('config', {})
    expected = {'retrieval_k': int(match[3] or match[2])}
    if match[1]:
        expected['candidate_k'] = int(match[2])
    return [dict(field=k, filename_value=v, config_value=config.get(k))
            for k, v in expected.items() if config.get(k) != v]


def prepare(baseline, treatment, dataset, source_hashes, seed=20261103,
            agreements_per_category=2):
    if type(agreements_per_category) is not int or agreements_per_category < 0:
        raise ValueError('Agreement sample size must be a nonnegative integer')
    left, right = indexed(baseline), indexed(treatment)
    if not left or left.keys() != right.keys():
        raise ValueError('Reports must contain the same nonempty question cohort')
    if baseline.get('dataset_hash') != treatment.get('dataset_hash'):
        raise ValueError('Report dataset hashes differ')
    # Match BenchmarkJob's canonical dataset identity, including full histories.
    dataset_hash = hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest()
    if baseline.get('dataset_hash') != dataset_hash:
        raise ValueError('Supplied dataset does not match the reports, including conversation histories')
    corpus = {s['sample_id']: s for s in dataset}
    if len(corpus) != len(dataset):
        raise ValueError('Duplicate dataset sample identity')
    reasons, agreements = {}, defaultdict(list)
    for identity in sorted(left):
        a, b = left[identity], right[identity]
        sample, index = identity
        if type(index) is not int or index < 0:
            raise ValueError('Invalid question index')
        qa = corpus[sample]['qa'][index]
        for c in (a, b):
            for field in ('question', 'answer', 'category', 'evidence'):
                expected = qa.get(field, [] if field == 'evidence' else None)
                if c.get(field, [] if field == 'evidence' else None) != expected:
                    raise ValueError(f'Dataset/report mismatch: {identity}, {field}')
        flags = []
        if a.get('correct') == 0 and b.get('correct') == 1:
            flags.append('gain')
        if a.get('correct') == 1 and b.get('correct') == 0:
            flags.append('regression')
        if a.get('correct') is None or b.get('correct') is None:
            flags.append('unresolved_judgment')
        if b.get('evidence_complete') is True and b.get('correct') == 0:
            flags.append('evidence_complete_failure')
        reasons[identity] = flags
        if not flags and a.get('correct') == b.get('correct'):
            agreements[str(a['category'])].append(identity)
    rng = random.Random(seed)
    sampled, strata = set(), {}
    for category, pool in sorted(agreements.items()):
        chosen = rng.sample(pool, min(len(pool), agreements_per_category))
        sampled.update(chosen)
        strata[category] = dict(eligible=len(pool), selected=len(chosen))
    selected = [k for k in sorted(left) if reasons[k] or k in sampled]
    rng.shuffle(selected)
    packet = dict(schema_version=VERSION, cases=[], conversations={})
    key = dict(schema_version=VERSION, seed=seed, source_hashes=source_hashes,
               dataset_hash=baseline.get('dataset_hash'), answers={}, cases={},
               selection=dict(total_questions=len(left), priority_questions=sum(bool(v) for v in reasons.values()),
                              agreement_strata=strata, selected_questions=len(selected),
                              reason_counts=dict(Counter(r for rs in reasons.values() for r in rs))))
    labels = dict(schema_version=VERSION, packet_sha256=None, reviews=[])
    for identity in selected:
        sample, index = identity
        case_id = digest([VERSION, seed, source_hashes, sample, index])[:24]
        conversation_id = digest([seed, source_hashes['dataset'], sample])[:24]
        packet['conversations'][conversation_id] = corpus[sample]['conversation']
        question = left[identity]
        row = dict(case_id=case_id, conversation_id=conversation_id,
                   question=question['question'], reference=question.get('answer'),
                   reference_evidence_ids=question.get('evidence', []), responses=[])
        conditions = ['baseline', 'treatment']
        rng.shuffle(conditions)
        for position, condition in enumerate(conditions):
            c = (left if condition == 'baseline' else right)[identity]
            answer_id = digest([case_id, position, seed])[:24]
            diagnostics = c.get('diagnostics', {})
            row['responses'].append(dict(answer_id=answer_id, prediction=c.get('prediction'),
                                        supplied_context=diagnostics.get('supplied_context')))
            key['answers'][answer_id] = dict(case_id=case_id, condition=condition,
                original_correct=c.get('correct'), original_judge=c.get('judge'),
                trace_stages=[t.get('stage') for t in diagnostics.get('retrieval_traces', [])])
            labels['reviews'].append(dict(answer_id=answer_id, reviewer_id=None,
                reviewed_at=None, provenance=None, correct=None, reference_ambiguity=None,
                failure_stage=None, notes=''))
        key['cases'][case_id] = dict(sample_id=sample, question_index=index,
            category=question['category'], reasons=reasons[identity] or ['sampled_agreement'])
        packet['cases'].append(row)
    key['packet_sha256'] = labels['packet_sha256'] = digest(packet)
    return packet, key, labels


def summarize(packet, key, documents):
    """Import human reviews into a separate report; never change automated labels."""
    if packet.get('schema_version') != VERSION or key.get('schema_version') != VERSION:
        raise ValueError('Unsupported packet/key schema')
    if digest(packet) != key['packet_sha256']:
        raise ValueError('Packet/key identity mismatch')
    expected = {r['answer_id'] for c in packet['cases'] for r in c['responses']}
    if expected != set(key['answers']):
        raise ValueError('Packet/key answer identities differ')
    grouped, seen, accepted = defaultdict(list), set(), []
    for document in documents:
        if document.get('schema_version') != VERSION or document.get('packet_sha256') != key['packet_sha256']:
            raise ValueError('Review belongs to a different packet/schema')
        for review in document['reviews']:
            answer_id = review['answer_id']
            if answer_id not in expected:
                raise ValueError('Unknown answer identity')
            # An untouched template is pending, never an incorrect human label.
            if review.get('correct') is None:
                continue
            if type(review['correct']) is not int or review['correct'] not in (0, 1):
                raise ValueError('Human correctness must be integer 0 or 1')
            reviewer = review.get('reviewer_id')
            if not isinstance(reviewer, str) or not reviewer.strip() or review.get('provenance') != 'human_review':
                raise ValueError('Completed labels require reviewer identity and human_review attestation')
            timestamp = datetime.fromisoformat(review.get('reviewed_at') or '')
            if timestamp.tzinfo is None:
                raise ValueError('Review timestamps require a timezone')
            if type(review.get('reference_ambiguity')) is not bool or review.get('failure_stage') not in STAGES:
                raise ValueError('Completed labels require ambiguity and failure-stage fields')
            if not isinstance(review.get('notes'), str):
                raise ValueError('Review notes must be text')
            if (answer_id, reviewer) in seen:
                raise ValueError('Duplicate reviewer/answer label')
            seen.add((answer_id, reviewer))
            record = dict(review)
            stages = key['answers'][answer_id]['trace_stages']
            if record['failure_stage'] in {'candidate_retrieval', 'reranking', 'packing'} and not {'reranker_pool', 'cosine_pool'}.intersection(stages):
                record['reported_failure_stage'] = record['failure_stage']
                record['failure_stage'] = 'unresolved'
                record['stage_limitation'] = 'Original candidate-pool trace unavailable'
            grouped[answer_id].append(record)
            accepted.append(record)
    totals = dict(selected_questions=key['selection']['selected_questions'],
                  selected_answers=len(expected), reviewed_answers=len(grouped),
                  human_label_count=len(accepted), pending_answers=len(expected)-len(grouped),
                  multi_reviewer_answers=0, reviewer_disagreements=0,
                  resolved_answers=0, calibration_denominator=0, judge_disagreements=0,
                  reference_ambiguous_labels=sum(r['reference_ambiguity'] for r in accepted))
    by_stratum = defaultdict(lambda: dict(reviewed_answers=0, resolved_answers=0, calibration_denominator=0, judge_disagreements=0))
    answers = []
    for answer_id, reviews in sorted(grouped.items()):
        original = key['answers'][answer_id]
        case = key['cases'][original['case_id']]
        stratum = 'sampled_agreement' if case['reasons'] == ['sampled_agreement'] else 'priority'
        bucket = by_stratum[stratum]
        bucket['reviewed_answers'] += 1
        outcomes = {r['correct'] for r in reviews}
        totals['multi_reviewer_answers'] += len(reviews) > 1
        totals['reviewer_disagreements'] += len(outcomes) > 1
        resolved = next(iter(outcomes)) if len(outcomes) == 1 else None
        if resolved is not None:
            totals['resolved_answers'] += 1
            bucket['resolved_answers'] += 1
            if original['original_correct'] is not None:
                totals['calibration_denominator'] += 1
                bucket['calibration_denominator'] += 1
                mismatch = resolved != original['original_correct']
                totals['judge_disagreements'] += mismatch
                bucket['judge_disagreements'] += mismatch
        answers.append(dict(answer_id=answer_id, **original, **case,
                            human_correct=resolved, reviews=reviews))
    return dict(schema_version=VERSION, packet_sha256=key['packet_sha256'],
                selection=key['selection'], totals=totals, by_stratum=dict(by_stratum), answers=answers,
                limitations=['Human provenance is reviewer-attested, not independently authenticated.',
                    'Priority cases are oversampled; these counts are not population accuracy.',
                    'Single-reviewer labels lack independent agreement checks.',
                    'Conflicting reviewer labels remain unresolved; retain originals and obtain a new adjudicator.',
                    'Evidence-ID coverage is diagnostic and does not establish semantic sufficiency.'])


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('prepare')
    for name in ('baseline', 'treatment', 'dataset', 'output'):
        export.add_argument('--' + name, required=True, type=Path)
    export.add_argument('--seed', type=int, default=20261103)
    export.add_argument('--agreements-per-category', type=int, default=2)
    review = commands.add_parser('summarize')
    for name in ('packet', 'key', 'output'):
        review.add_argument('--' + name, required=True, type=Path)
    review.add_argument('--reviews', required=True, nargs='+', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            inputs = {name: read(getattr(args, name)) for name in ('baseline', 'treatment', 'dataset')}
            packet, key, labels = prepare(*(inputs[n][0] for n in ('baseline', 'treatment', 'dataset')),
                {n: value[1] for n, value in inputs.items()}, args.seed, args.agreements_per_category)
            key['metadata_warnings'] = {n: metadata_warnings(getattr(args, n).name, inputs[n][0])
                                        for n in ('baseline', 'treatment')}
            outputs = [(args.output/'reviewer'/'packet.json', packet),
                       (args.output/'reviewer'/'labels.template.json', labels),
                       (args.output/'private'/'key.json', key)]
            if any(p.exists() for p, _ in outputs):
                raise ValueError('Output already exists; choose a new directory')
            for path, value in outputs:
                write_new(path, value)
            print(json.dumps(key['selection'], sort_keys=True))
        else:
            packet, key = read(args.packet)[0], read(args.key)[0]
            report = summarize(packet, key, [read(p)[0] for p in args.reviews])
            write_new(args.output, report)
            print(json.dumps(report['totals'], sort_keys=True))
    except (ValueError, KeyError, IndexError, TypeError, OSError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
