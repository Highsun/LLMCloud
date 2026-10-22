# M1 数据管理验收

日期：2026-10-22。范围：M1-01 至 M1-05；不包含真实模型训练或推理。入口为 [数据集契约](../api/datasets.md)。

## 已执行的场景

| 场景 | 验收证据 | 结果 |
| --- | --- | --- |
| 合法上传、哈希/统计/持久化、重复上传 | HTTP 测试；真实浏览器上传/详情/刷新 | 通过 |
| 空文件、错误 JSON、缺字段、非法类型/未知键、重复键、错误 UTF-8 | 共享扫描器/HTTP 测试；浏览器错误展示 | 通过 |
| BOM、CRLF、空白行、物理行号、末行无换行 | 共享扫描器/HTTP 测试 | 通过 |
| 文件恰好 50 MiB 与增加 1 byte、单行 1 MiB 边界 | HTTP 真字节边界、扫描器测试；浏览器预检稀疏超限文件 | 通过 |
| 无/伪造 Content-Length、multipart 总体上限、part 数量/字段重复 | ASGI 逐块测试；TCP 提前 413 冒烟 | 通过 |
| 原始文件名伪造相对/Windows 路径、扩展名/控制字符 | 服务/HTTP；浏览器经 API 上传路径名并读取详情 | 通过 |
| 磁盘不可写/满、缓存异常、数据库不可用/提交失败 | 服务/HTTP 故障测试；浏览器由测试服务注入真实异常 | 通过 |
| 提交已成功但确认丢失、提交结果未知、清理失败 | 服务测试与只读审计；不把未确认成功当作可删除文件 | 通过 |
| 断连、取消、磁盘缓存关闭、持久化线程关闭顺序 | HTTP/ASGI 与浏览器取消后核对资源 | 通过 |
| 错误状态/code/request_id、不泄漏正文/绝对路径/异常文本 | HTTP/浏览器断言，含 503/500 | 通过 |
| 故障后无新增行/临时/孤立文件，手动重试可恢复 | 浏览器失败前后 total 与只读审计 | 通过 |
| 分页、超大页码、固定排序、并发刷新、页大小 | HTTP 与浏览器 | 通过 |
| CORS、Location、Allow、OpenAPI 一致性 | HTTP/契约测试 | 通过 |
| 生产 API 无测试控制路由 | 独立生产应用工厂隔离测试 | 通过 |
| 代理 HTML 错误兜底 | 明确标识的浏览器 mock，仅验证客户端降级 | 通过 |
| 桌面与 390px 移动端交互、无 JS 异常/横向溢出 | M1-04 浏览器用例持续回归 | 通过 |

代码证据：[后端 HTTP](../../tests/test_dataset_http.py)、[扫描/服务](../../tests/test_dataset_service.py)、[迁移](../../tests/test_dataset_migration.py)、[生产隔离](../../tests/test_browser_isolation.py)、[浏览器交互](../../frontend/e2e/datasets.spec.mjs)、[浏览器故障](../../frontend/e2e/dataset-failures.spec.mjs)。

本机结果为 **62 项后端、22 项前端、19 项 Chromium 浏览器检查及生产构建通过**。后端另在新建的 CPU-only uv 环境中执行，不依赖已安装的 training extra。GPU 训练、云服务器磁盘实际填满及其他浏览器不属于本次证据；故障由隔离服务确定性注入，生产代码没有故障开关。

## 重现与 CI

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/export_dataset_contract.py --check
uv run --locked python scripts/check_dataset_http.py
bash scripts/export_requirements.sh
git diff --exit-code -- requirements.txt trainer/requirements.txt

cd frontend
npm ci
npm test
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

浏览器测试服务必须使用临时库，不复用业务端口。只有 `scripts/serve_test_api.py --faults` 才装载测试控制路由，默认服务与 `backend.app.main:app` 没有这些路由；不部署该脚本。故障一次性消费，失败后核验存储并显式重试。

[GitHub Actions](../../.github/workflows/ci.yml) 在 push、PR 或手动触发时运行 CPU 依赖同步、后端/契约/HTTP、导出漂移检查、前端测试/构建和浏览器测试，失败时保留 7 天 trace。无需 GPU、模型权重、Redis 服务或仓库凭据。远端任务实际结果以 [Actions 页面](https://github.com/Highsun/LLMCloud/actions) 为准，配置已提交不代表远端已经成功运行。

参考：[Playwright CI](https://playwright.dev/docs/ci-intro)、[setup-uv](https://github.com/astral-sh/setup-uv)。
