# M4 观测与 Adapter 下载契约 1.0.0

更新：2026-11-06。M4-01～06 已交付并审查收录，B 的消费者核对及观测/下载页面已在 ef1fe06 合入，真实 OpenAPI 包含三个 GET；07 GPU/双方人工待执行。本契约字段/版本未变；类型校验不能代替文件/授权/审计，正式可调用能力以真实 app.openapi() 为准。

实现入口：[CPU Schema](../../backend/app/models/observability_schemas.py)、[常量与日志字段策略](../../backend/app/core/observability_contract.py)、[内部完成 DTO/Protocol](../../backend/app/core/observability_protocols.py)。生成物为 [JSON Schema](../contracts/observability.schema.json)、[mock 样例索引](../examples/observability/index.json) 和 [样例说明](../examples/observability/README.md)。原 TaskCreate/TrainingConfig/TaskDetail、M2 事件与 Worker 五方法不变；观测契约独立版本从 1.0.0 起步。

## 共同约定与执行边界

成功直接返回下述资源，失败沿用 ErrorResponse，包含真实 HTTP 状态和 X-Request-ID；错误没有另加 task_id，调用方已经持有路径中的任务 ID。所有 ID 为 UUIDv4；时间为 RFC 3339 并归一 UTC，输出 Z。同一请求中的 task_status 是读 SQL 时的快照，不能用迟到的观测状态覆盖更新的 TaskDetail。

类型是 frozen、拒绝额外字段并在重新校验实例时验证嵌套值。计数/偏移为严格整数，布尔字段不接受 0/1 或字符串；响应不接受整数的字符串表示。查询整数可接受 ASCII 十进制字符串（允许前导零），拒绝小数/指数/正负号/空白/Unicode 数字/Python bool 或 float。查询不接受 after_step、路径、归属或未知参数。M4-02 HTTP 适配层从 multi_items 拒绝重复原始查询项，复用原统一错误、CORS 和 X-Request-ID；成功响应设置 Cache-Control: no-store。阻塞 SQL/文件访问在线程池执行。

| 层次 | CPU 类型检查 | 执行层检查 |
| --- | --- | --- |
| 查询 | 值/默认值/上限、cursor 与 source_id 配对、额外字段 | 02 已检查原始重复项、任务存在、游标文件身份/真实换行边界 |
| 响应 | ID、字段类型、局部记录顺序/计数/游标结构、日志编码/响应字节上限 | 02 已检查读预算、文件缺失语义、源内容/JSON/路径安全、直接前驱与本页顺序 |
| 完成 DTO/下载头 | 输出键和 UUID 一致、固定 max_steps/summary、一致安全文件名 | 03 已检查 SQL COMPLETED、快照/哈希/实际文件、审计、ZIP 和资源清理；06 实际 HTTP/浏览器复核通过 |

## 指标：GET /api/v1/tasks/{task_id}/metrics

查询模型 MetricsQuery，成功体 MetricsPage。接口已注册并从真实应用导出到 [任务 OpenAPI](tasks.openapi.json)。

| 参数 | 类型/默认值 | 边界 |
| --- | --- | --- |
| cursor | integer，0 | 0～9007199254740991，表示上次完整记录换行之后的字节位置 |
| source_id | string 或省略 | 64 位小写 hex；cursor>0 时必填，cursor=0 可带上已有源身份 |
| limit | integer，200 | 1～1000 条 |

source_id 是不透明的文件版本标识，不是授权令牌；必须使用服务返回值，不按大小/mtime 自行计算，不使用 mock 文件中的固定值。正常追加保持同一身份；文件替换、缩短到游标之前或游标非行边界返回 METRICS_CURSOR_INVALID。首版不承诺识别任意同 inode 历史改写，成功交付的完整性由原产物审计保证。

| MetricsPage 字段 | 类型/含义 |
| --- | --- |
| contract_version | 固定 1.0.0 |
| task_id / task_status | UUIDv4 / 五种 TaskStatus |
| source_state | ready 或 not_created |
| source_id | ready 时 64 位小写 hex；not_created 时 null |
| items | 至多 1000 个 MetricRecord；TrainingProgress 全部原字段外加 offset |
| next_cursor | 非负安全整数，最后返回完整行之后的位置；没新完整记录则保持请求 cursor |
| has_more | 当前扫描快照中还有完整记录可取；空数组时必须 false |
| tail_incomplete | 观察到不完整尾行；不将其返回为有效点或推进游标 |

