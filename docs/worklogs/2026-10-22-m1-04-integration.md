# M1-04 前端接续开发与验收日志

日期：2026-10-22。成员 A 侧 Codex，接续成员 B 已交付的页面。状态：M1-04 上传/列表/详情功能通过浏览器验收；M1-05 全量故障联调与 CI、M1-06 正式数据准备仍待完成。

## 一、阅读与基线

工作区起点为干净的 main，HEAD 为 `65fb120`，fetch 后远端一致。阅读成员 B 的 `5665ef2`（前端 demo）、`5114741`（正常合并 M1-03）、`65fb120`（交付日志和文档）及 [成员 B 日志](2026-10-21-m1-04-frontend.md)，再核对组件、API 层、workspace、现有测试与 M1 数据集契约。

成员 B 已完成六页 Vue 工作台、数据集上传/分页/详情、错误和取消提示、LoRA 草稿及后续阶段界面。原日志明确记录 18 项检查与构建通过，真实浏览器验收待进行。因此本次从接入与验收补缺，不重新实现已有页面。项目全局梳理见 [项目记忆](../project-memory.md)。

## 二、实际修复及影响

| 位置 | 原因与变更 |
| --- | --- |
| `frontend/src/workspace.js` 的 loadDatasets | 原先 datasetLoading=true 时直接返回，会丢弃上传成功触发的第一页刷新。改为取消旧 GET、递增请求序号，只允许最新请求更新资源、错误和加载状态 |
| `frontend/src/style.css` 的数据集面板/表格容器 | 390px 浏览器发现横向溢出。为数据集 grid 子面板增加 min-width:0，为 table-scroll 增加 position:relative，避免长表格和绝对定位的隐藏表头撑出视口；保留表格内横向滚动 |

新增竞态测试在修复前出现 3 项预期失败（第二次读取未执行），修复后全部通过；浏览器同样验证上传过程中存在旧列表请求时，新资源能够立即显示。移动端最初失败报告显示 scrollWidth=447、viewport=390，定位到隐藏表头，修复后满足文档宽度不超过视口。

没有修改任何 Vue 组件、导航结构、配色、页面功能布局、api.js、训练参数适配，也没有修改 backend/Trainer/Worker、共享字段或错误语义。生产代码仅两个文件发生局部变化，接口契约版本仍为 1.0.0。

## 三、可重复的测试入口

- `frontend/tests/datasets.test.mjs`：4 项并发读取/失败恢复测试，追加到现有 npm test；独立测试关闭 WebSocket，避免与原渲染测试争用 HMR 端口。
- `frontend/e2e/datasets.spec.mjs`、`playwright.config.mjs`：8 项真实 Chromium 场景，经 Vite 代理调用 FastAPI；单 Worker、无自动重试。
- `scripts/serve_test_api.py`：启动应用工厂，使用 TemporaryDirectory 内的 SQLite 和数据目录；固定测试端口 18000，前端测试端口 15173。已占用时直接失败，禁止复用实际业务服务。退出释放临时存储。
- `frontend/package.json/package-lock.json`：新增锁定的 @playwright/test 1.64.1 与 test:e2e 命令，已有 Vue/Vite 版本保持；.gitignore 排除浏览器报告、截图和 trace。

浏览器覆盖：真实合法上传、SHA-256/文件大小、只读详情、页面刷新后持久化；缺字段返回真实 422、物理行号与 request_id；本地空文件/错误扩展名预检；真实上传生成的分页数据及顺序/页大小；并发列表刷新；取消等待后核对已经保存的数据、无自动重传；断网恢复；移动端导航、上传、详情和宽度检查。取消与并发场景使用浏览器网络闸门延迟真实上游响应，不伪造成功资源。

## 四、验证结果与本机浏览器条件

```bash
# 仓库根目录
uv run --locked python -m unittest discover -s tests -q
uv run --locked python scripts/export_dataset_contract.py --check
uv run --locked python scripts/check_dataset_storage.py --verify-hash

# frontend 目录
npm test
npm run build
npm run test:e2e
```

结果：**61 项后端、22 项前端、8 项浏览器检查通过，生产构建通过，OpenAPI 检查无漂移**。22 项前端包含成员 B 原有 18 项及本次 4 项。所有自动化上传使用临时业务库，未向本机实际业务库写入测试资源。截图与 trace 位于被忽略的 frontend/test-results。

本机最初缺少 Chromium 的 libnspr4/libnss3/libasound，浏览器未启动，不是页面失败。通过 Ubuntu APT 元数据获取包地址，HTTPS 下载并核对官方 SHA512 后，仅解压到 `/tmp/llmcloud-browser-libs`；未调用 sudo 或变更系统安装。浏览器下载到 `/tmp/llmcloud-playwright-browsers`。中文截图读取已有 Windows 微软雅黑，临时 Fontconfig 配置位于 `/tmp/llmcloud-browser-fonts`。本机执行使用：

```bash
FONTCONFIG_FILE=/tmp/llmcloud-browser-fonts/fonts.conf \
LD_LIBRARY_PATH=/tmp/llmcloud-browser-libs/root/usr/lib/x86_64-linux-gnu \
PLAYWRIGHT_BROWSERS_PATH=/tmp/llmcloud-playwright-browsers npm run test:e2e
```

这些是临时验证条件，不是跨机器配置。新开发机器先按 frontend/README.md 安装 Playwright 浏览器和系统依赖；需要可读中文截图时准备中文字体。浏览器目录与运行库没有提交到 Git。

已查看 1440px 桌面及 390px 移动端中文截图；保留成员 B 的现有设计，页面与数据表可使用。当前验证仅为 Chromium 及移动视口，不代表已覆盖 Firefox/WebKit、手机系统或所有故障组合。

## 五、交接

M1-04 功能与本次浏览器场景通过；后续 M1-05 继续统一执行服务不可用/磁盘/数据库故障、大小边界、完整浏览器回归及轻量 CI，M1-06 准备真实数据来源、划分与固定测试问题。完成 M1 后再进入 M2，不将训练配置/任务/推理页面的存在当作对应服务完成。

组员后续修改数据集读取时保留“最新请求更新状态”的规则，特别是上传成功必须重新查询第一页。修改表格容器时同时检查隐藏无障碍文本与窄视口；不要通过隐藏整页横向溢出掩盖表格无法操作的问题。测试服务器只能使用临时目录，不能改成直接写默认 data/。

测试基础依据：[Playwright 多服务启动](https://playwright.dev/docs/test-webserver)、[浏览器安装与运行依赖](https://playwright.dev/docs/browsers)。
