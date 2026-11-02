"""A nonblocking OS file lock, held for the entire Worker process lifetime."""

import atexit
import errno
import os
from pathlib import Path
import stat

from backend.app.core.worker_lock import (
    WORKER_LOCK_FILENAME, WorkerInstanceLock as SharedWorkerInstanceLock,
    WorkerLockBusy as WorkerAlreadyRunning,
)


class WindowsWorkerInstanceLock:
    def __init__(self, log_dir):
        self.path = Path(log_dir).resolve() / WORKER_LOCK_FILENAME
        self._fd = None

    def acquire(self):
        if self._fd is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or getattr(self.path, "is_junction", lambda: False)():
            raise ValueError("Worker lock must not be a link")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise ValueError("Worker lock must be a regular file")
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise WorkerAlreadyRunning("已有 Worker 持有实例锁，拒绝启动第二实例。") from None
            raise
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def release(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)
        # Never unlink a lock file: another process could otherwise lock a new inode.

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


class WorkerInstanceLock(WindowsWorkerInstanceLock if os.name == "nt" else SharedWorkerInstanceLock):
    """Use A's shared primitive on Linux; Windows supports CPU checks only."""

    def __init__(self, log_dir):
        super().__init__(Path(os.path.abspath(log_dir)))


_process_lock = None
_process_pid = None


def acquire_worker_lock(log_dir):
    global _process_lock, _process_pid
    target = Path(os.path.abspath(log_dir)) / WORKER_LOCK_FILENAME
    if _process_lock is not None and _process_pid == os.getpid():
        if _process_lock.path != target:
            raise ValueError("A Worker cannot change its lock directory while running")
        return _process_lock.acquire()
    _process_lock = WorkerInstanceLock(log_dir).acquire()
    _process_pid = os.getpid()
    return _process_lock


def release_worker_lock():
    global _process_lock, _process_pid
    if _process_lock is not None:
        lock, owner = _process_lock, _process_pid
        _process_lock = _process_pid = None
        if owner == os.getpid():
            lock.release()


atexit.register(release_worker_lock)
