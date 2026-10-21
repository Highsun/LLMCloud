"""Bounded multipart parsing; dataset content validation remains in the service."""

import logging

from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.multipart import parse_options_header

from backend.app.api.errors import detail, validation_error
from backend.app.core.dataset_contract import (
    MAX_DATASET_BYTES, MAX_MULTIPART_FIELDS, MAX_MULTIPART_FILES,
    MAX_MULTIPART_TEXT_PART_BYTES, MAX_UPLOAD_NAME_BYTES,
)
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.core.request_context import RequestLogger
from backend.app.services.errors import DatasetServiceError

logger = RequestLogger(logging.getLogger(__name__), {})


class DatasetMultipartParser(MultiPartParser):
    """Small adapter for Starlette callbacks, covered against the locked version.

    Track the terminal boundary (finalize alone does not reject truncation), enforce
    real file bytes before spooling, and close spools on *all* failed parses.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.complete = False
        self.file_bytes = 0

    def on_part_begin(self):
        super().on_part_begin()
        self.file_bytes = 0

    def on_headers_finished(self):
        disposition, _ = parse_options_header(self._current_part.content_disposition)
        if disposition != b"form-data":
            raise MultiPartException("Invalid disposition")
        super().on_headers_finished()

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self.file_bytes += end - start
            if self.file_bytes > MAX_DATASET_BYTES:
                raise DatasetServiceError(
                    ApiErrorCode.UPLOAD_TOO_LARGE, "上传文件超过允许大小。", 413,
                    [detail(["body", "file"], "file_too_large", "文件超过允许大小。")],
                )
        super().on_part_data(data, start, end)

    def on_part_end(self):
        if self._current_part.file is None and self._current_part.field_name == "name":
            raw = self._current_part.data
            if len(raw) > MAX_UPLOAD_NAME_BYTES:
                raise validation_error([detail(["body", "name"], "out_of_range", "名称编码不能超过 1 KiB。")])
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise validation_error([detail(["body", "name"], "invalid_encoding", "名称必须使用 UTF-8 编码。")]) from None
            self.items.append(("name", value))
        else:
            super().on_part_end()

    def on_end(self):
        self.complete = True

    async def parse(self):
        try:
            form = await super().parse()
            if not self.complete:
                raise MultiPartException("Missing terminal boundary")
            return form
        except BaseException:
            for spool in self._files_to_close_on_error:
                spool.close()
            raise


async def parse_dataset_form(request: Request):
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    if content_type.lower() != b"multipart/form-data" or request.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise DatasetServiceError(ApiErrorCode.UNSUPPORTED_MEDIA_TYPE, "请使用未压缩的 multipart/form-data 上传。", 415)
    if not options.get(b"boundary"):
        raise DatasetServiceError(ApiErrorCode.INVALID_MULTIPART, "上传表单缺少 boundary。", 400)
    parser = DatasetMultipartParser(
        request.headers, request.stream(), max_files=MAX_MULTIPART_FILES,
        max_fields=MAX_MULTIPART_FIELDS, max_part_size=MAX_MULTIPART_TEXT_PART_BYTES,
    )
    try:
        return await parser.parse()
    except MultiPartException:
        raise DatasetServiceError(ApiErrorCode.INVALID_MULTIPART, "上传表单结构无效或超过解析限制。", 400) from None
    except OSError as error:
        logger.error("upload_spool_failed reason=%s", type(error).__name__)
        raise DatasetServiceError(ApiErrorCode.STORAGE_UNAVAILABLE, "上传缓存暂时不可用，请稍后重试。", 503) from None


def dataset_form_fields(form) -> tuple[UploadFile, str | None]:
    errors, seen = [], set()
    for key, value in form.multi_items():
        if key not in ("file", "name"):
            errors.append(detail(["body", key], "extra_field", "不支持此上传字段。"))
        elif key in seen:
            errors.append(detail(["body", key], "duplicate_field", "上传字段不能重复。"))
        elif (key == "file") != isinstance(value, UploadFile):
            errors.append(detail(["body", key], "invalid_type", "file 必须是文件，name 必须是文本。"))
        seen.add(key)
    if "file" not in seen:
        errors.append(detail(["body", "file"], "missing", "缺少上传文件。"))
    if errors:
        raise validation_error(errors)
    return form["file"], form.get("name")