MetricRecord 保留 contract_version/kind/step/total_steps/loss/learning_rate/epoch/recorded_at；新增 offset 是该源文件完整行的起始字节，0 也是有效记录身份。按 (source_id, offset) 合并，不能按 step 合并。记录按 offset 严格递增，同一页按 (step, train 在 eval 前) 排序且 total_steps 一致；页首允许是 eval，因为对应 train 可能已在上一页。next_cursor 必须大于最后一条的 offset；类型并不知道源行字节数，M4-02 负责真正的偏移关系。

M4-02 服务保证 items 数量不超过本次请求 limit、task_id 匹配路径、source_id/next_cursor 与输入关联；这些请求相关条件不能由孤立的响应类型证明。源身份由任务 UUID 与已打开文件的 device/inode 摘要生成，正常追加不改变；不能将其他任务的游标作为本任务续读凭据。

ready 的空文件、等待新行的空页、已取完的 COMPLETED 空页都是合法情况；后两者可有非零 next_cursor。not_created 必须 items=[]、source_id=null、next_cursor=0、has_more=false、tail_incomplete=false，不能用于 COMPLETED。服务只在无 source_id、cursor=0、数据库 current_step=0 且非 COMPLETED 时允许自然缺文件；携带旧来源而文件消失返回 409，已有 SQL 步数或完成任务缺文件返回 METRICS_UNAVAILABLE。

COMPLETED 不接受 tail_incomplete；FAILED 可返回之前完整点及半行告警。MetricWriter 先 flush 后更新 SQL，文件的 step 暂时领先 SQL 是正常的，不可据此丢点或改状态。TaskDetail 终态后，前端仍需补拉所有剩余页。0 Loss/0 learning_rate 有效；最后训练 Loss 选末条 train，不将 eval 当训练值。当前服务无验证集入口，不能为了画两线给产品补 eval；样例仅演示通用事件格式。

资源上限：完整行 16 KiB、扫描 512 KiB/次、序列化响应 1 MiB；预算中预留探测后继行的空间，半行不造成相同游标的 has_more 无限循环。类型对局部结构负责，扫描/序列化预算由执行层再检查；解析源行要拒绝重复 JSON 键、非法 UTF-8/非有限数值/坏完整行。

服务以打开时的文件大小为本次快照，只按 LF 分行。总读取预算包含尾字节、续读游标前最多 16 KiB+1 的直接前驱和当前窗口；不从头扫描。跨页比较直接前驱的 total_steps 和 (step, kind) 顺序，不承诺审计游标之前的整个历史。预算截断时保留最后一个完整行作后继证据，has_more=true 必须有真实完整行且游标前进。读取后复核路径仍指向已打开文件、未缩短/多重硬链接；并发正常追加留到下次读取。同 inode 的任意等长改写/截断后重长及已复用 inode 不属于首版完整性保证，最终完整 bundle 仍由产物审计负责。

可参考 [首次查询](../examples/observability/metrics-query-initial.json)、[下一页查询](../examples/observability/metrics-query-next.json)、[第一页](../examples/observability/metrics-first-page.json)、[第二页](../examples/observability/metrics-next-page.json)、[终态取完](../examples/observability/metrics-terminal-drained.json)、[半行](../examples/observability/metrics-incomplete-tail.json)。分页演示显式 limit=2，协议默认仍为 200。first/next 的真实格式字节偏移由生成器计算（本版本第二页 cursor=304），不是 step 或数组长度，也不是训练证据。

## 日志：GET /api/v1/tasks/{task_id}/logs

LogsQuery 仅 tail，默认 100、范围 1～500。成功体 LogsPage，字段：contract_version/task_id/task_status/source_state、lines:string[]、truncated:boolean、tail_incomplete:boolean、filtered_lines:integer。

- lines 至多 500 个单行字符串，不能带 CR/LF/NUL 或不可编码的 UTF-8；可含中文等正常 Unicode，客户端用文本渲染。类型校验不等于日志字段投影/脱敏已执行。
- 从 LOG_DIR/tasks/{UUID}.log 尾部最多读 64 KiB；在窗口内选最后 tail 个完整源行再作安全投影，不因过滤而继续向旧记录补足行数。序列化响应最大 256 KiB，LogsPage 按实际 UTF-8 JSON 编码检查此上限。前端替换快照，不拼接重复文本。
- truncated 表示早期内容因 tail/字节窗口未返回；tail_incomplete 表示不完整尾部。filtered_lines 为选中源行内丢弃或修改过的记录条数，一行最多计一次，不统计单纯因窗口省略的内容；它不大于本次 tail，类型全局上限 500，请求相关上限由 02 保证。
- not_created 必须空 lines、全部标志 false、filtered_lines=0，不能用于 COMPLETED。Worker 预检查失败可能没有 Trainer 日志；可读失败说明在 TaskDetail。完成日志丢失/I/O/链接/越界由执行层报错，不解释为等待。

