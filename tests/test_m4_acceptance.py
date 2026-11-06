"""M4 tooling failure/boundary checks; synthetic CPU fixtures are not GPU evidence."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import warnings
import zipfile

from backend.app.core.config import Settings
from scripts.check_m4_acceptance import Acceptance, main
from scripts.m4_acceptance_support import audit_download, audit_gpu_output, check_serial, new_run_directory
from trainer.artifacts import sha256
from trainer.model_cache import resolve_model_paths
import test_training_artifacts as fixtures

ROOT = Path(__file__).resolve().parents[1]


class M4AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self):
        support = fixtures.TrainingArtifactTests()
        support.parent = self.root
        return support.bundle()

    def zip(self, source, *, omit=None, extra=None, tamper=None):
        archive = self.root / 'download.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            for item in source.rglob('*'):
                if item.is_file() and item.name != omit:
                    name = f'{source.name}/{item.relative_to(source).as_posix()}'
                    bundle.writestr(name, b'changed' if item.name == tamper else item.read_bytes())
            if extra:
                bundle.writestr(extra, b'unsafe')
        return archive

    def runner(self):
        shared = Settings(_env_file=None, data_dir=self.root / 'business', log_dir=self.root / 'shared-logs')
        run = self.root / str(uuid4())
        run.mkdir()
        return Acceptance(run, shared, resolve_model_paths(), steps=40, timeout=30,
                          baseline={'commit': 'b' * 40, 'working_tree_dirty': False})

    def test_new_run_cannot_reuse_escape_or_follow_link(self):
        parent = self.root / 'm4-07'
        created = new_run_directory(parent)
        with self.assertRaises(FileExistsError):
            new_run_directory(parent, created)
        with self.assertRaises(ValueError):
            new_run_directory(parent, self.root / str(uuid4()))
        with self.assertRaises(ValueError):
            new_run_directory(parent, parent / 'not-a-uuid')
        linked = self.root / 'linked'
        linked.symlink_to(parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            new_run_directory(linked)

    def test_serial_intervals_reject_overlap_and_unfinished(self):
        now = datetime.now(timezone.utc)
        first = {'id': str(uuid4()), 'status': 'COMPLETED', 'started_at': now.isoformat(),
                 'finished_at': (now + timedelta(seconds=2)).isoformat()}
        second = {**first, 'id': str(uuid4()), 'started_at': first['finished_at'],
                  'finished_at': (now + timedelta(seconds=3)).isoformat()}
        self.assertTrue(check_serial([first, second])['sql_intervals_do_not_overlap'])
        for bad in ({**second, 'started_at': first['started_at']}, {**second, 'status': 'RUNNING'},
                    {**second, 'id': first['id']}, {**second, 'started_at': '2026-11-06T00:00:00'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_serial([first, bad])

    def test_download_exact_bytes_and_original_shared_audit(self):
        source, manifest = self.bundle()
        result = audit_download(self.zip(source), source, self.root / 'unpacked')
        self.assertTrue(result['exact_source_bytes'])
        self.assertEqual(result['extracted']['metric_count'], 2)
        self.assertEqual(result['source_manifest_sha256'], sha256(source / 'manifest.json'))
        self.assertEqual((self.root / 'unpacked' / source.name / 'manifest.json').read_bytes(),
                         (source / 'manifest.json').read_bytes())

    def test_zip_missing_extra_traversal_duplicate_and_tampered_are_rejected(self):
        source, _ = self.bundle()
        cases = ({'omit': 'metrics.jsonl'}, {'extra': '../escape'},
                 {'extra': f'{source.name}/extra.txt'}, {'tamper': 'training_config.json'},
                 {'extra': f'{source.name}/manifest.json'})
        for index, case in enumerate(cases):
            target = self.root / f'unpacked-{index}'
            with self.subTest(case=case), warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    audit_download(self.zip(source, **case), source, target)
                self.assertFalse(target.exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_zip_crc_failure_cleans_extraction(self):
        source, _ = self.bundle()
        archive = self.zip(source)
        data = bytearray(archive.read_bytes())
        with zipfile.ZipFile(archive) as bundle:
            item = bundle.infolist()[0]
            offset = item.header_offset + 30 + len(item.filename.encode()) + len(item.extra)
        data[offset] ^= 1
        archive.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            audit_download(archive, source, self.root / 'crc-failed')
        self.assertFalse((self.root / 'crc-failed').exists())

    def test_existing_extraction_is_preserved(self):
        source, _ = self.bundle()
        target = self.root / 'existing'
        target.mkdir()
        (target / 'keep').write_text('keep')
        with self.assertRaises(FileExistsError):
            audit_download(self.zip(source), source, target)
        self.assertEqual((target / 'keep').read_text(), 'keep')

    def test_valid_cpu_fixture_cannot_be_accepted_as_gpu(self):
        source, manifest = self.bundle()
        task = {'id': source.name, 'status': 'COMPLETED'}
        with self.assertRaisesRegex(ValueError, 'GPU allocation'):
            audit_gpu_output(source, task, SimpleNamespace(), revision=manifest.model_revision,
                steps=2, commit=manifest.environment.code_commit)

    def test_gpu_requires_explicit_opt_in_and_clean_git(self):
        with self.assertRaises(SystemExit), patch('scripts.check_m4_acceptance.Acceptance') as runner:
            main([])
        runner.assert_not_called()
        with patch('scripts.check_m4_acceptance.code_baseline', return_value={'working_tree_dirty': True}), \
                patch('scripts.check_m4_acceptance.shutil.which', return_value='/fixture/bin'), \
                patch('scripts.check_m4_acceptance.WorkerInstanceLock') as lock:
            with self.assertRaisesRegex(ValueError, 'Commit reviewed'):
                main(['--gpu'])
        lock.assert_not_called()

    def test_preflight_does_not_create_services_or_import_training(self):
        with patch('scripts.check_m4_acceptance.subprocess.run') as node, \
                patch('scripts.check_m4_acceptance.shutil.which', return_value='/fixture/bin'), \
                patch('scripts.check_m4_acceptance.Acceptance') as runner:
            main(['--check'])
        self.assertIn('--check', node.call_args.args[0])
        runner.assert_not_called()
        result = subprocess.run([sys.executable, '-c',
            "import scripts.check_m4_acceptance, sys; "
            "assert not set(('torch','numpy','transformers','peft','trl','datasets','accelerate')) & sys.modules.keys()"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_isolated_paths_queue_and_step_limit_reach_worker_environment(self):
        runner = self.runner()
        runner.settings.redis_url = 'redis+socket:///tmp/private-m407.sock?virtual_host=0'
        env = runner.environment()
        self.assertEqual(env['TRAINING_MAX_STEPS'], '40')
        self.assertEqual(env['LOG_DIR'], str(self.root / 'shared-logs'))
        self.assertEqual(env['DATA_DIR'], str(runner.root / 'data'))
        self.assertIn(runner.root.name, env['TRAINING_QUEUE'])
        self.assertEqual(env['CELERY_BROKER_URL'], runner.settings.redis_url)
        self.assertEqual(runner.report['joint_human_acceptance'], 'pending')

    def test_cleanup_continues_after_api_failure_and_reaps_owned_processes(self):
        runner = self.runner()
        processes = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(2)]
        for process in processes:
            self.addCleanup(lambda p=process: p.kill() if p.poll() is None else None)
        runner.browser_process, runner.redis_process = processes
        runner.stop_worker = AsyncMock()
        runner.stop_api = AsyncMock(side_effect=asyncio.CancelledError('injected API cancellation'))
        asyncio.run(runner.cleanup())
        self.assertTrue(all(process.poll() is not None for process in processes))
        runner.stop_worker.assert_awaited_once()
        self.assertEqual(runner.report['cleanup_errors'], ['CancelledError'])

    @unittest.skipUnless(os.environ.get('LLMCLOUD_M4_TOOL_BROWSER_TEST') == '1',
                         'Opt-in real browser/API test with explicitly synthetic CPU execution')
    def test_browser_workflow_against_real_api_and_synthetic_cpu_inputs(self):
        """Exercise the new robot itself; do not call the GPU orchestrator or pass it."""
        from backend.app.core.task_contract import PublishOutcome
        from backend.app.main import create_app
        from trainer.artifacts import inventory
        from trainer.contracts import TrainingProgress, TrainingSnapshot, TrainingSummary

        class PublisherDouble:
            def publish(self, *_args):
                return PublishOutcome.ACCEPTED

        async def scenario():
            runner = self.runner()
            runner.settings.training_max_steps = 5
            process = None
            try:
                with patch('scripts.check_m3_acceptance.create_app',
                           side_effect=lambda settings: create_app(settings, task_publisher=PublisherDouble())):
                    await runner.start_api()
                await runner.start_frontend()
                browser_dir = runner.root / 'browser'
                process = subprocess.Popen(['node', 'scripts/check_m4_browser.mjs', '--url', runner.front_url,
                    '--output', str(browser_dir), '--timeout', '45'], cwd=ROOT,
                    stdout=runner.log('browser.log'), stderr=subprocess.STDOUT)
                runner.browser_process = process
                submitted = await runner.wait_file(browser_dir / 'submitted.json')
                await runner.wait_file(browser_dir / 'observing.json')
                repo = runner.app.state.task_repository

                def inputs(task_id):
                    # CPU fixture adaptation, only in tests. No GPU allocation or
                    # actual training claim; the production artifact audit still runs.
                    token = uuid4()
                    spec = repo.claim(task_id, token, 'explicit-cpu-browser-tool-test')
                    support = fixtures.TrainingArtifactTests()
                    support.parent = runner.settings.data_dir
                    with patch.object(fixtures, 'uuid4', return_value=spec.task_id):
                        source, manifest = support.bundle()
                    snapshot = TrainingSnapshot(**{field: getattr(spec, field)
                        for field in TrainingSnapshot.model_fields})
                    support.dump(source / 'training_config.json', snapshot.model_dump(mode='json'))
                    adapter = json.loads((source / 'adapter/adapter_config.json').read_text())
                    adapter.update(revision=spec.model_revision, r=spec.config.lora_r,
                        lora_alpha=spec.config.lora_alpha, lora_dropout=spec.config.lora_dropout,
                        target_modules=spec.config.target_modules)
                    support.dump(source / 'adapter/adapter_config.json', adapter)
                    rank = spec.config.lora_r
                    tensors = {f'base_model.model.model.layers.0.self_attn.{module}.lora_{side}.weight':
                        {'dtype': 'F32', 'shape': [rank, 2] if side == 'A' else [2, rank],
                         'data': b'\0' * (4 * 2 * rank)}
                        for module in spec.config.target_modules for side in ('A', 'B')}
                    (source / 'adapter/adapter_model.safetensors').write_bytes(fixtures.encode(tensors))
                    events = [TrainingProgress(step=step, total_steps=5, loss=1 / step,
                        learning_rate=0.0001, epoch=step / 5, recorded_at=datetime.now(timezone.utc))
                        for step in range(1, 6)]
                    (source / 'metrics.jsonl').write_text(''.join(event.model_dump_json() + '\n' for event in events))
                    log = runner.settings.log_dir / 'tasks' / f'{task_id}.log'
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text(json.dumps({'stage': 'saving', 'recorded_at': datetime.now(timezone.utc).isoformat()}) + '\n')
                    for event in events:
                        repo.record_progress(task_id, token, event)
                    raw = manifest.model_dump(mode='json')
                    raw.update(snapshot.model_dump(mode='json'), tokenizer_revision=spec.model_revision,
                        train_dataset={'sha256': spec.dataset_sha256, 'size_bytes': spec.dataset_size_bytes,
                                       'row_count': spec.dataset_row_count},
                        summary=TrainingSummary(completed_steps=5, total_steps=5, elapsed_seconds=3.0,
                            peak_memory_allocated_bytes=0,
                            trainable_parameters=4 * rank * len(spec.config.target_modules), total_parameters=1024,
                            final_loss=events[-1].loss).model_dump(mode='json'),
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        artifacts=[item.model_dump(mode='json') for item in inventory(source)])
                    support.dump(source / 'manifest.json', raw)
                    return token, source, log, raw['summary']

                def complete(task_id, data):
                    token, source, log, summary = data
                    log.write_text(json.dumps({'stage': 'training_and_save_finished', 'completed_steps': 5,
                        'recorded_at': datetime.now(timezone.utc).isoformat()}) + '\n')
                    self.assertTrue(repo.complete(task_id, token, f'outputs/{task_id}',
                        sha256(source / 'manifest.json'), TrainingSummary.model_validate(summary)))

                first, second = submitted['task_ids']
                complete(first, inputs(first))
                second_data = inputs(second)
                # This handshake only paces CPU substitutes in this test. The
                # production GPU worker never consumes or waits for this file.
                await runner.wait_file(browser_dir / 'downloaded-first.json')
                complete(second, second_data)
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=45)
                self.assertEqual(process.returncode, 0, (runner.root / 'browser.log').read_text())
                result = json.loads((browser_dir / 'result.json').read_text())
                self.assertEqual(result['status'], 'browser_checks_passed')
                self.assertEqual(result['joint_human_acceptance'], 'pending')
                for task_id in (first, second):
                    self.assertEqual(result['final'][task_id]['train_points'], 5)
                    audit_download(browser_dir / f'llmcloud-adapter-{task_id}.zip',
                        runner.settings.data_dir / 'outputs' / task_id, runner.root / 'extracted' / task_id)
                self.assertFalse(runner.report['gpu_execution_verified'])
            finally:
                await runner.cleanup()

        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
