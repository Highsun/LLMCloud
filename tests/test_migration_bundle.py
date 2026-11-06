"""Small CPU-only backup/restore boundary tests; no services, model or GPU."""

import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.migration_bundle import build, checksum_files, digest, restore, verify


class MigrationBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for folder in ('data/models/hub/blobs', 'data/models/hub/snapshot', 'logs', 'frontend'):
            (self.root / folder).mkdir(parents=True)
        (self.root / 'data/models/hub/blobs/model').write_bytes(b'CPU fixture, not model weights')
        (self.root / 'data/models/hub/snapshot/model').symlink_to('../blobs/model')
        (self.root / '.env').write_text('DATA_DIR=data\n')
        (self.root / 'logs/task.log').write_text('historical CPU fixture\n')
        (self.root / 'logs/worker.lock').touch()
        self.connection = sqlite3.connect(self.root / 'data/llmcloud.db')
        self.addCleanup(self.connection.close)
        self.connection.execute('pragma journal_mode=WAL')
        self.connection.execute('create table datasets (id integer)')
        self.connection.execute('insert into datasets values (1)')
        self.connection.commit()
        self.home = patch('scripts.migration_bundle.Path.home', return_value=self.root / 'empty-home')
        self.home.start()
        self.addCleanup(self.home.stop)
        self.git = patch('scripts.migration_bundle.subprocess.check_output', return_value='b' * 40)
        self.git.start()
        self.addCleanup(self.git.stop)
        self.output = self.root / 'data/migration/test-run'

    def create(self):
        return build(self.output, root=self.root, services_stopped=True)

    def test_snapshot_includes_wal_rows_and_preserves_relative_cache_links(self):
        manifest = self.create()
        self.assertEqual(verify(self.output)['databases'], 1)
        self.assertEqual(manifest['databases']['data/llmcloud.db']['tables']['datasets'], 1)
        target = self.root / 'restored'
        restore(self.output, target)
        with sqlite3.connect(target / 'data/llmcloud.db') as database:
            self.assertEqual(database.execute('select count(*) from datasets').fetchone()[0], 1)
        self.assertTrue((target / 'data/models/hub/snapshot/model').is_symlink())
        self.assertEqual((target / 'data/models/hub/snapshot/model').read_bytes(), b'CPU fixture, not model weights')
        self.assertFalse((target / 'logs/worker.lock').exists())
        self.assertFalse((target / '.env').exists())
        self.assertTrue((target / 'private-config/backend.env').exists())
        self.assertFalse(any('/migration/' in item['path'] for item in manifest['files']))

    def test_requires_stopped_services_new_output_and_new_restore_target(self):
        with self.assertRaises(ValueError):
            build(self.output, root=self.root)
        with self.assertRaises(ValueError):
            build(self.root / 'outside', root=self.root, services_stopped=True)
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        (self.root / 'keep').mkdir()
        with self.assertRaises(FileExistsError):
            restore(self.output, self.root / 'keep')

    def test_tampered_archive_rejected_before_restore_creates_target(self):
        self.create()
        with (self.output / 'runtime.tar.gz').open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'Checksum differs'):
            restore(self.output, self.root / 'not-created')
        self.assertFalse((self.root / 'not-created').exists())

    def test_manifest_hash_mismatch_is_detected_even_with_new_outer_checksums(self):
        self.create()
        manifest = json.loads((self.output / 'manifest.json').read_text())
        next(item for item in manifest['files'] if item['kind'] == 'file')['sha256'] = 'a' * 64
        (self.output / 'manifest.json').write_text(json.dumps(manifest))
        checksum_files(self.output)
        with self.assertRaisesRegex(ValueError, 'member hash'):
            verify(self.output)

    def test_traversal_members_and_external_source_links_rejected(self):
        self.create()
        with tarfile.open(self.output / 'runtime.tar.gz', 'w:gz') as bundle:
            bundle.addfile(tarfile.TarInfo('../escape'))
        checksum_files(self.output)
        with self.assertRaises(ValueError):
            verify(self.output)
        (self.root / 'data/models/external').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            build(self.root / 'data/migration/second', root=self.root, services_stopped=True)

    def test_private_home_credentials_never_enter_inventory(self):
        (self.root / 'data/models/token').write_text('synthetic secret')
        manifest = self.create()
        self.assertNotIn('data/models/token', {item['path'] for item in manifest['files']})
        self.assertIn('data/models/token', {item['path'] for item in manifest['excluded']})
        self.assertEqual(len(digest(self.output / 'manifest.json')), 64)


if __name__ == '__main__':
    unittest.main()
