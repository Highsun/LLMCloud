"""Snapshot final rating files before loading the private model assignment.

Only local E-drive files are processed. No rating is changed or invented.
The received A sheet declares AI delegation; this is not two-human validation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/mnt/e/LLMCloud/data/experiments/e01-20261115')
EXPERIMENT = Path('/home/l7/LLMCloud/data/experiments/e01-20261115')
EXPECTED = {(f'C{i:02}', label) for i in range(1, 13) for label in ('A', 'B')}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def put(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def parse(raw):
    rows, seen = [], set()
    for line in raw.decode('utf-8-sig').splitlines():
        if not re.match(r'^\s*\|\s*C\d', line):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        assert len(cells) == 7, 'Expected seven table columns'
        case, label, *rest = cells
        key = (case, label)
        assert key in EXPECTED and key not in seen, 'Unexpected/duplicate case and label'
        seen.add(key)
        assert all(re.fullmatch(r'[0-9]+', c) for c in rest[:4]), 'Scores must be integers'
        accuracy, clarity, boundary, written_total = map(int, rest[:4])
        assert 0 <= accuracy <= 2 and 0 <= clarity <= 1 and 0 <= boundary <= 1
        assert 0 <= written_total <= 4, 'Invalid written total'
        total = accuracy + clarity + boundary
        rows.append({'case_id': case, 'label': label, 'accuracy': accuracy,
                     'clarity': clarity, 'boundary': boundary, 'total': total,
                     'written_total': written_total, 'total_recomputed': written_total != total,
                     'reason': rest[4] or None})
    assert seen == EXPECTED and len(rows) == 24, 'Incomplete rating table'
    return sorted(rows, key=lambda r: (r['case_id'], r['label']))


def lock():
    files = {'member_a': ROOT / 'scores-member-a-completed.md',
             'member_b': ROOT / 'scores-member-b.md'}
    raw = {name: path.read_bytes() for name, path in files.items()}
    parsed = {name: parse(value) for name, value in raw.items()}
    assert 'GPT-6 Astra' in raw['member_a'].decode('utf-8-sig')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / ('ratings-locked-' + stamp)
    target.mkdir()
    manifest = {'status': 'both_received_score_files_validated_and_snapshotted_before_unblinding',
        'locked_at_utc': now(), 'basis': 'User reported both sheets complete and saved the received A sheet; requested verification, SHA256 lock, reveal and summary in the ongoing chat.',
        'rater_sources': {
            'member_a': 'Received file declares GPT-6 Astra delegated evaluation for member A; human re-review not established by this file.',
            'member_b': 'User personal subjective evaluation; source header metadata remains unfilled. Completion confirmed in chat; snapshot timestamp is receipt/lock time, not claimed personal scoring time.'},
        'missing_reasons': {name: sum(r['reason'] is None for r in rows) for name,rows in parsed.items()},
        'missing_reasons_policy': 'Accepted under user instruction; retained as unprovided, never invented.',
        'aggregation_policy': 'Use sum of original accuracy/clarity/boundary per frozen protocol. Preserve written totals and record arithmetic mismatches without changing original files or component scores.',
        'arithmetic_mismatches': {name: [{'case_id': r['case_id'], 'label': r['label'], 'written_total': r['written_total'], 'component_sum': r['total']}
            for r in rows if r['total_recomputed']] for name, rows in parsed.items()},
        'files': {}, 'private_mapping_not_opened_during_lock': True}
    for name, data in raw.items():
        filename = name + '.original.md'
        with (target / filename).open('xb') as stream:
            stream.write(data)
        normalized = name + '.parsed.json'
        put(target / normalized, parsed[name])
        assert files[name].read_bytes() == data, 'Original changed during snapshot'
        manifest['files'][name] = {'source_path': str(files[name]), 'snapshot': filename,
            'sha256': digest(data), 'bytes': len(data), 'parsed': normalized,
            'parsed_sha256': digest((target / normalized).read_bytes()), 'valid_rows': 24}
    put(target / 'lock-manifest.json', manifest)
    with (target / 'SHA256SUMS.lock').open('x') as stream:
        for path in sorted(target.iterdir()):
            if path.name != 'SHA256SUMS.lock':
                stream.write(digest(path.read_bytes()) + '  ' + path.name + '\n')
    print(json.dumps({'status': manifest['status'], 'lock_dir': str(target),
        'locked_at_utc': manifest['locked_at_utc'],
        'score_sha256': {n:v['sha256'] for n,v in manifest['files'].items()},
        'missing_reasons': manifest['missing_reasons'], 'arithmetic_mismatches': manifest['arithmetic_mismatches']}, ensure_ascii=False))


def reveal(target):
    target = Path(target).resolve()
    assert target.parent == ROOT.resolve() and target.name.startswith('ratings-locked-')
    for line in (target / 'SHA256SUMS.lock').read_text().splitlines():
        expected, name = line.split('  ', 1)
        assert Path(name).name == name and digest((target / name).read_bytes()) == expected
    locked = read(target / 'lock-manifest.json')
    ratings = {}
    for name, item in locked['files'].items():
        snapshot = (target / item['snapshot']).read_bytes()
        assert digest(snapshot) == item['sha256']
        ratings[name] = parse(snapshot)
        assert ratings[name] == read(target / item['parsed'])
    # First private identity access happens only after the completed lock checks above.
    plan = read(EXPERIMENT / 'planning/experiment-plan.json')
    keypath = EXPERIMENT / 'private/blind-assignment-key.json'
    keybytes = keypath.read_bytes()
    assert digest(keybytes) == plan['fixed_evaluation']['blind_mapping_sha256']
    key = json.loads(keybytes)
    assert key['protocol_sha256'] == plan['received_file_sha256']['cloud-basics-eval-v2.json']
    mapping = {v['case_id']: {k:v[k] for k in ('A','B')} for v in key['assignments']}
    assert set(mapping) == {case for case,_ in EXPECTED}
    assert all(set(v.values()) == {'base','adapter'} for v in mapping.values())
    totals, per_case = {}, {}
    for member, rows in ratings.items():
        totals[member] = {model: {dim: 0 for dim in ('accuracy','clarity','boundary','total')}
                          for model in ('base','adapter')}
        cases = {case: {} for case in mapping}
        for row in rows:
            model = mapping[row['case_id']][row['label']]
            cases[row['case_id']][model] = {k:row[k] for k in ('accuracy','clarity','boundary','total')}
            for dim in totals[member][model]:
                totals[member][model][dim] += row[dim]
        changes = {'improved': [], 'unchanged': [], 'worse': []}
        for case, scores in cases.items():
            diff = scores['adapter']['total'] - scores['base']['total']
            changes['improved' if diff > 0 else 'worse' if diff < 0 else 'unchanged'].append(case)
        per_case[member] = {'scores': cases, 'cases_by_direction': changes}
        assert sum(v['total'] for v in totals[member].values()) == sum(r['total'] for r in rows)
    pooled = {model: {dim: sum(totals[m][model][dim] for m in totals) for dim in ('accuracy','clarity','boundary','total')}
              for model in ('base','adapter')}
    means = {model: {dim: v / 2 for dim,v in pooled[model].items()} for model in pooled}
    paired_mean = []
    for case in sorted(mapping):
        values = {model: sum(per_case[m]['scores'][case][model]['total'] for m in totals) / 2
                  for model in ('base','adapter')}
        paired_mean.append({'case_id': case, **values, 'difference': values['adapter'] - values['base']})
    agreement = sum(per_case['member_a']['scores'][case][model]['total'] == per_case['member_b']['scores'][case][model]['total']
                    for case in mapping for model in ('base','adapter'))
    summary = {'status': 'rating_files_locked_revealed_and_summarized', 'revealed_at_utc': now(),
        'task_id': '8099c629-36a0-418f-ba7b-80a6e6c0e75f', 'build_id': '8cf9ede8899f618a',
        'mapping_sha256': digest(keybytes), 'mapping_protocol_sha256': key['protocol_sha256'],
        'lock_manifest_sha256': digest((target / 'lock-manifest.json').read_bytes()),
        'source_sha256': {n:v['sha256'] for n,v in locked['files'].items()},
        'rater_sources': locked['rater_sources'], 'missing_reasons': locked['missing_reasons'],
        'aggregation_policy': locked['aggregation_policy'], 'arithmetic_mismatches': locked['arithmetic_mismatches'],
        'totals_per_rater_max48': totals, 'pooled_totals_max96': pooled,
        'equal_rater_mean_totals_max48': means, 'per_case': per_case,
        'per_case_equal_rater_means': paired_mean, 'same_total_score_count_out_of24': agreement,
        'evaluation_type': 'One personal subjective human rating plus one file-declared AI-delegated rating; not verified two-human blind review.',
        'limitations': ['12 fixed prompts, one tiny training run, no statistical generalization claimed.',
            'Member B reasons absent and rating metadata placeholders retained.',
            'A file declares AI delegation; independent human endorsement is not established.',
            'Equal weighting is a descriptive aggregate; per-source results must remain visible.',
            'No rerating, training, or generation was performed after seeing scores.']}
    put(target / 'revealed-assignment.json', {'revealed_at_utc': summary['revealed_at_utc'],
        'lock_manifest_sha256': summary['lock_manifest_sha256'], 'mapping': mapping})
    put(target / 'rating-summary.json', summary)
    with (target / 'SHA256SUMS.reveal').open('x') as stream:
        for name in ('revealed-assignment.json','rating-summary.json'):
            stream.write(digest((target / name).read_bytes()) + '  ' + name + '\n')
    print(json.dumps({'status': summary['status'], 'rater_totals': totals, 'pooled_max96': pooled,
        'equal_rater_mean_max48': means, 'case_changes': {m:v['cases_by_direction'] for m,v in per_case.items()},
        'agreement_out_of24': agreement, 'mapping': mapping}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('lock','reveal'))
    parser.add_argument('--lock-dir', type=Path)
    args = parser.parse_args()
    if args.phase == 'lock':
        lock()
    else:
        assert args.lock_dir is not None
        reveal(args.lock_dir)
