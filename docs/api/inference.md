# M5 在线推理接口草案

版本 0.1，待 A/B 评审。以现有[需求](../requirements.md)、[任务接口](tasks.md)和[独立重载入口](../../trainer/reload.py)为基础。首版在网页上选择已完成的训练任务，提交同一提示词，取得 Adapter 回答或基础模型与 Adapter 的对照回答。

## 请求

`POST /api/v1/inference` 接收 UTF-8 `application/json`。浏览器等待一次 JSON 响应，服务端把实际模型加载与生成交给现有单 GPU Worker。

| 字段 | 类型与默认值 | 约束 |
| --- | --- | --- |
| `task_id` | UUIDv4 字符串，必填 | 对应 SQL 中已完成且产物审计通过的训练任务 |
| `prompt` | 字符串，必填 | 去掉首尾空白后须有内容，保留原文本用于生成，最多 8192 个 Unicode 字符 |
| `max_new_tokens` | 整数，默认 128 | 每份回答 1–256 个新 token，布尔值、浮点数和字符串均拒绝 |
| `mode` | `adapter` 或 `compare`，默认 `adapter` | `adapter` 返回微调回答，`compare` 同时返回基础模型与微调回答 |

正文上限 64 KiB，沿用任务 JSON 的媒体类型、重复键、非有限数字、查询参数和分块正文限制。未知字段拒绝。服务端从训练任务快照解析模型、revision、tokenizer、精度和产物目录。模板化后输入最多 2048 token，超限返回字段错误。文本上限与生成上限沿用现有重载逻辑。

```json
{
  "task_id": "992aa53a-a246-45de-a8f1-4d4164d9b42e",
  "prompt": "用两句话解释云计算中的弹性伸缩。",
  "max_new_tokens": 128,
  "mode": "compare"
}
```

## 成功响应

`200 OK` 返回下列 JSON，响应头沿用服务端 `X-Request-ID`。示例文本和 token 数用于前端联调。

```json
{
  "task_id": "992aa53a-a246-45de-a8f1-4d4164d9b42e",
  "mode": "compare",
  "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
  "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
  "input_tokens": 31,
  "max_new_tokens": 128,
  "base": {
    "generated_text": "弹性伸缩会根据负载调整资源数量。",
    "generated_tokens": 12
  },
  "adapter": {
    "generated_text": "弹性伸缩根据业务负载增加或减少计算资源，帮助维持服务性能。流量下降时可以回收多余实例，降低成本。",
    "generated_tokens": 28
  }
}
```

`adapter` 为必填对象。模式为 `adapter` 时 `base` 固定为 `null`。两种模式均返回实际生成的文本和新 token 数。模式为 `compare` 时两份结果使用相同基础模型 revision、tokenizer、聊天模板、输入和生成参数，采用贪心解码。在一次 GPU 占用内顺序生成两份回答，均成功后返回 200。任一生成失败时返回统一错误。

## 错误

