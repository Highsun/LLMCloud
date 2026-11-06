"""M4-07 tool: CPU preflight, opt-in real GPU browser run, or a pending manual session.

No mock Publisher/Worker, injected training events, or product test routes.
Only the existing M3 service lifecycle helpers are reused; none of its cases run.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import redis  # noqa: E402
import httpx  # noqa: E402
from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION  # noqa: E402
from backend.app.core.worker_lock import WorkerInstanceLock  # noqa: E402
from scripts.check_m3_acceptance import Acceptance as ServiceLifecycle, port, stop, write  # noqa: E402
from scripts.m4_acceptance_support import (  # noqa: E402
    audit_download, audit_gpu_output, check_serial, new_run_directory, require,
)
from trainer.artifacts import sha256  # noqa: E402
from trainer.model_cache import resolve_model_paths, verify_model_cache  # noqa: E402


def code_baseline():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return {'commit': git('rev-parse', 'HEAD'), 'working_tree_dirty': bool(git('status', '--porcelain')),
            'uv_lock_sha256': sha256(ROOT / 'uv.lock')}


class Acceptance(ServiceLifecycle):
    def __init__(self, root, shared, paths, *, steps, timeout, baseline):
        super().__init__(root, shared, paths)
        self.settings.training_max_steps = steps
        self.settings.training_queue = 'm407-' + root.name
        self.settings.default_model_revision = DEFAULT_MODEL_REVISION
        self.timeout, self.browser_process = timeout, None
        self.report = {'version': '1.0.0', 'scope': 'M4-07', 'status': 'preparing',
            'run_id': root.name, 'started_at': datetime.now(timezone.utc).isoformat(),
            'baseline': baseline, 'model_revision': DEFAULT_MODEL_REVISION,
            'max_steps': steps, 'engineering_draft_unreviewed': True,
            'gpu_execution_verified': False, 'joint_human_acceptance': 'pending',
            'm3_joint_human_acceptance': 'pending', 'artifacts': {}}

    def save(self):
        write(self.root / 'report.json', self.report)

    def environment(self, **kwargs):
        # The API freezes this limit into TaskExecutionSpec; set the worker env too.
        return {**super().environment(**kwargs), 'TRAINING_MAX_STEPS': str(self.settings.training_max_steps),
                'DEFAULT_MODEL_REVISION': DEFAULT_MODEL_REVISION, 'TRAINING_PRECISION': 'bf16'}

    async def start_frontend(self):
        vite_port = port()
        self.front_url = f'http://127.0.0.1:{vite_port}'
        self.vite = subprocess.Popen(['npm', 'run', 'dev', '--', '--port', str(vite_port), '--strictPort'],
            cwd=ROOT / 'frontend', env={**os.environ, 'VITE_BACKEND_URL': self.api_url,
                'VITE_API_BASE_URL': '/api/v1', 'VITE_OPENAPI_URL': '/openapi.json'},
            stdout=self.log('vite.log'), stderr=subprocess.STDOUT, start_new_session=True)
        async with httpx.AsyncClient(trust_env=False, timeout=1) as probe:
            for _ in range(200):
                require(self.vite.poll() is None, 'Owned Vite exited; inspect vite.log')
                try:
                    if (await probe.get(self.front_url)).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
        raise RuntimeError('Owned Vite readiness failed')

    async def cleanup(self):
        # Keep trying all owned-resource cleanup even if a previous close failed.
        errors = []
        if self.browser_process is not None:
            try:
                os.killpg(self.browser_process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for operation in (lambda: asyncio.to_thread(stop, self.browser_process), self.stop_worker,
                          self.stop_api):
            try:
                await operation()
            except (Exception, asyncio.CancelledError) as error:
                errors.append(type(error).__name__)
        listener = getattr(self, 'listener', None)
        if listener is not None:
            listener.close()
        if self.vite is not None:
            try:
                os.killpg(self.vite.pid, signal.SIGTERM)
                await asyncio.to_thread(stop, self.vite)
            except ProcessLookupError:
                pass
            except Exception as error:
                errors.append(type(error).__name__)
        try:
            if hasattr(self, 'broker'):
                self.broker.close()
        finally:
            await asyncio.to_thread(stop, self.redis_process)
            for stream in self.open_files:
                stream.close()
        self.report['cleanup_errors'] = errors

    async def wait_file(self, path):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text())
            require(self.browser_process.poll() is None, 'Browser exited; inspect browser.log and trace')
            await asyncio.sleep(0.1)
        raise TimeoutError(f'Browser handshake timed out: {path.name}')

    async def capture(self, ids):
        tasks = [await self.detail(task_id) for task_id in ids]
        self.report['tasks'] = tasks
        for task in tasks:
            if task['status'] != 'COMPLETED':
                continue
            task_id = task['id']
            output = self.settings.data_dir / 'outputs' / task_id
            completed = self.app.state.task_repository.get_completed_artifact(task_id)
            self.report['artifacts'][task_id] = audit_gpu_output(output, task, completed,
                revision=DEFAULT_MODEL_REVISION, steps=self.settings.training_max_steps,
                commit=self.report['baseline']['commit'])
            dataset = self.settings.data_dir / 'datasets' / task['dataset_id'] / 'train.jsonl'
            require(sha256(dataset) == completed.spec.dataset_sha256, 'Uploaded dataset bytes differ from frozen SQL')
            self.report.setdefault('dataset_sha256', {})[task['dataset_id']] = sha256(dataset)
            log = self.shared.log_dir / 'tasks' / f'{task_id}.log'
            shutil.copyfile(log, self.root / f'{task_id}.log')
            # Retain the HTTP final view independently of the browser's cursor reads.
            for endpoint in ('metrics?limit=200', 'logs?tail=500'):
                response = await self.client.get(f'/api/v1/tasks/{task_id}/{endpoint}')
                require(response.status_code == 200, f'Final {endpoint} HTTP read failed')
                write(self.root / f"{task_id}-{endpoint.split('?')[0]}.json", response.json())
        self.save()
        return tasks

    async def automate(self):
        browser_dir = self.root / 'browser'
        self.browser_process = subprocess.Popen(['node', 'scripts/check_m4_browser.mjs',
            '--url', self.front_url, '--output', str(browser_dir), '--timeout', str(self.timeout)],
            cwd=ROOT, env=os.environ.copy(), stdout=self.log('browser.log'), stderr=subprocess.STDOUT,
            start_new_session=True)
        submitted = await self.wait_file(browser_dir / 'submitted.json')
        self.report['submissions'] = submitted
        self.save()
        # Both real messages are queued before the production worker starts. No
        # training sleeps or artificial metric pacing are introduced.
        await self.wait_file(browser_dir / 'observing.json')
        await self.start_worker()
        self.report['worker_pid'] = self.worker.pid
        try:
            await asyncio.wait_for(asyncio.to_thread(self.browser_process.wait), timeout=self.timeout + 90)
        except TimeoutError:
            raise TimeoutError('Browser/GPU acceptance exceeded its time budget') from None
        require(self.browser_process.returncode == 0, 'Browser failed; inspect browser/result.json and trace.zip')
        result = json.loads((browser_dir / 'result.json').read_text())
        tasks = await self.capture(submitted['task_ids'])
        self.report['serial_execution'] = check_serial(tasks)
        for task in tasks:
            task_id = task['id']
            output = self.settings.data_dir / 'outputs' / task_id
            audit = self.report['artifacts'][task_id]
            require(result['final'][task_id]['train_points'] == audit['train_points'], 'UI omitted train points')
            require(result['final'][task_id]['last_loss'] == audit['last_train']['loss'], 'UI final Loss differs')
            self.report.setdefault('downloads', {})[task_id] = audit_download(
                browser_dir / f'llmcloud-adapter-{task_id}.zip', output, self.root / 'extracted' / task_id)
        first = submitted['task_ids'][0]
        polls = [item for item in result['responses'] if item.get('task_id') == first
                 and item.get('endpoint') == 'metrics' and item.get('task_status') == 'RUNNING'
                 and item.get('count', 0) > 0]
        polls.sort(key=lambda item: item['at_ms'])
        require(len(polls) >= 2 and polls[-1]['at_ms'] - polls[0]['at_ms'] >= 1500,
                'Need two distinct live polling rounds; increase --max-steps instead of faking points')
        require(any(item['visible_train_points'] >= 5 for item in result['live_ui']),
                'Five real train points must be visible before completion; increase real max_steps')
        concurrent = result['download_during_training']
        second = tasks[1]
        training_start = datetime.fromisoformat(second['started_at'].replace('Z', '+00:00'))
        training_end = datetime.fromisoformat(second['finished_at'].replace('Z', '+00:00'))
        # Require a real optimizer event before and after the download, not merely
        # RUNNING while the model loads or saves.
        events = [json.loads(line) for line in (self.settings.data_dir / 'outputs' / second['id'] /
                  'metrics.jsonl').read_text().splitlines()]
        train_times = [datetime.fromisoformat(event['recorded_at'].replace('Z', '+00:00'))
                       for event in events if event['kind'] == 'train']
        download_start = datetime.fromisoformat(concurrent['started_at'].replace('Z', '+00:00'))
        download_end = datetime.fromisoformat(concurrent['finished_at'].replace('Z', '+00:00'))
        require(training_start <= download_start <= download_end <= training_end and
                min(train_times) <= download_start and max(train_times) >= download_end,
                'Download did not overlap actual optimizer activity; rerun with more real steps')
        deadline = time.monotonic() + 10
        downloads = self.settings.data_dir / 'downloads'
        while downloads.exists() and any(downloads.iterdir()) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        require(not downloads.exists() or not any(downloads.iterdir()), 'Download workspace leaked')
        self.report.update(status='automated_passed', gpu_execution_verified=True,
            browser_result='browser/result.json', download_workspace_clean=True,
            download_during_training=concurrent)

    async def manual(self, seconds):
        await self.start_worker()
        self.report.update(status='manual_session_open', worker_pid=self.worker.pid)
        self.save()
        print(json.dumps({'manual_browser_url': self.front_url, 'seconds': seconds,
            'instruction': 'B must freshly upload and submit two tasks; record actual human actions separately.'}), flush=True)
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                require(self.worker.poll() is None, 'Production Worker exited; inspect worker log')
                await asyncio.sleep(1)
        finally:
            # Do not call an unfinished human session passed; preserve real state.
            ids, page = [], 1
            while True:
                response = await self.client.get(f'/api/v1/tasks?page={page}&page_size=100')
                require(response.status_code == 200, 'Manual task listing failed')
                body = response.json()
                ids.extend(item['id'] for item in body['items'])
                if page >= body['total_pages']:
                    break
                page += 1
            await self.capture(ids)
            self.report['unfinished_tasks_at_close'] = [task['id'] for task in self.report['tasks']
                if task['status'] in ('PENDING', 'QUEUED', 'RUNNING')]
            self.report['status'] = 'manual_session_closed_pending_review'

    async def run(self, socket_dir, *, manual_seconds=None):
        socket_path = socket_dir / 'redis.sock'
        self.settings.redis_url = f'redis+socket://{socket_path}?virtual_host=0'
        self.settings.celery_result_backend = f'redis+socket://{socket_path}?virtual_host=1'
        try:
            self.redis_process = subprocess.Popen(['redis-server', '--port', '0', '--unixsocket', str(socket_path),
                '--unixsocketperm', '700', '--save', '', '--appendonly', 'no'],
                stdout=self.log('redis.log'), stderr=subprocess.STDOUT)
            self.broker = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=1)
            for _ in range(200):
                try:
                    if self.broker.ping():
                        break
                except redis.RedisError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError('Private Redis did not become ready')
            await self.start_api()
            await self.start_frontend()
            self.report.update(status='services_ready', api_url=self.api_url, browser_url=self.front_url,
                redis_pid=self.redis_process.pid, api_pid=os.getpid(), vite_pid=self.vite.pid,
                queue=self.settings.training_queue, shared_lock=str(self.shared.log_dir / 'worker.lock'))
            self.save()
            if manual_seconds is None:
                await self.automate()
            else:
                await self.manual(manual_seconds)
        finally:
            await self.cleanup()
            require(not self.report.get('cleanup_errors'), 'Owned service cleanup was incomplete')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='CPU dependency/browser launch check; no services or GPU')
    mode.add_argument('--gpu', action='store_true', help='Explicit real-GPU opt-in; coordinate exclusive use first')
    parser.add_argument('--manual', action='store_true', help='Leave real services for B; never asserts human success')
    parser.add_argument('--hold-seconds', type=int, default=1800)
    parser.add_argument('--max-steps', type=int, default=40)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args(argv)
    if not 5 <= args.max_steps <= 200 or not 30 <= args.timeout <= 3600 or not 30 <= args.hold_seconds <= 7200:
        parser.error('steps: 5..200; timeout: 30..3600 seconds; hold: 30..7200 seconds')
    if args.check and (args.manual or args.run_dir):
        parser.error('--manual/--run-dir require --gpu')
    for executable in ('node', 'npm', 'redis-server'):
        require(shutil.which(executable), f'{executable} is required')
    if args.check:
        subprocess.run(['node', 'scripts/check_m4_browser.mjs', '--check'], cwd=ROOT, check=True)
        print(json.dumps({'status': 'preflight_passed', 'gpu_started': False, 'services_started': False,
            'training_packages_available': all(importlib.util.find_spec(name) is not None for name in
                ('torch', 'transformers', 'peft', 'trl', 'datasets', 'accelerate')),
            'note': 'Does not check the model cache/GPU or assert M4-07 success'}))
        return
    baseline = code_baseline()
    require(not baseline['working_tree_dirty'], 'Commit reviewed tooling before the actual GPU run')
    require(all(importlib.util.find_spec(name) is not None for name in
                ('torch', 'transformers', 'peft', 'trl', 'datasets', 'accelerate')),
            'Use uv run --locked --extra training for a real GPU run')
    shared, paths = Settings(), resolve_model_paths()
    with WorkerInstanceLock(shared.log_dir):
        verify_model_cache(paths.cache_dir, DEFAULT_MODEL_REVISION)
    root = new_run_directory(ROOT / 'data/acceptance/m4-07', args.run_dir)
    runner = Acceptance(root, shared, paths, steps=args.max_steps, timeout=args.timeout, baseline=baseline)
    runner.save()
    print(json.dumps({'run_dir': str(root), 'status': 'starting'}), flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='m407-') as directory:
            asyncio.run(runner.run(Path(directory), manual_seconds=args.hold_seconds if args.manual else None))
    except BaseException as error:
        runner.report.update(status='interrupted_pending_review' if isinstance(error, KeyboardInterrupt)
                             else 'failed', error_type=type(error).__name__)
        raise
    finally:
        runner.report['finished_at'] = datetime.now(timezone.utc).isoformat()
        runner.save()
    print(json.dumps({'status': runner.report['status'], 'run_dir': str(root),
                      'joint_human_acceptance': 'pending'}), flush=True)


if __name__ == '__main__':
    main()
