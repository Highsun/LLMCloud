# M4-01 B 侧观测契约消费者核对

日期：2026-11-05（Asia/Shanghai）。用户明确要求接续完成 M4-01；按既定分工，本轮为 B 侧消费者核对。A 的 CPU 类型/生成物、02 指标/日志和 03 下载已交付。本轮结论：**正式观测契约 1.0.0 可供 B 接续实施，未发现需要调整 wire 字段/错误/版本的阻塞差异；B 独立核对已完成，待 A 收录反馈。** 生产观测/下载控制器仍待 04/05，不将契约核对当作页面联调验收。

## 同步、证据与改动范围

起点 feature/m4-observability-ui=4154550，工作区干净。实际 fetch 成功，origin/main=f57c403、origin/feature/m4-observability-ui=4154550，无新增队友提交。已阅读 AGENTS、project-plan/memory、M4 计划 1.3、正式观测契约末节六项清单、A 的 01/02/03 日志，以及实际 CPU 类型/常量、生成物、TasksPanel、request、能力探测和 LossChart。

正式输入来自 docs/contracts/observability.schema.json、docs/examples/observability 中 27 个生成 fixture/索引，以及 docs/api/tasks.openapi.json。样例标明 mock=true/http_evidence=false；测试中的记录、UUID、游标/字节数只证明格式可消费，不作为真实训练/网络验收数据。

仅新增 frontend/tests/observability-contract.test.mjs、本独立日志，更新 frontend/README.md。未修改 A 的后端/SQL/迁移/共享类型/正式文档/生成物/依赖，也未改 Trainer/Worker、原 04a 图表或产品请求逻辑。共享 AGENTS/计划/日志索引由 A 收录，不在本轮代签联合收口。

## 按契约末节六项逐项确认

| 清单 | 本轮实际核对与结论 | 接续责任 |
| --- | --- | --- |
| 1. source_id/cursor/offset | 用正式两页查询/响应经原 request 消费：首批 cursor=0，下一批使用返回 source_id 和 next_cursor=304；第二页首条 offset=304。隔离演练按 source_id/offset 合并/重放保留 4 条、两种 kind，offset=0 合法；旧 Map(step) 同样例只剩 2 条。 | 04 替换 after_step/Map(step)，来源变更明确清空旧源后重新读取，不混合曲线。 |
| 2. 空源/EOF/半行/零值 | 分别读取 not_created、ready 空文件、COMPLETED 空页和 FAILED 半行样例；终态空页仍保留 next_cursor=602。用原图表渲染正式页/零值/半行前完整点，零 Loss 和 learning_rate=0 不因 truthy 判断消失。 | 04 把业务状态/源状态/读取错误分别展示，保留已取得的完整记录，半行不推进游标。 |
| 3. 错误及日志告警 | 8 个 ErrorResponse fixture 经原 request 均保留 code、真实 HTTP status、request_id；GET 错误不标为提交结果未知。LogsPage 保留 source_state、lines 和 truncated/tail_incomplete/filtered_lines，能够分别表达三类告警；failure 不提供自由 message，说明从 TaskDetail 取。 | 04 对 METRICS_CURSOR_INVALID 做有界重置；日志只做文本渲染，替换尾部快照并展示告警，不改任务状态。 |
| 4. 最新 train/读取预算 | 正式双页四点直接输入 04a，最新 train=0.75、eval=1.0，图表保留两系列。x-limits 明确 2000ms、每轮至多 5 页、最近 10000 条；EOF 空数组不要求替换已有记录。 | 04 在 TaskDetail 终态后继续耗尽 has_more 并读取最终日志；有界补拉/展示窗口需实际实现并提示。 |
| 5. 下载 HTTP/身份/取消 | adapter-headers 的 usage 是 header_description_not_json_body；真实导出 OpenAPI 的 200 为 application/zip/binary，参数为空，Content-Disposition 固定 llmcloud-adapter-{UUID}.zip，忙时 Retry-After=2。契约足以固定点击时任务身份并定义 MIME/错误/取消范围。 | 05 实现专用下载生命周期，成功 MIME 核对、固定文件名、blob 全程 timeout/abort 和重复点击保护。现 helper 的实测差异见下表。 |
| 6. 内部 DTO/兼容能力 | CompletedArtifactSpec 是内部快照，原 validateTaskDetail 会以 INVALID_RESPONSE 拒绝；不得作为页面状态。原 supports 能识别真实 OpenAPI 三条 GET，仍保留 M1/M3 路径参数名归一规则；无路径时即使 fixture 存在也不启用能力。 | 04/05 沿用原 M1/M3 签名及运行时发现，不添加产品 mock 或使用内部 DTO 推测成功。 |

