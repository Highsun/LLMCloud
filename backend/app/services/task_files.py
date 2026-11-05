"""Bounded descriptor reads under server-owned roots (Linux/WSL deployment)."""

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import stat


class TaskFileMissing(FileNotFoundError):
    """A task-relative component is absent, not an inaccessible root."""


class TaskFileChanged(OSError):
    """The named file was replaced, unlinked or shrunk during a read."""


def _directory(stack, name, parent=None):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=parent)
    stack.callback(os.close, fd)
    return fd


@contextmanager
def open_task_directory(root, parts=()):
    # Walk even root ancestors without following links. Do not resolve a link
    # and subsequently trust the resolved target. Configured roots are absolute.
    root = Path(root)
    if (not root.is_absolute() or ".." in root.parts
            or any(p in ("", ".", "..") or "/" in p or "\\" in p for p in parts)):
        raise OSError("Unsafe task file layout")
    with ExitStack() as stack:
        parent = _directory(stack, "/")
        for part in root.parts[1:]:
            parent = _directory(stack, part, parent)
        try:
            for part in parts:
                parent = _directory(stack, part, parent)
        except FileNotFoundError:
            raise TaskFileMissing() from None
        yield parent


@contextmanager
def _open(root, parts):
    if not parts or any(p in ("", ".", "..") or "/" in p or "\\" in p for p in parts):
        raise OSError("Unsafe task file layout")
    with open_task_directory(root, parts[:-1]) as parent, ExitStack() as stack:
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=parent)
        except FileNotFoundError:
            raise TaskFileMissing() from None
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("Task source must be a singly linked regular file")
        yield fd, info


@dataclass(frozen=True)
class TaskFile:
    fd: int
    info: os.stat_result

    def read(self, size, offset):
        """One bounded pread; short reads fail instead of fabricating EOF."""
        result = os.pread(self.fd, size, offset)
        if len(result) != size:
            raise TaskFileChanged()
        return result


@contextmanager
def open_task_file(root, parts):
    """Pin a file, verify its final named identity, and always close handles."""
    with _open(root, parts) as (fd, initial):
        yield TaskFile(fd, initial)
        current = os.fstat(fd)
        if current.st_size < initial.st_size or current.st_nlink != 1:
            raise TaskFileChanged()
        try:
            with _open(root, parts) as (_, named):
                if (named.st_dev, named.st_ino) != (initial.st_dev, initial.st_ino):
                    raise TaskFileChanged()
        except TaskFileMissing:
            raise TaskFileChanged() from None
