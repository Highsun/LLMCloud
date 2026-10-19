# M1 数据集与公共错误契约

契约版本：**1.0.0**；日期：2026-10-19；对应任务：**M1-01**。

状态：接口设计与 Schema 已交付，运行时接口、存储和异常处理由 M1-02/M1-03 实现。当前后端只有健康检查和模型目录，访问下述数据集路径仍会得到旧的路由错误。不要把离线设计稿当作已部署 API。

面向项目成员及 AI 助手的全局约束见 [AGENTS.md](../../AGENTS.md)，阶段安排见 [项目规划](../project-plan.md)。

## 一、设计决定与全局关系

| 决定 | 原因 |
| --- | --- |
| 上传时只接收 file 和可选 name | 数据 ID、行数、路径和哈希由后端生成，减少前端与文件系统耦合 |
| 同步验证成功后返回 201 | 50 MiB 的课程 MVP 不需要额外的数据校验队列；训练才通过 Celery 异步执行 |
| 数据集没有 PENDING/QUEUED 等状态 | 这些是训练任务状态；M1 只公开已经校验、落盘、提交的资源 |
| 分页使用 page/page_size | 当前数据量较小，适合 Vue 表格；固定排序避免引入排序表达式 |
| 成功直接返回资源；失败统一 error 对象 | 保持现有 health/models 的直接成功响应风格，使用真实 HTTP 状态码 |
| 增加 original_filename 与 sha256 | 显示上传来源，关联 M2/M3 的不可变训练输入与复现实验 |
| 详情只返回元数据 | 不在普通详情接口读回训练正文；预览、原始文件下载、修改和删除暂不纳入 M1 |

基础路径固定为 `/api/v1`，字段使用 snake_case。以下常量集中定义在 `backend/app/core/dataset_contract.py`：

| 约束 | 值 |
| --- | --- |
| 单文件最大原始字节数 | 50 MiB = 52,428,800 bytes，等于上限可接受 |
| 整个 multipart 请求体上限 | 52,494,336 bytes，即文件上限 + 64 KiB 表单开销 |
| 单物理行上限 | 1 MiB = 1,048,576 bytes，包含该行原始换行符/BOM 字节 |
| multipart 解析器硬上限 | 最多 4 个 file part 和 4 个文本 part，单文本 part 缓冲最多 64 KiB；不表示这些额外字段会被接受 |
| 默认/最大 page_size | 20 / 100 |
| 单响应最多错误明细 | 10 |

文件上限针对真实上传字节；M1 不接收压缩文件或压缩请求。代理的请求体限制不应小于应用的 multipart 上限。应用仍需在解析和读取过程中计数，不能只相信 Content-Length、前端校验或 UploadFile 的内存缓存设置。

## 二、上传接口

`POST /api/v1/datasets`

请求必须是 `multipart/form-data`。浏览器使用 FormData 自动生成 boundary，不手动设置 Content-Type，不混合 JSON Body，不发送 Base64 文件。

| part 名称 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| file | 一个二进制文件 | 是 | 原始文件名必须以 .jsonl 结尾，大小写不敏感；内容仍需完整验证 |
| name | 文本 | 否 | 去除首尾空白后 1–255 个 Unicode 字符，禁止 C0/DEL 控制字符；缺省时使用清理后的原始文件名，包含扩展名 |

name 不传与传空字符串不同：空字符串或全空白返回 422。控制字符在原始 name 的任何位置都不允许，即使它位于首尾。name 可以重名，不作为文件键。单个 name part 的编码字节上限为 1 KiB；超出按请求字段校验失败处理。

解析完成后，必须恰好一个 file，最多一个 name；重复 part、未知 part、name 被当成文件上传或 file 被当成普通字符串均返回 422/VALIDATION_ERROR。不要依赖框架默认“取最后一个值”的行为。若先触发解析器的 part 数量/文本缓冲硬上限，则按 400/INVALID_MULTIPART 拒绝；整个请求体超限仍为 413。

`file.filename` 仅用于原始文件名展示：先把反斜杠与 `/` 都视为路径分隔符，取最后一段，去除首尾空白；随后要求非空、长度不超过 255 个 Unicode 字符、无控制字符、有非空文件主名和 .jsonl 扩展名。比如 `../../demo.jsonl` 只记录为 `demo.jsonl`，不能决定保存位置。原始名只作为数据库展示字段，不拼接为系统路径或响应头；日志也只使用清理后的值。

文件 part 的 MIME 可能是 application/json、application/x-ndjson、text/plain、application/octet-stream 或缺省；不以此决定是否接受。扩展名只能预筛，内容校验才决定是否为有效数据。文件扩展名错误返回 422/INVALID_DATASET，明细 code 为 unsupported_extension。

