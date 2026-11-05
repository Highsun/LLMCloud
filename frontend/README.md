# LLMCloud 前端工作台

本目录使用现有 Vue3/Vite 技术栈，不引入 UI 库、路由库或图表依赖。界面覆盖工作台总览、数据集、微调配置、任务观测、推理和使用指南，支持桌面与移动端布局。Hash 导航支持直接访问与浏览器前进/后退。

## 启动与检查

要求 Node.js 22.18+ 的 22.x 或 24.12+。

```bash
cd frontend
npm ci
npm run dev
```

本地入口：http://127.0.0.1:5173/ 。生产构建：`npm run build`；自动检查：`npm test`。

`.env.example` 中 `VITE_API_BASE_URL` 配置业务 API 前缀，`VITE_BACKEND_URL` 配置开发代理目标。开发代理同时转发 `/api` 和 `/openapi.json`。生产反向代理需要提供这两条路径，Vite 开发代理不包含在 dist 中。跨域 API 需由后端正确配置 CORS；如果 OpenAPI 地址不同，可设置 `VITE_OPENAPI_URL`。

## 当前交付与接口边界

- 所有页面可以在后端离线时浏览，不填充虚构数据、任务状态或训练指标。
- 数据集实现 multipart 上传、真实传输进度、取消等待、错误明细、请求编号、分页、只读详情。上传只发送 file 和可选 name，不在浏览器中另写 JSONL 扫描器，内容以共享服务端校验为准。
- 上传成功需要收到 201 和资源 ID。成功后重新读取第一页；网络中断、超时、取消或异常响应不自动重传，提示先核对列表。传输 100% 不表示校验或入库完成。
- LoRA 表单遵循现有 TrainingConfig 范围和默认值，可独立导出配置草稿。没有选择实际数据集时，草稿的 dataset_id 为空，不能直接当作有效任务请求。任务提交发送 UUIDv4 Idempotency-Key，只读取 TaskDetail.id；当前标签页的 sessionStorage 保存最近提交的键、配置快照与任务 ID，刷新可恢复原提交。待上传文件、未提交草稿与推理输入仍不跨刷新保存，不保存训练正文或生成记录。
- 工作台读取运行时 `/openapi.json` 判断接口是否存在，再启用相应操作。健康检查只表示 API 进程存活，模型目录只表示允许的模型，不展示推测的 GPU/Redis 状态。
- 任务列表支持 ALL/五状态服务端筛选、分页、刷新与每 2 秒轮询；切状态回第一页，后续查询保留当前状态和页码。使用 AbortController 与请求序号隔离旧成功/错误/finally；切出任务页停止轮询并取消查询，浏览器页面隐藏时暂停。详情只读取正式 config，显示真实步数、null 进度、错误码/说明与时间；COMPLETED/FAILED 停止详情自动查询，指标/日志继续补齐最终快照，仍可手动刷新。指标/日志及 Adapter 下载已按 M4 正式契约接入，真实文件/GPU 联合验收仍待 06/07；推理继续等待 M5 发布。不支持取消训练、重训或恢复训练。
- 推理页面仅选择任务列表当前页中 COMPLETED 的任务，提交 task_id、prompt、max_new_tokens；409 显示 GPU 忙。前端提示词限制 8000 字符、输出限制 1–512 tokens 是当前界面限制，须在 M5 对照正式接口确认。基础模型对照为明确标识的手动记录，不伪造第二次模型调用。

已同步成员 A 的 M1 数据集 HTTP 与 M3 任务 HTTP 实现。2026-11-03 补齐 M3-05；2026-11-04 A 的 M3-07 真实 Redis/GPU 串行及中断恢复已验收，B 已独立复核收到的真实证据和既有任务页面，并修复手机失败码挤压问题。B 本轮为 CPU 快照页面复查，GPU 运行来源及共同收口范围见独立日志。

## M3–M5 联调约定

### M4-05 Adapter 下载交互

`task-download.js` 在点击时捕获选中任务的 UUID，仅 COMPLETED 可下载。文件名固定为 llmcloud-adapter-{UUID}.zip，不读取服务端自定义文件名；重复点击共用一个请求，切任务/关闭详情/离开任务页取消旧传输并隔离迟到成功、错误和 finally。请求期间可主动“取消下载”，取消后可明确点击重试；不会自动重试网络失败或 DOWNLOAD_BUSY。

