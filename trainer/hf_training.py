"""Single-GPU Hugging Face execution, imported only when train() is called."""

import gc
import hashlib

from trainer.contracts import TrainingError
from trainer.events import fail
from trainer.preprocessing import InstructionCollator


def execute(request, cached, tokenizer, prepared, metrics, log):
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model, get_peft_model_state_dict
        from safetensors.torch import load_file
        from transformers import AutoModelForCausalLM, Trainer, TrainerCallback, TrainingArguments, set_seed
        from transformers.trainer_callback import PrinterCallback
    except ImportError as error:
        fail("MODEL_LOAD_FAILED", "model_loading", "请先 uv sync --locked --extra training 安装训练依赖。", cause=error)

    model = trainer = trainable = frozen = initial = saved = current = parameter = None
    stage = "model_loading"
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            fail("MODEL_LOAD_FAILED", stage, "训练要求恰好一个可见 CUDA GPU，请配置 CUDA_VISIBLE_DEVICES。")
        if request.runtime.precision == "bf16" and not torch.cuda.is_bf16_supported():
            fail("MODEL_LOAD_FAILED", stage, "当前 GPU 不支持请求的 BF16 精度。")
        torch.cuda.set_device(0)
        torch.cuda.reset_peak_memory_stats(0)
        set_seed(request.config.seed)
        model = AutoModelForCausalLM.from_pretrained(
            str(cached.snapshot_dir), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.bfloat16 if request.runtime.precision == "bf16" else torch.float32,
            token=False,
        )
        model.config.use_cache = False
        model.config._name_or_path = request.base_model
        model.name_or_path = request.base_model
        available = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
        if not set(request.config.target_modules).issubset(available):
            fail("INVALID_REQUEST", "preflight", "请求的 LoRA target_modules 在基础模型中不存在。")
        config = request.config
        model = get_peft_model(model, LoraConfig(
            task_type=TaskType.CAUSAL_LM, r=config.lora_r, lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout, target_modules=config.target_modules, bias="none",
        ), revision=request.model_revision)
        model.to("cuda:0")
        trainable = {name: parameter for name, parameter in model.named_parameters() if parameter.requires_grad}
        frozen = {name: parameter for name, parameter in model.named_parameters() if not parameter.requires_grad}
        if (not trainable or not frozen or any(".lora_" not in name for name in trainable)
                or any(".lora_" in name for name in frozen)):
            fail("TRAINING_FAILED", "training", "LoRA 可训练参数或基础参数冻结检查失败。")
        initial = {name: parameter.detach().cpu().clone() for name, parameter in trainable.items()}

        def base_digest():
            digest = hashlib.sha256()
            for name, tensor in frozen.items():
                digest.update(name.encode())
                digest.update(str((tuple(tensor.shape), tensor.dtype)).encode())
                digest.update(tensor.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes())
            return digest.hexdigest()

        before = base_digest()
        total_parameters = sum(parameter.numel() for parameter in model.parameters())
        trainable_parameters = sum(parameter.numel() for parameter in trainable.values())
        log("parameters", total_parameters=total_parameters, trainable_parameters=trainable_parameters,
            target_modules=config.target_modules, base_sha256_before=before)

        class FiniteTrainer(Trainer):
            def training_step(self, *args, **kwargs):
                loss = super().training_step(*args, **kwargs)
                if not torch.isfinite(loss).all().item():
                    fail("TRAINING_FAILED", "training", "训练出现非有限 Loss。")
                return loss

        class ProgressCallback(TrainerCallback):
            def on_train_begin(self, args, state, control, **kwargs):
                log("training", total_steps=state.max_steps, gradient_accumulation_steps=args.gradient_accumulation_steps)

            def on_pre_optimizer_step(self, args, state, control, **kwargs):
                for parameter in trainable.values():
                    if parameter.grad is not None and not torch.isfinite(parameter.grad).all().item():
                        fail("TRAINING_FAILED", "training", "训练出现非有限 LoRA 梯度。")
                if any(parameter.grad is not None for parameter in frozen.values()):
                    fail("TRAINING_FAILED", "training", "冻结的基础参数出现梯度。")

            def on_step_end(self, args, state, control, **kwargs):
                if state.global_step == state.max_steps:
                    control.should_log = True

            def on_log(self, args, state, control, logs=None, optimizer=None, **kwargs):
                logs = logs or {}
                kind = "eval" if "eval_loss" in logs else "train" if "loss" in logs else None
                if kind is None:
                    return  # aggregate train_runtime/train_loss is not a new step
                # v1 records the optimizer LR at event time (after scheduler.step).
                # HF's train log may instead carry the LR used for that update.
                learning_rate = optimizer.param_groups[0]["lr"]
                event = metrics.emit(kind=kind, step=state.global_step, total_steps=state.max_steps,
                    loss=float(logs["eval_loss" if kind == "eval" else "loss"]),
                    learning_rate=float(learning_rate), epoch=float(state.epoch))
                log("metric", **event.model_dump(mode="json"), framework_learning_rate=logs.get("learning_rate"))

        stage = "training"
        args = TrainingArguments(
            output_dir=str(request.output_dir / "checkpoints"),
            per_device_train_batch_size=config.per_device_train_batch_size,
            per_device_eval_batch_size=1, gradient_accumulation_steps=config.gradient_accumulation_steps,
            learning_rate=config.learning_rate, num_train_epochs=config.num_train_epochs,
            max_steps=request.runtime.max_steps if request.runtime.max_steps is not None else -1,
            logging_strategy="steps", logging_steps=config.logging_steps, logging_nan_inf_filter=False,
            eval_strategy="steps" if prepared.validation else "no", eval_steps=config.logging_steps,
            save_strategy="no", report_to=[], disable_tqdm=True, seed=config.seed, data_seed=config.seed,
            bf16=request.runtime.precision == "bf16", fp16=False, tf32=False,
            lr_scheduler_type="linear", warmup_steps=0, warmup_ratio=0.0, weight_decay=0.0,
            max_grad_norm=1.0, gradient_checkpointing=False, auto_find_batch_size=False, dataloader_drop_last=False,
            optim="adamw_torch", dataloader_num_workers=0, dataloader_pin_memory=False,
            remove_unused_columns=False, label_names=["labels"],
        )
        trainer = FiniteTrainer(
            model=model, args=args, train_dataset=Dataset.from_list([sample.as_feature() for sample in prepared.train.samples]),
            eval_dataset=Dataset.from_list([sample.as_feature() for sample in prepared.validation.samples]) if prepared.validation else None,
            data_collator=InstructionCollator(tokenizer.pad_token_id), callbacks=[ProgressCallback()],
        )
        trainer.remove_callback(PrinterCallback)
        trainer.train()
        if prepared.validation and ("eval" not in metrics.last or metrics.last["eval"].step != trainer.state.global_step):
            trainer.evaluate()
        final = metrics.last.get("train")
        if final is None or final.step != trainer.state.max_steps or trainer.state.global_step != trainer.state.max_steps:
            fail("TRAINING_FAILED", stage, "训练未达到计划优化器步数或缺少最终指标。")
        changed = sum(not torch.equal(initial[name], parameter.detach().cpu()) for name, parameter in trainable.items())
        after = base_digest()
        if not changed or before != after:
            fail("TRAINING_FAILED", stage, "LoRA 未发生更新或冻结的基础权重发生变化。")
        log("parameter_verification", changed_lora_tensors=changed, lora_tensor_count=len(trainable),
            base_sha256_before=before, base_sha256_after=after, base_unchanged=before == after)

        stage = "saving"
        log(stage)
        model.save_pretrained(request.output_dir / "adapter", safe_serialization=True, save_embedding_layers=False)
        tokenizer.save_pretrained(request.output_dir / "tokenizer")
        saved = load_file(str(request.output_dir / "adapter/adapter_model.safetensors"), device="cpu")
        current = get_peft_model_state_dict(model, save_embedding_layers=False)
        if set(saved) != set(current) or any(not torch.equal(saved[key], current[key].detach().cpu()) for key in saved):
            fail("INVALID_ARTIFACT", stage, "保存的 Adapter 张量与已训练参数不一致。")
        current = None
        torch.cuda.synchronize()
        return dict(completed_steps=trainer.state.global_step, total_steps=trainer.state.max_steps,
                    final_loss=final.loss, eval_loss=metrics.last["eval"].loss if "eval" in metrics.last else None,
                    peak_memory_allocated_bytes=torch.cuda.max_memory_allocated(0),
                    trainable_parameters=trainable_parameters, total_parameters=total_parameters)
    except TrainingError:
        raise
    except torch.cuda.OutOfMemoryError as error:
        fail("CUDA_OUT_OF_MEMORY", stage, "CUDA 显存不足；本次训练失败，未自动降低配置。", cause=error)
    except Exception as error:
        code = "MODEL_LOAD_FAILED" if stage == "model_loading" else "ARTIFACT_WRITE_FAILED" if stage == "saving" else "TRAINING_FAILED"
        fail(code, stage, f"训练执行失败（{type(error).__name__}）。", cause=error)
    finally:
        trainer = model = trainable = frozen = initial = saved = current = parameter = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