沿用 [ErrorResponse](tasks.md#错误和派发不确定性) 的 `error.code/message/details/details_truncated/request_id` 和 `X-Request-ID`。前端根据错误码决定行为。

| HTTP / code | 触发条件 | 页面行为 |
| --- | --- | --- |
| 400 / `HTTP_ERROR` | Content-Length 格式不合法 | 显示请求错误 |
| 404 / `TASK_NOT_FOUND` | 训练任务不存在 | 刷新任务列表 |
| 409 / `ARTIFACT_NOT_READY` | 训练任务还未完成 | 提示选择已完成任务 |
| 409 / `GPU_BUSY` | 训练正在执行或等待，或已有推理占用或预留 GPU | 提示稍后手动重试 |
| 413 / `REQUEST_TOO_LARGE` | JSON 正文超过 64 KiB | 提示缩短提示词 |
| 415 / `UNSUPPORTED_MEDIA_TYPE` | 请求媒体类型或编码不受支持 | 显示请求错误 |
| 422 / `VALIDATION_ERROR` | JSON、字段、查询参数或模板化后的输入长度不合规 | 展示相应字段提示 |
| 500 / `INVALID_ARTIFACT` | 完成记录与产物缺失、校验失败或版本不一致 | 提示检查训练产物并保留请求编号 |
| 500 / `INFERENCE_FAILED` | 模型加载或生成失败，或已领取的推理因 Worker 退出而中断 | 展示安全错误说明并保留请求编号 |
| 500 / `INTERNAL_ERROR` | 未分类服务异常 | 展示统一错误并保留请求编号 |
| 503 / `MODEL_NOT_CACHED` | 目标 revision 的离线模型缓存缺失或不可用 | 提示准备该版本的缓存 |
| 503 / `DATABASE_UNAVAILABLE` | 状态读写不可用 | 保留用户输入，提示服务暂不可用 |
| 503 / `INFERENCE_UNAVAILABLE` | 派发失败或确认丢失后，服务端终止了尚未领取的请求，或 Worker 未在领取时限内启动请求 | 保留用户输入，提示服务暂不可用 |
| 504 / `INFERENCE_TIMEOUT` | 已领取的推理超过本次 HTTP 等待预算 | 保留用户输入，提示稍后手动重试 |

忙碌示例：

```json
{
  "error": {
    "code": "GPU_BUSY",
    "message": "GPU 正在处理训练或推理，请稍后重试。",
    "details": [],
    "details_truncated": false,
    "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df"
  }
}
```

## 调度与生命周期

首版使用同一 Celery 队列和唯一的 `solo` Worker 串行执行训练和推理。API 只负责请求校验、状态读写与派发。使用内部推理请求 ID 关联消息与短期结果，Celery 消息只携带该 ID。API 通过短事务读取结果，等待期间释放数据库连接。

1. **预留。** API 先校验训练任务是否完成，再在同一 SQLite 写事务中检查 `PENDING/QUEUED/RUNNING` 训练和有效的推理占用。空闲时写入待领取推理请求及其截止时间。有等待训练或有效占用时返回 `GPU_BUSY`。训练提交可继续接受。
2. **领取。** Worker 通过条件更新领取未过期的推理请求，重复消息和过期消息退出。训练先进入 Worker 时，训练领取与撤销尚未领取的推理预留在同一写事务完成，等待中的 API 返回 `GPU_BUSY`。推理领取时也在同一事务检查是否出现待执行训练，训练优先。已开始的推理结束后，后续训练由同一 Worker 领取。
3. **执行。** 读取训练的完成快照，复用已完成产物投影与现有 CPU 审计，核对任务身份、revision、manifest 和 Adapter 内容，从固定的本地缓存加载。训练和推理由同一 Worker 顺序执行，`worker.lock` 继续用于进程单实例和停机对账。
4. **截止。** 草案建议 HTTP 等待预算为 90 秒，从服务端接收请求起算，浏览器超时为 120 秒。未领取请求的派发和启动预算至多 10 秒，且受总预算约束。派发确认丢失或领取超时后尝试原子终止仍待领取的记录，迟到消息按状态和截止时间退出。若 Worker 已领取，则继续按原请求等待。API 与 Worker 均按内部请求 ID 关联结果，客户端保留手动重试入口。
5. **退出。** 生成过程中检查截止时间与取消标记，收到断连时原子终止仍待领取的请求，已领取的请求只记录取消意图。实际 GPU 清理完成后 Worker 才释放运行占用。HTTP 超时和浏览器取消均可能先于 GPU 释放。Worker 异常退出后，后继 Worker 取得同一实例锁并核对遗留记录，再将失联请求标记为失败。尚在运行的请求即使超过截止时间，仍计入 GPU 占用。

实现建议用短期 SQLite 推理记录保存内部 ID、状态、截止时间、提示词和结果，复用现有写事务与错误投影。具体表结构、迁移与清理由 A 在实现评审中确定。终态后的提示词及回答建议最多保留 10 分钟，以便请求读取结果，之后清理。HTTP 响应使用 `Cache-Control: no-store`，日志记录请求编号、任务编号、耗时和错误码。

## A/B 接入与验收

| 负责人 | 任务 | 交付 |
| --- | --- | --- |
| A | 明确请求和响应类型、实现 HTTP 路由及错误映射，接通完成产物审计、GPU 调度与生成 | 可用的推理 API 和实际路由导出的 OpenAPI |
| B | 评审字段和状态，复用现有 [InferencePanel](../../frontend/src/components/InferencePanel.vue)，接入已完成任务选择、模式选择、等待、取消与对照展示 | 按响应样例展示结果，针对 `GPU_BUSY` 与 `ARTIFACT_NOT_READY` 分别提示，切任务后迟到响应保持归属于原请求 |
| A+B | 确认契约版本后并行开发，在现有 RTX 3060 环境联调 | 用已审计 Adapter 完成真实生成与对照，在训练期间获得明确忙碌反馈，GPU 空闲后重试成功，取消或超时后可继续使用 |

页面以运行时 OpenAPI 的 `POST /api/v1/inference` 为接入条件。评审期间可依据本页示例核对数据结构和交互。B 优先确认三个问题：是否接受 `mode=compare` 与 `base/adapter` 结构，现有页面是否能表达两种 409，120 秒等待与切任务取消是否符合体验。

正式效果实验在候选语料私下交接、交叉审核和按问答族划分后独立执行。双人审核及部署回归沿用现有项目计划。当前本地实测范围见 [M4 验收交接](../testing/laptop-3060-handoff-2026-11-13.md)。