### 安全投影策略（M4-02 实现，01 已提供字段常量）

通用字段仅 recorded_at/stage，阶段专用键见 LOG_FIELDS_BY_STAGE，覆盖当前 Trainer 的 preflight、model_loading、data_preparation、data_verified、parameters、training、metric、parameter_verification、saving、training_and_save_finished、failed。target_modules 最多 64 个模块标识符；LRU/diagnostic/frame/module 数量上限集中在原常量模块并导出至 Schema x-limits，不改变已有响应字段。不得读共享 Celery stdout、lock、训练正文或任意异常输入。

数据摘要仅 sha256/size_bytes/row_count/review_status/build_id；failure 仅 task_id/code/stage，**不透传自由文本 message**（说明由 TaskDetail.error_message 提供）。diagnostic 仅 type/frames，frame 仅 basename 文件名、受限函数名、正行号；校验标识符/类型/范围，拒绝目录/盘符/控制字符和任意原始 traceback。

未知阶段/坏 JSON/坏通用字段丢弃整行；已知阶段的额外/不安全字段按白名单删除，安全剩余字段格式化为一行 JSON 文本；被删除或调整的行计入 filtered_lines，一行仅一次，正常 UTC/JSON 格式化不计过滤。投影器为 [task_log_projection.py](../../backend/app/services/task_log_projection.py)，复用 TrainingProgress 校验 metric；只保留匹配任务的 UUID、受控枚举、有限数值/摘要和受限标识符。diagnostic 最多 16 个异常、每个最后 32 个安全 frame。原文件不改写。

首版对窗口起点保守丢弃首个可能不完整的片段；即使恰好是行边界也不猜测。被字节窗口省略的片段不计 filtered_lines，只置 truncated；完整选中行的坏 UTF-8/JSON/不安全值才逐行计数，不为凑 tail 补读。全窗口都是长半行时返回 truncated/tail_incomplete，不能冒充完整记录。

自然缺日志只允许非 COMPLETED 且 SQL current_step=0，并且本服务尚未观测到该日志。服务用最多 4096 项、线程安全的进程内 LRU 记忆已打开的日志；已观察文件后消失报 LOGS_UNAVAILABLE。重启或 LRU 淘汰后无法持久证明零步任务曾有日志，此时按当前 SQL 判定；不新增数据库列或声称跨重启丢失探测。

两类读取共用 [task_files.py](../../backend/app/services/task_files.py)：Linux/WSL 的目录 fd 逐级 O_NOFOLLOW、固定根/UUID 子路径、O_NONBLOCK 打开并 fstat 校验普通单硬链接文件；拒绝子目录/根祖先链接、FIFO/设备/目录/I/O 失败。打开描述符锁定文件，结束前重走命名路径核对身份，所有成功/失败分支关闭句柄。配置根本身不存在属于不可用，不解释为任务未产出。不使用 GPU 锁，不创建任何训练目录或文件。

示例：[正常尾部](../examples/observability/logs-ready.json)、[截断](../examples/observability/logs-truncated.json)、[过滤与半行](../examples/observability/logs-filtered-tail.json)、[尚未创建](../examples/observability/logs-not-created.json)。

## 下载：GET /api/v1/tasks/{task_id}/adapter

AdapterQuery 没有参数，额外字段拒绝；成功为二进制 ZIP，不是 JSON 对象。AdapterDownloadHeaders 仅描述 HTTP 头，包含的 task_id 是类型上下文，as_headers() 不把它当成 HTTP 头或响应体。使用 for_task(UUIDv4) 生成固定文件名，禁止客户端路径/自定义文件名。

| 项目 | 定稿 |
| --- | --- |
| Content-Type | application/zip |
| Content-Disposition | attachment; filename="llmcloud-adapter-{UUID}.zip" |
| Cache-Control | no-store |
| ZIP 顶层 | {UUID}/，对应原 outputs/{UUID} 的相对内容 |
| 成员 | 原审计成功的 manifest.artifacts 加 manifest.json；不添加 checkpoint/源日志/数据集/基础模型 |
| 临时区域 | DATA_DIR/downloads，不能在被审计输出目录内加 ZIP |
| 资源 | 单 API 进程最多 1 个在途下载（覆盖打包至清理）；未压缩总量最多 256 MiB |
| 忙 | 429/DOWNLOAD_BUSY，Retry-After: 2（DownloadBusyHeaders） |

