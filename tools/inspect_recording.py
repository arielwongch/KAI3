"""Offline integrity validation and JSON inspection; never invoke a model."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ExperimentRecording import validate, get, archive_metrics
from BenchmarkStore import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('--artifact', help='Print one full artifact by SHA-256.')
    args = parser.parse_args()
    try:
        report = read_json(args.report)
        validate(report)
        archive = report.get('recording')
        if archive is None:
            print('Legacy report: no exact-state recording archive; original results remain readable.')
            return
        if args.artifact:
            value = get(archive, {'artifact_sha256': args.artifact})
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(dict(run_id=report.get('run_id'), valid=True,
                **archive_metrics(archive), file_bytes=Path(args.report).stat().st_size,
                kinds=dict(Counter(v['kind'] for v in archive['artifacts'].values()))), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, 'Recording validation failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
