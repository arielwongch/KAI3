"""Freeze a matched compaction sweep; provider calls require explicit --execute.

Run from the repository root. Every condition starts with the same raw dataset;
percentages are never derived by recompressing another condition's output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def make_campaign(data, percentages, mode='one_shot', trigger=2000, budget=8000,
                  source_entries=None, repeats=1, question_limit=0):
    # Import only on use: --help works without API credentials or dependencies.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from Compaction import validate_options, digest
    from Benchmark import validate_dataset
    validate_dataset(data)
    if type(repeats) is not int or repeats < 1:
        raise ValueError('repeats must be positive.')
    if type(budget) is not int or budget < 1:
        raise ValueError('reader allowance must be positive.')
    conditions = []
    for repeat in range(1, repeats + 1):
        for index, percentage in enumerate(percentages, 1):
            controls = validate_options(dict(retain_percent=percentage, compaction_mode=mode,
                compaction_trigger_tokens=trigger, compaction_source_entries=source_entries))
            conditions.append(dict(filename=f'compaction-{mode}-{percentage:g}pct-r{repeat}-{index}.json',
                repeat=repeat, options=dict(module='compaction', all_conversations=True, question_limit=question_limit,
                    categories=[1, 2, 3, 4, 5], memory_context_tokens=budget, **controls)))
    return dict(schema_version=1, dataset_sha256=digest(data),
                sources=[dict(sample_id=s['sample_id'], conversation_sha256=digest(s['conversation'])) for s in data],
                source_policy='independent conditions from identical frozen raw data; no QA write-back',
                conditions=conditions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--percentages', type=float, nargs='+', default=[100, 75, 50, 35, 25, 15, 10, 5])
    parser.add_argument('--mode', choices=['one_shot', 'repeated'], default='one_shot')
    parser.add_argument('--trigger-tokens', type=int, default=2000)
    parser.add_argument('--reader-tokens', type=int, default=8000)
    parser.add_argument('--source-entries', type=int)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--question-limit', type=int, default=0)
    parser.add_argument('--execute', action='store_true', help='Make paid provider calls for every condition.')
    args = parser.parse_args()
    data = json.loads(Path(args.dataset).read_text(encoding='utf-8-sig'))
    campaign = make_campaign(data, args.percentages, args.mode, args.trigger_tokens,
                             args.reader_tokens, args.source_entries, args.repeats, args.question_limit)
    root = Path(args.output_dir)
    # Avoid overwriting a previous experiment or accidentally mixing campaigns.
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'frozen-dataset.json'
    source.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    campaign['source_file_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    (root / 'campaign.json').write_text(json.dumps(campaign, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Prepared {len(campaign["conditions"])} conditions in {root}.')
    if not args.execute:
        print('No provider calls made. Inspect campaign.json; --execute enables a new paid campaign.')
        return
    from Benchmark import BenchmarkJob
    from BenchmarkStore import atomic_json
    for condition in campaign['conditions']:
        job = BenchmarkJob(data, condition['options'])
        job.result['compaction_campaign'] = dict(dataset_sha256=campaign['dataset_sha256'],
            repeat=condition['repeat'], campaign_sha256=hashlib.sha256((root / 'campaign.json').read_bytes()).hexdigest())
        target = root / condition['filename']
        job.set_persistence_callback(lambda snapshot, path=target: atomic_json(str(path), snapshot))
        try:
            job.run()
        finally:
            atomic_json(str(target), job.snapshot())


if __name__ == '__main__':
    main()
