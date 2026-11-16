"""Render a silent historical-evidence insert, never an online demonstration.

Requires Pillow, ffmpeg and ffprobe. Inputs are verified slide PNGs rendered
from LLMCloud-course.pptx. Keep output_dir on the E drive for this workstation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


TIMELINE = [
    {"slide": 4, "seconds": 10, "date": "2026-11-12 本地真实训练历史截图"},
    {"slide": 7, "seconds": 12, "date": "2026-11-15 E01 一次性留出评估"},
    {"slide": 8, "seconds": 14, "date": "2026-11-15 人工评分与 AI 代评"},
    {"slide": 9, "seconds": 10, "date": "2026-11-14 本地 GPU_BUSY 历史截图"},
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str]) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slide-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    parser.add_argument("--encoder", default="h264_mf", choices=("h264_mf", "libx264", "mpeg4"))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    font = ImageFont.truetype(str(args.font), 25)
    small = ImageFont.truetype(str(args.font), 20)
    cues = []
    sequence_time = 0
    for index, item in enumerate(TIMELINE, start=1):
        source = (args.slide_dir / f"slide-{item['slide']}.png").resolve()
        with Image.open(source) as original:
            if original.size != (1280, 720):
                raise ValueError(f"Expected intact 1280x720 slide: {source}")
            frame = original.convert("RGB")
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 650, 1279, 719), fill="#14233D")
        disclosure = "历史证据与实验图表素材  非在线实录  无配音"
        draw.text((34, 654), disclosure, font=font, fill="white")
        draw.text((34, 690), item["date"], font=small, fill="#DDE9F7")
        image_path = output / f"frame-{index}.png"
        frame.save(image_path)
        cues.append({"asset_id": f"slide-{item['slide']}", "source": str(source), "source_sha256": sha256(source), "source_kind": "historical_screenshot_or_existing_experiment_chart", "sequence_start": sequence_time, "sequence_end": sequence_time + item["seconds"], "image": image_path.name, "disclosure": disclosure, "date": item["date"]})
        sequence_time += item["seconds"]
    concat = output / "timeline.ffconcat"
    records = ["ffconcat version 1.0"]
    for cue in cues:
        records.extend([f"file '{cue['image']}'", f"duration {cue['sequence_end'] - cue['sequence_start']}"])
    records.append(f"file '{cues[-1]['image']}'")
    concat.write_text("\n".join(records) + "\n", encoding="utf-8")
    destination = output / "LLMCloud-historical-evidence-silent.mp4"
    encoder_args = ["-c:v", args.encoder]
    if args.encoder == "h264_mf":
        encoder_args += ["-hw_encoding", "0", "-b:v", "4000k", "-rate_control", "quality", "-quality", "90"]
    elif args.encoder == "libx264":
        encoder_args += ["-preset", "medium", "-crf", "18"]
    else:
        encoder_args += ["-q:v", "2"]
    argv = [str(args.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "concat", "-safe", "0", "-i", str(concat), "-an", "-vf", "fps=24,format=yuv420p", "-frames:v", str(sequence_time * 24), *encoder_args, "-movflags", "+faststart", "-metadata", "title=LLMCloud historical evidence insert, not online recording", str(destination)]
    try:
        run(argv)
        metadata = json.loads(run([str(args.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(destination)]))
        run([str(args.ffmpeg), "-nostdin", "-v", "error", "-i", str(destination), "-map", "0:v:0", "-f", "null", "-"])
    except subprocess.CalledProcessError as error:
        (output / "render-error.txt").write_text(error.stderr or str(error), encoding="utf-8")
        raise
    duration = float(metadata["format"]["duration"])
    if abs(duration - sequence_time) > 1 / 24:
        raise ValueError(f"Timeline {sequence_time}s differs from output {duration}s")
    manifest = {"kind": "silent_historical_evidence_material", "online_recording": False, "audio": False, "fps": 24, "expected_seconds": sequence_time, "measured_seconds": duration, "timeline": cues, "output": str(destination), "output_sha256": sha256(destination), "ffmpeg_version": run([str(args.ffmpeg), "-version"]).splitlines()[0], "probe": metadata, "full_decode": "passed", "visual_review": "pending"}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "render-command.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"video": str(destination), "seconds": duration, "sha256": manifest["output_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
