"""Server-owned dataset keys; no client file name is used as a storage path."""

from pathlib import Path
from uuid import UUID


def sanitize_filename(filename: str) -> str:
    if not isinstance(filename, str):
        raise ValueError("invalid_filename")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in filename):
        raise ValueError("invalid_filename")
    if not filename.lower().endswith(".jsonl"):
        raise ValueError("unsupported_extension")
    if not filename[:-6].strip():
        raise ValueError("invalid_filename")
    return filename


def dataset_key(dataset_id: str) -> str:
    parsed = UUID(str(dataset_id))
    if parsed.version != 4 or str(parsed) != str(dataset_id):
        raise ValueError("Dataset ID must be a canonical UUIDv4")
    return f"datasets/{parsed}/train.jsonl"


def resolve_dataset_path(data_dir: Path, key: str) -> Path:
    parts = key.split("/")
    if len(parts) != 3 or dataset_key(parts[1]) != key:
        raise ValueError("Invalid dataset storage key")
    root = Path(data_dir).resolve()
    path = root / key
    for candidate in (root / "datasets", path.parent, path):
        if candidate.is_symlink():
            raise ValueError("Dataset symlinks are not supported")
    if not path.resolve().is_relative_to(root / "datasets"):
        raise ValueError("Dataset path escapes storage root")
    return path
