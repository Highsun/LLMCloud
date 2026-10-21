export const defaultConfig = {
  lora_r: 8,
  lora_alpha: 16,
  lora_dropout: 0.05,
  target_modules: ["q_proj", "v_proj"],
  learning_rate: 0.0002,
  num_train_epochs: 1,
  per_device_train_batch_size: 1,
  gradient_accumulation_steps: 8,
  max_seq_length: 512,
  logging_steps: 1,
  seed: 42,
};
export const configFields = [
  {
    key: "lora_r",
    label: "LoRA Rank",
    hint: "低秩矩阵维度",
    min: 1,
    max: 64,
    step: 1,
    group: "lora",
  },
  {
    key: "lora_alpha",
    label: "LoRA Alpha",
    hint: "适配权重缩放",
    min: 1,
    max: 128,
    step: 1,
    group: "lora",
  },
  {
    key: "lora_dropout",
    label: "Dropout",
    hint: "范围 0 ≤ p < 1",
    min: 0,
    max: 1,
    exclusiveMax: true,
    step: "any",
    group: "lora",
  },
  {
    key: "learning_rate",
    label: "学习率",
    hint: "大于 0，最大 0.01",
    min: 0,
    exclusiveMin: true,
    max: 0.01,
    step: "any",
    group: "train",
  },
  {
    key: "num_train_epochs",
    label: "训练轮数",
    hint: "Epochs · 1–10",
    min: 1,
    max: 10,
    step: 1,
    group: "train",
  },
  {
    key: "per_device_train_batch_size",
    label: "批次大小",
    hint: "每设备 · 1–4",
    min: 1,
    max: 4,
    step: 1,
    group: "train",
  },
  {
    key: "gradient_accumulation_steps",
    label: "梯度累积",
    hint: "累积步数 · 1–64",
    min: 1,
    max: 64,
    step: 1,
    group: "train",
  },
  {
    key: "max_seq_length",
    label: "最大序列长度",
    hint: "Tokens · 64–2048",
    min: 64,
    max: 2048,
    step: 1,
    group: "train",
  },
  {
    key: "logging_steps",
    label: "日志间隔",
    hint: "每 N 步记录 · 1–100",
    min: 1,
    max: 100,
    step: 1,
    group: "train",
  },
  {
    key: "seed",
    label: "随机种子",
    hint: "非负整数",
    min: 0,
    step: 1,
    group: "train",
  },
];
export function validateConfig(config) {
  const errors = [];
  for (const field of configFields) {
    const value = config[field.key];
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      value < field.min ||
      (field.exclusiveMin && value === field.min) ||
      (field.max !== undefined &&
        (value > field.max || (field.exclusiveMax && value === field.max))) ||
      (field.step === 1 && !Number.isSafeInteger(value))
    )
      errors.push(`${field.label}不在允许范围内。`);
  }
  if (
    !Array.isArray(config.target_modules) ||
    !config.target_modules.length ||
    config.target_modules.some(
      (item) => typeof item !== "string" || !item.trim(),
    )
  )
    errors.push("请至少选择一个目标模块。");
  return errors;
}
