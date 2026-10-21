import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.core.database import Base
from backend.app.models.dataset_schemas import DatasetListQuery
from backend.app.models.entities import Dataset
from backend.app.services.datasets import DatasetService
from backend.app.services.errors import DatasetServiceError
from trainer.dataset import DatasetScanner, DatasetValidationError, iter_records

RAW = '{"instruction":"解释云计算。","output":"按需提供资源。"}'.encode()


class ScannerTests(unittest.TestCase):
    def scan(self, raw, **kwargs):
        scanner = DatasetScanner(**kwargs)
        records = []
        for index in range(0, len(raw), 3):
            records.extend(scanner.feed(raw[index:index + 3]))
        records.extend(scanner.finish())
        return scanner.stats, records

    def test_bom_crlf_multibyte_chunks_blank_lines_and_eof(self):
        raw = b'\xef\xbb\xbf\r\n' + RAW + b'\r\n\n' + RAW
        stats, records = self.scan(raw)
        self.assertEqual(stats.row_count, 2)
        self.assertEqual(stats.size_bytes, len(raw))
        self.assertEqual(stats.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(records[0]['input'], '')

    def test_content_failures_with_safe_diagnostics(self):
        cases = [
            (b'', 'empty'), (b'\xef\xbb\xbf \r\n', 'empty'),
            (b'[]', 'invalid_type'), (b'\xff', 'invalid_encoding'),
            (b'{bad}', 'invalid_json'),
            (b'{"instruction":"x","output":"x","output":"y"}', 'duplicate_key'),
            (b'{"instruction":NaN,"output":"x"}', 'invalid_json'),
            (b'{"instruction":Infinity,"output":"x"}', 'invalid_json'),
            (b'{"instruction":"x"}', 'missing'),
            (b'{"instruction":"x","output":"x","input":null}', 'invalid_type'),
            (b'{"instruction":"x","output":"x","messages":[]}', 'extra_field'),
            (b'{"instruction":" ","output":"x"}', 'blank'),
            (b'[' * 2000 + b']' * 2000, 'invalid_json'),
        ]
        for raw, code in cases:
            with self.subTest(code=code, raw=raw[:40]), self.assertRaises(DatasetValidationError) as caught:
                self.scan(raw)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('messages', str(caught.exception))

    def test_physical_line_number_and_json_column(self):
        with self.assertRaises(DatasetValidationError) as caught:
            self.scan(RAW + b'\n\n{bad}')
        self.assertEqual(caught.exception.line, 3)
        self.assertEqual(caught.exception.column, 2)
        with self.assertRaises(DatasetValidationError) as caught:
            self.scan(RAW + b'\n\xef\xbb\xbf' + RAW)
        self.assertEqual(caught.exception.line, 2)

    def test_exact_and_exceeded_limits(self):
        self.scan(RAW, max_bytes=len(RAW), max_line_bytes=len(RAW))
        for limits, code in (({'max_bytes': len(RAW) - 1}, 'file_too_large'), ({'max_line_bytes': len(RAW) - 1}, 'line_too_large')):
            with self.subTest(code=code), self.assertRaises(DatasetValidationError) as caught:
                self.scan(RAW, **limits)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(DatasetValidationError):
            self.scan(RAW + b'\n', max_line_bytes=len(RAW))

    def test_trainer_reader_uses_the_same_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'train.jsonl'
            path.write_bytes(b'\xef\xbb\xbf' + RAW + b'\r\n')
            self.assertEqual(len(list(iter_records(path))), 1)
            path.write_bytes(b'{"instruction":"x","output":"x","output":"y"}')
            with self.assertRaises(DatasetValidationError):
                list(iter_records(path))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.settings = Settings(_env_file=None, data_dir=self.root / 'data', log_dir=self.root / 'logs')
        self.settings.ensure_directories()
        self.engine = create_engine(f'sqlite:///{self.root / "metadata.db"}', connect_args={'check_same_thread': False})
        event.listen(self.engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=False)
        self.service = DatasetService(self.settings, self.factory)

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def assert_empty(self):
        self.assertEqual(self.service.list().total, 0)
        self.assertEqual(list((self.settings.data_dir / 'datasets').rglob('*.part')), [])
        self.assertEqual(list((self.settings.data_dir / 'datasets').rglob('train.jsonl')), [])

    def test_create_preserves_raw_bytes_and_metadata(self):
        raw = b'\xef\xbb\xbf\n' + RAW + b'\r\n'
        source = io.BytesIO(raw)
        value = self.service.create(source, filename=r'C:\fakepath\sample.JSONL', name='  课程训练  ')
        self.assertFalse(source.closed)
        self.assertEqual(value.name, '课程训练')
        self.assertEqual(value.original_filename, 'sample.JSONL')
        self.assertEqual(value.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(value.row_count, 1)
        self.assertEqual(value.size_bytes, len(raw))
        with self.factory() as session:
            row = session.get(Dataset, str(value.id))
            self.assertEqual(row.storage_path, f'datasets/{value.id}/train.jsonl')
            self.assertIsNone(row.user_id)
            self.assertEqual((self.settings.data_dir / row.storage_path).read_bytes(), raw)
        self.assertTrue(self.service.get(value.id).model_dump(mode='json')['created_at'].endswith('Z'))
        self.assertFalse(any(self.service.audit_storage(verify_hash=True).values()))

    def test_duplicate_uploads_are_separate_resources(self):
        one = self.service.create(io.BytesIO(RAW), filename='../../sample.jsonl')
        two = self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertNotEqual(one.id, two.id)
        self.assertEqual(one.sha256, two.sha256)
        self.assertEqual(one.name, 'sample.jsonl')

    def test_parallel_uploads(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: self.service.create(io.BytesIO(RAW), filename='same.jsonl'), range(2)))
        self.assertNotEqual(values[0].id, values[1].id)
        self.assertEqual(self.service.list().total, 2)

    def test_validation_fails_without_leaving_files(self):
        cases = [(b'', 'sample.jsonl', None, 422), (b'{bad}', 'sample.jsonl', None, 422),
                 (RAW, 'bad.csv', None, 422), (RAW, '.jsonl', None, 422),
                 (RAW, 'sample.jsonl', ' ', 422), (RAW, 'sample.jsonl', '\nname', 422),
                 (RAW, 'sample.jsonl', 'x' * 2000, 422)]
        for raw, filename, name, status in cases:
            with self.subTest(filename=filename), self.assertRaises(DatasetServiceError) as caught:
                self.service.create(io.BytesIO(raw), filename=filename, name=name)
            self.assertEqual(caught.exception.status_code, status)
            self.assert_empty()

    def test_size_failures_map_to_413(self):
        real_scanner = DatasetScanner
        for limits in ({'max_bytes': len(RAW) - 1}, {'max_line_bytes': len(RAW) - 1}):
            with patch('backend.app.services.datasets.DatasetScanner', side_effect=lambda: real_scanner(**limits)):
                with self.assertRaises(DatasetServiceError) as caught:
                    self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
            self.assertEqual(caught.exception.status_code, 413)
            self.assert_empty()

    def test_source_interrupt_and_disk_failure_cleanup(self):
        class BrokenSource:
            def read(self, _size):
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.service.create(BrokenSource(), filename='sample.jsonl')
        self.assert_empty()
        for target in ('os.fsync', 'pathlib.Path.rename'):
            with patch(target, side_effect=OSError('private disk detail')):
                with self.assertRaises(DatasetServiceError) as caught:
                    self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
            self.assertEqual(caught.exception.code, 'STORAGE_UNAVAILABLE')
            self.assertNotIn('private', str(caught.exception))
            self.assert_empty()

    def test_symlink_storage_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.settings.data_dir / 'datasets').rmdir()
        (self.settings.data_dir / 'datasets').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(DatasetServiceError):
            self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertEqual(list(outside.iterdir()), [])

    def test_flush_failure_rolls_back_and_cleans_final_file(self):
        class FailingSession(Session):
            def flush(self, objects=None):
                raise OperationalError('INSERT', {}, Exception('private database detail'))
        factory = sessionmaker(bind=self.engine, class_=FailingSession)
        with self.assertRaises(DatasetServiceError) as caught:
            DatasetService(self.settings, factory).create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertEqual(caught.exception.code, 'DATABASE_UNAVAILABLE')
        self.assertNotIn('private', str(caught.exception))
        self.assert_empty()

    def test_commit_failure_before_commit_cleans_files(self):
        class FailingSession(Session):
            def commit(self):
                raise OperationalError('COMMIT', {}, Exception())
        factory = sessionmaker(bind=self.engine, class_=FailingSession)
        with self.assertRaises(DatasetServiceError):
            DatasetService(self.settings, factory).create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assert_empty()

    def test_commit_success_followed_by_exception_preserves_resource(self):
        class AmbiguousSession(Session):
            def commit(self):
                super().commit()
                raise RuntimeError('connection disappeared after commit')
        factory = sessionmaker(bind=self.engine, class_=AmbiguousSession)
        value = DatasetService(self.settings, factory).create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertEqual(self.service.get(value.id).sha256, value.sha256)
        self.assertFalse(any(self.service.audit_storage(verify_hash=True).values()))

    def test_unknown_commit_outcome_preserves_file_for_audit(self):
        class FailingSession(Session):
            def commit(self):
                raise OperationalError('COMMIT', {}, Exception())
        calls = 0
        def factory():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OperationalError('SELECT', {}, Exception())
            return FailingSession(bind=self.engine)
        with self.assertRaises(DatasetServiceError) as caught:
            DatasetService(self.settings, factory).create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(len(self.service.audit_storage()['orphan_candidates']), 1)
        self.assertEqual(self.service.list().total, 0)

    def test_unknown_outcome_after_real_commit_never_deletes_live_file(self):
        class AmbiguousSession(Session):
            def commit(self):
                super().commit()
                raise RuntimeError('acknowledgment lost')
        calls = 0
        def factory():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OperationalError('SELECT', {}, Exception())
            return AmbiguousSession(bind=self.engine)
        with self.assertRaises(DatasetServiceError):
            DatasetService(self.settings, factory).create(io.BytesIO(RAW), filename='sample.jsonl')
        self.assertEqual(self.service.list().total, 1)
        self.assertFalse(any(self.service.audit_storage(verify_hash=True).values()))

    def test_collision_never_removes_a_preexisting_dataset(self):
        value = self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
        with patch('backend.app.services.datasets.uuid4', return_value=value.id):
            with self.assertRaises(DatasetServiceError):
                self.service.create(io.BytesIO(RAW), filename='other.jsonl')
        self.assertEqual(self.service.list().total, 1)
        self.assertFalse(any(self.service.audit_storage(verify_hash=True).values()))

    def test_cleanup_failure_preserves_original_error_and_reports_candidate(self):
        with patch('pathlib.Path.unlink', side_effect=PermissionError('cannot clean up')):
            with self.assertRaises(DatasetServiceError) as caught:
                self.service.create(io.BytesIO(b'{bad}'), filename='sample.jsonl')
        self.assertEqual(caught.exception.code, 'INVALID_DATASET')
        report = self.service.audit_storage()
        self.assertEqual(len(report['temporary_candidates']), 1)
        self.assertEqual(self.service.list().total, 0)

    def test_paging_ties_huge_page_and_metadata_only_detail(self):
        values = [self.service.create(io.BytesIO(RAW), filename='sample.jsonl') for _ in range(3)]
        with self.factory() as session:
            session.execute(update(Dataset).values(created_at=datetime(2026, 10, 21, tzinfo=timezone.utc)))
            session.commit()
        page = self.service.list(DatasetListQuery(page=1, page_size=2))
        expected = sorted((str(value.id) for value in values), reverse=True)
        self.assertEqual([str(value.id) for value in page.items], expected[:2])
        self.assertEqual(page.total_pages, 2)
        self.assertEqual(self.service.list(DatasetListQuery(page=10 ** 100)).items, [])
        value = values[0]
        (self.settings.data_dir / f'datasets/{value.id}/train.jsonl').unlink()
        self.assertEqual(self.service.get(value.id).id, value.id)
        self.assertIn(str(value.id), self.service.audit_storage()['missing_files'])

    def test_missing_invalid_ids_and_audit_never_deletes(self):
        for value, expected in (('bad', 422), (str(uuid4()), 404)):
            with self.assertRaises(DatasetServiceError) as caught:
                self.service.get(value)
            self.assertEqual(caught.exception.status_code, expected)
        value = self.service.create(io.BytesIO(RAW), filename='sample.jsonl')
        path = self.settings.data_dir / f'datasets/{value.id}/train.jsonl'
        path.write_bytes(RAW + b'\n')
        part = self.settings.data_dir / 'datasets/.tmp/stale.part'
        part.write_bytes(b'unfinished')
        report = self.service.audit_storage(verify_hash=True)
        self.assertIn(str(value.id), report['checksum_mismatches'])
        self.assertTrue(report['temporary_candidates'])
        self.assertTrue(part.exists())
        self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