Content-Encoding 缺省或 identity 可接受，其他值返回 415。不是 multipart 的请求返回 415；缺少 boundary 或破损的 multipart 返回 400。应用在 multipart 解析阶段就必须控制整个请求体大小和 part 数量，不能等文件全部缓存后再限流。

成功：`201 Created`，响应体为 DatasetDetail，与详情接口结构完全相同；`Location: /api/v1/datasets/{id}`。

```bash
curl -i http://127.0.0.1:8000/api/v1/datasets \
  -F 'file=@docs/examples/train.jsonl' \
  -F 'name=云计算课程样例'
```

```javascript
const form = new FormData()
form.append('file', selectedFile)
if (name.trim()) form.append('name', name.trim())
const response = await fetch('/api/v1/datasets', { method: 'POST', body: form })
```

重复上传相同内容是合法的新资源，返回新的 UUID；sha256 相同不触发去重或 409。M1 不支持幂等键，客户端在网络中断后不要自动重试 POST；可以先刷新列表再由用户决定是否重传。

## 三、JSONL 文件与记录

格式标识为 `alpaca_jsonl`，由服务端返回，客户端不能上传 format 参数。

- 严格 UTF-8；允许且仅允许在文件起始处出现 UTF-8 BOM。支持 LF/CRLF，允许最后一行没有换行符。
- 空白行忽略，但错误中的 line 始终是从 1 开始的物理行号。至少一条有效记录，空文件/仅空白/BOM 文件均无效。
- 每个非空白物理行必须是完整 JSON 对象。禁止重复 JSON 键、NaN/Infinity、注释和跨物理行 JSON；过深或无法解析的 JSON 也返回数据错误。
- 指令内容中的换行使用 JSON 字符串转义 `\n`，不能把一个对象拆到多行。
- 允许的键只有 instruction、input、output，不默默丢弃未知键；messages 格式暂不接受。

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| instruction | string | 是 | 非空白，不转换数值/布尔值/null，不改写首尾空白 |
| input | string | 否 | 缺省视为 ""；可为空或全空白；显式 null 无效 |
| output | string | 是 | 与 instruction 相同 |

记录级类型定义在 `trainer/dataset_schema.py` 的 InstructionRecord。验证不做 tokenizer 截断、不补 system prompt、不重写文本；chat template 和序列长度属于 M2。正文按原始字节保存，BOM、换行与空白行仍保留，SHA-256 对原始完整字节计算，size_bytes 也是原始大小。row_count 只统计有效的非空白记录。

首个文件内容错误立即终止本次上传并返回 422/INVALID_DATASET。文件或行超过上限返回 413/UPLOAD_TOO_LARGE，而不是继续解析大对象。UTF-8/语法/记录错误在扫描时先遇到者优先；多个独立非法条件不承诺固定跨类别优先级。

合法样例：[train.jsonl](../examples/train.jsonl)。可执行的正反样例位于 [datasets 目录](../examples/datasets/README.md)。当前 `trainer.dataset.iter_records` 仍允许额外键且不支持 BOM/重复键检查；M1-02 需要更新为共享规则，不能直接宣称它已经满足本契约。

## 四、列表与分页

`GET /api/v1/datasets?page=1&page_size=20`

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| page | integer | 1 | 从 1 开始，必须 >= 1 |
| page_size | integer | 20 | 1–100，超限返回 422，不能静默截断 |

未知、重复、空值、非整数或越界查询参数返回 422/VALIDATION_ERROR。M1 没有 search、sort、offset、limit 或用户筛选参数。

固定排序为 `created_at DESC, id DESC`；数据库时间按 UTC 保存。第二排序键处理相同时间，不允许前端再次重排后伪造分页。

响应为 DatasetPage：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| items | DatasetSummary[] | 当前页资源，数量不超过 page_size |
| total | integer | 本次计数的资源总量，>= 0 |
| page | integer | 请求页码，原样保留 |
| page_size | integer | 请求或默认页大小 |
| total_pages | integer | ceil(total/page_size)；total=0 时为 0 |

没有资源或超出末页都返回 200 与空 items，不返回 404，也不偷偷跳到最后一页。服务可以在发现页码超过总页数时直接返回空页，避免把异常大的 page 转成数据库 OFFSET。

这是偏移分页，不承诺跨请求的快照：并发上传可能让翻页结果移动；前端上传成功后回到第 1 页并重新请求 total。MVP 不引入游标或分页快照令牌。

## 五、详情与公共资源字段

`GET /api/v1/datasets/{dataset_id}`，成功返回 `200 OK` 与 DatasetDetail。

