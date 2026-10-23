"""Independent offline Adapter acceptance; CPU import does not load ML libraries."""

from datetime import datetime, timezone
import gc
import hashlib
import os
import time

from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import TrainingError
from trainer.events import fail
from trainer.model_cache import verify_model_cache


def validate_generation(prompt, input_text, max_new_tokens):
    if (not isinstance(prompt, str) or not prompt.strip() or not isinstance(input_text, str)
            or len(prompt) + len(input_text) > 8192 or type(max_new_tokens) is not int
            or not 1 <= max_new_tokens <= 256):
        fail("INVALID_REQUEST", "preflight", "开发提示词须非空、总长度不超过 8192 字符，生成长度须为 1–256 整数。")


def reload_and_generate(output_dir, cache_dir, *, prompt, input_text="", max_new_tokens=128,
                        outputs_root=None, expected_task_id=None, expected_revision=None):
    validate_generation(prompt, input_text, max_new_tokens)
    verified = verify_training_artifacts(output_dir, outputs_root=outputs_root,
        expected_task_id=expected_task_id, expected_revision=expected_revision)
    cached = verify_model_cache(cache_dir, verified.manifest.model_revision)
    if cached.manifest.chat_template_sha256 != verified.manifest.chat_template_sha256:
        fail("INVALID_ARTIFACT", "reloading", "产物模板与固定基础模型缓存不一致。")
    if os.environ.get("WORLD_SIZE", "1") != "1":
        fail("INVALID_REQUEST", "preflight", "重载验收仅支持单进程单 GPU。")
    return _generate(verified, cached, prompt, input_text, max_new_tokens)


def _generate(verified, cached, prompt, input_text, max_new_tokens):
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig, LogitsProcessor
        from peft import PeftModel, get_peft_model_state_dict
        from safetensors.torch import load_file
    except ImportError as error:
        fail("MODEL_LOAD_FAILED", "reloading", "请先 uv sync --locked --extra training。", cause=error)
    model = base = tokens = generated = current = saved = None
    started = time.monotonic()
    manifest, result = verified.manifest, verified.result
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            fail("MODEL_LOAD_FAILED", "reloading", "重载需要恰好一个可见 CUDA GPU。")
        if manifest.runtime.precision == "bf16" and not torch.cuda.is_bf16_supported():
            fail("MODEL_LOAD_FAILED", "reloading", "当前 GPU 不支持产物记录的 BF16。")
        torch.cuda.set_device(0)
        torch.cuda.reset_peak_memory_stats(0)
        tokenizer = AutoTokenizer.from_pretrained(str(result.tokenizer_dir), local_files_only=True, trust_remote_code=False)
        original = AutoTokenizer.from_pretrained(str(cached.snapshot_dir), local_files_only=True, trust_remote_code=False)
        if (not tokenizer.is_fast or tokenizer.get_vocab() != original.get_vocab()
                or tokenizer.eos_token_id != original.eos_token_id or tokenizer.pad_token_id != original.pad_token_id
                or tokenizer.chat_template != original.chat_template):
            fail("INVALID_ARTIFACT", "reloading", "保存的 tokenizer 与固定基础缓存不匹配。")
        messages = [{"role": "user", "content": prompt + ("\n\n" + input_text if input_text else "")}]
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               return_tensors="pt", return_dict=True)
        if tokens["input_ids"].shape[1] > 2048:
            fail("INVALID_REQUEST", "preflight", "模板化提示词超过 2048 token；不自动截断。")
        base = AutoModelForCausalLM.from_pretrained(str(cached.snapshot_dir), local_files_only=True,
            trust_remote_code=False, use_safetensors=True,
            dtype=torch.bfloat16 if manifest.runtime.precision == "bf16" else torch.float32)
        model = PeftModel.from_pretrained(base, str(result.adapter_dir), is_trainable=False,
                                          local_files_only=True, autocast_adapter_dtype=True)
        current = get_peft_model_state_dict(model, save_embedding_layers=False)
        saved = load_file(str(result.adapter_dir / "adapter_model.safetensors"), device="cpu")
        if (set(current) != set(saved) or any(not torch.equal(current[key].detach().cpu(), saved[key]) for key in saved)
                or model.active_adapters != ["default"] or any(p.requires_grad for p in model.parameters())):
            fail("INVALID_ARTIFACT", "reloading", "实际加载的 Adapter 张量、激活状态或冻结状态不符。")
        current = saved = None
        model.to("cuda:0").eval()
        tokens = {key: value.to("cuda:0") for key, value in tokens.items()}
        class FiniteScores(LogitsProcessor):
            def __call__(self, input_ids, scores):
                if not torch.isfinite(scores).all().item():
                    fail("MODEL_LOAD_FAILED", "reloading", "生成出现非有限 logits。")
                return scores
        generation = GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=max_new_tokens,
            eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id, use_cache=True)
        with torch.inference_mode():
            generated = model.generate(**tokens, generation_config=generation, logits_processor=[FiniteScores()])
        torch.cuda.synchronize()
        length = tokens["input_ids"].shape[1]
        ids = generated[0, length:].tolist()
        if not ids or len(ids) > max_new_tokens:
            fail("MODEL_LOAD_FAILED", "reloading", "生成 token 数无效。")
        return {"status": "reload_verified", "contract_version": "1.0.0", "task_id": str(manifest.task_id),
            "model_revision": manifest.model_revision, "manifest_sha256": sha256(result.manifest_path),
            "adapter_sha256": sha256(result.adapter_dir / "adapter_model.safetensors"),
            "pid": os.getpid(), "recorded_at": datetime.now(timezone.utc).isoformat(),
            "precision": manifest.runtime.precision, "input_tokens": length, "generated_tokens": len(ids),
            "max_new_tokens": max_new_tokens, "do_sample": False, "adapter_tensor_count": verified.tensor_count,
            "adapter_weights_matched": True, "review_status": manifest.train_dataset.review_status,
            "prompt_sha256": hashlib.sha256(messages[0]["content"].encode()).hexdigest(),
            "response": tokenizer.decode(ids, skip_special_tokens=True),
            "elapsed_seconds": time.monotonic() - started,
            "peak_memory_allocated_bytes": torch.cuda.max_memory_allocated(0)}
    except TrainingError:
        raise
    except torch.cuda.OutOfMemoryError as error:
        fail("CUDA_OUT_OF_MEMORY", "reloading", "重载或生成显存不足；未自动降配。", cause=error)
    except Exception as error:
        fail("MODEL_LOAD_FAILED", "reloading", f"模型重载或生成失败（{type(error).__name__}）。", cause=error)
    finally:
        model = base = tokens = generated = current = saved = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
