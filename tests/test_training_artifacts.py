"""Small synthetic CPU bundles; never treated as actual model/reload evidence."""

from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from safetensors import TensorSpec, serialize

from trainer.artifacts import inventory, verify_training_artifacts
from trainer.contracts import TrainRequest, TrainingError, TrainingManifest, TrainingProgress
from trainer.run_storage import finish

ROOT = Path(__file__).resolve().parents[1]


def encode(tensors):
    # safetensors 0.8 uses TensorSpec; keep CPU buffers alive throughout serialization.
    buffers = {key: ctypes.create_string_buffer(value["data"]) for key, value in tensors.items()}
    return serialize({key: TensorSpec(dtype={"F32": "float32", "F16": "float16", "BF16": "bfloat16"}[value["dtype"]],
        shape=value["shape"], data_ptr=ctypes.addressof(buffers[key]), data_len=len(value["data"])) for key, value in tensors.items()})


class TrainingArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root, self.manifest = self.bundle()

    def dump(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def tensors(self, root, dtype="F32", value=0.1):
        raw = struct.pack("<ff", value, value) if dtype == "F32" else struct.pack("<HH", 0x3c00, 0x3c00)
        tensors = {f"base_model.model.model.layers.0.self_attn.q_proj.lora_{side}.weight":
            {"dtype": dtype, "shape": [1, 2] if side == "A" else [2, 1], "data": raw} for side in ("A", "B")}
        (root / "adapter/adapter_model.safetensors").write_bytes(encode(tensors))

    def bundle(self):
        task = uuid4()
        root = self.parent / "outputs" / str(task)
        for name in ("adapter", "tokenizer"):
            (root / name).mkdir(parents=True)
        template = "synthetic test template\n"
        self.tensors(root)
        config = {"target_modules": ["q_proj"], "lora_r": 1}
        snapshot = {"task_id": str(task), "base_model": "Qwen/Qwen2.5-0.5B-Instruct", "model_revision": "b" * 40,
                    "config": config, "runtime": {"max_steps": 2}}
        self.dump(root / "training_config.json", snapshot)
        self.dump(root / "adapter/adapter_config.json", {"base_model_name_or_path": snapshot["base_model"],
            "revision": snapshot["model_revision"], "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 1,
            "lora_alpha": 16, "lora_dropout": 0.05, "target_modules": ["q_proj"], "bias": "none", "inference_mode": True})
        self.dump(root / "tokenizer/tokenizer_config.json", {"tokenizer_class": "Qwen2Tokenizer", "eos_token": "EOS", "pad_token": "PAD",
            "added_tokens_decoder": {"1": {"content": "EOS"}, "2": {"content": "PAD"}}})
        self.dump(root / "tokenizer/tokenizer.json", {"model": {"type": "BPE", "vocab": {"word": 0}, "merges": []},
            "added_tokens": [{"content": "EOS", "id": 1}, {"content": "PAD", "id": 2}]})
        (root / "tokenizer/chat_template.jinja").write_text(template)
        start = datetime.now(timezone.utc) - timedelta(seconds=3)
        events = [TrainingProgress(step=step, total_steps=2, loss=1.3 - 0.1 * step, learning_rate=0.0001,
            epoch=step / 2, recorded_at=start + timedelta(seconds=step)) for step in (1, 2)]
        (root / "metrics.jsonl").write_text("".join(event.model_dump_json() + "\n" for event in events))
        env = json.loads((ROOT / "docs/examples/training/manifest.json").read_text())["environment"]
        manifest = TrainingManifest(**snapshot, tokenizer_revision="b" * 40,
            chat_template_sha256=hashlib.sha256(template.encode()).hexdigest(),
            train_dataset={"sha256": "a" * 64, "size_bytes": 20, "row_count": 2}, environment=env,
            started_at=start, finished_at=start + timedelta(seconds=3),
            summary={"completed_steps": 2, "total_steps": 2, "final_loss": events[-1].loss,
                     "elapsed_seconds": 3.0, "peak_memory_allocated_bytes": 0, "trainable_parameters": 4, "total_parameters": 104},
            artifacts=inventory(root))
        self.dump(root / "manifest.json", manifest.model_dump(mode="json"))
        return root, manifest

    def reseal(self, root=None, update=None):
        root = root or self.root
        manifest = json.loads((root / "manifest.json").read_text())
        manifest.update(update or {})
        manifest["artifacts"] = [item.model_dump() for item in inventory(root)]
        self.dump(root / "manifest.json", manifest)

    def assert_invalid(self, root=None, **kwargs):
        with self.assertRaises(TrainingError) as context:
            verify_training_artifacts(root or self.root, **kwargs)
        self.assertEqual(context.exception.failure.code, "INVALID_ARTIFACT")
        self.assertNotIn(str(self.parent), str(context.exception))

    def finish_call(self, root=None, manifest=None):
        root, manifest = root or self.root, manifest or self.manifest
        request = TrainRequest(task_id=manifest.task_id, dataset_path=self.parent / "source.jsonl", output_dir=root,
            cache_dir=self.parent / "cache", log_path=self.parent / f"{manifest.task_id}.log",
            base_model=manifest.base_model, model_revision=manifest.model_revision, config=manifest.config, runtime=manifest.runtime)
        prepared = SimpleNamespace(train=SimpleNamespace(summary=manifest.train_dataset), validation=None)
        cached = SimpleNamespace(manifest=SimpleNamespace(chat_template_sha256=manifest.chat_template_sha256))
        return finish(request, prepared, cached, manifest.summary.model_dump(exclude={"elapsed_seconds"}),
                      manifest.environment, manifest.started_at, time.monotonic() - 3)

    def test_valid_audit_is_read_only_and_portable_summary(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = verify_training_artifacts(self.root, outputs_root=self.parent / "outputs", expected_revision="b" * 40)
        self.assertEqual(result.tensor_count, 2)
        self.assertEqual(result.metric_count, 2)
        self.assertFalse(result.summary()["reload_verified"])
        self.assertNotIn(str(self.parent), json.dumps(result.summary()))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_wrong_expected_identity_revision_or_root(self):
        for options in ({"expected_task_id": uuid4()}, {"expected_revision": "a" * 40}, {"outputs_root": self.parent}):
            self.assert_invalid(**options)

    def test_missing_manifest_has_no_repair_side_effect(self):
        (self.root / "manifest.json").unlink()
        self.assert_invalid()
        self.assertFalse((self.root / "manifest.json").exists())

    def test_same_size_corruption_and_missing_file_fail(self):
        path = self.root / "adapter/adapter_model.safetensors"
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        self.assert_invalid()
        path.unlink()
        self.assert_invalid()

    def test_unlisted_files_and_base_weights_are_rejected(self):
        for name in ("model.safetensors", "dataset.jsonl", "extra.json"):
            with self.subTest(name=name):
                path = self.root / "adapter" / name
                path.write_text("must not enter download")
                self.assert_invalid()
                path.unlink()

    def test_file_directory_and_root_symlinks_are_rejected(self):
        path = self.root / "tokenizer/tokenizer.json"
        outside = self.parent / "outside.json"
        path.rename(outside)
        path.symlink_to(outside)
        self.assert_invalid()
        alias = self.parent / "task-link"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assert_invalid(alias)
        root, _ = self.bundle()
        tokenizer = root / "tokenizer"
        other = self.parent / "outside-tokenizer"
        tokenizer.rename(other)
        tokenizer.symlink_to(other, target_is_directory=True)
        self.assert_invalid(root)

    def test_hardlinks_and_failure_marker_cannot_be_success(self):
        import os
        path = self.root / "adapter/adapter_model.safetensors"
        os.link(path, self.parent / "external-hardlink")
        self.assert_invalid()
        root, _ = self.bundle()
        (root / "failure.json").write_text("{}")
        self.assert_invalid(root)

    def test_snapshot_drift_is_detected_even_after_rehash(self):
        path = self.root / "training_config.json"
        config = json.loads(path.read_text())
        config["config"]["learning_rate"] = 0.001
        self.dump(path, config)
        self.reseal()
        self.assert_invalid()

    def test_adapter_fields_must_match_even_after_rehash(self):
        for update in ({"revision": "a" * 40}, {"base_model_name_or_path": "/private/cache"}, {"lora_alpha": 32},
                       {"lora_dropout": 0.2}, {"r": 2}, {"target_modules": ["v_proj"]}, {"use_dora": True}):
            root, _ = self.bundle()
            path = root / "adapter/adapter_config.json"
            config = json.loads(path.read_text())
            config.update(update)
            self.dump(path, config)
            self.reseal(root)
            self.assert_invalid(root)

    def test_nan_weights_are_rejected_even_with_matching_hash(self):
        self.tensors(self.root, value=float("nan"))
        self.reseal()
        self.assert_invalid()

    def test_invalid_safetensors_structure_is_rejected_after_rehash(self):
        (self.root / "adapter/adapter_model.safetensors").write_bytes(b"invalid safetensors bytes")
        self.reseal()
        self.assert_invalid()

    def test_tensor_header_shapes_pairs_and_counts_are_checked(self):
        prefix = "base_model.model.model.layers.0.self_attn.q_proj.lora_"
        for tensors in (
            {prefix + "A.weight": {"dtype": "F32", "shape": [1, 2], "data": b"\0" * 8}},
            {"model.embed_tokens.weight": {"dtype": "F32", "shape": [1, 2], "data": b"\0" * 8}},
            {prefix + side + ".weight": {"dtype": "F32", "shape": [2, 2], "data": b"\0" * 16} for side in ("A", "B")},
        ):
            root, _ = self.bundle()
            (root / "adapter/adapter_model.safetensors").write_bytes(encode(tensors))
            self.reseal(root)
            self.assert_invalid(root)

    def test_f16_and_bf16_are_cpu_auditable(self):
        for dtype in ("F16", "BF16"):
            self.tensors(self.root, dtype=dtype)
            self.reseal()
            self.assertEqual(verify_training_artifacts(self.root).tensor_count, 2)

    def test_tokenizer_eos_ids_and_template_are_cross_checked(self):
        path = self.root / "tokenizer/tokenizer_config.json"
        config = json.loads(path.read_text())
        config["eos_token"] = "missing"
        self.dump(path, config)
        self.reseal()
        self.assert_invalid()
        root, _ = self.bundle()
        (root / "tokenizer/chat_template.jinja").write_text("different template")
        self.reseal(root)
        self.assert_invalid(root)

    def test_metric_sequence_and_summary_drift_are_detected_after_rehash(self):
        for change in ("duplicate", "reverse", "missing_final", "nan", "summary", "no_newline", "eval_without_data", "backward_time"):
            root, _ = self.bundle()
            path = root / "metrics.jsonl"
            events = [json.loads(line) for line in path.read_text().splitlines()]
            if change == "duplicate": events.append(events[-1])
            elif change == "reverse": events.reverse()
            elif change == "missing_final": events.pop()
            elif change == "nan": events[-1]["loss"] = float("nan")
            elif change == "summary": events[-1]["loss"] = 9.0
            elif change == "eval_without_data": events.append({**events[-1], "kind": "eval"})
            elif change == "backward_time":
                events[-1]["recorded_at"] = (datetime.fromisoformat(events[0]["recorded_at"].replace("Z", "+00:00")) - timedelta(days=1)).isoformat()
            raw = "".join(json.dumps(event) + "\n" for event in events)
            path.write_text(raw.rstrip("\n") if change == "no_newline" else raw)
            self.reseal(root)
            self.assert_invalid(root)

    def test_manifest_duplicate_json_keys_are_rejected(self):
        path = self.root / "manifest.json"
        text = path.read_text().rstrip()
        path.write_text(text[:-1] + ',"status":"completed"}')
        self.assert_invalid()

    def test_root_payload_is_rejected_and_checkpoints_are_excluded(self):
        (self.root / "checkpoints").mkdir()
        (self.root / "checkpoints/private-diagnostic.bin").write_bytes(b"diagnostic")
        self.assertEqual(verify_training_artifacts(self.root).metric_count, 2)
        (self.root / "train.jsonl").write_text("private training data")
        self.assert_invalid()

    def test_sparse_logging_and_validation_schedule(self):
        path = self.root / "metrics.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        raw = []
        for event in events:
            raw.extend([event, {**event, "kind": "eval", "loss": 1.0}])
        path.write_text("".join(json.dumps(event) + "\n" for event in raw))
        document = json.loads((self.root / "manifest.json").read_text())
        document["validation_dataset"] = {**document["train_dataset"], "sha256": "c" * 64}
        document["summary"]["eval_loss"] = 1.0
        self.reseal(update=document)
        self.assertEqual(verify_training_artifacts(self.root).metric_count, 4)
        # Missing a configured interval eval is rejected even with valid final eval.
        path.write_text("".join(json.dumps(event) + "\n" for event in [raw[0], *raw[2:]]))
        self.reseal()
        self.assert_invalid()
        # A configured sparse logging schedule legitimately starts at step 2.
        document["config"]["logging_steps"] = 2
        config_path = self.root / "training_config.json"
        config = json.loads(config_path.read_text())
        config["config"]["logging_steps"] = 2
        self.dump(config_path, config)
        path.write_text("".join(json.dumps(event) + "\n" for event in raw[2:]))
        self.reseal(update=document)
        self.assertEqual(verify_training_artifacts(self.root).metric_count, 2)

    def test_optional_tokenizer_legacy_files_must_agree(self):
        for name, contents in (("vocab.json", '{"different":0}'), ("added_tokens.json", '{}'),
                               ("merges.txt", '#version: 0.2\na b\n')):
            root, _ = self.bundle()
            (root / "tokenizer" / name).write_text(contents)
            self.reseal(root)
            self.assert_invalid(root)

    def test_success_is_published_only_after_common_audit(self):
        (self.root / "manifest.json").unlink()
        result = self.finish_call()
        self.assertEqual(verify_training_artifacts(self.root).result, result)
        self.assertEqual(list(self.root.glob(".manifest.*.tmp")), [])

    def test_audit_failure_and_fsync_or_publication_failure_leave_no_success(self):
        for step in ("audit", "fsync", "link"):
            root, manifest = self.bundle()
            (root / "manifest.json").unlink()
            if step == "audit":
                (root / "tokenizer/chat_template.jinja").write_text("mismatch")
            target = "trainer.run_storage.os.fsync" if step == "fsync" else "trainer.run_storage.os.link"
            context = patch(target, side_effect=OSError("controlled disk failure")) if step != "audit" else nullcontext()
            with context, self.assertRaises(TrainingError) as error:
                self.finish_call(root, manifest)
            self.assertEqual(error.exception.failure.code, "ARTIFACT_WRITE_FAILED")
            self.assertFalse((root / "manifest.json").exists())
            self.assertEqual(list(root.glob(".manifest.*.tmp")), [])

    def test_existing_marker_is_preserved(self):
        before = (self.root / "manifest.json").read_bytes()
        with self.assertRaises(TrainingError):
            self.finish_call()
        self.assertEqual((self.root / "manifest.json").read_bytes(), before)

    def test_publication_race_never_overwrites_foreign_marker(self):
        (self.root / "manifest.json").unlink()
        def raced_link(source, target):
            target.write_text("foreign marker")
            raise FileExistsError()
        with patch("trainer.run_storage.os.link", side_effect=raced_link), self.assertRaises(TrainingError):
            self.finish_call()
        self.assertEqual((self.root / "manifest.json").read_text(), "foreign marker")

    def test_cleanup_failure_rolls_back_success_marker(self):
        (self.root / "manifest.json").unlink()
        original = Path.unlink
        failed = False
        def unlink(path, *args, **kwargs):
            nonlocal failed
            if path.name.startswith(".manifest.") and not failed:
                failed = True
                raise PermissionError("controlled cleanup failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink), self.assertRaises(TrainingError):
            self.finish_call()
        self.assertFalse((self.root / "manifest.json").exists())

    def test_unrecoverable_cleanup_cannot_leave_valid_success(self):
        (self.root / "manifest.json").unlink()
        with patch.object(Path, "unlink", side_effect=PermissionError("controlled read-only directory")), self.assertRaises(TrainingError):
            self.finish_call()
        # Both staging and canonical names remain linked and cannot pass audit.
        self.assertEqual((self.root / "manifest.json").stat().st_nlink, 2)
        self.assert_invalid()

    def test_interrupt_during_publication_rolls_back_marker(self):
        (self.root / "manifest.json").unlink()
        original = Path.unlink
        interrupted = False
        def unlink(path, *args, **kwargs):
            nonlocal interrupted
            if path.name.startswith(".manifest.") and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink), self.assertRaises(KeyboardInterrupt):
            self.finish_call()
        self.assertFalse((self.root / "manifest.json").exists())
        self.assertEqual(list(self.root.glob(".manifest.*.tmp")), [])

    def test_cli_import_and_audit_need_no_torch_numpy_or_hf(self):
        code = '''
import importlib.abc,sys,runpy
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','huggingface_hub','datasets','peft','trl','accelerate'}:
            raise AssertionError('Unexpected ML dependency')
sys.meta_path.insert(0,Block())
sys.argv=['check_training_artifacts.py','--task-id',sys.argv[1],'--data-dir',sys.argv[2]]
runpy.run_path('scripts/check_training_artifacts.py',run_name='__main__')
'''
        run = subprocess.run([sys.executable, "-c", code, str(self.manifest.task_id), str(self.parent)],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(json.loads(run.stdout)["reload_verified"])


if __name__ == "__main__":
    unittest.main()
