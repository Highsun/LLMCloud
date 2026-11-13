# M5 推理页草案对接（B）

日期：2026-11-13。契约基线为 `d463116` 的 [inference.md](../../docs/api/inference.md) 0.1 草案。这里记录前端对接，不代表 HTTP/Worker/真实 GPU 已实现或联合验收通过。

## 字段核对结论

- 接受 `mode=adapter|compare` 和嵌套 `base/adapter` 结构。页面默认选择 compare，显式提交 mode；adapter 模式要求 base=null，不沿用旧的顶层 text/output 别名。
- 每份回答显示 generated_text 和 generated_tokens；保留请求时的 prompt、task_id，展示 base_model、固定 model_revision、input_tokens 和 max_new_tokens。compare 不展示部分成功，必须收到两份完整且身份匹配的结果。
- 请求只有 task_id/prompt/max_new_tokens/mode 四字段。任务须为 UUIDv4；提示词去空白后非空、原文保留、按 Unicode 码点计数最多 8192；输出为 1–256 整数，JSON 字节预算为 64 KiB。2048 模板输入 token 上限交给后端校验，不在浏览器猜 token 数。
- 两种 409 可以分别表达：`GPU_BUSY` 提示等待并手动重试；`ARTIFACT_NOT_READY` 提示训练未完成并刷新选择。其他状态和错误码不统一改写成忙碌。字段 details、截断标记和 request_id 沿用 ErrorNotice 展示。
- 接受浏览器 120 秒、服务端草案 90 秒的等待预算。超时/网络错误不自动 POST 重试，保留用户输入。不显示任务创建接口的“保存结果不确定”提示。
- 切换任务或模式、停止等待、离开 KeepAlive 缓存页面均取消当前等待并使请求序号失效。旧成功/失败/finally 不覆盖新请求。取消等待不承诺 GPU 已停止或释放。
- 已完成任务在本页通过 `GET /tasks?page=...&page_size=20&status=COMPLETED` 独立查询、刷新和分页，不改变训练任务页的筛选/页码。翻页清除原选择；刷新后原任务不在本页时也清除选择。
- 生产页面继续以运行时 OpenAPI 中 `POST /api/v1/inference` 为启用条件；未发布接口时按钮禁用。mock 不进入生产组件，没有假回答或假任务回退。

## 自动验证

在 frontend 目录运行，沿用已有锁定依赖，不新增依赖或 workflow：

```bash
npm test
npm run build
```

新控制器测试为 `tests/inference.test.mjs`。`tests/fixtures/inference-draft.json` 标记 mock，三个 JSON 对象与草案示例逐项一致，并有漂移检查。其他任务、错误和 adapter-only 响应只用于测试场景。

浏览器入口（全部 HTTP API 由 Playwright 拦截，不启动后端/Redis/Worker/GPU）：

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:LLMCLOUD_INFERENCE_TEST_OUTPUT='E:\LLMCloud\data\acceptance\b-review\m5-inference-mock-20261113-final'
node node_modules\@playwright\test\cli.js test --config playwright.inference.config.mjs
```

其他机器应把输出目录换成自己的运行盘，安装了 Playwright Chromium 时可省略 PLAYWRIGHT_CHANNEL。实际 mock 浏览器证据最终存于上述 E 盘目录；源码、测试说明及结果摘要在 D 盘，截图/trace/完整报告不纳入 Git。

本机 Node v24.13.1 / Windows 已有 Edge：135 项前端测试通过（含新增 19 项），生产构建通过；9 项浏览器检查通过。浏览器覆盖 compare 双回答和 metadata、adapter-only、文本转义、两种 409 和重试、任务切换、取消/缓存页切换、21 条分页、接口未发布禁用、模式切换。390px 页面检查无横向溢出，桌面/窄屏截图已人工查看。

控制器另外验证 headers/JSON body 两阶段的超时和取消（含传输忽略 AbortSignal）、旧成功/失败/finally 隔离、同任务取消后重试，以及 Unicode/参数/响应身份校验。浏览器 mock 的取消检查验证页面交互；不冒充服务端取消或 GPU 清理验证。

## 接口上线后的真实联调

1. A 发布实际推理路由和运行时 OpenAPI 后，先同步并核对字段/错误语义有无变化；草案 0.1 尚非正式契约版本，发生变化先对齐。
2. 在现有 E 盘 WSL/RTX 3060 环境使用已审计、模型 revision 匹配的完成任务。页面选择 compare，记录真实两份输出、token 数、revision、请求编号和耗时；再检查 adapter-only。
3. 启动真实训练占用或排队，推理应返回 GPU_BUSY；输入保留且不自动重发。GPU 空闲后由用户点击重试，确认成功。
4. 用未完成任务请求验证 ARTIFACT_NOT_READY（页面只列完成任务，需 A 提供受控 API 检查或状态变化场景）；不要为了制造错误放宽生产任务筛选。
5. 验证真实等待中的切任务、取消、离页和超时；确认旧结果不串任务，GPU 清理后可以继续使用。前端取消与 Worker 释放需分别取证。
6. D 盘保存小型结果/交接摘要，完整日志、模型、数据库与生成产物留在 E 盘。双方实际操作后分别确认结果，不提前标记 M3/M4 联合验收、M5 真实推理或云部署完成。
