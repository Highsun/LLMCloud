#!/usr/bin/env python3
"""Capture/verify durable bytes and SQL rows across an idle service restart.

Run against a quiescent deployment. This deliberately does not create data,
restart services, copy weights, expose row contents, or claim GPU readiness.
Keep the manifest on the runtime disk: it contains local paths and file names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError(f"Required directory is missing: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError(f"File escapes the selected root: {path}")
            result[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": sha256(path),
            }
    return result


def database(path: Path, ignored: list[str]) -> dict:
    if not path.is_file():
        raise ValueError("The SQLite database must already exist")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise ValueError("SQLite integrity_check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign_key_check failed")
        names = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        result = {}
        for name in names:
            if name in ignored:
                continue
            # Names originate from sqlite_master; quote identifiers, never values.
            quoted = '"' + name.replace('"', '""') + '"'
            rows = [json.dumps(row, ensure_ascii=False, default=lambda value: value.hex())
                    for row in db.execute(f"SELECT * FROM {quoted}")]
            encoded = "\n".join(sorted(rows)).encode("utf-8")
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(encoded).hexdigest(),
                            "schema_sha256": hashlib.sha256(schema.encode()).hexdigest()}
        return result


def capture(state: Path, model: Path, ignored: list[str]) -> dict:
    return {
        "version": 1, "state_dir": str(state.resolve()), "model_dir": str(model.resolve()),
        "ignored_tables": ignored,
        "database": database(state / "data" / "llmcloud.db", ignored),
        "datasets": files(state / "data" / "datasets"),
        "outputs": files(state / "data" / "outputs"),
        "model_cache": files(model),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("capture")
    record.add_argument("--state-dir", type=Path, required=True)
    record.add_argument("--model-dir", type=Path, required=True)
    record.add_argument("--ignore-table", action="append", default=["inference_jobs"])
    record.add_argument("--manifest", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            result = capture(args.state_dir, args.model_dir, args.ignore_table)
            if args.manifest.exists():
                raise ValueError("Refusing to overwrite an existing baseline manifest")
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            expected = json.loads(args.manifest.read_text(encoding="utf-8"))
            if expected.get("version") != 1:
                raise ValueError("Unsupported manifest version")
            result = capture(Path(expected["state_dir"]), Path(expected["model_dir"]), expected["ignored_tables"])
            differences = [key for key in ("database", "datasets", "outputs", "model_cache") if result[key] != expected[key]]
            if differences:
                raise ValueError("Persistent content changed: " + ", ".join(differences))
        print(json.dumps({"ok": True, "command": args.command,
            "tables": {name: item["rows"] for name, item in result["database"].items()},
            "dataset_files": len(result["datasets"]), "output_files": len(result["outputs"]),
            "model_files": len(result["model_cache"]),
            "note": "Idle durable-state check; not a GPU or cloud acceptance result"}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
