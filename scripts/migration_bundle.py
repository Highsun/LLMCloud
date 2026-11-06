"""Private, CPU-only runtime/model backup and verified fresh-directory restore.

Code travels through Git (or a separately finalized git bundle), not this archive.
Never include SSH/AWS/agent credentials, virtualenvs, or replay Redis automatically.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import sqlite3
import stat
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 1024 * 1024


def digest(path):
    with Path(path).open('rb') as stream:
        return stream_digest(stream)


def stream_digest(stream):
    value = hashlib.sha256()
    while chunk := stream.read(CHUNK):
        value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')) or '\\' in name:
        raise ValueError('Unsafe archive member name')
    return path


def safe_link(name, target):
    if not target or target.startswith('/') or '\\' in target:
        raise ValueError('Link must be relative')
    result = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if result == '..' or result.startswith('../'):
        raise ValueError('Link escapes archive')


def sources(root):
    """Do not follow directory links; record every exclusion rather than lose it."""
    selected, excluded = [], []
    for base in ('data', 'logs'):
        for directory, dirs, files in os.walk(root / base, followlinks=False):
            dirs.sort()
            files.sort()
            for name in dirs[:] + files:
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                reason = None
                if relative == 'data/migration':
                    dirs.remove(name)
                    reason = 'migration packages excluded to prevent recursive backup'
                elif relative == 'logs/worker.lock':
                    reason = 'host-local lock inode; recreate on target, never transplant'
                elif name.endswith(('-wal', '-shm')):
                    reason = 'SQLite sidecar; database is replaced with SQLite backup API snapshot'
                elif base == 'data' and relative.startswith('data/models/') and name in ('token', 'stored_tokens'):
                    reason = 'credential file; authenticate separately on target if necessary'
                if reason:
                    excluded.append({'path': relative, 'reason': reason})
                    continue
                selected.append((path, relative, 'models' if relative == 'data/models' or
                                 relative.startswith('data/models/') else 'runtime'))
    for source, name in ((root / '.env', 'private-config/backend.env'),
                         (root / 'frontend/.env', 'private-config/frontend.env'),
                         (Path.home() / '.config/systemd/user/llmcloud-redis.service',
                          'private-config/wsl-redis-user.service')):
        if source.exists():
            if source.is_symlink() or not source.is_file():
                raise ValueError('Expected an ordinary project configuration file')
            selected.append((source, name, 'runtime'))
    return selected, excluded


def database_snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(target) as backup:
            original.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite integrity check failed')
            tables = [row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            counts = {name: backup.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                      for name in tables}
            statuses = dict(backup.execute('SELECT status,count(*) FROM training_tasks GROUP BY status')) \
                if 'training_tasks' in tables else {}
    os.chmod(target, 0o600)
    return {'tables': counts, 'task_status_counts': statuses, 'integrity_check': 'ok'}


class HashingReader:
    def __init__(self, stream):
        self.stream, self.sha = stream, hashlib.sha256()

    def read(self, size):
        value = self.stream.read(size)
        self.sha.update(value)
        return value


def build(output, *, root=ROOT, services_stopped=False):
    if not services_stopped:
        raise ValueError('Stop project writers first, then explicitly pass --services-stopped')
    root, output = Path(root).resolve(), Path(output).absolute()
    if not output.is_relative_to(root / 'data/migration') or output.resolve() != output:
        raise ValueError('Output must be a new unlinked directory below data/migration')
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    selected, excluded = sources(root)
    manifest = {'version': '1.0.0', 'created_at': datetime.now(timezone.utc).isoformat(),
                'services_stopped_asserted': True, 'files': [], 'excluded': excluded, 'databases': {},
                'code_delivery': 'Git; code.bundle may be finalized after this data snapshot',
                'cloud_uploaded': False, 'credentials_policy': 'project .env copies private; no SSH/AWS/agent credentials'}
    try:
        manifest['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    except subprocess.CalledProcessError:
        manifest['source_commit'] = None
    try:
        for category in ('runtime', 'models'):
            archive = output / f'{category}.tar.gz'
            with tarfile.open(archive, 'w:gz', compresslevel=1) as bundle:
                for path, name, group in selected:
                    if group != category:
                        continue
                    safe_name(name)
                    before = path.lstat()
                    info = tarfile.TarInfo(name)
                    info.mode, info.mtime = stat.S_IMODE(before.st_mode), int(before.st_mtime)
                    item = {'archive': category, 'path': name, 'mode': info.mode}
                    if stat.S_ISDIR(before.st_mode):
                        info.type, item['kind'] = tarfile.DIRTYPE, 'directory'
                        bundle.addfile(info)
                    elif stat.S_ISLNK(before.st_mode):
                        target = os.readlink(path)
                        safe_link(name, target)
                        resolved = path.resolve(strict=True)
                        boundary = root / 'data/models' if category == 'models' else root
                        if not resolved.is_relative_to(boundary):
                            raise ValueError('Source link points outside its payload')
                        info.type, info.linkname = tarfile.SYMTYPE, target
                        item.update(kind='symlink', target=target)
                        bundle.addfile(info)
                    elif stat.S_ISREG(before.st_mode):
                        source = path
                        with path.open('rb') as stream:
                            sqlite = stream.read(16) == b'SQLite format 3\0'
                        if sqlite:
                            source = output / '_sqlite' / name
                            manifest['databases'][name] = database_snapshot(path, source)
                        info.size, item['kind'] = source.stat().st_size, 'file'
                        if name.startswith('private-config/'):
                            info.mode = 0o600
                        with source.open('rb') as stream:
                            reader = HashingReader(stream)
                            bundle.addfile(info, reader)
                        item.update(size_bytes=info.size, sha256=reader.sha.hexdigest(), sqlite_snapshot=sqlite)
                        after = path.lstat()
                        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                            raise ValueError('Source changed during backup; stop writers and retry in a new directory')
                    else:
                        raise ValueError('Special file cannot be migrated')
                    manifest['files'].append(item)
            os.chmod(archive, 0o600)
            print(json.dumps({'archive': archive.name, 'size_bytes': archive.stat().st_size}), flush=True)
        write_json(output / 'manifest.json', manifest)
        os.chmod(output / 'manifest.json', 0o600)
        checksum_files(output)
        return manifest
    finally:
        shutil.rmtree(output / '_sqlite', ignore_errors=True)


def checksum_files(directory):
    files = sorted(path for path in Path(directory).iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    (Path(directory) / 'SHA256SUMS').write_text(''.join(f'{digest(path)}  {path.name}\n' for path in files))


def verify(directory):
    directory = Path(directory)
    checksums = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        value, name = line.split('  ', 1)
        if Path(name).name != name or name in checksums or len(value) != 64:
            raise ValueError('Invalid checksum entry')
        checksums[name] = value
        if digest(directory / name) != value:
            raise ValueError(f'Checksum differs: {name}')
    if not {'manifest.json', 'runtime.tar.gz', 'models.tar.gz'}.issubset(checksums):
        raise ValueError('Required payload missing from checksums')
    manifest = json.loads((directory / 'manifest.json').read_text())
    for category in ('runtime', 'models'):
        records = [item for item in manifest['files'] if item['archive'] == category]
        expected = {item['path']: item for item in records}
        if len(expected) != len(records):
            raise ValueError('Duplicate manifest entry')
        seen = set()
        with tarfile.open(directory / f'{category}.tar.gz', 'r:gz') as bundle:
            for member in bundle:
                safe_name(member.name)
                if member.name in seen or member.name not in expected:
                    raise ValueError('Duplicate or unexpected archive entry')
                seen.add(member.name)
                record = expected[member.name]
                if record['kind'] == 'file':
                    if not member.isfile() or member.size != record['size_bytes']:
                        raise ValueError('Archive type or size differs')
                    with bundle.extractfile(member) as stream:
                        if stream_digest(stream) != record['sha256']:
                            raise ValueError('Archive member hash differs')
                elif record['kind'] == 'symlink':
                    if not member.issym() or member.linkname != record['target']:
                        raise ValueError('Archive link differs')
                    safe_link(member.name, member.linkname)
                elif record['kind'] != 'directory' or not member.isdir():
                    raise ValueError('Archive directory differs')
        if seen != set(expected):
            raise ValueError('Missing archive entries')
    return {'status': 'migration_verified', 'entries': len(manifest['files']),
            'databases': len(manifest['databases']), 'remote_transfer': 'not_assessed'}


def restore(directory, target):
    result = verify(directory)
    target = Path(target).absolute()
    if target.resolve() != target:
        raise ValueError('Restore target must not contain symlink ancestors')
    target.mkdir(parents=True, mode=0o700, exist_ok=False)
    # Verification finishes before extraction; restore never targets a live data directory.
    for category in ('runtime', 'models'):
        with tarfile.open(Path(directory) / f'{category}.tar.gz', 'r:gz') as bundle:
            bundle.extractall(target, filter='data')
    return {**result, 'restored_to': str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--output', required=True, type=Path)
    create.add_argument('--services-stopped', action='store_true')
    for name in ('verify', 'restore'):
        command = sub.add_parser(name)
        command.add_argument('--bundle', required=True, type=Path)
        if name == 'restore':
            command.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'build':
        build(args.output, services_stopped=args.services_stopped)
        result = verify(args.output)
    elif args.command == 'verify':
        result = verify(args.bundle)
    else:
        result = restore(args.bundle, args.target)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