专用 fetch helper 的 60 秒 timeout/AbortSignal 覆盖收到响应头、整个 blob、基本 ZIP 签名检查，finally 才清理计时器/监听；传输替身忽略 abort 时也能及时结束等待且不保存晚到数据。仅接受 200/application/zip，拒绝 JSON/HTML/空响应/206 或非 ZIP 签名；错误保留正式 ErrorResponse、真实 HTTP 状态/request_id，429 显示 Retry-After 秒数。ZIP 签名检查不替代服务端清单/CRC/哈希审计，浏览器保存提示也不代表新模型验收。

原 api.request 的 JSON 参数和错误语义保持；额外导出原 responseError 供下载复用，原 raw=blob 分支也改为 await response.blob()，确保已有调用在 body 结束前不会提前清理超时/取消。

```bash
node --test tests/task-download.test.mjs tests/api.test.mjs
node testing/check_task_download.mjs
```

独立浏览器入口使用完整、有效且明确标为合成数据的 ZIP（仅 fixture.txt，无模型权重），检验文件名/实际落盘字节、错误 MIME/JSON、忙/取消/延迟 body/任务切换及超时断连。截图、合成 ZIP/result 保存在仓库根目录被忽略的 data/acceptance/b-review/m4-05/。可使用已安装的 Playwright Chromium；通过 PLAYWRIGHT_BROWSERS_PATH 指定本机缓存、PLAYWRIGHT_CHANNEL 指定其他匹配浏览器，均为环境选择，不硬编码本机路径到产品。交接范围和验证结果见 [M4-05 B 日志](../docs/worklogs/2026-11-05-m4-05-b.md)。

### M4-04 增量指标与日志

`task-observability.js` 独立管理当前任务的观测状态：用服务返回的 source_id/cursor/offset 续读及标识记录，保留同 step train/eval；原 TasksPanel 的 after_step/Map(step) 已替换。每轮最多 5 页、每页 200 条，最近 10,000 条窗口有明确提示；最新训练 Loss 独立保存，不被末尾 eval 或窗口裁剪覆盖。严格检查正式整页/任务身份/源版本/请求游标关系，非法响应显示 INVALID_RESPONSE 并保留已有记录；409/METRICS_CURSOR_INVALID 每轮至多重置一次后从头读取。

观测使用独立的约 2 秒轮询周期，不等待任务列表请求完成。隐藏/离开任务页、关闭详情或切任务均取消旧请求并隔离迟到成功、错误及 finally；重新显示从保留游标续读。TaskDetail 是业务状态来源，观测响应不改写它；终态仍分轮补完 has_more，再取最终日志后停止自动读取。关闭自动刷新后仍可手动单轮刷新。

`TaskLogs.vue` 以文本显示正式有限尾部快照，分别提示截断、未完成行和过滤数；未产出、空文件、终态无记录和读取错误分别显示。刷新替换快照，查看历史时保留滚动位置，提供“回到底部”。失败时保留上次可用快照；指标/日志错误与 TaskDetail 独立。

```bash
node --test tests/task-observability.test.mjs
node testing/check_task_observability.mjs
```

浏览器入口使用已标注的独立 fixture HTTP 服务，检查真实 Vue 页面、桌面/390px、终态停止、隐藏恢复、任务切换、文本转义和日志滚动，截图/result 在仓库根目录被忽略的 data/acceptance/b-review/m4-04/ 下，独立于原 Playwright 输出清理。默认 Playwright Chromium；已安装 Chrome 可设置 PLAYWRIGHT_CHANNEL=chrome。此检查不启动后端/Worker/GPU，真实 Linux/WSL 文件接口对齐与 GPU 验收保留给 06/07。已有 29 项 M1/M3 浏览器回归使用临时真实 API/SQLite，Windows 上观测文件路由的 Linux 原语不可用，不能把该回归算作新文件接口通过。详情见 [M4-04 B 交接](../docs/worklogs/2026-11-05-m4-04-b.md)。

### M4-01 B 消费者核对

