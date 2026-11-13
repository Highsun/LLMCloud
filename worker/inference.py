"""Execute claimed inference jobs within the existing GPU worker."""

from contextlib import ExitStack
import gc
import logging
import sys
from time import monotonic, time
import traceback

from backend.app.core.observability_protocols import CompletedArtifactNotFound, CompletedArtifactNotReady
from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.inference_schemas import InferenceErrorCode, InferenceResponse
from backend.app.services.errors import DatasetServiceError
from backend.app.services.task_download import snapshot_completed_artifact
from trainer.contracts import TrainingError
from trainer.model_cache import resolve_model_paths, verify_model_cache
from trainer.reload import GenerationInterrupted, generate_verified_adapter

logger = logging.getLogger(__name__)


def _clear_exception_frames(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        traceback.clear_frames(error.__traceback__)
        error = error.__cause__ or error.__context__


def _load_cached_model(settings, revision):
    paths = resolve_model_paths(data_dir=settings.data_dir)
    try:
        return verify_model_cache(paths.cache_dir, revision)
    except TrainingError:
        raise DatasetServiceError(InferenceErrorCode.MODEL_NOT_CACHED, "模型缓存不可用。", 503) from None


def execute_inference(job_id, repository, settings):
    claimed = repository.claim_inference(job_id)
    if claimed is None:
        return
    body, finish_by = claimed
    deadline = monotonic() + max(0, finish_by - time())
    next_cancel_check = 0.0

    def checkpoint():
        nonlocal next_cancel_check
        if monotonic() >= deadline:
            raise GenerationInterrupted()
        now = monotonic()
        if now >= next_cancel_check:
            next_cancel_check = now + 0.25
            if repository.inference_cancelled(job_id):
                raise GenerationInterrupted()

    started = monotonic()
    error, result = None, None
    try:
        completed = repository.get_completed_artifact(body.task_id)
        with ExitStack() as resources:
            _, verified, _, _ = snapshot_completed_artifact(
                settings, completed, resources, area="inference", checkpoint=checkpoint)
            checkpoint()
            cached = _load_cached_model(settings, completed.spec.model_revision)
            checkpoint()
            generated = generate_verified_adapter(verified, cached, prompt=body.prompt,
                max_new_tokens=body.max_new_tokens, compare=body.mode == "compare", checkpoint=checkpoint)
            result = InferenceResponse.model_validate(generated).model_dump(mode="json")
    except Exception as exc:
        if isinstance(exc, GenerationInterrupted):
            error = InferenceErrorCode.INFERENCE_TIMEOUT
        elif isinstance(exc, CompletedArtifactNotFound):
            error = ApiErrorCode.TASK_NOT_FOUND
        elif isinstance(exc, CompletedArtifactNotReady):
            error = ApiErrorCode.ARTIFACT_NOT_READY
        elif isinstance(exc, TaskStoreError):
            error = ApiErrorCode.DATABASE_UNAVAILABLE
        elif isinstance(exc, DatasetServiceError):
            error = {
                ApiErrorCode.INVALID_ARTIFACT: ApiErrorCode.INVALID_ARTIFACT,
                ApiErrorCode.ARTIFACT_TOO_LARGE: ApiErrorCode.INVALID_ARTIFACT,
                InferenceErrorCode.MODEL_NOT_CACHED: InferenceErrorCode.MODEL_NOT_CACHED,
            }.get(exc.code, InferenceErrorCode.INFERENCE_FAILED)
        elif isinstance(exc, TrainingError):
            error = {
                "INVALID_REQUEST": ApiErrorCode.VALIDATION_ERROR,
                "INVALID_ARTIFACT": ApiErrorCode.INVALID_ARTIFACT,
                "MODEL_NOT_CACHED": InferenceErrorCode.MODEL_NOT_CACHED,
            }.get(exc.failure.code, InferenceErrorCode.INFERENCE_FAILED)
        else:
            error = InferenceErrorCode.INFERENCE_FAILED
        result = None
        logger.warning("inference_execution_failed request_id=%s task_id=%s code=%s reason=%s",
            job_id, body.task_id, error, type(exc).__name__)
        _clear_exception_frames(exc)
    finally:
        gc.collect()
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            try:
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            except Exception:
                # Exit before another task can use a broken CUDA context.
                # Recovery occurs after a successor obtains the process lock.
                raise SystemExit("推理 GPU 清理失败，需要重启 Worker。") from None
    try:
        repository.complete_inference(job_id, error=error, result=result)
    except TaskStoreError:
        raise SystemExit("推理终态写入未确认，需要重启 Worker。") from None
    logger.info("inference_finished request_id=%s task_id=%s seconds=%.3f",
                job_id, body.task_id, monotonic() - started)
