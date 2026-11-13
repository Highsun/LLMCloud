# M5 推理契约消费者核对与页面接入（B）

日期：2026-11-13（Asia/Shanghai）。用户根据 A 的交接授权完成现有推理页对接。起点 `d463116`，已包含 B 的 `cd0f493` 本地测试/语料交接；工作区初始干净。

## 范围与结论

读取 [在线推理草案 0.1](../api/inference.md)，接受 `mode=compare` 和 `base/adapter` 结构、两种 409 的独立错误码，以及 120 秒前端等待和切任务取消语义。详细核对、复跑和真实联调步骤见 [前端交接](../../frontend/testing/m5-inference.md)。这是 B 消费者确认，正式版本由 A 汇总，不修改共享草案。

修改现有 InferencePanel、局部样式，新增独立 inference.js：已完成任务独立分页/刷新、模式选择、Unicode 字符与 1–256 token 校验、同问题双回答/真实 token/模型 revision 展示、按错误码提示并手动重试。取消/超时覆盖响应头及 JSON body；切任务/模式、离开缓存页面和停止等待立即使旧请求失效，旧 success/error/finally 不影响新请求。取消仅表示停止浏览器等待，GPU 可能仍在清理。

生产能力探测保留，未发布运行时 OpenAPI 端点时不能生成。草案 JSON fixture 及独立 Playwright 路由 mock 仅用于测试，不进入页面运行路径。不修改 backend、SQL/迁移、共享类型/依赖、Worker 调度、Adapter 加载或部署配置；不新增 Actions。实现完成后用户要求提交并交接，交付到现有 B 分支 `feature/m4-observability-ui`，不更新 main 或 A 的契约分支。

## 验证结果

- Windows Node v24.13.1，`npm test`：135/135 通过，含新增 19 项推理控制器/传输/样例检查；原 116 项前端回归保留。
- `npm run build`：成功。
- 已有 Edge、仅本机 Vite、全部 API 拦截的草案 mock 浏览器：最终 9/9 通过。初轮 7/8，失败原因是测试误写了现有数据页标题，修正为实际“数据集”并新增模式切换检查后通过；未为此修改数据页。
- 桌面/390px mock 截图已查看，无横向页面溢出；截图在移动侧栏过渡结束后采集。
- 请求竞争的行为检查包括取消后同任务重试、旧成功/失败/finally、新任务结果身份核对、headers/body 超时，以及取消后传输迟到。无自动重试。

完整 mock 报告与截图保存在本机 `E:\LLMCloud\data\acceptance\b-review\m5-inference-mock-20261113-final\`，不是远程附件或真实推理证据。D 盘只保留代码/说明/结果摘要。

## 待交接

A 继续负责正式契约/HTTP/API、推理请求生命周期与 GPU 调度、Adapter 审计与加载。端点发布后先核对运行时 OpenAPI，再按前端交接在 RTX 3060 验证真实 base/adapter、真实训练忙碌与空闲后重试、取消/超时后可继续使用。目前未做真实推理、服务端取消或云端部署验证，不改变 M3/M4 双方验收状态，不把样例回答写成效果实验。

共享工作日志索引与里程碑由 A 在审查时收录，本次只新增 B 自有记录。提交前重新 fetch 成功，main 和推理契约分支均没有新提交，B 远端分支仍为 cd0f493；暂存范围仅限本轮前端代码、mock 检查与 B 文档。具体提交号和推送结果以 Git 历史及远端核验为准。