2026-11-05 已按 A 的正式观测契约 1.0.0、生成类型/27 个 mock 样例和真实任务 OpenAPI 完成 B 侧独立核对。现有 request 的 JSON/统一错误、能力探测及 04a 图表可以消费对应格式；分页/重放演练区分 source_id/cursor/offset，并验证终态空页、半行和零值不会要求丢弃已有数据。未发现需要修改后端 wire 契约的阻塞差异，具体差异及接续验收见 [B 核对日志](../docs/worklogs/2026-11-05-m4-01-b-consumer-review.md)。共享阶段状态由 A 收录确认。

`node --test tests/observability-contract.test.mjs` 可独立运行 12 项消费者检查，`npm test` 同时运行。这些测试直接读取正式生成样例并调用现有组件/请求/能力探测；分页合并仅在隔离测试中演练，网络响应为明确替身。此项没有实现生产观测控制器、日志告警或下载 helper，也不代表 M4-04/05 或实际 HTTP/GPU 联合验收完成。

### M4-04a 图表展示准备

`LossChart.vue` 已支持显式 `kind: "train" | "eval"`、正整数 `step`、非负有限数 `loss` 的记录数组。训练/验证分别显示图例、最新值和曲线，共用坐标轴；同 step 两类点都保留，验证线使用虚线和空心点。只有实际存在的系列才显示；单点仅画点，零 Loss 有效，空记录显示中性提示。组件不修改输入、不平滑或补点，窄容器内可用触摸或键盘左右滚动绘图区。

04a 本身只完成纯展示；后续 M4-04 已接入 source_id/cursor/offset 合并、终态补拉和日志，M4-05 已接入下载生命周期，详情见上节。生产页面仍按运行时 OpenAPI 探测能力，没有添加测试数据。

检查命令（在 frontend 目录）：

```bash
npm test
npm run build
node testing/check_loss_chart.mjs
```

浏览器检查只启动隔离组件页，不启动 API、Redis、Worker 或 GPU；测试数据明确标注为合成数据，不进入产品页。默认使用 Playwright Chromium，也可通过 `PLAYWRIGHT_CHANNEL=chrome` 使用已安装的 Chrome（PowerShell：`$env:PLAYWRIGHT_CHANNEL='chrome'`）。覆盖桌面/390px、窄屏滚动、同 step 双系列、记录替换/追加、零值及空态切换；截图保存在被忽略的 `frontend/test-results/loss-chart-*`。交接范围见 [M4-04a B 日志](../docs/worklogs/2026-11-04-m4-04a-b.md)。

M3 的分工和验收见 [完整开发计划](../docs/m3-development-plan.md)，正式请求/响应见 [任务 API](../docs/api/tasks.md)。M3-05 在原有列表交付上补齐：有 error.task_id 时只查询原任务；网络中断等没有 ID 的不确定结果不自动重发，用户可点击“确认原提交”，使用冻结的配置与原键调用服务端去重。若原记录存在，服务端返回 200 且不重新派发；若未保存，则此请求才创建任务。只有明确点击准备新任务才清除意图，下一次提交生成新键；放弃未知提交会提示可能重复。

提交前先保存意图，响应后保存任务 ID。刷新不会 POST，进入任务页可自动查询最近提交的 ID；存储不可用时显示保存提醒。sessionStorage 仅覆盖当前标签页会话，不提供跨设备或关闭标签页后的恢复。列表保留原有筛选/分页/竞态保护，历史小交付说明见 [列表测试](testing/m3-task-list.md)，本次完整接通证据见 [B 交付日志](../docs/worklogs/2026-11-03-m3-05-b.md)。共享入口/计划由 A 收录该日志，不代改 A 文件。

以下列出 M1/M3 已接通字段及 M4-04/05 已接入的观测/下载契约；M5 推理字段仍待其阶段确认：

| 接口                   | 当前前端读取                                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| GET tasks              | 分页对象 items、total；发送 page、page_size=20                                                                       |
| POST tasks             | dataset_id、base_model、config；发送 Idempotency-Key，读取 id；专用提交错误读取 error.task_id                           |
| GET tasks/{id}         | id、status、current_step、total_steps、progress、created_at、started_at、finished_at、error_code、error_message、config |
| GET tasks/{id}/metrics | 正式 MetricsPage：cursor/source_id/limit 查询；校验、合并 kind/step/loss/offset，终态补页与窗口提示已接入                 |
| GET tasks/{id}/logs    | 正式 LogsPage：lines、source_state、truncated、tail_incomplete、filtered_lines；tail=100，尾部/告警/滚动交互已接入        |
| GET tasks/{id}/adapter | 200/application/zip 和固定 UUID 文件名；ErrorResponse/Retry-After、完整 blob 取消/超时、错误体不保存已接入              |
| POST inference         | 读取 generated_text、text 或 output 字符串                                                                           |

