import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, inspect

from backend.app.core.dataset_migration import (
    DatasetSchemaMigrationRequired, migrate_datasets, require_dataset_schema, _replace_table,
)

RAW = b'{"instruction":"x","output":"y"}\n'
LEGACY_DDL = '''
CREATE TABLE users (id VARCHAR(36) NOT NULL PRIMARY KEY);
CREATE TABLE datasets (
 id VARCHAR(36) NOT NULL PRIMARY KEY,
 user_id VARCHAR(36),
 name VARCHAR(255) NOT NULL,
 storage_path TEXT NOT NULL,
 size_bytes INTEGER NOT NULL,
 row_count INTEGER NOT NULL,
 created_at DATETIME NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE training_tasks (id TEXT PRIMARY KEY, dataset_id VARCHAR(36) REFERENCES datasets(id), status TEXT);
CREATE INDEX dataset_name_index ON datasets(name);
'''


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.db = self.root / 'metadata.db'
        self.engine = create_engine(f'sqlite:///{self.db}')
        with sqlite3.connect(self.db) as connection:
            connection.executescript(LEGACY_DDL)

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def add_dataset(self, *, absolute_path=False):
        identifier, user_id, task_id = (str(uuid4()) for _ in range(3))
        key = f'datasets/{identifier}/train.jsonl'
        path = self.data / key
        path.parent.mkdir(parents=True)
        path.write_bytes(RAW)
        with sqlite3.connect(self.db) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('INSERT INTO users VALUES (?)', (user_id,))
            connection.execute('INSERT INTO datasets VALUES (?,?,?,?,?,?,?)',
                               (identifier, user_id, 'custom display name', str(path) if absolute_path else key, len(RAW), 1, '2026-10-21 08:00:00.000000'))
            connection.execute('INSERT INTO training_tasks VALUES (?,?,?)', (task_id, identifier, 'COMPLETED'))
        return identifier, user_id, task_id, path

    def test_empty_upgrade_check_backup_and_idempotence(self):
        self.assertEqual(migrate_datasets(self.engine, self.data).state, 'ready')
        self.assertFalse((self.data / 'backups').exists())
        with self.assertRaises(DatasetSchemaMigrationRequired):
            require_dataset_schema(self.engine)
        result = migrate_datasets(self.engine, self.data, apply=True)
        self.assertEqual(result.state, 'applied')
        self.assertTrue(Path(result.backup_path).is_file())
        self.assertEqual(migrate_datasets(self.engine, self.data, apply=True).state, 'current')
        require_dataset_schema(self.engine)
        columns = {c['name']: c for c in inspect(self.engine).get_columns('datasets')}
        self.assertFalse(columns['original_filename']['nullable'])
        self.assertFalse(columns['sha256']['nullable'])
        with sqlite3.connect(result.backup_path) as backup:
            self.assertNotIn('sha256', [row[1] for row in backup.execute('PRAGMA table_info(datasets)')])

    def test_existing_rows_require_trusted_filename_and_preserve_references(self):
        identifier, user_id, task_id, path = self.add_dataset(absolute_path=True)
        blocked = migrate_datasets(self.engine, self.data, apply=True)
        self.assertEqual(blocked.state, 'blocked')
        self.assertEqual(blocked.issues[0]['code'], 'original_filename_required')
        self.assertFalse((self.data / 'backups').exists())
        result = migrate_datasets(self.engine, self.data, apply=True, filenames={identifier: 'original.jsonl'})
        self.assertEqual(result.state, 'applied')
        self.assertEqual(path.read_bytes(), RAW)
        self.assertEqual(migrate_datasets(self.engine, self.data).rows, 1)
        with sqlite3.connect(self.db) as connection:
            row = connection.execute('SELECT id,user_id,name,storage_path,sha256,original_filename,created_at FROM datasets').fetchone()
            self.assertEqual(row, (identifier, user_id, 'custom display name', f'datasets/{identifier}/train.jsonl', hashlib.sha256(RAW).hexdigest(), 'original.jsonl', '2026-10-21 08:00:00.000000'))
            self.assertEqual(connection.execute('SELECT * FROM training_tasks').fetchone(), (task_id, identifier, 'COMPLETED'))
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertTrue(connection.execute("SELECT 1 FROM sqlite_master WHERE name='dataset_name_index'").fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE datasets SET sha256=NULL')

    def test_invalid_or_missing_sources_block_without_changes(self):
        identifier, _, _, path = self.add_dataset()
        for contents, expected in ((b'{bad}', 'invalid_json'), (None, 'source_file_unavailable')):
            if contents is None:
                path.unlink()
            else:
                path.write_bytes(contents)
            result = migrate_datasets(self.engine, self.data, apply=True, filenames={identifier: 'original.jsonl'})
            self.assertEqual(result.state, 'blocked')
            self.assertEqual(result.issues[0]['code'], expected)
            self.assertNotIn('sha256', [c['name'] for c in inspect(self.engine).get_columns('datasets')])

    def test_invalid_mapping_path_and_statistics_do_not_get_guessed(self):
        identifier, _, _, _ = self.add_dataset()
        result = migrate_datasets(self.engine, self.data, filenames={str(uuid4()): 'x.jsonl'})
        self.assertIn('unknown_filename_mapping', [issue['code'] for issue in result.issues])
        with sqlite3.connect(self.db) as connection:
            connection.execute('UPDATE datasets SET size_bytes=1')
        result = migrate_datasets(self.engine, self.data, filenames={identifier: 'source.jsonl'})
        self.assertEqual(result.issues[0]['code'], 'legacy_statistics_mismatch')
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE datasets SET storage_path='../outside'")
        result = migrate_datasets(self.engine, self.data, filenames={identifier: 'source.jsonl'})
        self.assertEqual(result.issues[0]['code'], 'storage_path_needs_repair')

    def test_unknown_schema_not_rebuilt(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute('ALTER TABLE datasets ADD COLUMN extra TEXT')
        self.assertEqual(migrate_datasets(self.engine, self.data, apply=True).state, 'unsupported_schema')
        self.assertIn('extra', [c['name'] for c in inspect(self.engine).get_columns('datasets')])

    def test_failure_after_drop_rolls_back_the_entire_schema_change(self):
        identifier, _, _, path = self.add_dataset()
        class FailRename:
            def __init__(self, connection):
                self.connection = connection
            def execute(self, sql, *args):
                if sql.startswith('ALTER TABLE datasets_m1_new'):
                    raise sqlite3.OperationalError('injected rename failure')
                return self.connection.execute(sql, *args)
            def executemany(self, *args):
                return self.connection.executemany(*args)
        with patch('backend.app.core.dataset_migration._replace_table', side_effect=lambda conn, rows: _replace_table(FailRename(conn), rows)):
            with self.assertRaises(sqlite3.OperationalError):
                migrate_datasets(self.engine, self.data, apply=True, filenames={identifier: 'original.jsonl'})
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute('SELECT id FROM datasets').fetchone()[0], identifier)
            self.assertNotIn('sha256', [row[1] for row in connection.execute('PRAGMA table_info(datasets)')])
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='datasets_m1_new'").fetchone())
            self.assertTrue(connection.execute("SELECT 1 FROM sqlite_master WHERE name='dataset_name_index'").fetchone())
        self.assertEqual(path.read_bytes(), RAW)
        self.assertEqual(len(list((self.data / 'backups').glob('*.sqlite3'))), 1)


if __name__ == '__main__':
    unittest.main()
