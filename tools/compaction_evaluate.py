"""Offline compaction fidelity annotations and paired campaign statistics."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from CompactionFidelity import prepare_review, score_review, calibrate
from CampaignAnalysis import compare_campaigns


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number.')))


def write_new(path, value):
    # Serialize/validate before exclusive creation. Never truncate an existing file.
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # Linking a complete file publishes atomically without replacing an
        # existing destination, even if another writer raced the earlier check.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Create a source-bound review template with null labels.')
    prepare.add_argument('--report', required=True)
    prepare.add_argument('--propositions', required=True)
    score = commands.add_parser('score', help='Score human/imported labels without invoking a model.')
    score.add_argument('--report', required=True)
    score.add_argument('--review', required=True)
    evaluator = score.add_mutually_exclusive_group(required=True)
    evaluator.add_argument('--annotator', help='Human annotator name or stable ID.')
    evaluator.add_argument('--evaluator', help='JSON provenance with exact external judge requests/responses.')
    calibration = commands.add_parser('calibrate', help='Compare annotations against a human reference.')
    calibration.add_argument('--reference', required=True)
    calibration.add_argument('--candidate', required=True)
    compare = commands.add_parser('compare', help='Paired conversation-clustered confidence intervals.')
    compare.add_argument('--left', nargs='+', required=True)
    compare.add_argument('--right', nargs='+', required=True)
    compare.add_argument('--vary', nargs='+', default=['retain_percent'])
    compare.add_argument('--resamples', type=int, default=10000)
    compare.add_argument('--seed', type=int, default=42, help='Local bootstrap seed; not a provider seed.')
    compare.add_argument('--confidence', type=float, default=.95)
    for command in (prepare, score, calibration, compare):
        command.add_argument('--output', required=True, help='New JSON path; existing paths are rejected.')
    args = parser.parse_args()
    try:
        if Path(args.output).exists():
            raise ValueError('Output already exists; choose a new path.')
        if args.command == 'prepare':
            result = prepare_review(read(args.report), read(args.propositions))
        elif args.command == 'score':
            provenance = dict(type='human', name=args.annotator) if args.annotator else read(args.evaluator)
            result = score_review(read(args.report), read(args.review), provenance)
        elif args.command == 'calibrate':
            result = calibrate(read(args.reference), read(args.candidate))
        else:
            result = compare_campaigns([read(p) for p in args.left], [read(p) for p in args.right],
                args.vary, args.resamples, args.seed, args.confidence)
        write_new(args.output, result)
        print('Wrote ' + args.output + '; no model calls made.')
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(1, 'Compaction evaluation failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
