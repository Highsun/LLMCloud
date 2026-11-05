"""M4 v1 vocabulary and bounds; no transport, persistence or training runtime."""

from enum import StrEnum
from types import MappingProxyType

OBSERVABILITY_CONTRACT_VERSION = "1.0.0"
MAX_SAFE_INTEGER = 2**53 - 1
DEFAULT_METRICS_LIMIT = 200
MAX_METRICS_LIMIT = 1000
MAX_METRIC_LINE_BYTES = 16 * 1024
MAX_METRICS_SCAN_BYTES = 512 * 1024
MAX_METRICS_RESPONSE_BYTES = 1024 * 1024
DEFAULT_LOG_TAIL = 100
MAX_LOG_TAIL = 500
MAX_LOG_READ_BYTES = 64 * 1024
MAX_LOG_RESPONSE_BYTES = 256 * 1024
MAX_OBSERVED_LOG_TASKS = 4096
MAX_LOG_DIAGNOSTICS = 16
MAX_LOG_FRAMES = 32
MAX_LOG_TARGET_MODULES = 64
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_CONCURRENT_DOWNLOADS = 1
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_DOWNLOAD_MANIFEST_BYTES = 512 * 1024
DOWNLOAD_RETRY_AFTER_SECONDS = 2
DOWNLOAD_MEDIA_TYPE = "application/zip"
DOWNLOAD_CACHE_CONTROL = "no-store"
OBSERVATION_POLL_INTERVAL_MS = 2000
MAX_METRIC_PAGES_PER_POLL = 5
MAX_VISIBLE_METRICS = 10_000


class SourceState(StrEnum):
    READY = "ready"
    NOT_CREATED = "not_created"


class ObservabilityErrorCode(StrEnum):
    METRICS_CURSOR_INVALID = "METRICS_CURSOR_INVALID"
    METRICS_CORRUPTED = "METRICS_CORRUPTED"
    METRICS_UNAVAILABLE = "METRICS_UNAVAILABLE"
    LOGS_UNAVAILABLE = "LOGS_UNAVAILABLE"
    ARTIFACT_NOT_READY = "ARTIFACT_NOT_READY"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    ARTIFACT_TOO_LARGE = "ARTIFACT_TOO_LARGE"
    DOWNLOAD_BUSY = "DOWNLOAD_BUSY"


OBSERVABILITY_ERROR_STATUS = MappingProxyType({
    ObservabilityErrorCode.METRICS_CURSOR_INVALID: 409,
    ObservabilityErrorCode.METRICS_CORRUPTED: 500,
    ObservabilityErrorCode.METRICS_UNAVAILABLE: 500,
    ObservabilityErrorCode.LOGS_UNAVAILABLE: 500,
    ObservabilityErrorCode.ARTIFACT_NOT_READY: 409,
    ObservabilityErrorCode.INVALID_ARTIFACT: 500,
    ObservabilityErrorCode.ARTIFACT_TOO_LARGE: 413,
    ObservabilityErrorCode.DOWNLOAD_BUSY: 429,
})
COMMON_OBSERVABILITY_ERROR_STATUS = MappingProxyType({
    "TASK_NOT_FOUND": 404, "DATABASE_UNAVAILABLE": 503,
    "VALIDATION_ERROR": 422, "STORAGE_UNAVAILABLE": 500, "INTERNAL_ERROR": 500,
})

# Projection policy for the existing task-local JSONL producer. This is not a
# log reader or sanitizer: M4-02 must validate values as well as project keys.
LOG_COMMON_FIELDS = ("recorded_at", "stage")
LOG_FIELDS_BY_STAGE = MappingProxyType({
    "preflight": ("task_id", "precision"),
    "model_loading": (),
    "data_preparation": (),
    "data_verified": ("train", "validation"),
    "parameters": ("total_parameters", "trainable_parameters", "target_modules", "base_sha256_before"),
    "training": ("total_steps", "gradient_accumulation_steps"),
    "metric": ("contract_version", "kind", "step", "total_steps", "loss", "learning_rate", "epoch", "framework_learning_rate"),
    "parameter_verification": ("changed_lora_tensors", "lora_tensor_count", "base_sha256_before", "base_sha256_after", "base_unchanged"),
    "saving": (),
    "training_and_save_finished": ("completed_steps",),
    "failed": ("failure", "diagnostic"),
})
LOG_DATASET_FIELDS = ("sha256", "size_bytes", "row_count", "review_status", "build_id")
# The free-form failure message is deliberately omitted. The client already has
# the safe business explanation in TaskDetail.error_message.
LOG_FAILURE_FIELDS = ("task_id", "code", "stage")
LOG_DIAGNOSTIC_FIELDS = ("type", "frames")
LOG_FRAME_FIELDS = ("file", "function", "line")


def contract_limits() -> dict[str, int]:
    """Detached machine-readable bounds for generated consumer fixtures."""
    return {
        "max_safe_integer": MAX_SAFE_INTEGER,
        "default_metrics_limit": DEFAULT_METRICS_LIMIT,
        "max_metrics_limit": MAX_METRICS_LIMIT,
        "max_metric_line_bytes": MAX_METRIC_LINE_BYTES,
        "max_metrics_scan_bytes": MAX_METRICS_SCAN_BYTES,
        "max_metrics_response_bytes": MAX_METRICS_RESPONSE_BYTES,
        "default_log_tail": DEFAULT_LOG_TAIL,
        "max_log_tail": MAX_LOG_TAIL,
        "max_log_read_bytes": MAX_LOG_READ_BYTES,
        "max_log_response_bytes": MAX_LOG_RESPONSE_BYTES,
        "max_observed_log_tasks": MAX_OBSERVED_LOG_TASKS,
        "max_log_diagnostics": MAX_LOG_DIAGNOSTICS,
        "max_log_frames": MAX_LOG_FRAMES,
        "max_log_target_modules": MAX_LOG_TARGET_MODULES,
        "max_download_bytes": MAX_DOWNLOAD_BYTES,
        "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
        "download_chunk_bytes": DOWNLOAD_CHUNK_BYTES,
        "max_download_manifest_bytes": MAX_DOWNLOAD_MANIFEST_BYTES,
        "download_retry_after_seconds": DOWNLOAD_RETRY_AFTER_SECONDS,
        "poll_interval_ms": OBSERVATION_POLL_INTERVAL_MS,
        "max_metric_pages_per_poll": MAX_METRIC_PAGES_PER_POLL,
        "max_visible_metrics": MAX_VISIBLE_METRICS,
    }
