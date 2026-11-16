"""Verify image source bytes when a deliberately Git-free image trains.

Normal checkouts still use real Git. This manifest is build provenance, not an
authentication signature; the image digest and original manifest remain the
deployment evidence. Missing/mutated source never silently becomes clean.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(root):
    root = Path(root).resolve()
    paths = [root / name for name in ("pyproject.toml", "uv.lock", "README.md")]
    for name in ("backend", "trainer", "worker", "scripts"):
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Missing or linked source directory")
        paths.extend(directory.rglob("*.py"))
    result = {}
    for path in sorted(paths):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Source must contain real files within the project")
        result[path.relative_to(root).as_posix()] = _sha256(path)
    return result


def git_identity(root):
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    commit = git("rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("Expected a complete Git commit")
    return commit, bool(git("status", "--porcelain"))


def export_provenance(root):
    root = Path(root).resolve()
    before = source_files(root)
    commit, dirty = git_identity(root)
    if source_files(root) != before:
        raise ValueError("Source changed while generating image provenance")
    return {"version": 1, "code_commit": commit, "working_tree_dirty": dirty, "files": before}


def image_identity(root):
    root = Path(root).resolve()
    path = root / "build-provenance.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Image build provenance is missing or unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"version", "code_commit", "working_tree_dirty", "files"}
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["working_tree_dirty"]) is not bool
            or not isinstance(value["code_commit"], str)
            or re.fullmatch(r"[0-9a-f]{40}", value["code_commit"]) is None
            or not isinstance(value["files"], dict)
            or value["files"] != source_files(root)):
        raise ValueError("Image source does not match build provenance")
    return value["code_commit"], value["working_tree_dirty"]


def code_identity(root):
    root = Path(root).resolve()
    if (root / ".git").exists():
        return git_identity(root)
    return image_identity(root)