dataset_id 必须是 UUID 字符串；服务端生成 UUIDv4，并以标准小写连字符形式输出。路径 UUID 语法错误返回 422，格式合法但不存在返回 404/DATASET_NOT_FOUND；不通过 404 掩盖参数校验错误。

| 字段 | 类型 | 列表 | 详情/上传 | 说明 |
| --- | --- | --- | --- | --- |
| id | UUIDv4 string | 有 | 有 | 不透明资源标识 |
| name | string | 有 | 有 | 显示名称，不唯一 |
| format | "alpaca_jsonl" | 有 | 有 | 当前固定格式 |
| size_bytes | integer >= 1 | 有 | 有 | 原始文件字节数 |
| row_count | integer >= 1 | 有 | 有 | 有效记录数 |
| created_at | RFC 3339 UTC string | 有 | 有 | 以 Z 结尾，允许小数秒 |
| original_filename | string | 无 | 有 | 清理后的客户端文件名 |
| sha256 | 64 位小写十六进制 string | 无 | 有 | 原始文件 SHA-256 |

详情只读数据库元数据，不重新读取/校验整份文件，也不返回正文、preview、storage_path、user_id 或绝对路径。后续创建训练任务时再检查底层文件存在与可读性。传输只返回元数据不表示底层文件绝不会被外部手工删除。

所有成功响应直接是资源或分页对象，没有 success/code/data 外壳。成功示例见 [upload-response.json](../examples/datasets/upload-response.json)、[list-response.json](../examples/datasets/list-response.json)、[empty-page.json](../examples/datasets/empty-page.json)。示例 UUID/时间是固定演示值，不是实际上传结果。

## 六、统一错误结构

此结构在 M1-03 作为应用公共异常处理落地，覆盖请求字段校验、业务异常、路由/方法错误及未捕获服务器异常；后续任务、推理接口复用。当前 FastAPI 默认错误尚未替换。

```json
{
  "error": {
    "code": "INVALID_DATASET",
    "message": "数据集第 2 行缺少 output 字段。",
    "details": [
      {
        "loc": ["body", "file", "output"],
        "code": "missing",
        "message": "output 为必填字符串。",
        "line": 2,
        "column": null
      }
    ],
    "details_truncated": false,
    "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df"
  }
}
```

- HTTP 状态码保留实际语义，不统一包装成 200。
- error.code 是稳定的大写机器码；message 可使用中文，不作为程序分支依据。
- details 始终是数组；无字段明细时为 []，最多 10 条，发生截断时 details_truncated=true。上例的结构字段均必需，line/column 不适用时显式为 null；响应不使用 exclude_none/exclude_defaults 来省略这些键。
- loc 是字段路径，使用 body/query/path 作为首项，如 `["query","page_size"]`；文件内容字段接在 body/file 后。line/column 是可空、从 1 开始的位置，column 按字符计数。不能确定位置时用 null。
- 文件内容只报告第一个错误；请求元数据或查询参数可报告多条。明细 code 使用受控语义，如 missing、invalid_type、out_of_range、extra_field、duplicate_field、invalid_filename、invalid_encoding、invalid_json、duplicate_key、blank、file_too_large、line_too_large、unsupported_extension。避免直接绑定 Pydantic 内部版本的错误名。
- 每个请求由服务端生成 UUIDv4 request_id，不能直接信任客户端传入的同名 header。所有应用响应携带 X-Request-ID，错误体与 header 一致。
- 错误不能回显整条训练数据、原始 input、绝对文件路径、数据库异常文本、凭据或堆栈。详细异常记录在服务端日志，并关联 request_id。

| HTTP | error.code | 场景 |
| --- | --- | --- |
| 400 | INVALID_MULTIPART | boundary 缺失/表单结构破损，或超出解析器 part/文本缓冲硬上限 |
| 413 | UPLOAD_TOO_LARGE | 文件、单行或整个请求体超过上限 |
| 415 | UNSUPPORTED_MEDIA_TYPE | 请求不是 multipart，或 Content-Encoding 不支持 |
| 422 | VALIDATION_ERROR | file/name/query/path 的缺失、重复、未知或非法值 |
| 422 | INVALID_DATASET | 扩展名、编码、JSON、记录内容或空数据错误 |
| 404 | DATASET_NOT_FOUND | UUID 合法但资源不存在 |
| 404 | NOT_FOUND | 没有此 API 路由 |
| 405 | METHOD_NOT_ALLOWED | 路由存在但 HTTP 方法不支持；保留 Allow header |
| 503 | STORAGE_UNAVAILABLE | 已识别的磁盘满、文件服务不可写等暂不可服务问题 |
| 503 | DATABASE_UNAVAILABLE | 已识别的数据库不可连接/锁超时等可用性问题 |
| 500 | INTERNAL_ERROR | 程序错误、未知异常，使用通用提示 |
| 原状态 | HTTP_ERROR | 其他尚未有专用机器码的 HTTP 异常，保留原状态和必要 headers |