M4-03 的 [TaskDownloadService](../../backend/app/services/task_download.py) 已实现以下流程，HTTP/生命周期见 [task_download.py](../../backend/app/api/task_download.py)：

1. 短事务取得 SQL COMPLETED 的 CompletedArtifactSpec 后释放；非完成状态返回 409，损坏 SQL 记录/存储失败返回 503，不根据磁盘目录猜状态。
2. 非阻塞取得单应用/单进程下载槽位；以安全 fd 读取最多 512 KiB manifest，比较其原始字节 SHA-256 和 SQL，校验原 TrainingManifest、模型/revision、完整 config/runtime、数据哈希/大小/行数、summary，服务任务不允许额外验证集。
3. 只扫描原审计白名单目录项的元数据，不遍历 checkpoints。拒绝链接、异常硬链接/非普通文件、未知文件、缺项、大小不符；先检查声明/实际未压缩总量（含 manifest）均不超过 256 MiB，再读取权重。
4. 在 DATA_DIR/downloads 的独立 0700 临时工作区按 64 KiB 复制，逐文件比较实际大小/哈希。临时父目录 fd 保留到清理，不接受可被组/其他用户写入的 downloads 目录。原审计器是基于路径的读取器，先隔离到私有副本再复用原 verify_training_artifacts，可避免审计源文件时被替换为无界/越界输入；不修改 Trainer 或其审计规则。
5. 原 CPU 审计通过后，只将该副本的 manifest.artifacts 加原 manifest.json 写入 ZIP_STORED；写入 ZIP 的实际字节再次校验大小/哈希，检查 ZIP CRC。打包前后复核源目录文件身份/大小/mtime/ctime，拒绝检测到的源变动。临时副本和 ZIP 总磁盘需求约两倍未压缩量（最高约 512 MiB 加 ZIP 元数据）；ZIP 不进入内存或原输出目录，不作下载缓存。
6. 完整包准备好再发送 200、Content-Length 和成功头；响应监听断连，读取/发送失败或取消均在 finally 关闭 ZIP、清理整个工作区并释放槽位。准备阶段请求取消时，后台线程完成后负责清理，结束前仍占槽位，不能提前放行第二次打包。CPU 文件读取在线程池运行，不占 GPU 锁。

重复/未知查询参数拒绝，CORS 暴露 Content-Disposition/X-Request-ID/Retry-After。下载接入原统一 ErrorResponse，源损坏为 INVALID_ARTIFACT，超限 413，忙时 429 + Retry-After: 2，临时存储失败 STORAGE_UNAVAILABLE；不改变任务状态。无 Range/断点续传缓存，重复请求重新校验并打包。进程强杀遗留由停 API 后人工清理专用临时目录，不承诺自动回收。

TaskDetail 100% 且 RUNNING 不可下载；只存在权重目录不可下载；缺失/损坏的 COMPLETED 文件也不可下发。下载旧的完成任务不获取 GPU 锁。响应开始后发生网络错误只能终止传输，不能往半个 ZIP 后面拼 JSON。

前端点击时固定 task_id/文件名及请求归属，切换任务的旧响应不能更新新任务；超时/取消必须覆盖 await blob 的完整读取，不在仅收到响应头时清理监听。成功 MIME 也要核对；JSON 错误不能另存 ZIP。下载包解压后用原 CPU 产物审计再次检查，不因此执行生成或占 GPU。

示例：[成功头描述](../examples/observability/adapter-headers.json)、[忙时头](../examples/observability/download-busy-headers.json)。前者不是可以直接返回给客户端的 JSON body。

## 内部完成快照：额外只读接口

CompletedArtifactRepository.get_completed_artifact(UUID) -> CompletedArtifactSpec，SqlTaskRepository 已实现该额外只读投影。DTO 为 spec:TaskExecutionSpec、output_key、manifest_sha256、training_summary、独立 contract_version。输出键必须 outputs/{spec.task_id}，summary 必须满足原完成约束及已设置的 runtime.max_steps；嵌套值从字典重校验并脱离传入模型的可变列表。

