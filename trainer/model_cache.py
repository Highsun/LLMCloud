"""Pinned Qwen cache preparation and offline integrity checks; no eager HF imports."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Annotated, Literal
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import Field, model_validator

from trainer.contracts import BaseModelId, ContractModel, PositiveInt, Revision, Sha256, TrainingError, TrainingFailure

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
REPO_FOLDER = "models--Qwen--Qwen2.5-0.5B-Instruct"
REQUIRED_FILES = (
    "config.json", "generation_config.json", "model.safetensors", "tokenizer.json",
    "tokenizer_config.json", "vocab.json", "merges.txt", "LICENSE", "README.md",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fail(code, message, *, stage="model_loading", cause=None):
    error = TrainingError(TrainingFailure(code=code, stage=stage, message=message))
    if cause is None:
        raise error
    raise error from cause


@dataclass(frozen=True)
class ModelPaths:
    data_dir: Path
    hf_home: Path
    cache_dir: Path


def resolve_model_paths(*, project_root=PROJECT_ROOT, env_file=None, environ=None,
                        data_dir=None, hf_home=None, cache_dir=None) -> ModelPaths:
    """CLI > environment > explicit .env > defaults. Relative values use repo root."""
    root = Path(project_root).resolve()
    source = root / ".env" if env_file is None else Path(env_file)
    if not source.is_absolute():
        source = root / source
    if env_file is not None and not source.is_file():
        raise ValueError("Explicit environment file does not exist")
    values = {**dotenv_values(source, interpolate=False),
              **(os.environ if environ is None else environ)}

    def path(value):
        candidate = Path(value).expanduser()
        return (candidate if candidate.is_absolute() else root / candidate).resolve()

    data = path(data_dir if data_dir is not None else values.get("DATA_DIR") or "data")
    home = path(hf_home if hf_home is not None else values.get("HF_HOME") or data / "models/huggingface")
    cache = path(cache_dir if cache_dir is not None else values.get("HF_HUB_CACHE") or home / "hub")
    return ModelPaths(data, home, cache)


class CachedFile(ContractModel):
    name: Literal[
        "config.json", "generation_config.json", "model.safetensors", "tokenizer.json",
        "tokenizer_config.json", "vocab.json", "merges.txt", "LICENSE", "README.md",
    ]
    size_bytes: PositiveInt
    sha256: Sha256
    source_hash_algorithm: Literal["git_sha1", "sha256"]
    source_digest: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]

    @model_validator(mode="after")
    def consistent_digest(self):
        if len(self.source_digest) != (40 if self.source_hash_algorithm == "git_sha1" else 64):
            raise ValueError("Source digest length does not match algorithm")
        return self


class ModelCacheManifest(ContractModel):
    cache_format_version: Literal["1.0.0"] = "1.0.0"
    base_model: BaseModelId = MODEL_ID
    model_revision: Revision
    tokenizer_revision: Revision
    chat_template_sha256: Sha256
    files: list[CachedFile] = Field(min_length=len(REQUIRED_FILES), max_length=len(REQUIRED_FILES))

    @model_validator(mode="after")
    def consistent_snapshot(self):
        if self.model_revision != self.tokenizer_revision:
            raise ValueError("Tokenizer revision differs from model")
        if {file.name for file in self.files} != set(REQUIRED_FILES):
            raise ValueError("Cache inventory is incomplete or duplicated")
        return self


@dataclass(frozen=True)
class CachedModel:
    cache_dir: Path
    snapshot_dir: Path
    manifest_path: Path
    manifest: ModelCacheManifest

    def summary(self):
        return {"status": "cache_verified", "base_model": self.manifest.base_model,
                "model_revision": self.manifest.model_revision,
                "tokenizer_revision": self.manifest.tokenizer_revision,
                "chat_template_sha256": self.manifest.chat_template_sha256,
                "file_count": len(self.manifest.files),
                "total_bytes": sum(file.size_bytes for file in self.manifest.files)}


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        _fail("INVALID_REQUEST", "离线检查需要完整的 40 位小写模型 revision。", stage="preflight")
    return value


def _member(root, *parts):
    candidate = root.joinpath(*parts)
    try:
        contained = candidate.resolve().is_relative_to(root)
    except (OSError, RuntimeError) as error:
        _fail("INVALID_REQUEST", "缓存路径无法解析或存在循环链接。", stage="preflight", cause=error)
    if not contained:
        _fail("INVALID_REQUEST", "缓存目录存在越界链接。", stage="preflight")
    return candidate


def _cache_root(cache_dir):
    supplied = Path(cache_dir)
    if not supplied.is_absolute() or ".." in supplied.parts:
        _fail("INVALID_REQUEST", "缓存参数必须是已解析的绝对路径。", stage="preflight")
    try:
        root = supplied.resolve()
    except (OSError, RuntimeError) as error:
        _fail("INVALID_REQUEST", "缓存根目录无法解析。", stage="preflight", cause=error)
    _member(root, REPO_FOLDER)
    _member(root, ".llmcloud", REPO_FOLDER)
    return root


def _locations(cache_dir, revision):
    root = _cache_root(cache_dir)
    _revision(revision)
    snapshot = _member(root, REPO_FOLDER, "snapshots", revision)
    metadata = _member(root, ".llmcloud", REPO_FOLDER, f"{revision}.json")
    return root, snapshot, metadata


def _hash_file(path, size):
    sha256 = hashlib.sha256()
    git_sha1 = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha256.update(chunk)
            git_sha1.update(chunk)
    return sha256.hexdigest(), git_sha1.hexdigest()


def _inspect_files(root, snapshot, expected):
    result = []
    for item in expected:
        file = _member(root, REPO_FOLDER, "snapshots", snapshot.name, item["name"])
        if not file.is_file() or file.stat().st_size != item["size_bytes"]:
            _fail("MODEL_NOT_CACHED", f"缓存文件 {item['name']} 缺失或大小不符，请检查指定 revision。")
        sha256, git_sha1 = _hash_file(file, item["size_bytes"])
        digest = git_sha1 if item["source_hash_algorithm"] == "git_sha1" else sha256
        if digest != item["source_digest"] or ("sha256" in item and sha256 != item["sha256"]):
            _fail("MODEL_NOT_CACHED", f"缓存文件 {item['name']} 哈希校验失败。")
        result.append(CachedFile(**{**item, "sha256": sha256}))
    config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((snapshot / "tokenizer_config.json").read_text(encoding="utf-8"))
    if config.get("model_type") != "qwen2":
        _fail("MODEL_LOAD_FAILED", "缓存模型配置不属于预期的 Qwen2 架构。")
    template = tokenizer.get("chat_template")
    if not isinstance(template, str) or not template.strip():
        _fail("MODEL_LOAD_FAILED", "缓存 tokenizer 缺少可用 chat template。")
    return result, hashlib.sha256(template.encode("utf-8")).hexdigest()


def verify_model_cache(cache_dir: Path, revision: str) -> CachedModel:
    """No HF import, network, writes, or GPU use. Verify every required file."""
    root, snapshot, metadata = _locations(cache_dir, revision)
    try:
        if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 128 * 1024:
            _fail("MODEL_NOT_CACHED", "缺少有效模型缓存清单，请先执行 prepare。")
        manifest = ModelCacheManifest.model_validate_json(metadata.read_bytes())
        if manifest.model_revision != revision:
            _fail("MODEL_NOT_CACHED", "缓存清单与请求 revision 不一致。")
        _, template_hash = _inspect_files(root, snapshot, [file.model_dump() for file in manifest.files])
        if manifest.chat_template_sha256 != template_hash:
            _fail("MODEL_NOT_CACHED", "缓存模板与清单不一致。")
        return CachedModel(root, snapshot, metadata, manifest)
    except TrainingError:
        raise
    except (OSError, ValueError, TypeError) as error:
        _fail("MODEL_NOT_CACHED", "无法读取或验证模型缓存，请检查指定 revision。", cause=error)


def _hub():
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as error:
        _fail("MODEL_LOAD_FAILED", "请先 uv sync --locked --extra training 安装模型依赖。", cause=error)
    return HfApi(token=False), snapshot_download


def prepare_model_cache(cache_dir: Path, revision="main") -> CachedModel:
    """Explicitly online: resolve once, download pinned files, verify, commit metadata."""
    if revision != "main":
        _revision(revision)
    cache_dir = _cache_root(cache_dir)
    try:
        api, download = _hub()
        info = api.model_info(MODEL_ID, revision=revision, files_metadata=True, timeout=20)
        pinned = info.sha
        if not isinstance(pinned, str) or not re.fullmatch(r"[0-9a-f]{40}", pinned):
            _fail("MODEL_LOAD_FAILED", "官方返回的模型 revision 无效。")
        if revision != "main" and revision != pinned:
            _fail("MODEL_LOAD_FAILED", "官方元数据返回了不同的模型 revision。")
        root, snapshot, metadata = _locations(cache_dir, pinned)
        available = {file.rfilename: file for file in info.siblings}
        expected = []
        for name in REQUIRED_FILES:
            file = available.get(name)
            if file is None or type(file.size) is not int or file.size <= 0:
                _fail("MODEL_LOAD_FAILED", "官方模型文件清单不完整或布局不受支持。")
            lfs_sha = getattr(file.lfs, "sha256", None) if file.lfs else None
            digest = lfs_sha or file.blob_id
            algorithm = "sha256" if lfs_sha else "git_sha1"
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{%d}" % (64 if lfs_sha else 40), digest):
                _fail("MODEL_LOAD_FAILED", "官方文件缺少可验证的摘要。")
            expected.append({"name": name, "size_bytes": file.size,
                             "source_hash_algorithm": algorithm, "source_digest": digest})
        downloaded = Path(download(MODEL_ID, revision=pinned, cache_dir=root,
                                   allow_patterns=list(REQUIRED_FILES), max_workers=2,
                                   token=False, local_files_only=False, etag_timeout=20))
        if downloaded.resolve() != snapshot.resolve():
            _fail("MODEL_LOAD_FAILED", "下载返回的缓存路径不匹配请求 revision。")
        files, template_hash = _inspect_files(root, snapshot, expected)
        manifest = ModelCacheManifest(model_revision=pinned, tokenizer_revision=pinned,
                                      chat_template_sha256=template_hash, files=files)
    except TrainingError:
        raise
    except Exception as error:
        _fail("MODEL_LOAD_FAILED", f"模型准备失败（{type(error).__name__}），请检查网络或缓存。", cause=error)
    temporary = metadata.with_name(f".{metadata.name}.{uuid4().hex}.tmp")
    try:
        metadata.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(manifest.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(metadata)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # A partial temp file is not a completion marker; preserve the primary error.
        _fail("ARTIFACT_WRITE_FAILED", "模型文件已检查，但缓存清单保存失败。", stage="saving", cause=error)
    return CachedModel(root, snapshot, metadata, manifest)
