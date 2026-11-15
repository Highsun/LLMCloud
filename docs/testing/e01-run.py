"""B-side E01 orchestration. Run with the existing WSL training interpreter.

Uses original production preparation, training, audit and reload entry points.
Private corpus, responses, models and logs stay on E-backed WSL storage.
No SQL/API changes, commits, automatic scores, or automatic hyperparameter search.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

REPO = Path('/home/l7/LLMCloud-e01-20261115')
ORIGINAL = Path('/home/l7/LLMCloud')
ROOT = ORIGINAL / 'data/experiments/e01-20261115'
RECEIVED = Path('/mnt/e/LLMCloud/data/handoffs/20261115-e01-a-review/received-20261115')
RECORDS = ROOT / 'execution'
PREPARED = ROOT / 'runtime-data/prepared/e01-reviewed'
CACHE = ORIGINAL / 'data/models/huggingface/hub'
REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
EXPECTED_PATCH = '16c42f20ac5b4b725b352c06947efca17ca1cd0b5c1ddc82cc2be7b1916b2437'
PATCH = RECEIVED.parent / 'e01-tools.patch'
PYTHON = str(ORIGINAL / '.venv/bin/python')
ALLOWED = {'scripts/prepare_dataset.py', 'scripts/reload_adapter.py',
           'trainer/dataset_manifest.py', 'trainer/reload.py'}
sys.path.insert(0, str(REPO))
os.chdir(REPO)
os.environ.update(HF_HOME=str(CACHE.parent), HF_HUB_CACHE=str(CACHE),
                  HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                  HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                  CUDA_VISIBLE_DEVICES='0', PYTHONUNBUFFERED='1')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def code_fingerprint():
    assert git('rev-parse', 'HEAD') == '390a7d91906e703c5fee785650d89e1a5a80a1d5'
    status = git('status', '--porcelain')
    paths = {line[3:] for line in status.splitlines()} if status else set()
    # Preserve the first status column: strip() only affects the first line.
    paths = set(subprocess.check_output(['git', '-C', str(REPO), 'diff', '--name-only'], text=True).splitlines())
    assert paths == ALLOWED, paths
    assert not git('ls-files', '--others', '--exclude-standard')
    assert not git('diff', '--cached', '--name-only')
    assert sha(PATCH) == EXPECTED_PATCH
    subprocess.run(['git', 'apply', '--reverse', '--check', str(PATCH)], cwd=REPO, check=True)
    changes = git('diff', '--binary').encode()
    return {'base_commit': git('rev-parse', 'HEAD'), 'working_tree_dirty': True,
            'received_patch_sha256': sha(PATCH), 'git_diff_sha256': hashlib.sha256(changes).hexdigest(),
            'files': {name: sha(REPO / name) for name in sorted(ALLOWED)},
            'uv_lock_sha256': sha(REPO / 'uv.lock'), 'runner_sha256': sha(Path(__file__))}


def run(name, args, *, extra_env=None):
    start = now()
    env = {**os.environ, **(extra_env or {})}
    out, err = RECORDS / (name + '.stdout.json'), RECORDS / (name + '.stderr.log')
    with out.open('x') as stdout, err.open('x') as stderr:
        proc = subprocess.Popen(args, cwd=REPO, env=env, stdout=stdout, stderr=stderr)
        print(json.dumps({'stage': name, 'pid': proc.pid, 'started_at': start}), flush=True)
        rc = proc.wait()
    write(RECORDS / (name + '.process.json'), {'command': args, 'pid': proc.pid, 'returncode': rc,
          'started_at': start, 'finished_at': now(), 'stdout_sha256': sha(out), 'stderr_sha256': sha(err)})
    assert rc == 0, f'{name} failed, exit={rc}; inspect private stderr (not auto-retried)'
    print(json.dumps({'stage': name, 'exit_code': rc, 'finished_at': now()}), flush=True)
    return read(out)


def checksums(directory):
    directory = Path(directory)
    target = directory / 'SHA256SUMS'
    with target.open('x') as stream:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path != target:
                stream.write(f'{sha(path)}  {path.relative_to(directory).as_posix()}\n')


def prepare():
    RECORDS.mkdir()  # Do not overwrite a previous formal attempt.
    plan = read(ROOT / 'planning/experiment-plan.json')
    original_hashes = {name: sha(RECEIVED / name) for name in plan['received_file_sha256']}
    assert original_hashes == plan['received_file_sha256']
    write(RECORDS / 'code-provenance.json', code_fingerprint())
    shutil.copyfile(PATCH, RECORDS / 'received-e01-tools.patch')
    with (RECORDS / 'working-tree.diff').open('x') as stream:
        subprocess.run(['git', 'diff', '--binary'], cwd=REPO, stdout=stream, check=True)
    approved = ROOT / 'reviewed-input'
    approved.mkdir()
    for name in original_hashes:
        if name != 'curation.json':
            shutil.copyfile(RECEIVED / name, approved / name)
    curation = read(RECEIVED / 'curation.json')
    assert len(curation['rows']) == 120 and len({r['group_id'] for r in curation['rows']}) == 26
    assert all(r['reviewed'] is False for r in curation['rows'])
    for row in curation['rows']:
        row['reviewed'] = True
    write(approved / 'curation.json', curation)
    write(approved / 'approval-record.json', {
        'recorded_at': now(), 'basis': 'User relayed A agreement in this chat on 2026-11-15; proceed with reviewed 120 rows, 26 families, v2 protocol and SHA-256; continue E01 if actual split matches preflight.',
        'b_review_basis': 'Prior user-delegated B adoption plus A revised attachment and B independent follow-up check.',
        'reviewed_flags': 'Set only in this new working copy, on explicit authorization; no invented personal signatures.',
        'received_files_sha256': original_hashes, 'approved_files_sha256': {n: sha(approved / n) for n in original_hashes},
        'changed_input': 'curation.json: 120 reviewed flags false to true; record IDs, groups and sources unchanged.'})
    cfg = read(ROOT / 'planning/training-config-proposed.json')
    assert cfg == plan['training_config']
    write(RECORDS / 'training-config-locked.json', cfg)
    write(RECORDS / 'evaluation-policy-locked.json', {
        'locked_at': now(), 'before_training_and_heldout_access': True,
        'no_hyperparameter_search': True, 'heldout_passes_per_model': 1,
        'heldout': 'One teacher-forced forward pass per row per model; sum float32 causal cross entropy over original supervised answer labels (including template EOS), divide by total shifted supervised tokens; perplexity=exp(mean token NLL). Batch1; no padding; max_seq_length512; no test-driven changes.',
        'validation': 'Original Trainer sample-averaged eval loss, used for observation only; no checkpoint selection.',
        'fixed_cases': {'protocol_sha256': original_hashes['cloud-basics-eval-v2.json'], 'cases': 12,
                        'max_new_tokens': 192, 'do_sample': False, 'num_beams': 1, 'independent_reload': True},
        'scoring': 'Two independent human raters, empty score tables retained; reveal private mapping only after both scores locked.'})
    args = [PYTHON, 'scripts/prepare_dataset.py', '--source', str(approved / 'cloud-basics-zh-candidate.jsonl'),
            '--curation', str(approved / 'curation.json'), '--sources', str(approved / 'sources.json'),
            '--eval-protocol', str(approved / 'cloud-basics-eval-v2.json'), '--seed', '42']
    preview = run('formal-check-only', [*args, '--check-only'])
    assert preview['review_status'] == 'reviewed' and preview['protocol_version'] == '2.0.0'
    assert {k: (v['row_count'], len(v['group_ids'])) for k, v in preview['splits'].items()} == {
        'train': (96, 22), 'validation': (16, 2), 'test': (8, 2)}
    actual = run('formal-prepare', [*args, '--output', str(PREPARED)], extra_env={'DATA_DIR': str(ROOT / 'runtime-data')})
    assert actual == preview == read(PREPARED / 'manifest.json')
    # Independent rebuild compares all five output byte strings without writing a second split.
    spec = importlib.util.spec_from_file_location('e01_prepare', REPO / 'scripts/prepare_dataset.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files, manifest = module.plan_dataset(approved / 'cloud-basics-zh-candidate.jsonl', approved / 'curation.json',
        sources_path=approved / 'sources.json', protocol_path=approved / 'cloud-basics-eval-v2.json', seed=42)
    assert all((PREPARED / name).read_bytes() == data for name, data in files.items())
    checksums(PREPARED)
    tokencheck = run('tokenizer-check', [PYTHON, 'scripts/check_training_data.py', '--dataset', str(PREPARED / 'train.jsonl'),
        '--validation-dataset', str(PREPARED / 'validation.jsonl'), '--dataset-manifest', str(PREPARED / 'manifest.json'),
        '--revision', REVISION, '--cache-dir', str(CACHE), '--max-seq-length', '512'])
    assert tokencheck['train']['review_status'] == 'reviewed' and tokencheck['validation']['review_status'] == 'reviewed'
    assert tokencheck['train']['truncated_rows'] == tokencheck['validation']['truncated_rows'] == 0
    assert {name: sha(RECEIVED / name) for name in original_hashes} == original_hashes
    task = str(uuid.uuid4())
    write(RECORDS / 'run-state.json', {'task_id': task, 'prepared_dir': str(PREPARED), 'build_id': manifest['build_id'],
        'data_manifest_sha256': sha(PREPARED / 'manifest.json'), 'prepared_at': now(), 'expected_optimizer_steps': 12,
        'source_unchanged': True, 'split_matches_preflight': True})
    print(json.dumps({'status': 'formal_data_prepared', 'task_id': task, 'manifest': manifest,
                      'manifest_sha256': sha(PREPARED / 'manifest.json')}, ensure_ascii=False), flush=True)


def gpu_guard():
    from backend.app.core.worker_lock import WorkerInstanceLock
    lock = WorkerInstanceLock(ORIGINAL / 'logs')
    lock.acquire()
    try:
        apps = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory',
                                        '--format=csv,noheader'], text=True).strip()
        assert not apps, f'Existing CUDA compute process: {apps}'
        return lock
    except BaseException:
        lock.release()
        raise


def train():
    state = read(RECORDS / 'run-state.json')
    assert code_fingerprint() == read(RECORDS / 'code-provenance.json')
    lock = gpu_guard()
    info = {'recorded_at': now(), 'lock_path': str(lock.path), 'lock_inode': lock.path.stat().st_ino,
            'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used',
                    '--format=csv,noheader'], text=True).strip(), 'e_drive_free_bytes': shutil.disk_usage('/mnt/e').free}
    try:
        write(RECORDS / 'gpu-before-training.json', info)
        result = run('train', [PYTHON, '-m', 'trainer.train', '--dataset', str(PREPARED / 'train.jsonl'),
            '--validation-dataset', str(PREPARED / 'validation.jsonl'), '--dataset-manifest', str(PREPARED / 'manifest.json'),
            '--revision', REVISION, '--task-id', state['task_id'], '--data-dir', str(ROOT / 'runtime-data'),
            '--log-dir', str(ROOT / 'runtime-logs'), '--cache-dir', str(CACHE), '--precision', 'bf16',
            '--config', str(RECORDS / 'training-config-locked.json')])
    finally:
        lock.release()
    from trainer.artifacts import verify_training_artifacts
    audit = verify_training_artifacts(ROOT / 'runtime-data/outputs' / state['task_id'],
        outputs_root=ROOT / 'runtime-data/outputs', expected_task_id=state['task_id'], expected_revision=REVISION)
    m = audit.manifest
    assert m.train_dataset.review_status == m.validation_dataset.review_status == 'reviewed'
    assert m.train_dataset.build_id == state['build_id']
    assert m.summary.completed_steps == m.summary.total_steps == 12
    assert m.runtime.max_steps is None and m.config.num_train_epochs == 1
    assert code_fingerprint() == read(RECORDS / 'code-provenance.json')
    write(RECORDS / 'train-audit.json', {'status': 'artifacts_verified', 'tensor_count': audit.tensor_count,
          'manifest_sha256': sha(result['manifest_path']), 'manifest': m.model_dump(mode='json'),
          'training_process_exited': True, 'shared_lock_released': True})
    print(json.dumps({'status': 'training_and_independent_audit_passed', 'task_id': state['task_id'],
                      'summary': m.summary.model_dump(mode='json')}, ensure_ascii=False), flush=True)


def compare():
    state = read(RECORDS / 'run-state.json')
    assert read(RECORDS / 'train.process.json')['returncode'] == 0
    protocol = read(ROOT / 'reviewed-input/cloud-basics-eval-v2.json')
    assert len(protocol['cases']) == 12
    lock = gpu_guard()
    results = []
    try:
        for case in protocol['cases']:
            result = run('compare-' + case['id'], [PYTHON, 'scripts/reload_adapter.py', '--task-id', state['task_id'],
                '--revision', REVISION, '--data-dir', str(ROOT / 'runtime-data'), '--cache-dir', str(CACHE),
                '--compare', '--prompt', case['prompt'], '--max-new-tokens', '192'])
            assert result['status'] == 'reload_verified' and result['adapter_weights_matched']
            assert result['pid'] != read(RECORDS / 'train.process.json')['pid']
            assert result['task_id'] == state['task_id'] and result['max_new_tokens'] == 192
            assert result['base'] and result['adapter'] and result['do_sample'] is False
            results.append({'case_id': case['id'], 'prompt_sha256': hashlib.sha256(case['prompt'].encode()).hexdigest(),
                'pid': result['pid'], 'input_tokens': result['input_tokens'],
                'base_tokens': result['base']['generated_tokens'], 'adapter_tokens': result['adapter']['generated_tokens'],
                'base_reached_limit': result['base']['generated_tokens'] == 192,
                'adapter_reached_limit': result['adapter']['generated_tokens'] == 192,
                'elapsed_seconds': result['elapsed_seconds'], 'adapter_weights_matched': result['adapter_weights_matched']})
    finally:
        lock.release()
    write(RECORDS / 'fixed-case-summary.json', {'status': 'all_12_pairs_generated', 'cases': results,
          'max_new_tokens': 192, 'do_sample': False, 'scores': 'pending_independent_human_rating'})
    print(json.dumps({'status': '12_fixed_case_pairs_generated', 'scores': 'pending'}), flush=True)


def heldout():
    state = read(RECORDS / 'run-state.json')
    assert read(RECORDS / 'evaluation-policy-locked.json')['before_training_and_heldout_access']
    # Exclusive marker prevents accidental repeat after a failure or interrupted evaluation.
    write(RECORDS / 'heldout-started.json', {'started_at': now(), 'policy_sha256': sha(RECORDS / 'evaluation-policy-locked.json'),
          'test_sha256': sha(PREPARED / 'test.jsonl'), 'passes_per_model': 1, 'pid': os.getpid()})
    lock = gpu_guard()
    try:
        import torch
        import torch.nn.functional as F
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel, get_peft_model_state_dict
        from safetensors.torch import load_file
        from trainer.artifacts import verify_training_artifacts
        from trainer.model_cache import verify_model_cache
        from trainer.dataset import DatasetScanner
        from trainer.preprocessing import tokenize_record
        verified = verify_training_artifacts(ROOT / 'runtime-data/outputs' / state['task_id'],
            outputs_root=ROOT / 'runtime-data/outputs', expected_task_id=state['task_id'], expected_revision=REVISION)
        cached = verify_model_cache(CACHE, REVISION)
        scanner, records = DatasetScanner(), []
        with (PREPARED / 'test.jsonl').open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                records.extend(scanner.feed(chunk))
        records.extend(scanner.finish())
        assert scanner.stats.sha256 == read(PREPARED / 'manifest.json')['splits']['test']['sha256']
        assert len(records) == 8
        tokenizer = AutoTokenizer.from_pretrained(str(verified.result.tokenizer_dir), local_files_only=True, trust_remote_code=False)
        original = AutoTokenizer.from_pretrained(str(cached.snapshot_dir), local_files_only=True, trust_remote_code=False)
        assert tokenizer.get_vocab() == original.get_vocab() and tokenizer.chat_template == original.chat_template
        assert tokenizer.eos_token_id == original.eos_token_id and tokenizer.pad_token_id == original.pad_token_id
        samples = [tokenize_record(row, tokenizer, max_seq_length=512, row=i + 1) for i, row in enumerate(records)]
        assert all(not s.summary()['truncated'] for s in samples)
        torch.cuda.reset_peak_memory_stats()
        base = AutoModelForCausalLM.from_pretrained(str(cached.snapshot_dir), local_files_only=True,
            trust_remote_code=False, use_safetensors=True, dtype=torch.bfloat16)
        model = PeftModel.from_pretrained(base, str(verified.result.adapter_dir), local_files_only=True,
            is_trainable=False, autocast_adapter_dtype=True)
        current, saved = get_peft_model_state_dict(model), load_file(str(verified.result.adapter_dir / 'adapter_model.safetensors'))
        assert set(current) == set(saved) and all(torch.equal(current[k].detach().cpu(), saved[k]) for k in saved)
        del current, saved
        model.to('cuda:0').eval()
        totals = {}
        start = time.monotonic()
        for label in ('base', 'adapter'):
            rows = []
            with (model.disable_adapter() if label == 'base' else contextlib.nullcontext()):
                with torch.inference_mode():
                    for i, sample in enumerate(samples):
                        ids = torch.tensor([sample.input_ids], device='cuda:0')
                        labels = torch.tensor([sample.labels], device='cuda:0')
                        logits = model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
                        targets = labels[:, 1:].reshape(-1)
                        count = int((targets != -100).sum().item())
                        nll = F.cross_entropy(logits[:, :-1, :].float().reshape(-1, logits.shape[-1]),
                            targets, ignore_index=-100, reduction='sum').item()
                        assert count > 0 and math.isfinite(nll)
                        rows.append({'row': i + 1, 'supervised_tokens': count, 'nll_sum': nll})
                        del logits, ids, labels, targets
            tokens = sum(r['supervised_tokens'] for r in rows)
            total = sum(r['nll_sum'] for r in rows)
            totals[label] = {'rows': len(rows), 'supervised_tokens': tokens, 'nll_sum': total,
                             'token_mean_loss': total / tokens, 'perplexity': math.exp(total / tokens), 'per_row': rows}
        assert totals['base']['supervised_tokens'] == totals['adapter']['supervised_tokens']
        write(RECORDS / 'heldout-results.json', {'status': 'one_time_heldout_evaluated', 'recorded_at': now(),
            'pid': os.getpid(), 'task_id': state['task_id'], 'test_sha256': scanner.stats.sha256,
            'policy_sha256': sha(RECORDS / 'evaluation-policy-locked.json'), 'max_seq_length': 512,
            'truncated_rows': 0, 'adapter_weights_matched': True, 'elapsed_seconds': time.monotonic() - start,
            'peak_memory_allocated_bytes': torch.cuda.max_memory_allocated(), 'models': totals})
        print(json.dumps({'status': 'heldout_evaluated', 'models': {k: {n: v[n] for n in ('rows', 'supervised_tokens', 'token_mean_loss', 'perplexity')} for k,v in totals.items()}}), flush=True)
    finally:
        lock.release()


def blind():
    assert read(RECORDS / 'fixed-case-summary.json')['status'] == 'all_12_pairs_generated'
    # Mapping is deliberately never printed or copied to the report checkout.
    key = read(ROOT / 'private/blind-assignment-key.json')
    plan = read(ROOT / 'planning/experiment-plan.json')
    assert sha(ROOT / 'private/blind-assignment-key.json') == plan['fixed_evaluation']['blind_mapping_sha256']
    protocol = read(ROOT / 'reviewed-input/cloud-basics-eval-v2.json')
    assert key['protocol_sha256'] == sha(ROOT / 'reviewed-input/cloud-basics-eval-v2.json')
    assignments = {a['case_id']: a for a in key['assignments']}
    assert set(assignments) == {c['id'] for c in protocol['cases']}
    bundle = ROOT / 'blind-rating'
    bundle.mkdir()
    text = ['# E01 匿名回答评分材料', '',
        '请独立评分，每份回答准确性0–2、清晰度0–1、边界0–1，总分0–4。',
        '两位评分者分别锁定评分后再揭晓模型身份。回答达到192 token上限时可能未完整收尾。', '']
    for case in protocol['cases']:
        result = read(RECORDS / ('compare-' + case['id'] + '.stdout.json'))
        a = assignments[case['id']]
        assert {a['A'], a['B']} == {'base', 'adapter'}
        text.extend(['## ' + case['id'], '', case['prompt'], ''])
        for label in ('A', 'B'):
            answer = result[a[label]]
            text.extend(['### 回答 ' + label, '', answer['generated_text'], '',
                f"生成长度：{answer['generated_tokens']}/192 token", ''])
    with (bundle / 'paired-responses.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(text) + '\n')
    for name in ('scores-member-a.md', 'scores-member-b.md', 'scoring-rubric-v2.json'):
        shutil.copyfile(ROOT / 'planning' / name, bundle / name)
    checksums(bundle)
    import zipfile
    with zipfile.ZipFile(ROOT / 'e01-blind-rating.zip', 'x', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(bundle.iterdir()):
            z.write(path, arcname=path.name)
    write(RECORDS / 'blind-materials-summary.json', {'status': 'ready_for_independent_human_scoring',
        'cases': 12, 'responses': 24, 'scores_filled': 0,
        'archive_sha256': sha(ROOT / 'e01-blind-rating.zip'), 'identity_mapping_in_archive': False,
        'mapping_sha256_unchanged': sha(ROOT / 'private/blind-assignment-key.json') == plan['fixed_evaluation']['blind_mapping_sha256']})
    print(json.dumps({'status': 'blind_rating_package_ready', 'cases': 12, 'responses': 24, 'scores': 'pending'}), flush=True)


def finish():
    state = read(RECORDS / 'run-state.json')
    audit = read(RECORDS / 'train-audit.json')
    assert code_fingerprint() == read(RECORDS / 'code-provenance.json')
    originals = read(ROOT / 'planning/experiment-plan.json')['received_file_sha256']
    assert all(sha(RECEIVED / n) == h for n,h in originals.items())
    files, manifest = {}, read(PREPARED / 'manifest.json')
    for name in ('train', 'validation', 'test'):
        assert sha(PREPARED / (name + '.jsonl')) == manifest['splits'][name]['sha256']
    out = ROOT / 'runtime-data/outputs' / state['task_id']
    assert sha(out / 'manifest.json') == audit['manifest_sha256']
    from trainer.artifacts import verify_training_artifacts
    verify_training_artifacts(out, outputs_root=out.parent, expected_task_id=state['task_id'], expected_revision=REVISION)
    lock = gpu_guard()
    lock.release()
    result = {'status': 'e01_training_reload_and_objective_evaluation_complete_human_scores_pending',
        'completed_at': now(), 'task_id': state['task_id'], 'build_id': state['build_id'],
        'data_manifest_sha256': state['data_manifest_sha256'], 'artifact_manifest_sha256': audit['manifest_sha256'],
        'summary': audit['manifest']['summary'], 'fixed_cases': read(RECORDS / 'fixed-case-summary.json'),
        'heldout': read(RECORDS / 'heldout-results.json'), 'blind_materials': read(RECORDS / 'blind-materials-summary.json'),
        'original_attachments_unchanged': True, 'formal_splits_unchanged': True,
        'code_patch_unchanged': True, 'shared_lock_reacquired_and_released': True,
        'git_commit_or_push_performed': False, 'cloud_or_joint_acceptance_claimed': False}
    write(RECORDS / 'final-result.json', result)
    checksums(RECORDS)
    # D contains small summaries only, never corpus, responses, DB or model weights.
    report = Path(__file__).resolve().parents[2] / 'data/acceptance/b-review/laptop-3060/e01-formal-20261115'
    report.mkdir()
    for name in ('code-provenance.json', 'run-state.json', 'training-config-locked.json',
                 'evaluation-policy-locked.json', 'train.process.json', 'train-audit.json',
                 'fixed-case-summary.json', 'heldout-results.json', 'blind-materials-summary.json', 'final-result.json',
                 'tokenizer-check.stdout.json', 'gpu-before-training.json'):
        shutil.copyfile(RECORDS / name, report / name)
    shutil.copyfile(PREPARED / 'manifest.json', report / 'data-manifest.json')
    checksums(report)
    print(json.dumps({'status': result['status'], 'task_id': state['task_id'], 'build_id': state['build_id'],
                      'summary': result['summary'], 'small_evidence_export': str(report)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['prepare', 'train', 'compare', 'heldout', 'blind', 'finish'], required=True)
    args = parser.parse_args()
    globals()[args.phase]()