找不到抛 CompletedArtifactNotFound（404）；任何已存在非 COMPLETED 抛 CompletedArtifactNotReady（409）；损坏/SQL 异常沿用 TaskStoreError（503）。业务异常在读事务外抛出，避免被 _session 包装成数据库不可用。不修改 get_status/claim/record_progress/complete/fail，不在仓储开文件或持事务等待 ZIP。

这是结构约定，不表示实例已被 SQL/路径/文件审计。[内部 mock DTO](../examples/observability/completed-artifact-spec.json) 没有真实成功标记或权重，不能用于宣布任务完成。

## 错误与上限来源

新错误在 ObservabilityErrorCode 中定义，并加入原 ApiErrorCode；原 M3 TaskErrorCode/Trainer FailureCode 不增加观测错误，不因 GET 失败将训练状态写 FAILED。

| code | HTTP | 意义 |
| --- | --- | --- |
| METRICS_CURSOR_INVALID | 409 | 文件版本/偏移不可继续，明确重置，避免无界重试 |
| METRICS_CORRUPTED | 500 | 无效完整指标行、完成指标半行/空文件 |
| METRICS_UNAVAILABLE / LOGS_UNAVAILABLE | 500 | 应有文件不可用或路径/读取不安全 |
| ARTIFACT_NOT_READY | 409 | 任务不是 COMPLETED |
| INVALID_ARTIFACT | 500 | 完成产物/快照/哈希/审计不一致 |
| ARTIFACT_TOO_LARGE | 413 | 超过单次未压缩量上限 |
| DOWNLOAD_BUSY | 429 | 单 API 下载槽位已占用，Retry-After=2 |

其余沿用 TASK_NOT_FOUND=404、DATABASE_UNAVAILABLE=503、VALIDATION_ERROR=422、STORAGE_UNAVAILABLE/INTERNAL_ERROR=500。message 用于展示，不作为分支条件。所有常量、上限与状态映射均由生成 Schema 的 x-limits/x-error-http-status 输出；轮询 2000 ms、每轮最多 5 页、最多显示最近 10000 个点。错误示例见样例索引，数值/错误均为 mock。

## 导出、发布与 B 消费者核对

```bash
uv run --locked python scripts/export_observability_contract.py --check
```

去掉 --check 生成类型/27 个格式样例、索引及说明。Schema 标记 types_only，HTTP 状态 not_asserted，索引 http_evidence=false；这些标记表示此导出器不提供 HTTP 证据，并非运行时能力探测。export_task_openapi.py 从真实 app.openapi() 导出全部实际任务子路径，含指标/日志/下载，旧未发布保护已按真实实现更新。

`uv run --locked python scripts/check_task_observability.py` 运行隔离 TCP/SQL/MetricWriter 观测冒烟；`uv run --locked python scripts/check_task_download.py` 复用已有 synthetic CPU bundle 测试工具，验证真实 HTTP ZIP、解压独立审计、忙/损坏、实际 TCP 断连后的清理（首块后显式注入暂停，报告 response_stall_injected=true）。两者均明确替身/CPU 范围，不启动 Worker/Redis/GPU，不代表新 GPU 训练、前端适配或 M4-07 验收已完成。

B 已完成下列消费者核对并交付 04/05/06，见 [B 核对](../worklogs/2026-11-05-m4-01-b-consumer-review.md)、[A 审查](../worklogs/2026-11-06-m4-b-review.md)。清单保留为后续回归基线：

1. source_id/cursor/offset 是三种不同含义，下一页实际 cursor=304，同一步两类不会覆盖。
2. not_created、ready 空文件、终态空页、半行、0 Loss 可区分，EOF 不丢最后 train。
3. ErrorResponse/409 重置和日志三类告警足够，观测错误独立于 TaskDetail。
4. 最后 Loss 选 train，最多 5 页/10000 点且有补拉/展示窗口提示；TaskDetail 终态后仍可补拉资产。
5. 成功下载是 ZIP/HTTP 头，不把 header-description fixture 当 JSON body；固定 UUID 文件名与取消/超时能覆盖整个 blob。
6. internal DTO 不用于页面状态；原 M1/M3 调用签名和能力探测保持，HTTP 未发布时不展示 fake 数据。

A 已收录 B 独立核对并重跑真实 HTTP/页面检查，无需调整 wire 版本；不兼容调整仍须同步独立观测版本/类型/样例。M3 人工剩余项和 M4-07 真实 GPU/联合操作继续按 [安排](../m4-acceptance.md) 执行，CPU 替身不替代它们。
