"""Linux process lock shared by the future Worker and offline reconciliation.

This primitive does not install Worker hooks. Every Worker on the same physical
GPU must use the same LOG_DIR and hold one handle throughout its lifetime.
"""

import os
from pathlib import Path
import stat

WORKER_LOCK_FILENAME = "worker.lock"


class WorkerLockError(RuntimeError):
    pass


class WorkerLockBusy(WorkerLockError):
    pass


class WorkerInstanceLock:
    def __init__(self, log_dir):
        self.path = Path(log_dir) / WORKER_LOCK_FILENAME
        self._descriptor = None

    def acquire(self):
        import fcntl

        if self._descriptor is not None:
            return self
        descriptor = None
        try:
            if self.path.parent.is_symlink():
                raise WorkerLockError("Worker lock directory must not be linked")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise WorkerLockError("Worker lock must be a private regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkerLockBusy("Worker instance lock is occupied") from None
            actual = self.path.stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
                raise WorkerLockError("Worker lock identity changed")
            self._descriptor, descriptor = descriptor, None
            return self
        except OSError:
            raise WorkerLockError("Worker instance lock is unavailable") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def release(self):
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        # Never unlink the inode: deleting a lock file permits two lock owners.

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exception):
        self.release()