前端优先显示 message 与字段/行号，未知 code 使用通用错误展示。浏览器断网、超时或上游代理 HTML 错误不一定包含此 JSON，需要单独兜底。CORS 在 M1-03 暴露 X-Request-ID 与 Location，前端不必发送自定义请求头。

## 七、路径、不可变性与数据库映射

```text
DATA_DIR/                          # 默认是仓库 data/，配置后可以改变
├── llmcloud.db
└── datasets/
    ├── .tmp/{upload_id}.part      # 私有临时文件，与最终目录在同一文件系统
    └── {dataset_id}/train.jsonl   # 已确认数据集，原始字节，不覆盖
```

Dataset.storage_path 保存 `datasets/{dataset_id}/train.jsonl`，相对 DATA_DIR，不包含前缀 data/。服务/Worker 通过设置解析绝对路径，并校验解析结果仍位于 DATA_DIR/datasets 下。客户端不能读写该键，不接受客户端绝对路径。

建议上传提交顺序：先校验元数据 → 流式写临时文件并计算大小/哈希 → 逐行校验并计数 → 同文件系统移动到唯一 UUID 目录 → 登记元数据并提交 → 返回 201。数据库记录不可先公开，避免 Worker 查到尚未就绪的文件。

普通失败应回滚并清理该次上传拥有的临时/最终文件；清理失败要记录。文件与 SQL 不是同一事务，进程被强杀或提交结果不确定时不能声称原子性，应提供孤立文件/元数据检查和人工修复依据，不能误删正在上传或已经被记录引用的文件。M1 不需要分布式事务或 outbox。

| 契约字段 | 当前实体及 M1-02 工作 |
| --- | --- |
| id/name/size_bytes/row_count/created_at | 复用现有 Dataset 字段；UTC 存储，SQLite 读出的无时区 datetime 由 DTO 按 UTC 解释 |
| format | 当前仅支持一种，服务层返回固定值，不必立即增加数据库列 |
| original_filename | 新增非空字符串列，最大 255；不能用自定义 name 替代 |
| sha256 | 新增非空 64 字符列；只用于校验与溯源，暂不建立唯一约束 |
| storage_path | 保留实体字段，明确为相对 DATA_DIR 的键，禁止返回给客户端 |
| user_id | MVP 无认证时仍为 null；不能由客户端提交或伪装已有权限校验 |

已有 `create_all` 不会修改旧表。M1-02 必须提供显式迁移/兼容方案：空表正常升级；已有记录可读取原文件时计算哈希，原始文件名只能从可信历史元数据恢复。无法恢复原始文件名或文件缺失时，迁移应输出待人工补录/修复清单，不用最终路径的 train.jsonl 冒充客户端文件名，不编造哈希。不能静默删除/重建已有数据库；仅确认为可丢弃的本地演示数据时才按明确指令重置。

上传后原始文件不修改、不覆盖，不提供 PATCH/DELETE。任务通过 dataset_id 引用数据，M3 记录当时的 sha256 与训练参数；重复上传获得不同 ID，避免后续训练输入被悄悄替换。

## 八、实现分界与交付检查

| 本次 M1-01 | 后续任务 |
| --- | --- |
| AGENTS.md 协作入口、本文、常量、Pydantic DTO、InstructionRecord、离线 OpenAPI、固定样例与契约检查 | M1-02：存储/扫描、共享记录校验、数据库迁移、清理；M1-03：真实路由、参数绑定与统一错误 handlers；M1-04：Vue 页面 |

生成/核验契约：

```bash
uv run --locked python scripts/export_dataset_contract.py
uv run --locked python scripts/export_dataset_contract.py --check
uv run --locked python -m unittest discover -s tests -p 'test_dataset_contract.py'
```

生成文件：[datasets.openapi.json](datasets.openapi.json)。Schema 由 Pydantic 生成，HTTP 元信息在导出脚本维护；样例是真实文件统计值加固定演示 ID/时间。生成器不导入主应用、不建表、不挂载占位路由。

M1-01 检查：字段、默认值与错误结构没有未决项；样例可通过对应 Schema；上传样例哈希/字节数/行数与文件一致；离线 OpenAPI 不含断裂引用；已有 health/models 行为不变。M1-03 还需用真实应用 OpenAPI 与 HTTP 响应验证，替换设计稿的 planned 状态。

技术依据：[FastAPI 表单与文件](https://fastapi.tiangolo.com/tutorial/request-forms-and-files/)、[FastAPI 异常处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)、[Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)、[OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0.html)。
