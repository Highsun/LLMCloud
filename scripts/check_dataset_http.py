"""Smoke-check dataset routes over TCP using an isolated temporary API and store."""

import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile

import httpx
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.dataset_contract import MAX_MULTIPART_BYTES  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models.dataset_schemas import DatasetDetail  # noqa: E402
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402


async def check(settings: Settings) -> dict:
    app = create_app(settings)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(500):
                if server.started or task.done():
                    break
                await asyncio.sleep(0.01)
            if not server.started:
                raise RuntimeError("Temporary API failed to start")
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                raw = (PROJECT_ROOT / "docs/examples/train.jsonl").read_bytes()
                request = client.build_request("POST", "/api/v1/datasets", files={"file": ("train.jsonl", raw)})
                body = request.read()

                async def chunks():
                    for index in range(0, len(body), 17):
                        yield body[index:index + 17]

                uploaded = await client.post("/api/v1/datasets", content=chunks(), headers={
                    "Content-Type": request.headers["content-type"], "Origin": "http://localhost:5173",
                })
                assert uploaded.status_code == 201, uploaded.text
                detail = DatasetDetail.model_validate(uploaded.json())
                assert uploaded.headers["access-control-allow-origin"] == "http://localhost:5173"
                fetched = await client.get(uploaded.headers["location"])
                assert fetched.json() == uploaded.json()
                page = (await client.get("/api/v1/datasets?page=1&page_size=20")).json()
                assert page["total"] == 1 and page["items"][0]["id"] == str(detail.id)
                assert (settings.data_dir / "datasets" / str(detail.id) / "train.jsonl").read_bytes() == raw
                invalid = await client.get("/api/v1/datasets?page_size=101")
                assert invalid.status_code == 422
                assert str(ErrorResponse.model_validate(invalid.json()).error.request_id) == invalid.headers["x-request-id"]

            # The server must reject a declared oversized body before receiving it.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write((
                    "POST /api/v1/datasets HTTP/1.1\r\nHost: localhost\r\n"
                    f"Content-Length: {MAX_MULTIPART_BYTES + 1}\r\n"
                    "Content-Type: multipart/form-data; boundary=test\r\nConnection: close\r\n\r\n"
                ).encode())
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), timeout=5)
                head, payload = response.split(b"\r\n\r\n", 1)
                assert head.startswith(b"HTTP/1.1 413"), head
                assert ErrorResponse.model_validate_json(payload).error.code == "UPLOAD_TOO_LARGE"
            finally:
                writer.close()
                await writer.wait_closed()
            return {"status": "ok", "transport": "TCP/HTTP", "chunked_upload": 201,
                    "list": 200, "detail": 200, "invalid_query": 422, "early_body_limit": 413}
        finally:
            server.should_exit = True
            await task


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="llmcloud-http-") as directory:
        root = Path(directory)
        settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs",
                            database_url="", api_prefix="/api/v1", cors_origins=["http://localhost:5173"])
        print(json.dumps(asyncio.run(check(settings)), ensure_ascii=False))


if __name__ == "__main__":
    main()
