"""Convert the uncut browser recording to H.264 without retiming or resizing."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def run(argv: list[str]) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def probe(ffprobe: Path, path: Path) -> dict:
    return json.loads(run([str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--ffmpeg", type=Path, required=True)
    p.add_argument("--ffprobe", type=Path, required=True)
    p.add_argument("--output-name", default="LLMCloud-live-demo.mp4")
    p.add_argument("--deployment-scope", default="Container API/frontend/Redis and temporary native GPU Worker on same E-backed WSL host, not full GPU-container or cloud")
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=False)
    source_probe = probe(a.ffprobe, a.source)
    source_streams = source_probe["streams"]
    if len(source_streams) != 1 or source_streams[0]["codec_type"] != "video":
        raise ValueError("This source contract is a silent, video-only browser recording")
    if Path(a.output_name).name != a.output_name or not a.output_name.lower().endswith(".mp4"):
        raise ValueError("output-name must be a plain MP4 filename")
    destination = a.output_dir / a.output_name
    command = [str(a.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n", "-i", str(a.source), "-map", "0:v:0", "-an", "-c:v", "h264_mf", "-hw_encoding", "0", "-rate_control", "quality", "-quality", "95", "-b:v", "6000k", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", "title=LLMCloud local real browser demo", str(destination)]
    try:
        run(command)
        output_probe = probe(a.ffprobe, destination)
        run([str(a.ffmpeg), "-nostdin", "-v", "error", "-i", str(destination), "-map", "0:v:0", "-f", "null", "-"])
    except subprocess.CalledProcessError as error:
        (a.output_dir / "render-error.txt").write_text(error.stderr or str(error), encoding="utf-8")
        raise
    source_video = source_streams[0]
    output_video = output_probe["streams"][0]
    for key in ("width", "height", "avg_frame_rate"):
        if source_video[key] != output_video[key]:
            raise ValueError(f"Unexpected {key} change")
    if abs(float(source_probe["format"]["duration"]) - float(output_probe["format"]["duration"])) > 0.04:
        raise ValueError("Unexpected duration change")
    manifest = {"kind": "uncut_real_browser_recording_transcode", "recording_date": "2026-11-15", "source": str(a.source.resolve()), "source_sha256": digest(a.source), "output": str(destination.resolve()), "output_sha256": digest(destination), "deployment_scope": a.deployment_scope, "source_probe": source_probe, "output_probe": output_probe, "speed": "unchanged", "geometry": "unchanged", "cuts": [], "audio": False, "full_decode": "passed", "visual_review": "pending"}
    (a.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.output_dir / "command.json").write_text(json.dumps(command, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"video": str(destination), "sha256": manifest["output_sha256"], "duration": output_probe["format"]["duration"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