额外确认：不能在 JavaScript 中将返回记录 JSON.stringify 后自行重算字节游标。Python 源事件的 0.0/1.0 与浏览器再序列化的 0/1 字节不同；本轮用 TextEncoder 实测重编码总量不等于正式 next_cursor=602。客户端必须原样使用服务返回的 next_cursor，不以 step、数组长度、字符串长度或重序列化字节数替代。

## 已发现的前端差异（明确留给 04/05）

| 位置 | 当前行为与契约差异 | 判定 |
| --- | --- | --- |
| TasksPanel.readDetail | after_step 查询、Map(step) 合并；未校验正式整页及请求相关字段，不保存 source_id/cursor。 | 04 必改；当前两类同 step 会丢点，后续 after_step 会被正式接口拒绝。 |
| TasksPanel 详情轮询 | COMPLETED/FAILED 后停止 readDetail，也没有独立补页控制器。 | 04 必改；TaskDetail 终态不等于指标已读完，has_more 必须继续消费并最终取日志。 |
| TasksPanel 最新 Loss 卡片 | 使用 metrics.at(-1)，尾条 eval 会覆盖“最新训练值”的含义；只有 04a 图例已正确区分。 | 04 必改；卡片取最后 train。 |
| TasksPanel 日志读取/展示 | 仅读取 lines 文本，丢弃 source_state 和三类告警，尚无查看历史时的滚动控制。现模板为插值 pre，保持该文本安全方式。 | 04 必改；未知/非法整页报 INVALID_RESPONSE，不猜字符串/logs 两套格式。 |
| TasksPanel.download | await 后用 selected.id 命名，没有固定点击时请求身份，切任务可能污染名称/错误。 | 05 必改；捕获 UUID/序号，取消旧请求并隔离成功/失败/finally。 |
| api.request raw=blob | return response.blob() 后 finally 提前清 timeout/abort 监听，未校验成功 MIME；ApiError 未保留 Retry-After。 | 05 必改；可使用专用 helper，直接读取头，并使整个 body 消费期间取消/超时有效，不改变旧 JSON 调用。 |

最后一项已独立复现：以隔离 fetch 替身返回“头已到达、blob 尚未完成”的响应，随后触发调用者 AbortController。实测 caller_aborted=true、transport_aborted=false、full_blob_cancel_gap=true；释放模拟 body 后请求仍完成。该实验只用于确认已知生命周期差异，没有真实网络/下载/GPU，也没有把错误行为固化成预期通过的回归测试。修复及正向行为测试属于 05。

以上差异均为旧前端接续工作，不要求改后端契约；不因这些尚未实施的行为伪称 04/05 已验收。正式文档“共同约定与执行边界”的完成 DTO 行仍含“03 待检查”旧措辞，而后文/实际 03 已交付；此为 A 可收尾的文案差异，无 wire 影响，本轮保留原共享文件。

## 验证与复跑

```text
仓库根目录：
.venv-worker-tests\Scripts\python.exe scripts/export_observability_contract.py --check

frontend 目录：
node --test tests/observability-contract.test.mjs
npm.cmd test
npm.cmd run build
```

本机使用已有 Windows Python CPU 环境，无新增依赖或 uv.lock 改动；跨机器标准导出检查仍为 uv run --locked python scripts/export_observability_contract.py --check。

观测生成物 --check 通过；新增 12 项独立消费者检查通过，覆盖全部 27 个样例，实际调用原图表、request、TaskDetail 校验及能力探测。完整前端 76 项检查全部通过（原 64 + 本轮 12），生产构建通过，git diff --check 通过。请求返回为明确 fixture 替身；分页 Map 仅是隔离消费演练，未安装到产品控制器。未执行真实 HTTP/Redis/Worker/GPU、真实 ZIP 下载或联合验收。

核对完成后再次 fetch 成功，origin/main 仍为 f57c403、功能分支仍为 4154550，无新增队友提交。已有后端/共享类型/契约/生成物和产品源码没有本轮差异。

## 反馈与下一步

B 确认当前 1.0.0 的字段/边界/错误可以支撑 04/05，无需另建私有响应或调整共享版本。请 A 收录本日志并确认接续差异；M4-01 的双方登记由 A 汇总，B 不修改共享完成勾选。下一项为 M4-04 观测控制器/日志，再做 05 下载；06/07 的实际 HTTP/GPU 及 M3 人工剩余项继续保留。用户验收本地交付后明确授权将本次测试、frontend 使用说明及本日志共三个文件提交并推送至 feature/m4-observability-ui，供 A 收录审查。
