"""Independent real-model GPU forward probe. Not a training or inference service."""

import gc
import hashlib
from importlib.metadata import version
import time

from trainer.contracts import RuntimeOptions, TrainingError
from trainer.model_cache import _fail, verify_model_cache


def probe_model_gpu(cache_dir, revision, *, precision="bf16"):
    cached = verify_model_cache(cache_dir, revision)
    options = RuntimeOptions(precision=precision)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        _fail("MODEL_LOAD_FAILED", "GPU 检查需要 training extra。", cause=error)
    if not torch.cuda.is_available():
        _fail("MODEL_LOAD_FAILED", "CUDA 不可用，请检查驱动与 WSL GPU 访问。")
    if options.precision == "bf16" and not torch.cuda.is_bf16_supported():
        _fail("MODEL_LOAD_FAILED", "当前 GPU 不支持 BF16；可显式选择 fp32，不自动降配。")
    model = tokenizer = inputs = outputs = None
    started = time.perf_counter()
    try:
        torch.cuda.reset_peak_memory_stats(0)
        tokenizer = AutoTokenizer.from_pretrained(str(cached.snapshot_dir), local_files_only=True,
                                                   trust_remote_code=False, token=False)
        if hashlib.sha256(tokenizer.chat_template.encode("utf-8")).hexdigest() != cached.manifest.chat_template_sha256:
            _fail("MODEL_LOAD_FAILED", "加载后的 tokenizer 模板与固定缓存不一致。")
        dtype = torch.bfloat16 if precision == "bf16" else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            str(cached.snapshot_dir), local_files_only=True, trust_remote_code=False,
            token=False, use_safetensors=True, dtype=dtype, attn_implementation="sdpa",
        ).to("cuda:0").eval()
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": "回复一个中文词语。"}],
            tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt",
        ).to("cuda:0")
        with torch.inference_mode():
            outputs = model(**inputs, use_cache=False)
        torch.cuda.synchronize(0)
        if outputs.logits.device.type != "cuda" or not torch.isfinite(outputs.logits).all().item():
            _fail("MODEL_LOAD_FAILED", "真实模型 GPU logits 异常。")
        return {**cached.summary(), "status": "gpu_forward_verified", "precision": precision,
                "gpu_name": torch.cuda.get_device_name(0), "cuda_runtime": torch.version.cuda,
                "torch_version": torch.__version__, "transformers_version": version("transformers"),
                "huggingface_hub_version": version("huggingface-hub"),
                "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
                "input_tokens": inputs["input_ids"].shape[-1], "logits_shape": list(outputs.logits.shape),
                "logits_dtype": str(outputs.logits.dtype), "logits_finite": True,
                "peak_memory_allocated_bytes": torch.cuda.max_memory_allocated(0),
                "elapsed_seconds": time.perf_counter() - started}
    except torch.OutOfMemoryError as error:
        _fail("CUDA_OUT_OF_MEMORY", "真实模型加载或前向时显存不足。", cause=error)
    except TrainingError:
        raise
    except Exception as error:
        _fail("MODEL_LOAD_FAILED", f"真实模型加载/前向失败（{type(error).__name__}）。", cause=error)
    finally:
        model = tokenizer = inputs = outputs = None
        gc.collect()
        torch.cuda.empty_cache()