若实际响应不同，修改 `src/api.js`、`src/workspace.js` 及对应页面的读取函数；本次未修改后端、Worker、Trainer、共享 Schema 或 docs 契约。

## 验证范围

M3-07 的 B 侧只读材料复核、真实快照页面复查命令见 [独立复核说明](testing/m3-07-review.md)。本轮已校验接收的 ZIP/62 项文件摘要，复核真实九任务/五组可读截图和十份 trace，并在原生产页面/快照 SQL 上通过桌面、390px 与手机交互检查；详见 [B 验收记录](../docs/worklogs/2026-11-04-m3-07-b.md)。这些入口不重跑 GPU、不改原证据、不自行宣布双方人工联调或全阶段共同收口。

`npm test` 检查错误语义、断网/超时与不重复 POST、FormData 字段、上传结果不确定性、参数边界、各页面无后端时的服务端渲染、HTML 转义、能力发现与真实 Loss 绘制。测试中的网络和数据为隔离替身，不出现在产品界面。

浏览器检查使用真实 TCP API、运行时 OpenAPI、临时 SQLite 与数据文件；Publisher 是仅测试使用的受控替身，进度/失败事件显式标记为合成事件。确认丢失用真实 POST 保存后丢弃响应，再验证同键找回原任务。不会启动业务 Redis、Worker 或 GPU，也不向产品注入模拟任务。M3-07 仍须用真实 Redis/Worker/GPU 完成服务链路验收。

2026-10-21：前端初次交付时，18 项自动检查与生产构建通过，受保护的后端/调度/训练/共享文档无修改。浏览器工具的访问策略阻止本地页面读取，因此未完成浏览器视觉验收与真实服务联调。同日正常合并成员 A 的 M1-03 更新后，再次通过全部 18 项检查与生产构建；同步记录见 docs/worklogs/2026-10-21-m1-04-frontend.md。


## 2026-10-22 接续与浏览器回归

保留初版组件与界面，局部修复 workspace.js 中上传后刷新被旧请求丢弃的问题，以及数据集面板/表格的移动端横向溢出。当前 22 项前端检查、8 项真实 Chromium 场景及生产构建通过，详见 [接续日志](../docs/worklogs/2026-10-22-m1-04-integration.md)。

首次准备浏览器测试（需要安装浏览器及 Linux 运行依赖；安装系统依赖时终端可能要求 sudo）：

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

已有浏览器依赖时可只运行 `npx playwright install chromium`。中文截图另需系统中文字体。仅使用 npm test/build 不需要浏览器或新增系统依赖。

浏览器测试自动启动独立 API（18000）及 Vite（15173），API 使用临时 SQLite/文件目录，退出清理；端口被占用时直接报错，不复用业务实例。API 启动器为 testing/serve_task_api.py，仅这个测试进程安装控制路由，生产 create_app 不变。默认用 uv run --locked python；可用 LLMCLOUD_TEST_PYTHON 指定已同步锁定依赖的 Python 命令，用 PLAYWRIGHT_CHANNEL=chrome 使用本机 Chrome。报告、截图和 trace 输出到被 Git 忽略的 test-results。需要只回归 M3 可运行 `npm run test:e2e -- tasks.spec.mjs`。


## M1-05 故障回归

2026-10-22 增加隔离的故障注入与边界场景，当前浏览器总计 19 项。测试配置显式使用 `serve_test_api.py --faults`，通过一次性测试控制触发磁盘/数据库/内部异常，核验真实错误与失败清理；这些入口只存在于临时服务，正常后端没有测试路由。产品组件没有新增 mock 或故障开关。验收矩阵见 [M1 检查](../docs/testing/m1-acceptance.md)。

GitHub CI 自动执行后端、前端测试与构建及 Chromium 回归；失败 trace 保留 7 天，查看仓库 Actions。
